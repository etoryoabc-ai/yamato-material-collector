# Action APIとrobots判定の調査（2026-11-01）

## 結論と修正範囲

v0.4の `CommonsSource.fetch` は全リクエストへ `RobotFileParser.can_fetch` を実行し、正式なAction APIをWebページ巡回と同じ経路で拒否していた。これはサーバーからの拒否ではなく、HTTP送信前のアプリ内判定だった。

公式Robot policyは取得経路に応じた規則を定め、Action API専用の節で未認証クライアントの逐次通信や遅い応答後の待機を規定している。API Usage Guidelinesもその条件内の利用を案内し、通常のAPI利用について一律の事前許可制とはしていない。Imageinfo文書は `action=query` による画像情報取得を正式機能として説明している。

v0.5は、その文書化された用途に限定したAPIクライアントとして、APIとWeb巡回を分離する。robotsを全URLで無効にする設定は設けない。サイトのrobots全般が無効という主張でも、特別なアクセス許可を取得したという主張でもない。通常ページ巡回や `/w/index.php` は行わない。APIが返した原本・標準サムネイルを取得する際には画像配信先のrobotsとMedia API規則を適用する。

## 公式資料

- Robot policy: https://wikitech.wikimedia.org/wiki/Robot_policy （Website / Action API / Media APIの各節）
- API Usage Guidelines: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines
- API Etiquette: https://www.mediawiki.org/wiki/API:Etiquette
- Imageinfo: https://www.mediawiki.org/wiki/API:Imageinfo
- Bot用APIの説明: https://www.mediawiki.org/wiki/Manual:Creating_a_bot#APIs_for_bots
- User-Agent: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
- 標準サムネイル: https://www.mediawiki.org/wiki/Common_thumbnail_sizes
- 画像robots: https://upload.wikimedia.org/robots.txt

原文のAPI専用条件を実装へ反映する判断であり、公式文書に存在しない「robots.txt全般の免除」を引用したものではない。

## 通信比較

| 項目 | v0.3 | v0.4 | v0.5 |
|---|---|---|---|
| エンドポイント | commons.wikimedia.org/w/api.php | 同左 | 同左 |
| 検索方式 | action=query / generator=search / imageinfo | 同左 | 同左（パラメータ許可リスト） |
| API送信前のrobots判定 | なし | 全APIへ適用し停止 | API専用規則で検証。Web巡回の判定と分離 |
| Web巡回 | なし | なし | 任意URL要求を明示拒否 |
| メディアrobots | 個別確認ゲート | 適用 | 適用維持 |
| User-Agent | v0.3＋利用者URL | v0.4＋利用者URL | v0.5＋利用者URL（正しい識別・偽装なし） |
| 待機・形式 | 逐次1秒 | 逐次1.1秒 | 逐次1.1秒、遅いAPI応答後5秒、gzip、標準330pxサムネイル、メディア2MB/秒以下 |

v0.3の候補10件成功はユーザー報告として受領。v0.5は比較用に同じ検索パラメータ（Edo map、gsrlimit=10、namespace=6、imageinfo）を実行し、実測結果を別ファイルへ保存する。過去と同一の検索結果・件数になる保証はしない。候補件数を画像取得枚数とは報告しない。

## 実際の拒否は引き続き停止

401/403は即時停止、429/503はRetry-Afterに従う限定再試行。長い待機要求・再試行上限・maxlag/ratelimitedの継続では実行を停止。UA変更、別ホストへの代替要求、ログイン回避、プロキシの迂回はしない。ネットワークに接続できない場合も実測0枚を記録する。
