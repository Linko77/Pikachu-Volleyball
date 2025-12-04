"""
LabVIEW-friendly REST API client for Pikachu Volleyball.

This module provides simple, synchronous HTTP functions for LabVIEW to interact
with the Match Server via REST API polling (no WebSocket, no background threads).

For 60 FPS gameplay, LabVIEW should call poll_state() every 16ms.
"""

from __future__ import annotations

import asyncio
import configparser
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("[WARNING] websockets library not available. WebSocket features will be disabled.")

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


# ==== WebSocket Client (New) ====

class WebSocketClient:
    """
    WebSocket 客戶端，提供 LabVIEW 友善的同步介面。

    背景執行緒持續接收伺服器推送的狀態，
    LabVIEW 可以隨時非阻塞地讀取最新狀態。
    """

    def __init__(self):
        self.latest_state: Optional[Dict] = None
        self.ws = None
        self.loop = None
        self.thread = None
        self.connected = False
        self.match_id = None
        self.role = None
        self._stop_flag = False

    def connect(self, match_id: str, role: str = "player1") -> bool:
        """
        建立 WebSocket 連線（啟動背景執行緒）。

        Args:
            match_id: Match ID from create_match()
            role: Player role ("player1" or "player2")

        Returns:
            True if connection succeeded, False otherwise
        """
        if not WEBSOCKETS_AVAILABLE:
            print("[ERROR] websockets library not available")
            return False

        self.match_id = match_id
        self.role = role
        self._stop_flag = False

        # 啟動背景執行緒
        self.thread = threading.Thread(
            target=self._run_async_loop,
            daemon=True
        )
        self.thread.start()

        # 等待連線建立（最多 2 秒）
        for _ in range(20):
            if self.connected:
                print(f"[WebSocket] Connected to match {match_id} as {role}")
                return True
            time.sleep(0.1)

        print("[WebSocket] Connection timeout")
        return False

    def _run_async_loop(self):
        """背景執行緒：執行 asyncio event loop"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._connect_and_receive())
        except Exception as e:
            print(f"[WebSocket] Error: {e}")
        finally:
            self.loop.close()

    async def _connect_and_receive(self):
        """建立 WebSocket 連線並持續接收狀態推送"""
        # 構建 WebSocket URL
        base_url = _server_base_url.replace('http://', '').replace('https://', '')
        url = f"ws://{base_url}/ws/{self.match_id}/{self.role}"

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            if self._stop_flag:
                break

            try:
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    self.connected = True
                    print(f"[WebSocket] Connected to {url}")

                    # 持續接收訊息
                    async for message in ws:
                        if self._stop_flag:
                            break

                        try:
                            data = json.loads(message)

                            # 更新最新狀態（所有訊息都視為狀態更新）
                            self.latest_state = data

                            if data.get("type") == "error":
                                print(f"[WebSocket] Server error: {data.get('message')}")

                        except json.JSONDecodeError:
                            print(f"[WebSocket] Invalid JSON: {message[:100]}")

            except websockets.ConnectionClosed:
                if self._stop_flag:
                    break
                print(f"[WebSocket] Connection closed, retrying ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(retry_delay)

            except Exception as e:
                print(f"[WebSocket] Connection error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                break

        self.connected = False
        print("[WebSocket] Disconnected")

    def send_input(self, move: list, role: str = "player1") -> bool:
        """
        非阻塞發送玩家輸入。

        Args:
            move: Action array [x, y, power]
            role: Player role

        Returns:
            True if send succeeded, False otherwise
        """
        if not self.connected or not self.ws or not self.loop:
            return False

        message = json.dumps({
            "type": "input",
            "role": role,
            "move": move
        })

        try:
            # 在背景執行緒的 event loop 中發送
            future = asyncio.run_coroutine_threadsafe(
                self.ws.send(message),
                self.loop
            )
            # 最多等待 0.1 秒
            future.result(timeout=0.1)
            return True
        except Exception as e:
            print(f"[WebSocket] Send error: {e}")
            return False

    def get_state(self) -> Optional[str]:
        """
        立即返回最新狀態（無網路延遲）。

        Returns:
            JSON string with latest state, or None if no state available
        """
        if self.latest_state:
            return json.dumps(self.latest_state)
        return None

    def disconnect(self) -> bool:
        """關閉 WebSocket 連線"""
        self._stop_flag = True

        if self.loop and self.ws:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.close(),
                    self.loop
                )
                future.result(timeout=1.0)
            except Exception as e:
                print(f"[WebSocket] Disconnect error: {e}")

        self.connected = False
        print("[WebSocket] Disconnect requested")
        return True


# 全域 WebSocket 客戶端實例
_ws_client: Optional[WebSocketClient] = None


# ==== LabVIEW 友善的 WebSocket API ====

def ws_connect(match_id: str, role: str = "player1") -> bool:
    """
    建立 WebSocket 連線。

    Args:
        match_id: Match ID from create_match()
        role: Player role ("player1" or "player2")

    Returns:
        True if connection succeeded

    Example (LabVIEW):
        match_id = create_match("pvai", "player1")
        success = ws_connect(match_id, "player1")
    """
    global _ws_client

    if not WEBSOCKETS_AVAILABLE:
        return False

    _ws_client = WebSocketClient()
    return _ws_client.connect(match_id, role)


def ws_send_input(move: list, role: str = "player1") -> bool:
    """
    非阻塞發送玩家輸入（~0.1ms）。

    Args:
        move: Action array [x, y, power]
        role: Player role

    Returns:
        True if send succeeded

    Example (LabVIEW):
        success = ws_send_input([1, 2, 0], "player1")  # jump
    """
    if not _ws_client:
        return False
    return _ws_client.send_input(move, role)


def ws_get_state() -> str:
    """
    立即返回最新狀態（~0.1ms，無網路延遲）。

    Returns:
        JSON string with latest state, or empty string if no state available

    Example (LabVIEW):
        state_json = ws_get_state()
        # Parse JSON in LabVIEW to get ball position, score, etc.
    """
    if not _ws_client:
        return ""

    state = _ws_client.get_state()
    return state if state else ""


def ws_disconnect() -> bool:
    """
    關閉 WebSocket 連線。

    Returns:
        True if disconnect succeeded

    Example (LabVIEW):
        success = ws_disconnect()
    """
    global _ws_client
    if _ws_client:
        result = _ws_client.disconnect()
        _ws_client = None
        return result
    return False
