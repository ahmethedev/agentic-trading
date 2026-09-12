# Worker + API image. Needs BOTH runtimes: Python for the trading logic and
# Node for the mandatory OKX Agent Trade Kit MCP server, which the worker spawns
# as a long-lived child process.
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm

# Copy the Node runtime rather than apt-installing it: the host has no
# passwordless sudo and this pins the version alongside the ATK lockfile.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

WORKDIR /app

# ATK first so its layer caches independently of application code.
COPY vendor/atk/package.json vendor/atk/package-lock.json ./vendor/atk/
RUN cd vendor/atk && npm ci --omit=dev

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY dashboard/dist ./dashboard/dist

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    ATK_DIR=/app/vendor/atk \
    OKX_UPDATE_CHECK=0

# Writable home for the ATK process (it caches under ~/.okx).
RUN useradd -m -u 10001 trader && chown -R trader:trader /app
USER trader

CMD ["python", "-m", "agentic_trade.worker"]
