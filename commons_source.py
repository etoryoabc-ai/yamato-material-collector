"""Replaceable source adapter. Public API only; bounded, sequential, cached requests."""
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from typing import Protocol

UNKNOWN='不明'
API='https://commons.wikimedia.org/w/api.php'
HOSTS={'commons.wikimedia.org','upload.wikimedia.org'}

class Source(Protocol):
    name:str
    def search(self,query:str,limit:int): ...
    def download(self,url:str,path:Path): ...

class AccessDenied(RuntimeError):pass

def plain(value):
    return html.unescape(re.sub(r'<[^>]*>',' ',str(value))).strip() or UNKNOWN

def safe_url(url, hosts=None):
    if not isinstance(url,str):return ''
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return ''
    if hosts and p.hostname not in hosts:return ''
    return url if not any(ord(c)<32 for c in url) else ''

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not safe_url(newurl,HOSTS):raise AccessDenied('許可ホスト外への転送を拒否')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class CommonsSource:
    name='Wikimedia Commons'
    def __init__(self, evidence, agent, progress=lambda text:None, delay=1.1):
        self.evidence=Path(evidence);self.evidence.mkdir(parents=True,exist_ok=True)
        self.agent=agent;self.progress=progress;self.delay=delay;self.last=0;self.robots={};self.log=[]
        self.opener=urllib.request.build_opener(SafeRedirect())
    def fetch(self,url,limit=5_000_000,robots=True):
        if not safe_url(url,HOSTS):raise AccessDenied('URLが許可ホスト外またはHTTPSではありません')
        host=urllib.parse.urlsplit(url).hostname
        if robots:
            parser=self.robot_rules(host)
            if not parser.can_fetch('YamatoMaterialsBot',url):raise AccessDenied('robots.txtにより取得対象外')
        for attempt in range(3):
            time.sleep(max(0,self.delay-(time.monotonic()-self.last)));self.last=time.monotonic()
            req=urllib.request.Request(url,headers={'User-Agent':self.agent})
            try:
                with self.opener.open(req,timeout=25) as r:
                    body=r.read(limit+1)
                    if len(body)>limit:raise ValueError('応答サイズ上限超過')
                    return body
            except urllib.error.HTTPError as e:
                if e.code in (401,403):raise AccessDenied(f'HTTP {e.code}: 取得を停止（制限回避なし）') from None
                if e.code in (429,503) and attempt<2:
                    header=e.headers.get('Retry-After','')
                    try:wait=max(5*(attempt+1),float(header)) if header else 5*(attempt+1)
                    except ValueError:raise RuntimeError('Retry-Afterの日時指定を受信。今回は停止して後で再実行してください') from None
                    if wait>30:raise RuntimeError(f'Retry-After {wait}秒。自動再試行せず停止') from None
                    self.progress(f'HTTP {e.code}: {wait}秒待って再試行');time.sleep(wait);continue
                raise
        raise RuntimeError('取得再試行回数超過')
    def robot_rules(self,host):
        if host in self.robots:return self.robots[host]
        url='https://'+host+'/robots.txt'; parser=urllib.robotparser.RobotFileParser(url)
        try:raw=self.fetch(url,500_000,robots=False)
        except urllib.error.HTTPError as e:
            if e.code==404:raw=b'User-agent: *\nAllow: /'
            else:raise
        text=raw.decode('utf-8-sig');parser.parse(text.splitlines())
        (self.evidence/(host+'_robots.txt')).write_bytes(raw)
        self.robots[host]=parser
        crawl=parser.crawl_delay('YamatoMaterialsBot')
        if crawl:self.delay=max(self.delay,crawl)
        rate=parser.request_rate('YamatoMaterialsBot')
        if rate:self.delay=max(self.delay,rate.seconds/rate.requests)
        return parser
    def query(self,params):
        params={'action':'query','format':'json','maxlag':5,**params}
        url=API+'?'+urllib.parse.urlencode(params)
        cache=self.evidence/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if cache.exists():return json.loads(cache.read_text(encoding='utf-8'))
        for attempt in range(3):
            raw=self.fetch(url);data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('API応答がオブジェクトではありません')
            if data.get('error',{}).get('code')=='maxlag' and attempt<2:
                self.progress('API maxlag: 5秒待機');time.sleep(5);continue
            if 'error' in data:raise RuntimeError('APIエラー: '+plain(data['error'].get('code','unknown')))
            cache.write_bytes(raw);return data
        raise RuntimeError('API maxlagが解消しません')
    def probe(self):
        return self.query({'meta':'siteinfo','siprop':'general'}).get('query',{}).get('general',{})
    def search(self,query,limit=12):
        params={'generator':'search','gsrsearch':query+' filetype:bitmap','gsrnamespace':6,'gsrlimit':min(limit,30),'prop':'imageinfo','iiprop':'url|size|extmetadata|sha1|mime','iiurlwidth':480,'iiextmetadatalanguage':'ja'}
        result=self.query(params)
        pages=result.get('query',{}).get('pages',{})
        if not isinstance(pages,dict):raise ValueError('API pages形式不正')
        self.log.append({'query':query,'count':len(pages),'warnings':result.get('warnings',{})})
        records=[]
        for p in pages.values():
            if not isinstance(p,dict) or not p.get('imageinfo'):continue
            records.append(metadata(p))
        return records
    def download(self,url,path):
        if not safe_url(url,{'upload.wikimedia.org'}):raise AccessDenied('画像ホストを検証できません')
        data=self.fetch(url,80*1024*1024)
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
      'thumbnail_url':safe_url(i.get('thumburl',''),{'upload.wikimedia.org'}),'license':v('LicenseShortName'),'license_url':license_url,
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
