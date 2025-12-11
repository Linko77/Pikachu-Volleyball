FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY server/pyproject.toml server/uv.lock ./
COPY server/main_microservice.py ./
COPY server/game_service_client.py ./

RUN uv sync --frozen

EXPOSE 12345

CMD ["uv", "run", "python", "main_microservice.py"]
