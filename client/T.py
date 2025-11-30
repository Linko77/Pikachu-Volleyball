from select import poll
from typing import Optional

import requests


def poll_state(match_id: str, role: str = "player1"):
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
    url = f"http://140.113.123.37:8000/match/{match_id}/state"
    params = {"role": role}

    try:
        response = requests.get(url, params=params, timeout=0.5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise
        return None

import json

data = poll_state("8aa848ce")

json_str = json.dumps(data, indent=4)
print(json_str)
