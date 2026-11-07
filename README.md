# 東京アフタヌーンティー：毎週自動更新

Claude Code Routines（Cloud Scheduled Tasks）が毎週月曜07:17 JSTに調査・HTML/JSON生成・PR作成を行い、GitHub Actionsが3ファイル限定の技術検証、自動マージ、GitHub Pages公開を行います。Codexの定期実行は不要です。

公開URL: [東京アフタヌーンティー](https://tsubasa0518.github.io/afternoon-tea/)

- 更新対象: `site/index.html`, `site/research.json`, `site/search_failures.json`
- 自動取り込み: `.github/workflows/auto-merge-weekly.yml`
- 公開: `.github/workflows/deploy.yml`（マージ後に明示的に起動）
- 店舗数0・2や未確認情報が残る場合も、説明を含む正常なHTMLを公開します。情報は捏造しません。
- 予約・仮予約・決済は全面禁止。匿名の安全な公開ページの読み取りだけを行います。
- 元120店舗HTMLは`docs/index.html`に保管し、deploy.ymlはsite/index.htmlを公開する方式へ変更しています。

[最初の設定・運用・停止・復旧方法](developer_docs/weekly_automation.md)と[Claudeへ貼るプロンプト全文](developer_docs/claude_weekly_prompt.md)を参照してください。

```sh
python3 -m afternoon_tea.routine_site validate
python3 -m unittest discover -s tests -v
```

掲載前の日付確認は `python3 -m afternoon_tea.weekly_review` で実行できます。調査範囲・期間・検索機能の改善と、登録済みClaude Routineの指示文の更新方法は[運用手順書](developer_docs/weekly_automation.md#調査範囲期間検索操作の改善)を参照してください。自動マージ・公開の条件は変更していません。

以下の従来Python調査・品質判定は補助機能として残します。新しい週次公開の必須条件には使用しません。

---

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
