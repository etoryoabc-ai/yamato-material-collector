import gzip
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.robotparser
from pathlib import Path
from unittest.mock import Mock, patch
from commons_source import CommonsSource, AccessDenied, LocalResourceDenied, request_kind, retry_delay, API

AGENT='YamatoMaterialsBot/0.5 (https://github.com/etoryoabc-ai/yamato-material-collector)'
URL=API+'?action=query&format=json&meta=siteinfo&maxlag=5'

class Response:
    def __init__(self,data,headers=None):self.buffer=io.BytesIO(data);self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):return self.buffer.read(n)

class TransportTests(unittest.TestCase):
    def test_documented_api_scope_is_not_website_crawling(self):
        self.assertEqual(request_kind(URL),'action-api')
        q={'action':'query','format':'json','generator':'search','gsrnamespace':6,'gsrsearch':'Edo map','gsrlimit':10,'prop':'imageinfo','iiprop':'url|size|extmetadata|sha1'}
        self.assertEqual(request_kind(API+'?'+urllib.parse.urlencode(q)),'action-api')
        for invalid in [URL+'&prop=revisions',URL+'&action=edit',API+'?action=parse&format=json&page=X','https://commons.wikimedia.org/w/index.php?title=X','https://commons.wikimedia.org/wiki/Main_Page','https://evil.example/w/api.php?action=query&format=json&meta=siteinfo']:
            with self.subTest(url=invalid),self.assertRaises(AccessDenied):request_kind(invalid)
    def test_api_returned_media_tracking_parameters_are_not_html_queries(self):
        for host in ['upload.wikimedia.org','thumb.wikimedia.org']:
            self.assertEqual(request_kind('https://'+host+'/wikipedia/commons/6/6b/Map.png?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original'),'media')
        with self.assertRaises(AccessDenied):request_kind('https://upload.wikimedia.org/wikipedia/commons/6/6b/Map.png?action=edit')
    def test_api_uses_profile_not_robots_preflight_and_preserves_ua(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'):
            source=CommonsSource(tmp,AGENT);source.opener=Mock();source.opener.open.return_value=Response(gzip.compress(b'{"query":{"general":{"sitename":"fixture"}}}'),{'Content-Encoding':'gzip'})
            with patch.object(source,'robot_rules',side_effect=AssertionError('Website preflight must not block documented API')):
                self.assertEqual(source.probe()['sitename'],'fixture')
            req=source.opener.open.call_args.args[0]
            self.assertEqual(req.get_header('User-agent'),AGENT);self.assertEqual(req.get_header('Accept-encoding'),'gzip')
            self.assertEqual(json.loads(Path(tmp,'通信ログ.jsonl').read_text(encoding='utf-8').splitlines()[0])['kind'],'action-api')
    def test_media_robots_still_blocks_archive_before_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=CommonsSource(tmp,AGENT);source.opener=Mock();rules=urllib.robotparser.RobotFileParser();rules.parse(['User-agent: *','Disallow: /wikipedia/commons/archive/'])
            with patch.object(source,'robot_rules',return_value=rules):
                with self.assertRaises(AccessDenied):source.fetch('https://upload.wikimedia.org/wikipedia/commons/archive/a/ab/old.jpg')
            source.opener.open.assert_not_called()
    def test_http403_does_not_retry_rotate_ua_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'):
            source=CommonsSource(tmp,AGENT);source.opener=Mock();source.opener.open.side_effect=urllib.error.HTTPError(URL,403,'Forbidden',{},None)
            with self.assertRaises(AccessDenied):source.probe()
            self.assertEqual(source.opener.open.call_count,1)
            with self.assertRaises(AccessDenied):source.fetch('https://upload.wikimedia.org/wikipedia/commons/a/ab/example.jpg')
            self.assertEqual(source.opener.open.call_count,1)
    def test_retry_after_bounded_and_no_retry_before_delay(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep') as sleeper:
            source=CommonsSource(tmp,AGENT);source.opener=Mock()
            source.opener.open.side_effect=[urllib.error.HTTPError(URL,429,'rate',{'Retry-After':'8'},None),Response(b'{"query":{"general":{"sitename":"fixture"}}}')]
            source.probe();self.assertTrue(any(c.args[0]>=8 for c in sleeper.call_args_list));self.assertEqual(source.opener.open.call_count,2)
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'):
            source=CommonsSource(tmp,AGENT);source.opener=Mock();source.opener.open.side_effect=urllib.error.HTTPError(URL,429,'rate',{'Retry-After':'120'},None)
            with self.assertRaises(AccessDenied):source.probe()
            self.assertEqual(source.opener.open.call_count,1)
    def test_slow_api_waits_five_seconds_after_response(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'),patch('commons_source.time.monotonic',side_effect=[100,100,100,100,102,102]):
            source=CommonsSource(tmp,AGENT);source.opener=Mock();source.opener.open.return_value=Response(b'{}')
            source.fetch(URL);self.assertEqual(source.next_allowed,107)
    def test_compressed_body_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'):
            source=CommonsSource(tmp,AGENT);source.opener=Mock();source.opener.open.return_value=Response(gzip.compress(b'X'*500),{'Content-Encoding':'gzip'})
            with self.assertRaises(ValueError):source.fetch(URL,100)
    def test_api_maxlag_retries_then_stops(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'):
            source=CommonsSource(tmp,AGENT)
            with patch.object(source,'fetch',return_value=b'{"error":{"code":"maxlag"}}') as get:
                with self.assertRaises(AccessDenied):source.probe()
                self.assertEqual(get.call_count,3)
    def test_goal_counts_real_files_not_metadata_claims(self):
        from validation import validate_collection
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);assets={}
            for i in range(10):
                body=b'\x89PNG\r\n\x1a\nfixture'+str(i).encode();file=root/(str(i)+'.png');file.write_bytes(body)
                assets[str(i)]={'id':str(i),'original':file.name,'sha256':hashlib.sha256(body).hexdigest(),'source':'https://commons.wikimedia.org/wiki/File:Fixture','license':'Public domain','rights':'PD'}
            m={'raw_discovered':10,'assets':assets,'network':{'status':'fixture'},'errors':[]}
            self.assertTrue(validate_collection(root,m,10,compare=False)['goal_met'])
            (root/'9.png').unlink()
            result=validate_collection(root,m,10,compare=False)
            self.assertFalse(result['goal_met']);self.assertEqual(result['verified_original_files'],9)
    def test_unavailable_thumbnail_robots_is_cached_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp,patch('commons_source.time.sleep'):
            source=CommonsSource(tmp,AGENT);source.opener=Mock();source.opener.open.side_effect=LocalResourceDenied('robots redirected to project homepage')
            for _ in range(2):
                with self.assertRaises(LocalResourceDenied):source.robot_rules('thumb.wikimedia.org')
            self.assertEqual(source.opener.open.call_count,1)
    def test_missing_thumbnail_policy_does_not_discard_valid_originals(self):
        from test_assistant import FixtureSource,PNG
        from material_assistant import collect,counts
        import hashlib
        class WithoutThumbs(FixtureSource):
            def download(self,url,path):
                if '/thumb/' in url:raise LocalResourceDenied('fixture robots unavailable')
                p=Path(str(path)+'.png');p.parent.mkdir(parents=True,exist_ok=True);body=PNG+str(path).encode();p.write_bytes(body)
                return p,hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=root/'s.txt';s.write_text('江戸の玉川上水と木樋。',encoding='utf-8')
            m=collect(s,root/'out','https://commons.wikimedia.org/wiki/User:Fixture',4,source_factory=WithoutThumbs,progress=lambda _:None,terms_confirmed=True)
            self.assertEqual(counts(m)['downloaded'],3)
            self.assertTrue(all(a['original'] for a in m['assets'].values() if a['rights']=='PD'))
    def test_standard_thumbnail_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=CommonsSource(tmp,AGENT)
            with patch.object(source,'query',return_value={}) as query:source.search('江戸',10)
            self.assertEqual(query.call_args.args[0]['iiurlwidth'],330)

if __name__=='__main__':unittest.main()
