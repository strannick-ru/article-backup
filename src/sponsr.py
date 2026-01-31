# src/sponsr.py
"""Загрузчик для Sponsr.ru"""

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import html2text

from .config import Config, Source, load_cookie
from .database import Database
from .downloader import BaseDownloader, Post

# Паттерны для преобразования embed URL в watch URL
VIDEO_EMBED_PATTERNS = [
    (r'rutube\.ru/play/embed/([a-f0-9]+)', lambda m: f'https://rutube.ru/video/{m.group(1)}/'),
    (r'youtube\.com/embed/([^/?]+)', lambda m: f'https://youtube.com/watch?v={m.group(1)}'),
    (r'youtu\.be/([^/?]+)', lambda m: f'https://youtube.com/watch?v={m.group(1)}'),
    (r'player\.vimeo\.com/video/(\d+)', lambda m: f'https://vimeo.com/{m.group(1)}'),
    (r'ok\.ru/videoembed/(\d+)', lambda m: f'https://ok.ru/video/{m.group(1)}'),
    (r'vk\.com/video_ext\.php\?.*?oid=(-?\d+).*?id=(\d+)', lambda m: f'https://vk.com/video{m.group(1)}_{m.group(2)}'),
]


class SponsorDownloader(BaseDownloader):
    """Загрузчик статей с Sponsr.ru"""

    PLATFORM = "sponsr"

    def __init__(self, config: Config, source: Source, db: Database):
        self._project_id: str | None = None
        super().__init__(config, source, db)

    def _setup_session(self):
        """Настройка сессии с cookies."""
        cookie = load_cookie(self.config.auth.sponsr_cookie_file)
        self.session.headers.update({
            'Cookie': cookie,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'X-Requested-With': 'XMLHttpRequest',
        })

    def _get_project_id(self) -> str:
        """Получает project_id со страницы проекта."""
        if self._project_id:
            return self._project_id

        url = f"https://sponsr.ru/{self.source.author}/"
        response = self.session.get(url, timeout=self.TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'lxml')
        data_tag = soup.find('script', id='__NEXT_DATA__')
        if not data_tag:
            raise ValueError(f"Не найден __NEXT_DATA__ на странице {url}")

        data = json.loads(data_tag.string)
        project_id = data.get('props', {}).get('pageProps', {}).get('project', {}).get('id')
        if not project_id:
            raise ValueError(f"Не найден project.id в __NEXT_DATA__")

        self._project_id = str(project_id)
        return self._project_id

    def fetch_posts_list(self) -> list[dict]:
        """Получает список всех постов через API."""
        project_id = self._get_project_id()
        all_posts = []
        offset = 0

        while True:
            api_url = f"https://sponsr.ru/project/{project_id}/more-posts/?offset={offset}"
            response = self.session.get(api_url, timeout=self.TIMEOUT)
            response.raise_for_status()

            data = response.json().get("response", {})
            posts_chunk = data.get("rows", [])

            if not posts_chunk:
                break

            all_posts.extend(posts_chunk)
            offset = len(all_posts)

            total = data.get("rows_count", 0)
            print(f"  Получено {offset}/{total} постов...")

        return all_posts

    def fetch_post(self, post_id: str) -> Post | None:
        """Получает один пост по ID."""
        # Сначала пробуем получить напрямую со страницы поста
        post = self._fetch_post_from_page(post_id)
        if post:
            return post

        # Fallback: ищем в API постранично (без загрузки всего списка)
        return self._find_post_in_api(post_id)

    def _fetch_post_from_page(self, post_id: str) -> Post | None:
        """Получает пост напрямую со страницы."""
        # URL формат: https://sponsr.ru/{author}/{post_id}/...
        url = f"https://sponsr.ru/{self.source.author}/{post_id}/"
        try:
            response = self.session.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')
            data_tag = soup.find('script', id='__NEXT_DATA__')
            if not data_tag:
                return None

            data = json.loads(data_tag.string)
            post_data = data.get('props', {}).get('pageProps', {}).get('post')
            if not post_data:
                return None

            return self._parse_post(post_data)
        except requests.RequestException:
            return None

    def _find_post_in_api(self, post_id: str) -> Post | None:
        """Ищет пост в API постранично (останавливается при нахождении)."""
        project_id = self._get_project_id()
        offset = 0

        while True:
            api_url = f"https://sponsr.ru/project/{project_id}/more-posts/?offset={offset}"
            try:
                response = self.session.get(api_url, timeout=self.TIMEOUT)
                response.raise_for_status()

                data = response.json().get("response", {})
                posts_chunk = data.get("rows", [])

                if not posts_chunk:
                    break

                for raw_post in posts_chunk:
                    if str(raw_post.get('post_id')) == post_id:
                        return self._parse_post(raw_post)

                offset += len(posts_chunk)
            except requests.RequestException:
                break

        return None

    def _parse_post(self, raw_data: dict) -> Post:
        """Парсит сырые данные API в Post."""
        post_id = str(raw_data['post_id'])
        title = raw_data.get('post_title', 'Без названия')
        post_date = raw_data.get('post_date', '')

        # URL поста
        post_url = raw_data.get('post_url', '')
        if post_url and not post_url.startswith('http'):
            post_url = f"https://sponsr.ru{post_url}"

        # HTML контент
        content_html = raw_data.get('post_text', '')

        # Теги
        tags = raw_data.get('tags', [])

        # Извлекаем assets из HTML
        assets = self._extract_assets(content_html)

        return Post(
            post_id=post_id,
            title=title,
            content_html=content_html,
            post_date=post_date,
            source_url=post_url,
            tags=tags,
            assets=assets,
        )

    def _extract_assets(self, html_content: str) -> list[dict]:
        """Извлекает URL изображений из HTML."""
        if not html_content:
            return []

        assets = []
        soup = BeautifulSoup(html_content, 'lxml')

        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if not src:
                continue

            # Абсолютный URL
            if not src.startswith('http'):
                src = urljoin('https://sponsr.ru', src)

            # Alt текст
            alt = img.get('alt', '')
            if not alt:
                parent = img.find_parent('div', class_='post-image')
                if parent and parent.get('data-alt'):
                    alt = parent.get('data-alt')

            assets.append({'url': src, 'alt': alt})

        return assets

    def _parse_video_url(self, embed_src: str) -> str | None:
        """Преобразует embed URL в watch URL."""
        for pattern, converter in VIDEO_EMBED_PATTERNS:
            match = re.search(pattern, embed_src)
            if match:
                return converter(match)
        # Fallback: вернуть оригинальный URL если не распознан
        if embed_src and ('video' in embed_src or 'embed' in embed_src):
            return embed_src
        return None

    def _replace_video_embeds(self, html_content: str) -> str:
        """Заменяет iframe/embed видео на markdown-ссылки."""
        soup = BeautifulSoup(html_content, 'lxml')

        for iframe in soup.find_all(['iframe', 'embed']):
            src = iframe.get('src', '')
            video_url = self._parse_video_url(src)
            if video_url:
                placeholder = soup.new_tag('p')
                placeholder.string = f'📹 Видео: {video_url}'
                iframe.replace_with(placeholder)

        return str(soup)

    def _to_markdown(self, post: Post, asset_map: dict[str, str]) -> str:
        """Конвертирует HTML в Markdown."""
        if not post.content_html:
            return f"# {post.title}\n\n"

        # Заменяем URL изображений на локальные
        html = post.content_html
        for original_url, local_filename in asset_map.items():
            html = html.replace(original_url, f"assets/{local_filename}")

        # Заменяем iframe/embed видео на markdown-ссылки
        html = self._replace_video_embeds(html)

        # Конвертируем HTML в Markdown
        h2t = html2text.HTML2Text()
        h2t.ignore_links = False
        h2t.ignore_images = False
        h2t.body_width = 0  # Без переноса строк
        h2t.unicode_snob = True

        markdown = h2t.handle(html)

        # Добавляем заголовок
        return f"# {post.title}\n\n{markdown}"
