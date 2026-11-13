#!/bin/sh
set -eu
# Доверие к CA меняется только внутри нового контейнера, не на машине пользователя.
if [ -n "${LOCAL_CA_FILE:-}" ]; then
  test -r "$LOCAL_CA_FILE"
  cp "$LOCAL_CA_FILE" /usr/local/share/ca-certificates/local-stack.crt
  update-ca-certificates >/dev/null
fi
if [ "${1:-}" = bootstrap ]; then
  mkdir -p /var/moodledata
  chown www-data:www-data /var/moodledata
  # Moodle CLI выполняется от того же пользователя, что и Apache.
  # init-config должен дать www-data доступ к входным файлам, без изменения их содержимого.
  runuser -u www-data -- php /usr/local/lib/moodle-bootstrap.php --install
  exec runuser -u www-data -- php /usr/local/lib/moodle-bootstrap.php
fi
exec docker-php-entrypoint "$@"
