"""Headless Chrome/Edge verification of a saved catalog, including actual image decode.

This does not download media. Use --require-images with a real collected result.
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from catalog_app import CatalogServer
from pathlib import Path

INJECT='''<script>addEventListener('load',()=>{for(const i of document.querySelectorAll('img.preview'))i.loading='eager';setTimeout(()=>{const a=[...document.querySelectorAll('img.preview')];document.body.setAttribute('data-decoded-images',a.filter(i=>i.complete&&i.naturalWidth>0).length);document.body.setAttribute('data-card-count',document.querySelectorAll('.card').length)},1500)});</script>'''

def browser_check(folder,require_images=True,minimum_images=1):
    folder=Path(folder).resolve()
    browser=next((v for v in [shutil.which('chromium'),shutil.which('google-chrome'),shutil.which('msedge'),str(Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'),str(Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe')] if v and Path(v).is_file()),None)
    if not browser:raise RuntimeError('Chrome/Edge/Chromiumが見つかりません。カタログを手動で開いて確認してください')
    snapshot=folder/'ブラウザ検証.html';snapshot.write_text((folder/'素材カタログ.html').read_text(encoding='utf-8').replace('</body>',INJECT+'</body>'),encoding='utf-8')
    command=[browser,'--headless','--disable-gpu','--no-sandbox','--disable-dev-shm-usage','--no-first-run','--disable-background-networking','--disable-extensions','--disable-component-update','--password-store=basic','--allow-file-access-from-files','--virtual-time-budget=8000','--dump-dom',snapshot.as_uri()]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sync_playwright=None
    if sync_playwright:
        with tempfile.TemporaryDirectory(prefix='yamato_browser_',ignore_cleanup_errors=True) as profile:
            for name in ('cache','config'):(Path(profile)/name).mkdir()
            environment=dict(os.environ,XDG_CACHE_HOME=profile+'/cache',XDG_CONFIG_HOME=profile+'/config')
            with sync_playwright() as pw:
                instance=pw.chromium.launch(executable_path=browser,headless=True,env=environment,args=['--no-sandbox','--disable-dev-shm-usage'],timeout=25000)
                server=CatalogServer(folder)
                try:
                    page=instance.new_page(viewport={'width':1440,'height':1000})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(server.origin+'/'+urllib.parse.quote(snapshot.name)+'?token='+server.token,wait_until='load',timeout=25000)
                    page.wait_for_function("document.body.hasAttribute('data-card-count')",timeout=10000)
                    if require_images:page.wait_for_function("(n)=>[...document.querySelectorAll('img.preview')].filter(i=>i.complete&&i.naturalWidth>0).length>=n",arg=minimum_images,timeout=30000)
                    info={'browser':Path(browser).name,'engine':'Playwright','decoded_images':page.locator('img.preview').evaluate_all('(imgs)=>imgs.filter(i=>i.complete&&i.naturalWidth>0).length'),'rendered_cards':page.locator('.card').count(),'javascript_errors':errors}
                    (folder/'ブラウザ検証DOM.html').write_text(page.content(),encoding='utf-8')
                    page.screenshot(path=str(folder/'カタログ表示検証.png'),full_page=True)
                finally:server.close();instance.close()
        (folder/'ブラウザ検証.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        if errors or (require_images and info['decoded_images']<minimum_images):raise RuntimeError('ブラウザ描画または画像デコード失敗')
        return info
    with tempfile.TemporaryDirectory(prefix='yamato_browser_',ignore_cleanup_errors=True) as profile:
        command.insert(1,'--user-data-dir='+profile)
        for name in ('cache','config'):(Path(profile)/name).mkdir()
        environment=dict(os.environ,XDG_CACHE_HOME=profile+'/cache',XDG_CONFIG_HOME=profile+'/config')
        try:
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40,env=environment)
        except subprocess.TimeoutExpired as e:
            (folder/'ブラウザ検証ログ.txt').write_bytes(e.stderr or b'')
            raise RuntimeError('ブラウザ検証が40秒で完了しませんでした。手動でカタログを確認してください') from None
    (folder/'ブラウザ検証ログ.txt').write_bytes(result.stderr)
    dom=result.stdout.decode('utf-8',errors='replace')
    (folder/'ブラウザ検証DOM.html').write_text(dom,encoding='utf-8')
    import re
    decoded=re.search(r'data-decoded-images="(\d+)"',dom);cards=re.search(r'data-card-count="(\d+)"',dom)
    info={'browser':Path(browser).name,'decoded_images':int(decoded[1]) if decoded else None,'rendered_cards':int(cards[1]) if cards else None,'returncode':result.returncode}
    (folder/'ブラウザ検証.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    if result.returncode or decoded is None or cards is None:raise RuntimeError('ブラウザでHTML実行を検証できませんでした')
    if require_images and info['decoded_images']<minimum_images:raise RuntimeError('実画像のデコード成功を確認できません')
    return info
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--allow-empty',action='store_true');a=p.parse_args();print(json.dumps(browser_check(a.folder,not a.allow_empty),ensure_ascii=False))
