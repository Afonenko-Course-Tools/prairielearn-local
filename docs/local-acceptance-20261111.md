# Фактическая локальная приёмка 11 ноября 2026 года

Проверен отдельный production-подобный `close-local`, затем восстановленный
`close-local-restore`. Основные dev-preview на 8088/8089 не останавливались.
Данные вымышленные; авторские Java/System Practice и их веса не изменялись.
Приватные configs, passwords, cookies, dumps и полные HTML остаются вне Git.

## Поставка и граница происхождения

Использованы готовые accepted Local bytes Java из `releases/rwytm3w0` и готовый
System Practice native. Новый render/export для доставки не выполнялся.
Обычный локальный bare Git fixture Java содержит эти же native bytes; его commit:
`b54327f67d28f3a5fbc5fbea39235bf922be80c9`.
Это настоящая проверка native Git/REST sync, но не доказательство hosted producer
artifact IDs или публикации в окончательном Git remote: их связывает выпуск
отдельно. Новой REST API создания PAT и собственного SQL importer нет.

Проверенные неизменяемые runtime:

| Компонент | Identity |
| --- | --- |
| Community 2.5.8 | `ghcr.io/afonenko-course-tools/prairielearn-community-gateway@sha256:f7d1903532e813fe29df74949da7131a353710ff7d0d632a51482762422dcb82` |
| Gateway v3.0.1 | `ghcr.io/afonenko-course-tools/moodle-prairielearn-gateway@sha256:9a46942a4085bcf4294647b2f5461fb9dc328fc610214a0b627b75ded7f75f87` |
| Moodle PostgreSQL 17.11 | `postgres@sha256:ff87138949ad9a46f32ff23bd6852b52ce024a13dffe9b4087be98292cdd3b4f` |
| Git Workspace | `ghcr.io/afonenko-course-tools/sp-git-workspace@sha256:465bf16061c3a44afdc61c77d1dd853216be35b0203072cb8e7c69a51a1bf31a` |

Moodle 5.3 собрана из закреплённого TGZ SHA-256
`7e5edf110555956571f40e42acffde0eb23681ebebd212a2fec0fe7d795dd511`,
PHP base digest `5d55c49594dd833e2e4ff677b65f7d8ff48817f443a60691d9b2b382413bba42`.
Фактический Moodle image ID:
`sha256:a63b12eed7af88e7caccf6aecba7c1120d6032d4444ffa63388926bfa21d8e81`.
Это квалификация Community 2.5.8; будущий image с integer manual-points feature
проверяется и публикуется отдельно. Local init и фактический config явно имеют
`workersCount: 1`.

Native administrator создан существующим bootstrap, PAT — настоящей формой
Settings с Cookie/CSRF. Штатный REST sync job 2 завершился `Success`; Ansible job 3
проверил тот же native commit/чистый Git и переключил public сайт. HTTP consumer
вернул все 60201 bytes `index.html` точно как в готовом выпуске.

Неправильный ожидаемый commit отклонён после реального успешного job 4:
прежняя ссылка сайта сохранилась. Отдельный Ansible job 9 получил реальный
native `Error` от отсутствующего Git remote; сайт, IDs, ответы и баллы сохранились.
После диагностики remote восстановлен, один явно повторённый job 10 — `Success`.
Неизвестный POST автоматически не повторялся; rollback DB/FS не обещается.

## Moodle, роли и студенческая форма

Одна isolated Moodle activity последовательно явно перенастраивалась оператором
на Java instance 1, synthetic editor instance 2 и System Practice instance 3.
После каждой смены были новые genuine signed launches двух студентов и Teacher.
Native user IDs остались 2, 3 и 4; Teacher получил Editor + Student Data Editor,
студенты не получили staff grants. Для обоих студентов доступны все десять Java
лабораторных. Instructor route даёт 403/403/200 во всех трёх instances.
Чужая реальная попытка и чужой Workspace/proxy отвергаются 403; публичный
spoofed Shibboleth callback — 403, private Bridge — 404, replay настоящего signed
launch и wrong target — 403.

