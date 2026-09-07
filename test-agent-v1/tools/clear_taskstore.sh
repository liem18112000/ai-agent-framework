#!/usr/bin/env bash
# clear_taskstore.sh — truncate the A2A task-store table in the Testing-Agent Cloud SQL Postgres.
#
# Both agents persist A2A Task objects in a shared Cloud SQL Postgres instance (kga-taskstore)
# via a2a-sdk's DatabaseTaskStore, which lazily creates a single `tasks` table (see
# common/taskstore.py and deployments/cloudsql.tf). This tool TRUNCATEs that table so the next
# pipeline run starts with an empty task store. It does NOT touch the GCS memory bank — use
# clear_memory.sh for that.
#
# Connection: the project's own venv (asyncpg + the Cloud SQL Python Connector) connects
# IAM-authenticated over ADC — NO psql client and NO proxy binary required. The DB password
# comes from Secret Manager (the same version Cloud Run mounts).
#
# PREVIEW-FIRST: a plain run only reports the current row count and changes nothing.
# Re-run with CONFIRM=1 to actually TRUNCATE. Truncation is irreversible.
#
# Usage:
#   ./clear_taskstore.sh                # preview: current tasks row count, changes nothing
#   CONFIRM=1 ./clear_taskstore.sh      # TRUNCATE the tasks table
#   TABLE=tasks ./clear_taskstore.sh    # override the table name (default: tasks)
#   PYTHON=/path/to/python ./clear_taskstore.sh   # override the interpreter
#
# Config (env overrides): INSTANCE, DB, DB_USER, SECRET, TABLE, PYTHON
#
# Requires: gcloud with ADC (roles/cloudsql.client on the instance + secretmanager.secretAccessor
#           on the password secret) and the project's .venv (asyncpg + cloud-sql-python-connector).
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

INSTANCE="${INSTANCE:-klara-nonprod:europe-west6:kga-taskstore}"
DB="${DB:-taskstore}"
USER_NAME="${DB_USER:-taskstore}"
SECRET="${SECRET:-kga-db-password}"
TABLE="${TABLE:-tasks}"
PROJECT="${INSTANCE%%:*}"
CONFIRM="${CONFIRM:-0}"

command -v gcloud >/dev/null || { echo "gcloud not on PATH" >&2; exit 1; }

# Locate the project's venv python (asyncpg + the connector live there), or fall back to $PATH.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for p in ../../.venv/Scripts/python.exe ../../.venv/bin/python; do
    [ -x "$p" ] && PYTHON="$p" && break
  done
fi
PYTHON="${PYTHON:-python}"

echo "==> fetching DB password from Secret Manager ($SECRET)"
PASSWORD="$(gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT")"

INSTANCE="$INSTANCE" DB="$DB" DB_USER="$USER_NAME" DB_PASSWORD="$PASSWORD" TABLE="$TABLE" CONFIRM="$CONFIRM" \
"$PYTHON" - <<'PY'
import asyncio
import os
import sys


async def main():
    try:
        from google.cloud.sql.connector import create_async_connector
    except ImportError:
        sys.exit("the Cloud SQL Python Connector is not installed in this interpreter "
                 "(pip install 'cloud-sql-python-connector[asyncpg]')")

    inst, db = os.environ["INSTANCE"], os.environ["DB"]
    user, pw = os.environ["DB_USER"], os.environ["DB_PASSWORD"]
    table, confirm = os.environ["TABLE"], os.environ["CONFIRM"] == "1"

    connector = await create_async_connector()  # must be created inside the running loop
    try:
        conn = await connector.connect_async(inst, "asyncpg", user=user, password=pw, db=db)
    except Exception as exc:  # noqa: BLE001
        await connector.close_async()
        sys.exit(f"could not connect to {inst}: {exc}")
    try:
        if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}"):
            print(f'\nTable "{table}" does not exist yet (no tasks persisted) — nothing to truncate.')
            return
        rows = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        print(f"\nTask store: {inst}  |  db={db}  |  table={table}")
        print(f"Rows:       {rows}")
        if confirm:
            print("Mode:       TRUNCATE (CONFIRM=1) -- irreversible")
            await conn.execute(f'TRUNCATE TABLE "{table}"')
            print(f'\nDone -- truncated {rows} row(s); "{table}" is now empty.')
        else:
            print("Mode:       PREVIEW (dry-run) — nothing changed.")
            print("\nRe-run to truncate:  CONFIRM=1 ./clear_taskstore.sh")
    finally:
        await conn.close()
        await connector.close_async()


asyncio.run(main())
PY
