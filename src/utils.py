# src/utils.py
"""Вспомогательные функции для бэкапа статей."""

import re
from pathlib import Path
from urllib.parse import urlparse
from slugify import slugify

# Типы ассетов и их расширения
ASSET_TYPES = {
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'},
    'video': {'.mp4', '.webm', '.mov', '.mkv', '.avi'},
    'audio': {'.mp3', '.wav', '.flac', '.ogg'},
    'document': {'.pdf'},
}

# Глобальный список разрешенных расширений
ALLOWED_EXTENSIONS = set().union(*ASSET_TYPES.values())

# Префиксы Content-Type для категорий
CONTENT_TYPE_MAP = {
    'image': ['image/'],
    'video': ['video/'],
    'audio': ['audio/'],
    'document': ['application/pdf'],
}

# Паттерны для внутренних ссылок
SPONSR_LINK_PATTERN = re.compile(
    r'https?://sponsr\.ru/(?P<author>[^/]+)/(?P<post_id>\d+)(?:/[^\s\)\]"\'<>]*)?'
)
BOOSTY_LINK_PATTERN = re.compile(
    r'https?://boosty\.to/(?P<author>[^/]+)/posts/(?P<post_id>[a-f0-9-]+)(?:[^\s\)\]"\'<>]*)?'
)


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


def should_download_asset(
    url: str,
    content_type: str | None = None,
    allowed_types: list[str] | None = None
) -> bool:
    """
    Проверяет, нужно ли скачивать файл.

    Args:
        url: URL файла
        content_type: Content-Type из заголовков ответа (опционально)
        allowed_types: Список разрешенных типов (image, video, audio, document).
                       Если None или пустой — разрешено всё из ALLOWED_EXTENSIONS.
    """
    ext = Path(urlparse(url).path).suffix.lower()

    # Если типы не указаны, используем глобальный фильтр
    if not allowed_types:
        if ext:
            return ext in ALLOWED_EXTENSIONS
        
        # Fallback для content-type (старое поведение)
        if content_type:
            basic_types = ['image/', 'video/', 'audio/', 'application/pdf']
            return any(ct in content_type for ct in basic_types)
        
        return False

    # Если типы указаны, проверяем строго по ним
    
    # 1. Проверка по расширению
    if ext:
        for type_name in allowed_types:
            if ext in ASSET_TYPES.get(type_name, set()):
                return True
        # Если расширение есть, но не совпало ни с одним разрешенным типом — запрещаем
        return False

    # 2. Проверка по Content-Type (если нет расширения)
    if content_type:
        for type_name in allowed_types:
            prefixes = CONTENT_TYPE_MAP.get(type_name, [])
            if any(prefix in content_type for prefix in prefixes):
                return True

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


def extract_internal_links(content: str) -> list[tuple[str, str, str, str]]:
    """
    Извлекает внутренние ссылки из контента.
    Возвращает [(full_url, platform, author, post_id), ...]
    """
    links = []

    for match in SPONSR_LINK_PATTERN.finditer(content):
        links.append((match.group(0), 'sponsr', match.group('author'), match.group('post_id')))

    for match in BOOSTY_LINK_PATTERN.finditer(content):
        links.append((match.group(0), 'boosty', match.group('author'), match.group('post_id')))

    return links
