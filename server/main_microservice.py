"""
Match Server using independent Game Service microservice.

This version communicates with the Game Service via HTTP REST API
instead of directly importing game physics.
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from game_service_client import GameServiceClient

# ==== Configuration ====

TICK_RATE = 60.0
STATE_BROADCAST_INTERVAL = 1 / TICK_RATE
GAME_SERVICE_URL = "http://localhost:8001"  # Game Service endpoint


# ==== Data Models ====

class MatchStartRequest(BaseModel):
    mode: str = Field(pattern="^(pvp|pvai)$")
    player_id: str
    player_name: Optional[str] = None

    @field_validator("player_id")
    @classmethod
    def validate_player_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("player_id is required")
        return value


class PlayerRegistrationRequest(BaseModel):
    """Request model for player registration."""
    role: str = Field(pattern="^(player1|player2)$")
    player_id: str


class PlayerInputRequest(BaseModel):
    """Request model for player input submission."""
    role: str = Field(pattern="^(player1|player2)$")
    move: str = Field(pattern="^(left|right|jump|none)$")


# ==== Match Implementation ====

class Match:
    """
    Match manager that coordinates REST API polling with Game Service.
    """

    def __init__(
        self,
        match_id: str,
        mode: str,
        owner_id: str,
        player_name: Optional[str] = None,
        game_client: Optional[GameServiceClient] = None
    ):
        self.id = match_id
        self.mode = mode
        self.owner_id = owner_id
        self.player_name = player_name or owner_id
        self.players: List[str] = [
            owner_id,
            "ai" if mode == "pvai" else "player2",
        ]

        # Game Service client
        self.game_client = game_client or GameServiceClient(GAME_SERVICE_URL)

        # Create game instance in Game Service
        game_response = self.game_client.create_game(mode=mode, game_id=match_id)
        if "error" in game_response:
            raise RuntimeError(f"Failed to create game: {game_response['error']}")

        self.game_id = game_response["game_id"]

        # REST API state management
        self.lock = asyncio.Lock()
        self.running = True
        self.latest_payload = self._convert_state_to_payload(game_response["state"])
        self.registered_players: Dict[str, dict] = {}
        self.state_sequence: int = 0
        self.input_buffer: Dict[str, Tuple[str, float]] = {
            "player1": ("none", 0.0),
            "player2": ("none", 0.0)
        }

        self._loop_task = asyncio.create_task(self._run_loop())

    def _convert_state_to_payload(self, state: Dict) -> Dict:
        """Convert Game Service state format to client payload with extended rendering info."""
        ball = state["ball"]
        p1 = state["p1"]
        p2 = state["p2"]

        return {
            "type": "state",
            "player1": {
                "x": p1["x"],
                "y": p1["y"],
                "dive_direction": p1["dive_direction"],
                "state": p1["state"],
                "frame_num": p1["frame_num"],
            },
            "player2": {
                "x": p2["x"],
                "y": p2["y"],
                "dive_direction": p2["dive_direction"],
                "state": p2["state"],
                "frame_num": p2["frame_num"],
            },
            "punch": {
                "visible": ball["punch_effect_radius"] > 0,
                "x": ball["punch_effect_x"],
                "y": ball["punch_effect_y"],
            },
            "ball_hyper": {
                "visible": ball["is_power_hit"],
                "x": ball["previous_x"],
                "y": ball["previous_y"],
            },
            "ball_trail": {
                "visible": ball["is_power_hit"],
                "x": ball["pre_previous_x"],
                "y": ball["pre_previous_y"],
            },
            "ball": {
                "x": ball["x"],
                "y": ball["y"],
                "rotation": ball["rotation"],
            },
            "score": {
                "p1": state["score_p1"],
                "p2": state["score_p2"]
            },
        }

    def status_payload(self) -> Dict[str, object]:
        """Get match status."""
        # Get current state from Game Service
        state_response = self.game_client.get_state(self.game_id)
        if "state" in state_response:
            state = state_response["state"]
            score = {"p1": state["score_p1"], "p2": state["score_p2"]}
        else:
            score = {"p1": 0, "p2": 0}

        return {
            "match_id": self.id,
            "mode": self.mode,
            "state": "running" if self.running else "stopped",
            "players": self.players,
            "player_name": self.player_name,
            "score": score,
        }

    async def stop(self) -> None:
        """Stop the match and clean up resources."""
        async with self.lock:
            self.running = False
        self._loop_task.cancel()

        # Delete game instance in Game Service
        self.game_client.delete_game(self.game_id)

    async def restart(self) -> None:
        """Restart the match."""
        async with self.lock:
            # Reset game in Game Service
            reset_response = self.game_client.reset_game(self.game_id)
            if "state" in reset_response:
                self.latest_payload = self._convert_state_to_payload(reset_response["state"])

    # ---- REST API Methods ----

    async def register_player(self, role: str, player_id: str) -> dict:
        """Register a player for REST API polling."""
        if not self.running:
            raise HTTPException(status_code=410, detail="match finished")

        if role in self.registered_players:
            raise HTTPException(status_code=409, detail=f"{role} already registered")

        self.registered_players[role] = {
            "player_id": player_id,
            "registered_at": time.time(),
            "last_poll": time.time(),
            "last_input": time.time()
        }

        logging.info(f"[REST] Registered {role} ({player_id}) for match {self.id}")
        return {
            "result": "registered",
            "match_id": self.id,
            "role": role,
            "polling_interval_ms": 16  # 60 FPS
        }

    async def unregister_player(self, role: str) -> None:
        """Unregister a player from REST API polling."""
        if role in self.registered_players:
            player_info = self.registered_players.pop(role)
            logging.info(f"[REST] Unregistered {role} ({player_info['player_id']}) from match {self.id}")

    async def submit_input(self, role: str, move: str) -> dict:
        """
        Accept player input and buffer it for next game step.
        Inputs are consumed during _step_game().
        """
        if role not in self.registered_players:
            raise HTTPException(status_code=403, detail="player not registered")

        if move not in {"left", "right", "jump", "none"}:
            raise HTTPException(status_code=400, detail="invalid move")

        # Update input buffer
        self.input_buffer[role] = (move, time.time())
        self.registered_players[role]["last_input"] = time.time()

        return {
            "result": "accepted",
            "queued_at": time.time()
        }

    async def get_state(self, role: str, last_seq: Optional[int] = None) -> dict:
        """
        Get current game state for polling.

        Args:
            role: Player role requesting state
            last_seq: Last sequence number client received (for future optimization)

        Returns:
            Current game state with sequence number
        """
        if role not in self.registered_players:
            raise HTTPException(status_code=403, detail="player not registered")

        # Update last poll time (for connection tracking)
        self.registered_players[role]["last_poll"] = time.time()

        # Return latest state
        return {
            **self.latest_payload,
            "sequence": self.state_sequence,
            "timestamp": time.time()
        }

    # ---- Game Loop ----

    async def _run_loop(self) -> None:
        """Main game loop that steps the game at 60 FPS."""
        try:
            while self.running:
                start = asyncio.get_event_loop().time()
                await self._step_game()

                # Increment sequence number for REST API clients
                self.state_sequence += 1

                elapsed = asyncio.get_event_loop().time() - start
                await asyncio.sleep(max(0.0, STATE_BROADCAST_INTERVAL - elapsed))
        except asyncio.CancelledError:
            pass

    async def _step_game(self) -> None:
        """Execute one game step via Game Service."""
        # Always use REST input buffer
        p1_move, _ = self.input_buffer.get("player1", ("none", 0.0))
        p2_move, _ = self.input_buffer.get("player2", ("none", 0.0))

        # Only use p2 action if player2 is registered
        p2_action = p2_move if "player2" in self.registered_players else None

        # Call Game Service to step the game
        step_response = self.game_client.step_game(
            self.game_id,
            p1_move,
            p2_action
        )

        if "error" in step_response:
            print(f"Game step error: {step_response['error']}")
            return

        if "state" in step_response:
            self.latest_payload = self._convert_state_to_payload(step_response["state"])

        # Auto-reset jump inputs
        if p1_move == "jump":
            self.input_buffer["player1"] = ("none", time.time())
        if p2_action == "jump":
            self.input_buffer["player2"] = ("none", time.time())


# ==== FastAPI Setup ====

app = FastAPI(title="Pikachu Volleyball Match Server (Microservice)", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

matches: Dict[str, Match] = {}
game_client = GameServiceClient(GAME_SERVICE_URL)


@app.get("/health")
async def health():
    """Health check endpoint."""
    # Check Game Service health
    game_health = game_client.health_check()
    game_service_ok = game_health.get("status") == "ok"

    return {
        "status": "ok",
        "version": "2.0",
        "game_service": game_health,
        "game_service_connected": game_service_ok,
    }


@app.get("/system/status")
async def system_status():
    """Get system status."""
    # Get active games from Game Service
    games_list = game_client.list_games()

    return {
        "active_matches": sum(1 for match in matches.values() if match.running),
        "players_online": list({match.owner_id for match in matches.values()}),
        "game_service_games": games_list.get("games", []),
        "ai_available": True,
    }


@app.post("/match/start")
async def start_match(payload: MatchStartRequest):
    """Start a new match."""
    match_id = uuid.uuid4().hex[:8]

    try:
        match = Match(
            match_id=match_id,
            mode=payload.mode,
            owner_id=payload.player_id,
            player_name=payload.player_name,
            game_client=game_client
        )
        matches[match_id] = match

        return {
            "match_id": match_id,
            "mode": payload.mode,
            "player_name": match.player_name,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/match/{match_id}/status")
async def match_status(match_id: str):
    """Get match status."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    return match.status_payload()


