"""Windows GUI: manuscript -> collect -> choose in browser. Standard library only."""
import argparse
import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from user_agent import normalize_user_page, saved_user_page, save_policy, POLICY_URL
from material_assistant import collect, counts
from catalog_app import CatalogServer, import_choices
from validation import validate_collection

ROOT=Path(__file__).resolve().parent

class App:
    def __init__(self,test=False):
        self.root=tk.Tk();self.root.title('大和噺｜原稿連動 映像素材アシスタント v0.5');self.root.geometry('850x790')
        for name in ('input','config','results','logs'):(ROOT/name).mkdir(exist_ok=True)
        try:self.policy=json.loads((ROOT/'config/policy.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.policy={}
        self.busy=False;self.events=queue.Queue();self.cancel=threading.Event();self.servers=[];self.latest=None
        self.script=tk.StringVar(value=str(ROOT/'input/完成原稿.txt'))
        self.contact=tk.StringVar(value=saved_user_page(self.policy));self.target=tk.StringVar(value=str(self.policy.get('target',100)))
        self.mode=tk.StringVar(value='無料ルール解析（AI未使用）');self.model=tk.StringVar(value=self.policy.get('model','gpt-4.1-mini'));self.key=tk.StringVar()
        self.terms=tk.BooleanVar(value=self.policy.get('commons_api_terms_reviewed',False));self.paid=tk.BooleanVar(value=False)
        frame=ttk.Frame(self.root,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='原稿から、映像の手がかりへ。',font=('',21)).pack(anchor='w')
        ttk.Label(frame,text='① 原稿を指定　→　② 素材収集開始　→　③ 画像一覧で採用',font=('',12)).pack(anchor='w',pady=12)
        row=ttk.Frame(frame);row.pack(fill='x');ttk.Entry(row,textvariable=self.script).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='原稿TXTを選ぶ',command=self.pick).pack(side='left',padx=5)
        row=ttk.Frame(frame);row.pack(fill='x',pady=12);ttk.Label(row,text='目標候補枚数').pack(side='left');ttk.Spinbox(row,from_=1,to=500,textvariable=self.target,width=7).pack(side='left',padx=8)
        ttk.Label(row,text='初期値100 / 1場面3〜5枚が目安。不足はレポートへ。').pack(side='left')
        ttk.Label(frame,text='原稿の解析方式').pack(anchor='w');ttk.Combobox(frame,textvariable=self.mode,values=['無料ルール解析（AI未使用）','OpenAI APIによる意味解析（有料・任意）'],state='readonly',width=65).pack(anchor='w',pady=5)
        notebook=ttk.Notebook(frame);notebook.pack(fill='x',pady=10)
        setup=ttk.Frame(notebook,padding=12);ai=ttk.Frame(notebook,padding=12);notebook.add(setup,text='初回設定（次回以降も保存）');notebook.add(ai,text='AI API設定（利用する場合のみ）')
        ttk.Label(setup,text='WikimediaユーザーページURL（個人メール不要）').pack(anchor='w');ttk.Entry(setup,textvariable=self.contact,width=90).pack(fill='x',pady=5)
        ttk.Label(setup,text='例: https://commons.wikimedia.org/wiki/User:あなたの利用者名').pack(anchor='w')
        links=ttk.Frame(setup);links.pack(anchor='w',pady=7)
        for label,url in [('再利用条件','https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia'),('API条件','https://www.mediawiki.org/wiki/API:Etiquette'),('User-Agent条件',POLICY_URL)]:
            ttk.Button(links,text=label,command=lambda u=url:webbrowser.open(u)).pack(side='left',padx=4)
        ttk.Checkbutton(setup,text='上記の条件を読み、API利用と画像の再利用条件を確認しました',variable=self.terms).pack(anchor='w')
        ttk.Label(ai,text='有料AIを選ぶと原稿全文をOpenAIへ送信します。無料モードは送信しません。\nAPI利用はモデル・トークン量により課金。ChatGPT契約だけで使えるとは限りません。').pack(anchor='w')
        row=ttk.Frame(ai);row.pack(fill='x',pady=6);ttk.Label(row,text='モデル').pack(side='left');ttk.Entry(row,textvariable=self.model,width=25).pack(side='left',padx=8)
        ttk.Label(row,text='APIキー').pack(side='left');ttk.Entry(row,textvariable=self.key,show='*').pack(side='left',fill='x',expand=True,padx=8)
        ttk.Label(ai,text='キーは画面内のみ・保存しません。空欄なら環境変数 OPENAI_API_KEY を使用。').pack(anchor='w')
        ttk.Checkbutton(ai,text='原稿送信とAPI課金を理解してAI解析を利用する',variable=self.paid).pack(anchor='w')
        ttk.Button(ai,text='公式API料金・モデルを確認',command=lambda:webbrowser.open('https://developers.openai.com/api/docs/pricing')).pack(anchor='w',pady=5)
        row=ttk.Frame(frame);row.pack(fill='x',pady=8)
        self.start_button=ttk.Button(row,text='素材収集開始',command=lambda:self.start(False));self.start_button.pack(side='left',padx=4)
        self.test_button=ttk.Button(row,text='江戸・10枚取得テスト',command=lambda:self.start(True));self.test_button.pack(side='left',padx=4)
        ttk.Button(row,text='中止',command=self.cancel.set).pack(side='left',padx=4)
        ttk.Button(row,text='過去のカタログを開く',command=self.open_previous).pack(side='left',padx=4)
        row=ttk.Frame(frame);row.pack(fill='x',pady=3)
        ttk.Button(row,text='選択JSON読込・書き出し',command=self.import_selection).pack(side='left',padx=4)
        ttk.Button(row,text='結果フォルダ',command=lambda:webbrowser.open((ROOT/'results').as_uri())).pack(side='left',padx=4)
        self.status=tk.StringVar(value='準備完了。初回だけ利用者ページと条件を設定してください。');ttk.Label(frame,textvariable=self.status,wraplength=790).pack(anchor='w',pady=10)
        self.log=tk.Text(frame,height=10,wrap='word');self.log.pack(fill='both',expand=True)
        self.root.protocol('WM_DELETE_WINDOW',self.close);self.root.after(150,self.poll)
        if test:self.root.after(500,lambda:messagebox.showinfo('実画像テスト','初回設定を確認し「江戸・10枚取得テスト」を押してください。テストは無料ルール解析・原本10枚を目標で実行します。'))
        self.root.mainloop()
    def pick(self):
        path=filedialog.askopenfilename(filetypes=[('UTF-8 原稿','*.txt')])
        if path:self.script.set(path)
    def start(self,test):
        if self.busy:return
        try:
            if not self.terms.get():raise ValueError('初回設定で公式条件を確認してください')
            contact=normalize_user_page(self.contact.get());target=int(self.target.get())
            if not 1<=target<=500:raise ValueError('目標枚数は1〜500です')
            script=Path(self.script.get());mode='free' if test or self.mode.get().startswith('無料') else 'ai'
            if test:script=ROOT/'examples/江戸_10枚取得テスト.txt';target=25
            if not script.is_file():raise ValueError('完成原稿.txtを指定してください（UTF-8）')
            if mode=='ai' and not self.paid.get():raise ValueError('AI設定で原稿送信と課金の確認欄を選んでください')
            key=(self.key.get().strip() or os.environ.get('OPENAI_API_KEY','')) if mode=='ai' else ''
            model=self.model.get().strip()
            if mode=='ai' and (not key or not model):raise ValueError('AI APIキーとモデルを設定してください')
            updated={**self.policy,'commons_api_terms_reviewed':True,'terms_url':'https://www.mediawiki.org/wiki/API:Etiquette','reviewed_at':datetime.now().astimezone().isoformat(),'target':int(self.target.get()),'model':model}
            self.policy=save_policy(ROOT/'config/policy.json',updated,contact)
        except Exception as e:messagebox.showerror('設定を確認',str(e));return
        out=ROOT/'results'/('大和噺_'+script.stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.busy=True;self.cancel.clear();self.start_button.config(state='disabled');self.test_button.config(state='disabled');self.log.delete('1.0','end');self.status.set('収集中。進捗を確認できます。')
        def worker():
            try:
                result=collect(script,out,contact,target,mode,key,model,lambda text:self.events.put(('progress',text)),self.cancel,terms_confirmed=True,download_limit=10 if test else None)
                if test:result['test_validation']=validate_collection(out,result,10)
                self.events.put(('done',(out,result)))
            except Exception as e:
                (ROOT/'logs'/('error_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.txt')).write_text(type(e).__name__+': '+str(e),encoding='utf-8')
                self.events.put(('error',type(e).__name__+': '+str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='progress':self.log.insert('end',value+'\n');self.log.see('end');self.status.set(value)
                else:
                    self.busy=False;self.start_button.config(state='normal');self.test_button.config(state='normal')
                    if kind=='done':
                        out,m=value;self.latest=out;c=counts(m)
                        self.status.set(f'発見 {c["discovered"]} / 関連候補 {c["candidates"]} / 原本取得 {c["downloaded"]} / 条件分類可(API) {c["license_classified"]}。最終確認は未了。')
                        for e in m['errors']:self.log.insert('end','記録: '+e+'\n')
                        if '10枚取得テスト' in out.name:
                            self.status.set(self.status.get()+(' 10枚取得目標達成。' if m.get('test_validation',{}).get('goal_met',False) else ' 10枚取得目標未達。成功扱いにしません。'))
                        self.open_catalog(out)
                    else:self.status.set('実行失敗（無料方式へ無断切替なし）');self.log.insert('end',value+'\n');messagebox.showerror('実行失敗',value)
        except queue.Empty:pass
        self.root.after(150,self.poll)
    def open_catalog(self,folder):
        try:
            if not Path(folder,'catalog.json').is_file():raise ValueError('v0.5のcatalog.jsonがある結果フォルダを選んでください')
            server=CatalogServer(folder);self.servers.append(server);webbrowser.open(server.url)
        except Exception as e:messagebox.showerror('カタログ',str(e))
    def open_previous(self):
        folder=filedialog.askdirectory(initialdir=ROOT/'results',title='catalog.jsonがある結果フォルダを選択')
        if folder:self.latest=Path(folder);self.open_catalog(folder)
    def import_selection(self):
        folder=filedialog.askdirectory(initialdir=ROOT/'results',title='選択に対応する結果フォルダを選択')
        if not folder:return
        path=filedialog.askopenfilename(filetypes=[('選択JSON','*.json')])
        if not path:return
        try:
            result=import_choices(folder,path);messagebox.showinfo('書き出し',f'保存 {result["copied"]}枚 / 書き出せない選択 {len(result["not_exportable"])}件\n{result["folder"]}')
        except Exception as e:messagebox.showerror('書き出し',str(e))
    def close(self):
        if self.busy:messagebox.showinfo('処理中','「中止」を押して、結果の保存が完了するまでお待ちください。');return
        for s in self.servers:s.close()
        self.root.destroy()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--test',action='store_true');args=p.parse_args();App(args.test)
