"""Wikimedia contact URL validation and descriptive HTTP User-Agent."""
import json
import re
import urllib.parse
from pathlib import Path

VERSION = '0.4'
POLICY_URL = 'https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy'
PROJECT_URL = 'https://github.com/etoryoabc-ai/yamato-material-collector'
HOST_PATTERN = re.compile(r'(?:[a-z0-9-]+\.)+(?:wikimedia\.org|wikipedia\.org|wiktionary\.org|wikibooks\.org|wikinews\.org|wikiquote\.org|wikisource\.org|wikiversity\.org|wikivoyage\.org)|(?:www\.)?(?:wikidata\.org|mediawiki\.org)')

def normalize_user_page(value):
    """Accept HTTPS /wiki/User:... or /wiki/利用者:... on known Wikimedia domains.

    Validates syntax only; does not establish ownership or that a page exists.
    Returns an ASCII URL safe for an HTTP header comment.
    """
    value = value.strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('WikimediaユーザーページURLを入力してください。制御文字は使えません。')
    p = urllib.parse.urlsplit(value)
    if p.scheme != 'https' or not p.hostname or not HOST_PATTERN.fullmatch(p.hostname.lower()):
        raise ValueError('Wikimedia公式サイトのHTTPSユーザーページURLを入力してください。')
    if p.username or p.password or p.netloc.lower() != p.hostname.lower() or p.query or p.fragment:
        raise ValueError('認証情報・ポート・クエリ・#以降を含まないURLを入力してください。')
    path = urllib.parse.unquote(p.path, encoding='utf-8', errors='strict')
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or '%' in path:
        raise ValueError('URLの文字コードが不正です。ブラウザのユーザーページURLをコピーしてください。')
    match = re.fullmatch(r'/wiki/(?:User|利用者):([^/]+)', path, re.IGNORECASE)
    if not match or not match[1].strip() or ':' in match[1]:
        raise ValueError('例: https://commons.wikimedia.org/wiki/User:あなたの利用者名 （利用者本人のページ）')
    # Parentheses are percent-encoded: they cannot terminate the UA contact comment.
    return 'https://' + p.hostname.lower() + urllib.parse.quote('/wiki/User:' + match[1], safe='/:_-.~')

def build_user_agent(user_page):
    return f'YamatoMaterialsBot/{VERSION} ({normalize_user_page(user_page)}; {PROJECT_URL})'

def saved_user_page(policy):
    """Migrate a legacy URL only. A legacy email is never displayed or reused."""
    try:
        return normalize_user_page(policy.get('wikimedia_user_page_url') or policy.get('contact', ''))
    except (ValueError, UnicodeError):
        return ''

def save_policy(path, policy, user_page):
    """Persist new URL atomically, preserving unrelated settings; remove legacy contact."""
    result = dict(policy)
    result.pop('contact', None)
    result['wikimedia_user_page_url'] = normalize_user_page(user_page)
    result['user_agent'] = build_user_agent(user_page)
    result['user_agent_policy_url'] = POLICY_URL
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    return result
