# src/boosty.py
"""Загрузчик для Boosty.to"""

import json
from datetime import datetime, timezone

import requests

from .config import Config, Source, load_cookie, load_auth_header
from .database import Database
from .downloader import BaseDownloader, Post


class BoostyDownloader(BaseDownloader):
    """Загрузчик статей с Boosty.to"""

    PLATFORM = "boosty"
    API_BASE = "https://api.boosty.to/v1"

    def _setup_session(self):
        """Настройка сессии с cookies и authorization."""
        cookie = load_cookie(self.config.auth.boosty_cookie_file)
        auth = load_auth_header(self.config.auth.boosty_auth_file)

        self.session.headers.update({
            'Cookie': cookie,
            'Authorization': auth,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })

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
        all_posts = []
        offset = None
        clean_chunks_count = 0  # Счётчик "чистых" чанков

        while True:
            url = f"{self.API_BASE}/blog/{self.source.author}/post/?limit=20"
            if offset:
                url += f"&offset={offset}"

            response = self.session.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()

            data = response.json()
            posts_chunk = data.get("data", [])

            if not posts_chunk:
                break

            all_posts.extend(posts_chunk)

            # Инкрементальный режим: проверяем, все ли посты уже существуют
            if incremental and existing_ids is not None:
                chunk_ids = {p.get("id") for p in posts_chunk}
                all_existing = chunk_ids.issubset(existing_ids)

                if all_existing:
                    clean_chunks_count += 1
                    print(f"  Получено {len(all_posts)} постов... (чанк уже скачан)")
                    # Останавливаемся после safety_chunks + 1 (первый чистый + N защитных)
                    if clean_chunks_count > safety_chunks:
                        print(f"  ⚡ Остановлено на {len(all_posts)} постах (все новые загружены)")
                        break
                else:
                    clean_chunks_count = 0
                    print(f"  Получено {len(all_posts)} постов...")
            else:
                print(f"  Получено {len(all_posts)} постов...")

            # Проверяем, есть ли ещё страницы
            extra = data.get("extra", {})
            if extra.get("isLast", True):
                break

            offset = extra.get("offset")
            if not offset:
                break

        return all_posts

    def fetch_post(self, post_id: str) -> Post | None:
        """Получает один пост по ID."""
        url = f"{self.API_BASE}/blog/{self.source.author}/post/{post_id}"

        try:
            response = self.session.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()
            data = response.json()
            return self._parse_post(data)
        except requests.RequestException as e:
            print(f"  Ошибка получения поста {post_id}: {e}")
            return None

    def _parse_post(self, raw_data: dict) -> Post:
        """Парсит сырые данные API в Post."""
        post_id = raw_data.get("id", "")
        title = raw_data.get("title", "Без названия")

        # Дата — timestamp в секундах
        created_at = raw_data.get("createdAt", 0)
        post_date = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()

        # URL поста
        author = raw_data.get("user", {}).get("blogUrl", self.source.author)
        source_url = f"https://boosty.to/{author}/posts/{post_id}"

        # Теги
        tags = [t.get("title", "") for t in raw_data.get("tags", []) if t.get("title")]

        # Контент — массив блоков
        content_blocks = raw_data.get("data", [])

        # Извлекаем assets
        assets = self._extract_assets(content_blocks)

        return Post(
            post_id=post_id,
            title=title,
            content_html=json.dumps(content_blocks, ensure_ascii=False),
            post_date=post_date,
            source_url=source_url,
            tags=tags,
            assets=assets,
        )

    def _extract_assets(self, blocks: list[dict]) -> list[dict]:
        """Извлекает URL медиафайлов из блоков контента."""
        assets = []

        for block in blocks:
            block_type = block.get("type", "")

            if block_type == "image":
                url = block.get("url", "")
                if url:
                    assets.append({
                        "url": url,
                        "alt": block.get("id", ""),
                    })

            elif block_type == "audio_file":
                url = block.get("url", "")
                if url:
                    assets.append({
                        "url": url,
                        "alt": block.get("title", block.get("id", "")),
                    })

            elif block_type == "ok_video":
                # ok.ru видео требует отдельной обработки
                # Пока сохраняем только превью, если есть
                preview = block.get("previewUrl") or block.get("preview") or ""
                if preview:
                    assets.append({
                        "url": preview,
                        "alt": f"video-preview-{block.get('id', '')}",
                    })

        return assets

    def _to_markdown(self, post: Post, asset_map: dict[str, str]) -> str:
        """Конвертирует блоки контента в Markdown."""
        try:
            blocks = json.loads(post.content_html)
        except json.JSONDecodeError:
            return ""

        lines: list[str] = []

        for block in blocks:
            md = self._block_to_markdown(block, asset_map)
            if md:
                lines.append(md)

        return "\n".join(lines)

    def _block_to_markdown(self, block: dict, asset_map: dict[str, str]) -> str:
        """Конвертирует один блок в Markdown."""
        block_type = block.get("type", "")

        if block_type == "text":
            return self._parse_text_block(block)

        elif block_type == "image":
            url = block.get("url", "")
            local = asset_map.get(url)
            if local:
                return f"\n![](assets/{local})\n"
            elif url:
                return f"\n![]({url})\n"

        elif block_type == "link":
            url = block.get("url", "")
            text = self._parse_text_block(block)
            if text and url:
                return f"[{text}]({url})"
            elif url:
                return f"<{url}>"

        elif block_type == "audio_file":
            url = block.get("url", "")
            title = block.get("title", "audio")
            local = asset_map.get(url)
            if local:
                return f"\n🎵 **{title}**: [скачать](assets/{local})\n"
            elif url:
                return f"\n🎵 **{title}**: [слушать]({url})\n"

        elif block_type == "ok_video":
            video_id = block.get("id", "")
            return f"\n📹 Видео: https://ok.ru/video/{video_id}\n"

        return ""

    def _parse_text_block(self, block: dict) -> str:
        """Парсит текстовый блок Boosty."""
        content = block.get("content", "")
        modificator = block.get("modificator", "")

        # BLOCK_END — разделитель параграфов
        if modificator == "BLOCK_END":
            return "\n"

        if not content:
            return ""

        # Формат: ["текст", "стиль", [[тип, начало, длина], ...]]
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list) and len(parsed) >= 1:
                text = str(parsed[0])

                # Применяем стили, если есть
                if len(parsed) >= 3 and parsed[2]:
                    text = self._apply_styles(text, parsed[2])

                return text
        except (json.JSONDecodeError, IndexError, TypeError):
            return content

        return ""

    def _apply_styles(self, text: str, styles: list) -> str:
        """Применяет стили к тексту (bold, italic)."""
        if not styles or not text:
            return text

        # Сортируем стили по позиции в обратном порядке
        # чтобы вставка не сбивала индексы
        sorted_styles = sorted(styles, key=lambda s: s[1] if len(s) > 1 else 0, reverse=True)

        result = text
        for style in sorted_styles:
            if len(style) < 3:
                continue

            style_type, start, length = style[0], style[1], style[2]
            end = start + length

            if start < 0 or end > len(result):
                continue

            fragment = result[start:end]

            # Типы стилей (примерные, на основе анализа)
            if style_type == 1:  # bold
                styled = f"**{fragment}**"
            elif style_type == 2:  # italic
                styled = f"*{fragment}*"
            elif style_type == 4:  # ссылка (обрабатывается в link блоках)
                styled = fragment
            else:
                styled = fragment

            result = result[:start] + styled + result[end:]

        return result
