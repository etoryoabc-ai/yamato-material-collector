"""Python 3.10+ / 標準ライブラリのみ。規約未確認では画像を取得しない。"""
import argparse, csv, hashlib, html, json, re, time, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from user_agent import build_user_agent

UNKNOWN = '不明'
TOPICS = [
 ('01_江戸の町並み',['町並み','名所','町割','地図'],['江戸名所図会','江戸 切絵図'],['Edo meisho zue','Edo map']),
 ('02_江戸の人口と都市規模',['人口','百万','100万','密集'],['江戸 町並み 絵図'],['Edo city panorama']),
 ('03_上水道',['上水','水道','木樋','玉川','神田'],['江戸 神田上水 玉川上水 木樋'],['Tamagawa aqueduct Edo','Kanda aqueduct']),
 ('04_海運と物流',['海運','廻船','河岸','市場','流通','商業','物流'],['江戸 日本橋 魚河岸 浮世絵'],['Hiroshige Nihonbashi fish market','Edo shipping']),
 ('05_ごみと下肥',['ごみ','下肥','肥料','汚物'],['江戸 下肥 ごみ 永代浦'],['Edo night soil waste']),
 ('06_火災と防災',['火災','火消','防災','大火'],['江戸 町火消 火災 錦絵'],['Edo firefighters ukiyo-e']),
 ('07_その他',[],['江戸 史料'],['Edo historical illustration'])]
FIELDS=['素材ID','ファイル名','画像タイトル','所蔵機関','制作者','制作年代','描写対象の年代','資料の種類','出典ページURL','画像URL','ライセンス','クレジット表記','商用利用可否','確認状況','対応する原稿の箇所','採用理由','史実上の注意点','権利根拠URL','確認日時','SHA256','幅','高さ','シーンID','記録区分','判定理由']
SITES={'国立国会図書館デジタルコレクション':'https://dl.ndl.go.jp/','国立国会図書館サーチSRU':'https://ndlsearch.ndl.go.jp/api/sru','国立公文書館':'https://www.digital.archives.go.jp/','東京都立図書館':'https://www.library.metro.tokyo.lg.jp/','Wikimedia Commons':'https://commons.wikimedia.org/w/api.php'}

def plain(s):
 return html.unescape(re.sub('<[^>]*>','',str(s))).strip() or UNKNOWN

def analyze(text):
 scenes=[]; offset=0
 for part in re.split(r'\n\s*\n',text):
  if not part.strip(): continue
  start=text.find(part,offset); offset=start+len(part)
  # 長い段落は文末で分割。文字位置は原文のUnicode文字単位。
  chunks=re.findall(r'.+?(?:[。！？](?=.{180})|$)',part,re.S) or [part]
  pos=start
  for chunk in chunks:
   scores=[sum(chunk.count(k) for k in t[1]) for t in TOPICS]
   indices=[i for i,s in enumerate(scores) if s] or [6]
   scenes.append({'id':f'S{len(scenes)+1:03d}','text':chunk,'start':pos,'end':pos+len(chunk),'folders':[TOPICS[i][0] for i in indices],'ja':sum([TOPICS[i][2] for i in indices],[]),'en':sum([TOPICS[i][3] for i in indices],[])})
   pos+=len(chunk)
 return scenes

class Client:
 def __init__(self, evidence, agent, delay=1.0): self.evidence=evidence; self.agent=agent; self.delay=delay; self.last=0
 def get(self,url,limit=4_000_000):
  if urllib.parse.urlsplit(url).scheme!='https': raise ValueError('HTTPSのみ許可')
  time.sleep(max(0,self.delay-(time.monotonic()-self.last))); self.last=time.monotonic()
  req=urllib.request.Request(url,headers={'User-Agent':self.agent})
  with urllib.request.urlopen(req,timeout=20) as r:
   body=r.read(limit+1)
   if len(body)>limit: raise ValueError('上限サイズ超過')
   return body
 def query(self,params):
  url=SITES['Wikimedia Commons']+'?'+urllib.parse.urlencode(params)
  data=self.get(url); name=hashlib.sha256(url.encode()).hexdigest()+'.json'
  (self.evidence/name).write_bytes(data)
  result=json.loads(data)
  if 'error' in result: raise ValueError(str(result['error']))
  return result

