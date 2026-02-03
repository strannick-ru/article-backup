import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import Config, Source, Auth
from src.database import Database
from src.sponsr import SponsorDownloader


class SponsorTagsTests(unittest.TestCase):
    def setUp(self):
        """Создаём тестовый экземпляр SponsorDownloader."""
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='sponsr', author='test_author')
        
        # Мокаем Database и session
        self.db = MagicMock(spec=Database)
        
        with patch('src.sponsr.load_cookie', return_value='fake_cookie'):
            self.downloader = SponsorDownloader(self.config, self.source, self.db)

    def test_parse_tags_as_objects(self):
        """Тест парсинга тегов как объектов (новый формат API)."""
        raw_data = {
            'post_id': '123',
            'post_title': 'Test Post',
            'post_date': '2025-01-01T00:00:00',
            'post_url': '/author/123/',
            'post_text': {'text': '<p>Content</p>'},
            'tags': [
                {
                    'count': 14,
                    'post_id': 135435,
                    'tag': {
                        'id': 71523,
                        'image': None,
                        'project_id': 7533,
                        'tag_name': 'Космос',
                        'ts': '2025-10-15T18:35:12.000Z'
                    },
                    'tag_id': 71523,
                    'ts': '2026-01-29T23:55:24.000Z'
                },
                {
                    'count': 5,
                    'tag': {
                        'tag_name': 'Наука'
                    }
                }
            ]
        }
        
        post = self.downloader._parse_post(raw_data)
        
        # Должны извлечься только имена тегов
        self.assertEqual(post.tags, ['Космос', 'Наука'])

    def test_parse_tags_as_strings(self):
        """Тест парсинга тегов как строк (старый формат)."""
        raw_data = {
            'post_id': '123',
            'post_title': 'Test Post',
            'post_date': '2025-01-01T00:00:00',
            'post_url': '/author/123/',
            'post_text': '<p>Content</p>',
            'tags': ['tag1', 'tag2', 'tag3']
        }
        
        post = self.downloader._parse_post(raw_data)
        
        self.assertEqual(post.tags, ['tag1', 'tag2', 'tag3'])

    def test_parse_tags_mixed_format(self):
        """Тест парсинга тегов в смешанном формате."""
        raw_data = {
            'post_id': '123',
            'post_title': 'Test Post',
            'post_date': '2025-01-01T00:00:00',
            'post_text': '<p>Content</p>',
            'tags': [
                'simple_tag',
                {
                    'tag': {
                        'tag_name': 'Объектный тег'
                    }
                }
            ]
        }
        
        post = self.downloader._parse_post(raw_data)
        
        self.assertEqual(post.tags, ['simple_tag', 'Объектный тег'])

    def test_parse_tags_with_tag_name_direct(self):
        """Тест парсинга тегов с tag_name напрямую в объекте."""
        raw_data = {
            'post_id': '123',
            'post_title': 'Test Post',
            'post_date': '2025-01-01T00:00:00',
            'post_text': '<p>Content</p>',
            'tags': [
                {
                    'tag_name': 'Прямой тег',
                    'id': 123
                }
            ]
        }
        
        post = self.downloader._parse_post(raw_data)
        
        self.assertEqual(post.tags, ['Прямой тег'])

    def test_parse_empty_tags(self):
        """Тест парсинга пустых тегов."""
        raw_data = {
            'post_id': '123',
            'post_title': 'Test Post',
            'post_date': '2025-01-01T00:00:00',
            'post_text': '<p>Content</p>',
            'tags': []
        }
        
        post = self.downloader._parse_post(raw_data)
        
        self.assertEqual(post.tags, [])

    def test_parse_no_tags_field(self):
        """Тест парсинга без поля tags."""
        raw_data = {
            'post_id': '123',
            'post_title': 'Test Post',
            'post_date': '2025-01-01T00:00:00',
            'post_text': '<p>Content</p>'
        }
        
        post = self.downloader._parse_post(raw_data)
        
        self.assertEqual(post.tags, [])


if __name__ == '__main__':
    unittest.main()
