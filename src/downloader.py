# src/downloader.py
"""Базовый класс загрузчика и общая логика."""

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from slugify import slugify

from .config import Config, Source
from .database import Database, PostRecord
from .utils import (
    ALLOWED_EXTENSIONS,
    should_download_asset,
    get_extension_from_content_type,
    transliterate,
    sanitize_filename,
    extract_internal_links,
)


def retry_request(
    func,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
):
    """
    Выполняет функцию с retry и exponential backoff.

    Args:
        func: Функция для выполнения (должна возвращать Response или вызывать исключение)
        max_retries: Максимальное количество попыток
        base_delay: Начальная задержка в секундах
        max_delay: Максимальная задержка в секундах
        backoff_factor: Множитель для увеличения задержки
    """
    last_exception = None
    delay = base_delay

    for attempt in range(max_retries):
        try:
            return func()
        except requests.RequestException as e:
            last_exception = e
            # Не ретраим 4xx ошибки (кроме 429 Too Many Requests)
            if hasattr(e, 'response') and e.response is not None:
                if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    raise

            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)

    raise last_exception


@dataclass
class Post:
    """Универсальная структура поста."""
    post_id: str
    title: str
    content_html: str
    post_date: str
    source_url: str
    tags: list[str]
    assets: list[dict]


