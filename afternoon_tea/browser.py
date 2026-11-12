"""Research browser: reads public pages, never reserves.

Allowed: open public pages (also from search results), follow normal links and checked
redirects, site search forms (keyword + the afternoon-tea option only), result paging,
tabs, scrolling and expanding menus or plan details on the page.

Refused before anything is sent: reservation, availability, date/time/party-size selection,
waiting lists, inquiries, login/registration, orders and payment, form fields other than a
search keyword, any non-GET page request, and any URL that `fetch.Policy` refuses. Every page
document is fetched by `fetch.Reader` (robots.txt, pacing, 403/429/CAPTCHA stop, redirect
hops checked), then handed to the browser for scripts to draw it.

One anonymous browser context is kept for the whole run (tabs and cookies of public pages only;
no login, no personal data). Nothing is stored outside `.staging/run`.
"""
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl, urljoin

from afternoon_tea.fetch import (AT_WORDS, RUN, USER_AGENT, AccessRefused, BudgetExhausted, ForbiddenOperation,
                                 Policy, Reader, RunState, SLOT_PARAMS, Unusable, challenged, excerpt, now_iso)

# Clear transaction verbs: never clicked, even when the link target looks harmless.
STRONG_DENY = re.compile(
    r'予約す|予約へ|予約に進|予約を|今すぐ予約|ネット予約|web予約|予約手続|仮予約|空席|空き状況|空き確認|キャンセル待ち|'
    r'申し?込|購入|カート|決済|支払|注文|ログイン|ログアウト|会員登録|新規登録|サインイン|問い?合わ?せ|お気に入り|'
    r'送信|確定|変更する|取り?消|クーポン(?:を)?(?:取得|獲得|使)|'
    r'book now|book a table|reserve|reservation|check availability|availability|waitlist|wait list|buy|purchase|'
    r'add to cart|checkout|pay|order now|sign ?in|log ?in|sign ?up|register|subscribe|submit|confirm|contact us|inquir',
    re.I)
# Words that make a script button (not a link) unsafe or a reservation-slot control.
BUTTON_DENY = re.compile(
    r'予約|会員|登録|日付|日時|時間帯|人数|名様|大人|子供|お子様|カレンダー|来店日|利用日|席|保存|シェア|'
    r'book|guest|people|party|calendar|date|time|seat|share|save|favorite', re.I)
SLOT_LABEL = re.compile(r'\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}/\d{1,2}|\d{1,2}:\d{2}|\d+\s*(?:名|人|様|guests?|people)', re.I)
EXPAND_LABEL = re.compile(
    r'もっと見る|もっと表示|さらに表示|さらに見る|すべて表示|すべて見る|全て表示|全て見る|続きを読む|続きを見る|詳細|詳しく|'
    r'プラン|メニュー|コース|一覧|開く|展開|閉じる|^[×✕✖+＋－-]$|アフタヌーンティー|ティー|料金|内容|'
    r'show more|see more|view more|read more|show all|view all|more|details?|plans?|menus?|courses?|close|expand|'
    r'afternoon tea', re.I)
PAGING_LABEL = re.compile(r'^(?:\d{1,3}|次へ|次の\d*件?|前へ|前の\d*件?|次のページ|前のページ|next|prev(?:ious)?|›|»|‹|«|>|<)$', re.I)
SEARCH_BUTTON = re.compile(r'検索|探す|絞り込|search|find|go', re.I)
KEYWORD_FIELD = re.compile(r'^(?:q|query|kw|keyword|keywords|sk|word|words|freeword|free_word|search|s|k|text|term)$', re.I)
KEYWORD_LABEL = re.compile(r'検索|キーワード|フリーワード|店名|施設名|ホテル名|search|keyword', re.I)
SENSITIVE_FIELD = re.compile(
    r'mail|tel|phone|password|passwd|card|cvc|cvv|expir|zip|postal|address|birth|kana|first_?name|last_?name|'
    r'full_?name|^name$|氏名|名前|お名前|電話|住所|郵便|生年月日|パスワード|カード|メール', re.I)
QUIET_TYPES = {'image', 'media', 'font', 'websocket', 'eventsource', 'manifest', 'texttrack', 'ping', 'other'}
SOCKET = RUN / 'browser.sock'
KEYFILE = RUN / 'browser.key'
LOGFILE = RUN / 'browser.log'

