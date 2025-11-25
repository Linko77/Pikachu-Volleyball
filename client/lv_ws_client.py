"""
Blocking-safe client utilities for LabVIEW.

The three exported functions (connect, send_input, poll_state) match the spec so
LabVIEW can interact with the WebSocket server without touching asyncio.
"""

from __future__ import annotations

import asyncio
import configparser
import json
import queue
import threading
from pathlib import Path
from typing import Optional, Dict, Any

import websockets
import requests

_send_queue: "queue.Queue[str]" = queue.Queue()
_latest_state: Optional[dict] = None
_ws_thread: Optional[threading.Thread] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_ws: Optional[websockets.WebSocketClientProtocol] = None
_stop_event = threading.Event()


async def _ws_loop(url: str) -> None:
    """Background asyncio loop that keeps a WebSocket open."""
    global _latest_state, _ws
    try:
        async with websockets.connect(url) as ws:
            _ws = ws
            # register as player1 by default per spec
            await ws.send(json.dumps({"type": "register", "role": "player1"}))

            async def sender():
                while not _stop_event.is_set():
                    # Use run_in_executor for Python 3.8 compatibility
                    loop = asyncio.get_event_loop()
                    move = await loop.run_in_executor(None, _send_queue.get)
                    await ws.send(
                        json.dumps(
                            {
                                "type": "input",
                                "move": move,
                            }
                        )
                    )

            async def receiver():
                global _latest_state
                async for message in ws:
                    data = json.loads(message)
                    if data.get("type") == "state":
                        _latest_state = data

            await asyncio.gather(sender(), receiver())
    except Exception as exc:  # pragma: no cover - used for diagnostics
        _latest_state = {"type": "error", "detail": str(exc)}
    finally:
        _ws = None


async def _close_ws():
    """Close the active websocket connection if it exists."""
    if _ws and not _ws.closed:
        await _ws.close()


def _thread_worker(url: str) -> None:
    """Run the websocket loop on a dedicated event loop."""
    global _loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop = loop
    try:
        loop.run_until_complete(_ws_loop(url))
    finally:
        _loop = None


def _ensure_thread(url: str) -> None:
    global _ws_thread
    if _ws_thread and _ws_thread.is_alive():
        return
    _stop_event.clear()
    _ws_thread = threading.Thread(target=_thread_worker, args=(url,), daemon=True)
    _ws_thread.start()


# ==== Public API expected by LabVIEW ====

def hello(s: str):
    return "Hello, " + s


def connect(url: str) -> None:
    """Start the background WebSocket worker if it is not already running."""
    _ensure_thread(url)


def disconnect() -> None:
    """Stop the background WebSocket worker and close the connection."""
    _stop_event.set()
    try:
        _send_queue.put_nowait("none")  # unblock sender loop if waiting
    except queue.Full:
        pass

    if _loop and _loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(_close_ws(), _loop)
            future.result(timeout=1)
        except Exception:
            pass

    if _ws_thread and _ws_thread.is_alive():
        _ws_thread.join(timeout=1)


def send_input(move: str) -> None:
    """
    Queue an input message that the background thread will push to the server.

    move should be one of: left, right, jump, none.
    """
    if not move:
        move = "none"
    _send_queue.put(move)


def poll_state():
    """Return the latest state payload received from the server (or None)."""
    return _latest_state


# ==== HTTP REST API for LabVIEW ====

# Load server URL from config file
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
    return "http://localhost:8000"

# Default server base URL from config
_server_base_url = _load_server_url()


def set_server_url(url: str) -> None:
    """
    Set the base URL for the server.

    Args:
        url: Base URL (e.g., "http://localhost:8000")
    """
    global _server_base_url
    _server_base_url = url.rstrip("/")


def create_match(mode: str = "pvai", player_id: str = "player1", player_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a new match on the server.

    Args:
        mode: Game mode ("pvp" or "pvai")
        player_id: Unique player identifier
        player_name: Display name for the player (optional)

    Returns:
        Dictionary containing match_id, mode, player_name, and ws_url

    Raises:
        Exception if the request fails
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
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_match_status(match_id: str) -> Dict[str, Any]:
    """
    Get the status of a match.

    Args:
        match_id: The match ID returned from create_match

    Returns:
        Dictionary containing match status information

    Raises:
        Exception if the request fails
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
