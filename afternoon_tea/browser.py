"""Optional headless browser for list pages whose plans are drawn by JavaScript.

Used only after an anonymous GET of the same URL succeeded but showed no
afternoon-tea text. Everything else works without Playwright installed.

Allowed: open the one URL, scroll, read the shown text, press buttons that only
expand the same page ("もっと見る", "プラン", "閉じる" ...).
Blocked before sending: any second page navigation, any non-GET request,
pop-up windows, downloads, iframes, form fields, and any button or link whose
label names reservation, availability, application, purchase, payment, login,
registration, dates, times or party size. A fresh empty context is used every
time, so no cookie or login state is stored.
"""
import os
import re
import time
from urllib.parse import urlsplit
from afternoon_tea.fetch import ForbiddenOperation, check_scope, TRANSACTION
from afternoon_tea.fetch import USER_AGENT, CHALLENGE

ALLOW_LABEL = re.compile(
    r'もっと見る|もっと表示|さらに表示|さらに見る|すべて表示|すべて見る|全て表示|全て見る|続きを読む|続きを見る|'
    r'プラン|メニュー|コース|一覧|開く|展開|閉じる|^[×✕✖]$|'
    r'show more|see more|view more|read more|show all|view all|more|plans?|menus?|courses?|close', re.I)
DENY_LABEL = re.compile(
    r'予約|空席|空き|申込|申し込|購入|決済|支払|注文|カート|買い物|ログイン|ログアウト|会員|登録|サインイン|'
    r'送信|確定|確認する|次へ|進む|問い合わせ|問合せ|クーポン|日付|日時|時間|人数|名様|カレンダー|'
    r'reserv|book|availab|login|log in|sign|register|cart|checkout|pay|order|buy|purchase|submit|'
    r'apply|next|continue|date|time|guest|people|calendar|\d', re.I)
SITE_FAMILY = ('ikyu.com', 'tabelog.com', 'tablecheck.com')
QUIET_TYPES = {'image', 'media', 'font', 'websocket', 'eventsource', 'manifest', 'texttrack', 'ping', 'other'}
MAX_CLICKS = 5
MAX_SECONDS = 40
# Lists visible candidates only; marks them so Python can click the vetted ones.
CANDIDATES_JS = r'''() => {
  const nodes = Array.from(document.querySelectorAll('button,[role=button],[role=tab],summary,a'));
  const out = [];
  nodes.forEach((el, i) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    el.setAttribute('data-at-candidate', String(i));
    out.push({id: String(i), tag: el.tagName.toLowerCase(),
      label: ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '')).trim().slice(0, 80),
      href: el.getAttribute('href'), type: (el.getAttribute('type') || '').toLowerCase(),
      in_form: !!el.closest('form'), disabled: !!el.disabled,
      popup: (el.getAttribute('target') || '').toLowerCase() === '_blank'});
  });
  return out;
}'''


class BrowserUnavailable(RuntimeError):
    pass


def click_allowed(item):
    """Only same-page expansion controls; any doubt means no click."""
    label = ' '.join(str(item.get('label') or '').split())
    href = item.get('href')
    if not label or len(label) > 30 or item.get('disabled') or item.get('in_form') or item.get('popup'):
        return False
    if item.get('type') in ('submit', 'reset', 'image'):
        return False
    if item.get('tag') == 'a' and href not in (None, '', '#') and not str(href).startswith('#'):
        return False
    return bool(ALLOW_LABEL.search(label)) and not DENY_LABEL.search(label)


class Guard:
    """Decides every browser request before it is sent."""

    def __init__(self, url, list_url):
        check_scope(url, list_url)
        self.url = url
        self.list_url = list_url
        self.navigated = False
        self.blocked_operations = 0
        self.blocked_resources = 0

    def allow(self, url, method, resource_type, navigation, main_frame):
        if navigation and resource_type == 'document':
            if not main_frame:
                self.blocked_resources += 1
                return False
            # Exactly one navigation: the vetted URL. Anything later is refused.
            if not self.navigated and method == 'GET' and url == self.url:
                try:
                    check_scope(url, self.list_url)
                except ForbiddenOperation:
                    self.blocked_operations += 1
                    return False
                self.navigated = True
                return True
            self.blocked_operations += 1
            return False
        p = urlsplit(url)
        host = p.hostname or ''
        family = any(host == d or host.endswith('.' + d) for d in SITE_FAMILY)
        if (method != 'GET' or resource_type in QUIET_TYPES or p.scheme != 'https' or p.username or p.password
                or not family or TRANSACTION.search(p.path.lower())):
            self.blocked_resources += 1
            return False
        return True


