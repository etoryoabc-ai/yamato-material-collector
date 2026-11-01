"""Opt-in Windows real API, ten originals and browser test. No fixtures substituted."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from material_assistant import collect, write_json
from browser_check import browser_check
from validation import validate_collection

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',action='store_true',help='実際のCommons利用条件を読んでから指定');p.add_argument('--output');p.add_argument('--browser',action='store_true');a=p.parse_args()
    if not a.run:p.error('実画像テストには利用条件確認後に --run を指定')
    root=Path(__file__).resolve().parent;out=Path(a.output) if a.output else root/'results'/('10枚取得テスト_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    m=collect(root/'examples/江戸_10枚取得テスト.txt',out,None,target=25,terms_confirmed=True,download_limit=10,agent_override='YamatoMaterialsBot/0.5 (https://github.com/etoryoabc-ai/yamato-material-collector; ten-image validation)')
    result=validate_collection(out,m,10)
    print(json.dumps({k:result[k] for k in ['download_goal','counts','verified_original_files','goal_met','network','errors','v03_comparison']},ensure_ascii=False,indent=2))
    if not result['goal_met']:raise SystemExit('原本10枚取得の目標未達。成功と扱いません。10枚取得テスト結果.json参照')
    if a.browser:
        try:
            info=browser_check(out,minimum_images=10);result['browser']=info;result['browser_verified']=True
        except Exception as e:
            result['browser_error']=str(e);write_json(out/'10枚取得テスト結果.json',result);raise SystemExit('画像表示検証失敗: '+str(e))
        write_json(out/'10枚取得テスト結果.json',result);print(json.dumps(info,ensure_ascii=False))
