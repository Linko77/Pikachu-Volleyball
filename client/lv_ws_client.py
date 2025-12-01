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


def restart_match(match_id: str) -> Dict[str, Any]:
    """
    Restart a match, resetting scores and game state.

    Args:
        match_id: The match ID

    Returns:
        Dictionary with result and current score
    """
    url = f"{_server_base_url}/match/{match_id}/restart"
    try:
        response = requests.post(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def stop_match(match_id: str) -> Dict[str, Any]:
    """
    Stop and terminate a match.

    Args:
        match_id: The match ID

    Returns:
        Dictionary with result status
    """
    url = f"{_server_base_url}/match/{match_id}/stop"
    try:
        response = requests.post(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


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

def connect(match_id: str, role: str = "player1") -> Dict[str, Any]:
    """
    Register player for REST API polling.

    This registers the player with the server so they can send inputs
    and poll game state. No background threads - all manual.

    Args:
        match_id: Match ID from create_match()
        role: Player role ("player1" or "player2")

    Returns:
        Registration result with polling_interval_ms

    Example:
        >>> match_info = create_match("pvai", "player1", "Howard")
        >>> result = connect(match_info["match_id"], "player1")
        >>> print(result)
        {'result': 'registered', 'match_id': '...', 'role': 'player1', 'polling_interval_ms': 16}
    """
    url = f"{_server_base_url}/match/{match_id}/register"
    payload = {
        "role": role,
        "player_id": f"labview_{role}"
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def send_input(match_id: str, move: str, role: str = "player1") -> Dict[str, Any]:
    """
    Send player input to the server.

    Args:
        match_id: Match ID
        move: Player move ("left", "right", "jump", "none")
        role: Player role

    Returns:
        Input submission result

    Example:
        >>> result = send_input(match_id, "jump", "player1")
        >>> print(result)
        {'result': 'accepted', 'queued_at': 1234567890.123}
    """
    url = f"{_server_base_url}/match/{match_id}/input"
    payload = {
        "role": role,
        "move": move
    }

    try:
        response = requests.post(url, json=payload, timeout=0.5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def poll_state(match_id: str, role: str = "player1") -> Optional[Dict[str, Any]]:
    """
    Poll current game state (manual, synchronous).

    For 60 FPS gameplay, LabVIEW should call this every 16ms in a loop.

    Args:
        match_id: Match ID
        role: Player role

    Returns:
        State dict with ball, p1, p2, score, sequence, timestamp
        Returns None if error

    Example:
        >>> state = poll_state(match_id, "player1")
        >>> if state:
        ...     print(f"Score: P1={state['score']['p1']}, P2={state['score']['p2']}")
        ...     print(f"Ball: x={state['ball']['x']}, y={state['ball']['y']}")
    """
    url = f"{_server_base_url}/match/{match_id}/state"
    params = {"role": role}

    try:
        response = requests.get(url, params=params, timeout=0.5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def disconnect(match_id: str, role: str = "player1") -> Dict[str, Any]:
    """
    Unregister player from match.

    Args:
        match_id: Match ID
        role: Player role

    Returns:
        Unregistration result

    Example:
        >>> result = disconnect(match_id, "player1")
        >>> print(result)
        {'result': 'unregistered'}
    """
    url = f"{_server_base_url}/match/{match_id}/unregister"
    payload = {"role": role}

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}
