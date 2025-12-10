#!/usr/bin/env python3
"""
Independent Game Service for Pikachu Volleyball.

This microservice manages the game physics engine and state.
It runs separately from the Match server and communicates via HTTP REST API.

Architecture:
- Runs on port 8001 (configurable)
- Manages game instances using modified pykachu_env
- Provides RESTful API for creating, stepping, and querying games
- Supports both single-player (vs AI) and multi-player modes
"""

import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from posix import PRIO_DARWIN_BG
from typing import List, Optional, Union, final

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add game directory to path
game_dir = Path(__file__).parent.parent / "game"
sys.path.insert(0, str(game_dir))

# Change to game directory for asset loading
original_cwd = os.getcwd()
os.chdir(game_dir)

try:
    from pykachu_env import PykachuEnv
finally:
    os.chdir(original_cwd)


# ==== Data Models ====

class GameCreateRequest(BaseModel):
    """Request to create a new game instance."""
    mode: str = "pvai"  # "pvai" or "pvp"
    game_id: Optional[str] = None  # Optional custom game ID


class GameStepRequest(BaseModel):
    """Request to step the game forward."""
    p1_action: List[int]  # [x, y, power] action array
    p2_action: Optional[List[int]] = None  # For PvP mode


@dataclass
class GameState:
    """Current state of a game."""
    game_id: str
    ball: dict[str, float]
    p1: dict[str, float]
    p2: dict[str, float]
    score_p1: int
    score_p2: int
    terminated: bool  # True if ball hit ground this frame
    mode: str


# ==== Game Instance Manager ====

@final
class GameInstance:
    """Manages a single game instance."""

    # Frame rate limiting: 25 FPS = 0.04 seconds per frame
    TARGET_FPS = 25
    FRAME_TIME = 1.0 / TARGET_FPS  # 0.04 seconds

    def __init__(self, game_id: str, mode: str = "pvai"):
        self.game_id = game_id
        self.mode = mode
        self.score_p1 = 0
        self.score_p2 = 0
        self.last_step_time = time.time()

        # Create Gymnasium environment
        is_p2_ai = (mode == "pvai")
        self.env = PykachuEnv(
            is_player_1_computer=False,
            is_player_2_computer=is_p2_ai,
            render_mode="human"
        )

        # Reset environment
        self.env.reset()

        # Action array format reference:
        # [x, y, power] where:
        #   x: 0=left, 1=none, 2=right
        #   y: 0=none, 1=normal, 2=jump
        #   power: 0=normal, 1=power hit
        # Examples:
        #   [1, 1, 0] = none
        #   [0, 1, 0] = left
        #   [2, 1, 0] = right
        #   [1, 2, 0] = jump
        #   [1, 1, 1] = power hit
        #   [0, 2, 0] = jump left
        #   [2, 2, 0] = jump right

    def step(self, p1_action: List[int], p2_action: Optional[List[int]] = None) -> GameState:
        """
        Execute one game step with 25 FPS frame rate limiting.

        Args:
            p1_action: Player 1 action array [x, y, power]
            p2_action: Player 2 action array (optional, uses AI if None in pvai mode)

        Returns:
            Current game state
        """
        # Enforce 25 FPS frame rate limiting
        current_time = time.time()
        elapsed = current_time - self.last_step_time

        """
        if elapsed < self.FRAME_TIME:
            # Sleep to maintain 25 FPS
            sleep_time = self.FRAME_TIME - elapsed
            time.sleep(sleep_time)
        """

        # Update last step time
        self.last_step_time = time.time()

        # Use the provided action array directly
        action = p1_action

        # Log action if not "none"
        if action != [1, 1, 0]:
            logging.info(f"[GAME] Player 1 action: {action}")

        # TODO: For PvP mode, handle p2_action
        # Currently the environment manages AI internally

        # Step environment with the actual action
        obs, reward, terminated, info = self.env.step(action)

        # Update scores if someone scored
        if terminated:
            if self.env.physics.ball.punch_effect_x < 216:  # Left side
                self.score_p2 += 1
            else:  # Right side
                self.score_p1 += 1
            # Reset for next round
            self.env.reset()

        return self.get_state(terminated)

    def get_state(self, terminated: bool = False) -> GameState:
        """Get current game state with extended rendering information."""
        physics = self.env.physics
        return GameState(
            game_id=self.game_id,
            ball={
                "x": physics.ball.x,
                "y": physics.ball.y,
                "vx": physics.ball.x_velocity,
                "vy": physics.ball.y_velocity,
                "rotation": physics.ball.rotation,
                "punch_effect_x": physics.ball.punch_effect_x,
                "punch_effect_y": physics.ball.punch_effect_y,
                "punch_effect_radius": physics.ball.punch_effect_radius,
                "is_power_hit": physics.ball.is_power_hit,
                "previous_x": physics.ball.previous_x,
                "previous_y": physics.ball.previous_y,
                "pre_previous_x": physics.ball.pre_previous_x,
                "pre_previous_y": physics.ball.pre_previous_y,
            },
            p1={
                "x": physics.player1.x,
                "y": physics.player1.y,
                "vy": physics.player1.y_velocity,
                "dive_direction": physics.player1.dive_direction,
                "state": physics.player1.state,
                "frame_num": physics.player1.frame_num,
            },
            p2={
                "x": physics.player2.x,
                "y": physics.player2.y,
                "vy": physics.player2.y_velocity,
                "dive_direction": physics.player2.dive_direction,
                "state": physics.player2.state,
                "frame_num": physics.player2.frame_num,
            },
            score_p1=self.score_p1,
            score_p2=self.score_p2,
            terminated=terminated,
            mode=self.mode,
        )


