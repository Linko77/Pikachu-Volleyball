#!/bin/bash
# Test runner script for Pikachu Volleyball

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$CLIENT_DIR")"

cd "$CLIENT_DIR"

echo "============================================================"
echo "Pikachu Volleyball Test Suite"
echo "============================================================"
echo ""

# Check if servers are running
echo "Checking servers..."
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "⚠️  Warning: Match Server (port 8000) not responding"
    echo "   Start with: cd server && uv run python main_microservice.py"
    echo ""
fi

if ! curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "⚠️  Warning: Game Service (port 8001) not responding"
    echo "   Start with: cd game_service && uv run python game_server.py"
    echo ""
fi

# Parse arguments
TEST_TYPE="${1:-all}"

case "$TEST_TYPE" in
    quick)
        echo "Running quick tests (excluding slow tests)..."
        uv run pytest tests -m "not slow" -v
        ;;
    stress)
        echo "Running stress tests only..."
        uv run pytest tests/test_stress.py -v
        ;;
    slow)
        echo "Running slow tests only..."
        uv run pytest tests -m slow -v
        ;;
    all)
        echo "Running all tests..."
        uv run pytest tests -v
        ;;
    *)
        echo "Running specific test: $TEST_TYPE"
        uv run pytest "tests/$TEST_TYPE" -v
        ;;
esac

echo ""
echo "============================================================"
echo "Test run completed!"
echo "============================================================"
