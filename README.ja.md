# Weeb Alexandria

Weeb Alexandria は、アニメ、オタク、Weeb、NSFW、SFW に関する知識を、シンプルでローカルに運用できる単一のナレッジベースへ統合するプロジェクトです。

ローカル AI エージェントが質問に関連する信頼性の高い情報へアクセスできるようにし、根拠のあるデータの取得を助けることで、この知識分野におけるハルシネーションを減らすことを目的としています。

このプロジェクトには、タグの定義、エイリアス、包含関係、キャラクター、作品シリーズ、アーティスト、特徴、情報源、そしてアニメ研究や画像生成に役立つその他の情報が統合されています。

## 構成

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   アクティブな MCP サーバー
├── .venv/                  MCP 用の Python 実行環境
├── tag_library.db          統合ナレッジベース
├── raw/                    ダウンロードしたソースデータ
│   ├── animadex/           AnimaDex の元データベース
│   ├── danbooru/
│   ├── e621/               処理済みの wiki とタグデータ
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                監査結果と手動レビューリスト
├── scripts/                データ保守・統合スクリプト
├── data/backups/           データベースのバックアップ
├── CREDITS.md              クレジットと情報源
├── run.bat                 MCP 起動スクリプト
└── README.md
```

AnimaDex の元の Web アプリケーション、旧 MCP、画像アセットは現在のランタイムには含まれていません。後から復元できるよう、以下の場所に保存されています。

```text
C:\Users\johin\Code_Library\AI\WeebAlexandria_legacy_archive
```

## データベース

`tag_library.db` には以下が含まれています。

- タグとカテゴリー。
- Danbooru、e621、Gelbooru の定義。
- エイリアスと包含関係。
- `lang='llm'` としてマークされた合成定義。
- AnimaDex から移行したキャラクター、特徴、アーティスト、LoRA のテーブル。

`raw/animadex/animadex.db` は元の名前のまま参照用コピーとして保存されています。アクティブな MCP は `tag_library.db` 内に移行された AnimaDex のテーブルを使用します。

## MCP

起動スクリプト：

```text
run.bat
```

利用可能なツール：

- `search_knowledge`
- `get_tag_knowledge`
- `search_characters`
- `get_character`
- `get_sources_status`

Weeb Alexandria はローカルでクエリを実行するため、元の AnimaDex Flask サーバーを起動する必要はありません。

元のプロジェクトと情報源については `CREDITS.md` を参照してください。
