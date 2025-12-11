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
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Union, final

import numpy as np
import torch
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
    import ppo_agent  # Import PPO agent for AI mode

    from pykachu_env import PykachuEnv
finally:
    os.chdir(original_cwd)


# ==== PPO AI Wrapper ====

class PPOAgent:
    """Wrapper for PPO AI agent"""

    def __init__(self, model_path: Optional[str] = None):
        """Initialize PPO agent with trained model"""
        if model_path is None:
            model_path = str(game_dir / "checkpoints" / "ppo_pykachu_update_100.pt")

        self.model_path = model_path
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Initialize agent
        self.agent = ppo_agent.PikachuPPO(
            ppo_agent.ACTION_DIMS,
            input_channels=3 * ppo_agent.FRAME_STACK
        ).to(self.device)

        # Load trained weights
        self.agent.load_state_dict(
            torch.load(model_path, map_location=self.device, weights_only=True)
        )
        self.agent.eval()

        logging.info(f"[AI] PPO agent loaded from {model_path}")

    def create_frame_stack(self):
        """Create a new frame stack for a game instance"""
        frames = deque(maxlen=ppo_agent.FRAME_STACK)
        # Initialize with empty frames
        dummy_frame = np.zeros((*ppo_agent.DOWNSAMPLED_SHAPE, 3), dtype=np.uint8)
        for _ in range(ppo_agent.FRAME_STACK):
            frames.append(dummy_frame)
        return frames

    def get_action(self, obs_env, frames: deque) -> List[int]:
        """Get action from PPO agent for given observation"""
        # Update frame stack
        obs_frame = ppo_agent.downsample_obs(obs_env)
        frames.append(obs_frame)

        # Stack frames
        stacked_obs = ppo_agent.stack_frames(frames)
        obs_tensor = ppo_agent.obs_to_tensor(stacked_obs).unsqueeze(0)

        # Get action from agent
        with torch.no_grad():
            actions, _, _, _ = self.agent.get_action_and_value(obs_tensor)

        action = actions.squeeze(0).cpu().numpy().tolist()
        return action


# Global singleton PPO agent (loaded once, shared by all aivai games)
_global_ppo_agent: Optional[PPOAgent] = None

def get_ppo_agent() -> PPOAgent:
    """Get or create the global PPO agent singleton"""
    global _global_ppo_agent
    if _global_ppo_agent is None:
        _global_ppo_agent = PPOAgent()
    return _global_ppo_agent


# ==== Data Models ====

class GameCreateRequest(BaseModel):
    """Request to create a new game instance."""
    mode: str = "pvai"  # "pvai", "pvp", or "aivai"
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

    # Frame rate limiting: 20 FPS = 0.05 seconds per frame
    TARGET_FPS = 20
    FRAME_TIME = 1.0 / TARGET_FPS  # 0.05 seconds

    def __init__(self, game_id: str, mode: str = "pvai"):
        self.game_id = game_id
        self.mode = mode
        self.score_p1 = 0
        self.score_p2 = 0
        self.last_step_time = time.time()

        # Create Gymnasium environment
        is_p1_ai = (mode == "aivai")  # Player 1 is AI in aivai mode
        is_p2_ai = (mode == "pvai" or mode == "aivai")  # Player 2 is AI in both pvai and aivai

        self.env = PykachuEnv(
            is_player_1_computer=is_p1_ai,
            is_player_2_computer=is_p2_ai,
            render_mode=None  # Use None for headless mode (no rendering)
        )

        # Initialize PPO agent for aivai mode (using global singleton)
        self.ppo_agent = None
        self.ai_frames = None  # Frame stack for AI
        if mode == "aivai":
            try:
                self.ppo_agent = get_ppo_agent()  # Use global singleton
                self.ai_frames = self.ppo_agent.create_frame_stack()
                logging.info(f"[GAME {game_id}] Using shared PPO AI (player1)")
            except Exception as e:
                logging.error(f"[GAME {game_id}] Failed to load PPO agent: {e}")
                raise RuntimeError(f"Failed to load PPO agent: {e}")

        # Reset environment
        reset_result = self.env.reset()
        if isinstance(reset_result, tuple):
            self.last_obs, _ = reset_result
        else:
            self.last_obs = reset_result

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
        Execute one game step with 20 FPS frame rate limiting.

        Args:
            p1_action: Player 1 action array [x, y, power]
            p2_action: Player 2 action array (optional, uses AI if None in pvai mode)

        Returns:
            Current game state
        """
        # Enforce 20 FPS frame rate limiting
        current_time = time.time()
        elapsed = current_time - self.last_step_time

        if elapsed < self.FRAME_TIME:
            # Sleep to maintain 30 FPS
            sleep_time = self.FRAME_TIME - elapsed
            time.sleep(sleep_time)

        # Update last step time
        self.last_step_time = time.time()

        # In aivai mode, use PPO agent for player1
        if self.mode == "aivai" and self.ppo_agent is not None:
            p1 = self.ppo_agent.get_action(self.last_obs, self.ai_frames)
            logging.info(f"[GAME] AI Player 1 action: {p1}")
        else:
            p1 = p1_action

        p2 = p2_action if p2_action is not None else [1, 1, 0]  # Default to "no action"

        # Log actions if not "none"
        if p1 != [1, 1, 0] and self.mode != "aivai":
            logging.info(f"[GAME] Player 1 action: {p1}")
        if p2 != [1, 1, 0]:
            logging.info(f"[GAME] Player 2 action: {p2}")

        # Step environment with both player actions
        obs, reward, terminated, info = self.env.step(
            player1_action=p1,
            player2_action=p2
        )

        # Store observation for next step (needed for AI)
        self.last_obs = obs


        # Update scores if someone scored
        if terminated:
            if self.env.physics.ball.punch_effect_x < 216:  # Left side
                self.score_p2 += 1
            else:  # Right side
                self.score_p1 += 1
            # Reset for next round
            reset_result = self.env.reset()
            if isinstance(reset_result, tuple):
                self.last_obs, _ = reset_result
            else:
                self.last_obs = reset_result

            # Reset PPO agent frame stack if in aivai mode
            if self.mode == "aivai" and self.ppo_agent is not None:
                self.ai_frames = self.ppo_agent.create_frame_stack()

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
    Background thread that reads actions from actions.txt at 30 FPS.

    File format: player_id, x, y, power
    Example: player1, 0, 1, 0

    Match ID is read from data/match_id.txt
    """
    global action_reader_running

    logging.info("[ACTION_READER] Started at 30 FPS")

    # 讀取 match ID
    match_id = read_match_id()
    if not match_id:
        logging.error("[ACTION_READER] No match_id found in data/match_id.txt")
        return

    logging.info(f"[ACTION_READER] Using match_id: {match_id}")

    while action_reader_running:
        try:
            if not ACTIONS_FILE.exists():
                time.sleep(0.0333)  # 30 FPS = 0.0333s per frame
                continue

            # Read all lines from file
            with open(ACTIONS_FILE, 'r') as f:
                lines = f.readlines()

            if not lines:
                time.sleep(0.0333)
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

            # Wait for next frame (30 FPS)
            time.sleep(0.0333)

        except Exception as e:
            logging.error(f"[ACTION_READER] Error: {e}")
            time.sleep(0.0333)

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
    logging.info(f"[API] Step request for {game_id}: p1={request.p1_action}, p2={request.p2_action}")

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
    Reads actions from data/actions.txt at 30 FPS.
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
        port=12346,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
