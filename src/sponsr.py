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
from .downloader import BaseDownloader, Post, retry_request

# Паттерны для распознавания embed URL видеохостингов (whitelist).
# Если iframe src матчит один из паттернов — это встроенное видео.
VIDEO_EMBED_PATTERNS = [
    r'rutube\.ru/play/embed/',
    r'youtube\.com/embed/',
    r'player\.vimeo\.com/video/',
    r'ok\.ru/videoembed/',
    r'vk\.com/video_ext\.php',
]


class SponsorDownloader(BaseDownloader):
    """Загрузчик статей с Sponsr.ru"""

    PLATFORM = "sponsr"
    FETCH_FULL_POST_IN_SYNC = True

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
        def do_request():
            resp = self.session.get(url, timeout=self.TIMEOUT)
            resp.raise_for_status()
            return resp

        response = retry_request(do_request, max_retries=3)

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
            def do_request():
                resp = self.session.get(api_url, timeout=self.TIMEOUT)
                resp.raise_for_status()
                return resp

            response = retry_request(do_request, max_retries=3)

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
            def do_request():
                resp = self.session.get(url, timeout=self.TIMEOUT)
                resp.raise_for_status()
                return resp

            response = retry_request(do_request, max_retries=3)

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
                def do_request():
                    resp = self.session.get(api_url, timeout=self.TIMEOUT)
                    resp.raise_for_status()
                    return resp

                response = retry_request(do_request, max_retries=3)

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

    def _is_video_embed(self, src: str) -> bool:
        """Проверяет, является ли URL embed-ссылкой на известный видеохостинг."""
        for pattern in VIDEO_EMBED_PATTERNS:
            if re.search(pattern, src):
                return True
        return False

    def _replace_video_embeds(self, html_content: str) -> str:
        """Заменяет iframe/embed видео на HTML-ссылки.
        
        Распознанные видеохостинги → <a href="embed_url">📹 Видео</a>
        (html2text превратит в markdown-ссылку, Hugo render hook — в iframe).
        Нераспознанные → текстовая ссылка как fallback.
        """
        soup = BeautifulSoup(html_content, 'lxml')

        for iframe in soup.find_all(['iframe', 'embed']):
            src = iframe.get('src', '')
            if not src:
                continue

            if self._is_video_embed(src):
                # Распознанный видеохостинг → ссылка с embed URL
                link = soup.new_tag('a', href=src)
                link.string = '\U0001f4f9 Видео'
                wrapper = soup.new_tag('p')
                wrapper.append(link)
                iframe.replace_with(wrapper)
            elif 'video' in src or 'embed' in src:
                # Нераспознанный, но похож на видео → текстовая ссылка
                link = soup.new_tag('a', href=src)
                link.string = '\U0001f4f9 Видео'
                wrapper = soup.new_tag('p')
                wrapper.append(link)
                iframe.replace_with(wrapper)

        return str(soup)

    def _cleanup_html(self, html: str) -> str:
        """Предобработка HTML перед конвертацией в Markdown."""
        from bs4 import BeautifulSoup, NavigableString
        
        soup = BeautifulSoup(html, 'lxml')
        
        # 1. Слияние вложенных одинаковых тегов: <em><em>text</em></em> → <em>text</em>
        #    Также обрабатывает эквиваленты: <b><strong>, <em><i> и т.п.
        equivalent_tags = {'b': 'strong', 'strong': 'b', 'em': 'i', 'i': 'em'}
        for tag in list(soup.find_all(['b', 'strong', 'em', 'i'])):
            if tag.parent is None:
                continue
            # Проверяем: тег содержит ровно один дочерний элемент того же типа
            children = list(tag.children)
            if len(children) == 1 and hasattr(children[0], 'name'):
                child = children[0]
                equiv = equivalent_tags.get(tag.name)
                if child.name == tag.name or child.name == equiv:
                    # Разворачиваем внутренний тег, оставляя внешний
                    child.unwrap()
        
        # 2. Слияние соседних <em>/<i> тегов внутри одного родителя.
        #    <em>вы</em> <b><em>обязаны</em></b> <em>это</em>
        #    → <em>вы <b>обязаны</b> это</em>
        #    Это предотвращает фрагментированный курсив после html2text.
        em_tags = {'em', 'i'}
        bold_tags = {'b', 'strong'}
        self._merge_adjacent_em(soup, em_tags, bold_tags)
        
        # 3. Удаляем пустые теги форматирования и выносим пробелы наружу
        for tag in list(soup.find_all(['b', 'strong', 'em', 'i'])):
            if tag.parent is None:
                continue
            text = tag.get_text()
            if not text:
                tag.decompose()
            elif text.isspace():
                tag.replace_with(text)
            else:
                # Вынос leading пробелов из тега наружу (перед тегом)
                first_text = self._first_navigable_string(tag)
                if first_text is not None and first_text.lstrip() != first_text:
                    leading = first_text[:len(first_text) - len(first_text.lstrip())]
                    first_text.replace_with(first_text.lstrip())
                    tag.insert_before(NavigableString(leading))
                
                # Вынос trailing пробелов из тега наружу (после тега)
                last_text = self._last_navigable_string(tag)
                if last_text is not None and last_text.rstrip() != last_text:
                    trailing = last_text[len(last_text.rstrip()):]
                    last_text.replace_with(last_text.rstrip())
                    tag.insert_after(NavigableString(trailing))
        
        # 4. Вынос trailing/leading пробелов из <a> тегов наружу
        for tag in list(soup.find_all('a')):
            if tag.parent is None:
                continue
            children = list(tag.children)
            if children:
                last_child = children[-1]
                if isinstance(last_child, NavigableString) and last_child != last_child.rstrip():
                    trailing = str(last_child)[len(str(last_child).rstrip()):]
                    last_child.replace_with(NavigableString(str(last_child).rstrip()))
                    tag.insert_after(NavigableString(trailing))
        
        # 5. Экранирование markdown-символов в текстовых узлах
        #    Чтобы "сырые" _, *, [ ] в тексте не превращались в разметку
        self._escape_text_nodes(soup)

        # 6. Умная расстановка пробелов вокруг inline-тегов в DOM.
        #    Вместо regex-постпроцессинга, мы раздвигаем "слипшиеся" узлы
        #    на уровне HTML (текст<b>bold</b> -> текст <b>bold</b>).
        self._ensure_spacing(soup)

        return str(soup)

    @staticmethod
    def _ensure_spacing(soup):
        """Обеспечивает наличие пробелов вокруг inline-тегов в DOM.
        
        Если текстовый узел "прилип" к тегу форматирования, вставляет маркер.
        Пример: "word<b>bold</b>" -> "word@@@SP@@@<b>bold</b>"
        html2text сохранит это как "word@@@SP@@@**bold**".
        Позже маркер заменяется на пробел.
        Использование NBSP или обычного пробела ненадежно, т.к. html2text может их схлопнуть.
        """
        from bs4 import NavigableString, Tag
        
        # Маркер для принудительного пробела
        SPACER = '@@@SP@@@'
        
        # Теги, вокруг которых нужны пробелы (если они граничат с текстом)
        inline_tags = {'b', 'strong', 'em', 'i', 'a', 'code', 'span'}
        
        # Обходим все такие теги
        for tag in soup.find_all(list(inline_tags)):
            if tag.parent is None:
                continue
                
            # --- Проверка слева (prev_sibling) ---
            prev_node = tag.previous_sibling
            if isinstance(prev_node, NavigableString):
                text = str(prev_node)
                if text:
                    # Если текст заканчивается пробелом -> заменяем его на маркер
                    if text.endswith(' '):
                        new_text = text.rstrip(' ')
                        if new_text:
                            prev_node.replace_with(NavigableString(new_text))
                        else:
                            prev_node.extract()
                        tag.insert_before(NavigableString(SPACER))
                    
                    # Если нет пробела, но нужен (буква/пунктуация)
                    elif text[-1].isalnum() or text[-1] in '.,:;!?")':
                        tag.insert_before(NavigableString(SPACER))
            
            # --- Проверка справа (next_sibling) ---
            next_node = tag.next_sibling
            if isinstance(next_node, NavigableString):
                text = str(next_node)
                if text:
                    # Если текст начинается с пробела -> заменяем
                    if text.startswith(' '):
                        new_text = text.lstrip(' ')
                        if new_text:
                            next_node.replace_with(NavigableString(new_text))
                        else:
                            next_node.extract()
                        tag.insert_after(NavigableString(SPACER))
                    
                    # Если нет пробела, но нужен
                    elif text[0].isalnum() or text[0] in '("':
                        tag.insert_after(NavigableString(SPACER))

    @staticmethod
    def _escape_text_nodes(soup):
        """Экранирует спецсимволы Markdown в текстовых узлах."""
        from bs4 import NavigableString
        
        replacements = {
            '_': '@@@US@@@',
            '*': '@@@AST@@@',
            '[': '@@@LBR@@@',
            ']': '@@@RBR@@@',
        }
        
        for text_node in soup.find_all(string=True):
            if text_node.parent and text_node.parent.name in ['script', 'style', 'title']:
                continue
            
            text = str(text_node)
            if not text:
                continue
                
            new_text = text
            for char, placeholder in replacements.items():
                if char in new_text:
                    new_text = new_text.replace(char, placeholder)
            
            if new_text != text:
                text_node.replace_with(NavigableString(new_text))

    @staticmethod
    def _merge_adjacent_em(soup, em_tags: set, bold_tags: set):
        """Объединяет соседние <em>/<i> теги внутри одного родителя.
        
        Обрабатывает случаи вида:
          <em>вы</em> <b><em>обязаны</em></b> <em>это</em>
        → <em>вы <b>обязаны</b> это</em>
        
        Между <em> могут быть:
        - whitespace (NavigableString из пробелов)
        - <b>/<strong>, целиком обёрнутые в <em> (<b><em>текст</em></b>)
        """
        from bs4 import NavigableString, Tag
        
        def is_em(node):
            """Проверяет, является ли узел тегом em/i."""
            return isinstance(node, Tag) and node.name in em_tags
        
        def is_bold_wrapped_em(node):
            """Проверяет, является ли узел <b><em>текст</em></b>."""
            if not isinstance(node, Tag) or node.name not in bold_tags:
                return False
            children = list(node.children)
            return len(children) == 1 and is_em(children[0])
        
        def is_whitespace(node):
            """Проверяет, является ли узел пробельным текстом."""
            return isinstance(node, NavigableString) and node.strip() == ''
        
        # Обходим все элементы, которые могут содержать em-последовательности
        # Нельзя итерировать напрямую, т.к. дерево мутирует — собираем список родителей
        parents = set()
        for em in soup.find_all(list(em_tags)):
            if em.parent is not None:
                parents.add(id(em.parent))
        
        # Для каждого родителя проверяем его children
        for parent in list(soup.descendants):
            if not isinstance(parent, Tag) or id(parent) not in parents:
                continue
            
            # Собираем runs — последовательности соседних em-элементов
            children = list(parent.children)
            i = 0
            while i < len(children):
                # Ищем начало run: первый <em>
                if not is_em(children[i]):
                    i += 1
                    continue
                
                # Собираем run: <em>, whitespace, <b><em>...</em></b>, <em>, ...
                run_start = i
                run_nodes = [children[i]]
                j = i + 1
                while j < len(children):
                    node = children[j]
                    if is_em(node) or is_bold_wrapped_em(node):
                        run_nodes.append(node)
                        j += 1
                    elif is_whitespace(node):
                        # Пробел между em-элементами — добавляем в run
                        # но только если за ним следует ещё em/bold-em
                        if j + 1 < len(children) and (is_em(children[j + 1]) or is_bold_wrapped_em(children[j + 1])):
                            run_nodes.append(node)
                            j += 1
                        else:
                            break
                    else:
                        break
                
                # Нужно минимум 2 em-элемента (не считая whitespace) для слияния
                em_count = sum(1 for n in run_nodes if is_em(n) or is_bold_wrapped_em(n))
                if em_count < 2:
                    i = j
                    continue
                
                # Объединяем run в один <em>
                # Берём первый <em> как базу, переносим в него содержимое остальных
                first_em = run_nodes[0]
                
                for node in run_nodes[1:]:
                    if is_whitespace(node):
                        # Пробел → переносим внутрь first_em
                        ws = NavigableString(str(node))
                        node.extract()
                        first_em.append(ws)
                    elif is_em(node):
                        # <em>текст</em> → переносим содержимое в first_em
                        for child in list(node.children):
                            child.extract()
                            first_em.append(child)
                        node.extract()
                    elif is_bold_wrapped_em(node):
                        # <b><em>текст</em></b> → <b>текст</b>, переносим в first_em
                        inner_em = list(node.children)[0]
                        inner_em.unwrap()  # убираем <em>, оставляя содержимое в <b>
                        node.extract()
                        first_em.append(node)
                
                # Пересобираем children, т.к. дерево изменилось
                children = list(parent.children)
                # Не инкрементируем i — начинаем с того же места
                # (first_em остался, но children пересобрались)
                i = children.index(first_em) + 1 if first_em in children else j

    @staticmethod
    def _first_navigable_string(tag):
        """Находит первый текстовый узел (NavigableString) внутри тега."""
        from bs4 import NavigableString
        for desc in tag.descendants:
            if isinstance(desc, NavigableString) and desc.strip():
                return desc
        # Если нет непустых, берём первый любой
        for desc in tag.descendants:
            if isinstance(desc, NavigableString):
                return desc
        return None

    @staticmethod
    def _last_navigable_string(tag):
        """Находит последний текстовый узел (NavigableString) внутри тега."""
        from bs4 import NavigableString
        last = None
        for desc in tag.descendants:
            if isinstance(desc, NavigableString):
                last = desc
        # Нам нужен последний с текстом, а если все пустые — последний любой
        last_with_text = None
        for desc in tag.descendants:
            if isinstance(desc, NavigableString) and desc.strip():
                last_with_text = desc
        return last_with_text if last_with_text is not None else last

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

        # Восстанавливаем экранированные символы (из плейсхолдеров DOM)
        markdown = markdown.replace('@@@US@@@', r'\_')
        markdown = markdown.replace('@@@AST@@@', r'\*')
        markdown = markdown.replace('@@@LBR@@@', r'\[')
        markdown = markdown.replace('@@@RBR@@@', r'\]')
        # Заменяем маркеры пробелов, вставленные в DOM
        markdown = markdown.replace('@@@SP@@@', ' ')

        # Удаляем bidi-маркеры, которые ломают пробелы рядом с текстом
        markdown = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', markdown)

        # Нормализуем неразрывные пробелы
        markdown = re.sub(r'[\u00a0\u202f]', ' ', markdown)

        # Склеиваем вложенные em/strong в жирный курсив
        # html2text создаёт ** _текст_** или _**текст**_ для <b><em>
        # Примечание: первый regex сохраняет \s* (html2text для <strong><em> даёт ** _text_**)
        # Второй regex без \s* — иначе он жадно ловит _вы_ ***обязаны*** _это_
        markdown = re.sub(r'\*\*\s*_(.+?)_\s*\*\*', r'***\1***', markdown)
        markdown = re.sub(r'_\*\*(.+?)\*\*_', r'***\1***', markdown)

        # Нормализуем 4+ звёздочек до 3 (страховка от артефактов слияния)
        # ****текст**** → ***текст***, *****текст***** → ***текст***
        markdown = re.sub(r'\*{4,}(.+?)\*{4,}', r'***\1***', markdown)
        
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

        # Убираем пробел перед знаками препинания (.,:;!?)
        # Работает для: обычного текста, ссылок, курсива, жирного
        # [link](url) . -> [link](url).
        # word _._ -> word_._
        # word **.** -> word**.**
        # Используем [ \t]+ вместо \s+, чтобы не удалять переносы строк
        punct = r'[.,:;!?]'
        # 1. Обычная пунктуация
        markdown = re.sub(r'[ \t]+(' + punct + ')', r'\1', markdown)
        # 2. Курсивная пунктуация (_._)
        markdown = re.sub(r'[ \t]+(_' + punct + '_)', r'\1', markdown)
        # 3. Жирная пунктуация (**.**)
        # Используем [*][*] вместо \*\*, чтобы избежать SyntaxWarning
        markdown = re.sub(r'[ \t]+([*][*]' + punct + '[*][*])', r'\1', markdown)
        # 4. Курсив, начинающийся со знака препинания (_, text_)
        # Убираем пробел перед ним: word _, -> word_,
        markdown = re.sub(r'[ \t]+(_' + punct + ')', r'\1', markdown)

        # Исправляем артефакты html2text внутри ссылок: [ _текст_ ] -> [_текст_]
        markdown = re.sub(r'\[\s+_', r'[_', markdown)
        markdown = re.sub(r'_\s+\]', r'_]', markdown)

        # Заголовок берётся из frontmatter (Hugo), не дублируем его в body.
        return markdown
