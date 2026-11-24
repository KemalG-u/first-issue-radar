"""GitHub'a yalnız okuma yapan radar işlevleri."""
import datetime
from contextlib import closing
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

NAME = re.compile(r'^[A-Za-z0-9_.-]{1,100}$')
IDENT = re.compile(r'^([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100})#([1-9][0-9]{0,9})$')
CONFIG_NAME = 'config.json'
BASE = 'is:issue is:open is:public archived:false no:assignee'
QUERIES = [BASE + ' label:"good first issue"', BASE + ' label:"first-timers-only"', BASE + ' label:documentation label:"help wanted"']

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def text(value, limit=2000):
    return ''.join(c for c in str(value or '') if c in '\n\t' or ord(c) >= 32)[:limit]

def parse_id(value):
    if not isinstance(value, str):
        raise ValueError('Geçersiz kimlik')
    m = IDENT.fullmatch(value)
    if not m or any(x in ('.', '..') for x in m.group(1, 2)):
        raise ValueError('Geçersiz kimlik')
    return m.group(1), m.group(2), int(m.group(3))

def gh(endpoint, params=None):
    # Only routes needed by this application; no URL or query-string escapes.
    if not isinstance(endpoint, str) or not isinstance(params if params is not None else {}, dict):
        raise ValueError('Geçersiz GitHub isteği')
    params = params or {}
    parts = endpoint.split('/')
    allowed = endpoint in ('user', 'search/issues')
    kind = endpoint
    if len(parts) >= 3 and parts[0] == 'repos':
        try:
            parse_id(parts[1] + '/' + parts[2] + '#1')
            tail = '/'.join(parts[3:])
            allowed = (tail == '' or bool(re.fullmatch(r'issues/[1-9][0-9]{0,9}(/(comments|timeline))?', tail))
                       or bool(re.fullmatch(r'pulls/[1-9][0-9]{0,9}', tail)) or tail in ('contents/CONTRIBUTING.md', 'contents/.github/CONTRIBUTING.md', 'contents/docs/CONTRIBUTING.md')
                       or bool(re.fullmatch(r'commits/[0-9a-fA-F]{40}/(check-runs|status)', tail)))
            kind = tail
        except ValueError:
            allowed = False
    if not allowed: raise ValueError('İzin verilmeyen GitHub yolu')
    permitted = {'q', 'per_page'} if kind == 'search/issues' else ({'per_page'} if kind.endswith(('/comments', '/timeline', '/check-runs')) else set())
    if not set(params) <= permitted: raise ValueError('İzin verilmeyen GitHub parametresi')
    if 'q' in params and (not isinstance(params['q'], str) or not 1 <= len(params['q']) <= 500 or any(ord(c) < 32 or ord(c) == 127 for c in params['q'])):
        raise ValueError('Geçersiz arama sorgusu')
    if kind == 'search/issues' and 'q' not in params: raise ValueError('Arama sorgusu eksik')
    if 'per_page' in params and (type(params['per_page']) is not int or not 1 <= params['per_page'] <= 100): raise ValueError('Geçersiz sayfa boyutu')
    args = ['gh', 'api', '-X', 'GET', endpoint]
    for k, v in (params or {}).items():
        args += ['-f', k + '=' + str(v)]
    try:
        p = subprocess.run(args, capture_output=True, timeout=20, check=False)
        if p.returncode:
            raise RuntimeError('GitHub okuması başarısız veya erişim sınırlı')
        return json.loads(p.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise RuntimeError('GitHub yanıtı alınamadı') from exc

# This fixed query is the only GraphQL operation: no client-supplied query or mutation.
CONTRIBUTION_QUERY = 'query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){contributionsCollection(from:$from,to:$to){pullRequestContributions(first:100){nodes{pullRequest{number url repository{nameWithOwner}}} pageInfo{hasNextPage}}}}}'

def contribution_graph(created_at, login):
    try:
        if not isinstance(login, str) or not NAME.fullmatch(login): raise ValueError('Geçersiz hesap adı')
        dt = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        if dt.tzinfo is None: raise ValueError('Saat dilimi yok')
        day = dt.astimezone(datetime.timezone.utc).date()
        start = day.isoformat() + 'T00:00:00Z'
        end = (day + datetime.timedelta(days=1)).isoformat() + 'T00:00:00Z'
        args = ['gh', 'api', 'graphql', '-f', 'query=' + CONTRIBUTION_QUERY, '-f', 'login=' + login, '-f', 'from=' + start, '-f', 'to=' + end]
        result = subprocess.run(args, capture_output=True, timeout=20, check=False)
        if result.returncode: raise RuntimeError('GraphQL sorgusu başarısız')
        return json.loads(result.stdout)
    except (AttributeError, TypeError, ValueError, OverflowError, OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Katkı sorgusu veya PR tarihi okunamadı') from exc

def contribution_visible(created_at, warnings=None, tracked=None, login=None):
    try:
        if tracked is None or login is None: raise RuntimeError('İzlenen PR veya hesap tanımlı değil.')
        t_owner, t_repo, t_number = tracked
        graph = contribution_graph(created_at, login)
        if not isinstance(graph, dict) or graph.get('errors'): raise RuntimeError('GitHub GraphQL sorgusu hata döndürdü.')
        page = graph['data']['user']['contributionsCollection']['pullRequestContributions']
        nodes = page['nodes']; more = page['pageInfo']['hasNextPage']
        if not isinstance(nodes, list) or type(more) is not bool: raise ValueError()
        for node in nodes:
            pull = node['pullRequest']
            number, url, repo = pull['number'], pull['url'], pull['repository']['nameWithOwner']
            if type(number) is not int or not isinstance(url, str) or not isinstance(repo, str): raise ValueError()
            if number == t_number and url == f'https://github.com/{t_owner}/{t_repo}/pull/{t_number}' and repo.lower() == f'{t_owner}/{t_repo}'.lower(): return True
        if more: raise RuntimeError('İlk 100 katkı içinde PR bulunamadı; ek sonuçlar var.')
        return False
    except RuntimeError as exc:
        if warnings is not None: warnings.append('Katkı görünürlüğü bilinmiyor: ' + str(exc))
        return None
    except (KeyError, TypeError, ValueError, AttributeError):
        if warnings is not None: warnings.append('Katkı görünürlüğü bilinmiyor: GitHub yanıtı eksik veya geçersiz.')
        return None

def safe_issue(item):
    try:
        url = item['html_url']; number = item['number']; title = item['title']
        m = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)', url)
        if not m or type(number) is not int or int(m.group(3)) != number or not isinstance(title, str) or not title.strip():
            return None
        owner, repo = m.group(1, 2)
        parse_id(f'{owner}/{repo}#{number}')
        labels = [text(x.get('name'), 100) for x in item.get('labels', []) if isinstance(x, dict) and isinstance(x.get('name'), str)][:30]
        return {'id': f'{owner}/{repo}#{number}', 'owner': owner, 'repo': repo, 'number': number,
                'title': text(title, 500), 'url': url, 'labels': labels, 'updated_at': text(item.get('updated_at'), 50),
                'language': None, 'why': ['Etiket: ' + x for x in labels if x.lower() in ('good first issue', 'first-timers-only', 'documentation', 'help wanted')],
                'unknowns': ['Bakımcı politikası bilinmiyor', 'Tekrar iş olup olmadığı bilinmiyor', 'Maliyet bilinmiyor'], 'score': 0}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None

def scan():
    items = {}; warnings = []; incomplete = False
    for q in QUERIES:
        try:
            result = gh('search/issues', {'q': q, 'per_page': 20})
            if not isinstance(result, dict) or not isinstance(result.get('items'), list):
                raise RuntimeError('Geçersiz arama yanıtı')
            if result.get('incomplete_results') is not False:
                incomplete = True; warnings.append('GitHub arama sonucunun eksiksizliği doğrulanamadı.')
            if type(result.get('total_count')) is not int or result['total_count'] < 0:
                raise RuntimeError('Geçersiz arama sayısı')
            if result['total_count'] > len(result['items']):
                incomplete = True; warnings.append('Arama ilk 20 sonuçla sınırlı.')
            for raw in result['items']:
                item = safe_issue(raw)
                if item:
                    items[item['id'].lower()] = item
                else:
                    incomplete = True; warnings.append('Geçersiz bir sonuç atlandı.')
        except (RuntimeError, TypeError):
            incomplete = True; warnings.append('Bir arama okunamadı; sonuçlar kısmi olabilir.')
    return {'items': list(items.values()), 'scanned_at': now(), 'queries': QUERIES[:], 'incomplete': incomplete, 'warnings': list(dict.fromkeys(warnings))}

def check_summary(sha, warnings, tracked):
    root = f'repos/{tracked[0]}/{tracked[1]}/commits/' + sha
    checks = status = None
    try: checks = gh(root + '/check-runs', {'per_page': 100})
    except RuntimeError: warnings.append('PR kontrolleri okunamadı.')
    try: status = gh(root + '/status')
    except RuntimeError: warnings.append('PR durum bağlamları okunamadı.')
    runs = checks.get('check_runs') if isinstance(checks, dict) else None
    contexts = status.get('statuses') if isinstance(status, dict) else None
    failure = ('failure', 'timed_out', 'cancelled', 'action_required', 'startup_failure', 'error')
    if isinstance(runs, list) and any(isinstance(r, dict) and r.get('conclusion') in failure for r in runs): return 'failure'
    if isinstance(status, dict) and status.get('state') in ('failure', 'error'): return 'failure'
    if isinstance(contexts, list) and any(isinstance(c, dict) and c.get('state') in ('failure', 'error') for c in contexts): return 'failure'
    if isinstance(runs, list) and any(isinstance(r, dict) and r.get('status') in ('queued', 'in_progress', 'waiting', 'pending', 'requested') for r in runs): return 'pending'
    if isinstance(status, dict) and status.get('state') == 'pending': return 'pending'
    if isinstance(contexts, list) and any(isinstance(c, dict) and c.get('state') == 'pending' for c in contexts): return 'pending'
    complete_runs = (isinstance(runs, list) and bool(runs) and type(checks.get('total_count')) is int and checks['total_count'] == len(runs)
                     and all(isinstance(r, dict) and r.get('status') == 'completed' and r.get('conclusion') in ('success', 'neutral', 'skipped') for r in runs))
    complete_status = (isinstance(contexts, list) and type(status.get('total_count')) is int and status['total_count'] == len(contexts)
                       and status.get('state') == 'success' and all(isinstance(c, dict) and c.get('state') == 'success' for c in contexts))
    return 'success' if complete_runs and complete_status else None

def load_config(root=None, environ=None):
    """Optional settings. Environment variables override config.json (see config.example.json).

    github_login: expected GitHub account (RADAR_GITHUB_LOGIN); optional safety check.
    tracked_pr:   "owner/repo#number" (RADAR_TRACKED_PR); optional pull request to show in the side panel.
    Returns {'github_login': str|None, 'tracked_pr': (owner, repo, number)|None}. Raises ValueError if invalid.
    """
    env = os.environ if environ is None else environ
    data = {}
    path = Path(root if root is not None else Path(__file__).resolve().parent) / CONFIG_NAME
    if path.is_file() and not path.is_symlink():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('config.json okunamadı veya geçersiz') from exc
        if not isinstance(data, dict): raise ValueError('config.json bir nesne olmalı')
    login = env.get('RADAR_GITHUB_LOGIN') or data.get('github_login') or None
    tracked = env.get('RADAR_TRACKED_PR') or data.get('tracked_pr') or None
    if login is not None and (not isinstance(login, str) or not NAME.fullmatch(login)): raise ValueError('Geçersiz github_login')
    if tracked is not None: tracked = parse_id(tracked)
    return {'github_login': login, 'tracked_pr': tracked}

def account_pr(config=None):
    warning = []
    if config is None:
        try: config = load_config()
        except ValueError as exc:
            config = {'github_login': None, 'tracked_pr': None}; warning.append('Yapılandırma yok sayıldı: ' + str(exc))
    expected = config.get('github_login'); tracked = config.get('tracked_pr')
    try:
        login = gh('user').get('login')
        if not isinstance(login, str) or not NAME.fullmatch(login): raise RuntimeError('Geçersiz hesap')
        account = login if expected is None or login.lower() == expected.lower() else None
        if account is None: warning.append('GitHub hesabı beklenen hesap değil.')
    except (RuntimeError, AttributeError):
        account = None; warning.append('GitHub hesabı okunamadı.')
    pr = None
    if tracked is None:
        return account, '; '.join(warning) or None, None
    t_owner, t_repo, t_number = tracked
    pr_url = f'https://github.com/{t_owner}/{t_repo}/pull/{t_number}'
    try:
        p = gh(f'repos/{t_owner}/{t_repo}/pulls/{t_number}')
        if p.get('html_url') != pr_url: raise RuntimeError('Geçersiz PR')
        check = None
        sha = p.get('head', {}).get('sha', '')
        if isinstance(sha, str) and re.fullmatch(r'[0-9a-fA-F]{40}', sha):
            check = check_summary(sha, warning, tracked)
        pr = {'url': p['html_url'], 'title': text(p.get('title'), 500), 'state': text(p.get('state'), 20), 'draft': p.get('draft') if isinstance(p.get('draft'), bool) else None, 'merged': p.get('merged') if isinstance(p.get('merged'), bool) else None, 'check_status': check, 'contribution_visible': None, 'checked_at': now()}
        if account is not None:
            pr['contribution_visible'] = contribution_visible(p.get('created_at'), warning, tracked, account)
        else:
            warning.append('Katkı görünürlüğü bilinmiyor: GitHub hesabı doğrulanamadı.')
    except (RuntimeError, AttributeError): warning.append('PR okunamadı.')
    return account, '; '.join(warning) or None, pr

def detail(ident):
    owner, repo, number = parse_id(ident); root = f'repos/{owner}/{repo}'
    issue = gh(f'{root}/issues/{number}'); meta = gh(root)
    valid = safe_issue(issue)
    if not valid or valid['id'].lower() != ident.lower() or 'pull_request' in issue or meta.get('private') is not False:
        raise RuntimeError('Issue veya açık depo doğrulanamadı')
    limitations = ['AI politikası incelenmedi; bilinmiyor.', 'Yorum ve bağlantılar sınırlı sayıda okunur.']
    comments = []
    try:
        raw = gh(f'{root}/issues/{number}/comments', {'per_page': 20})
        if not isinstance(raw, list): raise RuntimeError()
        comments = [text(x.get('body'), 500) for x in raw if isinstance(x, dict)]
        if len(raw) == 20: limitations.append('Yorumlar ilk 20 ile sınırlı.')
    except RuntimeError: limitations.append('Yorumlar okunamadı.')
    related = []
    title_query = ' '.join(re.findall(r'[A-Za-z0-9]+', valid['title']))[:100].strip()
    searches = [f'repo:{owner}/{repo} is:pr is:open {number}']
    if title_query: searches.append(f'repo:{owner}/{repo} is:pr is:open in:title "{title_query}"')
    else: limitations.append('Başlıktan PR arama sorgusu oluşturulamadı.')
    for q in searches:
        try:
            found = gh('search/issues', {'q': q, 'per_page': 20})
            if found.get('incomplete_results') is not False or found.get('total_count', 0) > len(found.get('items', [])):
                limitations.append('İlgili PR araması eksik veya sınırlı.')
            for p in found.get('items', []):
                u = p.get('html_url', '')
                if re.fullmatch(r'https://github\.com/' + re.escape(owner) + '/' + re.escape(repo) + r'/pull/[1-9][0-9]*', u, re.I) and not any(x['url'] == u for x in related): related.append({'title': text(p.get('title'), 500), 'url': u})
        except (RuntimeError, AttributeError, TypeError): limitations.append('İlgili PR araması okunamadı.')
    try:
        events = gh(f'{root}/issues/{number}/timeline', {'per_page': 20})
        if not isinstance(events, list): raise RuntimeError()
        for event in events:
            source = event.get('source') or {}
            linked = source.get('issue') or {}
            u = linked.get('html_url', '')
            if linked.get('pull_request') is not None and linked.get('state') == 'open' and re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*', u):
                if not any(x['url'] == u for x in related): related.append({'title': text(linked.get('title'), 500), 'url': u})
        if len(events) == 20: limitations.append('Zaman çizelgesi ilk 20 olayla sınırlı.')
    except (RuntimeError, AttributeError, TypeError): limitations.append('Zaman çizelgesi okunamadı.')
    rules_url = None
    for path in ('CONTRIBUTING.md', '.github/CONTRIBUTING.md', 'docs/CONTRIBUTING.md'):
        try:
            obj = gh(root + '/contents/' + path)
            url = obj.get('html_url')
            if url == f'https://github.com/{owner}/{repo}/blob/{meta.get("default_branch")}/{path}': rules_url = url; break
        except (RuntimeError, AttributeError): pass
    if not rules_url: limitations.append('Katkı kuralları konumu doğrulanamadı.')
    limitations.append('Arama ve zaman çizelgesi tüm bağlantılı işleri kapsamayabilir.')
    license_data = meta.get('license')
    return {'id': valid['id'], 'title': valid['title'], 'url': valid['url'], 'state': text(issue.get('state'), 20), 'assignees': [text(x.get('login'), 100) for x in issue.get('assignees', []) if isinstance(x, dict)], 'updated_at': valid['updated_at'], 'author': text(issue['user']['login'], 100) if isinstance(issue.get('user'), dict) and isinstance(issue['user'].get('login'), str) else None, 'created_at': text(issue['created_at'], 50) if isinstance(issue.get('created_at'), str) else None, 'body_text': text(issue.get('body'), 12000), 'comment_summary': comments, 'open_related_prs': related, 'rules_url': rules_url, 'ai_policy': 'bilinmiyor', 'license': text(license_data.get('spdx_id'), 100) if isinstance(license_data, dict) else None, 'limitations': limitations, 'checked_at': now(), 'source_sha': None}

class Store:
    def __init__(self, directory):
        directory = Path(directory)
        if directory.exists() and (directory.is_symlink() or not directory.is_dir() or (hasattr(directory, 'is_junction') and directory.is_junction())): raise RuntimeError('Veri dizini güvenli değil')
        directory.mkdir(exist_ok=True)
        self.path = directory / 'radar.sqlite'
        if self.path.is_symlink() or (hasattr(self.path, 'is_junction') and self.path.is_junction()): raise RuntimeError('Veritabanı güvenli değil')
        existing = self.path.exists()
        with closing(self.connect()) as db, db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RuntimeError('Veritabanı bozuk')
            if not existing:
                db.execute('CREATE TABLE selection (singleton INTEGER PRIMARY KEY CHECK(singleton=1), issue_id TEXT, revision INTEGER NOT NULL)')
                db.execute('INSERT INTO selection VALUES (1,NULL,0)')
            else:
                rows = db.execute('SELECT issue_id, revision FROM selection WHERE singleton=1').fetchall()
                self._validate(rows)
    @staticmethod
    def _validate(rows):
        if len(rows) != 1 or type(rows[0][1]) is not int or rows[0][1] < 0: raise RuntimeError('Seçim verisi bozuk')
        if rows[0][0] is not None:
            try: parse_id(rows[0][0])
            except ValueError as exc: raise RuntimeError('Seçim verisi bozuk') from exc
    def connect(self):
        return sqlite3.connect(self.path, timeout=10)
    def selection(self):
        with closing(self.connect()) as db, db:
            rows = db.execute('SELECT issue_id,revision FROM selection WHERE singleton=1').fetchall()
            self._validate(rows)
            row = rows[0]
            return {'issue_id': row[0], 'revision': row[1]}
    def select(self, ident, revision):
        parse_id(ident)
        if type(revision) is not int or revision < 0: raise ValueError('Geçersiz sürüm')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._validate(db.execute('SELECT issue_id,revision FROM selection WHERE singleton=1').fetchall())
            result = db.execute('UPDATE selection SET issue_id=?, revision=revision+1 WHERE singleton=1 AND revision=?', (ident, revision))
            if result.rowcount != 1: raise Conflict()
            return {'issue_id': ident, 'revision': revision+1}

class Conflict(Exception): pass
