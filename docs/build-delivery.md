# Сборка и доставка готового курса

На Arch пакет `go-task` устанавливает команду `go-task`. Системные `quarto`,
`tsc`, `pyright`, `shellcheck`, Python с PyYAML/jsonschema должны быть в PATH.
Java и System Practice размещаются рядом с Local, Platform и полным набором
исходников расширений; иной checkout задаётся через `COURSE_ROOT`.

```sh
go-task prepare COURSE=java
go-task up COURSE=java
```

Для System Practice используется `COURSE=system-practice`. Команда `prepare`
копирует исходники во временный checkout, применяет обычный Quarto profile
с локальным URL, вызывает course targets `check`, `render`, `export` и принимает
структурную проверку штатного Platform exporter. Один корневой student render
строит сайт; отдельный export выполняет полный author capture для native.
Полный HTML-сайт перед export не строится.

`PROVIDERS_ROOT` по умолчанию указывает на родителя Local. Полные packages
в одноразовой копии устанавливаются из working trees соседних расширений;
неполный набор вызывает явный отказ. `PROVIDERS_ROOT=/абсолютный/путь`
выбирает иной полный набор. Выбранный mode и путь печатаются перед сборкой. Mapping
берётся штатным installer из `providers.json`; HEAD и dirty diff печатаются
в журнал. Канонические исходники и их установленные packages сохраняются.
Для standalone checkout `PROVIDERS_ROOT=''` явно выбирает установленный
набор packages самого курса. Совместимость этого набора квалифицируется
отдельно; успех сборки с соседними working trees её не подтверждает.

Готовые выдачи находятся под `state/builds/COURSE`. `prepare`, `receive` и
`resume-export` переключают только `prepared`, кандидата на загрузку.
`active` обозначает последний успешно загруженный выпуск, `site` следует его
student-сайту. Подготовка нового кандидата сохраняет работающий сайт.
`up` передаёт native-кандидат через постоянный путь `current`, ждёт успешного
server job и только затем переключает `active`. Старые выпуски сохраняются.
При первом запуске принятый сайт появляется после успешной загрузки.
Промежуточные исходники и неудавшиеся outputs находятся в `state/builds-work`.
При отказе disposable checkout сохраняется вместе с готовым student-сайтом.
После исправления exporter можно выполнить только экспорт:

```sh
go-task resume-export COURSE=java WORK_DIR=/абсолютный/путь/state/builds-work/java/.prepare-ID
```

Повтор использует сохранённые checkout, packages, профиль и student bytes.
Изменения исходного дерева providers по тому же пути не устанавливаются повторно.
Другой `SITE_URL` или `PROVIDERS_ROOT` отклоняется; применение изменений
render-входов требует нового `prepare`. Это узкий повтор экспорта текущим
Platform, например после исправления его writer. Старые незавершённые группы
без сохранённых параметров требуют нового `prepare`.
Успешный resume удаляет disposable исходники и публикует кандидата с сохранённым
сайтом и новым native output. Пути releases,
work и private checks отклоняются при ссылках в любом компоненте; controller
каталоги проверяются физически вне runtime mount до публикации.
Private checks, runtime registry, reports и logs хранятся в `state/builds-checks`,
вне родителя, который монтируется в runtime. Ссылки на них доступны controller.
Каждая prepare-группа использует собственный Quarto cache.

`up` берёт готовую выдачу, ожидает runtime и фактический результат native load.
Повторная команда ничего не пересобирает. `go-task status` проверяет состояние,
`go-task down` останавливает контейнеры с сохранением state. Для смены origin
при сборке можно задать `SITE_URL=http://127.0.0.1:8088/`; generated HTML вручную
не переписывается. Functional profile `preview` передаётся также в native
author capture. Временный profile меняет `reference-catalog.imports.*.base-url`
только для imports внутри canonical URL этого же курса; суффикс пути
сохраняется. В disposable `_quarto.yml` переносятся внутренние `href` и
`logo-href` в штатных `book.navbar`/`website.navbar`; структура меню, подписи,
controls, sidebar и внешние ссылки сохраняются. Navbar не дублируется в
profile, поскольку Quarto объединяет его массивы. Ссылки в учебной прозе
сохраняются. Авторские поля профиля `full` сохраняются.

