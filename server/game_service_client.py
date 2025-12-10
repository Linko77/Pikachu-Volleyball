"""
Client for communicating with the independent Game Service.

This module provides a clean interface for the Match server to interact
with the Game Service microservice.
"""

from typing import Any, Dict, Optional

import requests


class GameServiceClient:
    """Client for Game Service HTTP API."""

    def __init__(self, base_url: str = "http://localhost:12346"):
        """
        Initialize Game Service client.

        Args:
            base_url: Base URL of the Game Service
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = 5  # seconds

    def health_check(self) -> Dict[str, Any]:
        """
        Check if Game Service is healthy.

        Returns:
            Health status dict
        """
        try:
            response = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"status": "error", "detail": str(e)}

    def create_game(self, mode: str = "pvai", game_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new game instance.

        Args:
            mode: Game mode ("pvai" or "pvp")
            game_id: Optional custom game ID

        Returns:
            Dict with game_id, mode, and initial state
        """
        payload = {"mode": mode}
        if game_id:
            payload["game_id"] = game_id

        try:
            response = requests.post(
                f"{self.base_url}/game/create",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def step_game(self, game_id: str, p1_action: str, p2_action: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute one game step.

        Args:
            game_id: Game instance ID
            p1_action: Player 1 action ("left", "right", "jump", "none")
            p2_action: Player 2 action (optional)

        Returns:
            Dict with updated state
        """
        payload = {"p1_action": p1_action}
        if p2_action:
            payload["p2_action"] = p2_action

        try:
            response = requests.post(
                f"{self.base_url}/game/{game_id}/step",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def get_state(self, game_id: str) -> Dict[str, Any]:
        """
        Get current game state without stepping.

        Args:
            game_id: Game instance ID

        Returns:
            Dict with current state
        """
        try:
            response = requests.get(
                f"{self.base_url}/game/{game_id}/state",
                timeout=self.timeout
            )
            response.raise_for_status()

            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def reset_game(self, game_id: str) -> Dict[str, Any]:
        """
        Reset a game instance.

        Args:
            game_id: Game instance ID

        Returns:
            Dict with reset state
        """
        try:
            response = requests.post(
                f"{self.base_url}/game/{game_id}/reset",
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def delete_game(self, game_id: str) -> Dict[str, Any]:
        """
        Delete a game instance.

        Args:
            game_id: Game instance ID

        Returns:
            Success dict
        """
        try:
            response = requests.delete(
                f"{self.base_url}/game/{game_id}",
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def list_games(self) -> Dict[str, Any]:
        """
        List all active games.

        Returns:
            Dict with list of games
        """
        try:
            response = requests.get(
                f"{self.base_url}/games",
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}
