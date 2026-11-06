# 東京アフタヌーンティー調査仕様（Codex・GitHub用）

このパッケージは、ユーザー提供の調査仕様テキストから作成しています。

- `research_spec.md` — GitHubで読みやすい調査仕様。末尾にPythonコードも掲載しています。
- `build_html.py` — 元の調査仕様に埋め込まれていたHTML生成スクリプトを**コード変更なし**で抽出したものです。
- `original_prompt.txt` — 元のテキストの完全なコピー（UTF-8）。

## GitHubへの追加方法

ZIPを解凍し、これらのファイルをリポジトリにアップロードしてコミットしてください。
Codexには `research_spec.md` を読ませ、HTMLを生成するときは `build_html.py` を使うよう指示してください。

## HTMLの生成

調査結果JSON (`data_YYYY-MM-DD.json`) が用意できたら、次のように実行します。

```bash
python3 build_html.py data_YYYY-MM-DD.json
```

このパッケージには**調査結果JSON自体は含まれません**。Pythonファイルの構文チェックは済んでいますが、実データを使った実行検証は行っていません。

注意: 元の仕様にはChatGPTの会話内だけで成立するタスク管理・ファイル提示などの指示があります。GitHub Actions向け実装では相当するログ・アーティファクト等への置換が必要です。
