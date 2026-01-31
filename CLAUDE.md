# Контекст проекта для LLM

## Назначение
Скрипт для локального бэкапа статей с платформ Sponsr.ru и Boosty.to.
Конвертирует в Markdown, скачивает медиа, поддерживает инкрементальную синхронизацию.

## Архитектура

```
backup.py          → CLI точка входа, парсинг аргументов
src/
├── config.py      → загрузка YAML-конфига, dataclasses Config/Source/Auth
├── database.py    → SQLite индекс, CRUD для PostRecord
├── downloader.py  → BaseDownloader (абстрактный), общая логика сохранения
├── sponsr.py      → SponsorDownloader, API sponsr.ru
├── boosty.py      → BoostyDownloader, API boosty.to
└── utils.py       → транслитерация, фильтрация assets, парсинг URL
```

## Ключевые классы

- `BaseDownloader` — абстрактный базовый класс
  - `sync()` — полная синхронизация автора
  - `download_single()` — один пост по ID
  - `_save_post()` — сохранение на диск + запись в БД
  - `_download_assets()` — параллельное скачивание медиа (ThreadPoolExecutor) с retry
  - `_deduplicate_filename()` — генерация уникальных имён файлов при коллизии

- `Post` — dataclass с полями: post_id, title, content_html, post_date, source_url, tags, assets

- `Database` — SQLite wrapper с connection pooling
  - Использует один connection на сессию
  - Поддерживает context manager (`with Database(...) as db:`)

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

## Hugo-сайт

```
site/
├── hugo.toml           → конфиг Hugo (relativeURLs = true)
├── build.sh            → сборка + копирование CSS в папки авторов
├── static/css/         → стили (reader.css)
├── layouts/_default/   → шаблоны (single.html, list.html, baseof.html)
└── public/             → сгенерированный сайт
```

- `backup.py` автоматически создаёт симлинк `site/content → output_dir`
- `build.sh` — собирает Hugo и копирует CSS в каждую папку автора для автономной раздачи через субдомены
- Относительные URL включены — сайт работает из любой директории
- RSS генерируется для каждого автора: `/{platform}/{author}/index.xml`

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
→ `utils.py`: `ALLOWED_EXTENSIONS`, `should_download_asset()`

**Настроить retry параметры:**
→ `downloader.py`: `retry_request()` — параметры max_retries, base_delay, max_delay, backoff_factor

**Изменить шаблоны Hugo:**
→ `site/layouts/_default/` — single.html (статья), list.html (списки), baseof.html (базовый)
→ Все ссылки должны использовать `relURL` для относительных путей

**Добавить CSS для автора:**
→ Создать `backup/{platform}/{author}/css/author.css` с кастомными переменными
