import base64
import re
import shutil
import subprocess
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from scene_analysis import blocks, free_analysis, allocate, validate_ai, ai_analysis
from commons_source import metadata, classify, CommonsSource, AccessDenied
from material_assistant import collect, counts, export_adopted, write_json
from catalog_app import CatalogServer, render_catalog, import_choices

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jxHkAAAAASUVORK5CYII=')
PAGE='https://commons.wikimedia.org/wiki/File:Fixture.png'

def asset(i,rights='PD',title=None):
    m={'LicenseShortName':{'value':'Public domain'},'Copyrighted':{'value':'False'},'Artist':{'value':'Fixture artist'},'ImageDescription':{'value':'江戸 玉川 上水 Tamagawa aqueduct 木樋'},'DateTimeOriginal':{'value':'1856'}}
    a=metadata({'pageid':i,'title':title or f'File:Fixture {i}.png','imageinfo':[{'extmetadata':m,'url':'https://upload.wikimedia.org/'+str(i)+'.png','thumburl':'https://upload.wikimedia.org/thumb/'+str(i)+'.png','descriptionurl':PAGE,'mime':'image/png','sha1':str(i),'width':2000,'height':1000}]})
    if rights=='要確認':a['rights']='要確認';a['conditions']='unknown test only'
    return a

class FixtureSource:
    downloads=[]
    def __init__(self,evidence,agent,progress):self.log=[]
    def probe(self):return {'sitename':'TEST FIXTURE (not live)'}
    def search(self,query,limit):return [asset(1),asset(2),asset(3,'要確認'),asset(4,title='File:Duplicated content.png')]
    def download(self,url,path):
        FixtureSource.downloads.append(url)
        p=Path(str(path)+'.png');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(PNG)
        # 1 and 4 have same hash -> only one original; 2 fails.
        if url.endswith('/2.png'):p.unlink();raise OSError('fixture download failure')
        return p,'same_content'