# ==== FastAPI Application ====

app = FastAPI(title="Pikachu Volleyball Game Service", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global game instances storage
games: dict[str, GameInstance] = {}

# Action reader state
action_reader_running = False
action_reader_thread = None
ACTIONS_FILE = Path(__file__).parent.parent / "data" / "actions.txt"
RESULTS_FILE = Path(__file__).parent.parent / "data" / "action_results.txt"
MATCH_ID_FILE = Path(__file__).parent.parent / "data" / "match_id.txt"


def read_match_id() -> Optional[str]:
    """讀取配置文件中的 match ID"""
    if not MATCH_ID_FILE.exists():
        return None
    try:
        with open(MATCH_ID_FILE) as f:
            line = f.readline().strip()
            if line and not line.startswith('#'):
                return line
    except Exception:
        pass
    return None


def action_reader_loop():
    """
    Background thread that reads actions from actions.txt at 25 FPS.

    File format: player_id, x, y, power
    Example: player1, 0, 1, 0

    Match ID is read from data/match_id.txt
    """
    global action_reader_running

    logging.info("[ACTION_READER] Started at 25 FPS")

    # 讀取 match ID
    match_id = read_match_id()
    if not match_id:
        logging.error("[ACTION_READER] No match_id found in data/match_id.txt")
        return

    logging.info(f"[ACTION_READER] Using match_id: {match_id}")

    while action_reader_running:
        try:
            if not ACTIONS_FILE.exists():
                time.sleep(0.04)  # 25 FPS = 0.04s per frame
                continue

            # Read all lines from file
            with open(ACTIONS_FILE, 'r') as f:
                lines = f.readlines()

            if not lines:
                time.sleep(0.04)
                continue

            # Process first line
            line = lines[0].strip()
            if line:
                try:
                    # Parse: player_id, x, y, power
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 4:
                        player_id = parts[0]
                        x, y, power = int(parts[1]), int(parts[2]), int(parts[3])

                        # Execute action
                        game = games.get(match_id)
                        if game:
                            action = [x, y, power]
                            logging.info(f"[ACTION_READER] {match_id} ({player_id}): {action}")

                            # Execute step and get result
                            state = game.step(action)

                            # Write result to output file
                            result_line = (
                                f"{match_id},{player_id},"
                                f"{state.ball['x']:.2f},{state.ball['y']:.2f},"
                                f"{state.p1['x']:.2f},{state.p1['y']:.2f},"
                                f"{state.p2['x']:.2f},{state.p2['y']:.2f},"
                                f"{state.score_p1},{state.score_p2},"
                                f"{int(state.terminated)}\n"
                            )

                            with open(RESULTS_FILE, 'a') as f:
                                f.write(result_line)

                            logging.info(f"[ACTION_READER] Result: ball({state.ball['x']:.1f},{state.ball['y']:.1f}) score={state.score_p1}:{state.score_p2}")
                        else:
                            logging.warning(f"[ACTION_READER] Game {match_id} not found")

                    # Remove processed line
                    with open(ACTIONS_FILE, 'w') as f:
                        f.writelines(lines[1:])

                except (ValueError, IndexError) as e:
                    logging.error(f"[ACTION_READER] Parse error: {line} - {e}")
                    # Remove bad line
                    with open(ACTIONS_FILE, 'w') as f:
                        f.writelines(lines[1:])

            # Wait for next frame (25 FPS)
            time.sleep(0.04)

        except Exception as e:
            logging.error(f"[ACTION_READER] Error: {e}")
            time.sleep(0.04)

    logging.info("[ACTION_READER] Stopped")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "game-service",
        "version": "1.0",
        "active_games": len(games),
        "action_reader_running": action_reader_running,
    }


