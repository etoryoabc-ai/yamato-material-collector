"""v0.5 collection pipeline; HTML catalog is generated even on network failure."""
import csv
import hashlib
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from scene_analysis import free_analysis, ai_analysis, allocate
from commons_source import CommonsSource, AccessDenied, relevance
from user_agent import build_user_agent

CLEAR={'PD','CC0','CC BY'}

def write_json(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)

def filename(value,maxlen=55):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',value).strip(' .')[:maxlen]
    return value or '名称不明'

def quotas_report(manifest):
    rows=[]
    for scene in manifest['scenes']:
        links=[x for x in manifest['links'] if x['scene_id']==scene['id']]
        available=sum(bool(manifest['assets'][x['asset_id']]['original']) for x in links)
        rows.append({'scene':scene['id'],'topic':scene['topic'],'quota':scene['quota'],'candidates':len(links),'downloaded':available,'shortage':max(0,scene['quota']-len(links))})
    return rows

def collect(script,out,user_page,target=100,mode='free',key='',model='gpt-4.1-mini',progress=print,cancel=None,source_factory=CommonsSource,terms_confirmed=False,agent_override=None,download_limit=None):
    if not terms_confirmed:raise ValueError('API・再利用条件を初回設定で確認してください')
    if not 1<=target<=500:raise ValueError('目標枚数は1〜500')
    if download_limit is not None and not 1<=download_limit<=500:raise ValueError('取得枚数上限は1〜500')
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('出力先を上書きしません。新しいフォルダを指定してください')
    text=Path(script).read_text(encoding='utf-8-sig')
    if not text.strip():raise ValueError('原稿が空です')
    if len(text)>100000:raise ValueError('原稿は100,000字まで')
    out.mkdir(parents=True,exist_ok=True);evidence=out/'証跡';evidence.mkdir()
    (out/'使用原稿.txt').write_text(text,encoding='utf-8')
    progress('原稿解析中（'+('有料AI' if mode=='ai' else '無料ルール・AI未使用')+'）')
    scenes=ai_analysis(text,key,model,evidence) if mode=='ai' else free_analysis(text)
    if not scenes:raise ValueError('原稿から場面を作成できませんでした')
    allocate(scenes,target)
    manifest={'version':'0.5','run_id':out.name,'created_at':datetime.now(timezone.utc).isoformat(),'target':target,'mode':mode,'analysis':'AI推定・未検証' if mode=='ai' else '無料ルール（AI未使用）','scenes':scenes,'assets':{},'links':[],'choices':{},'errors':[],'network':{},'raw_discovered':0,'rejected':[]}
    def stopped():return cancel is not None and cancel.is_set()
    source=source_factory(evidence,agent_override or build_user_agent(user_page),progress)
    online=False
    try:
        info=source.probe()
        if not info:raise ValueError('API接続応答にsiteinfoがありません')
        manifest['network']={'status':'API応答成功','site':info.get('sitename','不明')};online=True
    except Exception as e:manifest['network']={'status':'接続失敗','error':str(e)};manifest['errors'].append('API接続: '+str(e))
    raw={};pools={s['id']:{} for s in scenes};blocked=False;search_count=0
    if online:
        # Query rounds give all scenes a chance before deeper searches.
        for round_no in range(6):
            for s in sorted(scenes,key=lambda s:(-s['importance'],s['id'])):
                if stopped() or blocked:break
                if not s['quota'] or round_no>=len(s['queries']):continue
                if search_count>=300:blocked=True;manifest['errors'].append('API検索予算300クエリ上限に到達');break
                query=s['queries'][round_no].strip()
                if not query:continue
                search_count+=1;progress(f'{s["id"]} 検索 {search_count}: {query}')
                try:
                    items=source.search(query,limit=20)
                    for item in items:
                        raw.setdefault(item['id'],item)
                        match=relevance(s,item)
                        if match is not None:
                            if item['id'] not in pools[s['id']] or match['score']>pools[s['id']][item['id']]['score']:
                                pools[s['id']][item['id']]=match
                except AccessDenied as e:blocked=True;manifest['errors'].append('アクセス停止: '+str(e))
                except Exception as e:manifest['errors'].append(s['id']+' '+query+': '+str(e))
            if stopped() or blocked:break
    manifest['raw_discovered']=len(raw)
    write_json(evidence/'発見候補.json',list(raw.values()))
    write_json(evidence/'検索ログ.json',getattr(source,'log',[]))
    used=set();hashes=set()
    # Round allocation gives 1st/2nd/3rd choices fairly; extra slots favor important scenes.
    for slot in range(5):
        for s in sorted(scenes,key=lambda s:(-s['importance'],s['id'])):
            if slot>=s['quota'] or len(used)>=target:continue
            for aid,match in sorted(pools[s['id']].items(),key=lambda p:-p[1]['score']):
                asset=raw[aid];unique=asset.get('sha1') or aid
                if aid in used or unique in hashes or asset['rights']=='対象外':continue
                used.add(aid);hashes.add(unique);manifest['assets'][aid]=dict(asset)
                manifest['links'].append({'id':s['id']+'_'+aid,'scene_id':s['id'],'asset_id':aid,**match});break
    manifest['links'].sort(key=lambda x:(x['scene_id'],-x['score']))
    for aid,a in raw.items():
        if aid not in used:
            if a['rights']=='対象外':reason='権利条件が自動取得対象外'
            elif not any(aid in pool for pool in pools.values()):reason='具体的な画像説明語との一致なし（関連性不足）'
            elif a.get('sha1') and a['sha1'] in hashes:reason='原画像SHA1が一致（重複）'
            else:reason='シーン別枠・全体目標枚数超過'
            manifest['rejected'].append({'id':aid,'title':a['title'],'source':a['source'],'reason':reason})
    sha256s={}
    for aid,a in manifest['assets'].items():
        if stopped():break
        if a['rights'] not in CLEAR:
            a['download_status']='利用条件未確認・画像未取得';continue
        if a['mime'] not in ('image/jpeg','image/png'):
            a['download_status']='形式対象外（原本JPEG/PNGのみ）';continue
        if download_limit is not None and len(sha256s)>=download_limit:
            a['download_status']='取得テストの保存目標到達・保存省略';continue
        progress('画像取得: '+a['title'])
        try:
            p,digest=source.download(a['original_url'],out/'候補原本'/aid)
            if digest in sha256s:
                p.unlink();a['download_status']='重複・保存省略';a['duplicate_of']=sha256s[digest];continue
            sha256s[digest]=aid;a['sha256']=digest;a['original']=str(p.relative_to(out)).replace('\\','/');a['download_status']='原本取得成功'
            if a['thumbnail_url']:
                try:
                    thumb,_=source.download(a['thumbnail_url'],out/'サムネイル'/aid)
                    a['thumbnail']=str(thumb.relative_to(out)).replace('\\','/')
                except AccessDenied as e:manifest['errors'].append(aid+' サムネイル取得を停止: '+str(e));break
                except Exception as e:manifest['errors'].append(aid+' サムネイル: '+str(e))
        except AccessDenied as e:
            a['download_status']='取得エラー';manifest['errors'].append(aid+': '+str(e));break
        except Exception as e:a['download_status']='取得エラー';manifest['errors'].append(aid+': '+str(e))
    duplicates={aid for aid,a in manifest['assets'].items() if a.get('duplicate_of')}
    manifest['links']=[x for x in manifest['links'] if x['asset_id'] not in duplicates]
    for aid in duplicates:manifest['rejected'].append({'id':aid,'reason':'原画像SHA256が一致','duplicate_of':manifest['assets'][aid]['duplicate_of']});del manifest['assets'][aid]
    if stopped():manifest['errors'].append('利用者による中止。取得済み結果を保存')
    persist(out,manifest)
    return manifest

