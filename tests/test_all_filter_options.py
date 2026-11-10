"""Filter choices remain available independently of research coverage."""
from html.parser import HTMLParser
import re
import unittest
from afternoon_tea.publication import renderer as r
from tests.test_renderer import fixture, FAILURES
SWEETS = ['いちご', 'メロン', '桃', 'マンゴー', 'ぶどう・マスカット', '栗・マロン', '芋・かぼちゃ', '柿・洋梨・いちじく', '柑橘', 'チョコレート', '抹茶・和', 'マカロン', 'パフェ', 'スコーン', 'その他']
EVENTS = ['クリスマス', 'バレンタイン', 'ホワイトデー', 'コラボ企画', '季節の味覚']

class Buttons(HTMLParser):

    def __init__(self, source):
        super().__init__()
        self.buttons = []
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'button' and 'data-sw' in attrs:
            self.current = {'key': attrs['data-sw'], 'text': '', 'attrs': attrs}

    def handle_data(self, text):
        if self.current is not None:
            self.current['text'] += text

    def handle_endtag(self, tag):
        if tag == 'button' and self.current is not None:
            self.buttons.append(self.current)
            self.current = None

class AllFilterOptionsTests(unittest.TestCase):

    def test_all_fifteen_sweet_options_in_reference_order_for_two_and_zero_stores(self):
        for count in (2, 0):
            data = fixture()
            data['shops'] = [{**data['shops'][0], 'name': 'TEST ' + str(i)} for i in range(count)]
            buttons = Buttons(r.render(data)).buttons
            self.assertEqual(len(buttons), 15)
            self.assertEqual([re.sub('\\d+$', '', b['text']) for b in buttons], SWEETS)
            self.assertTrue(all((b['text'].endswith('0') for b in buttons)))
            self.assertTrue(all(('disabled' not in b['attrs'] for b in buttons)))
            self.assertNotIn('halloween', [b['key'] for b in buttons])

    def test_sweet_counts_are_distinct_plans_and_store_sweets_are_not_inherited(self):
        data = fixture()
        a = data['shops'][0]
        data['shops'] = [{**a,
             'sweets': ['ichigo',
             'xmas'],
             'plans': [{'menu': 'scone scone'},
             {'menu': 'chocolate scone'}]},
             {**a,
             'sweets': ['ichigo'],
             'plans': [{'menu': 'parfait',
             'season': ['xmas']}]}]
        buttons = {b['key']: b['text'] for b in Buttons(r.render(data)).buttons}
        for (key, count) in {'scone': 2, 'choco': 1, 'parfait': 1, 'ichigo': 0, 'melon': 0, 'macaron': 0}.items():
            self.assertTrue(buttons[key].endswith(str(count)), (key, buttons[key]))

    def test_zero_badge_is_styled_without_hiding_the_button(self):
        result = r.render(fixture())
        self.assertIn('class="bc zero">0</span>', result)
        self.assertIn('.fb .bc.zero{color:var(--sub)}', result)
        self.assertIn('word-break:keep-all', result)
