# 大和噺 歴史映像素材収集システム（最小構成）

Windows / Python 3.10以降。追加パッケージ不要。ZIPを展開し、そのフォルダでPowerShellを開いて実行します。原稿はUTF-8 TXT（BOM可）。CP932の場合は `--encoding cp932` を指定します。

## 初回実行

```powershell
py -3 collector.py --script "江戸_テスト原稿.txt" --output "動画別出力\江戸_調査01"
```

実原稿に差し替える場合は `--script "完成原稿.txt"` に変更します。空でない出力フォルダは上書きしません。毎回新しいフォルダ名を指定してください。実行は接続確認と検索計画生成から始まります。

## Commonsで候補を検索

現行の公式条件を自分で確認し、`policy.example.json` を `policy.json` に複製して、確認したURL・日時と `commons_api_terms_reviewed: true` を記録します。未確認のままtrueにしないでください。

公式確認先（この環境では本文未取得・現行条件未検証）：

- https://www.mediawiki.org/wiki/API:Etiquette
- https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
- https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- https://commons.wikimedia.org/wiki/Commons:Licensing

```powershell
py -3 collector.py --script "完成原稿.txt" --output "動画別出力\江戸_候補01" --policy policy.json --queries 4 --limit 4 --user-agent "YamatoMaterials/0.1 (自分の連絡先URLに置換)"
```

API応答を `証跡/` に保存します。日本語・英語検索語はシーンJSONに出力され、`--queries` 件を各シーンの先頭から検索します。既定値2では英語検索が省略されることがあるため、両方検索する場合は増やしてください。結果は検索一致候補であり、原資料・年代・内容の正しさを保証しません。情報不在は「不明」です。

## 個別確認と取得

`素材一覧.csv` の素材IDを使い `review.example.json` を参考に `review.json` を作ります。個別出典ページ、権利表示、商用利用、必要クレジット、制作年代と描写内容、原資料か復元図かを確認してください。確認URL・日時・担当者・史実上の注意点を記録し、確認できた場合だけ2つのboolをtrueにします。複数ライセンスや国別PD条件など曖昧なケースは保留してください。APIのPD表示だけでは取得しません。

```powershell
py -3 collector.py --script "完成原稿.txt" --output "動画別出力\江戸_取得01" --policy policy.json --review review.json --download --queries 4 --user-agent "YamatoMaterials/0.1 (自分の連絡先URLに置換)"
```

同じ検索を再実行するため、検索結果が変化し承認済みIDが出現しなければ未取得です。検索スナップショットからの再開機能は未実装。CC BY-SAはMVPでは対象外。CC BYは正確なライセンスURLと個別確認が必要です。クレジットは出典一覧から動画説明欄等に転記し、実際のライセンス条件に従ってください。

原本JPEG/PNGをそのまま保存し、サイズ上限80MB、SHA256完全一致で重複排除します。拡張子・シグネチャ検査のみで画像の完全デコード検証はしません。HTMLは原画像をCSS縮小表示し、クリックで原画像を開きます。プレビュー生成による原本改変はありません。Resolveのメディアプールに各素材フォルダを読み込んでください。タイムラインの自動生成は対象外です。

## 国内機関

NDL、国立公文書館、東京都立図書館は公式入口への接続確認と検索計画の出力までです。資料本文・規約・API仕様を検証できなかったため、自動収集アダプターは実装していません。NDLサーチSRUは書誌検索の検討先であり、画像利用許諾APIではありません。国内機関の個別資料をCommonsのライセンスで代用承認しないでください。

## 第1回テスト結果（2026-10-30）

実原稿は未提供のため、同梱の明示的なテスト原稿で6シーンを処理。5接続先すべて `Operation not permitted`。ネットワークポリシーの許可先に対象アーカイブがありません。制限回避なし。候補発見0件、画像取得0件、利用条件未確認候補0件（未検索先の実在候補数は不明）。すべて未充足です。実資料の収集成功とライブAPIの互換性は未検証です。

`第1回_大和噺_素材収集/` に結果・接続エラー・検索計画を保存しました。原稿の史実や「100万人」という数値を検証した結果ではありません。利用条件の本文を取得できていないため、実行は規約確認ゲートで停止しています。

外部接続が許可されたWindows環境で再実行するか、クラウド環境設定で対象の公式ドメインと画像配信ドメインを許可する必要があります。現時点の最小構成はCommons専用であり、すべての要件を満たす完成版ではありません。

## 検証

```powershell
py -3 -m unittest -v test_collector.py
```

模擬データにより、非商用ライセンス拒否、確認記録欠落時の拒否、原文位置、未承認画像への非アクセス、原本バイト保持、重複保存抑止を検証します。模擬画像は実史料ではなく、一時フォルダ内だけで使用します。HTTP再試行・自動再開・近似重複・高度な意味解析・国内API・IIIF/TIFF/PDF対応は今後の拡張です。接続失敗時に別経路へ自動迂回しません。
