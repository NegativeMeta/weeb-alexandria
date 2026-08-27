# Weeb Alexandria

## プロジェクトについて

Weeb Alexandria は、アニメ、オタク、Weeb、NSFW、SFW に関する知識を、シンプルでローカルに運用できる単一のナレッジベースへ統合するプロジェクトです。

ローカル AI エージェントが質問に関連する信頼性の高い情報へアクセスできるようにし、根拠のあるデータの取得を助けることで、この知識分野におけるハルシネーションを減らすことを目的としています。

このプロジェクトには、タグの定義、エイリアス、包含関係、キャラクター、作品シリーズ、アーティスト、特徴、情報源、そしてアニメ研究や画像生成に役立つその他の情報が統合されています。

## 現在のスナップショット

現在の `tag_library.db` スナップショットには、およそ以下が含まれています。

- **142 万件のユニークタグ**
- 複数のソースにわたる **151 万件のタグレコード**
- **673,000 件の wiki エントリ**
- **592,000 件の定義付き wiki エントリ**
- **38,000 件のタグエイリアス**
- **25,000 件の有効なエイリアス**
- **24,000 件のタグ包含関係**
- **21,000 件の有効な包含関係**

データベースサイズ：約 **866 MB**。

スナップショットの日付：**2026-08-25**。

これらの数値は公開済みデータベースのスナップショットに基づいており、リリースごとに変わる可能性があります。

## クイックスタート

### 1. プロジェクトを取得する

リポジトリをクローンするか、ソースファイルをローカルディレクトリにダウンロードします。

```bash
git clone https://github.com/NegativeMeta/weeb-alexandria.git "<WEEB_ALEXANDRIA_DIR>"
```

#### 代替方法：Git CLI を使わない場合

ブラウザで GitHub リポジトリを開きます。

```text
https://github.com/NegativeMeta/weeb-alexandria
```

**Code → Download ZIP** を選択してアーカイブを展開し、展開したフォルダーを `<WEEB_ALEXANDRIA_DIR>` として使用します。

### 2. データベースをダウンロードする

Hugging Face から公開されているデータベーススナップショットをダウンロードします。

```bash
hf download negativemeta/weeb-alexandria tag_library.db \
  --repo-type dataset \
  --local-dir "<WEEB_ALEXANDRIA_DIR>"
```

#### 代替方法：Hugging Face CLI を使わない場合

ブラウザでデータセットを開きます。

```text
https://huggingface.co/datasets/negativemeta/weeb-alexandria
```

**Files and versions** を開き、`tag_library.db` をダウンロードして `<WEEB_ALEXANDRIA_DIR>` に配置します。

データベースは次の場所に配置してください。

```text
<WEEB_ALEXANDRIA_DIR>\tag_library.db
```

### 2.1 キャラクター・コンテキスト索引を構築する（推奨）

派生索引は、キャラクター名と作品のコンテキストを分離することで、`Rika Higurashi` のようなクエリを解決しやすくします。また、次のような正規作品の関係も記録します。

```text
furude_rika → higurashi_no_naku_koro_ni
```

次のコマンドで構築または再構築します。

```bash
.venv/Scripts/python.exe scripts/build_context_index.py
```

`character_context`、`character_work_context`、`context_index_metadata` テーブルを含む `data/character_context.sqlite` が作成されます。この索引はローカルで生成されるファイルで、Git には意図的に含めていません。`tag_library.db` を置き換えた後は再構築してください。メタデータには、元データベースのサイズと索引スキーマのバージョンが記録されます。

### 3. Hermes に接続する

ローカルの stdio MCP サーバーを登録します。

```bash
hermes mcp add weeb-alexandria \
  --command "C:\\Windows\\System32\\cmd.exe" \
  --args /d /c "<WEEB_ALEXANDRIA_DIR>\\run.bat"
```

### 4. LM Studio に接続する

**Program → Install → Edit mcp.json** を開き、次の設定を追加します。

```json
{
  "mcpServers": {
    "weeb-alexandria": {
      "command": "C:\\Windows\\System32\\cmd.exe",
      "args": [
        "/d",
        "/c",
        "<WEEB_ALEXANDRIA_DIR>\\run.bat"
      ]
    }
  }
}
```

新しいチャットを開始し、Weeb Alexandria の 5 つのツールが利用可能であることを確認してください。

### 5. 会話で試す

MCP ツールを手動で呼び出す必要はありません。モデルに自然な文章で質問できます。例えば：

```text
Inugami Korone がどのようなキャラクターか教えてください。Weeb Alexandria を使ってキャラクター情報と関連タグを確認しても構いません。
```

モデルは `get_character`、`search_characters`、`search_knowledge` など適切なツールを選び、結果を通常の言葉で説明できます。

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
├── data/character_context.sqlite
│                           派生キャラクター・コンテキスト索引（ローカル）
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
- Weeb Alexandria 所有の構造化キャラクタープロファイルと特徴マッピング（`character_profiles`、`trait_definitions`、`character_traits`）。
- アーティストと作品の検索はグローバルな `tags` テーブルを使用します。

`raw/animadex/animadex.db` は初期シードの監査・復旧専用として元の名前のまま保存されています。アクティブな MCP はこのファイルを開かず、旧構造化テーブルにも依存しません。

履歴シードと移行記録は [`docs/ANIMADEX_VALUE_ANALYSIS.md`](docs/ANIMADEX_VALUE_ANALYSIS.md) に記載しています。`search_knowledge` は構造化結果を `entities` 名前空間で返します。

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

## 用語集

データベースの内容と MCP ツールの簡単な説明は [`GLOSSARY.ja.md`](GLOSSARY.ja.md) を参照してください。英語、スペイン語、中国語簡体字版は [`GLOSSARY.md`](GLOSSARY.md)、[`GLOSSARY.es.md`](GLOSSARY.es.md)、[`GLOSSARY.zh-CN.md`](GLOSSARY.zh-CN.md) です。

## クレジットと情報源

- [AnimaDex](https://github.com/zetaneko/AnimaDex) — 小規模な構造化シードの履歴上の情報源。帰属と移行の出所のために保持しており、アクティブなランタイム依存ではありません。
- [Danbooru](https://danbooru.donmai.us/) — wiki、タグメタデータ、エイリアス、包含関係、人気度データ。
- [e621](https://e621.net/) — wiki とタグメタデータ。
- [Gelbooru](https://gelbooru.com/) — wiki とタグメタデータ。
- [`CREDITS.md`](CREDITS.md) — 謝辞、帰属表示、情報源の詳細。
