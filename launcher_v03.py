"""Windows GUI launcher: command entry is not required."""
import argparse, csv, json, subprocess, sys, threading, traceback, webbrowser
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from user_agent import normalize_user_page, saved_user_page, save_policy

ROOT=Path(__file__).resolve().parent
TERMS='https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia'
API_TERMS='https://www.mediawiki.org/wiki/API:Etiquette'

def load(path, default):
 return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def unique_output(test=False):
 return ROOT/'results'/(( 'Commons検証_' if test else '素材収集_')+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))

class App:
 def __init__(self, test=False):
  self.test=test; self.root=tk.Tk(); self.root.title('大和噺 歴史資料収集 v0.3'); self.root.geometry('760x640'); self.busy=False
  for folder in ('input','config','results','logs'): (ROOT/folder).mkdir(exist_ok=True)
  self.policy=load(ROOT/'config/policy.json',{})
  ttk.Label(self.root,text='大和噺｜Commons実接続テスト' if test else '大和噺｜歴史資料収集',font=('',18)).pack(pady=12)
  ttk.Label(self.root,text='input フォルダに「完成原稿.txt」を入れてください。\n初回は利用条件の確認と連絡先の設定が必要です。').pack()
  bar=ttk.Frame(self.root); bar.pack(pady=8)
  for label,url in [('再利用条件',TERMS),('API利用条件',API_TERMS),('User-Agent条件','https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy')]:
   ttk.Button(bar,text=label,command=lambda u=url:webbrowser.open(u)).pack(side='left',padx=4)
  self.checked=tk.BooleanVar(value=self.policy.get('commons_api_terms_reviewed',False))
  ttk.Checkbutton(self.root,text='上記の現行利用条件を読み、API利用条件を確認しました',variable=self.checked).pack()
  ttk.Label(self.root,text='WikimediaユーザーページURL').pack(pady=(8,0))
  self.contact=tk.StringVar(value=saved_user_page(self.policy)); ttk.Entry(self.root,textvariable=self.contact,width=70).pack()
  ttk.Label(self.root,text='例: https://commons.wikimedia.org/wiki/User:あなたの利用者名\n個人メールは不要です。自分の連絡可能な利用者ページを指定してください。').pack()
  ttk.Label(self.root,text='検索後、候補を個別確認し「個別確認・見送りを登録」から登録してください。\n権利・史実未確認の画像はダウンロードしません。').pack(pady=10)
  row=ttk.Frame(self.root); row.pack()
  self.search=ttk.Button(row,text='検索を開始',command=lambda:self.start(False)); self.search.pack(side='left',padx=4)
  self.reviewbutton=ttk.Button(row,text='個別確認・見送りを登録',command=self.review); self.reviewbutton.pack(side='left',padx=4)
  self.download=ttk.Button(row,text='確認済み画像を取得',command=lambda:self.start(True)); self.download.pack(side='left',padx=4)
  self.status=tk.StringVar(value='準備完了'); ttk.Label(self.root,textvariable=self.status,wraplength=700).pack(pady=10)
  self.log=tk.Text(self.root,height=14,wrap='word'); self.log.pack(fill='both',expand=True,padx=12,pady=6)
  ttk.Button(self.root,text='結果フォルダを開く',command=lambda:webbrowser.open((ROOT/'results').as_uri())).pack(pady=8)
  self.root.protocol('WM_DELETE_WINDOW',self.close)
  if self.checked.get() and self.contact.get().strip() and (test or (ROOT/'input/完成原稿.txt').exists()):
   self.root.after(500,lambda:self.start(True))
  self.root.mainloop()
 def close(self):
  if self.busy: messagebox.showinfo('処理中','処理完了後に閉じてください。'); return
  self.root.destroy()
 def start(self, download):
  if self.busy: return
  if not self.checked.get():
   messagebox.showerror('初回設定','利用条件を確認してください。'); return
  try: contact=normalize_user_page(self.contact.get())
  except (ValueError, UnicodeError) as e:
   messagebox.showerror('WikimediaユーザーページURL',str(e)); return
  script=ROOT/'input/完成原稿.txt'
  if self.test:
   script=ROOT/'config/commons_test.txt'; script.write_text('【実接続テスト用原稿】江戸の町並み。Hiroshige Nihonbashi の歴史資料を調べます。',encoding='utf-8')
  if not script.exists(): messagebox.showerror('原稿がありません','input/完成原稿.txt を保存してください。サンプルは examples にあります。'); return
  updated=dict(self.policy)
  updated.update({'commons_api_terms_reviewed':True,'terms_url':API_TERMS,'reuse_terms_url':TERMS,'reviewed_at':datetime.now().astimezone().isoformat()})
  self.policy=save_policy(ROOT/'config/policy.json',updated,contact)
  out=unique_output(self.test)
  cmd=[sys.executable,str(ROOT/'collector.py'),'--script',str(script),'--output',str(out),'--policy',str(ROOT/'config/policy.json'),'--wikimedia-user-page',contact,'--queries','4','--limit','3' if self.test else '4']
  review=ROOT/'config/review.json'
  if review.exists(): cmd+=['--review',str(review)]
  if download: cmd+=['--download']
  self.busy=True
  for b in (self.search,self.download,self.reviewbutton): b.config(state='disabled')
  self.status.set('処理中… 回線によっては数分かかります。'); self.log.delete('1.0','end')
  def worker():
   try:
    result=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    log=result.stdout; code=result.returncode
   except Exception: code=1; log=traceback.format_exc()
   (ROOT/'logs'/(out.name+'.log')).write_text(log,encoding='utf-8')
   self.root.after(0,lambda:self.finish(code,log,out))
  threading.Thread(target=worker,daemon=True).start()
 def finish(self,code,log,out):
  self.busy=False
  for b in (self.search,self.download,self.reviewbutton): b.config(state='normal')
  self.log.insert('end',log)
  result=load(out/'実行結果.json',{})
  errors=result.get('errors',[])
  summary=f'候補 {result.get("candidates",0)}件 / 取得 {result.get("downloaded",0)}件 / 記録エラー {len(errors)}件'
  self.status.set(('実行失敗。ログを確認してください。' if code else '処理終了：'+summary)+'\n'+str(out))
  self.log.insert('end','\n'+'\n'.join(errors))
  self.last=out
  if self.test and not code:
   msg='実画像の取得に成功しました。出典・画像を確認してください。' if result.get('downloaded') else '実画像はまだ取得できていません。候補があれば個別確認を登録し、「確認済み画像を取得」を押してください。接続失敗ならログを確認してください。'
   messagebox.showinfo('Commons検証結果',msg+'\n'+summary)
 def review(self):
  if self.busy: return
  runs=sorted((ROOT/'results').glob('*/素材一覧.csv'),key=lambda p:p.stat().st_mtime,reverse=True)
  if not runs: messagebox.showinfo('候補なし','先に検索してください。'); return
  with runs[0].open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
  if not rows: messagebox.showinfo('候補なし','直近の検索結果は0件です。ログをご確認ください。'); return
  win=tk.Toplevel(self.root); win.title('個別確認（直近の検索結果）'); win.geometry('820x780')
  current=tk.StringVar(); options=[r['素材ID']+' | '+r['画像タイトル'] for r in rows]
  combo=ttk.Combobox(win,textvariable=current,values=options,state='readonly',width=95); combo.pack(pady=6); combo.current(0)
  ttk.Button(win,text='出典ページをブラウザで開く',command=lambda:webbrowser.open(rows[combo.current()]['出典ページURL'])).pack()
  ttk.Label(win,text='原資料か・制作年代と描写年代・権利条件を出典で確認してください。\n検索でヒットしただけでは史実確認になりません。').pack(pady=5)
  variables={}
  for key,label in [('rights_evidence_url','権利条件の根拠URL'),('credit','必要クレジット'),('reviewer','確認者'),('type','資料の種類（原資料／後世の復元図／現代のイメージ画像）'),('depicted_date','描写対象の年代'),('historical_note','史実上の注意点'),('reason','採用理由'),('institution','所蔵機関（不明なら不明）'),('skip_reason','見送り理由（見送り時）')]:
   ttk.Label(win,text=label).pack(); v=tk.StringVar(); variables[key]=v
   if key=='type': ttk.Combobox(win,textvariable=v,values=['原資料','後世の復元図','現代のイメージ画像'],state='readonly',width=85).pack()
   else: ttk.Entry(win,textvariable=v,width=95).pack()
  rights=tk.BooleanVar(); historical=tk.BooleanVar()
  ttk.Checkbutton(win,text='個別条件を確認し、収益化動画での商用利用が認められている',variable=rights).pack(pady=5)
  ttk.Checkbutton(win,text='描写内容・年代・資料の種類を確認した',variable=historical).pack()
  def populate(*_):
   rv=load(ROOT/'config/review.json',{}).get(rows[combo.current()]['素材ID'],{})
   for k,v in variables.items(): v.set(rv.get(k,''))
   rights.set(rv.get('commercial_allowed',False)); historical.set(rv.get('historical_verified',False))
  combo.bind('<<ComboboxSelected>>',populate); populate()
  def save(skip):
   rv={k:v.get().strip() for k,v in variables.items()}
   if skip and not rv['skip_reason']: messagebox.showerror('記入不足','見送り理由を記入してください。',parent=win); return
   if not skip and (not rights.get() or not historical.get() or not all(rv[k] for k in ('rights_evidence_url','credit','reviewer','type','depicted_date','historical_note','reason'))):
    messagebox.showerror('未確認','権利・史実の確認と必要項目の記入が必要です。',parent=win); return
   rv.update({'commercial_allowed':rights.get(),'historical_verified':historical.get(),'reviewed_at':datetime.now().astimezone().isoformat(),'decision':'skip' if skip else 'approve'})
   path=ROOT/'config/review.json'; data=load(path,{}); data[rows[combo.current()]['素材ID']]=rv
   path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); messagebox.showinfo('保存','記録しました。取得ボタンで再検索・取得してください。',parent=win)
  buttons=ttk.Frame(win); buttons.pack(pady=8)
  ttk.Button(buttons,text='確認済みとして保存',command=lambda:save(False)).pack(side='left',padx=8)
  ttk.Button(buttons,text='取得見送りとして保存',command=lambda:save(True)).pack(side='left',padx=8)

if __name__=='__main__':
 parser=argparse.ArgumentParser(); parser.add_argument('--test',action='store_true'); args=parser.parse_args()
 try: App(args.test)
 except Exception:
  (ROOT/'logs').mkdir(exist_ok=True); (ROOT/'logs/起動エラー.log').write_text(traceback.format_exc(),encoding='utf-8')
  raise
