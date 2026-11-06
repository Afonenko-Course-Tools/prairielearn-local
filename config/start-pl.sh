#!/bin/bash
# Штатные support/migration/start без автоматического общего Workspace host.
set -euo pipefail
case "${HOST_JOBS_DIR:-}" in
  /*) ;;
  *) echo 'HOST_JOBS_DIR должен быть абсолютным путём хоста' >&2; exit 64 ;;
esac
export PGDATA=/var/postgres
pl_pid=''
stop() {
  local exit_status=$?
  trap - EXIT TERM INT
  if [[ -n "$pl_pid" ]]; then
    kill -TERM -- "-$pl_pid" 2>/dev/null || true
    wait "$pl_pid" 2>/dev/null || true
  fi
  if [[ -f "$PGDATA/PG_VERSION" ]]; then
    local pg_status=0
    su postgres -c 'pg_ctl -D /var/postgres status' >/dev/null 2>&1 || pg_status=$?
    case "$pg_status" in
      0)
        if su postgres -c 'pg_ctl -D /var/postgres stop -m fast -w -t 30'; then
          :
        else
          local stop_status=$?
          echo "Не удалось остановить PostgreSQL (pg_ctl: $stop_status)" >&2
          if (( exit_status == 0 )); then exit_status=$stop_status; fi
        fi
        ;;
      3) ;; # Кластер уже остановлен.
      *)
        echo "Не удалось проверить PostgreSQL (pg_ctl: $pg_status)" >&2
        if (( exit_status == 0 )); then exit_status=$pg_status; fi
        ;;
    esac
  fi
  exit "$exit_status"
}
# Cleanup действует и при ошибке частичного start-support или migrate.
trap stop EXIT
trap 'exit 0' TERM INT
ln -sfn "${PL_CONFIG_PATH:-/run/base-pl/config.json}" /PrairieLearn/config.json
cd /PrairieLearn
make -s start-support
make migrate
setsid make start &
pl_pid=$!
wait "$pl_pid"