COLLECT_JS = r'''() => {
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const labelOf = el => {
    let t = (el.innerText || el.value || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '');
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t += ' ' + l.innerText; }
    const wrap = el.closest('label'); if (wrap) t += ' ' + wrap.innerText;
    if (el.placeholder) t += ' ' + el.placeholder;
    return t.replace(/\s+/g, ' ').trim().slice(0, 120); };
  const forms = Array.from(document.forms);
  const ctx = el => {
    const c = el.closest('[class*=calendar i],[class*=datepicker i],[class*=date-picker i],[role=grid],[class*=timeslot i],[class*=time-slot i],[class*=people i],[class*=guest i]');
    const p = el.closest('nav,[class*=pagination i],[class*=pager i],[class*=paging i],[aria-label*=page i],[role=navigation]');
    return {in_calendar: !!c, in_paging: !!p}; };
  const out = [];
  let n = 0;
  document.querySelectorAll('a[href],button,[role=button],[role=tab],[role=link],summary,input,select,textarea').forEach(el => {
    if (el.type !== 'hidden' && !visible(el) && el.type !== 'checkbox' && el.type !== 'radio') return;
    const id = String(++n); el.setAttribute('data-at-id', id);
    const f = el.form || el.closest('form');
    out.push(Object.assign({id, tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
      role: (el.getAttribute('role') || '').toLowerCase(), label: labelOf(el), name: el.getAttribute('name') || '',
      href: el.tagName === 'A' ? el.href : null, raw_href: el.getAttribute('href'),
      target: (el.getAttribute('target') || '').toLowerCase(), form: f ? forms.indexOf(f) : -1,
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true', checked: !!el.checked,
      value: el.tagName === 'SELECT' ? '' : (el.value || '').slice(0, 80),
      options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text.trim().slice(0, 60)) : null}, ctx(el)));
  });
  const fdesc = forms.map((f, i) => ({index: i, action: f.getAttribute('action') === null ? '' : f.action,
    raw_action: f.getAttribute('action'), method: (f.getAttribute('method') || 'get').toLowerCase()}));
  return {controls: out, forms: fdesc};
}'''


class BrowserUnavailable(RuntimeError):
    pass


def _label(item):
    return ' '.join(str(item.get('label') or '').split())


def keyword_field(item):
    if item.get('tag') not in ('input', 'textarea') or item.get('type') not in ('', 'text', 'search'):
        return False
    return item.get('type') == 'search' or bool(KEYWORD_FIELD.match(item.get('name') or '')) or bool(
        KEYWORD_LABEL.search(_label(item)))


def sensitive_field(item):
    if item.get('type') in ('password', 'email', 'tel', 'file'):
        return True
    if item.get('tag') not in ('input', 'textarea', 'select'):
        return False
    return bool(SENSITIVE_FIELD.search(item.get('name') or '') or SENSITIVE_FIELD.search(_label(item)))


def search_forms(controls, forms, policy):
    """A search form: GET, harmless action, a keyword field and no personal-data field."""
    result = {}
    for form in forms:
        fields = [c for c in controls if c.get('form') == form['index']]
        if form['method'] != 'get' or not any(keyword_field(c) for c in fields):
            continue
        if any(sensitive_field(c) for c in fields):
            continue
        action = form['action'] or ''
        if action:
            try:
                policy.check(urlunsplit(urlsplit(action)._replace(query='', fragment='')))
            except ForbiddenOperation:
                continue
        result[form['index']] = form
    return result