@app.post("/match/{match_id}/stop")
async def stop_match(match_id: str):
    """Stop a match."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    await match.stop()
    return {"result": "terminated"}


@app.post("/match/{match_id}/restart")
async def restart_match(match_id: str):
    """Restart a match."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    await match.restart()

    # Get updated score
    state_response = game_client.get_state(match.game_id)
    if "state" in state_response:
        state = state_response["state"]
        score = {"p1": state["score_p1"], "p2": state["score_p2"]}
    else:
        score = {"p1": 0, "p2": 0}

    return {"result": "restarted", "score": score}


@app.get("/match/{match_id}/stats")
async def match_stats(match_id: str):
    """Get match statistics."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")

    # Get state from Game Service
    state_response = game_client.get_state(match.game_id)
    if "state" in state_response:
        state = state_response["state"]
        score = {"p1": state["score_p1"], "p2": state["score_p2"]}
    else:
        score = {"p1": 0, "p2": 0}

    return {
        "match_id": match.id,
        "mode": match.mode,
        "player_name": match.player_name,
        "score": score,
        "running": match.running,
        "registered_players": list(match.registered_players.keys()),
    }


# ==== REST API Endpoints for Polling ====

@app.post("/match/{match_id}/register")
async def register_player_to_match(match_id: str, request: PlayerRegistrationRequest):
    """Register a player to poll game state via REST API."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")

    result = await match.register_player(request.role, request.player_id)
    return result


