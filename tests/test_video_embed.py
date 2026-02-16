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

    def test_ok_video_uses_player_url(self):
        """ok_video блок → markdown-ссылка на лучший playerUrl."""
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

    def test_ok_video_uses_local_file_if_downloaded(self):
        """ok_video с playerUrl должен ссылаться на локальный asset, если скачан."""
        video_url = "https://vd.example/high?id=1"
        blocks = [
            {
                "type": "ok_video",
                "id": "abc",
                "playerUrls": [{"type": "high", "url": video_url}],
            }
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {video_url: "video-1.mp4"})

        self.assertIn('[📹 Видео](assets/video-1.mp4)', result)

    def test_ok_video_falls_back_to_vid_url(self):
        """При отсутствии playerUrls используем ok.ru/video/{vid}."""
        blocks = [
            {"type": "ok_video", "id": "uuid-1", "vid": "11386338749172"},
        ]
        post = Post(
            post_id='1', title='Test',
            content_html=json.dumps(blocks),
            post_date='2025-01-01', source_url='https://test.com',
            tags=[], assets=[]
        )

        result = self.downloader._to_markdown(post, {})

        self.assertIn('[📹 Видео](https://ok.ru/video/11386338749172)', result)

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
        blocks = [
            {"type": "text", "content": json.dumps(["Посмотрите видео:"])},
            {"type": "text", "modificator": "BLOCK_END"},
            {
                "type": "ok_video",
                "id": "999888777",
                "playerUrls": [{"type": "medium", "url": "https://vd.example/medium?id=2"}],
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

        result = self.downloader._to_markdown(post, {})

        self.assertIn('Посмотрите видео:', result)
        self.assertIn('[📹 Видео](https://vd.example/medium?id=2)', result)
        self.assertIn('Вот такие дела.', result)

    def test_extract_assets_prefers_ok_video_player_url(self):
        """_extract_assets для ok_video должен добавлять видео URL, а не только preview."""
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

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["url"], "https://vd.example/high?id=1")

    def test_extract_assets_ok_video_falls_back_to_preview(self):
        """_extract_assets: если playerUrls пусты, берём preview."""
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


if __name__ == '__main__':
    unittest.main()
