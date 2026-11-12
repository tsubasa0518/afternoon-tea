"""A local imitation of a booking site, used only by tests. Nothing here contacts the internet.

It records every request so tests can prove that reservation pages, forms and refused
addresses were never requested.
"""
import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

TOP = '''<!doctype html><html><head><title>Local booking site</title></head><body>
<a href="/login">ログイン</a> <a href="/member/register">会員登録</a>
<form action="/search" method="get" id="sf">
  <label>キーワード <input type="text" name="q" placeholder="店名・ホテル名"></label>
  <label><input type="checkbox" name="genre" value="at">アフタヌーンティー</label>
  <label><input type="checkbox" name="genre" value="date">デート向け</label>
  <label><input type="checkbox" name="genre" value="french">フレンチ</label>
  <select name="people"><option>2名</option><option>4名</option></select>
  <input type="date" name="date">
  <input type="hidden" name="area" value="tokyo">
  <button type="submit">検索</button>
</form>
<form action="/reserve" method="post" id="rf">
  <input name="name" placeholder="お名前"><input type="email" name="mail"><input type="tel" name="tel">
  <button type="submit">予約を確定する</button>
</form>
</body></html>'''

SHOP = '''<!doctype html><html><head><title>Test Lounge</title></head><body>
<h1>テストラウンジ／テストホテル東京</h1>
<p>所在地：東京都千代田区テスト1-1　最寄駅：有楽町駅</p>
<a href="/shop/1/plan/10">【冬】ストロベリー アフタヌーンティー</a>
<a href="/shop/1/reserve">予約する</a>
<a href="/shop/1/plan/10?date=2026-12-24&people=2">12/24 2名で空きを見る</a>
<a href="https://example.invalid/shop" target="_blank">公式サイト</a>
<button id="more" type="button">もっと見る</button>
<div id="hidden" style="display:none">セイボリー3種とスコーン</div>
<button type="button" onclick="location.href='/shop/1/reserve'">空席確認</button>
<div class="calendar"><button type="button">24</button><button type="button">25</button></div>
<nav class="pagination"><a href="/shop/1?page=2">2</a></nav>
<script>document.getElementById('more').onclick=()=>{document.getElementById('hidden').style.display='block'}</script>
</body></html>'''

PLAN = '''<!doctype html><html><head><title>Plan</title></head><body>
<h1>【冬】ストロベリー アフタヌーンティー</h1>
<p>料金：7,500円（税・サ込）　提供期間：2026年12月1日〜2027年1月31日　平日・土日祝</p>
<p>メニュー：苺のショートケーキ、スコーン、セイボリー</p>
<a href="/shop/1/reserve">このプランで予約する</a>
</body></html>'''


def results(query, page):
    items = ''.join('<li><a href="/shop/%d">%s 検索結果%d</a></li>' % (1 if page == 1 else 2, html.escape(query), page)
                    for _ in range(1))
    return ('<!doctype html><html><head><title>Results</title></head><body><ul>%s</ul>'
            '<nav class="pagination"><a href="/search?q=%s&genre=at&page=2">2</a>'
            '<a href="/search?q=%s&genre=at&page=2">次へ</a></nav></body></html>') % (items, query, query)


class Handler(BaseHTTPRequestHandler):
    log = []

    def _send(self, status, body='', headers=None, kind='text/html; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        Handler.log.append(('POST', self.path))
        self._send(200, '<html><body>POST received</body></html>')

    def do_GET(self):
        Handler.log.append(('GET', self.path))
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        routes = {
            '/robots.txt': lambda: self._send(200, 'User-agent: *\nDisallow: /private/\n', kind='text/plain'),
            '/': lambda: self._send(200, TOP),
            '/search': lambda: self._send(200, results(html.escape(query.get('q', [''])[0]), int(query.get('page', ['1'])[0]))),
            '/shop/1': lambda: self._send(200, SHOP),
            '/shop/2': lambda: self._send(200, SHOP.replace('テストラウンジ', '二件目ラウンジ')),
            '/shop/1/plan/10': lambda: self._send(200, PLAN),
            '/moved': lambda: self._send(302, headers={'Location': '/shop/1'}),
            '/go-reserve': lambda: self._send(302, headers={'Location': '/shop/1/reserve'}),
            '/denied': lambda: self._send(403, 'forbidden'),
            '/captcha': lambda: self._send(200, '<html><body><p>Please verify you are human</p></body></html>'),
            '/private/page': lambda: self._send(200, '<html><body>アフタヌーンティー</body></html>'),
            '/pdf': lambda: self._send(200, '%PDF', kind='application/pdf'),
        }
        routes.get(url.path, lambda: self._send(404, 'not found'))()

    def log_message(self, *args):
        pass


class LocalSite:
    def __enter__(self):
        Handler.log = []
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.host = '127.0.0.1:%d' % self.server.server_address[1]
        self.base = 'http://' + self.host
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    @property
    def log(self):
        return list(Handler.log)

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
