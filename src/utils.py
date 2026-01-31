# src/utils.py
"""Вспомогательные функции для бэкапа статей."""

import re
from pathlib import Path
from urllib.parse import urlparse
from slugify import slugify

# Белый список расширений
ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
    '.mp4', '.webm', '.mov', '.mkv', '.avi',
    '.mp3', '.wav', '.flac', '.ogg',
    '.pdf',
}

# Допустимые Content-Type
ALLOWED_CONTENT_TYPES = {'image/', 'video/', 'audio/', 'application/pdf'}

# Паттерны для внутренних ссылок
SPONSR_LINK_PATTERN = re.compile(r'https?://sponsr\.ru/([^/]+)/(\d+)(?:/[^\s\)\]"\'<>]*)?')
BOOSTY_LINK_PATTERN = re.compile(r'https?://boosty\.to/([^/]+)/posts/([a-f0-9-]+)(?:[^\s\)\]"\'<>]*)?')


def transliterate(text: str) -> str:
    """Транслитерация текста в slug."""
    return slugify(text, lowercase=True, max_length=80)


def parse_post_url(url: str) -> tuple[str, str, str]:
    """
    Парсит URL поста, возвращает (platform, author, post_id).

    Примеры:
        https://sponsr.ru/pushkin/134833/... → ('sponsr', 'pushkin', '134833')
        https://boosty.to/lermontov/posts/uuid → ('boosty', 'lermontov', 'uuid')
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip('/').split('/') if p]

    if 'sponsr.ru' in parsed.netloc:
        if len(parts) < 2:
            raise ValueError(f"Неверный формат URL Sponsr: {url}")
        return ('sponsr', parts[0], parts[1])

    elif 'boosty.to' in parsed.netloc:
        if len(parts) < 3 or parts[1] != 'posts':
            raise ValueError(f"Неверный формат URL Boosty: {url}")
        return ('boosty', parts[0], parts[2])

    raise ValueError(f"Неизвестная платформа: {url}")


def is_post_url(text: str) -> bool:
    """Проверяет, является ли строка URL поста."""
    try:
        parse_post_url(text)
        return True
    except ValueError:
        return False


def should_download_asset(url: str, content_type: str | None = None) -> bool:
    """
    Проверяет, нужно ли скачивать файл.

    Args:
        url: URL файла
        content_type: Content-Type из заголовков ответа (опционально)
    """
    ext = Path(urlparse(url).path).suffix.lower()

    if ext:
        return ext in ALLOWED_EXTENSIONS

    if content_type:
        return any(ct in content_type for ct in ALLOWED_CONTENT_TYPES)

    return False


def get_extension_from_content_type(content_type: str) -> str:
    """Определяет расширение файла по Content-Type."""
    mapping = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/svg+xml': '.svg',
        'video/mp4': '.mp4',
        'video/webm': '.webm',
        'audio/mpeg': '.mp3',
        'audio/wav': '.wav',
        'audio/flac': '.flac',
        'audio/ogg': '.ogg',
        'application/pdf': '.pdf',
    }

    ct = content_type.split(';')[0].strip().lower()
    return mapping.get(ct, '')


def sanitize_filename(name: str) -> str:
    """Очищает имя файла от недопустимых символов."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name or 'unnamed'


def extract_internal_links(content: str) -> list[tuple[str, str, str]]:
    """
    Извлекает внутренние ссылки из контента.
    Возвращает [(full_url, platform, post_id), ...]
    """
    links = []

    for match in SPONSR_LINK_PATTERN.finditer(content):
        links.append((match.group(0), 'sponsr', match.group(2)))

    for match in BOOSTY_LINK_PATTERN.finditer(content):
        links.append((match.group(0), 'boosty', match.group(2)))

    return links
