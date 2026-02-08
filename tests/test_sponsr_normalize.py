import unittest
import re
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

    def _one_line(self, text: str) -> str:
        return " ".join(text.split())

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

    def test_mixed_nested_formatting_bold_inside_italic_preserved(self):
        """Жирный внутри курсива сохраняется, без разрывов внутри слов."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>слово<em>курсив <strong>жирный</strong> курсив</em>слово</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        # Ожидаем единый курсив вокруг фразы и жирный сегмент внутри.
        self.assertRegex(
            one_line,
            r'слово\*курсив \*\*жирный\*\* курсив\*слово',
            msg=f"Expected italic span with bold segment inside (use '*' for intraword italic). Got: {one_line!r}",
        )
        # Не должно вставляться пробелов на границах внутри "слова...слово".
        self.assertNotRegex(one_line, r'слово\s+[_*]', msg=f"Unexpected space before italic. Got: {one_line!r}")
        self.assertNotRegex(one_line, r'[_*]\s+слово', msg=f"Unexpected space after italic. Got: {one_line!r}")

    def test_literal_underscores_not_mangled(self):
        """Литералы с '_' не должны превращаться в '*...*' внутри слова."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>foo_bar_baz</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        self.assertIn('foo_bar_baz', one_line)
        self.assertNotIn('foo*bar*baz', one_line)

    def test_intraword_single_letter_italic_uses_asterisk(self):
        """Одинарный курсив внутри слова должен быть `*...*`, а не `_..._` (Goldmark)."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>п<em>о</em>том</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        self.assertIn('п*о*том', one_line)
        self.assertNotIn('п_о_том', one_line)

    def test_blockquote_italic_trims_spaces_inside_emphasis(self):
        """Курсив в цитате не должен закрываться после пробела ("… _")."""
        post = Post(
            post_id='1',
            title='Test',
            content_html=(
                '<p>свидетелями.</p>'
                '<blockquote><em>'
                'Китайский порох стал прежде всего зажигательным веществом. '
                'Привести кавалерию в панику, зажечь лагерь противника, '
                'опалить бойцов в строю при таранном ударе… '
                '<span>&nbsp;</span></em></blockquote>'
                '<p>Уже</p>'
            ),
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        self.assertIn('> _Китайский порох стал прежде всего зажигательным веществом.', result)
        self.assertIn('ударе…_', one_line)
        self.assertNotIn('ударе… _', one_line)

        # Дополнительно: если пробелы попадут внутрь маркеров, они сломают emphasis.
        self.assertNotIn('> _ ', result)
        self.assertNotIn(' _\n', result)

    def test_trims_spaces_inside_emphasis_both_sides(self):
        """Пробелы/табы внутри маркеров emphasis должны тримиться с двух сторон."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p><em><span>&nbsp;</span>текст<span>&nbsp;</span></em></p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        self.assertIn('_текст_', one_line)
        self.assertNotIn('_ текст_', one_line)
        self.assertNotIn('_текст _', one_line)

    def test_bold_spacing_restored(self):
        """Bold внутри слова не должен разрывать его пробелами."""
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
        
        # Не вставляем пробелы вокруг **жирное**
        self.assertIn('слово**жирное**слово', result)
        self.assertNotIn('слово **жирное** слово', result)

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

    def test_no_space_before_colon_after_bold_italic(self):
        """Двоеточие сразу после закрывающего *** без пробела."""
        post = Post(
            post_id='1',
            title='Test',
            content_html=(
                '<p>поразила <b><em>зараза «божественной миссии», губительная для правителей</em></b>: он всерьёз</p>'
            ),
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        self.assertRegex(
            one_line,
            r'\*\*\*зараза «божественной миссии», губительная для правителей\*\*\*:\s+он',
            msg=f"Expected ':' immediately after closing emphasis. Got: {one_line!r}",
        )
        self.assertNotRegex(
            one_line,
            r'\*\*\*зараза «божественной миссии», губительная для правителей\*\*\*\s+:',
            msg=f"Unexpected whitespace before ':'. Got: {one_line!r}",
        )

    def test_emphasis_does_not_split_word(self):
        """Курсив/жирный курсив внутри слова не должен разрывать его пробелами."""
        post = Post(
            post_id='1',
            title='Test',
            content_html='<p>требующая оплату п<b><em>о</em></b>том.</p>',
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        self.assertRegex(
            one_line,
            r'п\*\*\*о\*\*\*том\.',
            msg=f"Expected emphasized 'o' without splitting the word. Got: {one_line!r}",
        )
        self.assertNotRegex(
            one_line,
            r'п\s+\*\*\*о\*\*\*\s+том',
            msg=f"Word got split by spaces around emphasis. Got: {one_line!r}",
        )

    def test_single_italic_span_across_link(self):
        """Курсив вокруг фразы со ссылкой должен быть единым span без артефактов."""
        post = Post(
            post_id='1',
            title='Test',
            content_html=(
                '<p><em>этого кинополотна, </em>'
                '<a href="https://sponsr.ru/marahovsky/797/Konan_ne_verit_v_vozvrashchenie_SSSR" target="_blank">'
                '<em>Конан</em></a>'
                '<em> из Киммерии.</em></p>'
            ),
            post_date='2025-01-01',
            source_url='https://test.com',
            tags=[],
            assets=[],
        )

        result = self.downloader._to_markdown(post, {})
        one_line = self._one_line(result)

        # Ожидаем единый курсив снаружи, ссылка внутри.
        self.assertRegex(
            one_line,
            re.compile(r'(?P<m>[_*])этого кинополотна, \[Конан\]\([^)]+\) из Киммерии\.(?P=m)'),
            msg=f"Expected one continuous italic span around phrase with link. Got: {one_line!r}",
        )
        # Не должно превращаться в курсив внутри ссылки.
        self.assertNotIn('[_Конан_]', one_line, msg=f"Italic leaked into link text. Got: {one_line!r}")
        self.assertNotRegex(
            one_line,
            r'[_*]\[Конан\]\([^)]+\)[_*]',
            msg=f"Italic wrapped only the link. Got: {one_line!r}",
        )
        # Не должно быть пробелов внутри скобок/квадратных скобок.
        self.assertNotIn('[ Конан]', one_line, msg=f"Unexpected leading space in link text. Got: {one_line!r}")
        self.assertNotIn('[Конан ]', one_line, msg=f"Unexpected trailing space in link text. Got: {one_line!r}")


if __name__ == '__main__':
    unittest.main()