CSV_FIELDS=['シーンID','原稿','素材ID','資料名','制作者','所蔵機関','制作年代','描写対象の年代','資料の種類','画像説明','出典URL','原画像URL','ライセンス','条件URL','商用利用条件','判定','クレジット','おすすめ度','採用理由（推定）','史実上の注意点','採否','取得状況','ファイル名']

def counts(m):
    return {'discovered':m['raw_discovered'],'candidates':len(m['assets']),'downloaded':sum(bool(a['original']) for a in m['assets'].values()),'license_classified':sum(a['rights'] in CLEAR for a in m['assets'].values()),'needs_review':sum(a['rights']=='要確認' for a in m['assets'].values()),'legal_historical_final_verified':0}

def persist(out,m):
    out=Path(out);write_json(out/'catalog.json',m)
    write_json(out/'実行結果.json',{'counts':counts(m),'scenes':quotas_report(m),'errors':m['errors'],'network':m['network']})
    scenes={s['id']:s for s in m['scenes']}
    write_json(out/'除外候補.json',m['rejected'])
    rows=[]
    for link in m['links']:
        a=m['assets'][link['asset_id']];s=scenes[link['scene_id']]
        rows.append(dict(zip(CSV_FIELDS,[s['id'],s['text'],a['id'],a['title'],a['artist'],a['institution'],a['date'],'不明（解析の時代指定は推定）',a['object_type'],a['description'],a['source'],a['original_url'],a['license'],a['license_url'],a['conditions'],a['rights']+'（API分類・最終確認未了）',a['credit'],link['score'],link['reason'],link['notes'],m['choices'].get(link['id'],'保留'),a['download_status'],a['original']])))
    for name,subset in [('素材一覧',rows),('取得済み',[r for r in rows if r['ファイル名']]),('利用条件未確認',[r for r in rows if r['判定'].startswith('要確認')]),('取得見送り',[r for r in rows if not r['ファイル名']]),('取得エラー',[r for r in rows if r['取得状況']=='取得エラー'])]:
        with (out/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=CSV_FIELDS);w.writeheader()
            for row in subset:w.writerow({k:("'"+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in row.items()})
    c=counts(m)
    report=['# 収集レポート',f'解析方式: {m["analysis"]}',f'全体目標: {m["target"]} / API発見: {c["discovered"]} / 関連候補: {c["candidates"]} / 原本取得: {c["downloaded"]} / 利用条件分類可(API): {c["license_classified"]} / 要確認: {c["needs_review"]}',
      '法的・史実的な最終確認完了: 0件（このアプリの自動判定では完了扱いにしない）',f'全体不足: {max(0,m["target"]-c["candidates"])}件。1場面5枚まで。短い原稿では100枚に届かないことがあります。',
      '出典メタデータはAPI取得、解析とおすすめ理由は推定。AIによる画像の視覚検証は行っていません。','接続: '+json.dumps(m['network'],ensure_ascii=False),'','## シーン別']
    for row in quotas_report(m):report.append(f'- {row["scene"]} {row["topic"]}: 目標 {row["quota"]} / 候補 {row["candidates"]} / 原本 {row["downloaded"]} / 候補不足 {row["shortage"]}')
    report+=['','## 追加調査','不足シーンの別キーワード・NDL等の公式資料、制作年代と描写年代、原資料・後世の復元・現代写真の区別、各国の権利条件。国内機関アダプターは未実装。','','## エラー']+m['errors']
    (out/'収集レポート.md').write_text('\n'.join(report),encoding='utf-8')
    credits=['候補資料のクレジット案（採用一覧は編集用フォルダ内）','APIメタデータに基づく。映像での変更表示・権利条件の最終確認が必要。']
    credits += [a['id']+' '+a['credit'] for a in m['assets'].values()]
    (out/'クレジット一覧.txt').write_text('\n\n'.join(credits),encoding='utf-8')
    from catalog_app import render_catalog
    render_catalog(out,m)

EXPORT_LOCK=threading.RLock()

def export_adopted(out,m):
    # New revision each time: changing selections never deletes previous editorial exports.
    with EXPORT_LOCK:
        out=Path(out);dest=out/'編集用'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');dest.mkdir(parents=True)
        scenes={s['id']:s for s in m['scenes']};credits=[];copied=0;missing=[]
        for link in m['links']:
            if m['choices'].get(link['id'])!='採用':continue
            a=m['assets'][link['asset_id']]
            if not a['original'] or a['rights'] not in CLEAR:missing.append(link['id']);continue
            original=(out/a['original']).resolve()
            if not original.is_relative_to(out.resolve()) or not original.is_file():missing.append(link['id']);continue
            s=scenes[link['scene_id']];folder=dest/(s['id'][1:]+'_'+filename(s['topic']))
            folder.mkdir(exist_ok=True)
            name=s['id']+'_'+filename(a['title'])+'_'+a['id']+original.suffix
            shutil.copyfile(original,folder/name);copied+=1
            credits.append(f'{link["id"]} / {a["credit"]}\n確認状態: 自動分類・最終確認未了\n{link["notes"]}')
        (dest/'クレジット一覧.txt').write_text('\n\n'.join(credits),encoding='utf-8')
        (dest/'書き出し結果.json').write_text(json.dumps({'copied':copied,'not_exportable':missing},ensure_ascii=False,indent=2),encoding='utf-8')
        return {'folder':str(dest),'copied':copied,'not_exportable':missing}