@app.post("/game/create")
async def create_game(request: GameCreateRequest):
    """
    Create a new game instance.

    Returns:
        Game ID and initial state
    """
    game_id = request.game_id or uuid.uuid4().hex[:8]

    if game_id in games:
        raise HTTPException(status_code=409, detail="Game ID already exists")

    # Create new game instance
    game = GameInstance(game_id=game_id, mode=request.mode)
    games[game_id] = game

    return {
        "game_id": game_id,
        "mode": request.mode,
        "state": asdict(game.get_state()),
    }


@app.post("/game/{game_id}/step")
async def step_game(game_id: str, request: GameStepRequest):
    """
    Execute one game step.

    Args:
        game_id: Game instance ID
        request: Player actions

    Returns:
        Updated game state
    """
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    # Log incoming action at API level
    logging.debug(f"[API] Step request for {game_id}: p1={request.p1_action}, p2={request.p2_action}")

    state = game.step(request.p1_action, request.p2_action)
    return {"state": asdict(state)}


@app.get("/game/{game_id}/state")
async def get_game_state(game_id: str):
    """
    Get current game state without stepping.

    Args:
        game_id: Game instance ID

    Returns:
        Current game state
    """
    game = games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    return {"state": asdict(game.get_state())}


@app.delete("/game/{game_id}")
async def delete_game(game_id: str):
    """
    Delete a game instance.

    Args:
        game_id: Game instance ID

    Returns:
        Success message
    """
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")

    del games[game_id]
    return {"result": "deleted", "game_id": game_id}


@app.get("/games")
async def list_games():
    """
    List all active game instances.

    Returns:
        List of game IDs and their modes
    """
    return {
        "games": [
            {"game_id": gid, "mode": game.mode, "score": {"p1": game.score_p1, "p2": game.score_p2}}
            for gid, game in games.items()
        ]
    }


@app.post("/action-reader/start")
async def start_action_reader():
    """
    Start the action reader background thread.
    Reads actions from data/actions.txt at 25 FPS.
    """
    global action_reader_running, action_reader_thread

    if action_reader_running:
        return {"status": "already_running"}

    action_reader_running = True
    action_reader_thread = threading.Thread(target=action_reader_loop, daemon=True)
    action_reader_thread.start()

    return {
        "status": "started",
        "fps": 25,
        "file": str(ACTIONS_FILE),
    }


@app.post("/action-reader/stop")
async def stop_action_reader():
    """Stop the action reader background thread."""
    global action_reader_running

    if not action_reader_running:
        return {"status": "not_running"}

    action_reader_running = False
    return {"status": "stopped"}


@app.get("/action-reader/status")
async def action_reader_status():
    """Get action reader status."""
    return {
        "running": action_reader_running,
        "input_file": str(ACTIONS_FILE),
        "input_file_exists": ACTIONS_FILE.exists(),
        "output_file": str(RESULTS_FILE),
        "output_file_exists": RESULTS_FILE.exists(),
        "fps": 25,
    }


@app.post("/action-reader/clear-results")
async def clear_results():
    """Clear the action results file."""
    try:
        if RESULTS_FILE.exists():
            RESULTS_FILE.unlink()
        return {"status": "cleared", "file": str(RESULTS_FILE)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Run the game service."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    print("=" * 60)
    print("Pikachu Volleyball Game Service")
    print("=" * 60)
    print("Game Service running on: http://0.0.0.0:8001")
    print("=" * 60)

    uvicorn.run(
        "game_server:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
