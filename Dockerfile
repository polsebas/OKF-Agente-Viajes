# OKF Travel Agent — imagen CLI
#
# Build:
#   docker build -t okf-travel-agent .
#
# One-shot:
#   docker run --rm --env-file .env okf-travel-agent "Qué días tiene el itinerario?"
#
# REPL interactivo:
#   docker run --rm -it --env-file .env okf-travel-agent
#
# Vault externo (montá tu Obsidian y apuntá OKF_VAULT_ROOT):
#   docker run --rm -it --env-file .env \
#     -v /ruta/a/tu/vault:/vault \
#     -e OKF_VAULT_ROOT=/vault \
#     okf-travel-agent
#
# Si el modelo es Ollama en el host:
#   -e OLLAMA_HOST=http://host.docker.internal:11434
#   (en Linux: --add-host=host.docker.internal:host-gateway)

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["python", "main.py"]
