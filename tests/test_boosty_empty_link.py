import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import Config, Source, Auth
from src.database import Database
from src.boosty import BoostyDownloader
from src.downloader import Post


class BoostyEmptyLinkTests(unittest.TestCase):
    """Тесты обработки пустых ссылок в Boosty."""

    def setUp(self):
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='boosty', author='test_author')
        self.db = MagicMock(spec=Database)

        with patch('src.boosty.load_cookie', return_value='fake_cookie'), \
             patch('src.boosty.load_auth_header', return_value='Bearer fake_token'):
            self.downloader = BoostyDownloader(self.config, self.source, self.db)

    def test_empty_link_is_ignored(self):
        """Ссылка с пустым текстом игнорируется (не превращается в <url>)."""
        blocks = [
            # Пустая ссылка (артефакт)
            {
                "type": "link",
                "url": "https://boosty.to/post/1",
                "content": json.dumps(["", "unstyled", []])
            },
            # Нормальная ссылка
            {
                "type": "link",
                "url": "https://boosty.to/post/2",
                "content": json.dumps(["Вторая часть", "unstyled", []])
            },
            # Конец блока (параграфа)
            {"type": "text", "modificator": "BLOCK_END", "content": ""}
        ]
        
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        # Должна быть только текстовая ссылка
        self.assertIn('[Вторая часть](https://boosty.to/post/2)', result)
        
        # Не должно быть артефакта <url>
        self.assertNotIn('<https://boosty.to/post/1>', result)
        # Не должно быть пустых скобок
        self.assertNotIn('[]', result)

    def test_empty_link_does_not_break_paragraph(self):
        """Пустая ссылка не должна создавать лишние переводы строк."""
        blocks = [
            {"type": "text", "content": json.dumps(["Текст до."])},
            {
                "type": "link",
                "url": "https://boosty.to/post/empty",
                "content": json.dumps(["", "unstyled", []])
            },
            {"type": "text", "content": json.dumps(["Текст после."])},
            {"type": "text", "modificator": "BLOCK_END", "content": ""}
        ]

        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})
        
        # Текст должен быть слитным (без разрывов)
        self.assertEqual(result.strip(), "Текст до.Текст после.")

if __name__ == '__main__':
    unittest.main()
