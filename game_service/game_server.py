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

import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, final

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
    p1_action: str  # "left", "right", "jump", "none"
    p2_action: Optional[str] = None  # For PvP mode


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

    def __init__(self, game_id: str, mode: str = "pvai"):
        self.game_id = game_id
        self.mode = mode
        self.score_p1 = 0
        self.score_p2 = 0

        # Create Gymnasium environment
        is_p2_ai = (mode == "pvai")
        self.env = PykachuEnv(
            is_player_1_computer=False,
            is_player_2_computer=is_p2_ai,
            render_mode=None
        )

        # Reset environment
        self.env.reset()

        # Action mapping
        self.action_map = {
            "none": [1, 1, 0],
            "left": [0, 1, 0],
            "right": [2, 1, 0],
            "jump": [1, 2, 0],
            "power": [1, 1, 1],
            "jump_left": [0, 2, 0],
            "jump_right": [2, 2, 0],
        }

    def step(self, p1_action: str, p2_action: Optional[str] = None) -> GameState:
        """
        Execute one game step.

        Args:
            p1_action: Player 1 action
            p2_action: Player 2 action (optional, uses AI if None in pvai mode)

        Returns:
            Current game state
        """
        # Convert action to environment format
        action = self.action_map.get(p1_action, self.action_map["none"])

        # TODO: For PvP mode, handle p2_action
        # Currently the environment manages AI internally

        # Step environment
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


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "game-service",
        "version": "1.0",
        "active_games": len(games),
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


def main():
    """Run the game service."""
    uvicorn.run(
        "game_server:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )


if __name__ == "__main__":
    main()
