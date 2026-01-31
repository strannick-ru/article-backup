# Article Backup

Скрипт для локального бэкапа статей с платформ **Sponsr.ru** и **Boosty.to**.

Конвертирует статьи в Markdown с YAML-метаданными, скачивает изображения и другие медиафайлы, поддерживает инкрементальную синхронизацию.

## Возможности

- Полный архив статей одного или нескольких авторов
- Инкрементальные обновления — скачивает только новые статьи
- Конвертация в Markdown с frontmatter (title, date, tags, source)
- Локальное сохранение изображений, видео, аудио, PDF
- Исправление внутренних ссылок между статьями
- Интеграция с Hugo для просмотра в браузере
- SQLite-индекс для быстрого поиска

## Установка

Требуется **Python 3.10+**

```bash
git clone https://github.com/username/article-backup.git
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
python backup.py
```

### Скачать один пост по URL

```bash
python backup.py "https://sponsr.ru/author/12345/post-title/"
python backup.py "https://boosty.to/author/posts/uuid"
```

### Указать другой конфиг

```bash
python backup.py -c /path/to/config.yaml
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

```bash
# Инициализация Hugo-сайта
hugo new site site
rm -rf site/content
ln -s ../backup site/content

# Запуск локального сервера
cd site && hugo server -D
```

Откройте http://localhost:1313

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
