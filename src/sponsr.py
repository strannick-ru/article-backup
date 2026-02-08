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
        from bs4.element import NavigableString, Tag

        soup = BeautifulSoup(html, 'lxml')
        
        # Удаляем пустые теги форматирования (содержат только пробелы/пустые)
        for tag in reversed(list(soup.find_all(['b', 'strong', 'em', 'i']))):
            # Важно: не удаляем теги, которые оборачивают другие теги,
            # например <em><img/></em> или <strong><br/></strong>.
            if tag.find(True) is not None:
                continue
            text = tag.get_text()
            if not text or text.isspace():
                tag.decompose()

        # Нормализуем узкий паттерн:
        #   <em>LEFT</em><a ...><em>MID</em></a><em>RIGHT</em>
        # в:
        #   <em>LEFT <a ...>MID</a> RIGHT</em>
        # (пробелы/переводы строк между соседними тегами сохраняются)
        def _is_ws_node(node: object) -> bool:
            return isinstance(node, NavigableString) and not str(node).strip()

        def _prev_non_ws_sibling(node: Tag) -> object | None:
            sib = node.previous_sibling
            while sib is not None and _is_ws_node(sib):
                sib = sib.previous_sibling
            return sib

        def _next_non_ws_sibling(node: Tag) -> object | None:
            sib = node.next_sibling
            while sib is not None and _is_ws_node(sib):
                sib = sib.next_sibling
            return sib

        def _starts_with_ws(text: str) -> bool:
            return bool(text) and text[0].isspace()

        def _needs_space_after(text: str) -> bool:
            if not text:
                return False
            last = text[-1]
            return last.isalnum() or last in ',;:'

        def _needs_space_before(text: str) -> bool:
            return bool(text) and text[0].isalnum()

        def _rstrip_ws_to_nbsp(tag: Tag) -> None:
            """Переносит хвостовые пробелы/табы в NBSP.

            Важно: не трогаем переводы строк (\n), чтобы не "схлопывать"
            намеренные переносы.
            """
            if not tag.contents:
                return
            last = tag.contents[-1]
            if not isinstance(last, NavigableString):
                return
            s = str(last)
            m = re.search(r'[ \t]+$', s)
            if not m:
                return
            base = s[:m.start()]
            if base:
                last.replace_with(base)
            else:
                last.extract()
            # bs4 создаст текстовый узел (NavigableString)
            tag.append('\xa0')

        def _lstrip_ws_to_nbsp(node: NavigableString) -> None:
            s = str(node)
            m = re.match(r'^[ \t]+', s)
            if not m:
                return
            node.replace_with('\xa0' + s[m.end():])

        for a in list(soup.find_all('a')):
            left = _prev_non_ws_sibling(a)
            right = _next_non_ws_sibling(a)
            if not (isinstance(left, Tag) and left.name == 'em'):
                continue
            if not (isinstance(right, Tag) and right.name == 'em'):
                continue

            # Узко и безопасно: снаружи и внутри ссылки не допускаем вложенных тегов.
            if left.find(True) is not None or right.find(True) is not None:
                continue

            inner_tags = [c for c in a.contents if isinstance(c, Tag)]
            if len(inner_tags) != 1 or inner_tags[0].name != 'em':
                continue
            inner_em = inner_tags[0]
            if inner_em.find(True) is not None:
                continue
            if any(
                isinstance(c, NavigableString) and str(c).strip()
                for c in a.contents
                if not isinstance(c, Tag)
            ):
                continue

            # Сохраняем поведение узким и безопасным: не сливаем,
            # если атрибуты форматирования различаются.
            left_attrs = dict(left.attrs or {})
            mid_attrs = dict(inner_em.attrs or {})
            right_attrs = dict(right.attrs or {})
            if not (not left_attrs and not mid_attrs and not right_attrs):
                if not (left_attrs == mid_attrs == right_attrs):
                    continue

            # Проверяем, что между em/a/em нет ничего кроме whitespace.
            between_left_a: list[NavigableString] = []
            node = left.next_sibling
            ok = True
            while node is not None and node is not a:
                if not _is_ws_node(node):
                    ok = False
                    break
                between_left_a.append(node)
                node = node.next_sibling
            if not ok or node is None:
                continue

            between_a_right: list[NavigableString] = []
            node = a.next_sibling
            while node is not None and node is not right:
                if not _is_ws_node(node):
                    ok = False
                    break
                between_a_right.append(node)
                node = node.next_sibling
            if not ok or node is None:
                continue

            left_text = left.get_text() or ''
            mid_text = inner_em.get_text() or ''
            right_text = right.get_text() or ''

            import copy

            new_em = soup.new_tag('em')
            new_em.attrs = copy.deepcopy(left.attrs)

            for child in list(left.contents):
                new_em.append(child.extract())
            for n in between_left_a:
                new_em.append(n.extract())

            # Если пробел был в конце LEFT или между тегами, сохраняем его как NBSP,
            # чтобы html2text не "съел" его перед ссылкой.
            _rstrip_ws_to_nbsp(new_em)
            # Если пробела нет, но он нужен между словами, добавляем NBSP.
            if (
                not between_left_a
                and not _starts_with_ws(mid_text)
                and _needs_space_after(left_text)
                and _needs_space_before(mid_text)
            ):
                new_em.append('\xa0')

            inner_em.unwrap()  # <a><em>..</em></a> -> <a>..</a>
            new_em.append(a.extract())

            for n in between_a_right:
                new_em.append(n.extract())

            # Сохраняем возможные пробелы между </a> и RIGHT.
            _rstrip_ws_to_nbsp(new_em)

            # Если RIGHT начинается с пробела/таба, превратим его в NBSP.
            if right.contents and isinstance(right.contents[0], NavigableString):
                _lstrip_ws_to_nbsp(right.contents[0])

            # Если пробела нет, но он нужен между словами, добавляем NBSP.
            if (
                not between_a_right
                and not _starts_with_ws(right_text)
                and (mid_text and mid_text[-1].isalnum())
                and (right_text and right_text[0].isalnum())
            ):
                new_em.append('\xa0')
            for child in list(right.contents):
                new_em.append(child.extract())

            left.replace_with(new_em)
            right.extract()
        
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

        # Консервативная чистка пробелов вокруг Markdown-конструкций.
        # Принцип: не добавлять пробелы "вслепую" (и тем более внутри слов),
        # а исправлять только узкие артефакты html2text/предобработки.
        def _cleanup_spacing(text: str) -> str:
            # 1) Убираем пробелы внутри квадратных скобок ссылки, когда там есть форматирование.
            #    [ _Конан_ ] -> [_Конан_]
            text = re.sub(r'\[[ \t]+([_*])', r'[\1', text)
            text = re.sub(r'([_*])[ \t]+\]', r'\1]', text)

            # 1.5) Тримим пробелы/табы сразу внутри маркеров emphasis.
            # html2text иногда создаёт `_ текст _` (например, когда пробелы идут отдельными узлами span/NBSP).
            def _trim_em_inner(delim: str, inner: str) -> str:
                trimmed = inner.strip(' \t')
                return f"{delim}{trimmed}{delim}" if trimmed else f"{delim}{inner}{delim}"

            text = re.sub(r'\*\*\*([^*\n]+?)\*\*\*', lambda m: _trim_em_inner('***', m.group(1)), text)
            text = re.sub(r'(?<!\*)\*\*([^*\n]+?)\*\*(?!\*)', lambda m: _trim_em_inner('**', m.group(1)), text)
            text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', lambda m: _trim_em_inner('*', m.group(1)), text)
            text = re.sub(r'_([^_\n]+?)_', lambda m: _trim_em_inner('_', m.group(1)), text)

            # 2) Убираем пробелы перед пунктуацией сразу после закрывающего форматирования.
            #    ***...*** : -> ***...***:
            emphasis_span = r'(?:\*\*\*[^*\n]+?\*\*\*|\*\*[^*\n]+?\*\*|_[^_\n]+?_|\*[^*\n]+?\*)'
            text = re.sub(rf'({emphasis_span})[ \t]+([:;,.!?])', r'\1\2', text)

            word_char = r'[0-9A-Za-zА-Яа-яЁё]'

            # 3) html2text иногда "съедает" пробел перед **жирным** внутри _курсива_.
            #    _курсив**жирный** курсив_ -> _курсив **жирный** курсив_
            def _fix_bold_spacing_inside_underscore_italic(m: re.Match) -> str:
                inner = m.group('inner')
                inner = re.sub(
                    rf'(?P<l>{word_char})\*\*(?P<b>[^*\n]+?)\*\*(?=[ \t]+{word_char})',
                    r'\g<l> **\g<b>**',
                    inner,
                )
                return f"_{inner}_"

            text = re.sub(r'_(?P<inner>[^_\n]+?)_', _fix_bold_spacing_inside_underscore_italic, text)

            # 4) Склеиваем разорванные слова, когда форматирование находится внутри слова.
            #    п ***о*** том -> п***о***том
            # Варианты артефактов: пробелы могут быть с обеих сторон или только с одной.
            inside_word_both = re.compile(rf'(?P<l>{word_char})[ \t]+(?P<em>{emphasis_span})[ \t]+(?P<r>{word_char})')
            inside_word_left = re.compile(rf'(?P<l>{word_char})[ \t]+(?P<em>{emphasis_span})(?P<r>{word_char})')
            inside_word_right = re.compile(rf'(?P<l>{word_char})(?P<em>{emphasis_span})[ \t]+(?P<r>{word_char})')
            common_one_letter_words = {
                # ru
                'и', 'а', 'я', 'о', 'у', 'в', 'к', 'с',
                # en
                'a', 'i',
            }

            def _em_inner(em: str) -> str:
                for pre, suf in (("***", "***"), ("**", "**"), ("_", "_"), ("*", "*")):
                    if em.startswith(pre) and em.endswith(suf) and len(em) >= len(pre) + len(suf):
                        return em[len(pre) : -len(suf)]
                return em

            def _is_short_emphasis(em: str) -> bool:
                inner = _em_inner(em).strip()
                if re.search(r'\s', inner):
                    return False
                return re.fullmatch(rf'{word_char}{{1,3}}', inner) is not None

            def _join_if_inside_word(m: re.Match, *, require_short: bool) -> str:
                l = m.group('l')
                r = m.group('r')

                if require_short and not _is_short_emphasis(m.group('em')):
                    return m.group(0)

                # Если слева односимвольное слово ("и", "а", "в"...),
                # лучше не склеивать: высок риск "починить" авторский текст.
                i = m.start('l')
                prev = text[i - 1] if i > 0 else ''
                if (i == 0 or prev.isspace()) and l.lower() in common_one_letter_words:
                    return m.group(0)

                return f"{l}{m.group('em')}{r}"

            text = inside_word_both.sub(lambda m: _join_if_inside_word(m, require_short=True), text)
            text = inside_word_left.sub(lambda m: _join_if_inside_word(m, require_short=False), text)
            # Если слева форматирование уже приклеено к слову, а пробел остался справа,
            # это почти наверняка разрыв одного слова.
            text = inside_word_right.sub(lambda m: _join_if_inside_word(m, require_short=False), text)

            # 5) Добавляем пропущенный пробел после запятой перед ссылкой.
            #    кинополотна,[Конан](...) -> кинополотна, [Конан](...)
            text = re.sub(r',[ \t]*(\[[^\]]+\]\([^)]+\))', r', \1', text)

            # 6) Разделяем слова и markdown-ссылки, если они "слиплись".
            #    подтвердилa[...](...)и -> подтвердилa [...](...) и
            link = r'(?:\[[^\]]+\]\([^)]+\))'
            text = re.sub(rf'({word_char})({link})', r'\1 \2', text)
            text = re.sub(rf'({link})({word_char})', r'\1 \2', text)

            return text

        markdown = _cleanup_spacing(markdown)

        # Markdown (CommonMark/Goldmark): `_em_` внутри слова часто НЕ рендерится как курсив.
        # Если курсив "вшит" в слово (буква + _..._ + буква), иногда нужно переводить в `*...*`.
        # Правило (консервативно):
        # - всегда конвертируем, если внутри есть пробелы/markdown-маркеры (типичный вывод html2text);
        # - дополнительно конвертируем одно-трёхбуквенные вставки кириллицы, если контекст кириллический
        #   (например: п_о_том -> п*о*том), чтобы Goldmark не игнорировал курсив.
        word_char = r'[0-9A-Za-zА-Яа-яЁё]'
        intraword_underscore_italic = re.compile(
            rf'(?P<l>{word_char})_(?P<inner>[^_\n]+?)_(?P<r>{word_char})'
        )

        def _intraword_underscore_to_asterisk(m: re.Match) -> str:
            l = m.group('l')
            inner = m.group('inner')
            r = m.group('r')
            # Защита от ложных срабатываний на литералах с подчёркиваниями (foo_bar_baz).
            # Конвертируем только когда это очень похоже на курсив из html2text:
            # внутри обычно есть пробелы и/или markdown-маркеры (например '**' или '[...]').
            looks_like_html2text_em = any(ch.isspace() for ch in inner) or '*' in inner or '[' in inner

            # Спец-случай: одна-три кириллические буквы внутри кириллического контекста.
            # Это безопаснее, чем конвертировать любые короткие вставки, и не ломает foo_bar_baz.
            cyr = r'[А-Яа-яЁё]'
            has_cyr_context = re.search(cyr, f"{l}{inner}{r}") is not None
            is_short_cyr_inner = re.fullmatch(rf'{cyr}{{1,3}}', inner) is not None

            if not (looks_like_html2text_em or (has_cyr_context and is_short_cyr_inner)):
                return m.group(0)
            return f"{l}*{inner}*{r}"

        markdown = intraword_underscore_italic.sub(_intraword_underscore_to_asterisk, markdown)

        return markdown
