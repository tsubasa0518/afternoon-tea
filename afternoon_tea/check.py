"""Trusted-main validation, weekly PR intake and publication checks."""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from afternoon_tea.fetch import NoRedirect
from afternoon_tea.config import ROOT
from afternoon_tea.fetch import require
from afternoon_tea.fetch import dumps

REPO = 'tsubasa0518/afternoon-tea'
SITE = 'https://tsubasa0518.github.io/afternoon-tea/'
BRANCH_PREFIX = 'claude/weekly-afternoon-tea-'
RESEARCH = 'site/research.json'
ALLOWED = {RESEARCH, 'site/index.html'}
MAX_HTML = 5000000
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

def sha(value):
    return hashlib.sha256(value).hexdigest()

def json_bytes(value):
    return dumps(value).encode()

class SensitiveDataError(ValueError):
    """A safe reason only: never include the matched value in logs."""

def scan(value):
    text = value.decode('utf-8')
    patterns = ('-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
         '\\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:ant-|proj-)[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})',
         '(?i)authorization\\s*[:=]\\s*[\\"\\x27]?bearer\\s+\\S+',
         '\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b',
         '\\b0[5789]0[- ]\\d{4}[- ]\\d{4}\\b')
    if any(re.search(p, text) for p in patterns):
        raise SensitiveDataError('secret_or_personal_contact_detected')
    # Card-like values are checked without printing matched sensitive text.
    for raw in re.findall('(?<!\\d)(?:\\d[ -]?){13,19}(?!\\d)', text):
        digits = re.sub('\\D', '', raw)
        if len(digits) < 13:
            continue
        nums = [int(c) for c in digits[::-1]]
        total = sum(((n * 2 - 9 if n * 2 > 9 else n * 2) if i % 2 else n for (i, n) in enumerate(nums)))
        if total % 10 == 0:
            raise SensitiveDataError('possible_payment_card_detected')
    return text

def resource(url, asset=False):
    if url.startswith('#'):
        return
    if asset and url.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/gif;base64,', 'data:image/webp;base64,')):
        return
    p = urlsplit(url)
    require(p.scheme == 'https' and p.hostname and (p.username is None) and (p.password is None), 'unsafe_or_missing_resource')
    require(not any((c.isspace() for c in url)) and '\\' not in url, 'invalid_resource_url')
    require(not re.search('(?i)(?:[?&])(?:token|session(?:id)?|auth|password|booking_id)=', url), 'session_in_resource')
    if asset:
        require(p.hostname in ('fonts.googleapis.com', 'fonts.gstatic.com'), 'use_embedded_assets_or_google_fonts')

