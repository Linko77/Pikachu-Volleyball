"""
Stress test using pytest.

Creates multiple concurrent matches to test server load.
Can be run with different concurrency levels using pytest markers.
"""

import time
import threading
from typing import List, Dict
import pytest
import lv_ws_client as client


class StressTestResults:
    """Container for stress test results."""

    def __init__(self):
        self.active_matches: List[Dict] = []
        self.errors: List[str] = []
        self.lock = threading.Lock()

    def add_match(self, thread_id: int, match_id: str, ws_url: str):
        with self.lock:
            self.active_matches.append({
                "thread_id": thread_id,
                "match_id": match_id,
                "ws_url": ws_url,
            })

    def add_error(self, error: str):
        with self.lock:
            self.errors.append(error)


def play_single_match(match_id: int, duration: int, results: StressTestResults):
    """
    Play a single match in a thread.

    Args:
        match_id: Match identifier
        duration: How long to play in seconds
        results: Results container
    """
    match_info = None

    try:
        # Create match
        match_info = client.create_match(
            mode="pvai",
            player_id=f"stress_{match_id}",
            player_name=f"Player{match_id}"
        )

        if "error" in match_info:
            results.add_error(f"Match {match_id}: Create failed - {match_info['error']}")
            return

        # Track match
        results.add_match(match_id, match_info["match_id"], match_info["ws_url"])

        # Connect
        client.connect(match_info["ws_url"])
        time.sleep(0.3)

        # Check connection
        state = client.poll_state()
        if not state or state.get("type") != "state":
            results.add_error(f"Match {match_id}: Failed to receive state")
            return

        # Play
        moves = ["left", "right", "jump", "none"]
        start_time = time.time()
        move_idx = 0

        while time.time() - start_time < duration:
            client.send_input(moves[move_idx % len(moves)])
            move_idx += 1
            time.sleep(0.1)

        # Cleanup
        client.disconnect()
        client.stop_match(match_info["match_id"])

    except Exception as e:
        results.add_error(f"Match {match_id}: Exception - {str(e)}")
        # Try cleanup
        try:
            client.disconnect()
            if match_info and "match_id" in match_info:
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

    # Create and start threads
    for i in range(num_matches):
        thread = threading.Thread(
            target=play_single_match,
            args=(i, duration, results)
        )
        thread.daemon = True
        threads.append(thread)
        thread.start()
        time.sleep(0.05)  # Stagger starts

    # Wait for completion
    for thread in threads:
        thread.join(timeout=duration + 10)  # Add buffer time

    # Assertions
    assert len(results.active_matches) >= num_matches * 0.8, \
        f"Too many failures: {len(results.active_matches)}/{num_matches} succeeded"

    if results.errors:
        print(f"\nErrors encountered ({len(results.errors)}):")
        for error in results.errors[:5]:  # Show first 5
            print(f"  - {error}")

    # Should have mostly successful matches
    success_rate = len(results.active_matches) / num_matches * 100
    assert success_rate >= 80, f"Success rate too low: {success_rate:.1f}%"


@pytest.mark.slow
def test_stress_heavy(server_url):
    """Heavy stress test - 20 concurrent matches."""
    num_matches = 20
    duration = 10

    results = StressTestResults()
    threads = []

    print(f"\nStarting heavy stress test: {num_matches} matches for {duration}s each")

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
        time.sleep(0.1)

    # Wait for completion
    for thread in threads:
        thread.join(timeout=duration + 15)

    elapsed = time.time() - start_time

    # Results
    print(f"\nStress test completed in {elapsed:.1f}s")
    print(f"Matches created: {len(results.active_matches)}/{num_matches}")
    print(f"Errors: {len(results.errors)}")

    if results.errors:
        print("\nFirst 5 errors:")
        for error in results.errors[:5]:
            print(f"  - {error}")

    # Assertions
    assert len(results.active_matches) >= num_matches * 0.7, \
        f"Too many failures: {len(results.active_matches)}/{num_matches} succeeded"

    success_rate = len(results.active_matches) / num_matches * 100
    print(f"Success rate: {success_rate:.1f}%")

    # For heavy load, accept 70% success rate
    assert success_rate >= 70, f"Success rate too low: {success_rate:.1f}%"
