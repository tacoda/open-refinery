# ponytail: uv base image ships python + uv; no multi-stage needed for a
# dependency-free package. Revisit if the image grows or build deps appear.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Sync deps first (cached) — then the sources it builds from.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    LOG_LEVEL=INFO

EXPOSE 8000

# ponytail: CLI is the entrypoint today; becomes `serve` at 0.3.0 (FastAPI).
ENTRYPOINT ["open-refinery"]
CMD ["--help"]
