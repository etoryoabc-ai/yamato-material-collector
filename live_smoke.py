"""Opt-in real API + image + browser smoke test. Never substitutes dummy images."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from material_assistant import collect, counts
from browser_check import browser_check

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',action='store_true',help='実際のCommons利用条件を読んでから指定');p.add_argument('--output');p.add_argument('--browser',action='store_true');a=p.parse_args()
    if not a.run:p.error('実画像テストには利用条件確認後に --run を指定')
    root=Path(__file__).resolve().parent;out=Path(a.output) if a.output else root/'results'/('実画像テスト_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    m=collect(root/'examples/江戸_テスト原稿.txt',out,None,target=8,terms_confirmed=True,agent_override='YamatoMaterialsBot/0.4 (https://github.com/etoryoabc-ai/yamato-material-collector; live smoke test)')
    print(json.dumps(counts(m),ensure_ascii=False))
    if not counts(m)['downloaded']:raise SystemExit('実画像0件。成功と扱いません。収集レポート参照')
    if a.browser:print(json.dumps(browser_check(out),ensure_ascii=False))
