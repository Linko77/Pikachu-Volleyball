FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app/game_service

# Copy game directory first (needed by game_server.py)
COPY game /app/game

# Copy game service files
COPY game_service/pyproject.toml game_service/uv.lock ./
COPY game_service/game_server.py ./
COPY game_service/pykachu_env ./pykachu_env

# Install dependencies using uv
RUN uv sync --frozen

EXPOSE 12346

CMD ["uv", "run", "python", "game_server.py"]
