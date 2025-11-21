"""
Simple CLI client for quickly testing the Pikachu Volleyball server without LabVIEW.

Usage:
    python test_client.py --server http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
import urllib.error
import urllib.request

import websockets


def _start_match(base_url: str, mode: str, player_id: str) -> str:
    """Call POST /match/start and return the ws_url."""
    payload = json.dumps({"mode": mode, "player_id": player_id}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/match/start",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        return data["ws_url"]


async def _run(ws_url: str, moves: Iterable[str], delay: float) -> None:
    """Connect to the server, auto-send moves, and print every state payload."""
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "register", "role": "player1"}))

        async def sender():
            for move in itertools.cycle(moves):
                await ws.send(json.dumps({"type": "input", "player": 1, "move": move}))
                await asyncio.sleep(delay)

        async def receiver():
            async for message in ws:
                data = json.loads(message)
                if data.get("type") != "state":
                    continue
                ball = data["ball"]
                score = data["score"]
                print(
                    f"Ball=({ball['x']:.1f},{ball['y']:.1f}) "
                    f"Vel=({ball['vx']:.1f},{ball['vy']:.1f}) "
                    f"Score P1:{score['p1']} P2:{score['p2']}"
                )

        await asyncio.gather(sender(), receiver())


def main():
    parser = argparse.ArgumentParser(description="CLI test client for Pikachu Volleyball server")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="Base REST server URL")
    parser.add_argument(
        "--mode",
        default="pvai",
        choices=["pvp", "pvai"],
        help="Matchmaking mode to request when ws-url is not provided",
    )
    parser.add_argument("--player-id", default="cli-tester", help="Player identifier for /match/start")
    parser.add_argument(
        "--ws-url",
        help="Connect directly to this WebSocket URL (skip /match/start)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Seconds between auto input messages",
    )
    parser.add_argument(
        "--moves",
        nargs="*",
        default=["left", "right", "jump", "none"],
        help="Sequence of moves to cycle through",
    )
    args = parser.parse_args()

    ws_url = args.ws_url
    if not ws_url:
        try:
            ws_url = _start_match(args.server, args.mode, args.player_id)
        except urllib.error.URLError as exc:  # pragma: no cover - CLI only
            print(f"Failed to start match via REST API: {exc}", file=sys.stderr)
            sys.exit(2)

    try:
        asyncio.run(_run(ws_url, args.moves, args.delay))
    except KeyboardInterrupt:  # pragma: no cover - CLI only
        print("\nClient stopped.")


if __name__ == "__main__":
    main()
