# Article Backup

[![PyPI version](https://badge.fury.io/py/article-backup.svg)](https://pypi.org/project/article-backup/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Скрипт для локального бэкапа статей с платформ **Sponsr.ru** и **Boosty.to**.

Конвертирует статьи в Markdown с YAML-метаданными, скачивает изображения и другие медиафайлы, поддерживает инкрементальную синхронизацию.

## Возможности

- Полный архив статей одного или нескольких авторов
- Инкрементальные обновления — скачивает только новые статьи
- Конвертация в Markdown с frontmatter (title, date, tags, source)
- Локальное сохранение изображений, видео, аудио, PDF
- Сохранение ссылок на встроенные видео (Rutube, YouTube, Vimeo, VK, OK.ru)
- Исправление внутренних ссылок между статьями
- Интеграция с Hugo для просмотра в браузере
- SQLite-индекс для быстрого поиска

## Установка

Требуется **Python 3.10+**

### Вариант 1: Через pip (рекомендуется)

```bash
pip install article-backup
```

### Вариант 2: Из исходников

```bash
git clone https://github.com/strannick-ru/article-backup.git
cd article-backup
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Настройка

### 1. Создайте конфиг

```bash
cp config.yaml.example config.yaml
```

### 2. Заполните `config.yaml`

```yaml
output_dir: ./backup

hugo:
  base_url: "https://example.com/"
  title: "Бэкап статей"
  language_code: "ru"

auth:
  sponsr_cookie_file: ./sponsr_cookie.txt
  boosty_cookie_file: ./boosty_cookie.txt
  boosty_auth_file: ./boosty_auth.txt

sources:
  - platform: sponsr
    author: pushkin
    display_name: "Пушкин. Проза"

  - platform: boosty
    author: lermontov
    display_name: "Лермонтов. Стихи"
```

### 3. Получите токены авторизации

#### Sponsr

1. Войдите на sponsr.ru
2. Откройте DevTools (F12) → Network
3. Перезагрузите страницу
4. Найдите любой запрос → Headers → Cookie
5. Скопируйте значение в `sponsr_cookie.txt`

#### Boosty

1. Войдите на boosty.to
2. Откройте DevTools (F12) → Console
3. Вставьте код:
```javascript
const cookie = document.cookie;
const auth = JSON.parse(decodeURIComponent(document.cookie.match(/auth=([^;]+)/)[1]));
console.log("Cookie:\n" + cookie + "\n\nAuthorization:\nBearer " + auth.accessToken);
```
4. Скопируйте Cookie в `boosty_cookie.txt`
5. Скопируйте Authorization в `boosty_auth.txt`

## Использование

### Синхронизация всех авторов

```bash
# Если установлено через pip
article-backup

# Или из исходников
python backup.py
```

### Скачать один пост по URL

```bash
article-backup "https://sponsr.ru/author/12345/post-title/"
article-backup "https://boosty.to/author/posts/uuid"
```

### Указать другой конфиг

```bash
article-backup -c /path/to/config.yaml
```

## Docker

Для серверов с устаревшим Python можно использовать Docker.

```bash
# Сборка образа
docker compose build

# Синхронизация всех авторов
docker compose run --rm backup

# Скачать один пост
docker compose run --rm backup "https://sponsr.ru/author/123/"

# Сборка Hugo-сайта
docker compose run --rm hugo

# Полная синхронизация (backup + hugo)
docker compose run --rm backup && docker compose run --rm hugo

# Пересборка после изменений кода
docker compose build --no-cache
```

### Cron

Для автоматической синхронизации добавьте в crontab:

```bash
# Каждый день в 3:00
0 3 * * * cd /path/to/article-backup && docker compose run --rm backup && docker compose run --rm hugo >> /var/log/article-backup.log 2>&1
```

## Структура выходных файлов

```
backup/
├── index.db                          # SQLite-индекс
├── sponsr/
│   └── pushkin/
│       ├── _index.md
│       └── posts/
│           └── 2026-01-31-article-title/
│               ├── index.md          # Статья с frontmatter
│               └── assets/           # Медиафайлы
└── boosty/
    └── lermontov/
        └── posts/
            └── 2026-01-31-another-article/
                ├── index.md
                └── assets/
```

## Интеграция с Hugo

После каждого запуска `backup.py`:
- Автоматически создаётся симлинк `site/content → output_dir`
- Генерируется `site/hugo.toml` из секции `hugo:` в конфиге

```bash
# Запуск локального сервера
cd site && hugo server -D
```

Откройте http://localhost:1313

### Настройка Hugo

Параметры Hugo задаются в `config.yaml`:

```yaml
hugo:
  base_url: "https://example.com/"  # URL сайта для production
  title: "Мой архив статей"         # Заголовок сайта
  language_code: "ru"               # Язык контента
```

Если секция `hugo:` не указана, используются значения по умолчанию (`http://localhost:1313/`).

### RSS-ленты

Для каждого автора автоматически генерируется RSS-фид:

- `http://localhost:1313/sponsr/pushkin/index.xml`
- `http://localhost:1313/boosty/lermontov/index.xml`

На странице автора отображается ссылка 📡 для подписки.

### Субдомены для авторов (nginx)

Каждого автора можно раздавать на отдельном субдомене. При использовании Docker CSS автоматически копируется в папки авторов.

```bash
# Docker (CSS копируется автоматически)
docker compose run --rm backup && docker compose run --rm hugo

# Или локально через build.sh
cd site && ./build.sh
```

Пример конфига nginx:

```nginx
server {
    listen 80;
    server_name pushkin.example.site;
    root /var/www/backup/site/public/sponsr/pushkin;
    index index.html;

    # Корень показывает список постов
    location = / {
        try_files /posts/index.html =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

## Формат статьи

```yaml
---
title: "Заголовок статьи"
date: 2024-01-15T12:00:00
source: https://sponsr.ru/pushkin/12345/...
author: pushkin
platform: sponsr
post_id: 12345
tags: ["тег1", "тег2"]
---

# Заголовок статьи

Текст статьи...
```