@app.post("/match/{match_id}/unregister")
async def unregister_player_from_match(match_id: str, request: PlayerRegistrationRequest):
    """Unregister a player from match."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")

    await match.unregister_player(request.role)
    return {"result": "unregistered"}


@app.post("/match/{match_id}/input")
async def submit_player_input(match_id: str, request: PlayerInputRequest):
    """Submit player input to be processed in next game step."""
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")

    result = await match.submit_input(request.role, request.move)
    return result


@app.get("/match/{match_id}/state")
async def get_match_state(
    match_id: str,
    role: str,
    seq: Optional[int] = None,
    response: Response = None
):
    """
    Poll current game state via REST API.

    Query Parameters:
        role: Player role (player1 or player2)
        seq: Last received sequence number (optional, for future optimization)
    """
    match = matches.get(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match not found")

    # Disable caching to ensure fresh data
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    state = await match.get_state(role, seq)
    return state


def main():
    """Run the match server."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    print("=" * 60)
    print("Pikachu Volleyball Match Server (REST API Only)")
    print("=" * 60)
    print(f"Match Server will run on: http://0.0.0.0:8000")
    print(f"Game Service expected at: {GAME_SERVICE_URL}")
    print("\nMake sure Game Service is running first:")
    print("  cd game_service && python game_server.py")
    print("\nREST API polling at 60 FPS for real-time gameplay")
    print("=" * 60)

    uvicorn.run(
        "main_microservice:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
