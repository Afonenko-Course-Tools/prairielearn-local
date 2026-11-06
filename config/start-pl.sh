#!/bin/bash
# Штатные support/migration/start без автоматического общего Workspace host.
set -euo pipefail
case "${HOST_JOBS_DIR:-}" in
  /*) ;;
  *) echo 'HOST_JOBS_DIR должен быть абсолютным путём хоста' >&2; exit 64 ;;
esac
ln -sfn "${PL_CONFIG_PATH:-/run/base-pl/config.json}" /PrairieLearn/config.json
cd /PrairieLearn
make -s start-support
make migrate
setsid make start &
pl_pid=$!
stop() {
  trap - EXIT TERM INT
  kill -TERM -- "-$pl_pid" 2>/dev/null || true
  wait "$pl_pid" 2>/dev/null || true
  su postgres -c 'pg_ctl stop -m fast -w' || true
}
trap stop EXIT
trap 'exit 0' TERM INT
wait "$pl_pid"
