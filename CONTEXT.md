# Контекст проекта для LLM

## Назначение
Скрипт для локального бэкапа статей с платформ Sponsr.ru и Boosty.to.
Конвертирует в Markdown, скачивает медиа, поддерживает инкрементальную синхронизацию.

## Правила работы LLM/агента

- Диалог с пользователем ведётся на русском языке.
- Сообщения git-коммитов, аннотации git-тегов, заголовки GitHub Release и release notes пишутся на русском языке.
- В сообщениях git-коммитов, аннотациях git-тегов, заголовках GitHub Release и release notes не использовать emoji.
- Перед созданием git-коммита сначала показать пользователю предлагаемое сообщение и дождаться подтверждения.
- Не коммитить generated artifacts: `dist/`, `*.egg-info/`, `site/public/`, quickstart-архивы `article-backup-v*-quickstart.tar.gz`.
- Для release-коммитов использовать явный `git add` нужных файлов вместо `git add .`.
- Не трогать пользовательские и локальные untracked-файлы без явной просьбы.
- После release-сборки локальные generated artifacts можно удалить, если они больше не нужны для публикации.
- Перед заявлением о завершении задачи указывать фактически выполненные проверки.

## Архитектурный контекст

## Архитектура

```
backup.py          → CLI точка входа, парсинг аргументов
src/
├── config.py      → загрузка YAML-конфига, dataclasses Config/Source/Auth/HugoConfig
├── database.py    → SQLite индекс, CRUD для PostRecord
├── downloader.py  → BaseDownloader (абстрактный), общая логика сохранения
├── sponsr.py      → SponsorDownloader, API sponsr.ru
├── boosty.py      → BoostyDownloader, API boosty.to
└── utils.py       → транслитерация, фильтрация assets, парсинг URL
```

## Ключевые классы

- `BaseDownloader` — абстрактный базовый класс
  - `sync()` — синхронизация автора (полная или инкрементальная)
  - `fetch_posts_list()` — получение списка постов (с поддержкой инкрементального режима)
  - `download_single()` — один пост по ID
  - `_save_post()` — сохранение на диск + запись в БД
  - `_download_assets()` — параллельное скачивание медиа (ThreadPoolExecutor) с retry
  - `_deduplicate_filename()` — генерация уникальных имён файлов при коллизии

- `Post` — dataclass с полями: post_id, title, content_html, post_date, source_url, tags, assets

- `Database` — SQLite wrapper с connection pooling
  - Использует один connection на сессию с timeout=30 и WAL mode
  - Поддерживает context manager (`with Database(...) as db:`)
  - Таблица `sync_state` для отслеживания статуса инкрементальной синхронизации

- `retry_request()` — функция для retry с exponential backoff (3 попытки, задержка 1-30 сек). Применяется для API-запросов и скачивания файлов.

## API платформ

**Sponsr:**
- Список постов: `GET /project/{project_id}/more-posts/?offset={n}`
- Один пост: парсинг `__NEXT_DATA__` со страницы `/{author}/{post_id}/`
- project_id из `__NEXT_DATA__` на странице проекта
- Авторизация: Cookie header

**Boosty:**
- Список постов: `GET /v1/blog/{author}/post/?limit=20&offset={token}`
- Один пост: `GET /v1/blog/{author}/post/{uuid}`
- Авторизация: Cookie + Authorization: Bearer

## Известные особенности

