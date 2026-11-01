"""Real connectivity probe; never changes proxy or retries via another route."""
import argparse
import json
from pathlib import Path
from commons_source import CommonsSource

def probe(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    client=CommonsSource(folder,'YamatoMaterialsBot/0.4 (https://github.com/etoryoabc-ai/yamato-material-collector; network diagnostic)')
    results=[]
    for url in ['https://commons.wikimedia.org/robots.txt','https://commons.wikimedia.org/w/api.php?action=query&format=json&meta=siteinfo','https://upload.wikimedia.org/robots.txt']:
        try:
            data=client.fetch(url,robots=not url.endswith('/robots.txt'))
            results.append({'url':url,'status':'取得成功','bytes':len(data)})
        except Exception as e:results.append({'url':url,'status':'失敗','error':str(e)})
    (folder/'ネットワーク検証.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2));return results
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='results/接続検証');args=parser.parse_args();probe(args.output)
