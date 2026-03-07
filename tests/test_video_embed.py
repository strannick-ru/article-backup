import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import Config, Source, Auth
from src.database import Database
from src.sponsr import SponsorDownloader
from src.boosty import BoostyDownloader
from src.downloader import Post


class SponsorVideoEmbedTests(unittest.TestCase):
    """Тесты встраивания видео для Sponsr."""

    def setUp(self):
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='sponsr', author='test_author')
        self.db = MagicMock(spec=Database)

        with patch('src.sponsr.load_cookie', return_value='fake_cookie'):
            self.downloader = SponsorDownloader(self.config, self.source, self.db)

    def _make_post(self, html: str) -> Post:
        return Post(
            post_id='1', title='Test', content_html=html,
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

    def test_rutube_iframe_becomes_markdown_link(self):
        """Rutube iframe → markdown-ссылка с embed URL."""
        html = '<p>Текст</p><iframe src="https://rutube.ru/play/embed/a1b2c3d4e5f6"></iframe><p>Ещё текст</p>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('[📹 Видео](https://rutube.ru/play/embed/a1b2c3d4e5f6)', result)
        self.assertNotIn('<iframe', result)
        self.assertNotIn('📹 Видео:', result)  # не текстовый формат

    def test_youtube_iframe_becomes_markdown_link(self):
        """YouTube iframe → markdown-ссылка с embed URL."""
        html = '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('[📹 Видео](https://www.youtube.com/embed/dQw4w9WgXcQ)', result)

    def test_vimeo_iframe_becomes_markdown_link(self):
        """Vimeo iframe → markdown-ссылка с embed URL."""
        html = '<iframe src="https://player.vimeo.com/video/123456789"></iframe>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('[📹 Видео](https://player.vimeo.com/video/123456789)', result)

    def test_ok_ru_iframe_becomes_markdown_link(self):
        """OK.ru iframe → markdown-ссылка с embed URL."""
        html = '<iframe src="https://ok.ru/videoembed/987654321"></iframe>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('[📹 Видео](https://ok.ru/videoembed/987654321)', result)

    def test_vk_iframe_becomes_markdown_link(self):
        """VK Video iframe → markdown-ссылка с embed URL."""
        html = '<iframe src="https://vk.com/video_ext.php?oid=-12345&id=67890&hd=2"></iframe>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('[📹 Видео](https://vk.com/video_ext.php?oid=-12345&id=67890&hd=2)', result)

    def test_unknown_video_embed_fallback(self):
        """Нераспознанный iframe с video/embed в src → markdown-ссылка (fallback)."""
        html = '<iframe src="https://unknown-host.com/embed/video123"></iframe>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        # Должна быть markdown-ссылка, а не сырой iframe
        self.assertIn('[📹 Видео](https://unknown-host.com/embed/video123)', result)
        self.assertNotIn('<iframe', result)

    def test_non_video_iframe_ignored(self):
        """iframe без video/embed в src — игнорируется (не заменяется)."""
        html = '<p>Текст</p><iframe src="https://example.com/widget/form"></iframe><p>Ещё</p>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        # Не должно быть видео-ссылки
        self.assertNotIn('📹', result)

    def test_embed_tag_also_converted(self):
        """Тег <embed> тоже обрабатывается."""
        html = '<embed src="https://rutube.ru/play/embed/a1b2c3d4e5f6">'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('[📹 Видео](https://rutube.ru/play/embed/a1b2c3d4e5f6)', result)

    def test_video_link_surrounded_by_text(self):
        """Видео-ссылка корректно окружена текстом."""
        html = '<p>Вот видео:</p><iframe src="https://rutube.ru/play/embed/abc123"></iframe><p>А вот продолжение.</p>'
        result = self.downloader._to_markdown(self._make_post(html), {})

        self.assertIn('Вот видео:', result)
        self.assertIn('[📹 Видео](https://rutube.ru/play/embed/abc123)', result)
        self.assertIn('А вот продолжение.', result)

    def test_is_video_embed_recognizes_all_hosts(self):
        """_is_video_embed распознаёт все хостинги из whitelist."""
        urls = [
            'https://rutube.ru/play/embed/abc123',
            'https://www.youtube.com/embed/xyz789',
            'https://player.vimeo.com/video/111222',
            'https://ok.ru/videoembed/333444',
            'https://vk.com/video_ext.php?oid=-1&id=2',
        ]
        for url in urls:
            self.assertTrue(
                self.downloader._is_video_embed(url),
                f"Должен распознать: {url}"
            )

    def test_is_video_embed_rejects_non_video(self):
        """_is_video_embed отклоняет обычные URL."""
        urls = [
            'https://example.com/page',
            'https://rutube.ru/video/abc123/',  # watch URL, не embed
            'https://google.com',
        ]
        for url in urls:
            self.assertFalse(
                self.downloader._is_video_embed(url),
                f"Не должен распознать: {url}"
            )


class BoostyVideoEmbedTests(unittest.TestCase):
    """Тесты встраивания видео для Boosty."""

    def setUp(self):
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='boosty', author='test_author')
        self.db = MagicMock(spec=Database)

        with patch('src.boosty.load_cookie', return_value='fake_cookie'), \
             patch('src.boosty.load_auth_header', return_value='Bearer fake_token'):
            self.downloader = BoostyDownloader(self.config, self.source, self.db)

    def test_ok_video_uses_player_url_no_preview(self):
        """ok_video без превью → простая текстовая ссылка на playerUrl."""
        blocks = [
            {
                "type": "ok_video",
                "id": "7823634c-f8bc-4f5b-9345-99ac11ed68f5",
                "playerUrls": [
                    {"type": "low", "url": "https://vd.example/low?id=1"},
                    {"type": "high", "url": "https://vd.example/high?id=1"},
                ],
            },
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://vd.example/high?id=1)', result)
        # Не должно быть старого формата
        self.assertNotIn('📹 Видео:', result)

    def test_ok_video_clickable_preview_with_local_video(self):
        """ok_video: превью скачано + видео скачано → кликабельная картинка на локальный файл."""
        preview_url = "https://iv.okcdn.ru/videoPreview?id=1"
        video_url = "https://vd.example/high?id=1"
        blocks = [
            {
                "type": "ok_video",
                "id": "abc",
                "preview": preview_url,
                "playerUrls": [{"type": "high", "url": video_url}],
            }
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        asset_map = {preview_url: "video-preview-abc.jpg", video_url: "video-1.mp4"}
        result = self.downloader._to_markdown(post, asset_map)

        self.assertIn('[![📹 Видео](assets/video-preview-abc.jpg)](assets/video-1.mp4)', result)

    def test_ok_video_clickable_preview_with_fallback_url(self):
        """ok_video: превью скачано, видео нет → кликабельная картинка на ok.ru/video."""
        preview_url = "https://iv.okcdn.ru/videoPreview?id=1"
        blocks = [
            {
                "type": "ok_video",
                "id": "uuid-1",
                "vid": "11386338749172",
                "preview": preview_url,
            }
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        asset_map = {preview_url: "video-preview-uuid-1.jpg"}
        result = self.downloader._to_markdown(post, asset_map)

        self.assertIn('[![📹 Видео](assets/video-preview-uuid-1.jpg)](https://ok.ru/video/11386338749172)', result)

    def test_ok_video_preview_not_downloaded_falls_back_to_text_link(self):
        """ok_video: превью есть в блоке но не скачано → обычная текстовая ссылка."""
        blocks = [
            {
                "type": "ok_video",
                "id": "uuid-1",
                "vid": "11386338749172",
                "preview": "https://iv.okcdn.ru/videoPreview?id=1",
            }
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://ok.ru/video/11386338749172)', result)
        self.assertNotIn('![', result)

    def test_ok_video_falls_back_to_embed_id(self):
        """Legacy fallback: если есть только id, оставляем videoembed/{id}."""
        blocks = [
            {"type": "ok_video", "id": "123456789"},
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://ok.ru/videoembed/123456789)', result)

    def test_ok_video_with_surrounding_text(self):
        """ok_video между текстовыми блоками."""
        preview_url = "https://iv.okcdn.ru/preview?id=2"
        video_url = "https://vd.example/medium?id=2"
        blocks = [
            {"type": "text", "content": json.dumps(["Посмотрите видео:"])},
            {"type": "text", "modificator": "BLOCK_END"},
            {
                "type": "ok_video",
                "id": "999888777",
                "preview": preview_url,
                "playerUrls": [{"type": "medium", "url": video_url}],
            },
            {"type": "text", "content": json.dumps(["Вот такие дела."])},
            {"type": "text", "modificator": "BLOCK_END"},
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        asset_map = {preview_url: "preview.jpg", video_url: "video.mp4"}
        result = self.downloader._to_markdown(post, asset_map)

        self.assertIn('Посмотрите видео:', result)
        self.assertIn('[![📹 Видео](assets/preview.jpg)](assets/video.mp4)', result)
        self.assertIn('Вот такие дела.', result)

    def test_extract_assets_ok_video_with_player_urls_extracts_both(self):
        """_extract_assets для ok_video с playerUrls: и превью, и видео."""
        blocks = [
            {
                "type": "ok_video",
                "id": "video-id",
                "title": "Видео",
                "preview": "https://iv.okcdn.ru/videoPreview?id=1",
                "playerUrls": [
                    {"type": "low", "url": "https://vd.example/low?id=1"},
                    {"type": "high", "url": "https://vd.example/high?id=1"},
                ],
            }
        ]

        assets = self.downloader._extract_assets(blocks)

        self.assertEqual(len(assets), 2)
        # Первый — превью (с force=True)
        self.assertEqual(assets[0]["url"], "https://iv.okcdn.ru/videoPreview?id=1")
        self.assertIn("video-preview-", assets[0]["alt"])
        self.assertTrue(assets[0].get("force"))
        # Второй — видео
        self.assertEqual(assets[1]["url"], "https://vd.example/high?id=1")

    def test_extract_assets_ok_video_without_player_urls_extracts_preview(self):
        """_extract_assets: если playerUrls пусты, берём только preview (с force)."""
        blocks = [
            {
                "type": "ok_video",
                "id": "video-id",
                "preview": "https://iv.okcdn.ru/videoPreview?id=1",
            }
        ]

        assets = self.downloader._extract_assets(blocks)

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["url"], "https://iv.okcdn.ru/videoPreview?id=1")
        self.assertIn("video-preview-", assets[0]["alt"])
        self.assertTrue(assets[0].get("force"))

    def test_extract_assets_ok_video_no_preview_only_video(self):
        """_extract_assets: если нет preview, только видео."""
        blocks = [
            {
                "type": "ok_video",
                "id": "video-id",
                "playerUrls": [
                    {"type": "high", "url": "https://vd.example/high?id=1"},
                ],
            }
        ]

        assets = self.downloader._extract_assets(blocks)

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["url"], "https://vd.example/high?id=1")
        self.assertFalse(assets[0].get("force", False))

    def test_ok_video_player_url_all_empty(self):
        """playerUrls с пустыми url → fallback на vid/id."""
        blocks = [
            {
                "type": "ok_video",
                "id": "uuid-1",
                "vid": "12345",
                "playerUrls": [
                    {"type": "full_hd", "url": ""},
                    {"type": "hls", "url": ""},
                ],
            },
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://ok.ru/video/12345)', result)

    def test_ok_video_player_url_only_stream(self):
        """Если есть только hls-поток, берём его."""
        blocks = [
            {
                "type": "ok_video",
                "id": "uuid-1",
                "playerUrls": [
                    {"type": "full_hd", "url": ""},
                    {"type": "hls", "url": "https://vd.example/video.m3u8?id=1"},
                ],
            },
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://vd.example/video.m3u8?id=1)', result)

    def test_ok_video_quality_priority(self):
        """Проверяем что full_hd выбирается раньше high."""
        blocks = [
            {
                "type": "ok_video",
                "id": "x",
                "playerUrls": [
                    {"type": "low", "url": "https://vd.example/low"},
                    {"type": "high", "url": "https://vd.example/high"},
                    {"type": "full_hd", "url": "https://vd.example/full_hd"},
                ],
            },
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://vd.example/full_hd)', result)

    def test_ok_video_no_player_urls_no_vid_no_id(self):
        """ok_video без playerUrls, vid, id — пустая строка (блок пропускается)."""
        blocks = [
            {"type": "ok_video"},
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertNotIn('📹', result)


class DownloadAssetsForceTests(unittest.TestCase):
    """Тесты force-флага при скачивании assets."""

    def setUp(self):
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        # asset_types без image — обычные картинки фильтруются
        self.source = Source(platform='boosty', author='test_author',
                             asset_types=['video'])
        self.db = MagicMock(spec=Database)

        with patch('src.boosty.load_cookie', return_value='fake_cookie'), \
             patch('src.boosty.load_auth_header', return_value='Bearer fake_token'):
            self.downloader = BoostyDownloader(self.config, self.source, self.db)

    @patch('src.downloader.retry_request')
    def test_force_asset_bypasses_type_filter(self, mock_retry):
        """Asset с force=True скачивается даже если тип не в asset_types."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = Path(tmpdir)

            # Мокаем ответ для картинки-превью
            mock_response = MagicMock()
            mock_response.headers = {'Content-Type': 'image/jpeg'}
            mock_response.iter_content.return_value = [b'fake image data']
            mock_response.close = MagicMock()
            mock_retry.return_value = mock_response

            assets = [
                {"url": "https://iv.okcdn.ru/preview.jpg", "alt": "video-preview-1", "force": True},
            ]

            result = self.downloader._download_assets(assets, assets_dir)

            # Должна быть скачана, несмотря на то что image не в asset_types
            self.assertEqual(len(result), 1)
            self.assertIn("https://iv.okcdn.ru/preview.jpg", result)

    @patch('src.downloader.retry_request')
    def test_non_force_asset_filtered_by_type(self, mock_retry):
        """Обычный asset фильтруется по asset_types."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = Path(tmpdir)

            assets = [
                {"url": "https://example.com/photo.jpg", "alt": "photo"},
            ]

            result = self.downloader._download_assets(assets, assets_dir)

            # Не должна быть скачана — image не в asset_types
            self.assertEqual(len(result), 0)
            mock_retry.assert_not_called()


if __name__ == '__main__':
    unittest.main()