class BaseDownloader(ABC):
    """Базовый класс для загрузчиков."""

    PLATFORM: str = ""
    MAX_WORKERS: int = 5
    TIMEOUT: tuple = (5, 30)

    def __init__(self, config: Config, source: Source, db: Database):
        self.config = config
        self.source = source
        self.db = db
        self.session = requests.Session()
        self._setup_session()

    @abstractmethod
    def _setup_session(self):
        """Настройка сессии (cookies, headers)."""
        pass

    @abstractmethod
    def fetch_posts_list(self) -> list[dict]:
        """Получает список постов с API."""
        pass

    @abstractmethod
    def fetch_post(self, post_id: str) -> Post | None:
        """Получает один пост по ID."""
        pass

    @abstractmethod
    def _parse_post(self, raw_data: dict) -> Post:
        """Парсит сырые данные API в Post."""
        pass

    def sync(self):
        """Синхронизирует все новые посты автора."""
        print(f"[{self.PLATFORM}] Синхронизация {self.source.author}...")

        self._create_index_files()

        existing_ids = self.db.get_all_post_ids(self.PLATFORM, self.source.author)
        posts = self.fetch_posts_list()

        new_posts = [p for p in posts if str(p.get('id', p.get('post_id'))) not in existing_ids]
        print(f"  Найдено постов: {len(posts)}, новых: {len(new_posts)}")

        for raw_post in new_posts:
            post = self._parse_post(raw_post)
            if post:
                self._save_post(post)

        # Фиксим ссылки после скачивания всех постов
        if new_posts:
            print(f"  Фиксим внутренние ссылки...")
            self.fix_internal_links()

    def download_single(self, post_id: str):
        """Скачивает один пост по ID."""
        print(f"[{self.PLATFORM}] Скачивание поста {post_id}...")
        post = self.fetch_post(post_id)
        if post:
            self._save_post(post)
        else:
            print(f"  Ошибка: пост {post_id} не найден")

    def _create_index_files(self):
        """Создаёт _index.md файлы для навигации Hugo."""
        # Для платформы
        platform_dir = self.config.output_dir / self.PLATFORM
        platform_dir.mkdir(parents=True, exist_ok=True)
        platform_index = platform_dir / "_index.md"
        if not platform_index.exists():
            platform_index.write_text(f"---\ntitle: {self.PLATFORM.title()}\n---\n", encoding='utf-8')

        # Для автора
        author_dir = platform_dir / self.source.author
        author_dir.mkdir(parents=True, exist_ok=True)
        author_index = author_dir / "_index.md"
        display_name = self.source.display_name or self.source.author
        safe_display_name = display_name.replace('"', '\\"')
        author_index.write_text(f'---\ntitle: "{safe_display_name}"\n---\n', encoding='utf-8')

        # Для posts
        posts_dir = author_dir / "posts"
        posts_dir.mkdir(parents=True, exist_ok=True)
        posts_index = posts_dir / "_index.md"
        posts_index.write_text(f'---\ntitle: "Посты"\n---\n', encoding='utf-8')

    def _save_post(self, post: Post):
        """Сохраняет пост на диск."""
        slug = self._make_slug(post)
        post_dir = self._get_post_dir(slug)
        post_dir.mkdir(parents=True, exist_ok=True)

        # Скачиваем assets
        if self.source.download_assets and post.assets:
            assets_dir = post_dir / "assets"
            assets_dir.mkdir(exist_ok=True)
            asset_map = self._download_assets(post.assets, assets_dir) or {}
        else:
            asset_map = {}

        # Конвертируем в Markdown
        content_md = self._to_markdown(post, asset_map)

        # Создаём frontmatter
        frontmatter = self._make_frontmatter(post)

        # Записываем файл
        md_path = post_dir / "index.md"
        md_path.write_text(frontmatter + content_md, encoding='utf-8')

        # Обновляем индекс
        record = PostRecord(
            platform=self.PLATFORM,
            author=self.source.author,
            post_id=post.post_id,
            title=post.title,
            slug=slug,
            post_date=post.post_date,
            source_url=post.source_url,
            local_path=str(post_dir),
            tags=json.dumps(post.tags, ensure_ascii=False),
            synced_at=datetime.now(timezone.utc).isoformat(),
        )
        self.db.add_post(record)
        print(f"  ✓ {post.title}")

    def _make_slug(self, post: Post) -> str:
        """Создаёт slug для папки поста."""
        date_prefix = post.post_date[:10]
        title_slug = transliterate(post.title)[:60]
        return f"{date_prefix}-{title_slug}"

    def _get_post_dir(self, slug: str) -> Path:
        """Возвращает путь к папке поста."""
        return (
            self.config.output_dir
            / self.PLATFORM
            / self.source.author
            / "posts"
            / slug
        )

    def _make_frontmatter(self, post: Post) -> str:
        """Создаёт YAML frontmatter."""
        # Экранируем кавычки в заголовке
        safe_title = post.title.replace('"', '\\"')

        lines = [
            "---",
            f'title: "{safe_title}"',
            f"date: {post.post_date}",
            f"source: {post.source_url}",
            f"author: {self.source.author}",
            f"platform: {self.PLATFORM}",
            f"post_id: {post.post_id}",
        ]
        if post.tags:
            tags_str = json.dumps(post.tags, ensure_ascii=False)
            lines.append(f"tags: {tags_str}")
        lines.append("---\n\n")
        return "\n".join(lines)

    def _download_assets(self, assets: list[dict], assets_dir: Path) -> dict[str, str]:
        """
        Скачивает assets параллельно.
        Возвращает маппинг {original_url: local_filename}.
        """
        asset_map = {}
        used_filenames: set[str] = set()

        def download_one(asset: dict) -> tuple[str, str | None]:
            url = asset["url"]
            try:
                # Предварительная проверка только по расширению (если есть)
                ext = Path(urlparse(url).path).suffix.lower()
                if ext and ext not in ALLOWED_EXTENSIONS:
                    return url, None

                def do_request():
                    resp = self.session.get(url, stream=True, timeout=self.TIMEOUT)
                    resp.raise_for_status()
                    return resp

                response = retry_request(do_request, max_retries=3)

                content_type = response.headers.get('Content-Type', '')

                # Полная проверка после получения Content-Type
                if not should_download_asset(url, content_type):
                    return url, None

                filename = self._make_asset_filename(url, content_type, asset.get('alt'))
                filepath = assets_dir / filename

                if not filepath.exists():
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                return url, filename
            except requests.RequestException as e:
                print(f"    Ошибка скачивания {url}: {e}")
                return url, None

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {executor.submit(download_one, a): a for a in assets}
            for future in as_completed(futures):
                url, filename = future.result()
                if filename:
                    # Дедупликация имён файлов
                    if filename in used_filenames:
                        filename = self._deduplicate_filename(filename, url)
                    used_filenames.add(filename)
                    asset_map[url] = filename

        return asset_map

    def _deduplicate_filename(self, filename: str, url: str) -> str:
        """Создаёт уникальное имя файла добавляя хеш URL."""
        path = Path(filename)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{path.stem}-{url_hash}{path.suffix}"

    def _make_asset_filename(self, url: str, content_type: str, alt: str | None) -> str:
        """Создаёт имя файла для asset."""
        path = urlparse(url).path
        original_name = Path(path).name
        ext = Path(path).suffix.lower()

        if not ext or ext not in ALLOWED_EXTENSIONS:
            ext = get_extension_from_content_type(content_type) or '.bin'

        if alt:
            name = transliterate(alt)[:50]
        else:
            name = slugify(Path(path).stem or 'asset', max_length=50)

        return f"{name}{ext}"

    def fix_internal_links(self):
        """Фиксит внутренние ссылки во всех постах автора."""
        posts = self.db.get_all_posts(self.PLATFORM, self.source.author)
        if not posts:
            return

        # Строим маппинг post_id → slug
        id_to_slug = {p.post_id: p.slug for p in posts}

        fixed_files = 0

        for post in posts:
            md_path = Path(post.local_path) / "index.md"
            if not md_path.exists():
                continue

            content = md_path.read_text(encoding='utf-8')

            # Разделяем frontmatter и body
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    body = parts[2]
                else:
                    continue
            else:
                continue

            original_body = body

            for full_url, platform, post_id in extract_internal_links(body):
                if post_id in id_to_slug:
                    body = body.replace(full_url, f"../{id_to_slug[post_id]}/")

            if body != original_body:
                new_content = f"---{frontmatter}---{body}"
                md_path.write_text(new_content, encoding='utf-8')
                fixed_files += 1

        if fixed_files:
            print(f"    Исправлено ссылок в {fixed_files} файлах")

    @abstractmethod
    def _to_markdown(self, post: Post, asset_map: dict[str, str]) -> str:
        """Конвертирует контент поста в Markdown."""
        pass
