"""
Simple game test using pytest with REST API polling.

Tests basic game functionality:
- Create match
- Register player (REST)
- Send inputs via REST
- Poll game state manually
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
    assert match_info["mode"] == "pvai"
    assert match_info["player_name"] == "Test Player"

    match_cleanup.append(match_info["match_id"])


def test_rest_connection(server_url, match_cleanup):
    """Test REST API player registration."""
    # Create match
    match_info = client.create_match(
        mode="pvai",
        player_id="test_rest",
        player_name="REST Test"
    )
    assert "error" not in match_info
    match_id = match_info["match_id"]
    match_cleanup.append(match_id)

    # Connect (register)
    result = client.connect(match_id, "player1")
    assert "error" not in result, f"Connection failed: {result.get('error')}"
    assert result.get("result") == "registered"
    assert result.get("polling_interval_ms") == 16  # 60 FPS

    # Poll initial state
    state = client.poll_state(match_id, "player1")
    assert state is not None, "No state received"
    assert state.get("type") == "state"
    assert "ball" in state
    assert "p1" in state
    assert "p2" in state
    assert "score" in state
    assert "sequence" in state

    # Disconnect
    client.disconnect(match_id, "player1")


def test_game_input_and_state(server_url, match_cleanup):
    """Test sending inputs and polling game state updates."""
    # Create and connect
    match_info = client.create_match(
        mode="pvai",
        player_id="test_input",
        player_name="Input Test"
    )
    assert "error" not in match_info
    match_id = match_info["match_id"]
    match_cleanup.append(match_id)

    client.connect(match_id, "player1")
    time.sleep(0.1)

    # Get initial state
    initial_state = client.poll_state(match_id, "player1")
    assert initial_state is not None
    initial_ball_y = initial_state["ball"]["y"]
    initial_seq = initial_state["sequence"]

    # Send inputs and poll state (simulate 60 FPS for 1 second)
    for i in range(60):
        move = "jump" if i == 0 else "left"
        client.send_input(match_id, move, "player1")

        state = client.poll_state(match_id, "player1")
        assert state is not None

        time.sleep(0.016)  # ~60 FPS

    # Check state changed
    final_state = client.poll_state(match_id, "player1")
    assert final_state is not None

    # Sequence should have incremented
    assert final_state["sequence"] > initial_seq

    # Ball should have moved (physics is working)
    assert (final_state["ball"]["y"] != initial_ball_y or
            final_state["ball"]["x"] != initial_state["ball"]["x"])

    # Disconnect
    client.disconnect(match_id, "player1")


def test_game_scoring(server_url, match_cleanup):
    """Test that game scoring works over time."""
    # Create and connect
    match_info = client.create_match(
        mode="pvai",
        player_id="test_scoring",
        player_name="Scoring Test"
    )
    assert "error" not in match_info
    match_id = match_info["match_id"]
    match_cleanup.append(match_id)

    client.connect(match_id, "player1")
    time.sleep(0.1)

    # Play for a bit to potentially get scores
    start_time = time.time()
    max_time = 10  # Max 10 seconds

    while time.time() - start_time < max_time:
        client.send_input(match_id, "left", "player1")
        state = client.poll_state(match_id, "player1")

        if state and state.get("score"):
            score = state["score"]
            if score["p1"] > 0 or score["p2"] > 0:
                break

        time.sleep(0.016)  # ~60 FPS

    # Check final state
    final_state = client.poll_state(match_id, "player1")
    assert final_state is not None
    assert "score" in final_state

    # Disconnect
    client.disconnect(match_id, "player1")


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


def test_polling_frequency(server_url, match_cleanup):
    """Test that we can poll at 60 FPS."""
    # Create and connect
    match_info = client.create_match(
        mode="pvai",
        player_id="test_polling",
        player_name="Polling Test"
    )
    assert "error" not in match_info
    match_id = match_info["match_id"]
    match_cleanup.append(match_id)

    client.connect(match_id, "player1")
    time.sleep(0.1)

    # Poll for 1 second at 60 FPS
    start_time = time.time()
    poll_count = 0
    target_duration = 1.0

    while time.time() - start_time < target_duration:
        state = client.poll_state(match_id, "player1")
        if state:
            poll_count += 1
        time.sleep(0.016)  # ~60 FPS

    elapsed = time.time() - start_time
    actual_fps = poll_count / elapsed

    # Should achieve close to 60 FPS (allow some variance)
    assert actual_fps >= 50, f"Polling too slow: {actual_fps:.1f} FPS"
    assert poll_count >= 50, f"Too few successful polls: {poll_count}"

    # Disconnect
    client.disconnect(match_id, "player1")
