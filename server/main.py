import asyncio
import math
import uuid
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


# ==== Game Constants ====

FIELD_WIDTH = 480.0
FIELD_HEIGHT = 270.0
NET_X = FIELD_WIDTH / 2
NET_WIDTH = 12.0
NET_HEIGHT = 180.0

BALL_RADIUS = 10.0
BALL_SPEED = 3.0

PLAYER_RADIUS = 18.0
PLAYER_HEIGHT = 42.0
GROUND_Y = FIELD_HEIGHT - PLAYER_HEIGHT
PLAYER_SPEED = 5.0
JUMP_VELOCITY = -9.0  # negative moves upward because gravity pulls down

GRAVITY = 0.5
TICK_RATE = 60.0
STATE_BROADCAST_INTERVAL = 1 / TICK_RATE


# ==== Data Models ====


class MatchStartRequest(BaseModel):
    mode: str = Field(pattern="^(pvp|pvai)$")
    player_id: str

    @field_validator("player_id")
    @classmethod
    def validate_player_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("player_id is required")
        return value


@dataclass
class PlayerState:
    x: float
    y: float = GROUND_Y
    vy: float = 0.0

    def to_payload(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass
class BallState:
    x: float
    y: float
    vx: float
    vy: float

    def to_payload(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "vx": self.vx, "vy": self.vy}


@dataclass
class GameState:
    ball: BallState
    p1: PlayerState
    p2: PlayerState
    score_p1: int = 0
    score_p2: int = 0

    def to_payload(self) -> Dict[str, object]:
        return {
            "type": "state",
            "ball": self.ball.to_payload(),
            "p1": self.p1.to_payload(),
            "p2": self.p2.to_payload(),
            "score": {"p1": self.score_p1, "p2": self.score_p2},
        }


def default_game_state() -> GameState:
    return GameState(
        ball=BallState(
            x=FIELD_WIDTH / 2,
            y=FIELD_HEIGHT / 3,
            vx=BALL_SPEED,
            vy=-BALL_SPEED / 2,
        ),
        p1=PlayerState(x=80.0),
        p2=PlayerState(x=FIELD_WIDTH - 80.0),
    )


# ==== Match Implementation ====


class Match:
    def __init__(self, match_id: str, mode: str, owner_id: str):
        self.id = match_id
        self.mode = mode
        self.owner_id = owner_id
        self.players: List[str] = [
            owner_id,
            "ai" if mode == "pvai" else "player2",
        ]
        self.state = default_game_state()
        self.inputs: Dict[str, str] = {"player1": "none", "player2": "none"}
        self.clients: Dict[str, WebSocket] = {}
        self.lock = asyncio.Lock()
        self.running = True
        self.latest_payload = self.state.to_payload()
        self._loop_task = asyncio.create_task(self._run_loop())

    # ---- public helpers ----
    def status_payload(self, ws_url: str) -> Dict[str, object]:
        return {
            "match_id": self.id,
            "mode": self.mode,
            "state": "running" if self.running else "stopped",
            "players": self.players,
            "ws_url": ws_url,
        }

    async def register(self, role: str, websocket: WebSocket) -> None:
        if role not in ("player1", "player2"):
            raise HTTPException(status_code=400, detail="role must be player1 or player2")

        async with self.lock:
            if not self.running:
                raise HTTPException(status_code=410, detail="match finished")
            if role in self.clients:
                raise HTTPException(status_code=409, detail=f"{role} already connected")
            self.clients[role] = websocket

    async def unregister(self, role: str) -> None:
        async with self.lock:
            self.clients.pop(role, None)

    async def stop(self) -> None:
        async with self.lock:
            self.running = False
        self._loop_task.cancel()
        # close connections
        for ws in list(self.clients.values()):
            await ws.close()
        self.clients.clear()

    async def handle_input(self, role: str, move: str) -> None:
        if role not in self.inputs:
            return
        if move not in {"left", "right", "jump", "none"}:
            return
        self.inputs[role] = move

    # ---- internal loop ----

    async def _run_loop(self) -> None:
        try:
            while self.running:
                start = asyncio.get_event_loop().time()
                self._maybe_drive_ai()
                self._apply_inputs()
                self._update_physics()
                await self._broadcast_state()
                elapsed = asyncio.get_event_loop().time() - start
                await asyncio.sleep(max(0.0, STATE_BROADCAST_INTERVAL - elapsed))
        except asyncio.CancelledError:
            pass

    def _maybe_drive_ai(self) -> None:
        if self.mode != "pvai":
            return
        # AI only controls player2 when no human connection supplied
        if "player2" in self.clients:
            return

        target_x = self.state.ball.x
        p2 = self.state.p2
        if abs(target_x - p2.x) <= PLAYER_SPEED:
            self.inputs["player2"] = "none"
        elif target_x < p2.x:
            self.inputs["player2"] = "left"
        else:
            self.inputs["player2"] = "right"

        # jump if the ball is descending over the AI
        if self.state.ball.y < p2.y and abs(self.state.ball.x - p2.x) < 30 and self._is_on_ground(
            p2
        ):
            self.inputs["player2"] = "jump"

    def _apply_inputs(self) -> None:
        self._apply_player_move(
            self.state.p1,
            self.inputs["player1"],
            left_limit=PLAYER_RADIUS,
            right_limit=NET_X - NET_WIDTH / 2 - PLAYER_RADIUS,
        )
        self._apply_player_move(
            self.state.p2,
            self.inputs["player2"],
            left_limit=NET_X + NET_WIDTH / 2 + PLAYER_RADIUS,
            right_limit=FIELD_WIDTH - PLAYER_RADIUS,
        )

    def _apply_player_move(
        self, player: PlayerState, move: str, left_limit: float, right_limit: float
    ) -> None:
        if move == "left":
            player.x -= PLAYER_SPEED
        elif move == "right":
            player.x += PLAYER_SPEED
        elif move == "jump" and self._is_on_ground(player):
            player.vy = JUMP_VELOCITY

        player.x = max(left_limit, min(right_limit, player.x))
        player.vy += GRAVITY
        player.y += player.vy

        if player.y >= GROUND_Y:
            player.y = GROUND_Y
            player.vy = 0.0
        elif player.y < 0:
            player.y = 0.0
            player.vy = 0.0

        # reset jump input so that jumps are discrete
        if move == "jump":
            self.inputs = {**self.inputs, "player1": self.inputs["player1"], "player2": self.inputs["player2"]}

    def _update_physics(self) -> None:
        ball = self.state.ball
        ball.vy += GRAVITY
        ball.x += ball.vx
        ball.y += ball.vy

        # walls
        if ball.x <= BALL_RADIUS:
            ball.x = BALL_RADIUS
            ball.vx = abs(ball.vx)
        elif ball.x >= FIELD_WIDTH - BALL_RADIUS:
            ball.x = FIELD_WIDTH - BALL_RADIUS
            ball.vx = -abs(ball.vx)

        # ceiling
        if ball.y <= BALL_RADIUS:
            ball.y = BALL_RADIUS
            ball.vy = abs(ball.vy)

        # net collision
        if (
            NET_X - NET_WIDTH / 2 - BALL_RADIUS < ball.x < NET_X + NET_WIDTH / 2 + BALL_RADIUS
            and ball.y > FIELD_HEIGHT - NET_HEIGHT
        ):
            if ball.x < NET_X:
                ball.x = NET_X - NET_WIDTH / 2 - BALL_RADIUS
                ball.vx = -abs(ball.vx)
            else:
                ball.x = NET_X + NET_WIDTH / 2 + BALL_RADIUS
                ball.vx = abs(ball.vx)

        # player collisions
        self._handle_player_collision(ball, self.state.p1)
        self._handle_player_collision(ball, self.state.p2)

        # scoring (touch ground)
        if ball.y >= FIELD_HEIGHT - BALL_RADIUS:
            scorer = "p2" if ball.x < NET_X else "p1"
            self._score_point(scorer)

    def _handle_player_collision(self, ball: BallState, player: PlayerState) -> None:
        px = player.x
        py = player.y + PLAYER_HEIGHT / 2
        dx = ball.x - px
        dy = ball.y - py
        distance = math.hypot(dx, dy)
        min_distance = BALL_RADIUS + PLAYER_RADIUS
        if distance >= min_distance or distance == 0:
            return

        # push the ball out along the collision normal
        nx = dx / distance
        ny = dy / distance
        overlap = min_distance - distance
        ball.x += nx * overlap
        ball.y += ny * overlap

        # basic reflection with added push from player's vertical velocity
        impact_force = 4.0
        ball.vx = ball.vx + nx * impact_force
        ball.vy = ball.vy + ny * impact_force + (-player.vy * 0.2)

    def _score_point(self, scorer: str) -> None:
        if scorer == "p1":
            self.state.score_p1 += 1
        else:
            self.state.score_p2 += 1
        self.state = default_game_state()

    async def _broadcast_state(self) -> None:
        payload = self.state.to_payload()
        self.latest_payload = payload

        stale_roles: List[str] = []
        for role, ws in self.clients.items():
            try:
                await ws.send_json(payload)
            except Exception:
                stale_roles.append(role)
        for role in stale_roles:
            await self.unregister(role)

    def current_state(self) -> Dict[str, object]:
        return asdict(self.state)

    def _is_on_ground(self, player: PlayerState) -> bool:
        return abs(player.y - GROUND_Y) < 1e-3


# ==== FastAPI setup ====

app = FastAPI(title="Pikachu Volleyball Server", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

matches: Dict[str, Match] = {}
matchmaking_queue: List[str] = []


def build_ws_url(request: Request, match_id: str) -> str:
    base = request.base_url._url.rstrip("/")
    if base.startswith("https"):
        ws_base = base.replace("https", "wss", 1)
    else:
        ws_base = base.replace("http", "ws", 1)
    return f"{ws_base}/ws/match/{match_id}"


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0"}


@app.get("/system/status")
async def system_status():
    return {
        "active_matches": sum(1 for match in matches.values() if match.running),
        "players_online": list({match.owner_id for match in matches.values()}),
        "queue": matchmaking_queue,
        "ai_available": True,
    }


@app.post("/match/start")
async def start_match(payload: MatchStartRequest, request: Request):
    match_id = uuid.uuid4().hex[:8]
    match = Match(match_id=match_id, mode=payload.mode, owner_id=payload.player_id)
    matches[match_id] = match
    ws_url = build_ws_url(request, match_id)
    return {"match_id": match_id, "mode": payload.mode, "ws_url": ws_url}


@app.get("/match/{match_id}/status")
async def match_status(match_id: str, request: Request):
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    return match.status_payload(ws_url=build_ws_url(request, match_id))


@app.post("/match/{match_id}/stop")
async def stop_match(match_id: str):
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    await match.stop()
    return {"result": "terminated"}


@app.websocket("/ws/match/{match_id}")
async def websocket_endpoint(websocket: WebSocket, match_id: str):
    match = matches.get(match_id)
    if not match:
        await websocket.close(code=4404)
        return
    await websocket.accept()

    try:
        register_msg = await websocket.receive_json()
    except Exception:
        await websocket.close(code=4400)
        return

    if register_msg.get("type") != "register":
        await websocket.close(code=4400)
        return

    role = register_msg.get("role", "")
    try:
        await match.register(role, websocket)
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "detail": exc.detail})
        await websocket.close(code=exc.status_code)
        return

    # push immediate state to new client
    await websocket.send_json(match.latest_payload)

    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "input":
                move = message.get("move", "none")
                await match.handle_input(role, move)
    except WebSocketDisconnect:
        await match.unregister(role)


def main():
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
