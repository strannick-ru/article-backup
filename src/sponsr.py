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

    def fetch_posts_list(
        self,
        existing_ids: set[str] | None = None,
        incremental: bool = False,
        safety_chunks: int = 1
    ) -> list[dict]:
        """
        Получает список постов через API.
        
        Args:
            existing_ids: Множество уже загруженных post_id (для инкрементального режима)
            incremental: Включить инкрементальный режим
            safety_chunks: Количество "защитных" чанков перед остановкой
        """
        project_id = self._get_project_id()
        all_posts = []
        offset = 0
        clean_chunks_count = 0  # Счётчик "чистых" чанков

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

            # Инкрементальный режим: проверяем, все ли посты уже существуют
            if incremental and existing_ids is not None:
                chunk_ids = {str(p.get('post_id')) for p in posts_chunk}
                all_existing = chunk_ids.issubset(existing_ids)

                if all_existing:
                    clean_chunks_count += 1
                    print(f"  Получено {offset}/{total} постов... (чанк уже скачан)")
                    # Останавливаемся после safety_chunks + 1 (первый чистый + N защитных)
                    if clean_chunks_count > safety_chunks:
                        print(f"  ⚡ Остановлено на {offset} постах (все новые загружены)")
                        break
                else:
                    clean_chunks_count = 0
                    print(f"  Получено {offset}/{total} постов...")
            else:
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
        post_id = str(raw_data.get('post_id') or raw_data.get('id'))
        title = raw_data.get('post_title') or raw_data.get('title') or 'Без названия'
        post_date = raw_data.get('post_date') or raw_data.get('date') or ''

        # URL поста
        post_url = raw_data.get('post_url') or f"/{self.source.author}/{post_id}/"
        if post_url and not post_url.startswith('http'):
            post_url = f"https://sponsr.ru{post_url}"

        # HTML контент
        content_obj = raw_data.get('post_text') or raw_data.get('text')
        if isinstance(content_obj, dict):
            content_html = content_obj.get('text', '')
        elif isinstance(content_obj, str):
            content_html = content_obj
        else:
            content_html = ''

        # Теги - извлекаем только имена из объектов
        tags_raw = raw_data.get('tags', [])
        tags = []
        if isinstance(tags_raw, list):
            for tag in tags_raw:
                if isinstance(tag, dict):
                    # API может вернуть объект с полем tag_name или tag.tag_name
                    tag_name = tag.get('tag_name') or tag.get('tag', {}).get('tag_name')
                    if tag_name:
                        tags.append(tag_name)
                elif isinstance(tag, str):
                    tags.append(tag)

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

    def _cleanup_html(self, html: str) -> str:
        """Предобработка HTML перед конвертацией в Markdown."""
        from bs4 import BeautifulSoup
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Удаляем пустые теги форматирования (содержат только пробелы/пустые)
        for tag in soup.find_all(['b', 'strong', 'em', 'i']):
            text = tag.get_text()
            if not text:
                tag.decompose()
            elif text.isspace():
                tag.replace_with(text)
        
        return str(soup)

    def _to_markdown(self, post: Post, asset_map: dict[str, str]) -> str:
        """Конвертирует HTML в Markdown."""
        if not post.content_html:
            return ""

        # Заменяем URL изображений на локальные
        html = post.content_html
        for original_url, local_filename in asset_map.items():
            html = html.replace(original_url, f"assets/{local_filename}")

        # Заменяем iframe/embed видео на markdown-ссылки
        html = self._replace_video_embeds(html)
        
        # Предобработка HTML
        html = self._cleanup_html(html)

        # Конвертируем HTML в Markdown
        h2t = html2text.HTML2Text()
        h2t.ignore_links = False
        h2t.ignore_images = False
        h2t.body_width = 0  # Без переноса строк
        h2t.unicode_snob = True

        markdown = h2t.handle(html)

        # Удаляем bidi-маркеры, которые ломают пробелы рядом с текстом
        markdown = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', markdown)

        # Нормализуем неразрывные пробелы
        markdown = re.sub(r'[\u00a0\u202f]', ' ', markdown)

        # Склеиваем вложенные em/strong в жирный курсив
        # html2text создаёт ** _текст_** или _**текст**_ для <b><em> (с пробелами)
        markdown = re.sub(r'\*\*\s*_(.+?)_\s*\*\*', r'***\1***', markdown)
        markdown = re.sub(r'_\s*\*\*(.+?)\*\*\s*_', r'***\1***', markdown)
        
        # Перемещаем форматирование внутрь ссылок
        # [** _текст_**](url) → [***текст***](url)
        markdown = re.sub(r'\[(\*{2,3})\s*(.+?)\s*(\*{2,3})\]\((.+?)\)', r'[\1\2\3](\4)', markdown)
        # ***[текст](url)*** → [***текст***](url)
        markdown = re.sub(r'(\*{2,3})\[(.+?)\]\((.+?)\)\1', r'[\1\2\1](\3)', markdown)
        # _[текст](url)_ → [_текст_](url)
        markdown = re.sub(r'_\[(.+?)\]\((.+?)\)_', r'[_\1_](\2)', markdown)

        # Убираем лишние пробелы, добавленные html2text рядом с Unicode-кавычками
        # Открывающие: « „ " '
        markdown = re.sub(r'([\u00ab\u201e\u201c\u2018])\s+', r'\1', markdown)
        # Закрывающие: » " '
        markdown = re.sub(r'\s+([\u00bb\u201d\u2019])', r'\1', markdown)

        # Восстанавливаем пробелы вокруг форматирования и ссылок
        def _fix_spacing(text: str, pattern: re.Pattern) -> str:
            """Добавляет пробелы вокруг элементов, если их нет."""
            parts = []
            last = 0
            for match in pattern.finditer(text):
                start, end = match.span()
                before = text[last:start]
                
                # Добавляем пробел слева, если нужно
                if start > 0 and before and before[-1].isalnum():
                    before = before + ' '
                
                parts.append(before)
                
                # Добавляем сам матч
                matched_text = text[start:end]
                
                # Добавляем пробел справа, если нужно
                if end < len(text) and text[end].isalnum():
                    matched_text = matched_text + ' '
                
                parts.append(matched_text)
                last = end

            parts.append(text[last:])
            return ''.join(parts)

        # Восстанавливаем пробелы вокруг bold-italic, bold, ссылок
        markdown = _fix_spacing(markdown, re.compile(r'\*\*\*.+?\*\*\*'))
        markdown = _fix_spacing(markdown, re.compile(r'(?<!\*)\*\*(?!\*).+?(?<!\*)\*\*(?!\*)'))
        markdown = _fix_spacing(markdown, re.compile(r'\[[^\]]+\]\([^)]+\)'))

        # Заголовок берётся из frontmatter (Hugo), не дублируем его в body.
        return markdown
