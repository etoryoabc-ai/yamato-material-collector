"""Real file verification and v0.3 wire-shape comparison; no dummy fallback."""
import hashlib
import json
from pathlib import Path
from commons_source import CommonsSource
from material_assistant import counts, write_json


def validate_collection(folder,m,goal=10,compare=True):
    folder=Path(folder);verified=[];failures=[]
    for aid,a in m['assets'].items():
        if not a['original']:continue
        file=(folder/a['original']).resolve()
        if not file.is_relative_to(folder.resolve()) or not file.is_file():failures.append(aid+': 保存ファイルなし');continue
        body=file.read_bytes()
        if hashlib.sha256(body).hexdigest()!=a.get('sha256'):failures.append(aid+': SHA256不一致');continue
        if not(body.startswith(b'\xff\xd8\xff') or body.startswith(b'\x89PNG\r\n\x1a\n')):failures.append(aid+': JPEG/PNGシグネチャ不一致');continue
        verified.append({'id':aid,'file':a['original'],'bytes':len(body),'sha256':a['sha256'],'source':a['source'],'license':a['license']})
    comparison={'status':'未実行','query':'Edo map','limit':10,'user_report_v03_candidates':10,'note':'ユーザー報告のv0.3成功10件は受領情報。以下の実測結果と区別する。'}
    policy_path=folder/'証跡/アクセス方針.json'
    stop=any(any(token in e for token in ['HTTP 401','HTTP 403','HTTP 429','HTTP 503','アクセス停止','API maxlag','API ratelimited','中止']) for e in m['errors'])
    if compare and m['network'].get('status')=='API応答成功' and not stop and policy_path.exists():
        try:
            agent=json.loads(policy_path.read_text(encoding='utf-8'))['user_agent']
            source=CommonsSource(folder/'証跡',agent)
            response=source.query({'generator':'search','gsrsearch':'Edo map','gsrnamespace':6,'gsrlimit':10,'prop':'imageinfo','iiprop':'url|size|extmetadata|sha1'})
            comparison.update({'status':'API応答成功','measured_candidates':len(response.get('query',{}).get('pages',{})),'route':'v0.3と同じaction=query / generator=search / prop=imageinfo'})
        except Exception as e:comparison.update({'status':'失敗','error':str(e)})
    elif stop:comparison['note']+=' サーバー拒否・待機・中止があるため追加要求を行わない。'
    result={'version':'0.5','download_goal':goal,'counts':counts(m),'verified_original_files':len(verified),'goal_met':len(verified)>=goal,'verified_files':verified,'file_errors':failures,'network':m['network'],'errors':m['errors'],'v03_comparison':comparison,'browser_verified':False}
    write_json(folder/'10枚取得テスト結果.json',result)
    write_json(folder/'v03通信方式比較.json',comparison)
    return result
