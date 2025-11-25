"""
Pytest configuration and fixtures.
"""

import sys
from pathlib import Path

import pytest

# Add client to path for imports
client_dir = Path(__file__).parent.parent
sys.path.insert(0, str(client_dir))

import lv_ws_client as client


@pytest.fixture(scope="session")
def server_url():
    """Get server URL from config."""
    return client._server_base_url


@pytest.fixture
def match_cleanup():
    """
    Fixture to track and clean up matches created during tests.

    Usage:
        def test_example(match_cleanup):
            match_id = create_match(...)
            match_cleanup.append(match_id)
            # Test code...
            # Match will be cleaned up automatically
    """
    created_matches = []

    yield created_matches

    # Cleanup after test
    for match_id in created_matches:
        try:
            client.stop_match(match_id)
        except:
            pass


@pytest.fixture
def ws_cleanup():
    """
    Fixture to ensure WebSocket is disconnected after test.

    Usage:
        def test_example(ws_cleanup):
            client.connect(ws_url)
            # Test code...
            # WebSocket will be disconnected automatically
    """
    yield

    # Cleanup after test
    try:
        client.disconnect()
    except:
        pass
