# Локальная инфраструктура PrairieLearn и Moodle

Отдельный Docker Compose-стенд с PrairieLearn Community, тестовой Moodle, постоянными хранилищами и HTTPS-прокси. Gateway и Bridge подключаются только с уже подготовленными штатными конфигурациями. Базовый запуск не требует курса, registry, репозитория исходников или будущей CI/CD.

**Готовность:** отдельная локальная приёмка чистого запуска, TLS/Moodle/LTI, ролей, Workspace и backup/restore выполнена на точных runtime images. Результаты и границы описаны в [отчёте приёмки](docs/local-acceptance-20261111.md). Для новой установки оператор повторяет её проверки; локальный опыт не заменяет hosted delivery или выбранный VM target.

Для отдельного loopback dev-preview Java и System Practice доступны
`go-task prepare COURSE=java` и `go-task up COURSE=java`. Подготовка сохраняет
кандидата, успешная native-загрузка активирует его сайт. Этот режим и его
проверки описаны в [инструкции preview](docs/preview.md) и
[сборке и доставке](docs/build-delivery.md). Production Git-sync и готовый student-сайт описаны в
[локальном production-маршруте](docs/production-local.md). Быстрый контроль Local — `go-task check`.

## Требования

- Linux/amd64, Docker Engine и Docker Compose v2.
- Git; свободные локальные порты. Python и OpenSSL для начальной настройки выполняются внутри образа.
- Отдельные Compose project, state и host jobs. Не используйте хранилища действующей установки.
- Достаточная свободная память для PL, PostgreSQL и Moodle. Перед параллельным запуском оператор оценивает память и текущие grader-задачи; сумма лимитов контейнеров не заменяет эту проверку.

Приложения поставляются опубликованными образами. Moodle собирается из закреплённого официального источника через Dockerfile этого репозитория. Здесь нет копии Java/System Practice, Quarto-рендера, проверки решений или своего формата курса.

## Подготовка

```sh
git clone https://github.com/Afonenko-Course-Tools/prairielearn-local.git
cd prairielearn-local
docker compose up -d --build --wait
docker compose ps -a
```

Базовый запуск использует значения по умолчанию и не требует `.env`. При необходимости скопируйте `.env.example` в `.env` **до запуска** и измените имя проекта, адреса, порты или пути. `STATE_DIR` по умолчанию — `./state`, host jobs — `${PWD}/state/jobs`; Compose запускают из каталога репозитория. Путь jobs должен быть абсолютным и доступным на том же Docker-хосте. Для повторного запуска используйте тот же каталог, имя проекта и state.

`BOOTSTRAP_ADMIN_UID` по умолчанию — `servicebootstrap@local.invalid`. Это постоянный служебный actor для первоначального native administrator и последующих внешних административных операций. Это не аккаунт Moodle, не LTI UID и не пользователь с автоматически созданным паролем.

Одноразовый сервис `config-init` создаёт ключи, тестовые аккаунты, сертификат и обычные конфигурации приложений в state. Существующие ключи и аккаунты при повторе не заменяются. Секреты не входят в Git; не публикуйте `.env`, state и журналы с закрытыми данными. Если порты заняты, задайте разные свободные `PL_HTTPS_PORT` и `MOODLE_HTTPS_PORT` в `.env` и повторите запуск, как описано ниже. Завершение `up --wait` ещё требует проверки оператором, описанной ниже.

## Адреса и TLS

