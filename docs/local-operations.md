# Резервная копия собственного локального стенда

Операция относится к отдельно выбранным Compose project/state. Имя исходного
проекта, список его контейнеров и mounts проверяют через `docker inspect`.
У нового проекта должны отсутствовать все целевые volumes. Прежние volumes,
state и исходную установку сохраняют; `down -v` и общий prune не нужны.

## Согласованный backup

Сначала завершите проверки и остановите Workspace штатным native способом.
Убедитесь, что native grading jobs закончились, все Workspaces имеют состояние
`stopped`, а host удалил их session containers. Согласуйте паузу записей Moodle,
включая операторский импорт оценок. Сохраните список native user/course/instance
IDs, ответы и баллы для последующего сравнения.

Остановите входные приложения своего проекта: proxy, Gateway, Bridge, Moodle,
Workspace host и public course-site. Проверьте отсутствие незавершённых native
server jobs, sync/regrade и external grading jobs. Затем корректно остановите
PL целиком: его `start-pl.sh` завершает native процессы и PostgreSQL. Baseline
для последующего сравнения снимается после этой границы, а не до остановки
writers.

Для PL временно запускают только PostgreSQL из того же image с прежним PG
volume, без PL node/cron/server jobs и без сети. Убедитесь, что исходный PL
остановлен и другой контейнер не использует этот volume. Временный сервер
запускают штатным `pg_ctl` от `postgres`, повторно проверяют отсутствие активных
jobs, читают baseline и снимают custom-format dump. Пример dump из уже готового
PG-only helper и из отдельной Moodle PostgreSQL, у которой Moodle остановлена:

```sh
umask 077
docker exec OWN-pg-backup pg_dump -U postgres -d postgres -Fc --no-owner \
  > /private/backup/pl.dump
docker compose --env-file /private/stack/.env -f compose.yml -f compose.auth.yml \
  exec -T moodle-db pg_dump -U moodle -d moodle -Fc --no-owner > /private/backup/moodle.dump
```

Каталог backup имеет режим 0700, файлы — 0600 и доступны оператору.
Путь backup находится вне Git; dump содержит users, ответы и ключи приложения.
Проверьте успешный exit code обоих `pg_dump`, затем корректно остановите временный PG-only helper через `pg_ctl`,
Moodle PostgreSQL и выделенный Workspace daemon. Теперь архивируйте постоянные
`courses`, `files`, `s3`, `moodle-data`, `gateway-data`, полный `STATE_DIR` с jobs,
внешние PL/Bridge/Gateway configs и их secrets, `.env`, public site releases и
ссылку `current`. Для root-owned файлов используйте контейнер с read-only source
mount и отдельным backup mount. Обычный tar сохраняет `.git`, `.pl-seed`, права
и относительные ссылки. Запишите фактические image digests/config IDs и checksums
архивов. PostgreSQL volumes в файловые архивы не включают: их данные находятся
в двух dumps. Копия работающего PG datadir резервной копией не считается.

## Новый project/state

Восстановление использует другие имя проекта, volumes и host state. Подготовьте
именно те PL/Moodle/PostgreSQL/Gateway/Workspace images, которые записаны в
backup; mutable tag сам по себе не доказывает одинаковые bytes. PostgreSQL
в приёмке имеет major 17. Сначала проверьте checksums, затем распакуйте обычные
файлы/state/configs в новые каталоги и volumes с прежними владельцами и режимами.

PL PostgreSQL восстанавливают до запуска приложения. Пустой целевой volume
обязательно подключают как `--mount type=volume,source=NEW_PROJECT_postgres,target=/var/postgres,volume-nocopy`.
Без `volume-nocopy` Docker переносит PG files из image и каталог уже непустой
до `initdb`. Только после этого в том же PL image создают пустой cluster
штатным `initdb`, временно запускают только PostgreSQL через
`pg_ctl`, выполняют `pg_restore -U postgres -d postgres --no-owner --no-privileges
--exit-on-error --single-transaction /backup/pl.dump` и корректно останавливают
его. Native migrations затем выполняет обычный `start-pl.sh`.
Это другой cluster, а не копия физического PG volume.

Для Moodle сначала запустите только `config-init` и `moodle-db` нового проекта,
используя восстановленный password file. В созданную пустую БД `moodle`
выполните `pg_restore -U moodle -d moodle --no-owner --no-privileges
--exit-on-error --single-transaction` из `moodle.dump` через stdin. Восстановление
от имени `moodle` сохраняет рабочее владение объектами. Только после успешного
restore запускают Moodle и остальные приложения.

В новом `.env` изменяются Compose project и абсолютные host paths для state,
jobs, configs и public site. Внутренние native `/course/...`, UUID, ключи,
Moodle registration и bindings сохраняются. Для проверки прежних LTI UID
используйте прежние HTTPS origins: исходный собственный proxy уже остановлен,
поэтому новый проект может занять его порты. Произвольная смена issuer не является
прозрачным восстановлением identity. Основные dev-preview 8088/8089 не участвуют.

Workspace daemon нового проекта получает только его socket, image store и
jobs directory. Его daemon ID отличается от системного Docker. Native host
видит тот же абсолютный jobs path, который монтирует выделенный daemon. При
использовании официального `docker:dind` entry point его `/tmp` mount не должен
закрывать вложенный jobs bind: задайте tmpfs `/tmp` явно до nested bind либо
разместите jobs вне `/tmp`. Не обходите штатную cgroup-инициализацию `dind`.
Для длинного host path socket используйте короткий путь внутри daemon
(`docker exec … docker -H unix:///run/…/docker.sock`): Unix socket address имеет
ограничение длины, хотя сам bind source может находиться глубже.
Editor не публикуется на host; proxy использует private адрес daemon в Docker
network. Права native Workspace files остаются UID/GID 1001.

## Проверка восстановленной установки

Сверьте native user/course/instance IDs, UUID из course files, ключи, ответы,
баллы и bindings с исходным списком. Выполните свежий Moodle login и подписанный
LTI launch для двух студентов и преподавателя; UID и права должны сохраниться.
Проверьте public сайт побайтно, прежнюю native сдачу через преподавательские
file URLs, Git A→B/HEAD/index/worktree из Workspace и новую сдачу с настоящим
grader. Сверьте перенесённые Moodle grades и контрольные чужие ячейки.
Повторный `up` не должен создавать других пользователей или менять native IDs.
Только эти проверки подтверждают восстановление; готовность контейнеров сама
по себе не заменяет их. Результат локального опыта не подтверждает VM target,
DNS/TLS или перенос прежних пользовательских оценок.