def classify(item, searchable, policy):
    """Return (kind, reason). kind: navigate, click, fill, check, select, submit or deny."""
    label = _label(item)
    tag, kind = item.get('tag'), item.get('type')
    in_search = item.get('form', -1) in searchable
    if item.get('disabled'):
        return 'deny', 'disabled'
    if item.get('in_calendar'):
        return 'deny', 'reservation_slot_control'
    if tag in ('input', 'textarea', 'select'):
        if sensitive_field(item):
            return 'deny', 'personal_data_field'
        if keyword_field(item) and (in_search or (item.get('form', -1) < 0 and kind == 'search')):
            return 'fill', 'search_keyword'
        if SLOT_PARAMS.match(item.get('name') or '') or kind in ('date', 'time', 'datetime-local', 'number'):
            return 'deny', 'reservation_slot_control'
        if kind in ('checkbox', 'radio') or tag == 'select':
            if item.get('form', -1) >= 0 and not in_search:
                return 'deny', 'not_a_search_form'
            if tag == 'select':
                return 'select', 'afternoon_tea_option_only'
            if AT_WORDS.search(label):
                return 'check', 'afternoon_tea_option'
            return 'deny', 'only_the_afternoon_tea_option_may_be_selected'
        if kind in ('submit', 'image') and in_search:
            return 'submit', 'search'
        return 'deny', 'form_field'
    if STRONG_DENY.search(label):
        return 'deny', 'reservation_or_transaction'
    href = item.get('href')
    raw = item.get('raw_href') or ''
    if tag == 'a' and href and not raw.startswith(('#', 'javascript:')) and href.startswith(('http://', 'https://')):
        try:
            policy.check(href.split('#')[0])
        except ForbiddenOperation as error:
            return 'deny', str(error)
        return 'navigate', 'link'
    if SLOT_LABEL.search(label) and not (item.get('in_paging') and PAGING_LABEL.match(label)):
        return 'deny', 'reservation_slot_control'
    if item.get('form', -1) >= 0:
        if in_search and (kind == 'submit' or SEARCH_BUTTON.search(label)) and not BUTTON_DENY.search(label):
            return 'submit', 'search'
        return 'deny', 'form_control'
    if BUTTON_DENY.search(label):
        return 'deny', 'reservation_or_account_control'
    if item.get('in_paging') and PAGING_LABEL.match(label):
        return 'click', 'paging'
    if tag == 'summary' or item.get('role') == 'tab' or (label and len(label) <= 40 and EXPAND_LABEL.search(label)):
        return 'click', 'expand'
    return 'deny', 'unknown_role'


def search_url(form, controls, values=None):
    """Only the keyword and checked afternoon-tea options are sent; other filters are not added."""
    action = form['action'] or ''
    parts = urlsplit(action)
    params = []
    for c in controls:
        if c.get('form') != form['index'] or not c.get('name'):
            continue
        if keyword_field(c):
            value = (values or {}).get(c['id'], c.get('value') or '')
            if value:
                params.append((c['name'], value))
        elif c.get('type') in ('checkbox', 'radio') and c.get('checked') and AT_WORDS.search(_label(c)):
            params.append((c['name'], c.get('value') or 'on'))
        elif c.get('type') == 'hidden' and not SLOT_PARAMS.match(c['name']) and not re.search(
                r'token|csrf|auth|session|utf8', c['name'], re.I):
            params.append((c['name'], c.get('value') or ''))
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not SLOT_PARAMS.match(k)]
    return urlunsplit(parts._replace(query=urlencode(keep + params), fragment=''))


def _launch(playwright):
    options = {'headless': True}
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        options['args'] = ['--no-sandbox']
    path = os.environ.get('AFTERNOON_TEA_CHROMIUM')
    try:
        return playwright.chromium.launch(executable_path=path, **options) if path else playwright.chromium.launch(**options)
    except Exception as error:
        fallback = '/opt/pw-browsers/chromium'
        if path or not os.path.exists(fallback):
            raise BrowserUnavailable('browser_launch_failed:' + type(error).__name__) from error
        try:
            return playwright.chromium.launch(executable_path=fallback, **options)
        except Exception as again:
            raise BrowserUnavailable('browser_launch_failed:' + type(again).__name__) from again


