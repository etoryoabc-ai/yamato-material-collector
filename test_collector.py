import argparse, contextlib, csv, io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import collector as m

class SafetyTests(unittest.TestCase):
 def test_license_deny(self):
  for name in ['CC BY-NC 4.0','CC BY-SA 4.0','不明','Fair use']:
   self.assertFalse(m.license_gate({'LicenseShortName':{'value':name}})[0])
  self.assertTrue(m.license_gate({'LicenseShortName':{'value':'Public domain'}})[0])
 def test_offsets(self):
  text='玉川上水を調べる。\n\n火災と町火消。'
  for s in m.analyze(text): self.assertEqual(text[s['start']:s['end']],s['text'])
 def test_gate_and_dedup(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); (root/'script.txt').write_text('神田上水。',encoding='utf-8')
   policy={'commons_api_terms_reviewed':True,'terms_url':'https://example.invalid/terms','reviewed_at':'TEST'}
   (root/'policy.json').write_text(json.dumps(policy))
   rv={'commercial_allowed':True,'historical_verified':True,'rights_evidence_url':'https://example.invalid/rights','credit':'TEST','reviewed_at':'TEST','reviewer':'fixture','historical_note':'模擬史料','type':'原資料','depicted_date':'TEST','reason':'TEST'}
   (root/'review.json').write_text(json.dumps({'WC1':rv,'WC2':rv}))
   pages={str(i):{'pageid':i,'title':'File:Fixture.jpg','imageinfo':[{'url':f'https://upload.wikimedia.org/fixture{i}.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:Fixture.jpg','extmetadata':{'LicenseShortName':{'value':'Public domain'}}}]} for i in (1,2,3)}
   image_calls=[]
   def get(client,url,limit=0):
    if 'upload.wikimedia.org' in url: image_calls.append(url); return b'\xff\xd8\xffFIXTURE_NOT_REAL_IMAGE'
    return b'{}'
   a=argparse.Namespace(script=str(root/'script.txt'),output=str(root/'out'),encoding='utf-8',policy=str(root/'policy.json'),review=str(root/'review.json'),user_agent='TEST',queries=1,limit=3,max_mb=1,download=True)
   with patch.object(m.Client,'get',get),patch.object(m.Client,'query',return_value={'query':{'pages':pages}}),contextlib.redirect_stdout(io.StringIO()): m.run(a)
   with (root/'out'/'素材一覧.csv').open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
   self.assertEqual([r['確認状況'] for r in rows],['取得成功','重複・保存省略','要確認・未取得'])
   self.assertEqual([r['記録区分'] for r in rows],['取得済み','取得見送り','利用条件未確認'])
   self.assertTrue((root/'out/取得エラー.csv').exists())
   self.assertEqual(len(image_calls),2) # 未承認WC3はリクエストされない
   self.assertEqual(len(list((root/'out').rglob('*.jpg'))),1)
   self.assertEqual(next((root/'out').rglob('*.jpg')).read_bytes(),b'\xff\xd8\xffFIXTURE_NOT_REAL_IMAGE')
 def test_explicit_skip_overrides_approval(self):
  rv={k:'verified fixture' for k in ('rights_evidence_url','credit','reviewed_at','reviewer','historical_note','depicted_date','reason')}
  rv.update({'type':'原資料','commercial_allowed':True,'historical_verified':True,'decision':'skip'})
  policy={'commons_api_terms_reviewed':True,'terms_url':'https://example.invalid','reviewed_at':'fixture'}
  self.assertFalse(m.approved({'_eligible':True},rv,policy))
 def test_missing_review_denied(self):
  self.assertFalse(m.approved({'_eligible':True},{},{'commons_api_terms_reviewed':True}))
if __name__=='__main__': unittest.main()
