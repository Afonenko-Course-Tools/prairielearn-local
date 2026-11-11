# Готовая поставка в отдельном локальном production-стенде

Production использует `compose.yml`, при необходимости `compose.auth.yml` и
`compose.workspace.yml`. Dev-preview на 8088/8089 имеет другие projects/state.
Всегда передавайте один и тот же `--env-file` и набор `-f` всем командам своего
стенда. Local init задаёт `workersCount: 1`; сохраните это явное значение и
в предоставленном `PL_CONFIG_FILE`. Native default может выбирать workers по
CPU компьютера, а Docker `cpus` не заменяет этот параметр. Native DB, ключи, Moodle и Gateway сохраняются между обновлениями.

## Native Git из готовых bytes

Сначала скачайте фактические artifact IDs одного producer run: `delivery.tar`
с student/native и отдельный controller artifact с checks/runtime profiles.
Проверьте готовую поставку обычным course `verify`, не выполняя новый render.
Сохраните producer run/artifact IDs, native Git commit и путь student-архива
в приватном журнале доставки. Совпадение произвольных входов Ansible не доказывает.

Используйте обычный checkout существующего native Git repository. Его `.git`,
README и операторские docs сохраняются; другие исчезнувшие generated файлы
удаляются, включая hidden файлы. Пример для отдельно распакованного native:

```sh
git -C /private/native-java status --short
# При локальном hotfix сначала сохраните git diff --binary вне Git и перенесите
# исправление в canonical source. Перед заменой дерево должно быть чистым.
rsync -a --delete --exclude='/.git/' --exclude='/README.md' --exclude='/docs/' \
  /private/producer/native/ /private/native-java/
git -C /private/native-java add -A
git -C /private/native-java diff --cached --check
git -C /private/native-java diff --cached --stat
git -C /private/native-java diff --cached
git -C /private/native-java commit -m 'Обновить готовый native курс'
git -C /private/native-java push origin main
git -C /private/native-java rev-parse HEAD
```

Перед commit проверьте UUID, hidden `workspace/.pl-seed`, ожидаемые удаления
и отсутствие checks, secrets/state. `rsync` не делает обратный импорт hotfix
в авторский курс. Спорную правку разбирают по Git diff и заново выпускают
каноническим producer. Force push не требуется. Для System Practice повторяется
тот же маршрут в его собственном native repository.

Первый administrator создаётся существующим Local bootstrap. PAT создают
штатной формой `/pl/settings` после входа и сохраняют вне Git. Публичного REST
API создания PAT нет. Git repository/branch задают штатной административной
страницей PL; повторный sync выполняет существующий native REST API.

## Native sync и student-сайт

`ansible/deploy.yml` получает готовый `site.tar`, numeric native course ID и
точный native commit. Он распаковывает новый каталог, делает один POST sync,
ожидает его GET status, проверяет native DB/Git revision под штатным lock и
только после этого переключает `site_root/current`.
Неизвестный результат POST сначала диагностируют по native sync jobs; POST
автоматически не повторяется. При Error или mismatch прежний сайт сохраняется.
Native DB/FS уже могли измениться; автоматический rollback не обещается.

Для фактического HTTP обслуживания готового student-сайта подключите
необязательный `compose.site.yml`. Он читает только public `SITE_ROOT`, где
Ansible создаёт `releases/` и относительную ссылку `current`. Private checks
в этот каталог не попадают. Например, после первой успешной доставки:

```sh
SITE_ROOT=/private/stack/sites SITE_HTTP_PORT=18088 \
  docker compose --env-file /private/stack/.env \
  -f compose.yml -f compose.auth.yml -f compose.site.yml up -d course-site
```

Это отдельный loopback HTTP preview public student bytes. PL/Moodle используют
свой HTTPS proxy и локальный CA. Для внешней VM всё ещё нужны выбранные
target, DNS, TLS и разрешение владельца; локальный опыт не подтверждает VM.

## LTI и Workspace

Gateway image закреплён опубликованным digest v3.0.1. Его версия имеет префикс
`v`; отсутствующий tag `3.0.1` не является рабочим образом. Gateway отвечает
за LTI auth/handoff и доверенные student/teacher grants. Оценки и ручная проверка
принадлежат native PL; AGS/автоматический grade passback в этом auth-only договоре
отсутствует. Выбранный операторский перенос использует существующие Native
Assessment → Downloads → `*_points.csv` и штатный Moodle Grades → Import → CSV.
CSV содержит настоящие native UID и баллы; ничего округлять не нужно.

Оператор явно сопоставляет native UID с проверенным numeric Moodle user ID
и при импорте выбирает `userid`, а колонку баллов связывает с конкретным
существующим manual grade item того же курса и с тем же максимумом. Gateway UID
не равен Moodle username; совпадение по похожему имени или email не заменяет
сопоставление. В Moodle для отображения выбирают 0 десятичных знаков; это
настройка отображения, а не серверная проверка целочисленности.

`*_points.csv` выбирает наибольший native процент пользователя, при равенстве —
последний номер попытки. Когда нужна определённая попытка, оператор выбирает её
явно из `*_points_all.csv` или `*_instances_all.csv` и проверяет Points/Max points.
До commit импорта проверяют preview, numeric пользователя и выбранный grade item,
сохраняют исходный CSV и таблицу сопоставления вне Git. После импорта сверяют
0/max и повторное обновление, а также неизменность другого пользователя и
другого grade item. Повторный импорт обновляет выбранные ячейки; новый item
автоматически не создают.

Для двух студентов создайте второй synthetic account штатным Moodle user API
или UI и зачислите в fixture course. Проверяйте отдельные Moodle passwords,
настоящие подписанные launches, разные native user IDs и отсутствие staff прав
у Student. Для Teacher ожидаются native Editor + Student Data Editor. Отдельно
проверяются чужая попытка, закрытие приёма, replay/wrong-target и закрытые
публичные `/pl/shibcallback` и `/internal/`.

Workspace host получает отдельный Docker daemon: его native cleanup действует
на Workspace labels. Проверьте фактический daemon ID, mounts и отсутствие
публикации editor-порта на машине. Пути `HOST_JOBS_DIR` должны обозначать одни
байты с точки зрения PL, host worker и daemon. Для nested daemon его опубликованные
порты остаются внутри private Docker network; `workspaceDevContainerHostname`
задают адресом этого daemon, доступным native host. `workspaceDevHostHostname`
обозначает API host worker, а не editor. Отдельно настройте owner UID/GID 1001
и `workspacePullImagesFromDockerHub: false` для заранее загруженного точного image.
Сохранение staged/unstaged/untracked и Git history подтверждается через настоящий
Save, Stop/Resume, native submission и преподавательские файлы.

Согласованные dumps и восстановление в другом project/state описаны в
[локальных операциях](local-operations.md).
