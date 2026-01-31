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
  - `_download_assets()` — параллельное скачивание медиа (ThreadPoolExecutor)

- `Post` — dataclass с полями: post_id, title, content_html, post_date, source_url, tags, assets

## API платформ

**Sponsr:**
- Список постов: `GET /project/{project_id}/more-posts/?offset={n}`
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