def license_gate(meta):
 """Commonsの機械可読情報を候補判定するだけ。個別根拠と史実確認は別途必須。"""
 val=lambda k: plain(meta.get(k,{}).get('value',''))
 name=val('LicenseShortName'); url=val('LicenseUrl')
 allowed=(name in ('Public domain','CC0') or bool(re.fullmatch(r'CC BY (?:1\.0|2\.0|2\.5|3\.0|4\.0)',name)))
 if val('NonFree').lower()=='true' or val('Restrictions')!=UNKNOWN: allowed=False
 if name.startswith('CC BY') and not url.startswith('https://creativecommons.org/licenses/by/'): allowed=False
 return allowed,name,url

def approved(row, review, policy):
 required=['rights_evidence_url','credit','reviewed_at','reviewer','historical_note','type','depicted_date','reason']
 return bool(policy.get('commons_api_terms_reviewed') is True and policy.get('terms_url') and policy.get('reviewed_at') and row.get('_eligible') and review.get('decision')!='skip' and review.get('commercial_allowed') is True and review.get('historical_verified') is True and all(review.get(k) for k in required) and review.get('type') in ['原資料','後世の復元図','現代のイメージ画像'])

def run(args):
 out=Path(args.output)
 if out.exists() and any(out.iterdir()): raise ValueError('出力先は空フォルダを指定してください（動画ごとに独立）')
 out.mkdir(parents=True,exist_ok=True)
 for t in TOPICS: (out/t[0]).mkdir()
 (out/'08_要確認素材').mkdir(); evidence=out/'証跡'; evidence.mkdir()
 raw=Path(args.script).read_text(encoding=args.encoding)
 if not raw.strip(): raise ValueError('原稿が空です')
 (out/'使用原稿.txt').write_text(raw,encoding='utf-8')
 scenes=analyze(raw); (out/'シーン一覧.json').write_text(json.dumps(scenes,ensure_ascii=False,indent=2),encoding='utf-8')
 reviews=json.loads(Path(args.review).read_text(encoding='utf-8')) if args.review else {}
 policy=json.loads(Path(args.policy).read_text(encoding='utf-8')) if args.policy else {}
 c=Client(evidence,args.user_agent); errors=[]; probes=[]; rows={}; searchlog=[]
 for name,url in SITES.items():
  probe=url+'?action=query&format=json&meta=siteinfo' if name=='Wikimedia Commons' else url
  try: c.get(probe); probes.append({'site':name,'url':probe,'status':'接続成功（規約確認済みを意味しない）'})
  except Exception as e: probes.append({'site':name,'url':probe,'status':str(e)}); errors.append(name+': '+str(e))
 # 未確認規約のサイトへの自動検索を停止。接続確認以外のHTMLスクレイピングは行わない。
 if policy.get('commons_api_terms_reviewed') is True and policy.get('terms_url') and policy.get('reviewed_at'):
  for s in scenes:
   for q in list(dict.fromkeys(s['ja']+s['en']))[:args.queries]:
    searchlog.append({'scene':s['id'],'query':q,'site':'Wikimedia Commons'})
    try:
     data=c.query({'action':'query','format':'json','generator':'search','gsrsearch':q,'gsrnamespace':6,'gsrlimit':args.limit,'prop':'imageinfo','iiprop':'url|size|extmetadata|sha1','maxlag':5})
     for page in data.get('query',{}).get('pages',{}).values():
      info=page.get('imageinfo',[{}])[0]; m=info.get('extmetadata',{}); good,lic,licurl=license_gate(m)
      val=lambda k:plain(m.get(k,{}).get('value',''))
      pid=str(page['pageid']); mid='WC'+pid
      if mid in rows:
       if s['id'] not in rows[mid]['シーンID'].split(','): rows[mid]['シーンID']+=','+s['id']; rows[mid]['対応する原稿の箇所']+='\n'+s['id']+': '+s['text']
       continue
      row={k:UNKNOWN for k in FIELDS}; row.update({'素材ID':mid,'画像タイトル':page['title'],'制作者':val('Artist'),'制作年代':val('DateTimeOriginal'),'出典ページURL':info.get('descriptionurl',UNKNOWN),'画像URL':info.get('url',UNKNOWN),'ライセンス':lic,'権利根拠URL':licurl,'確認状況':'要確認・未取得','商用利用可否':'要確認','対応する原稿の箇所':s['id']+': '+s['text'],'シーンID':s['id'],'幅':info.get('width',UNKNOWN),'高さ':info.get('height',UNKNOWN),'史実上の注意点':'検索一致のみ。時代・描写・所蔵・原資料かどうかを個別確認すること。','_eligible':good,'_folder':s['folders'][0]})
      rv=reviews.get(mid,{})
      if approved(row,rv,policy):
       row.update({'資料の種類':rv['type'],'描写対象の年代':rv['depicted_date'],'クレジット表記':rv['credit'],'商用利用可否':'可（記録した根拠の範囲）','確認状況':'確認済み・未取得','権利根拠URL':rv['rights_evidence_url'],'確認日時':rv['reviewed_at'],'史実上の注意点':rv['historical_note'],'採用理由':rv['reason'],'所蔵機関':rv.get('institution',UNKNOWN)})
      rows[mid]=row
    except Exception as e: errors.append(s['id']+' '+q+': '+str(e))
 else: errors.append('Commons API利用条件の確認記録がないため自動検索を停止。検索計画のみ生成。')
 hashes={}; successes=0
 for mid,row in rows.items():
  if row['確認状況']!='確認済み・未取得': continue
  if not args.download: continue
  try:
   url=row['画像URL']; parsed=urllib.parse.urlsplit(url)
   if parsed.hostname!='upload.wikimedia.org': raise ValueError('原画像の許可ホスト外')
   ext=Path(parsed.path).suffix.lower()
   if ext not in ('.jpg','.jpeg','.png'): raise ValueError('MVPはJPEG/PNG原本のみ対応')
   data=c.get(url,args.max_mb*1024*1024)
   if not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')): raise ValueError('画像シグネチャ不一致')
   digest=hashlib.sha256(data).hexdigest(); row['SHA256']=digest
   if digest in hashes: row['確認状況']='重複・保存省略'; row['ファイル名']=hashes[digest]; continue
   filename=row['_folder']+'/'+mid+ext; (out/filename).write_bytes(data); hashes[digest]=filename
   row['ファイル名']=filename; row['確認状況']='取得成功'; successes+=1
  except Exception as e: row['確認状況']='取得失敗'; errors.append(mid+': '+str(e))
 rows=list(rows.values())
 for row in rows:
  status=row['確認状況']
  if status=='取得成功': group,reason='取得済み','確認記録あり・原本保存成功'
  elif status=='取得失敗': group,reason='取得エラー','保存できませんでした。エラーログ参照'
  elif reviews.get(row['素材ID'],{}).get('decision')=='skip': group,reason='取得見送り',reviews[row['素材ID']].get('skip_reason','利用者が見送りを指定')
  elif row['ライセンス']!=UNKNOWN and not row['_eligible']: group,reason='取得見送り','MVPの許可ライセンス対象外、または追加制限あり'
  elif status in ('重複・保存省略','確認済み・未取得'): group,reason='取得見送り',status
  else: group,reason='利用条件未確認','個別の権利・史実確認記録が不足'
  row['記録区分']=group; row['判定理由']=reason
 for group in ('取得済み','取得見送り','利用条件未確認','取得エラー'):
  with (out/(group+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore'); writer.writeheader()
   for row in rows:
    if row['記録区分']==group: writer.writerow({k:("'"+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in row.items()})
 (out/'実行結果.json').write_text(json.dumps({'candidates':len(rows),'downloaded':successes,'counts':{g:sum(r['記録区分']==g for r in rows) for g in ('取得済み','取得見送り','利用条件未確認','取得エラー')},'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
 with (out/'素材一覧.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore'); w.writeheader()
  # Excelの数式解釈を防ぐ。元メタデータは証跡JSONに保存。
  for r in rows: w.writerow({k:("'"+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in r.items()})
 pending=[r for r in rows if r['確認状況']!='取得成功']
 (out/'08_要確認素材'/'候補一覧.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf-8')
 for name,value in [('接続確認',probes),('検索実行記録',searchlog),('利用条件確認記録',policy),('個別確認記録',reviews)]:
  (evidence/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
 esc=lambda x:html.escape(str(x),quote=True)
 cards=[]; sources=['# 出典一覧','取得成功のみが利用可能な保存ファイルです。候補は未採用です。']
 for r in rows:
  sources.append('\n## '+r['素材ID']+' '+r['画像タイトル']+'\n出典: '+r['出典ページURL']+'\nライセンス: '+r['ライセンス']+'\nクレジット: '+r['クレジット表記']+'\n状況: '+r['確認状況'])
  if r['確認状況']=='取得成功':
   link=urllib.parse.quote(r['ファイル名'],safe='/')
   cards.append(f'<article><a href="{link}"><img loading="lazy" src="{link}" alt="{esc(r["画像タイトル"])}"></a><p>{esc(r["素材ID"])} {esc(r["画像タイトル"])}<br>{esc(r["制作年代"])}</p><a href="{esc(r["出典ページURL"])}">出典</a></article>')
 (out/'出典一覧.md').write_text('\n'.join(sources),encoding='utf-8')
 (out/'画像プレビュー.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><title>大和噺 素材プレビュー</title><style>body{font-family:sans-serif;margin:2rem;background:#f4f1e9}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:1rem}article{background:white;padding:1rem}img{width:100%;height:200px;object-fit:contain}</style><h1>大和噺 素材プレビュー</h1><p>取得成功 '+str(successes)+'件。表示画像は原本をCSSで縮小しています。</p><main>'+''.join(cards)+'</main></html>',encoding='utf-8')
 report=['# 収集レポート',datetime.now(timezone.utc).isoformat(),'','## 結果',f'発見候補: {len(rows)}件 / 取得成功: {successes}件 / 利用条件未確認: {sum(r["記録区分"]=="利用条件未確認" for r in rows)}件',f'実行した検索: {len(searchlog)}件。未接続先の候補数は不明（0件と断定しない）。','収益化動画での採用には保存した根拠と史実の最終確認が必要。','','## 接続確認（検索完了ではない）']
 report += [f'- {p["site"]}: {p["status"]}' for p in probes]
 report += ['','## 記録区分']+[f'- {g}: {sum(r["記録区分"]==g for r in rows)}件' for g in ('取得済み','取得見送り','利用条件未確認','取得エラー')]
 report += ['','## 各シーンの充足状況']
 for s in scenes:
  n=sum(r['確認状況']=='取得成功' and s['id'] in r['シーンID'].split(',') for r in rows)
  report.append(f'- {s["id"]}: {n}件 / '+('未充足' if not n else '画像取得あり・編集上の充足は要確認'))
 report+=['','## 方法と制約','段落・文末分割と辞書照合による検索計画。Commons Action APIのみ自動検索対応。国内機関は接続確認と手動調査先の記録のみ。HTMLスクレイピングなし。機械可読ライセンスの許可リスト判定に加え、個別の権利根拠・商用利用・史実確認の記録が揃った画像だけ取得。JPEG/PNG原本を無改変保存、SHA256で完全一致重複を除外。','未対応: NDL等の検索API連携、IIIF画像組立、TIFF/PDF、近似重複、生成AIによる意味解析、DaVinciタイムライン生成。','追加調査: 実原稿との照合、全シーンの年代・描写、所蔵機関、国内機関の現行規約とAPI、下肥・木樋の直接史料。','','## エラー']+['- '+e for e in errors]
 (out/'収集レポート.md').write_text('\n'.join(report),encoding='utf-8')
 plan=['# 手動調査・検索計画','これは発見済み資料のリストではありません。機関の公式画面で検索し、個別ページと規約を確認してください。']
 for s in scenes:
  plan+=['\n## '+s['id'],s['text'],'日本語: '+' / '.join(s['ja']),'英語: '+' / '.join(s['en'])]+[name+': '+url for name,url in SITES.items()]
 (out/'08_要確認素材'/'検索計画.md').write_text('\n'.join(plan),encoding='utf-8')
 print(json.dumps({'candidates':len(rows),'downloaded':successes,'errors':len(errors),'output':str(out)},ensure_ascii=False))

def main():
 p=argparse.ArgumentParser(description=__doc__); p.add_argument('--script',required=True); p.add_argument('--output',required=True); p.add_argument('--encoding',default='utf-8-sig'); p.add_argument('--policy'); p.add_argument('--review'); p.add_argument('--download',action='store_true'); p.add_argument('--user-agent',help='明示的な上級者用User-Agent'); p.add_argument('--wikimedia-user-page',help='Wikimedia利用者ページのHTTPS URL'); p.add_argument('--queries',type=int,default=2); p.add_argument('--limit',type=int,default=4); p.add_argument('--max-mb',type=int,default=80)
 a=p.parse_args()
 if a.wikimedia_user_page and a.user_agent: p.error('連絡先URLと上級者用User-Agentはどちらか一方を指定してください')
 if a.wikimedia_user_page:
  try: a.user_agent=build_user_agent(a.wikimedia_user_page)
  except (ValueError, UnicodeError) as e: p.error(str(e))
 elif not a.user_agent: p.error('--wikimedia-user-page で利用者ページURLを指定してください（Windowsでは起動.batを利用）')
 if not (1<=a.limit<=20 and 1<=a.queries<=10 and 1<=a.max_mb<=500): p.error('limit 1..20 / queries 1..10 / max-mb 1..500')
 run(a)
if __name__=='__main__': main()
