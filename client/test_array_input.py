"""
Test script for numeric action array input.

This script tests the functionality where clients send
action arrays [x, y, power] to control the game.
"""

import json
import sys
from pathlib import Path

# Add client directory to path
sys.path.insert(0, str(Path(__file__).parent))

import lv_ws_client as client


def test_array_actions():
    """Test sending numeric action arrays."""
    print("=" * 60)
    print("Testing Numeric Action Array Input")
    print("=" * 60)

    # Set server URL
    client.set_server_url("http://localhost:8000")

    # Create a match
    print("\n1. Creating match...")
    match_id = client.create_match("pvai", "test_player", "TestPlayer")
    if not match_id:
        print("❌ Failed to create match")
        return
    print(f"✓ Match created: {match_id}")

    # Test action mapping
    actions = {
        "none": [1, 1, 0],
        "left": [0, 1, 0],
        "right": [2, 1, 0],
        "jump": [1, 2, 0],
        "power": [1, 1, 1],
        "jump_left": [0, 2, 0],
        "jump_right": [2, 2, 0],
    }

    print("\n2. Testing action arrays...")
    for action_name, action_array in actions.items():
        # Send action array
        result = client.send_input(match_id, action_array, "player1")
        print(f"  {action_name} {action_array}: {result}")

    print("\n3. Polling game state...")
    state_json = client.poll_state(match_id)
    print(f"Received JSON string (length: {len(state_json)} chars)")

    # Parse JSON string
    try:
        state = json.loads(state_json)
        print(f"✓ State parsed successfully:")
        print(f"  - Ball position: ({state['ball']['x']:.1f}, {state['ball']['y']:.1f})")
        print(f"  - Score: P1={state['score']['p1']}, P2={state['score']['p2']}")
        print(f"  - Sequence: {state.get('sequence', 'N/A')}")
    except json.JSONDecodeError:
        print(f"❌ Failed to parse JSON: {state_json[:100]}...")

    print("\n4. Stopping match...")
    result = client.stop_match(match_id)
    print(f"Stop result: {result}")

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_array_actions()