По умолчанию: [Moodle](https://moodle.infra.localhost:19443) и [PrairieLearn](https://pl.infra.localhost:19444). Проверьте разрешение этих имён в loopback на ноутбуке; при необходимости настройте его средствами ОС. Отдельные hostname изолируют cookies от прежних localhost-стендов; одного другого порта для этого недостаточно.

Локальный CA хранится в `STATE_DIR/tls/ca.crt`. Если state создан контейнером и недоступен host-пользователю, скопируйте только публичный сертификат:

```sh
docker compose cp proxy:/state/tls/ca.crt ./local-ca.crt
```

Пользователь самостоятельно проверяет его и явно добавляет в доверенные штатными средствами своей ОС и браузера. Скрипты не меняют системное хранилище доверия. Не отключайте проверку сертификата и не обходите предупреждения TLS.

Логины и пароли трёх тестовых аккаунтов Moodle (роли admin, student и teacher) находятся в `STATE_DIR/moodle-accounts.json`. Для локального просмотра файла с контейнерными правами:

```sh
docker compose exec moodle cat /state/moodle-accounts.json
```

Не публикуйте этот вывод. Аккаунты относятся к отдельной локальной Moodle. Moodle administrator не становится автоматически administrator PrairieLearn. Публикация курса, регистрация LTI и разрешённые роли PL настраиваются отдельно.

## Начальный local administrator

После миграций одноразовый bootstrap использует native `models/user.selectOrInsertUserByUid` и существующий `administratorAdmins.sql` из опубликованного PL через штатный SQL loader. Выдача роли и аудит остаются native; операция защищена штатным lock и транзакцией.

Источником истины служит native БД. Если пользователь с `BOOTSTRAP_ADMIN_UID` уже является native administrator, bootstrap завершает проверку без создания пользователя, повторного grant или изменения прав. Новая роль создаётся только при отсутствии пользователей, курсов и других administrators. Служебные справочники самой БД не считаются пользовательской историей.

Другой UID в непустой БД не получает новую роль; отозванное право не восстанавливается автоматически. Отдельного файла identity или разрешения первого запуска нет. Этот скрипт не создаёт курсы, Bridge bindings, регистрации Moodle, пользователей группы или зачёты.

## Повторный старт и остановка

Для уже работающего собственного проекта:

```sh
docker compose up -d --build --wait
```

Используйте прежние Compose project и state; для подключённых auth/Workspace повторяйте тот же набор `-f` во всех командах. Постоянные volumes и state сохраняют PostgreSQL, файлы PL, Moodledata, ключи и, при подключённом auth, SQLite Gateway.

Для смены портов измените `PL_HTTPS_PORT` и/или `MOODLE_HTTPS_PORT` в `.env` и снова выполните `docker compose up -d --build --wait`. Это относится и к первому запуску, который остановился из-за занятого порта proxy: сохраняйте уже созданные state и volumes. Compose и `config-init` согласуют новые порты публикации, Nginx, healthcheck и базовые public origins; PL пересоздаётся для чтения обновлённой конфигурации. Обычный `restart` не применяет изменения `.env`.

Смена порта своей тестовой Moodle обновляет её URL в существующем `STATE_DIR/moodle/registration.json`, включая issuer URL. Сохраняются HTTPS, hostname, пути URL, native IDs, clientId, deploymentId, contextId, subjects и ключи. Смена порта PL также обновляет URL существующего тестового LTI tool/activity. Это узкое обновление портов сохранённой fixture; смена hostname или регистрационных идентификаторов им не разрешается.

```sh
docker compose stop
docker compose start
```

Удаление контейнеров своего проекта без удаления данных:

```sh
docker compose down
```

Не добавляйте `-v` и не удаляйте `STATE_DIR`: это уничтожает историю и ключи. Для резервирования используйте штатный согласованный dump PostgreSQL и копию постоянных файлов/state либо полный холодный снимок после корректной остановки. Простое копирование файлов работающей PostgreSQL резервной копией не считается.

## Курсы и вход из Moodle

Для базового production Compose публикация и обновление готовых курсов выполняются
штатными средствами Platform отдельно от инфраструктурного `up`. Dev-preview
использует отдельные Task-команды и dev loader Platform. В репозитории нет
собственного импортёра или registry. Текущие административные команды и guards
описаны в [документации Platform](https://github.com/Afonenko-Course-Tools/prairielearn-platform/blob/main/docs/proxmox-pilot.md).

Gateway и Bridge используют предоставленные оператором существующие native конфигурации с фактическими IDs/UUID и регистрацией Moodle. Начальный стенд не придумывает их и не создаёт поддельный delivery. Базовый HTTPS подтверждает доступность инфраструктуры. Вход пользователя в PL и рабочая LTI-привязка требуют отдельной auth-конфигурации и опубликованного курса; базовый запуск их не обещает. Auth подключают явно через `docker compose -f compose.yml -f compose.auth.yml …` с готовыми конфигурациями, описанными в [config/README.md](config/README.md).

После смены порта Moodle обновите параметры регистрации в обычной конфигурации Gateway по актуальному `STATE_DIR/moodle/registration.json` и согласуйте адреса с подключённой auth-конфигурацией. Скрипты стенда не изменяют предоставленные извне конфигурации Gateway, Bridge и PL. Если меняется порт PL, их адреса тоже проверяют и обновляют штатными средствами перед повторным запуском auth override.

Образы grader и Workspace-сессий задаёт сам курс. Этот репозиторий не меняет их на другой Java/Workspace image и не считает импорт или публикацию проверкой решений. Обновление приложения и изменение конфигурации не должны сбрасывать volumes, state или исторические ответы. Перед пересозданием контейнеров дождитесь завершения текущих проверок. Изменение bind mount требует пересоздания контейнера; один `restart` его не обновляет.

## Workspace

Workspace по умолчанию выключен. Native Workspace host очищает контейнеры по общим меткам, поэтому отдельный `compose.workspace.yml` требует выделенного Docker daemon и явного `WORKSPACE_DOCKER_SOCKET`. Override подключают через `docker compose -f compose.yml -f compose.workspace.yml …` с готовым native PL config; обязательные параметры описаны в [config/README.md](config/README.md). Не направляйте его на daemon действующего Workspace-стенда.

После подключения override оператор отдельно проверяет запуск, Save, Stop/Resume, прежние файлы и Git после возобновления. Настройки host jobs и портов должны соответствовать Docker-хосту. Само наличие сервиса в Compose не подтверждает сохранность сессии.

## Лёгкие проверки

Без Docker:

```sh
node --check scripts/bootstrap-admin.mjs
node --test tests/bootstrap-admin.test.mjs
python3 -m py_compile scripts/init-config.py
php -l scripts/moodle-bootstrap.php
```

Проверки initial administrator заменяют native зависимости моделями в памяти: они проверяют первый grant, read-success существующего administrator и отказы без изменения прав, но не соединение с настоящей БД. Source-проверки не заменяют отдельную приёмку пустых хранилищ, повторного `up`, TLS и, при подключении, LTI/Workspace.
