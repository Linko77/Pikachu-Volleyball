"""
Stress test using pytest with REST API polling.

Creates multiple concurrent matches to test server load.
Can be run with different concurrency levels using pytest markers.
"""

import time
import threading
from typing import List, Dict
import random
import pytest
import lv_ws_client as client


class StressTestResults:
    """Container for stress test results."""

    def __init__(self):
        self.active_matches: List[Dict] = []
        self.errors: List[str] = []
        self.success_count = 0
        self.error_count = 0
        self.lock = threading.Lock()

    def add_match(self, thread_id: int, match_id: str):
        with self.lock:
            self.active_matches.append({
                "thread_id": thread_id,
                "match_id": match_id,
            })

    def add_error(self, error: str):
        with self.lock:
            self.errors.append(error)

    def increment_success(self):
        with self.lock:
            self.success_count += 1

    def increment_error(self):
        with self.lock:
            self.error_count += 1


def play_single_match(match_num: int, duration: int, results: StressTestResults):
    """
    Play a single match in a thread using REST API polling.

    Args:
        match_num: Match identifier
        duration: How long to play in seconds
        results: Results container
    """
    match_info = None

    try:
        # Create match
        match_info = client.create_match(
            mode="pvai",
            player_id=f"stress_{match_num}",
            player_name=f"Player{match_num}"
        )

        if "error" in match_info:
            results.add_error(f"Match {match_num}: Create failed - {match_info['error']}")
            results.increment_error()
            return

        match_id = match_info["match_id"]
        results.add_match(match_num, match_id)

        # Connect (register)
        connect_result = client.connect(match_id, "player1")
        if "error" in connect_result:
            results.add_error(f"Match {match_num}: Connect failed - {connect_result['error']}")
            results.increment_error()
            return

        # Poll initial state
        state = client.poll_state(match_id, "player1")
        if not state or state.get("type") != "state":
            results.add_error(f"Match {match_num}: Failed to receive initial state")
            results.increment_error()
            return

        # Play - poll at 60 FPS
        start_time = time.time()
        moves = ["left", "right", "jump", "none"]
        move_idx = 0

        while time.time() - start_time < duration:
            # Send input
            move = moves[move_idx % len(moves)]
            client.send_input(match_id, move, "player1")

            # Poll state
            state = client.poll_state(match_id, "player1")
            if state:
                results.increment_success()

            move_idx += 1
            time.sleep(0.016)  # ~60 FPS

        # Cleanup
        client.disconnect(match_id, "player1")
        client.stop_match(match_id)

    except Exception as e:
        results.add_error(f"Match {match_num}: Exception - {str(e)}")
        results.increment_error()
        # Try cleanup
        try:
            if match_info and "match_id" in match_info:
                client.disconnect(match_info["match_id"], "player1")
                client.stop_match(match_info["match_id"])
        except:
            pass


@pytest.mark.parametrize("num_matches,duration", [
    (5, 5),   # Quick test: 5 matches, 5 seconds
    (10, 5),  # Medium test: 10 matches, 5 seconds
])
def test_stress_light(server_url, num_matches, duration):
    """Light stress test with configurable concurrency."""
    results = StressTestResults()
    threads = []

    print(f"\nStarting stress test: {num_matches} matches for {duration}s each")

    # Create and start threads
    for i in range(num_matches):
        thread = threading.Thread(
            target=play_single_match,
            args=(i, duration, results)
        )
        thread.daemon = True
        threads.append(thread)
        thread.start()
        time.sleep(0.1)  # Stagger starts slightly

    # Wait for completion
    for thread in threads:
        thread.join(timeout=duration + 15)  # Add buffer time

    # Results
    print(f"\nMatches created: {len(results.active_matches)}/{num_matches}")
    print(f"Successful state polls: {results.success_count}")
    print(f"Errors: {len(results.errors)}")

    if results.errors:
        print(f"\nFirst 5 errors:")
        for error in results.errors[:5]:
            print(f"  - {error}")

    # Assertions
    assert len(results.active_matches) >= num_matches * 0.8, \
        f"Too many failures: {len(results.active_matches)}/{num_matches} succeeded"

    # Should have mostly successful matches
    success_rate = len(results.active_matches) / num_matches * 100
    assert success_rate >= 80, f"Success rate too low: {success_rate:.1f}%"


@pytest.mark.slow
def test_stress_heavy(server_url):
    """Heavy stress test - 15 concurrent matches with REST polling."""
    num_matches = 15
    duration = 8

    results = StressTestResults()
    threads = []

    print(f"\nStarting heavy stress test: {num_matches} matches for {duration}s each")
    print("Each match polls at ~60 FPS via REST API")

    # Create and start threads
    start_time = time.time()
    for i in range(num_matches):
        thread = threading.Thread(
            target=play_single_match,
            args=(i, duration, results)
        )
        thread.daemon = True
        threads.append(thread)
        thread.start()
        time.sleep(0.15)  # Stagger starts

    # Wait for completion
    for thread in threads:
        thread.join(timeout=duration + 20)

    elapsed = time.time() - start_time

    # Results
    print(f"\nStress test completed in {elapsed:.1f}s")
    print(f"Matches created: {len(results.active_matches)}/{num_matches}")
    print(f"Total successful state polls: {results.success_count}")
    print(f"Errors: {len(results.errors)}")

    if results.errors:
        print("\nFirst 10 errors:")
        for error in results.errors[:10]:
            print(f"  - {error}")

    # Assertions
    assert len(results.active_matches) >= num_matches * 0.7, \
        f"Too many failures: {len(results.active_matches)}/{num_matches} succeeded"

    success_rate = len(results.active_matches) / num_matches * 100
    print(f"Match creation success rate: {success_rate:.1f}%")

    # For heavy load, accept 70% success rate
    assert success_rate >= 70, f"Success rate too low: {success_rate:.1f}%"


def test_sequential_matches(server_url):
    """Test creating and playing multiple matches sequentially."""
    num_matches = 5
    duration_per_match = 2

    for i in range(num_matches):
        # Create match
        match_info = client.create_match(
            mode="pvai",
            player_id=f"seq_{i}",
            player_name=f"Sequential{i}"
        )
        assert "error" not in match_info
        match_id = match_info["match_id"]

        # Connect
        result = client.connect(match_id, "player1")
        assert "error" not in result

        # Play briefly
        start = time.time()
        while time.time() - start < duration_per_match:
            move = random.choice(["left", "right", "jump", "none"])
            client.send_input(match_id, move, "player1")

            state = client.poll_state(match_id, "player1")
            assert state is not None

            time.sleep(0.016)  # 60 FPS

        # Cleanup
        client.disconnect(match_id, "player1")
        client.stop_match(match_id)

    print(f"\nSuccessfully completed {num_matches} sequential matches")
