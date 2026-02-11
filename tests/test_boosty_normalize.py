import unittest
import json
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import Config, Source, Auth
from src.database import Database
from src.boosty import BoostyDownloader
from src.downloader import Post


class BoostyApplyStylesTests(unittest.TestCase):
    def setUp(self):
        """Создаём тестовый экземпляр BoostyDownloader."""
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='boosty', author='test_author')

        self.db = MagicMock(spec=Database)

        with patch('src.boosty.load_cookie', return_value='fake_cookie'), \
             patch('src.boosty.load_auth_header', return_value='Bearer fake'):
            self.downloader = BoostyDownloader(self.config, self.source, self.db)

    def test_italic_trailing_space(self):
        """Пробел в конце курсивного фрагмента выносится наружу маркера."""
        result = self.downloader._apply_styles('текст ', [[2, 0, 6]])
        self.assertEqual(result, '*текст* ')
        self.assertNotIn('* ', result.rstrip())

    def test_italic_leading_space(self):
        """Пробел в начале курсивного фрагмента выносится наружу маркера."""
        result = self.downloader._apply_styles(' текст', [[2, 0, 6]])
        self.assertEqual(result, ' *текст*')

    def test_italic_both_spaces(self):
        """Пробелы с обеих сторон выносятся наружу маркеров."""
        result = self.downloader._apply_styles(' текст ', [[2, 0, 7]])
        self.assertEqual(result, ' *текст* ')

    def test_italic_no_spaces(self):
        """Текст без пробелов оборачивается как обычно."""
        result = self.downloader._apply_styles('текст', [[2, 0, 5]])
        self.assertEqual(result, '*текст*')

    def test_bold_trailing_space(self):
        """Пробел в конце жирного фрагмента выносится наружу маркера."""
        result = self.downloader._apply_styles('текст ', [[1, 0, 6]])
        self.assertEqual(result, '**текст** ')

    def test_bold_leading_space(self):
        """Пробел в начале жирного фрагмента выносится наружу маркера."""
        result = self.downloader._apply_styles(' текст', [[1, 0, 6]])
        self.assertEqual(result, ' **текст**')

    def test_whitespace_only_not_wrapped(self):
        """Фрагмент из одних пробелов не оборачивается в маркеры."""
        result = self.downloader._apply_styles('   ', [[2, 0, 3]])
        self.assertEqual(result, '   ')
        self.assertNotIn('*', result)

    def test_nbsp_trailing(self):
        """Non-breaking space в конце выносится наружу маркера."""
        result = self.downloader._apply_styles('текст\u00a0', [[2, 0, 6]])
        self.assertEqual(result, '*текст*\u00a0')

    def test_partial_italic_with_trailing_space(self):
        """Курсив на часть текста с пробелом в конце фрагмента."""
        # "слово курсив ещё" — italic на "курсив " (с пробелом)
        text = 'слово курсив ещё'
        result = self.downloader._apply_styles(text, [[2, 6, 7]])
        self.assertIn('*курсив*', result)
        self.assertNotIn('*курсив *', result)


class BoostyParagraphTests(unittest.TestCase):
    def setUp(self):
        """Создаём тестовый экземпляр BoostyDownloader."""
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='boosty', author='test_author')
        self.db = MagicMock(spec=Database)
        with patch('src.boosty.load_cookie', return_value='fake'), \
             patch('src.boosty.load_auth_header', return_value='Bearer fake'):
            self.downloader = BoostyDownloader(self.config, self.source, self.db)

    def test_inline_blocks_concatenation(self):
        """Проверяем, что inline-блоки объединяются в одну строку."""
        blocks = [
            {'type': 'text', 'content': json.dumps(['Начало ', 'unstyled', []])},
            {'type': 'link', 'url': 'https://ya.ru', 'content': json.dumps(['ссылка', 'unstyled', []])},
            {'type': 'text', 'content': json.dumps([' конец.', 'unstyled', []])},
            {'type': 'text', 'modificator': 'BLOCK_END', 'content': ''}
        ]
        post = Post(post_id='1', title='T', content_html=json.dumps(blocks), 
                    post_date='2025-01-01', source_url='u', tags=[], assets=[])
        
        md = self.downloader._to_markdown(post, {})
        self.assertEqual(md.strip(), 'Начало [ссылка](https://ya.ru) конец.')
        self.assertNotIn('\n', md.strip())

    def test_paragraph_separation(self):
        """BLOCK_END создает пустую строку между параграфами."""
        blocks = [
            {'type': 'text', 'content': json.dumps(['Параграф 1', 'unstyled', []])},
            {'type': 'text', 'modificator': 'BLOCK_END', 'content': ''},
            {'type': 'text', 'content': json.dumps(['Параграф 2', 'unstyled', []])},
            {'type': 'text', 'modificator': 'BLOCK_END', 'content': ''}
        ]
        post = Post(post_id='1', title='T', content_html=json.dumps(blocks), 
                    post_date='2025-01-01', source_url='u', tags=[], assets=[])
        
        md = self.downloader._to_markdown(post, {})
        self.assertEqual(md.strip(), 'Параграф 1\n\nПараграф 2')

    def test_global_style_offset(self):
        """Проверяем, что стили с глобальным смещением применяются корректно."""
        # Текст (len=7) + Ссылка (len=6). Ссылка начинается с offset=7.
        # Стиль italic [2, 7, 6] должен примениться к ссылке.
        blocks = [
            {'type': 'text', 'content': json.dumps(['Текст: ', 'unstyled', []])},
            {'type': 'link', 'url': 'u', 'content': json.dumps(['ссылка', 'unstyled', [[2, 7, 6]]])},
            {'type': 'text', 'modificator': 'BLOCK_END', 'content': ''}
        ]
        post = Post(post_id='1', title='T', content_html=json.dumps(blocks), 
                    post_date='2025-01-01', source_url='u', tags=[], assets=[])
        
        md = self.downloader._to_markdown(post, {})
        self.assertEqual(md.strip(), 'Текст: [*ссылка*](u)')

    def test_block_level_elements_break_paragraph(self):
        """Block-level элементы (картинки) разрывают параграф."""
        blocks = [
            {'type': 'text', 'content': json.dumps(['Текст до', 'unstyled', []])},
            {'type': 'image', 'url': 'img.jpg', 'id': 'img1'},
            {'type': 'text', 'content': json.dumps(['Текст после', 'unstyled', []])},
            {'type': 'text', 'modificator': 'BLOCK_END', 'content': ''}
        ]
        post = Post(post_id='1', title='T', content_html=json.dumps(blocks), 
                    post_date='2025-01-01', source_url='u', tags=[], assets=[])
        
        md = self.downloader._to_markdown(post, {})
        # Ожидаем: Текст до \n Картинка \n Текст после
        self.assertIn('Текст до\n\n![]', md)
        self.assertIn(')\n\nТекст после', md)


if __name__ == '__main__':
    unittest.main()
