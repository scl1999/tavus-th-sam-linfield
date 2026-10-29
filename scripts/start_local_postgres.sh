#!/usr/bin/env bash
# Start the user-space PostgreSQL 16 cluster used when Docker is not available.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG_BIN="${PG_BIN:-$HOME/.local/opt/pgroot/usr/lib/postgresql/16/bin}"
DATA="$ROOT/.postgres-data"
if [[ ! -x "$PG_BIN/pg_ctl" ]]; then
  echo "PostgreSQL binaries not found at $PG_BIN" >&2
  exit 1
fi
if ! "$PG_BIN/pg_isready" -h /tmp -p 5432 -q; then
  "$PG_BIN/pg_ctl" -D "$DATA" -l "$DATA/postgres.log" -o "-k /tmp -c listen_addresses=localhost" start
fi
echo "PostgreSQL listening on localhost:5432 database tavus_interviewer user tavus"
