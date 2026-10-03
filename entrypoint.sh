#!/bin/sh
set -e
case "${1:-api}" in
  api)
    trap 'exit 143' TERM INT
    node /app/frontend/scripts/migrate-auth.mjs
    alembic upgrade head
    uvicorn app.main:app --host 127.0.0.1 --port 8000 &
    backend=$!
    (cd /app/frontend && PORT=3000 HOSTNAME=0.0.0.0 exec node server.js) &
    frontend=$!
    trap 'kill -TERM "$backend" "$frontend" 2>/dev/null' TERM INT
    while kill -0 "$backend" 2>/dev/null && kill -0 "$frontend" 2>/dev/null; do
      sleep 2
    done
    kill -TERM "$backend" "$frontend" 2>/dev/null || true
    wait || true
    exit 1
    ;;
  worker)
    exec python -m app.worker
    ;;
  sentinel)
    exec /usr/local/bin/janus-sniff -m app.sentinel.main
    ;;
  scanner)
    exec python -m app.intel.scanner
    ;;
  *)
    exec "$@"
    ;;
esac