1. URL картинок Boosty не содержат расширения — определяем по Content-Type
2. Заголовки могут содержать кавычки — экранируем для YAML
3. Внутренние ссылки между статьями — фиксим после скачивания всех постов
4. frontmatter не должен модифицироваться при фиксе ссылок
5. Сетевые запросы используют retry с exponential backoff (кроме 4xx ошибок)
6. При коллизии имён файлов добавляется хеш URL
7. Встроенные видео (iframe/embed) в Sponsr и ok_video в Boosty конвертируются в markdown-ссылки вида `[📹 Видео](embed_url)`. Hugo render hook (`site/layouts/_default/_markup/render-link.html`) распознаёт embed URL известных видеохостингов (Rutube, YouTube, Vimeo, OK.ru, VK) и рендерит `<iframe>` с адаптивным контейнером `.video-container`. В Markdown файлах остаётся чистая ссылка без HTML-вставок. Boosty `ok_video` блоки содержат `playerUrls` — подписанные временные URL прямых видеопотоков; скрипт выбирает лучшее качество (`full_hd > ... > lowest`, fallback на `hls/dash`) и скачивает видео как asset. Превью-картинка (`preview`/`previewUrl`) скачивается **всегда** (с `force=True`, обходя фильтр `asset_types`). Если превью скачано — в Markdown вставляется кликабельная картинка `[![📹 Видео](assets/preview.jpg)](video_link)`. Целевая ссылка: локальный видеофайл (если скачан) > `ok.ru/video/{vid}` > `ok.ru/videoembed/{id}`. Если превью недоступно — обычная текстовая ссылка `[📹 Видео](video_link)`.
8. Hugo `relativeURLs = true` + `relURL` даёт пути вида `../../../path/` — не работает для субдоменов, используем `path.Base` в list.html
9. Sponsr: HTML предобрабатывается перед html2text — слияние вложенных тегов (`<em><em>` → `<em>`), слияние соседних `<em>`/`<i>` тегов в одном родителе. Важно: для сохранения пробелов вокруг inline-тегов (`<b>`, `<em>`) используется вставка специального маркера `@@@SP@@@`, который заменяется на пробел после конвертации (так как `html2text` склонен "съедать" пробелы на границах тегов).
10. SQLite использует timeout=30 сек и WAL mode для избежания "database is locked" при множественных источниках
11. `site/hugo.toml` перезаписывается при каждом запуске backup.py — ручные изменения не сохраняются
12. Дедупликация имён скачиваемых assets должна происходить *до* записи файла и быть потокобезопасной, иначе Markdown может ссылаться на несуществующий файл
13. Фикс внутренних ссылок должен быть ограничен одной платформой и одним автором (не трогать ссылки на другие платформы/авторов)
14. Для субдоменной раздачи автора ссылки в `list.html` должны использовать `path.Base .RelPermalink` (иначе возможны 404 из-за `../../../` путей)
15. Теги в API Sponsr могут приходить как массив строк (старый формат) или как массив объектов с вложенной структурой `{tag: {tag_name: "..."}}`— извлекаем только `tag_name`
16. Инкрементальная синхронизация: после первой полной загрузки (`is_full_sync=True`) скрипт загружает чанками по 20 постов и останавливается, когда встречает N чанков подряд, состоящих только из уже загруженных постов (по умолчанию N=1, т.е. 1 защитный чанк). Порядок постов в API: от новых к старым (offset=0 = самые свежие).
17. Заголовок статьи выводится Hugo из frontmatter (`title`), поэтому конвертеры платформ не добавляют `# Заголовок` в body Markdown (иначе получается дублирование).
18. Boosty: при применении стилей (bold/italic) пробелы на границах фрагмента выносятся наружу маркеров (`*текст *` → `*текст* `), иначе Markdown-разметка невалидна. Фрагменты из одних пробелов не оборачиваются.
19. Boosty: API отдаёт контент как массив блоков. `BLOCK_END` — разделитель параграфов, все inline-блоки (text, link) между двумя `BLOCK_END` конкатенируются в один параграф. Позиции стилей в блоках — глобальные (относительно начала параграфа), при применении нормализуются вычитанием offset-а предыдущих блоков.
20. Sponsr: для консистентности разметки в `sync()` новые посты догружаются полным запросом по `post_id` (как в `download_single()`), так как HTML из `/more-posts` может отличаться от HTML страницы поста.

## Эксплуатационный контекст

## Docker

```
Dockerfile              → Python 3.12-slim, копирует backup.py и src/
docker-compose.yml      → готовый образ из GHCR (для пользователей)
docker-compose-dev.yml  → сборка из исходников (build: .) для разработки
run-docker.sh           → скрипт-обертка для корректного запуска с учетом config.yaml
.dockerignore           → исключает __pycache__, .git, backup/, site/public/
```

Запуск: `./run-docker.sh` (рекомендуется). Скрипт использует `docker-compose.yml` (готовый образ).

Разработка:
```bash
docker compose -f docker-compose-dev.yml build
docker compose -f docker-compose-dev.yml run --rm backup
```

Сервис `hugo` после сборки автоматически копирует CSS в папки авторов для поддержки субдоменов.

**Публикация образов:**
Настроен GitHub Actions workflow (`.github/workflows/docker-publish.yml`). При создании тега `v*` (релиз):
1. Собирается мультиплатформенный образ (amd64/arm64).
2. Публикуется в GHCR: `ghcr.io/strannick-ru/article-backup:latest` и `:vX.Y.Z`.

## Hugo-сайт

```
site/
├── hugo.toml           → конфиг Hugo (генерируется из config.yaml)
├── build.sh            → сборка + копирование CSS в папки авторов
├── static/css/         → стили (reader.css)
├── layouts/_default/   → шаблоны (baseof.html, single.html, list.html, _markup/render-link.html)
└── public/             → сгенерированный сайт
```

- `backup.py` автоматически создаёт симлинк `site/content → output_dir`
- `backup.py` генерирует `site/hugo.toml` из секции `hugo:` в config.yaml (base_url, title, language_code)
- Перед полной синхронизацией `backup.py` выполняет preflight-проверку авторизации по всем источникам. Секция `sync.on_error` управляет поведением при ошибках: `stop` (по умолчанию) останавливает запуск до скачивания, `continue` пропускает проблемные источники и позволяет Docker-запуску собрать Hugo-сайт из доступных данных.
- `build.sh` — собирает Hugo и копирует CSS в каждую папку автора для автономной раздачи через субдомены
- Относительные URL включены — сайт работает из любой директории
- RSS генерируется для автора и секции постов:
  - `/{platform}/{author}/index.xml`
  - `/{platform}/{author}/posts/index.xml` — title берётся из `author`, description — из `display_name` (записывается в `posts/_index.md`)

## Проектные соглашения

