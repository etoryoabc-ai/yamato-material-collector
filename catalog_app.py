"""Local image library. File snapshot works offline; localhost server persists selections."""
import functools
import hmac
import json
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML=r'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>大和噺｜素材カタログ</title>
<style>
:root{color-scheme:dark;--bg:#14191a;--panel:#202729;--ink:#f0ede4;--muted:#aab9b8;--accent:#d7b67d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,"Yu Gothic",sans-serif}header{padding:30px 4vw 20px;border-bottom:1px solid #4c5554}header small{color:var(--accent);letter-spacing:.18em}h1{font-family:serif;font-size:30px;margin:9px 0}p{line-height:1.7}#stats{display:flex;gap:12px;flex-wrap:wrap}.stat{padding:12px 20px;background:var(--panel);border-radius:6px}.stat b{font-size:25px;display:block;color:var(--accent)}.tools{position:sticky;top:0;z-index:2;background:#14191af5;padding:15px 4vw;display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid #465453}input,select,button{padding:9px;border:1px solid #61706e;border-radius:4px;background:#202b2c;color:var(--ink);font:inherit}button{cursor:pointer}button:hover,button.selected{background:var(--accent);color:#151919}button:disabled{opacity:.45;cursor:default}#q{flex:1;min-width:170px}main{padding:0 4vw 40px}.scene{margin:28px 0}.scene h2{font-size:23px}.excerpt{border-left:3px solid var(--accent);padding:10px 18px;white-space:pre-wrap;background:#1b2223}.analysis{color:var(--muted);font-size:13px;white-space:pre-wrap}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}.card{background:var(--panel);border:1px solid #465452;border-radius:8px;overflow:hidden}.preview{width:100%;height:210px;object-fit:contain;background:#101414;cursor:zoom-in}.placeholder{height:210px;display:grid;place-content:center;color:var(--muted);padding:20px;text-align:center}.body{padding:16px}.body h3{font-size:17px;line-height:1.5;margin:8px 0}.badge{display:inline-block;font-size:12px;background:#364844;padding:4px 7px;border-radius:3px;margin-right:6px}.warn{background:#615034}.score{color:var(--accent);font-size:14px}a{color:#d9c18e}details{margin:12px 0;color:var(--muted);font-size:13px}details p{white-space:pre-wrap;overflow-wrap:anywhere}.choices{display:flex;gap:6px}.choices button{flex:1}#notice{padding:8px 4vw;color:var(--accent);white-space:pre-wrap}dialog{max-width:95vw;max-height:95vh;background:#151919;color:white;border:1px solid #aaa}dialog img{max-width:88vw;max-height:78vh;object-fit:contain}#empty{padding:35px;background:var(--panel)}.short{color:#e4ba83}footer{padding:20px 4vw;color:var(--muted);font-size:13px}
</style></head><body><header><small>大和噺 / VISUAL RESEARCH</small><h1>原稿から、映像の手がかりへ。</h1><p>資料を見比べて「採用」を選び、最後に編集用フォルダへ書き出してください。</p><div id="stats"></div></header>
<div class="tools"><input id="q" placeholder="資料名・原稿・作者で絞り込み" aria-label="検索"><select id="scene" aria-label="シーン"><option value="">全シーン</option></select><select id="rights" aria-label="利用条件"><option value="">すべての利用条件</option><option>PD</option><option>CC0</option><option>CC BY</option><option>要確認</option></select><select id="decision" aria-label="採否"><option value="">すべての採否</option><option>採用</option><option>保留</option><option>不採用</option></select><select id="sort" aria-label="並び替え"><option value="script">原稿順＋おすすめ順</option><option value="score">おすすめ順（全シーン）</option></select><button id="export">採用画像を書き出す</button><button id="save">選択をJSON保存</button></div><div id="notice" role="status"></div><main id="main"></main><footer>PD・CC0・CC BYは出典APIによる自動分類です。法的・史実的な最終確認完了ではありません。制作年代と描写年代、原資料・復元図・現代写真の区別を出典で確認してください。</footer><dialog id="zoom"><button id="close">閉じる</button><br><img id="big" alt="拡大資料"></dialog>
<script id="data" type="application/json">__DATA__</script><script>
'use strict';
const D=JSON.parse(document.getElementById('data').textContent), $=id=>document.getElementById(id), live=location.protocol==='http:', token=new URLSearchParams(location.search).get('token')||'', storageKey='yamato04:'+D.run_id;
const scenes=Object.fromEntries(D.scenes.map(s=>[s.id,s]));let choices={...D.choices},saving=Promise.resolve();
if(!live){try{Object.assign(choices,JSON.parse(localStorage.getItem(storageKey)||'{}'))}catch(e){}}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notice(t){$('notice').textContent=t}
function assetPath(p){return p.split('/').map(encodeURIComponent).join('/')}
function sourceLink(url,label){const n=el('a',label);try{if(new URL(url).protocol==='https:')n.href=url}catch(e){}n.target='_blank';n.rel='noopener noreferrer';return n}
async function api(path,payload){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Catalog-Token':token},body:JSON.stringify(payload)});const data=await r.json();if(!r.ok)throw Error(data.error||'保存失敗');return data}
async function choose(id,value){const old=choices[id]||'保留';choices[id]=value;render();try{if(live)await api('/api/choice',{id,value});else localStorage.setItem(storageKey,JSON.stringify(choices));notice(live?'選択を保存しました。最後に「採用画像を書き出す」を押してください。':'オフライン選択をブラウザに保存しました。JSON保存→アプリで選択JSON読込から書き出せます。')}catch(e){choices[id]=old;render();notice('保存できませんでした: '+e.message)}}
function card(link){const a=D.assets[link.asset_id],c=el('article',undefined,'card'),imgpath=a.thumbnail||a.original;
 if(imgpath){const image=el('img');image.className='preview';image.loading='lazy';image.src=assetPath(imgpath);image.alt=a.title;image.onclick=()=>{$('big').src=assetPath(a.original||imgpath);$('zoom').showModal()};c.append(image)}else c.append(el('div',a.rights==='要確認'?'利用条件が未確定のため画像未取得。出典ページで確認してください。':a.download_status,'placeholder'));
 const body=el('div',undefined,'body');body.append(el('span',a.rights+' / 最終確認未了','badge'+(a.rights==='要確認'?' warn':'')),el('span','おすすめ '+link.score,'score'),el('h3',a.title),el('p',a.artist+' / '+a.date),sourceLink(a.source,'出典を開く'));
 const why=el('p',link.reason,'analysis');body.append(why);
 const details=el('details');details.append(el('summary','説明・利用条件・クレジット'));
 for(const [label,value] of [['素材ID',a.id],['所蔵',a.institution],['API資料種別',a.object_type],['説明',a.description],['ライセンス',a.license],['条件',a.conditions],['クレジット案',a.credit],['画素数',a.width+' × '+a.height],['取得',a.download_status],['史実注意',link.notes],['おすすめ根拠',link.inference]])details.append(el('p',label+'：'+value));
 if(a.license_url)details.append(sourceLink(a.license_url,'利用条件の原文'));body.append(details);
 const buttons=el('div',undefined,'choices');for(const value of ['採用','保留','不採用']){const b=el('button',value);b.className=(choices[link.id]||'保留')===value?'selected':'';b.onclick=()=>{saving=saving.then(()=>choose(link.id,value))};buttons.append(b)}body.append(buttons);c.append(body);return c}
function render(){const main=$('main');main.replaceChildren();const q=$('q').value.toLocaleLowerCase();let links=D.links.filter(l=>{const a=D.assets[l.asset_id],s=scenes[l.scene_id];return (!$('scene').value||l.scene_id===$('scene').value)&&(!$('rights').value||a.rights===$('rights').value)&&(!$('decision').value||(choices[l.id]||'保留')===$('decision').value)&&(!q||[a.title,a.artist,a.description,s.text].join(' ').toLocaleLowerCase().includes(q))});
 if($('sort').value==='score'){links.sort((a,b)=>b.score-a.score);const grid=el('div',undefined,'grid');for(const l of links){const c=card(l);c.querySelector('.body').prepend(el('p',l.scene_id+' '+scenes[l.scene_id].topic));grid.append(c)}main.append(grid)}else{
 for(const s of D.scenes){if($('scene').value&&$('scene').value!==s.id)continue;const group=links.filter(l=>l.scene_id===s.id);if(!group.length&&q)continue;const section=el('section',undefined,'scene');section.append(el('h2',s.id+'　'+s.topic),el('p',s.text,'excerpt'),el('p',s.analysis+'\n人物: '+(s.people.join('・')||'不明')+' / 場所: '+(s.places.join('・')||'不明')+' / 時代: '+s.period+'\n画像: '+s.image_types.join('・'),'analysis'));
 const all=D.links.filter(l=>l.scene_id===s.id).length;if(all<s.quota)section.append(el('p','候補不足 '+(s.quota-all)+'枚（目標 '+s.quota+' / 候補 '+all+'）','short'));
 const grid=el('div',undefined,'grid');for(const l of group.sort((a,b)=>b.score-a.score))grid.append(card(l));section.append(grid);main.append(section)}}
 if(!links.length)main.append(el('p','表示できる候補がありません。収集レポートの接続結果・不足シーンを確認してください。','placeholder'));
 $('stats').replaceChildren();const stats=[['全体目標',D.target],['API発見',D.raw_discovered],['関連候補',Object.keys(D.assets).length],['原本取得',Object.values(D.assets).filter(a=>a.original).length],['条件分類可(API)',Object.values(D.assets).filter(a=>['PD','CC0','CC BY'].includes(a.rights)).length],['採用',Object.values(choices).filter(x=>x==='採用').length]];
 for(const [label,value]of stats){const item=el('div',undefined,'stat');item.append(el('b',value),el('span',label));$('stats').append(item)}}
for(const s of D.scenes){const o=el('option',s.id+' '+s.topic);o.value=s.id;$('scene').append(o)}
for(const id of ['q','scene','rights','decision','sort'])$(id).addEventListener('input',render);
$('close').onclick=()=>$('zoom').close();
$('save').onclick=()=>{const blob=new Blob([JSON.stringify({run_id:D.run_id,choices},null,2)],{type:'application/json'});const a=el('a');a.href=URL.createObjectURL(blob);a.download='素材選択_'+D.run_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$('export').onclick=async()=>{if(!live){notice('「選択をJSON保存」で保存し、アプリの「選択JSON読込・書き出し」を使ってください。');return}try{$('export').disabled=true;await saving;const data=await api('/api/export',{});notice('書き出し '+data.copied+'枚 / 未取得等で書き出せない採用 '+data.not_exportable.length+'件\n'+data.folder)}catch(e){notice('書き出し失敗: '+e.message)}finally{$('export').disabled=false}};
notice(D.analysis+'。'+(live?'選択はこの結果フォルダへ保存されます。':'ファイル表示：選択はブラウザ内保存。編集用書き出しは起動.batで結果を開いて行えます。'));render();
</script></body></html>'''

def render_catalog(out,manifest):
    encoded=json.dumps(manifest,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    Path(out,'素材カタログ.html').write_text(HTML.replace('__DATA__',encoded),encoding='utf-8')

class CatalogServer:
    def __init__(self,folder):
        from material_assistant import EXPORT_LOCK
        self.folder=Path(folder).resolve();self.token=secrets.token_urlsafe(32);self.lock=EXPORT_LOCK
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def valid_host(self):return self.headers.get('Host')==owner.origin.removeprefix('http://')
            def reply(self,code,obj):
                data=json.dumps(obj,ensure_ascii=False).encode('utf-8');self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if not self.valid_host():self.reply(403,{'error':'Host rejected'});return
                path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip('/') or '素材カタログ.html'
                file=(owner.folder/path).resolve()
                if not file.is_relative_to(owner.folder) or not file.is_file() or file.suffix.lower() not in ('.html','.jpg','.jpeg','.png'):
                    self.reply(404,{'error':'Not found'});return
                body=file.read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8' if file.suffix=='.html' else 'image/png' if file.suffix=='.png' else 'image/jpeg');self.send_header('Content-Length',str(len(body)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(body)
            def do_POST(self):
                if not self.valid_host() or self.headers.get('Origin')!=owner.origin or not hmac.compare_digest(self.headers.get('X-Catalog-Token',''),owner.token):self.reply(403,{'error':'このアプリで開いたカタログから操作してください'});return
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=100_000:raise ValueError('入力サイズ不正')
                    data=json.loads(self.rfile.read(length));route=urllib.parse.urlsplit(self.path).path
                    with owner.lock:
                        from material_assistant import persist,export_adopted
                        m=json.loads((owner.folder/'catalog.json').read_text(encoding='utf-8'))
                        if route=='/api/choice':
                            ids={x['id'] for x in m['links']}
                            if data.get('id') not in ids or data.get('value') not in ('採用','保留','不採用'):raise ValueError('採否指定が不正')
                            m['choices'][data['id']]=data['value'];persist(owner.folder,m);result={'saved':True}
                        elif route=='/api/export':result=export_adopted(owner.folder,m)
                        else:self.reply(404,{'error':'Not found'});return
                    self.reply(200,result)
                except Exception as e:self.reply(400,{'error':str(e)})
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.http.daemon_threads=True
        self.origin='http://127.0.0.1:'+str(self.http.server_port)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    @property
    def url(self):return self.origin+'/?token='+self.token
    def close(self):self.http.shutdown();self.http.server_close()

def import_choices(folder,path):
    from material_assistant import persist, export_adopted
    folder=Path(folder);m=json.loads((folder/'catalog.json').read_text(encoding='utf-8'));data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('run_id')!=m['run_id']:raise ValueError('別の実行結果の選択ファイルです')
    if not isinstance(data.get('choices'),dict):raise ValueError('選択データが不正です')
    ids={x['id'] for x in m['links']}
    if any(k not in ids or v not in ('採用','保留','不採用') for k,v in data['choices'].items()):raise ValueError('未登録の素材IDまたは採否')
    m['choices'].update(data['choices']);persist(folder,m);return export_adopted(folder,m)
