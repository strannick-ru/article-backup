# Контекст проекта для LLM

## Назначение
Скрипт для локального бэкапа статей с платформ Sponsr.ru и Boosty.to.
Конвертирует в Markdown, скачивает медиа, поддерживает инкрементальную синхронизацию.

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

- `retry_request()` — функция для retry с exponential backoff (3 попытки, задержка 1-30 сек)

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
7. Встроенные видео (iframe/embed) в Sponsr заменяются на markdown-ссылки перед конвертацией html2text
8. Hugo `relativeURLs = true` + `relURL` даёт пути вида `../../../path/` — не работает для субдоменов, используем `path.Base` в list.html
9. Sponsr: HTML предобрабатывается перед html2text — слияние вложенных тегов (`<em><em>` → `<em>`), вынос leading/trailing пробелов из тегов форматирования и ссылок наружу (чтобы избежать `_текст _` или `[ссылка ]`), удаление пустых тегов. Затем постобработка: нормализация 4+ звёздочек, склеивание bold-italic (`** _текст_**` → `***текст***`), удаление bidi-маркеров, нормализация пробелов Unicode-кавычек, перемещение форматирования внутрь ссылок.
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

## Docker

```
Dockerfile              → Python 3.12-slim, копирует backup.py и src/
docker-compose.yml      → сервисы backup (Python) и hugo (latest + копирование CSS)
run-docker.sh           → скрипт-обертка для корректного запуска с учетом config.yaml
.dockerignore           → исключает __pycache__, .git, backup/, site/public/
```

Запуск: `./run-docker.sh` (рекомендуется) или `docker compose run ...`

Сервис `hugo` после сборки автоматически копирует CSS в папки авторов для поддержки субдоменов.

## Hugo-сайт

```
site/
├── hugo.toml           → конфиг Hugo (генерируется из config.yaml)
├── build.sh            → сборка + копирование CSS в папки авторов
├── static/css/         → стили (reader.css)
├── layouts/_default/   → шаблоны (baseof.html, single.html, list.html)
└── public/             → сгенерированный сайт
```

- `backup.py` автоматически создаёт симлинк `site/content → output_dir`
- `backup.py` генерирует `site/hugo.toml` из секции `hugo:` в config.yaml (base_url, title, language_code)
- `build.sh` — собирает Hugo и копирует CSS в каждую папку автора для автономной раздачи через субдомены
- Относительные URL включены — сайт работает из любой директории
- RSS генерируется для автора и секции постов:
  - `/{platform}/{author}/index.xml`
  - `/{platform}/{author}/posts/index.xml` — title берётся из `author`, description — из `display_name` (записывается в `posts/_index.md`)

## Соглашения

- Slug папки: `{YYYY-MM-DD}-{transliterated-title}`
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

## Релизы и публикация

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
   python -m build
   python -m twine check dist/*
   ```

4. **Опубликовать на PyPI:**
   ```bash
   python -m twine upload dist/*
   # Токен: pypi-...
   ```

5. **Git релиз:**
   ```bash
   git add .
   git commit -m "Подготовка к релизу vX.Y.Z"
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```

6. **GitHub Release:**
   - Создать через веб-интерфейс или `gh release create`
   - Описание из CHANGELOG
   - Приложить quickstart архив:
     ```bash
     tar -czf article-backup-vX.Y.Z-quickstart.tar.gz \
       README.md LICENSE config.yaml.example docker-compose.yml \
       Dockerfile .dockerignore requirements.txt pyproject.toml \
       --transform 's,^,article-backup/,'
     gh release upload vX.Y.Z article-backup-vX.Y.Z-quickstart.tar.gz
     ```

**После релиза:**
- Проверить https://pypi.org/project/article-backup/
- Протестировать установку: `pip install article-backup==X.Y.Z`
- Проверить GitHub Release с assets