class Session:
    """One research browser. All page documents pass through Reader; reservation steps never do."""

    def __init__(self, run=None, policy=None, playwright=None):
        self.run = run or RunState()
        self.policy = policy or Policy()
        self.reader = Reader(self.run, self.policy)
        self.manager = None
        if playwright is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as error:
                raise BrowserUnavailable('playwright_not_installed') from error
            try:
                playwright = sync_playwright().start()
                self.manager = playwright  # stopped in close()
            except Exception as error:
                raise BrowserUnavailable('playwright_start_failed') from error
        self.browser = _launch(playwright)
        self.context = self.browser.new_context(accept_downloads=False, service_workers='block', user_agent=USER_AGENT,
                                                locale='ja-JP', viewport={'width': 1280, 'height': 900})
        self.context.route('**/*', self._route)
        self.context.on('page', self._new_page)
        self.pages = []
        self.current = None
        self.pending = None
        self.error = None
        self.controls = {}
        self.forms = {}
        self.searchable = {}
        self.prefetched = {}
        self.stats = {'blocked_operations': 0, 'blocked_resources': 0}
        self._new_page(self.context.new_page())

    # -- request guard -------------------------------------------------------------
    def _count(self, key):
        self.stats[key] += 1

    def _flush(self):
        if any(self.stats.values()):
            with self.run.update() as state:
                for key, value in self.stats.items():
                    state[key] += value
            self.stats = {key: 0 for key in self.stats}

    def _route(self, route, request):
        try:
            if request.resource_type == 'document' and request.is_navigation_request():
                if request.frame.parent_frame is not None:
                    self._count('blocked_resources')
                    return route.abort()
                if request.method != 'GET':
                    self.error = ForbiddenOperation('non_GET_page_request_is_a_form_submission')
                    self._count('blocked_operations')
                    return route.abort()
                try:
                    page = self.prefetched.pop(request.url, None) or self.reader.get(request.url, via='browser', follow=False)
                except (ForbiddenOperation, AccessRefused, Unusable, BudgetExhausted, ValueError) as error:
                    self.error = error
                    return route.abort()
                if page.status in (301, 302, 303, 307, 308):
                    self.pending = page.final_url  # already checked; opened as a new checked request
                    return route.abort()
                headers = {k: v for k, v in page.headers.items()
                           if k.lower() in ('content-type', 'content-language', 'cache-control')}
                return route.fulfill(status=page.status, headers=headers, body=page.body)
            if request.method not in ('GET', 'HEAD') or request.resource_type in QUIET_TYPES:
                self._count('blocked_resources')
                return route.abort()
            try:
                # Static code and styles are not actions; data requests get the full URL check.
                self.policy.check(request.url, robots_path=request.resource_type in ('script', 'stylesheet'))
            except ForbiddenOperation:
                self._count('blocked_resources')
                return route.abort()
            return route.continue_()
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    def _new_page(self, page):
        if page in self.pages:
            self.current = page
            return
        page.on('dialog', lambda dialog: dialog.dismiss())
        page.set_default_timeout(15000)
        self.pages.append(page)
        self.current = page

    # -- navigation ----------------------------------------------------------------
    def _navigate(self, action):
        """Run an action that may navigate; follow checked redirects as new requests."""
        self.pending, self.error = None, None
        limits = self.run.load()['limits']
        response = None
        try:
            response = action()
        except Exception:
            pass
        hops = 0
        while self.pending and hops < int(limits['max_redirects']):
            target, self.pending, self.error = self.pending, None, None
            hops += 1
            try:
                response = self.current.goto(target, wait_until='domcontentloaded',
                                             timeout=limits['page_timeout_seconds'] * 1000)
            except Exception:
                pass
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        if self.pending:
            raise Unusable('too_many_redirects')
        try:
            self.current.wait_for_load_state('networkidle', timeout=6000)
        except Exception:
            pass
        self.stats.setdefault('browser_pages', 0)
        self.stats['browser_pages'] += 1
        self._flush()
        return response

    def open(self, url, new_tab=False):
        """Fetch and check first (redirect hops too); the tab changes only if the page may be read."""
        self.policy.check(url)
        limits = self.run.load()['limits']
        target = url
        for _ in range(int(limits['max_redirects']) + 1):
            page = self.reader.get(target, via='browser', follow=False)
            if page.status not in (301, 302, 303, 307, 308):
                break
            target = page.final_url
        else:
            raise Unusable('too_many_redirects')
        self.prefetched = {target: page}
        if new_tab:
            self._new_page(self.context.new_page())
        self._navigate(lambda: self.current.goto(target, wait_until='domcontentloaded',
                                                  timeout=limits['page_timeout_seconds'] * 1000))
        self.prefetched = {}
        self.controls = {}
        return self.snapshot()

    def text(self, full=False):
        body = self.current.inner_text('body') if self.current.url.startswith(('http://', 'https://')) else ''
        if challenged(body):
            host = urlsplit(self.current.url).netloc.lower()
            with self.run.update() as state:
                state['blocked_hosts'][host] = 'access_challenge'
            raise AccessRefused('access_challenge_host_stopped_for_this_run')
        limits = self.run.load()['limits']
        return body if full else excerpt(body, limits['excerpt_chars'], limits['max_excerpt_chars']), body

    def snapshot(self, full=False):
        shown, body = self.text(full)
        return {'url': self.current.url, 'title': self.current.title(), 'read_at': now_iso(), 'method': 'browser',
                'tab': self.pages.index(self.current), 'at_words_found': bool(AT_WORDS.search(body)),
                'text_mode': 'full' if full else 'excerpt', 'full_text_chars': len(body), 'text': shown}

    def scan(self):
        data = self.current.evaluate(COLLECT_JS)
        self.controls = {c['id']: c for c in data['controls']}
        self.forms = {f['index']: f for f in data['forms']}
        self.searchable = search_forms(data['controls'], data['forms'], self.policy)
        return data['controls']

    def list_controls(self, match=None):
        out = []
        for c in self.scan():
            kind, reason = classify(c, self.searchable, self.policy)
            if match and match.lower() not in (c['label'] + ' ' + (c.get('href') or '')).lower():
                continue
            out.append({'id': c['id'], 'allowed': kind, 'reason': reason, 'tag': c['tag'], 'label': c['label'][:80],
                        'href': c.get('href'), 'options': c.get('options')})
        return out

    def links(self, match=None):
        return [{'id': c['id'], 'label': c['label'], 'href': c['href']} for c in self.list_controls(match)
                if c['allowed'] == 'navigate']

    def _control(self, cid, expected):
        if not self.controls:
            self.scan()
        item = self.controls.get(str(cid))
        if item is None:
            raise ValueError('unknown_control_run_controls_again')
        kind, reason = classify(item, self.searchable, self.policy)
        if kind not in expected:
            self._count('blocked_operations')
            self._flush()
            raise ForbiddenOperation('refused_' + reason)
        return item, kind

    def click(self, cid):
        item, kind = self._control(cid, ('navigate', 'click', 'submit'))
        if kind == 'submit':
            return self.submit(cid)
        if kind == 'navigate':
            # A link is opened as its checked address, so a refused page never replaces this tab.
            return self.open(item['href'].split('#')[0], new_tab=item.get('target') == '_blank')
        before = len(self.pages)
        self._navigate(lambda: self.current.click('[data-at-id="%s"]' % item['id'], timeout=5000))
        if len(self.pages) > before:
            self._navigate(lambda: self.current.wait_for_load_state('domcontentloaded'))
        self.controls = {}
        return self.snapshot()

    def fill(self, cid, text):
        item, _ = self._control(cid, ('fill',))
        if not isinstance(text, str) or len(text) > 100 or re.search(r'@|\d{3}[- ]?\d{4}', text):
            raise ForbiddenOperation('search_text_only_shop_or_hotel_names')
        self.current.fill('[data-at-id="%s"]' % item['id'], text)
        item['value'] = text
        return {'filled': item['id'], 'text': text}

    def check(self, cid):
        item, _ = self._control(cid, ('check',))
        self.current.check('[data-at-id="%s"]' % item['id'])
        item['checked'] = True
        return {'checked': item['id'], 'label': item['label']}

    def select(self, cid, option):
        item, _ = self._control(cid, ('select',))
        if not AT_WORDS.search(option or '') or option not in (item.get('options') or []):
            self._count('blocked_operations')
            self._flush()
            raise ForbiddenOperation('refused_only_the_afternoon_tea_option_may_be_selected')
        self.current.select_option('[data-at-id="%s"]' % item['id'], label=option)
        return {'selected': item['id'], 'option': option}

    def submit(self, cid):
        item, _ = self._control(cid, ('submit', 'fill'))
        form = self.searchable.get(item.get('form'))
        if form is None:
            raise ForbiddenOperation('refused_not_a_search_form')
        values = {c['id']: c.get('value') for c in self.controls.values()}
        if form['action'] and not (form.get('raw_action') or '').startswith(('#', 'javascript:')):
            return self.open(search_url(form, list(self.controls.values()), values))
        # Script-driven search: the resulting page and data requests still pass the URL checks.
        self._navigate(lambda: self.current.press('[data-at-id="%s"]' % item['id'], 'Enter')
                       if item['tag'] == 'input' else self.current.click('[data-at-id="%s"]' % item['id']))
        self.controls = {}
        return self.snapshot()

    def scroll(self):
        self.current.mouse.wheel(0, 2500)
        self.current.wait_for_timeout(600)
        self.controls = {}
        return self.snapshot()

    def back(self):
        self._navigate(lambda: self.current.go_back(wait_until='domcontentloaded'))
        self.controls = {}
        return self.snapshot()

    def tabs(self):
        return [{'tab': i, 'url': p.url, 'current': p is self.current} for i, p in enumerate(self.pages) if not p.is_closed()]

    def tab(self, index):
        page = self.pages[int(index)]
        if page.is_closed():
            raise ValueError('tab_closed')
        self.current = page
        self.controls = {}
        return self.snapshot()

    def close_tab(self):
        if len([p for p in self.pages if not p.is_closed()]) <= 1:
            raise ValueError('last_tab')
        self.current.close()
        self.current = [p for p in self.pages if not p.is_closed()][-1]
        return self.tabs()

    def close(self):
        self._flush()
        for closer in (self.context.close, self.browser.close):
            try:
                closer()
            except Exception:
                pass
        if self.manager is not None:
            try:
                self.manager.stop()
            except Exception:
                pass


