import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import collector
from user_agent import normalize_user_page, build_user_agent, saved_user_page, save_policy

URL='https://commons.wikimedia.org/wiki/User:YamatoExample'

class UserAgentTests(unittest.TestCase):
 def test_descriptive_user_agent_no_email(self):
  agent=build_user_agent(URL)
  self.assertEqual(agent,'YamatoMaterialsBot/0.4 ('+URL+'; https://github.com/etoryoabc-ai/yamato-material-collector)')
  self.assertNotIn('@',agent)
 def test_japanese_url_and_parentheses_are_ascii(self):
  url=normalize_user_page('https://commons.wikimedia.org/wiki/利用者:大和(噺)')
  self.assertIn('/wiki/User:',url); self.assertIn('%E5',url); self.assertIn('%28',url)
  self.assertEqual(url,normalize_user_page(url)); build_user_agent(url).encode('ascii')
 def test_wikimedia_user_pages(self):
  for host in ['commons.wikimedia.org','meta.wikimedia.org','ja.wikipedia.org','www.wikidata.org','www.mediawiki.org']:
   with self.subTest(host=host): self.assertEqual(normalize_user_page(f'https://{host}/wiki/User:Example'),f'https://{host}/wiki/User:Example')
 def test_reject_non_user_urls_and_injection(self):
  urls=['','someone@example.com','http://commons.wikimedia.org/wiki/User:Example',
   'https://commons.wikimedia.org.evil.example/wiki/User:Example','https://example.com/wiki/User:Example',
   'https://commons.wikimedia.org/wiki/Main_Page','https://commons.wikimedia.org/wiki/User:',
   'https://commons.wikimedia.org/wiki/User:Example\r\nX:1','https://commons.wikimedia.org/wiki/User:Example%0AInjected',
   'https://commons.wikimedia.org/wiki/User:Example%250AInjected','https://name@commons.wikimedia.org/wiki/User:Example',
   'https://commons.wikimedia.org:443/wiki/User:Example','https://commons.wikimedia.org/wiki/User:Example?x=y']
  for url in urls:
   with self.subTest(url=url),self.assertRaises(ValueError): normalize_user_page(url)
 def test_persist_reload_and_remove_legacy_email(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'policy.json'
   saved=save_policy(path,{'contact':'old@example.com','commons_api_terms_reviewed':True},URL)
   reloaded=json.loads(path.read_text(encoding='utf-8'))
   self.assertEqual(reloaded,saved); self.assertEqual(saved_user_page(reloaded),URL)
   self.assertNotIn('contact',reloaded); self.assertNotIn('old@example.com',path.read_text())
   self.assertTrue(reloaded['commons_api_terms_reviewed'])
 def test_legacy_url_migration_email_not_reused(self):
  self.assertEqual(saved_user_page({'contact':URL}),URL)
  self.assertEqual(saved_user_page({'contact':'old@example.com'}),'')
 def test_actual_request_header_for_query_and_image(self):
  with tempfile.TemporaryDirectory() as tmp:
   client=collector.Client(Path(tmp),build_user_agent(URL),delay=0)
   response=MagicMock(); response.__enter__.return_value.read.return_value=b'{"query":{}}'
   with patch('urllib.request.urlopen',return_value=response) as opener:
    client.query({'action':'query','format':'json'})
    client.get('https://upload.wikimedia.org/test.jpg')
   self.assertEqual(opener.call_count,2)
   for call in opener.call_args_list:
    self.assertEqual(call.args[0].get_header('User-agent'),build_user_agent(URL))
 def test_cli_uses_same_header_builder(self):
  with patch('sys.argv',['collector.py','--script','script.txt','--output','out','--wikimedia-user-page',URL]),patch.object(collector,'run') as run:
   collector.main()
  self.assertEqual(run.call_args.args[0].user_agent,build_user_agent(URL))
 def test_missing_cli_contact_stops_before_network(self):
  with patch('sys.argv',['collector.py','--script','script.txt','--output','out']),patch.object(collector,'run') as run,patch('sys.stderr'):
   with self.assertRaises(SystemExit): collector.main()
   run.assert_not_called()

if __name__=='__main__': unittest.main()
