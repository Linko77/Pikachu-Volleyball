FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app/client

# Copy client files
COPY client/pyproject.toml client/uv.lock ./
COPY client/*.py ./

# Install dependencies using uv
RUN uv sync --frozen

# Create data directory that will be mounted
RUN mkdir -p /app/data

# Expose no ports (client connects to servers)

CMD ["uv", "run", "python", "labview_bridge.py"]