- Slug папки: `{YYYY-MM-DD}-{transliterated-title}-{short-hash}` (для обратной совместимости старые посты остаются без хеша)
- Assets в подпапке `assets/` рядом с `index.md`
- Белый список расширений: jpg, png, gif, webp, svg, mp4, webm, mov, mkv, avi, mp3, wav, flac, ogg, pdf

## Типичные задачи

**Добавить новую платформу:**
1. Создать `src/newplatform.py` с классом `NewPlatformDownloader(BaseDownloader)`
2. Реализовать: `_setup_session()`, `fetch_posts_list()`, `fetch_post()`, `_parse_post()`, `_to_markdown()`
3. Добавить в `backup.py` в `get_downloader()`
4. Добавить auth-поля в `config.py`

**Изменить формат frontmatter:**
→ `BaseDownloader._make_frontmatter()`

**Изменить фильтрацию assets:**
→ `utils.py`: `ASSET_TYPES`, `should_download_asset()`
→ `config.py`: `Source.asset_types` (image, video, audio, document)

**Настроить retry параметры:**
→ `downloader.py`: `retry_request()` — параметры max_retries, base_delay, max_delay, backoff_factor

**Настроить инкрементальную синхронизацию:**
→ `downloader.py: sync()` — параметр `safety_chunks` в вызове `fetch_posts_list()` (по умолчанию 1)
→ `sponsr.py/boosty.py: fetch_posts_list()` — логика остановки при достижении чистых чанков
→ `database.py: sync_state` — таблица с полями platform, author, is_full_sync, last_sync_at

**Изменить шаблоны Hugo:**
→ `site/layouts/_default/` — single.html (статья), list.html (списки), baseof.html (базовый)
→ CSS использует переменные для тем (Light, Dark, Sepia, Gruvbox, Everforest)
→ CSS и внешние ресурсы используют `relURL` для относительных путей
→ Ссылки на посты в list.html используют `path.Base .RelPermalink` для прямых путей (совместимость с субдоменами)

**Добавить CSS для автора:**
→ Создать `backup/{platform}/{author}/css/author.css` с кастомными переменными

**Изменить Docker-конфигурацию:**
→ `Dockerfile` — базовый образ, зависимости, точка входа
→ `docker-compose.yml` — volumes, сервисы backup и hugo
→ Пересборка: `docker compose build`

**Изменить настройки Hugo:**
→ `config.yaml` секция `hugo:` — base_url, title, language_code, default_theme
→ `backup.py: generate_hugo_config()` — шаблон генерации hugo.toml
→ `src/config.py: HugoConfig` — dataclass с параметрами и значениями по умолчанию

## Release playbook

**Структура пакета для PyPI:**
- `backup.py` — основной модуль в корне (py-modules)
- `src/` — пакет с модулями (packages.find)
- `pyproject.toml` — метаданные, зависимости, entry point `article-backup`
- Entry point: `article-backup` → `backup:main`

**Процесс релиза:**

1. **Обновить версию:**
   - `pyproject.toml`: `version = "X.Y.Z"`
   - `CHANGELOG.md`: переместить [Unreleased] → [X.Y.Z] с датой

2. **Обновить документацию:**
   - `README.md`: проверить актуальность инструкций
   - Бейджи PyPI, Python, License в начале README

3. **Собрать пакет:**
   ```bash
   rm -rf dist article_backup.egg-info
   python -m build
   python -m twine check dist/*
   ```

4. **Опубликовать на PyPI:**
   Если `TWINE_PASSWORD` задан в окружении, использовать non-interactive upload:
   ```bash
   TWINE_USERNAME="${TWINE_USERNAME:-__token__}" python -m twine upload dist/*
   ```
   Если токен не задан, остановиться и попросить пользователя выполнить команду локально:
   ```bash
   TWINE_USERNAME=__token__ TWINE_PASSWORD='pypi-...' python -m twine upload dist/*
   ```

5. **Git релиз:**
   ```bash
   git add pyproject.toml CHANGELOG.md README.md
   git commit -m "Релиз vX.Y.Z: краткое описание"
   git tag -a vX.Y.Z -m "Релиз vX.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```

6. **GitHub Release:**
   - Создать через веб-интерфейс или `gh release create`.
   - Заголовок и описание брать из CHANGELOG, на русском языке и без emoji.
   - Приложить quickstart архив:
     ```bash
     tar -czf article-backup-vX.Y.Z-quickstart.tar.gz \
       README.md LICENSE config.yaml.example \
       docker-compose.yml docker-compose-dev.yml \
       Dockerfile .dockerignore run-docker.sh \
       requirements.txt pyproject.toml \
       --transform 's,^,article-backup/,'
     gh release upload vX.Y.Z article-backup-vX.Y.Z-quickstart.tar.gz
     ```

**После релиза:**
- Проверить https://pypi.org/project/article-backup/
- Протестировать установку: `pip install article-backup==X.Y.Z`
- Проверить GitHub Release с assets
- Удалить локальные generated artifacts, если они больше не нужны: `dist/`, `*.egg-info/`, `article-backup-vX.Y.Z-quickstart.tar.gz`