COMMANDS = {'open': lambda s, a: s.open(a['url'], a.get('new_tab', False)),
            'text': lambda s, a: s.snapshot(a.get('full', False)),
            'links': lambda s, a: s.links(a.get('match')),
            'controls': lambda s, a: s.list_controls(a.get('match')),
            'click': lambda s, a: s.click(a['id']),
            'fill': lambda s, a: s.fill(a['id'], a['text']),
            'check': lambda s, a: s.check(a['id']),
            'select': lambda s, a: s.select(a['id'], a['option']),
            'submit': lambda s, a: s.submit(a['id']),
            'scroll': lambda s, a: s.scroll(),
            'back': lambda s, a: s.back(),
            'tabs': lambda s, a: s.tabs(),
            'tab': lambda s, a: s.tab(a['index']),
            'close-tab': lambda s, a: s.close_tab(),
            'ping': lambda s, a: {'ok': True}}


def execute(session, command, args):
    """Run one command; errors become a result so the research can move to the next source."""
    try:
        return {'ok': True, 'result': COMMANDS[command](session, args)}
    except ForbiddenOperation as error:
        return {'ok': False, 'kind': 'forbidden', 'error': str(error)}
    except AccessRefused as error:
        return {'ok': False, 'kind': 'access_refused', 'error': str(error)}
    except BudgetExhausted as error:
        return {'ok': False, 'kind': 'stop_research', 'error': str(error)}
    except Unusable as error:
        return {'ok': False, 'kind': 'unusable', 'error': str(error)}
    except (ValueError, KeyError, IndexError) as error:
        return {'ok': False, 'kind': 'usage', 'error': str(error)}
    except Exception as error:
        return {'ok': False, 'kind': 'browser_error', 'error': type(error).__name__}


