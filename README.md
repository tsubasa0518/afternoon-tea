# 東京アフタヌーンティー

候補リストの公開ページを毎週読み、確認できたアフタヌーンティーをGitHub Pagesに掲載します。調査が途中でも集めた結果で掲載処理へ進み、保存した表示データから固定HTMLを生成します。

[公開サイト](https://tsubasa0518.github.io/afternoon-tea/) · [安全規則](AGENTS.md) · [週次手順と数値](docs/weekly_procedure.md)

```mermaid
flowchart TD
    A[既存Claude Routine] --> B[最新mainの指示を読む]
    B --> C[begin: 前回を控え、今週を開始]
    C --> D[fetch: 候補リストを順に読む]
    D --> E[build: 引き継ぎ・表示データ作成・検証]
    E --> F[report: 集計して週次PRを提出]
    F --> G[Actions: mainのコードで審査]
    G --> H[マージ・HTML公開・公開確認]
```
