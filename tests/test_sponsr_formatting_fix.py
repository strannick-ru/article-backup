import unittest
import sys
import os

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import Config, Source, Auth
from src.sponsr import SponsorDownloader, Post

class TestSponsrFormattingFix(unittest.TestCase):
    def setUp(self):
        # Мокаем _setup_session, чтобы не требовал куки
        self.original_setup = SponsorDownloader._setup_session
        SponsorDownloader._setup_session = lambda self: None

        self.cfg = Config(output_dir='.', auth=Auth(), sources=[])
        self.src = Source(platform='sponsr', author='test')
        self.downloader = SponsorDownloader(self.cfg, self.src, None)

    def tearDown(self):
        SponsorDownloader._setup_session = self.original_setup

    def test_ensure_spacing_with_html2text(self):
        """Проверка восстановления пробелов перед тегами (через NBSP)."""
        cases = [
            # Case 1: Пробел перед тегом (съедался html2text)
            (
                '<p>Реальность влияния человека на активность ураганов </em><b><em>гораздо более сложна и неопределённа</em></b><em>, чем обсуждается</p>',
                'Реальность влияния человека на активность ураганов ***гораздо более сложна и неопределённа***_, чем обсуждается_'
            ),
            # Case 2: Пробел после точки перед тегом
            (
                '<p>И это застало учёных врасплох. </em><b><em>Модели этого не предсказывали</em></b><em>», — сказал Марц.</em></p>',
                'И это застало учёных врасплох. ***Модели этого не предсказывали*** _», — сказал Марц._'
            ),
            # Case 3: Пробел после слова перед тегом
            (
                '<p>в результате </em><b><em>естественной изменчивости</em></b><em>.</em></p>',
                'в результате ***естественной изменчивости***_._'
            )
        ]

        for html, expected in cases:
            post = Post(
                post_id='1', title='Title', post_date='', source_url='', tags=[],
                content_html=html, assets=[]
            )
            md = self.downloader._to_markdown(post, {})
            # Ожидаем точное совпадение фрагмента
            self.assertIn(expected, md)

if __name__ == "__main__":
    unittest.main()
