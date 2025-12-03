"""
LabVIEW-friendly REST API client for Pikachu Volleyball.

This module provides simple, synchronous HTTP functions for LabVIEW to interact
with the Match Server via REST API polling (no WebSocket, no background threads).

For 60 FPS gameplay, LabVIEW should call poll_state() every 16ms.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# ==== Configuration ====

def _load_server_url() -> str:
    """Load Match Server URL from config/configfile.ini"""
    try:
        config_path = Path(__file__).parent.parent / "config" / "configfile.ini"
        if config_path.exists():
            config = configparser.ConfigParser()
            config.read(config_path)
            return config.get("Server", "match_server_url", fallback="http://localhost:8000")
    except Exception:
        pass
    return "http://140.113.123.37:8000"

_server_base_url = _load_server_url()


# ==== Configuration Functions ====

def set_server_url(url: str) -> None:
    """
    Set the base URL for the server.

    Args:
        url: Base URL (e.g., "http://localhost:8000")
    """
    global _server_base_url
    _server_base_url = url.rstrip("/")


def hello(s: str) -> str:
    """Test function for LabVIEW."""
    return "Hello, " + s


# ==== Match Management API ====

def create_match(mode: str = "pvai", player_id: str = "player1", player_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new match on the server.

    Args:
        mode: Game mode ("pvp" or "pvai")
        player_id: Unique player identifier
        player_name: Display name for the player (optional)

    Returns:
        Dictionary containing match_id, mode, and player_name

    Example:
        >>> match_info = create_match("pvai", "player1", "Howard")
        >>> print(match_info)
        {'match_id': 'abc123', 'mode': 'pvai', 'player_name': 'Howard'}
    """
    url = f"{_server_base_url}/match/start"
    payload = {
        "mode": mode,
        "player_id": player_id,
    }
    if player_name:
        payload["player_name"] = player_name

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        result = response.json()
        return result.get("match_id", "")
    except requests.RequestException as e:
        return ""


def get_match_status(match_id: str) -> Dict[str, Any]:
    """
    Get the status of a match.

    Args:
        match_id: The match ID returned from create_match

    Returns:
        Dictionary containing match status information
    """
    url = f"{_server_base_url}/match/{match_id}/status"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_match_stats(match_id: str) -> Dict[str, Any]:
    """
    Get detailed statistics for a match.

    Args:
        match_id: The match ID

    Returns:
        Dictionary containing match statistics
    """
    url = f"{_server_base_url}/match/{match_id}/stats"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def restart_match(match_id: str) -> bool:
    """
    Restart a match, resetting scores and game state.

    Args:
        match_id: The match ID

    Returns:
        True if restart succeeded, False otherwise
    """
    url = f"{_server_base_url}/match/{match_id}/restart"
    try:
        response = requests.post(url, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def stop_match(match_id: str) -> bool:
    """
    Stop and terminate a match.

    Args:
        match_id: The match ID

    Returns:
        True if stop succeeded, False otherwise
    """
    url = f"{_server_base_url}/match/{match_id}/stop"
    try:
        response = requests.post(url, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def get_server_status() -> Dict[str, Any]:
    """
    Get overall server status.

    Returns:
        Dictionary with server health and active match information
    """
    url = f"{_server_base_url}/system/status"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


# ==== Gameplay API (REST Polling) ====

def connect(match_id: str, role: str = "player1") -> bool:
    """
    Register player for REST API polling.

    NOTE: This function is now OPTIONAL - the server will auto-register
    players when they first call send_input() or poll_state().

    Args:
        match_id: Match ID from create_match()
        role: Player role ("player1" or "player2")

    Returns:
        True if registration succeeded, False otherwise

    Example:
        >>> match_id = create_match("pvai", "player1", "Howard")
        >>> success = connect(match_id, "player1")
    """
    url = f"{_server_base_url}/match/{match_id}/register"
    payload = {
        "role": role,
        "player_id": f"labview_{role}"
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def send_input(match_id: str, move: list[int], role: str = "player1") -> str:
    """
    Send player input to the server.

    Args:
        match_id: Match ID
        move: Action array [x, y, power] where:
              - x: 0=left, 1=none, 2=right
              - y: 0=none, 1=normal, 2=jump
              - power: 0=normal, 1=power hit
        role: Player role

    Returns:
        True if input was accepted, False if error occurred

    Example:
        >>> success = send_input(match_id, [1, 2, 0])  # jump
        >>> if success:
        ...     print("Input sent successfully")
    """
    url = f"{_server_base_url}/match/{match_id}/input"
    payload = {
        "role": role,
        "move": move
    }

    try:
        response = requests.post(url, json=payload, timeout=0.5)
        response.raise_for_status()
        return "True"
    except requests.RequestException as e:
        return f"{e}"


def poll_state(match_id: str, role: Optional[str] = None) -> str:
    """
    Poll current game state (manual, synchronous).

    For 60 FPS gameplay, LabVIEW should call this every 16ms in a loop.

    Args:
        match_id: Match ID
        role: Player role (optional, only used for connection tracking)

    Returns:
        JSON string with game state, or error message string

    Example:
        >>> # Simple usage - no role needed
        >>> state_json = poll_state(match_id)
        >>> # In LabVIEW, parse this JSON string to get ball position, score, etc.
        >>> # Example JSON: {"ball": {"x": 216, "y": 100}, "score": {"p1": 0, "p2": 0}, ...}
    """
    url = f"{_server_base_url}/match/{match_id}/state"
    params = {}
    if role:
        params["role"] = role

    try:
        response = requests.get(url, params=params, timeout=0.5)
        response.raise_for_status()
        return response.text  # Return raw JSON string
    except requests.RequestException as e:
        return f"Error: {e}"


def disconnect(match_id: str, role: str = "player1") -> bool:
    """
    Unregister player from match.

    Args:
        match_id: Match ID
        role: Player role

    Returns:
        True if unregistration succeeded, False otherwise

    Example:
        >>> success = disconnect(match_id, "player1")
    """
    url = f"{_server_base_url}/match/{match_id}/unregister"
    payload = {"role": role}

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False
