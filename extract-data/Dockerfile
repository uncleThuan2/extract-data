# ── Stage 1: build ────────────────────────────────────────────────────────────
# Use the full Python image so tiktoken (and any other C/Rust extension) can
# always be compiled from source if a pre-built wheel is unavailable.
FROM python:3.11 AS builder

WORKDIR /build

# System deps needed to compile native extensions (tiktoken uses Rust via maturin,
# psycopg/vecs may need libpq headers).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (required by tiktoken if no wheel is available for the platform).
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Only the runtime shared libraries are needed (no build tools).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder.
COPY --from=builder /install /usr/local

# Copy application source.
COPY . .

# Render injects PORT automatically; fall back to 8080 for local docker run.
ENV PORT=8080
EXPOSE 8080

# Default: run both bots. Override CMD or set PLATFORM env var if needed.
CMD ["python", "run.py", "both"]
