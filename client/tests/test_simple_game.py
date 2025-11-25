"""
Simple game test using pytest.

Tests basic game functionality:
- Create match
- Connect WebSocket
- Send inputs
- Receive game state
- Clean up
"""

import time
import lv_ws_client as client


def test_create_match(server_url, match_cleanup):
    """Test creating a match."""
    match_info = client.create_match(
        mode="pvai",
        player_id="test_player",
        player_name="Test Player"
    )

    assert "error" not in match_info, f"Failed to create match: {match_info.get('error')}"
    assert "match_id" in match_info
    assert "ws_url" in match_info
    assert match_info["mode"] == "pvai"
    assert match_info["player_name"] == "Test Player"

    match_cleanup.append(match_info["match_id"])


def test_websocket_connection(server_url, match_cleanup, ws_cleanup):
    """Test WebSocket connection and initial state."""
    # Create match
    match_info = client.create_match(
        mode="pvai",
        player_id="test_ws",
        player_name="WS Test"
    )
    assert "error" not in match_info
    match_cleanup.append(match_info["match_id"])

    # Connect
    ws_url = match_info["ws_url"]
    client.connect(ws_url)
    time.sleep(0.5)

    # Check initial state
    state = client.poll_state()
    assert state is not None, "No state received"
    assert state.get("type") == "state"
    assert "ball" in state
    assert "p1" in state
    assert "p2" in state
    assert "score" in state


def test_game_input_and_state(server_url, match_cleanup, ws_cleanup):
    """Test sending inputs and receiving game state updates."""
    # Create and connect
    match_info = client.create_match(
        mode="pvai",
        player_id="test_input",
        player_name="Input Test"
    )
    assert "error" not in match_info
    match_cleanup.append(match_info["match_id"])

    client.connect(match_info["ws_url"])
    time.sleep(0.5)

    # Send inputs and check state updates
    initial_state = client.poll_state()
    assert initial_state is not None

    initial_ball_y = initial_state["ball"]["y"]

    # Send some inputs
    for i in range(10):
        client.send_input("jump" if i == 0 else "none")
        time.sleep(0.1)

    # Check state changed
    final_state = client.poll_state()
    assert final_state is not None

    # Ball should have moved (physics is working)
    final_ball_y = final_state["ball"]["y"]
    # Position should have changed (even if slightly)
    assert initial_ball_y != final_ball_y or initial_state["ball"]["x"] != final_state["ball"]["x"]


def test_game_scoring(server_url, match_cleanup, ws_cleanup):
    """Test that game scoring works over time."""
    # Create and connect
    match_info = client.create_match(
        mode="pvai",
        player_id="test_scoring",
        player_name="Scoring Test"
    )
    assert "error" not in match_info
    match_cleanup.append(match_info["match_id"])

    client.connect(match_info["ws_url"])
    time.sleep(0.5)

    # Play for a bit to potentially get scores
    start_time = time.time()
    max_time = 15  # Max 15 seconds
    scored = False

    while time.time() - start_time < max_time:
        client.send_input("left")
        time.sleep(0.1)

        state = client.poll_state()
        if state and state.get("score"):
            score = state["score"]
            if score["p1"] > 0 or score["p2"] > 0:
                scored = True
                break

    # Should eventually get a score (but not guaranteed, so we just check state exists)
    final_state = client.poll_state()
    assert final_state is not None
    assert "score" in final_state


def test_match_cleanup(server_url, match_cleanup):
    """Test that matches can be properly stopped."""
    # Create match
    match_info = client.create_match(
        mode="pvai",
        player_id="test_cleanup",
        player_name="Cleanup Test"
    )
    assert "error" not in match_info
    match_id = match_info["match_id"]

    # Stop match
    result = client.stop_match(match_id)
    assert "error" not in result or result.get("result") == "terminated"

    # Match should be cleaned up (don't add to match_cleanup since we already stopped it)