```sh
go-task verify COURSE=java
```

Это отдельные полные проверки declared и delivery тех же native/checks/registry.
Обе стадии запускаются также при отказе первой; ненулевой код сохраняется.
Отчёты и grader logs остаются на controller. Source checks в `prepare`
не заменяют эти проверки и отдельную runtime приёмку.

## Готовая CI поставка

Java и System Practice workflows вызывают те же course targets. Producer сохраняет `delivery.tar`
с `site/` и `native/`, а также `site.tar` и `native.tar` для отдельных consumers.
Обычный tar сохраняет hidden `.pl-seed` и режимы файлов. Отдельный controller
artifact содержит `native-checks.json` и `runtime-profiles.json`. Consumer
скачивает actual artifact IDs producer и выполняет `go-task verify` без сборки.
Повтор consumer job не вычисляет artifact names через собственный run attempt.

После скачивания двух архивов на controller:

```sh
mkdir -p /tmp/course-release
tar -C /tmp/course-release -xf delivery.tar
tar -C /tmp/course-release -xf controller.tar
go-task receive COURSE=java BUILD_DIR=/tmp/course-release
go-task up COURSE=java
```

`receive` проверяет package integrity штатным checker и сохраняет готовые
bytes как `prepared` без render/export. Последующий `up` загружает и активирует
этот выпуск. Checks не входят в student/native деревья. URL
публикации остаётся тем, который был выбран при сборке.

## Ansible

`ansible/preview.yml` выполняется один раз на controller с local connection.
Он использует установленные инструменты Arch и обычные `go-task prepare/up`.
Например, `ansible-playbook ansible/preview.yml -e course=java`.
Для готовой выдачи задайте `-e prepare_course=false`.

`ansible/deploy.yml` потребляет готовый student `site.tar` и уже опубликованный
native Git course. Нужны inventory group `course_cd`, `pl_url`, numeric
`course_id`, `pl_container`, полный `expected_native_commit`, `site_archive`,
абсолютный `site_root`, уникальный `site_release` и controller environment
`COURSE_CD_TOKEN`. Архив сайта и ожидаемый native Git commit выбираются из
одного проверенного выпуска. Команда не устанавливает это соответствие для
произвольно выбранных оператором входов. Native release branch сохраняется
неизменной на время доставки; внешние native writers исключаются оператором.
Web server должен обслуживать
`site_root/current`; готовый loopback consumer предоставляет необязательный
`compose.site.yml` с `SITE_ROOT=site_root`. Обычная Git-публикация и настройка
consumer описаны в [production-маршруте](production-local.md).
На target нужны Docker CLI и доступ к контейнеру native PrairieLearn.

Play сначала проверяет архив на controller и распаковывает сайт в новый
каталог выпуска. Повторное использование каталога отклоняется. Доставки одного
`site_root` сериализуются host lock. Затем выполняется один POST sync и только
GET до конечного статуса. После `Success` read-only helper под штатным native
course lock проверяет именно этот job, сохранённый `courses.commit_hash`,
отсутствие sync errors и чистый Git HEAD. Несовпадение с ожидаемым commit
останавливает переключение сайта. Helper использует native lock infrastructure,
не изменяет данные курса и не добавляет публичного REST endpoint.

При отказе сайт сохраняется; native sync требует штатной диагностики уже
применённого состояния. Остаточный каталог неудавшегося выпуска сохраняется,
для следующей попытки задаётся новый `site_release`. После аварийного прерывания
оператор проверяет отсутствие выполняющегося deploy до снятия `.course-cd-lock`.
Private checks на сервер не отправляются.
Production Ubuntu provisioning и пользовательские accounts этим play не меняются.

## Проверки Local

`go-task check` выполняет короткие проверки Python, публикации и активации,
ShellCheck и Node-проверки служебных входов. Та же команда блокирует ошибки в
`.github/workflows/check.yml`. Курсовые render/export и Docker в неё не входят.
Межрепозиторная проверка course Taskfiles явно пропускается в отдельном clone
Local без соседних курсов; основной набор Local выполняется полностью.
