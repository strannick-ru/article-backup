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
            content_html='<p>подтвердила<b><em> </em></b><a href="https://sponsr.ru/test_author/119132/test_post" target="_blank"><b><em>космическая спутниковая разведка </em></b></a>и другие</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Должна быть ссылка с форматированием внутри: [***текст***](url)
        self.assertIn('[***космическая спутниковая разведка***](https://sponsr.ru/test_author/119132/test_post)', result)
        
        # Не должно быть лишних звездочек снаружи
        self.assertNotIn('******[', result)
        self.assertNotIn(']***', result)
        self.assertNotIn('******космическая', result)
        
        # Пробелы должны быть корректными
        self.assertIn('подтвердила [***', result)
        # После ссылки должен быть пробел перед "и другие"
        self.assertRegex(result, r'\]\(https://sponsr\.ru/test_author/119132/test_post\)\s+и другие')


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

    def test_italic_trailing_space_moved_outside(self):
        """Проблема 2: пробел в конце <em> выносится наружу маркера.
        
        HTML: себя <em>не таким как все </em>(которого не проведёшь)?
        Плохо: себя  _не таким как все _(которого
        Хорошо: себя _не таким как все_ (которого
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>себя <em>не таким как все </em>(которого не проведёшь)?</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Закрывающий маркер должен быть прижат к тексту
        self.assertIn('_не таким как все_', result)
        # Пробел перед закрывающим маркером — невалидный markdown
        self.assertNotIn('все _', result)
        # Пробел между italic и скобкой должен сохраниться
        self.assertIn('все_ (которого', result)

    def test_italic_across_paragraphs(self):
        """Проблема 3: italic через границу абзацев.
        
        HTML: В.М.).</em></p><p><em>Метеоролог ... отвергает. </em></p><p><em>Однако
        Плохо: В.М.)._\\n\\n_Метеоролог ... отвергает. _\\n\\n _Однако
        Хорошо: В.М.)._\\n\\n_Метеоролог ... отвергает._\\n\\n_Однако
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p><em>В.М.).</em></p><p><em>Метеоролог Крис Марц сказал, что климатология полна неопределенности и нюансов, которые «Неудобная правда» полностью отвергает. </em></p><p><em>Однако фильм поднимает важные вопросы.</em></p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Закрывающие маркеры должны быть прижаты к тексту
        self.assertNotIn('отвергает. _', result)
        self.assertIn('отвергает._', result)
        # Открывающие маркеры тоже должны быть прижаты (нет пробела между _ и текстом)
        self.assertNotIn('_ Однако', result)
        self.assertNotIn('_ Метеоролог', result)
        # _Метеоролог — корректный italic
        self.assertIn('_Метеоролог', result)

    def test_italic_bold_italic_in_link(self):
        """Проблема 1: italic + bold-italic внутри ссылки с trailing пробелами.
        
        HTML: «<em>39 лет ... пишу: </em><a href="..."><em>вы </em><b><em>обязаны</em></b><em> это посмотреть</em></a>»
        Плохо: «_39 лет ... пишу: _[ _вы_ ***обязаны*** _это посмотреть_](...)»
        Хорошо: «_39 лет ... пишу:_ [_вы **обязаны** это посмотреть_](...)»
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>сформулировал: «<em>39 лет я никогда не писал этих слов в отзыве на кино, а сейчас пишу: </em><a href="https://example.com/article" target="_blank"><em>вы </em><b><em>обязаны</em></b><em> это посмотреть</em></a>».</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Не должно быть 4+ звёздочек
        self.assertNotIn('****', result)
        # Закрывающий _ не должен иметь пробел перед ним
        self.assertNotIn('пишу: _', result)
        # Соседние <em> внутри ссылки объединены в один курсив
        # Ожидаем: [_вы **обязаны** это посмотреть_](url)
        self.assertIn('[_вы **обязаны** это посмотреть_]', result)
        # Не должно быть фрагментированного курсива
        self.assertNotIn('_вы_', result)
        self.assertNotIn('***обязаны***', result)
        self.assertNotIn('_это посмотреть_]', result)

    def test_nested_identical_tags_merged(self):
        """Тест слияния вложенных одинаковых тегов: <em><em>text</em></em> → <em>text</em>."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>перед <em><em>двойной курсив</em></em> после</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Должен быть одинарный курсив, без артефактов
        self.assertIn('_двойной курсив_', result)
        self.assertNotIn('__', result)

    def test_italic_leading_space_moved_outside(self):
        """Тест выноса leading пробела из italic наружу."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>текст<em> курсив</em> продолжение</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Пробел должен быть снаружи, а не внутри маркера
        self.assertIn('текст _курсив_', result)
        self.assertNotIn('текст_ курсив_', result)

    def test_quadruple_asterisks_normalized(self):
        """Тест нормализации ****text**** → ***text*** в markdown."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>перед <b><em><em>слово</em></em></b> после</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        # Не должно быть 4+ звёздочек
        self.assertNotIn('****', result)
        self.assertIn('слово', result)


    def test_adjacent_em_merged_in_link(self):
        """Соседние <em> внутри <a> объединяются в один.
        
        HTML: <a><em>раз</em> <em>два</em> <em>три</em></a>
        Хорошо: [_раз два три_](url)
        Плохо: [_раз_ _два_ _три_](url)
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p><a href="https://example.com"><em>раз</em> <em>два</em> <em>три</em></a></p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        self.assertIn('[_раз два три_](https://example.com)', result)
        self.assertNotIn('_раз_', result)
        self.assertNotIn('_два_', result)

    def test_adjacent_em_merged_in_paragraph(self):
        """Соседние <em> внутри <p> объединяются в один.
        
        HTML: <p>перед <em>курсив1</em> <em>курсив2</em> после</p>
        Хорошо: перед _курсив1 курсив2_ после
        Плохо: перед _курсив1_ _курсив2_ после
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>перед <em>курсив1</em> <em>курсив2</em> после</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        self.assertIn('_курсив1 курсив2_', result)
        self.assertNotIn('_курсив1_', result)

    def test_adjacent_em_with_bold_merged(self):
        """Соседние <em> с <b><em> между ними объединяются.
        
        HTML: <em>раз</em> <b><em>два</em></b> <em>три</em>
        Хорошо: _раз **два** три_
        Плохо: _раз_ ***два*** _три_
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p><em>раз</em> <b><em>два</em></b> <em>три</em></p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        self.assertIn('_раз **два** три_', result)
        self.assertNotIn('***два***', result)

    def test_single_em_not_affected(self):
        """Одиночный <em> не затрагивается слиянием."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>текст <em>курсив</em> обычный</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        self.assertIn('_курсив_', result)

    def test_non_adjacent_em_not_merged(self):
        """<em> теги, разделённые обычным текстом, не объединяются.
        
        HTML: <em>курсив1</em> обычный <em>курсив2</em>
        Должно остаться: _курсив1_ обычный _курсив2_
        """
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p><em>курсив1</em> обычный <em>курсив2</em></p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[]
        )
        
        result = self.downloader._to_markdown(post, {})
        
        self.assertIn('_курсив1_', result)
        self.assertIn('_курсив2_', result)
        self.assertIn('обычный', result)


if __name__ == '__main__':
    unittest.main()
