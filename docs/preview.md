# Локальный dev preview

`go-task prepare COURSE=java COURSE_ROOT=/absolute/Java` готовит сайт и native пакет, `go-task up COURSE=java`
запускает их. Для System Practice используется `COURSE=system-practice` с
явным `COURSE_ROOT=/absolute/System-Practice`. Перед сборкой установите Quarto
packages штатными командами курса; Local их не устанавливает.
По умолчанию сайт и `/pl/` доступны на `http://127.0.0.1:8088` для Java,
на `http://127.0.0.1:8089` для System Practice.

Низкоуровневый интерфейс для диагностики из каталога Local:

```sh
python3 scripts/preview.py up --course java --output-root "$PWD/state/builds"
python3 scripts/preview.py ready --course java
python3 scripts/preview.py status --course java
python3 scripts/preview.py load --course java
python3 scripts/preview.py down --course java
```

Если задан другой `--output-root`, `--state-dir`, `--platform`, `--project`
или `--port`, передавайте те же параметры следующим командам. `up` принимает
готовые выходы и не запускает render/export. `load` загружает подготовленный
выпуск в уже работающем runtime. `ready` проверяет HTTP PL и сайта и требует
успешного состояния загрузки; результат server job проверяют `up` и `load`.

Platform CLI и default Community image поставляются submodule `deps/platform`
(`git submodule update --init deps/platform`). Preview берёт image через
стандартный Compose `extends` того же producer fragment, что production.
`PL_PREVIEW_IMAGE` независимо переопределяет preview image; production `PL_IMAGE`
и `.env` не влияют на этот выбор. `--platform` выбирает другой явный checkout
и для CLI, и для Compose fragment.

Самостоятельный `compose.preview.yml` использует существующий Community image
с native `/PrairieLearn/scripts/init.sh`, `devMode:true`, `hasShib:false` и
штатным dev-входом PrairieLearn. В браузере автоматически открывается
вымышленный native пользователь `Dev User`; штатное меню позволяет переключить
staff/student view. Это приёмка dev preview. Moodle/LTI и Workspace проверяются
отдельно.

Preview привязан только к loopback HTTP. У него собственные Compose projects
`pl-preview-java` и `pl-preview-system-practice`, volumes и каталоги
`state/preview-java`, `state/preview-system-practice`. Production `.env` и
production entrypoint не используются. `down` сохраняет volumes и ключи.

Весь стабильный родитель `state/builds` смонтирован в `/course` и `/output`.
Loader всегда передаёт `/course/java/current` либо
`/course/system-practice/current`. Подготовка переключает только `prepared`.
Перед загрузкой `current` направляется на native-кандидат, после успеха
`active` переключает принятый выпуск. Nginx читает `COURSE/site`, следующий
`active/site`, через тот же родительский mount. До успеха загрузки он продолжает
отдавать прежний сайт. Подготовка и загрузка сериализуются одним `.prepare.lock`.
Частные checks и рабочие исходники сборки должны находиться вне этого родителя.

Platform `tools/dev-load-course.mjs` до соединения с БД проверяет реальный
native config, один раз вызывает штатный `/pl/loadFromDisk` и ожидает
`Success` именно возвращённого server job. Числовые course/instance IDs берутся
из native БД. Redirect, HTTP readiness и запущенный контейнер сами по себе
успехом загрузки не считаются. Штатный sync очищает element/extensions cache.
При ошибке команда завершается ненулевым кодом; ссылка на native job позволяет
увидеть диагностику частично применённого состояния. Автоматического повторного
запуска job и отката БД нет.

`load-status.json` хранит результат попытки и названия кандидата и принятого
выпуска. При отказе прежний сайт сохраняется, а native DB может быть частично
обновлена. Команда `status` показывает это состояние, `ready` не объявляет его
готовым. Возврат старого disk-каталога сам по себе не восстанавливает native DB.

Истечение времени ожидания клиента не завершает server job. Его ID и исходное
намерение отправки сохраняются отдельно в `state/preview-COURSE/jobs/preview-load-COURSE-ATTEMPT.json`.
Следующий `up`/`load` продолжает ожидание того же задания без повторного запроса
загрузки и без смены его native-входа. Если за это время появился другой
`prepared`, он остаётся кандидатом для следующего явного запуска после завершения
первого. Подтверждённый terminal Error/Stopped допускает новую попытку.
Каждая попытка получает собственный файл; старые записи сохраняются, поэтому
запоздавший процесс не перезаписывает состояние следующей попытки. Точный путь
показан в `load-status.json`. Файл содержит служебные IDs без секретов и доступен
пользователю хоста для чтения; родительский каталог preview имеет права `0700`.

Если соединение оборвалось между отправкой запроса и получением ID, исход
неизвестен. Автоматическая повторная отправка заблокирована. Нужно проверить
native job в интерфейсе PrairieLearn и завершение прежней попытки до ручного
восстановления этого служебного состояния; удалять файл вслепую нельзя.
