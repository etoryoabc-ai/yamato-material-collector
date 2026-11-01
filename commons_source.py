"""Documented read-only Action API client; media/website rules are separate."""
import gzip
import hashlib
import html
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

UNKNOWN='不明'
API='https://commons.wikimedia.org/w/api.php'
MEDIA_HOSTS={'upload.wikimedia.org','thumb.wikimedia.org'}
HOSTS={'commons.wikimedia.org',*MEDIA_HOSTS}
POLICY='https://wikitech.wikimedia.org/wiki/Robot_policy#Action_API_rules'

class Source(Protocol):
    name:str
    def search(self,query:str,limit:int): ...
    def download(self,url:str,path:Path): ...

class AccessDenied(RuntimeError):pass


def plain(value):
    return html.unescape(re.sub(r'<[^>]*>',' ',str(value))).strip() or UNKNOWN


def safe_url(url, hosts=None):
    if not isinstance(url,str):return ''
    try:
        p=urllib.parse.urlsplit(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443) or p.fragment:return ''
        if hosts and p.hostname not in hosts:return ''
    except ValueError:return ''
    return url if not any(ord(c)<32 for c in url) else ''


def request_kind(url):
    """Only the documented JSON siteinfo/search+imageinfo API, not /w/* crawling.

    API Usage Guidelines + Robot policy / Action API rules govern these bounded,
    user-initiated calls. No generic robots-off option, edits, parse, or HTML APIs.
    """
    if not safe_url(url,HOSTS):raise AccessDenied('URLが許可ホスト外またはHTTPSではありません')
    p=urllib.parse.urlsplit(url)
    if p.path=='/robots.txt' and not p.query:return 'robots'
    if p.hostname=='commons.wikimedia.org' and p.path=='/w/api.php':
        pairs=urllib.parse.parse_qsl(p.query,keep_blank_values=True)
        q=dict(pairs)
        if len(q)!=len(pairs):raise AccessDenied('APIパラメータ重複を拒否')
        allowed={'action','format','maxlag','meta','siprop','generator','gsrsearch','gsrnamespace','gsrlimit','prop','iiprop','iiurlwidth','iiextmetadatalanguage'}
        if set(q)-allowed or q.get('action')!='query' or q.get('format')!='json':raise AccessDenied('許可された読み取り専用JSON APIではありません')
        if q.get('maxlag','5')!='5':raise AccessDenied('API maxlagは5に固定')
        if q.get('meta')=='siteinfo' and set(q)<= {'action','format','maxlag','meta','siprop'} and q.get('siprop','general')=='general':return 'action-api'
        try:limit=int(q.get('gsrlimit','0'))
        except ValueError:limit=0
        props=set(q.get('iiprop','').split('|'))
        if (q.get('generator')=='search' and q.get('gsrnamespace')=='6' and 1<=limit<=30 and q.get('prop')=='imageinfo'
            and 0<len(q.get('gsrsearch',''))<=500 and props and props<={'url','size','extmetadata','sha1','mime'} and not q.get('meta')
            and q.get('iiurlwidth','330') in ('250','330','500') and q.get('iiextmetadatalanguage','ja') in ('ja','en')):
            return 'action-api'
        raise AccessDenied('検索・画像メタデータ以外のAPI要求を拒否')
    if p.hostname in MEDIA_HOSTS and p.path.startswith('/wikipedia/commons/'):
        tracking=urllib.parse.parse_qsl(p.query,keep_blank_values=True)
        if all(k in {'utm_source','utm_campaign','utm_content','utm_medium','utm_term'} for k,v in tracking) and len({k for k,v in tracking})==len(tracking):return 'media'
    raise AccessDenied('未許可のリソース用途: '+p.hostname+p.path)

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        # Do not let an unexpected redirect change the operation/host or access policy.
        if request_kind(newurl)!=request_kind(req.full_url) or urllib.parse.urlsplit(newurl).hostname!=urllib.parse.urlsplit(req.full_url).hostname:
            raise AccessDenied('異なるホスト・用途への転送を拒否')
        # Media redirects need a fresh robots decision; do not silently follow them.
        if request_kind(newurl)=='media':raise AccessDenied('画像URLの転送を自動追跡せず記録')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def retry_delay(value,attempt):
    base=5*(2**attempt)
    if not value:return base
    try:delay=float(value)
    except ValueError:
        try:delay=(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds()
        except (TypeError,ValueError):raise AccessDenied('Retry-Afterを解釈できないため停止') from None
    return max(base,delay,0)

class CommonsSource:
    name='Wikimedia Commons'
    def __init__(self, evidence, agent, progress=lambda text:None, delay=1.1):
        self.evidence=Path(evidence);self.evidence.mkdir(parents=True,exist_ok=True)
        if not agent or any(ord(c)<32 for c in agent):raise ValueError('説明的なUser-Agentが必要')
        self.agent=agent;self.progress=progress;self.delay=max(1.1,delay);self.last=0;self.next_allowed=0;self.robots={};self.log=[];self.halted=None
        self.opener=urllib.request.build_opener(SafeRedirect())
        (self.evidence/'アクセス方針.json').write_text(json.dumps({'version':'0.5','api':API,'api_scope':'action=query JSON: siteinfo or namespace 6 search + imageinfo only','api_guideline':POLICY,'robots_scope':'Media downloads, not website crawler preflight on documented Action API calls','user_agent':agent,'parallel_requests':1,'interval_seconds':self.delay,'slow_api_cooldown_seconds':5,'media_limit_bytes_per_second':2_000_000},ensure_ascii=False,indent=2),encoding='utf-8')
    def record(self,**fields):
        with (self.evidence/'通信ログ.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),**fields},ensure_ascii=False)+'\n')
    def fetch(self,url,limit=5_000_000):
        if self.halted:raise AccessDenied(self.halted)
        try:kind=request_kind(url)
        except AccessDenied as e:
            self.record(url=url,status='local_url_denied',error=str(e));raise
        if kind=='media':
            parser=self.robot_rules(urllib.parse.urlsplit(url).hostname)
            if not parser.can_fetch('YamatoMaterialsBot',url):
                self.record(kind=kind,url=url,status='local_media_robots_denied')
                raise AccessDenied('画像URLがrobots.txtにより取得対象外')
        for attempt in range(3):
            time.sleep(max(0,self.last+self.delay-time.monotonic(),self.next_allowed-time.monotonic()));self.last=time.monotonic()
            headers={'User-Agent':self.agent}
            if kind!='media':headers['Accept-Encoding']='gzip'
            req=urllib.request.Request(url,headers=headers);start=time.monotonic()
            try:
                with self.opener.open(req,timeout=30) as r:
                    chunks=[];length=0
                    while True:
                        chunk=r.read(min(65536,limit+1-length))
                        if not chunk:break
                        chunks.append(chunk);length+=len(chunk)
                        if length>limit:raise ValueError('応答サイズ上限超過')
                        if kind=='media':time.sleep(max(0,length/2_000_000-(time.monotonic()-start)))
                    body=b''.join(chunks)
                    if r.headers.get('Content-Encoding','').lower()=='gzip':
                        with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:body=compressed.read(limit+1)
                        if len(body)>limit:raise ValueError('gzip展開後サイズ上限超過')
                elapsed=time.monotonic()-start
                if kind=='action-api' and elapsed>1:self.next_allowed=time.monotonic()+5
                self.record(kind=kind,url=url,status='success',bytes=len(body),elapsed_seconds=round(elapsed,3),attempt=attempt+1)
                return body
            except urllib.error.HTTPError as e:
                self.record(kind=kind,url=url,status='http_error',http_status=e.code,retry_after=e.headers.get('Retry-After',''),attempt=attempt+1)
                if e.code in (401,403):
                    self.halted=f'HTTP {e.code}: サーバーが拒否。停止（別経路・UA変更で再試行しない）'
                    raise AccessDenied(self.halted) from None
                if e.code in (429,503):
                    wait=retry_delay(e.headers.get('Retry-After',''),attempt)
                    if attempt==2 or wait>30:
                        self.halted=f'HTTP {e.code}: {wait:.0f}秒以上待機が必要。今回は停止し後で再実行'
                        raise AccessDenied(self.halted) from None
                    self.progress(f'HTTP {e.code}: {wait:.0f}秒待機');time.sleep(wait);continue
                if e.code>=500:raise AccessDenied(f'HTTP {e.code}: サーバー障害のため停止') from None
                raise
            except Exception as e:
                self.record(kind=kind,url=url,status='error',error=type(e).__name__+': '+str(e),attempt=attempt+1)
                raise
        raise AccessDenied('取得再試行回数超過のため停止')
    def robot_rules(self,host):
        if host not in HOSTS:raise AccessDenied('robotsホスト不正')
        if host in self.robots:return self.robots[host]
        url='https://'+host+'/robots.txt';parser=urllib.robotparser.RobotFileParser(url)
        try:raw=self.fetch(url,500_000)
        except urllib.error.HTTPError as e:
            if e.code==404:raw=b'User-agent: *\nAllow: /'
            else:raise
        parser.parse(raw.decode('utf-8-sig').splitlines());(self.evidence/(host+'_robots.txt')).write_bytes(raw)
        self.robots[host]=parser
        crawl=parser.crawl_delay('YamatoMaterialsBot')
        if crawl:self.delay=max(self.delay,crawl)
        rate=parser.request_rate('YamatoMaterialsBot')
        if rate:self.delay=max(self.delay,rate.seconds/rate.requests)
        return parser
    def query(self,params):
        params={'action':'query','format':'json','maxlag':5,**params}
        url=API+'?'+urllib.parse.urlencode(params);request_kind(url)
        cache=self.evidence/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if cache.exists():return json.loads(cache.read_text(encoding='utf-8'))
        for attempt in range(3):
            raw=self.fetch(url);data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('API応答がオブジェクトではありません')
            error=data.get('error',{})
            if error:
                code=plain(error.get('code','unknown'));self.record(kind='action-api',url=url,status='api_error',api_code=code)
                if code in ('maxlag','ratelimited'):
                    if attempt==2:raise AccessDenied('API '+code+': 待機後も解消せず停止')
                    wait=5*(2**attempt);self.progress(f'API {code}: {wait}秒待機');time.sleep(wait);continue
                raise RuntimeError('APIエラー: '+code)
            cache.write_bytes(raw);return data
        raise AccessDenied('API負荷状態が解消しません')
    def probe(self):
        return self.query({'meta':'siteinfo','siprop':'general'}).get('query',{}).get('general',{})
    def search(self,query,limit=12):
        # Same read-only generator/search + imageinfo route as v0.3.
        params={'generator':'search','gsrsearch':query+' filetype:bitmap','gsrnamespace':6,'gsrlimit':min(limit,30),'prop':'imageinfo','iiprop':'url|size|extmetadata|sha1|mime','iiurlwidth':330,'iiextmetadatalanguage':'ja'}
        result=self.query(params);pages=result.get('query',{}).get('pages',{})
        if not isinstance(pages,dict):raise ValueError('API pages形式不正')
        self.log.append({'query':query,'count':len(pages),'warnings':result.get('warnings',{})})
        records=[]
        for p in pages.values():
            if not isinstance(p,dict) or not p.get('imageinfo'):continue
            try:records.append(metadata(p))
            except (KeyError,ValueError,TypeError) as e:self.record(kind='metadata',status='invalid_record',pageid=p.get('pageid'),error=str(e))
        return records
    def download(self,url,path):
        if not safe_url(url,MEDIA_HOSTS):raise AccessDenied('画像ホストを検証できません')
        try:data=self.fetch(url,80*1024*1024)
        except AccessDenied as e:raise AccessDenied(str(e)+' [画像URL: '+url+']') from None
        ext='.jpg' if data.startswith(b'\xff\xd8\xff') else '.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else ''
        if not ext:raise ValueError('原本形式がJPEG/PNGではありません（変換しません）')
        p=Path(str(path)+ext);p.parent.mkdir(parents=True,exist_ok=True)
        temp=p.with_suffix(p.suffix+'.part');temp.write_bytes(data);temp.replace(p)
        return p,hashlib.sha256(data).hexdigest()

def classify(m, source):
    v=lambda k:plain(m.get(k,{}).get('value',''))
    name=v('LicenseShortName');licurl=v('LicenseUrl');usage=v('UsageTerms');artist=v('Artist')
    combined=(name+' '+usage).lower()
    if any(x in combined for x in ('noncommercial','non-commercial','by-nc','by-nd','fair use','all rights reserved')):
        return '対象外','商用利用不可・改変制限等のため自動取得対象外'
    if v('NonFree').lower()=='true' or v('Restrictions')!=UNKNOWN:return '要確認','追加制限・矛盾する権利情報あり'
    if not safe_url(source,{'commons.wikimedia.org'}):return '要確認','出典ページが不明'
    if name=='Public domain' and v('Copyrighted').lower()=='false':return 'PD','APIにパブリックドメイン・非著作権表示あり。国別条件等の最終確認は別途'
    if name=='CC0' and re.fullmatch(r'https?://creativecommons\.org/publicdomain/zero/1\.0/?',licurl):return 'CC0','APIにCC0表示と正規条件URLあり'
    match=re.fullmatch(r'CC BY (1\.0|2\.0|2\.5|3\.0|4\.0)',name)
    if match and re.fullmatch(r'https?://creativecommons\.org/licenses/by/'+re.escape(match[1])+r'/(?:deed\.[a-z_-]+)?',licurl) and artist!=UNKNOWN:
        return 'CC BY','帰属表示・ライセンスリンク・変更表示が必要。API情報の最終確認は別途'
    return '要確認','許可対象ライセンス・正規URL・必要情報を機械判定できません（CC BY-SA等も保留）'

def metadata(page):
    i=page['imageinfo'][0];m=i.get('extmetadata',{});v=lambda k:plain(m.get(k,{}).get('value',''))
    source=safe_url(i.get('descriptionurl',''),{'commons.wikimedia.org'})
    rights,conditions=classify(m,source)
    title=plain(page.get('title',UNKNOWN)).removeprefix('File:')
    license_url=safe_url(v('LicenseUrl').replace('http://creativecommons.org/','https://creativecommons.org/'))
    # Raw values remain in API JSON; plain text is displayed without executing metadata HTML.
    credit=' / '.join(x for x in [v('Artist'),title,v('Credit'),v('Attribution'),v('LicenseShortName'),license_url,source,'原本無改変（編集時は変更内容の表示を確認）'] if x and x!=UNKNOWN)
    return {'id':'WC'+str(page['pageid']),'title':title,'institution':v('Institution'),'artist':v('Artist'),'date':v('DateTimeOriginal'),
      'description':v('ImageDescription'),'object_type':v('ObjectType'),'source':source,'original_url':safe_url(i.get('url',''),{'upload.wikimedia.org'}),
      'thumbnail_url':safe_url(i.get('thumburl',''),MEDIA_HOSTS),'license':v('LicenseShortName'),'license_url':license_url,
      'credit':credit,'rights':rights,'conditions':conditions,'sha1':i.get('sha1',''),'width':i.get('width',0),'height':i.get('height',0),
      'mime':i.get('mime',UNKNOWN),'original':'','thumbnail':'','download_status':'未取得','history_status':'未確認','kind':'不明（APIの資料種別を参照）','evidence':'Commons APIメタデータ（内容の真偽・権利の最終確認ではない）'}

def relevance(scene, asset):
    text=(asset['title']+' '+asset['description']).casefold()
    # Specific scene cues required; no quota-filling using unrelated search hits.
    terms=list(dict.fromkeys(t.casefold().strip() for t in scene['visual_terms'] if len(t.strip())>=2))
    hits=[t for t in terms if (re.search(r'(?<![a-z])'+re.escape(t)+r'(?![a-z])',text) if re.fullmatch('[a-z ]+',t) else t in text)]
    if not hits:return None
    score=min(75,35+12*len(hits))
    score+=10 if asset['rights'] in ('PD','CC0','CC BY') else 0
    score+=5 if max(asset['width'] or 0,asset['height'] or 0)>=1800 else 0
    notes=['描写年代・原資料/復刻/復元/現代写真の区別は未確認']
    years=re.findall(r'(?<!\d)(1[6-9]\d{2}|20\d{2})(?!\d)',asset['date'])
    if ('江戸' in scene['period'] or 'Edo' in scene['period']) and years and all(int(y)>1868 for y in years):
        score-=25;notes.append('制作年代表示が江戸時代以後。複製年代・復元図・現代写真等か要確認')
    if re.search(r'photograph|photo of|taken in|現代|復元',text):
        score-=10;notes.append('写真・復元等の語あり。当時の原資料と断定しない')
    return {'score':max(score,1),'reason':'説明文・資料名との一致: '+', '.join(hits[:7])+'。'+scene['reason'],
      'notes':' / '.join(notes),'inference':'おすすめ度は語句一致・解像度・権利情報による推定。画像内容をAIが確認した値ではない'}
