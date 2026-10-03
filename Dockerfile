FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpcap0.8 libcap2-bin nmap ieee-data libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && cp "$(readlink -f /usr/local/bin/python3.12)" /usr/local/bin/janus-sniff \
    && setcap cap_net_raw+ep /usr/local/bin/janus-sniff
COPY backend/ .
COPY --from=web /app/frontend/.next/standalone /app/frontend
COPY --from=web /app/frontend/.next/static /app/frontend/.next/static
COPY --from=web /app/frontend/public /app/frontend/public
# migrate-auth.mjs resolves better-auth and pg from the standalone node_modules
# (both are serverExternalPackages, so the build traces them there).
COPY --from=web /app/frontend/scripts /app/frontend/scripts
COPY entrypoint.sh /app/entrypoint.sh

ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1 NEXT_TELEMETRY_DISABLED=1
USER 1000:1000
EXPOSE 3000
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["api"]