def _launch(playwright):
    options = {'headless': True}
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        options['args'] = ['--no-sandbox']
    path = os.environ.get('AFTERNOON_TEA_CHROMIUM')
    if path:
        options['executable_path'] = path
    try:
        return playwright.chromium.launch(**options)
    except Exception as error:
        fallback = '/opt/pw-browsers/chromium'
        if path or not os.path.exists(fallback):
            raise BrowserUnavailable('browser_launch_failed') from error
        try:
            return playwright.chromium.launch(executable_path=fallback, **options)
        except Exception as again:
            raise BrowserUnavailable('browser_launch_failed') from again


def render(url, list_url, playwright=None, deadline=None):
    """Return (text, links, guard). Raises BrowserUnavailable if no browser."""
    guard = Guard(url, list_url)
    manager = None
    if playwright is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise BrowserUnavailable('playwright_not_installed') from error
        try:
            manager = sync_playwright()
            playwright = manager.start()
        except Exception as error:
            raise BrowserUnavailable('playwright_start_failed') from error
    end = min(deadline or float('inf'), time.monotonic() + MAX_SECONDS)
    browser = None
    try:
        browser = _launch(playwright)
        context = browser.new_context(accept_downloads=False, service_workers='block', user_agent=USER_AGENT,
                                      locale='ja-JP', java_script_enabled=True)
        page = context.new_page()

        def route(route, request):
            if guard.allow(request.url, request.method, request.resource_type,
                           request.is_navigation_request(), request.frame == page.main_frame):
                route.continue_()
            else:
                route.abort()

        def popup(other):
            guard.blocked_operations += 1
            other.close()
        context.route('**/*', route)
        context.on('page', popup)
        page.on('dialog', lambda dialog: dialog.dismiss())
        page.set_default_timeout(8000)
        response = page.goto(url, wait_until='domcontentloaded', timeout=15000)
        if response is None or response.status != 200:
            raise RuntimeError('browser_HTTP_' + str(getattr(response, 'status', 'none')))
        try:
            page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass
        clicked = set()
        for _ in range(MAX_CLICKS):
            if time.monotonic() >= end:
                break
            page.mouse.wheel(0, 2500)
            items = [i for i in page.evaluate(CANDIDATES_JS) if click_allowed(i) and i['label'] not in clicked]
            if not items:
                break
            clicked.add(items[0]['label'])
            try:
                page.click('[data-at-candidate="%s"]' % items[0]['id'], timeout=3000, no_wait_after=True)
                page.wait_for_timeout(800)
            except Exception:
                pass
            if page.url != url:
                guard.blocked_operations += 1
                raise ForbiddenOperation('browser_left_page')
        text = page.inner_text('body')
        links = page.evaluate('() => Array.from(document.links, a => a.href)')
        context.close()
    except BrowserUnavailable:
        raise
    except (ForbiddenOperation, RuntimeError) as error:
        error.guard = guard
        raise
    except Exception as error:
        failure = RuntimeError('browser_failed:' + type(error).__name__)
        failure.guard = guard
        raise failure from error
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if manager is not None:
            try:
                manager.stop()
            except Exception:
                pass
    try:
        if any(marker in text.lower() for marker in CHALLENGE):
            raise RuntimeError('access_challenge')
        from afternoon_tea.check import scan
        scan(text.encode())
    except ValueError as error:
        failure = RuntimeError('unusable_page:' + str(error))
        failure.guard = guard
        raise failure from error
    except RuntimeError as error:
        error.guard = guard
        raise
    return text, links, guard
