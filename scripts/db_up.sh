#!/usr/bin/env bash
# Zajistí běžící PostgreSQL pro platformu. Pořadí pokusů:
#   1) server na DATABASE_URL už běží -> nic nedělá
#   2) Docker Compose (služba "db" z docker-compose.yml)
#   3) lokální binárky PostgreSQL (pg_ctl) -> dočasný cluster v .pgdata/ na portu 55432
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgresql://pvk:pvk@localhost:55432/pvk}"
PORT="${PVK_PG_PORT:-55432}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

najdi_pg_bin() {
  if command -v pg_ctl >/dev/null 2>&1; then dirname "$(command -v pg_ctl)"; return 0; fi
  local d
  for d in /usr/lib/postgresql/*/bin; do
    if [ -x "$d/pg_ctl" ]; then echo "$d"; return 0; fi
  done
  return 1
}

pripraveno() {
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -q -d "$DATABASE_URL" >/dev/null 2>&1
  else
    local bin; bin="$(najdi_pg_bin)" || return 1
    "$bin/pg_isready" -q -d "$DATABASE_URL" >/dev/null 2>&1
  fi
}

if pripraveno; then
  echo "db: PostgreSQL na DATABASE_URL už běží"
  exit 0
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "db: startuji docker compose (služba db, port $PORT)"
  (cd "$ROOT" && docker compose up -d --wait db)
  for _ in $(seq 1 30); do pripraveno && exit 0; sleep 1; done
  echo "db: docker compose nastartoval, ale server neodpovídá" >&2
  exit 1
fi

BIN="$(najdi_pg_bin || true)"
if [ -n "$BIN" ]; then
  DATA="$ROOT/.pgdata"
  SPUSTIT=()
  if [ "$(id -u)" = "0" ]; then
    # PostgreSQL odmítá běžet pod rootem
    id postgres >/dev/null 2>&1 || { echo "db: jsem root a uživatel postgres neexistuje" >&2; exit 1; }
    mkdir -p "$DATA" && chown postgres "$DATA"
    SPUSTIT=(runuser -u postgres --)
  fi
  if [ ! -f "$DATA/PG_VERSION" ]; then
    echo "db: inicializuji lokální cluster v $DATA"
    "${SPUSTIT[@]}" "$BIN/initdb" -D "$DATA" -U pvk --auth=trust -E UTF8 --locale=C.UTF-8 >/dev/null
  fi
  "${SPUSTIT[@]}" "$BIN/pg_ctl" -D "$DATA" -o "-p $PORT -k /tmp" -l "$DATA/server.log" -w start >/dev/null
  "$BIN/psql" -h localhost -p "$PORT" -U pvk -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='pvk'" | grep -q 1 \
    || "$BIN/createdb" -h localhost -p "$PORT" -U pvk pvk
  pripraveno && { echo "db: lokální PostgreSQL běží na portu $PORT"; exit 0; }
fi

echo "db: nelze zajistit PostgreSQL. Nastavte DATABASE_URL na běžící server, nebo nainstalujte Docker." >&2
exit 1