class StaticHTML(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.seen = set()
        self.resources = []
        self.body_text = []

    def handle_starttag(self, tag, attrs):
        require(len({k for (k, v) in attrs}) == len(attrs), 'duplicate_html_attribute')
        attrs = dict(attrs)
        if tag in ('html', 'head', 'body', 'title'):
            require(tag not in self.seen, 'duplicate_document_element')
            parent = {'html': None, 'head': 'html', 'body': 'html', 'title': 'head'}[tag]
            require((self.stack[-1] if self.stack else None) == parent, 'invalid_document_structure')
            if tag == 'body':
                require('head' in self.seen, 'missing_document_head')
        else:
            require(bool(self.stack), 'element_outside_html')
        self.seen.add(tag)
        require(tag not in ('form', 'iframe', 'object', 'embed', 'base'), 'active_form_or_embedded_content_forbidden')
        require(not any((k.lower().startswith('on') for k in attrs)), 'inline_event_handler_forbidden')
        if tag == 'script':
            require('src' not in attrs, 'external_script_forbidden')
        for key in ('href', 'src', 'poster'):
            if attrs.get(key):
                resource(attrs[key], asset=tag != 'a')
                self.resources.append(attrs[key])
        require('srcset' not in attrs, 'embed_images_without_srcset')
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
            raise ValueError('automatic_navigation_forbidden')
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if 'body' in self.stack and (not set(self.stack) & {'script', 'style'}):
            self.body_text.append(data)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        require(bool(self.stack) and self.stack[-1] == tag, 'unbalanced_html_tags')
        self.stack.pop()

def validate_html_bytes(value):
    require(0 < len(value) <= MAX_HTML, 'html_missing_empty_or_too_large')
    text = scan(value)
    parser = StaticHTML()
    parser.feed(text)
    parser.close()
    require(not parser.stack and {'html', 'head', 'body', 'title'} <= parser.seen, 'html_document_incomplete')
    require(''.join(parser.body_text).strip(), 'blank_page_forbidden')
    for target in re.findall('url\\(\\s*[\\"\\x27]?([^\\)\\"\\x27]+)', text, re.I):
        resource(target.strip(), asset=True)
    # Inline script is allowed for static filters, but must not drive network/forms.
    require(not re.search('\\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon|eval)\\b|document\\.cookie|(?:local|session)Storage',
         text),
         'network_or_session_script_forbidden')
    return {'bytes': len(value), 'sha256': sha(value), 'resources': parser.resources, 'technical_validation': 'passed'}

class ZeroListing(ValueError):
    """Not an error of the program: there is nothing confirmed to show, so the live site is kept."""


def validate_json(value):
    require(len(value) <= 3000000, 'json_too_large')
    scan(value)
    data = json.loads(value, parse_constant=lambda x: require(False, 'non_finite_json_number'))
    scan(json_bytes(data))
    require(isinstance(data, dict) and data.get('schema_version') == 2, 'invalid_json_document')
    require(isinstance(data.get('shops'), list), 'json_records_required')
    if data.get('generated_at') is not None:
        require(dt.datetime.fromisoformat(data['generated_at']).tzinfo is not None, 'timestamp_timezone_required')
    from afternoon_tea.build import validate_country
    ids = set()
    for shop in data['shops']:
        require(isinstance(shop, dict) and isinstance(shop.get('plans', []), list), 'invalid_shop')
        if 'id' in shop:
            require(isinstance(shop['id'], str) and shop['id'] not in ids, 'shop_id_invalid_or_duplicated')
            ids.add(shop['id'])
        require(isinstance(shop.get('name'), str) and shop['name'].strip(), 'shop_name_required')
        require(type(shop.get('area_no')) is int and 1 <= shop['area_no'] <= 14,
                'shop_area_outside_fourteen')
        for plan in shop.get('plans', []):
            require(isinstance(plan, dict), 'invalid_plan')
            validate_country(plan)
    progress = data.get('progress', {'entries': {}})
    require(isinstance(progress, dict) and isinstance(progress.get('entries', {}), dict), 'invalid_progress')
    for entry in progress.get('entries', {}).values():
        require(isinstance(entry, dict) and len(json_bytes(entry)) < 4000, 'invalid_progress_entry')
    return data

def publishable(research, require_nonzero=True):
    """Count what the site would show. Zero shops or zero valid plans never replace the live site."""
    from afternoon_tea.build import displayable
    shown = list(displayable(research))
    counts = {'shops': len(shown), 'plans': sum(len(plans) for _, plans in shown)}
    if require_nonzero and (counts['shops'] == 0 or counts['plans'] == 0):
        raise ZeroListing('zero_listing_publication_refused_previous_site_kept')
    return counts

def validate_site(files):
    require(set(files) == ALLOWED, 'site_requires_exactly_two_files')
    report = validate_html_bytes(files['site/index.html'])
    research = validate_json(files['site/research.json'])
    # Age is not a publication condition; format and safety are.
    from afternoon_tea.build import timestamp
    for shop in research['shops']:
        for plan in shop.get('plans', []):
            timestamp(plan.get('checked_at'))
    return {**report, 'generated_at': research.get('generated_at'), **publishable(research, require_nonzero=False)}

def card_count(html_bytes):
    return len(re.findall(rb'<article class="card ', html_bytes))

def write_summary(stage, report):
    """Use existing Actions step summaries; do not add monitoring or merge conditions."""
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if not target:
        return
    rows = [('処理結果', stage)]
    if report:
        rows += [('調査データ生成日時',
             report.get('generated_at') or '未記録'),
             ('掲載店舗数', report.get('shops', 0)),
             ('掲載プラン数', report.get('plans', 0))]


    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    lines = ['\n### 週次サイト更新', '', '| 項目 | 結果 |', '| --- | --- |']
    lines += ['| ' + cell(k) + ' | ' + cell(v) + ' |' for (k, v) in rows]
    lines.append('')
    if report.get('pr'):
        lines.append('PR: https://github.com/' + REPO + '/pull/' + str(int(report['pr'])))
    run = os.environ.get('GITHUB_RUN_ID')
    if run and run.isdigit():
        lines.append('実行: https://github.com/' + REPO + '/actions/runs/' + run)
    lines.append('公開URL: ' + SITE)
    with open(target, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

class API:

    def call(self, method, path, body=None):
        require(method in ('GET', 'PUT') and path.startswith('/') and ('..' not in path), 'invalid_github_api_request')
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'RoutineSiteDelivery'}
        token = os.environ.get('GH_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        payload = json_bytes(body) if body is not None else None
        if payload:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request('https://api.github.com/repos/' + REPO + path, data=payload, headers=headers, method=method)
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def get(self, path):
        return self.call('GET', path)

    def blob(self, blob_sha):
        require(bool(re.fullmatch('[0-9a-f]{40}', blob_sha)), 'invalid_blob_sha')
        obj = self.get('/git/blobs/' + blob_sha)
        require(obj['encoding'] == 'base64' and obj['size'] <= MAX_HTML, 'blob_too_large')
        return base64.b64decode(''.join(obj['content'].split()), validate=True)

    def files(self, commit):
        require(bool(re.fullmatch('[0-9a-f]{40}', commit)), 'invalid_commit_sha')
        tree = self.get('/git/trees/' + commit + '?recursive=1')
        require(not tree.get('truncated'), 'truncated_tree')
        return {x['path']: x for x in tree['tree']}


def require_routine(pr, author):
    require((not pr['draft'] and pr['base']['ref'] == 'main'
             and pr['base']['repo']['full_name'] == REPO
             and pr['head']['repo'] and pr['head']['repo']['full_name'] == REPO
             and pr['head']['ref'].startswith(BRANCH_PREFIX)
             and pr['user']['login'] == author and pr['title'].startswith('[weekly-site]')),
            'pr_not_a_trusted_routine')


def intake(api, number, author, expected_head=None):
    """Read only the PR's JSON; validate with trusted main, then merge that head."""
    number = str(int(number))
    pr = api.get('/pulls/' + number)
    require_routine(pr, author)
    head = pr['head']['sha']
    require(bool(re.fullmatch('[0-9a-f]{40}', head)), 'invalid_pr_head')
    require(expected_head is None or head == expected_head, 'pr_head_changed')
    if pr.get('merged') is True:
        return {'pr': number, 'head_sha': head, 'merge': 'already_merged'}
    require(pr['state'] == 'open', 'pr_closed_without_merge')
    require(pr['changed_files'] == 1, 'routine_change_allowlist')
    changed = api.get('/pulls/' + number + '/files?per_page=100')
    require(len(changed) == 1 and changed[0]['filename'] == RESEARCH
            and changed[0]['status'] in ('added', 'modified'), 'routine_change_allowlist')
    entry = api.files(head).get(RESEARCH, {})
    require(entry.get('mode') == '100644' and entry.get('type') == 'blob', 'unsafe_pr_file')
    raw = api.blob(entry['sha'])
    from afternoon_tea.render import render
    research = validate_json(raw)
    report = validate_site({RESEARCH: raw, 'site/index.html': render(research).encode()})
    try:
        publishable(research)
    except ZeroListing:
        # Results stay on the PR branch for the next run; nothing is merged or published.
        return {**report, 'pr': number, 'head_sha': head, 'merge': 'skipped_zero_listing'}
    latest = api.get('/pulls/' + number)
    require_routine(latest, author)
    require(latest['head']['sha'] == head, 'pr_head_changed')
    require(latest['state'] == 'open' and not latest['draft'], 'pr_no_longer_open')
    require(latest.get('mergeable') is not False, 'pr_merge_conflict')
    # GitHub enforces branch protection and the expected head atomically.
    merged = api.call('PUT', '/pulls/' + number + '/merge', {'sha': head, 'merge_method': 'merge'})
    require(merged.get('merged') is True, 'merge_not_completed')
    require(bool(re.fullmatch('[0-9a-f]{40}', merged.get('sha', ''))), 'invalid_merge_commit')
    return {**report, 'pr': number, 'head_sha': head, 'commit': merged['sha'], 'merge': 'merged'}


def delivery_directory():
    staging = ROOT / '.staging'
    base = staging / 'routine-delivery'
    require(not staging.is_symlink() and not base.is_symlink(), 'unsafe_delivery_directory')
    require(base.resolve().is_relative_to(ROOT.resolve() / '.staging'), 'unsafe_delivery_directory')
    base.mkdir(parents=True, exist_ok=True)
    return base


def outputs(**values):
    """Only validated hashes become job outputs, never PR text or shell code."""
    for value in values.values():
        require(isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', value)),
                'invalid_workflow_output')
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a', encoding='utf-8') as stream:
            for key, value in values.items():
                stream.write(key + '=' + value + '\n')


def prepare():
    from afternoon_tea.render import render
    path = ROOT / RESEARCH
    require(not path.is_symlink() and not path.parent.is_symlink(), 'site_symlink_forbidden')
    raw = path.read_bytes()
    research = validate_json(raw)
    html = render(research).encode()
    report = validate_site({RESEARCH: raw, 'site/index.html': html})
    report.update(source_commit=os.environ.get('SOURCE_COMMIT'), url=SITE)
    try:
        publishable(research)
    except ZeroListing:
        report['publication'] = 'refused_zero_listing'
        return report
    require(card_count(html) == report['shops'], 'rendered_cards_do_not_match_listing')
    base = delivery_directory()
    target = base / 'site'
    require(not target.is_symlink() and not (target / 'index.html').is_symlink()
            and not (base / 'report.json').is_symlink(), 'unsafe_delivery_directory')
    target.mkdir(exist_ok=True)
    (target / 'index.html').write_bytes(html)
    report['publication'] = 'prepared'
    (base / 'report.json').write_bytes(json_bytes(report))
    values = {'html_sha256': report['sha256']}
    if report['source_commit'] is not None:
        values['source_commit'] = report['source_commit']
    outputs(**values)
    return report


def verify_public(expected, attempts=6, opener=None, sleep=time.sleep):
    opener = opener or urllib.request.build_opener(NoRedirect())
    observations = []
    for i in range(attempts):
        raw = None
        try:
            with opener.open(urllib.request.Request(SITE, headers={'Cache-Control': 'no-cache'}), timeout=15) as r:
                raw = r.read(MAX_HTML + 1)
                observations.append({'status': r.status, 'sha256': sha(raw)})
                matched = r.status == 200 and sha(raw) == expected
        except Exception as e:
            observations.append({'error': type(e).__name__})
            matched = False
        if matched:
            validate_html_bytes(raw)
            observations[-1]['cards'] = card_count(raw)
            require(observations[-1]['cards'] > 0, 'public_site_has_zero_listings')
            return observations
        if i + 1 < attempts:
            sleep(10)
    raise ValueError('public_verification_failed:' + json.dumps(observations))

def main(command='site', expected_sha256=None):
    try:
        if command == 'site':
            from afternoon_tea.render import render
            raw = (ROOT / RESEARCH).read_bytes()
            print(validate_site({RESEARCH: raw, 'site/index.html': render(validate_json(raw)).encode()}))
        elif command == 'intake':
            event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
            report = intake(API(), event['number'], os.environ.get('ROUTINE_AUTHOR') or REPO.split('/')[0],
                            expected_head=event['pull_request']['head']['sha'])
            if report.get('commit'):
                outputs(commit=report['commit'])
            print(report)
            write_summary({'merged': 'マージ成功', 'already_merged': 'マージ済み（再公開しない）',
                           'skipped_zero_listing': '掲載対象0件のため自動マージ・公開を見送り（異常終了ではありません。前回の公開サイトを維持）'
                           }.get(report['merge'], report['merge']), report)
        elif command == 'prepare':
            report = prepare()
            print(report)
            if report.get('publication') == 'refused_zero_listing':
                write_summary('掲載対象0件のため公開を見送り（異常終了ではありません。前回の公開サイトを維持）', report)
            else:
                write_summary('HTML公開準備成功（デプロイ前）', report)
        elif command == 'verify':
            require(isinstance(expected_sha256, str) and bool(re.fullmatch('[0-9a-f]{64}', expected_sha256)),
                    'expected_html_sha256_required')
            observations = verify_public(expected_sha256)
            target = delivery_directory() / 'public-verification.json'
            require(not target.is_symlink(), 'unsafe_delivery_directory')
            target.write_bytes(json_bytes(observations))
            print({'public_verification': 'passed', 'http': observations})
            write_summary('Pages公開確認成功（HTTP 200・HTML SHA-256一致）', {})
        else:
            raise ValueError('unknown_check_command')
    except Exception:
        write_summary(command + '失敗。実行ログのエラーを確認してください。', {})
        raise
