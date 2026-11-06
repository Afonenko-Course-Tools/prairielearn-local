# Инфраструктурная конфигурация

Базовый `compose.yml` не принимает и не импортирует курсы. Он запускает PL с пустым постоянным каталогом `/course`, тестовую Moodle, HTTPS-прокси и узкую первоначальную настройку native administrator. Получение артефактов и штатные Platform bootstrap/sync остаются за границей этого репозитория.

`config-init` получает переменные, уже раскрытые самим Docker Compose. Собственного `.env` parser нет. Он создаёт только локальные ключи PL, тестовые Moodle accounts/password, TLS и обычные конфигурации серверов. Повторная инициализация не заменяет ключи и аккаунты. Системное доверие CA не устанавливается.

По умолчанию используются отдельные `pl.infra.localhost:19444` и `moodle.infra.localhost:19443`. Отличающиеся hostname сохраняют изоляцию browser cookies от других localhost-стендов: один лишь другой порт её не даёт.

Состояние монтируется каталогом `/state`; конфигурационные файлы не требуются на этапе создания контейнеров. PL и admin получают только read-only config-каталог `/run/base-pl` и подключают его файл ссылкой в штатный `/PrairieLearn/config.json` после завершения init. Nginx читает `/state/nginx.conf` после готовности PL и Moodle. PostgreSQL Moodle читает password-файл из read-only каталога после init. Это устраняет зависимость первого `up` от заранее существующих generated bind files.

Moodle пишет публичную регистрацию в `/state/moodle/registration.json`. Отдельный output-каталог принадлежит www-data; accounts и DB password доступны группе 33 только для чтения. Корень state даёт traversal, private TLS key остаётся 0600. Наличие тестовой Moodle activity ещё не означает работающий PL LTI-вход.

## Необязательный auth override

`compose.auth.yml` подключается отдельно обычным `-f`. Он принимает готовые native `PL_CONFIG_FILE`, `BRIDGE_CONFIG_DIR/config.json` с реальными bindings и его tokenFile, `GATEWAY_CONFIG_DIR/runtime.json` с его secret/CA-файлами и `handoff-auth.conf`. Конфигурации должны согласовываться с опубликованными приложениями и сохранять прежние session/database keys. Gateway config должен быть доступен штатному UID 1000, его SQLite хранится в отдельном volume. Ни course IDs, ни регистрации Gateway здесь не выдумываются и не генерируются.

Bridge запускается после native admin, Gateway — после readiness Bridge. Auth Nginx использует подтверждённый handoff и только synthetic preauth cookie в native callback. Базовый Nginx вообще не разрешает имя отсутствующего Gateway: `/gateway/` закрыт. Auth override не выполняет импорт курса.

## Необязательный Workspace override

`compose.workspace.yml` читается только при явном `-f`, поэтому базовый Compose не требует Workspace socket. Нужны готовый native `PL_CONFIG_FILE` с Workspace settings и отдельный `WORKSPACE_DOCKER_SOCKET`. Native worker очищает контейнеры по общим меткам и не должен делить Docker daemon с работающим стендом. Проверка выделенного daemon и реальное Save/Stop/Resume — отдельная приёмка оператора.

Host jobs задаётся обычной подстановкой Compose, по умолчанию `${PWD}/state/jobs`, внутри контейнеров `/jobs`. Путь должен быть одинаков для PL, worker и Docker daemon, который запускает session/grader containers. Образы заданий не переопределяются: они принадлежат будущей поставке курса.

Ни Docker build/pull/up, ни чистый запуск этими исходниками ещё не подтверждены. Только назначенный оператор выполняет их после review и проверки свободной памяти; основной рабочий стенд не затрагивается.
