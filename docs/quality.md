# Проверки собственных файлов Local

`go-task check` проверяет Python (Ruff E4/E7/E9/F/B, полный Ruff format,
Pyright с отказом на warnings), JavaScript (strict checkJs/JSDoc и синтаксис Node),
shell (ShellCheck/shfmt), YAML (yamllint), workflows (actionlint), playbooks
(Ansible lint), Dockerfiles (Hadolint), PHP (штатный `php -l`). Проверка запускает
реальные Python/Node тесты. `go-task format` применяет Ruff, shfmt и Prettier.
Обе команды включают новые untracked файлы: источник списка — `git ls-files`
с `--others --exclude-standard`, без фиксированного перечня скриптов.

Установка: `python3 -m pip install -r requirements-dev.txt`, `npm ci --ignore-scripts`.
Остальные инструменты берутся из PATH: go-task, git, shellcheck, shfmt, actionlint,
hadolint, PHP и Docker Compose. Используйте системные пакеты или официальные
выпуски этих инструментов. npm предоставляет локальные TypeScript/Prettier и
типизацию Node. Для Pyright нужен доступный Python с установленным PyYAML.
Отсутствующая CLI, ненулевой exit или предупреждение анализатора останавливают gate.

Compose проверяется только штатным `docker compose config --quiet`: основной
файл, отдельный preview и каждый найденный overlay с основным файлом. Используются
синтетические пути во временном каталоге и `--env-file /dev/null`; `.env`, ключи,
аккаунты и состояние пользователя не читаются. Docker daemon не требуется,
контейнеры и сервисы не запускаются. Инициализируйте submodule `deps/platform`
или передайте `go-task check PLATFORM_ROOT=/абсолютный/Platform` с настоящим `compose/runtime.yml`.
Ansible lint получает отдельные temporary home/cache; deploy playbooks не исполняются.

JSDoc и `types/native.d.ts` описывают только используемые PL DB/locks/user/schema
API. Runtime по-прежнему загружает установленные пакеты PL; эти объявления не
подменяют реализацию. `scripts/check-native-revision.mjs` доставляется через stdin,
поэтому его JSDoc не создаёт runtime imports или зависимости на локальные `.d.ts`.

## Контекст проверки безопасности

Bandit сканирует все собственные Python файлы, включая тесты, без глобальных skips
и baseline. Уточнения `nosec` ограничены конкретным правилом и строкой:

- B404: импорт стандартного subprocess для явного argv; `shell=True` не используется.
- B603/B607 в `init-config.py`: фиксированный `openssl` из PATH с фиксированными
  операциями req/verify/x509. Hostname проходят DNS-проверку, пути получены из
  явного state аргумента; существующие ключи сохраняются. CLI обслуживает доверенный
  оператор, системное доверие не меняется.
- B603 в prepare/preview/quality: команды составляются Local как список аргументов,
  выполняются установленными CLI без shell. Пути, release aliases и публикация
  проверяются до изменения готовой выдачи. Quality запускает только анализаторы,
  синтаксические проверки, статический Compose config и тесты.
- B310 в preview: readiness HTTP получает loopback origin, сформированный main из
  фиксированного `127.0.0.1` и проверенного непривилегированного port. Эта операция
  не читает URL или credentials из курса; таймаут задан явно.
- B101 и subprocess в тестах: assert проверяет importlib loader тестового модуля;
  процессы исполняют собственные фикстуры/CLI в TemporaryDirectory. Эти строки
  не участвуют в production authorization. Тесты проверяют отказ публикации,
  опасные ссылки/архивы, повтор native job и сохранение прежнего сайта.

Hadolint DL3008 исключён только для установки Debian пакетов в Moodle Dockerfile:
базовый образ закреплён digest, а security updates Debian остаются доступны без
нештатного lock поверх apt. RUN использует Bash pipefail для проверки SHA архива.
YAML форматирует Prettier; yamllint проверяет структуру/пробелы, разрешая его
переносы строк и форматирование flow collections. Исторические Markdown документы
проходят только форматирование; учебное содержание зависимостей не меняется.

Установленный ansible-core может печатать сообщения о deprecated встроенных
callback plugins `oneline` и `tree` при перечислении plugin API. Local их не
использует; то же сообщение воспроизводится командой `ansible-doc -t callback -l`.
Это предупреждение инструмента, а lint результат playbooks остаётся
`0 failure(s), 0 warning(s)`; глобальное подавление deprecations не включено.
