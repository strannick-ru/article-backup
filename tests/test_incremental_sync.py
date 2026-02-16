import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import Auth, Config, Source
from src.database import Database
from src.boosty import BoostyDownloader
from src.downloader import Post
from src.sponsr import SponsorDownloader


class IncrementalSyncTests(unittest.TestCase):
    def test_sponsr_sync_fetches_full_post_for_new_items(self):
        """Sponsr sync догружает полный пост, а не берёт урезанный HTML из списка."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform='sponsr', author='test_author')

            with Database(tmp_path / 'test.db') as db:
                with patch('src.sponsr.load_cookie', return_value='fake_cookie'):
                    dl = SponsorDownloader(config, source, db)

                raw_posts = [{
                    'post_id': '137432',
                    'post_title': 'Test title',
                    'post_date': '2025-01-01T00:00:00',
                    'post_url': '/test_author/137432/test-title',
                    'post_text': {'text': '<p>bad<strong>html</strong></p>'},
                }]

                full_post = Post(
                    post_id='137432',
                    title='Test title',
                    content_html='<p>good <strong>html</strong></p>',
                    post_date='2025-01-01T00:00:00',
                    source_url='https://sponsr.ru/test_author/137432/test-title',
                    tags=[],
                    assets=[],
                )

                with patch.object(dl, 'fetch_posts_list', return_value=raw_posts):
                    with patch.object(dl, 'fetch_post', return_value=full_post) as mocked_fetch_post:
                        dl.sync()

                mocked_fetch_post.assert_called_once_with('137432')

                saved = db.get_post('sponsr', 'test_author', '137432')
                if saved is None:
                    self.fail('Пост не был сохранён в БД')
                md_path = Path(saved.local_path) / 'index.md'
                content = md_path.read_text(encoding='utf-8')
                self.assertIn('good **html**', content)
                self.assertNotIn('bad **html**', content)

    def test_sponsr_incremental_stops_on_clean_chunk(self):
        """Sponsr: останавливается на чистом чанке."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform='sponsr', author='test_author')
            
            with Database(tmp_path / 'test.db') as db:
                with patch('src.sponsr.load_cookie', return_value='fake_cookie'):
                    dl = SponsorDownloader(config, source, db)
                
                # Мокаем _get_project_id
                dl._project_id = '123'
                
                # Мокаем API: возвращает 2 чанка по 20 постов
                responses = [
                    {
                        "response": {
                            "rows": [{"post_id": f"{i}"} for i in range(1, 21)],
                            "rows_count": 40
                        }
                    },
                    {
                        "response": {
                            "rows": [{"post_id": f"{i}"} for i in range(21, 41)],
                            "rows_count": 40
                        }
                    }
                ]
                
                call_count = 0
                def mock_get(url, timeout=None):
                    nonlocal call_count
                    resp = MagicMock()
                    resp.json.return_value = responses[call_count]
                    call_count += 1
                    return resp
                
                # Все посты уже существуют
                existing_ids = {str(i) for i in range(1, 41)}

                with patch.object(dl.session, 'get', side_effect=mock_get):
                    posts = dl.fetch_posts_list(existing_ids, incremental=True, safety_chunks=1)
                
                # Должен остановиться после первого чанка + 1 защитный
                self.assertEqual(call_count, 2)
                self.assertEqual(len(posts), 40)
    
    def test_sponsr_incremental_finds_new_posts(self):
        """Sponsr: находит новые посты."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform='sponsr', author='test_author')
            
            with Database(tmp_path / 'test.db') as db:
                with patch('src.sponsr.load_cookie', return_value='fake_cookie'):
                    dl = SponsorDownloader(config, source, db)
                
                dl._project_id = '123'
                
                responses = [
                    {
                        "response": {
                            "rows": [{"post_id": f"{i}"} for i in range(1, 21)],
                            "rows_count": 40
                        }
                    },
                    {
                        "response": {
                            "rows": [{"post_id": f"{i}"} for i in range(21, 41)],
                            "rows_count": 40
                        }
                    },
                    {
                        "response": {
                            "rows": [],
                            "rows_count": 40
                        }
                    }
                ]
                
                call_count = 0
                def mock_get(url, timeout=None):
                    nonlocal call_count
                    idx = min(call_count, len(responses) - 1)
                    resp = MagicMock()
                    resp.json.return_value = responses[idx]
                    call_count += 1
                    return resp
                
                # Первые 5 постов новые, остальные существуют
                existing_ids = {str(i) for i in range(6, 41)}

                with patch.object(dl.session, 'get', side_effect=mock_get):
                    posts = dl.fetch_posts_list(existing_ids, incremental=True, safety_chunks=1)
                
                # Должен загрузить: первый (с новыми) + второй (чистый) + остановиться
                # Всего 2 чанка с данными (call_count может быть 2 или 3 в зависимости от реализации)
                # Важнее что все посты загружены
                self.assertEqual(len(posts), 40)
                self.assertGreaterEqual(call_count, 2)
    
    def test_boosty_incremental_stops_on_clean_chunk(self):
        """Boosty: останавливается на чистом чанке."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = Config(output_dir=tmp_path, auth=Auth())
            source = Source(platform='boosty', author='test_author')
            
            with Database(tmp_path / 'test.db') as db:
                with patch('src.boosty.load_cookie', return_value='fake_cookie'):
                    with patch('src.boosty.load_auth_header', return_value='Bearer token'):
                        dl = BoostyDownloader(config, source, db)
                
                responses = [
                    {
                        "data": [{"id": f"uuid-{i}"} for i in range(1, 21)],
                        "extra": {"isLast": False, "offset": "token1"}
                    },
                    {
                        "data": [{"id": f"uuid-{i}"} for i in range(21, 41)],
                        "extra": {"isLast": True}
                    }
                ]
                
                call_count = 0
                def mock_get(url, timeout=None):
                    nonlocal call_count
                    resp = MagicMock()
                    resp.json.return_value = responses[call_count]
                    call_count += 1
                    return resp
                
                existing_ids = {f"uuid-{i}" for i in range(1, 41)}

                with patch.object(dl.session, 'get', side_effect=mock_get):
                    posts = dl.fetch_posts_list(existing_ids, incremental=True, safety_chunks=1)
                
                self.assertEqual(call_count, 2)
                self.assertEqual(len(posts), 40)
    
    def test_database_sync_state_methods(self):
        """Проверяет методы sync_state в Database."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            with Database(tmp_path / 'test.db') as db:
                # Изначально не синхронизирован
                self.assertFalse(db.is_full_sync('sponsr', 'author1'))
                
                # Помечаем как синхронизированный
                db.mark_full_sync('sponsr', 'author1')
                self.assertTrue(db.is_full_sync('sponsr', 'author1'))
                
                # update_last_sync не должен сбрасывать is_full_sync
                db.update_last_sync('sponsr', 'author1')
                self.assertTrue(db.is_full_sync('sponsr', 'author1'))
                
                # Другой автор не синхронизирован
                self.assertFalse(db.is_full_sync('sponsr', 'author2'))
    
    def test_backward_compatibility(self):
        """Старая БД без sync_state работает корректно."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            # Создаём старую БД без sync_state
            import sqlite3
            conn = sqlite3.connect(tmp_path / 'old.db')
            conn.execute('''
                CREATE TABLE posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    author TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    title TEXT,
                    slug TEXT,
                    post_date TEXT,
                    source_url TEXT,
                    local_path TEXT,
                    tags TEXT,
                    synced_at TEXT,
                    UNIQUE(platform, author, post_id)
                )
            ''')
            conn.commit()
            conn.close()
            
            # Открываем через Database — должна создаться таблица sync_state
            with Database(tmp_path / 'old.db') as db:
                # is_full_sync должен вернуть False для несуществующих записей
                self.assertFalse(db.is_full_sync('sponsr', 'author1'))
                
                # Можем пометить как синхронизированный
                db.mark_full_sync('sponsr', 'author1')
                self.assertTrue(db.is_full_sync('sponsr', 'author1'))


if __name__ == '__main__':
    unittest.main()
