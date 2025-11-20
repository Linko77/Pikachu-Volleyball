"""
Blocking-safe client utilities for LabVIEW.

The three exported functions (connect, send_input, poll_state) match the spec so
LabVIEW can interact with the WebSocket server without touching asyncio.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Optional

import websockets

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
                    move = await asyncio.to_thread(_send_queue.get)
                    await ws.send(
                        json.dumps(
                            {
                                "type": "input",
                                "player": 1,
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