Первичная механика проверена через реальные HTML формы/Cookie/CSRF по HTTPS
с проверкой локального CA и штатный browser Socket.IO protocol. После restore
выполнена также **настоящая Chromium/DOM приёмка**: два отдельных student login
и Teacher login → Moodle signed LTI → native instance 3; browser instructor ACL
403/403/200. Настоящий JS Workspace запустил Code Server iframe и видимый
`.monaco-workbench`. `ignoreHTTPSErrors: false`; CA добавлен только в private NSS
home внутри временного mount namespace, глобальные HOME/trust stores не менялись.

Synthetic editor проходит incomplete Save/reopen без изменения bytes,
assertion failure с expected/actual, student compilation error и correct result.
Скачанный настоящий starter ZIP собран локальным JDK 25, те же IDE files приняты
native grader. Совместимая смена двух editor sources на три sources/ZIP сохранила
все пять прежних submission IDs, variant, raw answers, bytes и scores.
Teacher настоящим native access UI закрыл приём: история осталась доступна,
прямой Student grade POST получил 400 «not accepting submissions»; повторное
открытие тем же UI восстановило приём.

## Workspace и оценка

Системный Docker ID отличается от выделенного daemon. Native session работает
с UID/GID 1001, одним точным jobs bind; editor не опубликован на host. В реальной
среде сделан Git A → B, затем staged/unstaged/untracked checkpoint. Native Save
вернул 19 файлов. Штатная остановка удалила старый контейнер; Resume создал другой.
Все 23 файла home, включая raw index/HEAD/objects и untracked bytes, совпали точно.
После снятия только checkpoint edits native submission вернула 18 файлов.
Teacher скачал их авторизованными native file URLs, восстановил читаемый Git
A → B с чистыми index/worktree, проверил `git fsck` и explanation, поставил
100/100 через native manual-grading UI. Авторский grading method `Manual`
сохранён; автоматическая проверка наблюдения двух Git restore не выдумывается.

Полный final home имеет 22 файла; 18 возвращённых файлов совпали побайтно.
Остальные четыре — seed manifest/ZIP и внешние README/material ZIP — сохраняются
полным state/jobs backup, хотя не входят в native graded-file projection.
Фактический published initializer, текущий source и lifecycle tests согласованы:
корректный manifest проверяется, изменённый starter ZIP не заменяет существующую
работу при resume; Git refresh/reset отсутствует.

Выбранный перенос оценок прошёл существующими Native Downloads `*_points.csv`
и Moodle CSV filepicker/preview/commit: exact Gateway UID → numeric Moodle user ID,
native 0/100 → Moodle 0/100, затем повторный 100. Manual item имеет max 100 и
0 десятичных знаков; пять чужих контрольных ячеек 2/7/2/8/37 не изменились.
Это явный операторский перенос, автоматический AGS/Gateway grading не добавлен.

## Восстановление

Перед baseline все приложения и native writers остановлены. Source PG запущен
отдельно в PG-only helper без сети и PL node/cron/jobs. Проверено отсутствие
active native/external jobs и Workspaces; сняты custom-format `pg_dump` обеих БД,
затем согласованные stopped-files/state/config archives. Живой PG datadir не
копировался. Backup находится на workspace disk вне Git, mode 0700/0600.

В другом project/state созданы новые PG clusters/volumes и выполнен настоящий
`pg_restore`. До новых действий native users/course/instance IDs, все прежние
answers/raw bytes/scores и Moodle users/course/items/grade cells совпали с baseline.
Все восемь key/account/TLS files и 22 Workspace home files восстановлены побайтно.
У clone свой новый daemon ID, image store/socket и **другой jobs bind**; чтения
исходного home нет. Прежние HTTPS origins сохранены, поэтому fresh browser LTI
сохранил native identities и bindings.

После restore тот же Student отправил новый трёхфайловый Java ZIP: native
submission 8, прежний variant 1, реальный JDK 25 external grader дал score 1,
`classification: success`. Все семь исходных сдач и их bytes/scores сохранились.
Повторный полный `up` сохранил IDs, восемь submissions, answers, native/Moodle
grades и public site bytes. Основные preview 8088/8089 продолжали работать.

`go-task check`, `git diff --check` и эффективная конфигурация base/auth/Workspace/site
прошли. Author evidence и отдельная независимая рецензия хранятся у координатора;
приватный стенд и backup в Git не помещаются. VM target/DNS/TLS и SSH-перенос
не выполнялись и этим локальным результатом не закрываются.