class AssistantTests(unittest.TestCase):
    def test_free_mode_honestly_marked_and_source_spans(self):
        text='江戸の上水道は玉川上水が支えた。\n\n町火消と火災。'
        for s in free_analysis(text):
            self.assertEqual(s['text'],text[s['start']:s['end']]);self.assertIn('AI未使用',s['analysis'])
        self.assertEqual(''.join(b['text'] for b in blocks(text)).replace('\n',''),text.replace('\n',''))
    def test_capacity_and_priority(self):
        scenes=[{'importance':1},{'importance':3}];allocate(scenes,7)
        self.assertEqual([s['quota'] for s in scenes],[3,4])
        allocate(scenes,100);self.assertEqual(sum(s['quota'] for s in scenes),10)
    def test_ai_alignment_missing_or_duplicate_rejected(self):
        text='第一。第二。';bs=blocks(text)
        s={'block_ids':[1,2],'topic':'topic','period':'不明','reason':'reason','people':[],'places':[],'image_types':['map'],'queries':['Edo map'],'visual_terms':['Edo'],'importance':2}
        self.assertEqual(validate_ai({'scenes':[s]},text,bs)[0]['text'],text)
        for ids in [[1],[2,1],[1,1]]:
            with self.assertRaises(ValueError):validate_ai({'scenes':[{**s,'block_ids':ids}]},text,bs)
    def test_ai_api_request_and_no_key_in_evidence(self):
        text='玉川上水。';bs=blocks(text)
        scene={'block_ids':[1],'topic':'上水','period':'江戸時代','reason':'水路を示す','people':[],'places':['江戸'],'image_types':['浮世絵'],'queries':['Tamagawa aqueduct'],'visual_terms':['Tamagawa'],'importance':3}
        response={'status':'completed','usage':{'input_tokens':10},'output':[{'content':[{'type':'output_text','text':json.dumps({'scenes':[scene]})}]}]}
        class R:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps(response).encode()
        with tempfile.TemporaryDirectory() as temp,patch('urllib.request.urlopen',return_value=R()) as opener:
            scenes=ai_analysis(text,'secret-fixture-key','gpt-4.1-mini',temp)
            sent=json.loads(opener.call_args.args[0].data)
            self.assertFalse(sent['store']);self.assertTrue(sent['text']['format']['strict'])
            self.assertIn('AI推定',scenes[0]['analysis']);self.assertNotIn('secret-fixture-key',next(Path(temp).glob('*.json')).read_text())
    def test_license_conflicts_and_missing_credit(self):
        self.assertEqual(asset(1)['rights'],'PD')
        self.assertEqual(classify({'LicenseShortName':{'value':'Public domain'}},PAGE)[0],'要確認')
        self.assertEqual(classify({'LicenseShortName':{'value':'CC BY-NC 4.0'}},PAGE)[0],'対象外')
        meta={'LicenseShortName':{'value':'CC BY 4.0'},'LicenseUrl':{'value':'https://creativecommons.org/licenses/by/4.0/'},'Artist':{'value':'Example'}}
        self.assertEqual(classify(meta,PAGE)[0],'CC BY');meta['Restrictions']={'value':'personality rights'}
        self.assertEqual(classify(meta,PAGE)[0],'要確認')
    def test_pipeline_safe_downloads_dedup_errors_and_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'script.txt';script.write_text('江戸の玉川上水と木樋。',encoding='utf-8');FixtureSource.downloads=[]
            m=collect(script,root/'out','https://commons.wikimedia.org/wiki/User:Fixture',4,source_factory=FixtureSource,progress=lambda _:None,terms_confirmed=True)
            c=counts(m);self.assertEqual(c['discovered'],4);self.assertEqual(c['downloaded'],1)
            self.assertEqual(c['candidates'],3);self.assertEqual(c['needs_review'],1)
            self.assertFalse(any(url.endswith('/3.png') for url in FixtureSource.downloads))
            self.assertTrue(any('failure' in e for e in m['errors']))
            self.assertTrue((root/'out/素材カタログ.html').is_file())
            for l in m['links']:m['choices'][l['id']]='採用'
            result=export_adopted(root/'out',m);self.assertEqual(result['copied'],1);self.assertEqual(len(result['not_exportable']),2)
            self.assertEqual(len(list(Path(result['folder']).rglob('*.png'))),1)
    def test_network_failure_still_has_catalog_and_shortage(self):
        class Down(FixtureSource):
            def probe(self):raise AccessDenied('fixture policy deny')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);s=root/'s.txt';s.write_text('江戸の上水道。')
            m=collect(s,root/'out','https://commons.wikimedia.org/wiki/User:Fixture',100,source_factory=Down,progress=lambda _:None,terms_confirmed=True)
            self.assertEqual(counts(m)['downloaded'],0);self.assertIn('全体不足: 100', (root/'out/収集レポート.md').read_text())
            self.assertTrue((root/'out/素材カタログ.html').exists())
    @unittest.skipUnless(shutil.which('node'),'Nodeがある開発環境でJavaScript構文を検証')
    def test_catalog_javascript_syntax(self):
        from catalog_app import HTML
        script='\n'.join(re.findall(r'<script>(.*?)</script>',HTML,re.S))
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'catalog.js';file.write_text(script,encoding='utf-8')
            result=subprocess.run([shutil.which('node'),'--check',str(file)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_metadata_cannot_inject_script(self):
        with tempfile.TemporaryDirectory() as temp:
            render_catalog(temp,{'title':'</script><script>alert(1)</script>'})
            text=Path(temp,'素材カタログ.html').read_text()
            self.assertNotIn('</script><script>alert(1)',text);self.assertIn('\\u003c/script',text)
    def test_server_persists_and_denies_untrusted_posts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);s=root/'s.txt';s.write_text('江戸の上水道。')
            m=collect(s,root/'out','https://commons.wikimedia.org/wiki/User:Fixture',1,source_factory=FixtureSource,progress=lambda _:None,terms_confirmed=True)
            server=CatalogServer(root/'out')
            try:
                link=m['links'][0]['id'];body=json.dumps({'id':link,'value':'採用'}).encode()
                # localhost only; not an external networking test.
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                req=urllib.request.Request(server.origin+'/api/choice',data=body,headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError):opener.open(req)
                req=urllib.request.Request(server.origin+'/api/choice',data=body,headers={'Content-Type':'application/json','Origin':server.origin,'X-Catalog-Token':server.token})
                with opener.open(req) as r:self.assertTrue(json.load(r)['saved'])
                self.assertEqual(json.loads((root/'out/catalog.json').read_text())['choices'][link],'採用')
                req=urllib.request.Request(server.origin+'/api/export',data=b'{}',headers={'Content-Type':'application/json','Origin':server.origin,'X-Catalog-Token':server.token})
                with opener.open(req) as r:self.assertEqual(json.load(r)['copied'],1)
                # No traversal or raw manuscript/metadata serving.
                for path in ['/../catalog.json','/catalog.json','/%2e%2e/secret.png']:
                    with self.assertRaises(urllib.error.HTTPError):opener.open(server.origin+path)
            finally:server.close()

if __name__=='__main__':unittest.main()
