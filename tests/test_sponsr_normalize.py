import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import Config, Source, Auth
from src.database import Database
from src.sponsr import SponsorDownloader
from src.downloader import Post


class SponsorNormalizeTests(unittest.TestCase):
    def setUp(self):
        """Создаём тестовый экземпляр SponsorDownloader."""
        self.config = Config(output_dir=Path('/tmp/test'), auth=Auth())
        self.source = Source(platform='sponsr', author='test_author')
        
        # Мокаем Database и session
        self.db = MagicMock(spec=Database)
        
        with patch('src.sponsr.load_cookie', return_value='fake_cookie'):
            self.downloader = SponsorDownloader(self.config, self.source, self.db)

    def test_empty_bold_italic_removed(self):
        """Тест удаления пустого форматирования."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>text<b><em> </em></b>more</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Не должно быть пустых звездочек
        self.assertNotIn('***   ***', result)
        self.assertNotIn('**  **', result)
        self.assertNotIn('****', result)
        # Текст должен быть склеенным или с одним пробелом
        self.assertTrue('text' in result and 'more' in result)

    def test_bold_italic_link_normalization(self):
        """Тест перемещения форматирования внутрь ссылки."""
        # HTML как в примере: <b><em>космическая спутниковая разведка</em></b> внутри <a>
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>подтвердила<b><em> </em></b><a href="https://test.com/link"><b><em>космическая спутниковая разведка </em></b></a>и другие</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Ожидаем: [***текст***](url), а не ***[***текст***](url)***
        self.assertIn('[***космическая спутниковая разведка***](https://test.com/link)', result)
        
        # Не должно быть звездочек снаружи ссылки
        self.assertNotIn('***[***', result)
        self.assertNotIn(']***', result)
        self.assertNotIn('******[', result)

    def test_unicode_quotes_spacing(self):
        """Тест удаления лишних пробелов вокруг кавычек."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>Он сказал: «<em>привет</em>»</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # html2text использует _ для курсива
        # Ожидаем: «_текст_», а не « _текст_ »
        self.assertIn('«_привет_»', result)
        self.assertNotIn('« _привет_ »', result)

    def test_nested_bold_italic_collapsed(self):
        """Тест схлопывания вложенных em/strong."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p><strong><em>жирный курсив</em></strong></p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Ожидаем: ***текст***, а не **_текст_**
        self.assertIn('***жирный курсив***', result)
        self.assertNotIn('**_жирный курсив_**', result)
        self.assertNotIn('_**жирный курсив**_', result)

    def test_bold_spacing_restored(self):
        """Тест восстановления пробелов вокруг bold."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>слово<strong>жирное</strong>слово</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Ожидаем пробелы вокруг **жирное**
        self.assertIn('слово **жирное** слово', result)
        self.assertNotIn('слово**жирное**слово', result)

    def test_real_world_case_from_issue(self):
        """Тест реального случая из issue."""
        # Точный HTML из примера пользователя
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>подтвердила<b><em> </em></b><a href="https://sponsr.ru/dicelords/119132/Kosmiiicheskoe_zoloto" target="_blank"><b><em>космическая спутниковая разведка </em></b></a>и другие</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Должна быть ссылка с форматированием внутри: [***текст***](url)
        self.assertIn('[***космическая спутниковая разведка***](https://sponsr.ru/dicelords/119132/Kosmiiicheskoe_zoloto)', result)
        
        # Не должно быть лишних звездочек снаружи
        self.assertNotIn('******[', result)
        self.assertNotIn(']***', result)
        self.assertNotIn('******космическая', result)
        
        # Пробелы должны быть корректными
        self.assertIn('подтвердила [***', result)
        # После ссылки должен быть пробел перед "и другие"
        self.assertRegex(result, r'\]\(https://sponsr\.ru/dicelords/119132/Kosmiiicheskoe_zoloto\)\s+и другие')


    def test_whitespace_preserved_after_link(self):
        """Тест сохранения пробела из <em> </em> после ссылки."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>что в <a href="https://www.google.com/search?q=test" target="_blank"><em>актах</em></a><em> </em>(то есть</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Пробел между ссылкой и скобкой не должен теряться
        self.assertNotIn('](https://www.google.com/search?q=test)(то', result)
        self.assertIn(') (то есть', result)


if __name__ == '__main__':
    unittest.main()