def serve(idle_seconds=None):
    from multiprocessing.connection import Listener
    run = RunState()
    limits = run.load()['limits']
    idle = float(idle_seconds or limits['browser_idle_seconds'])
    key = KEYFILE.read_bytes()
    if SOCKET.exists():
        SOCKET.unlink()
    session = Session(run)
    last = [time.monotonic()]

    def watchdog():
        while time.monotonic() - last[0] < idle:
            time.sleep(5)
        try:
            SOCKET.unlink()
        except OSError:
            pass
        os._exit(0)
    threading.Thread(target=watchdog, daemon=True).start()
    with Listener(str(SOCKET), family='AF_UNIX', authkey=key) as listener:
        while True:
            conn = listener.accept()
            with conn:
                message = conn.recv()
                last[0] = time.monotonic()
                if message.get('command') == 'stop':
                    conn.send({'ok': True, 'result': 'stopped'})
                    break
                conn.send(execute(session, message.get('command'), message.get('args') or {}))
                last[0] = time.monotonic()
    session.close()
    try:
        SOCKET.unlink()
    except OSError:
        pass


def call(command, timeout=None, **args):
    from multiprocessing.connection import Client
    if not SOCKET.exists():
        raise BrowserUnavailable('browser_not_started_run_browse_start')
    with Client(str(SOCKET), family='AF_UNIX', authkey=KEYFILE.read_bytes()) as conn:
        conn.send({'command': command, 'args': args})
        return conn.recv()


def start(wait=90):
    run = RunState()
    run.load()
    if SOCKET.exists():
        try:
            if call('ping').get('ok'):
                return {'browser': 'already_running'}
        except Exception:
            SOCKET.unlink()
    KEYFILE.parent.mkdir(parents=True, exist_ok=True)
    KEYFILE.write_bytes(secrets.token_bytes(32))
    os.chmod(KEYFILE, 0o600)
    with open(LOGFILE, 'ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'afternoon_tea', 'browse', 'serve'], stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(RUN.parents[1]))
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if process.poll() is not None:
            with run.update() as state:
                state['browser_unavailable'] = 'browser_start_failed'
            raise BrowserUnavailable('browser_start_failed_use_read_command')
        if SOCKET.exists():
            try:
                if call('ping').get('ok'):
                    return {'browser': 'started'}
            except Exception:
                pass
        time.sleep(0.3)
    process.kill()
    raise BrowserUnavailable('browser_start_timeout_use_read_command')


def stop():
    if not SOCKET.exists():
        return {'browser': 'not_running'}
    try:
        call('stop')
    except Exception:
        pass
    return {'browser': 'stopped'}
