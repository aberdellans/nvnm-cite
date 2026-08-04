# syntax=docker/dockerfile:1
# nvnm-cite web app. One stateless process; no database, no keys, no secrets.
# The container serves plaintext HTTP on 8787 for a TLS reverse proxy /
# k8s ingress in front (see docs/DEPLOYMENT.md).

# ---- build: resolve the locked environment with uv, install the project ----
FROM python:3.11-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

# Use the image's Python (matches the 3.11 the test suite runs on) and
# precompile bytecode so cold starts don't write .pyc at runtime.
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer first: src edits don't invalidate the resolved deps.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Project install is non-editable so /app/.venv is self-contained (package
# data — registry manifests, vendored ABI, webapp static — rides along).
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime ----
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="nvnm-cite" \
      org.opencontainers.image.description="Citation existence verification and filing receipts on NVNM Chain" \
      org.opencontainers.image.source="https://github.com/NVNM-Chain/nvnm-cite" \
      org.opencontainers.image.url="https://nvnmcite.com"

RUN useradd --system --uid 10001 --user-group nvnm \
    && mkdir -p /app/data \
    && chown -R nvnm:nvnm /app

WORKDIR /app
COPY --from=build --chown=nvnm:nvnm /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER nvnm
EXPOSE 8787

# Reads default to mainnet (NVNM_NETWORK=testnet for a staging instance).
# /app/data is an OPTIONAL local index mount (status-panel counts only; the
# chain is the lookup authority). No --telemetry flag: telemetry stays OFF,
# which is the required production posture unless explicitly decided otherwise.
CMD ["python", "-m", "nvnm_cite.webapp", "--host", "0.0.0.0", "--port", "8787", "--data-dir", "/app/data"]
