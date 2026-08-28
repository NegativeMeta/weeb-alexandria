# Weeb Alexandria

## 项目简介

Weeb Alexandria 是一个项目，旨在将动漫、御宅族、Weeb、NSFW 和 SFW 相关知识统一到一个简单且可在本地运行的知识库中。

它可以让本地 AI 智能体访问与用户问题相关的可靠信息，帮助智能体获取有依据的数据，并减少其在这一知识领域中的幻觉。

该项目整合了标签定义、别名、蕴含关系、角色、作品系列、艺术家、特征、外观/服装卡片、数据来源，以及其他适用于动漫研究和图像生成的有用信息。

## 当前快照

当前 `tag_library.db` 快照大约包含：

- **142 万个唯一标签**
- **151 万条标签记录**，来自多个数据源
- **673,000 条 wiki 条目**
- **592,000 条包含定义的 wiki 条目**
- **38,000 个标签别名**
- **25,000 个启用中的别名**
- **24,000 条标签蕴含关系**
- **21,000 条启用中的蕴含关系**

数据库大小：约 **866 MB**。

快照日期：**2026-08-25**。

这些统计数据对应已发布的数据库快照，可能会在不同版本之间发生变化。

## 快速开始

### 1. 获取项目

将仓库克隆或下载到本地目录：

```bash
git clone https://github.com/NegativeMeta/weeb-alexandria.git "<WEEB_ALEXANDRIA_DIR>"
```

#### 替代方式：不使用 Git CLI

在浏览器中打开 GitHub 仓库：

```text
https://github.com/NegativeMeta/weeb-alexandria
```

选择 **Code → Download ZIP**，解压文件，并将解压后的文件夹作为 `<WEEB_ALEXANDRIA_DIR>`。

### 2. 下载数据库

从 Hugging Face 下载公开的数据库快照：

```bash
hf download negativemeta/weeb-alexandria tag_library.db \
  --repo-type dataset \
  --local-dir "<WEEB_ALEXANDRIA_DIR>"
```

#### 替代方式：不使用 Hugging Face CLI

在浏览器中打开数据集：

```text
https://huggingface.co/datasets/negativemeta/weeb-alexandria
```

打开 **Files and versions**，下载 `tag_library.db`，并将其放入 `<WEEB_ALEXANDRIA_DIR>`。

数据库文件必须位于：

```text
<WEEB_ALEXANDRIA_DIR>\tag_library.db
```

### 2.1 构建角色上下文索引（推荐）

派生索引可以通过分离角色名称和作品上下文来解析类似 `Rika Higurashi` 的查询。它还会记录规范作品关系，例如：

```text
furude_rika → higurashi_no_naku_koro_ni
```

使用以下命令构建或重新构建：

```bash
.venv/Scripts/python.exe scripts/build_context_index.py
```

该命令会创建 `data/character_context.sqlite`，其中包含 `character_context`、`character_work_context` 和 `context_index_metadata` 表。该索引是本地生成文件，并且特意排除在 Git 之外；替换 `tag_library.db` 后应重新生成。元数据会记录源数据库大小、SHA-256、sidecar 状态、行数和索引模式版本。MCP 会忽略过期或不完整的上下文索引，并回退到常规解析路径。

### 2.2 构建标签搜索索引（推荐）

可选的 FTS5 索引可以加速标签名称和别名的部分搜索。替换 `tag_library.db` 后使用以下命令构建或重新构建：

```bash
.venv/Scripts/python.exe scripts/build_search_index.py
```

该命令会创建 `data/tag_search.sqlite`，保存源数据库的 SHA-256 和已索引行数，并且特意排除在 Git 之外。MCP 会验证这些值（包括 SQLite sidecar 文件）；如果索引缺失、过期、不完整、格式错误或无法打开，就会自动回退到主 SQLite 查询。

### 3. 连接到 Hermes

注册本地 stdio MCP 服务器：

```bash
hermes mcp add weeb-alexandria \
  --command "C:\\Windows\\System32\\cmd.exe" \
  --args /d /c "<WEEB_ALEXANDRIA_DIR>\\run.bat"
```

### 4. 连接到 LM Studio

打开 **Program → Install → Edit mcp.json**，加入：

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

开始新对话，并确认六个 Weeb Alexandria 工具可用。

### 5. 在对话中试用

你不需要手动调用 MCP 工具。可以直接用自然语言向模型提问，例如：

```text
告诉我 Inugami Korone 是什么样的。你可以使用 Weeb Alexandria 查询角色信息和相关标签。
```

模型可以选择合适的工具，例如 `get_character`、`search_characters` 或 `search_knowledge`，然后用普通语言解释结果。

### 多标签搜索

如果 `search_knowledge` 收到的是多个连在一起的标签，例如 `blushing red face`，它可能返回 `query_mode: "multi_tag"`、`tag_library.query_parts` 中的独立部分，以及顶层的 `query_recommendation`。智能体应读取 `query_recommendation.queries`，针对每个查询分别调用一次 `search_knowledge`，然后再合并这些独立搜索的结果。

```json
{
  "query_recommendation": {
    "action": "search_each_tag_separately",
    "queries": ["blushing", "red face"]
  }
}
```

已知的多词标签（例如 `red face` 和 `closed mouth`）会保持完整。角色或作品系列的上下文查询（例如 `Fuwawa Hololive` 和 `Mococo Hololive`）也会保留，不会被拆分。

## 外观与服装卡片

外观数据分为基础外观以及彼此独立的服装/变体档案。规范数据位于 `tag_library.db`：

- `character_appearance_profiles`：每个基础外观或服装变体一行。
- `character_appearance_features`：每个外观 facet/tag 一行，例如 `hair`、`eyes`、`dress` 或 `footwear`。
- `character_appearance_sources`：Danbooru、Gelbooru、参考帖子和已审核种子的来源目录。
- `character_appearance_feature_sources`：每个特征的证据、计数和冲突。

可选的 `data/character_appearance.sqlite` 保存从已捕获 wiki/帖子样本生成的观测值和 `pending` 候选。候选必须经过明确审核和提升，才会作为 MCP 的规范事实公开。

```bash
.venv/Scripts/python.exe scripts/build_appearance_candidates.py \\
  --character inugami_korone

.venv/Scripts/python.exe scripts/promote_appearance.py \\
  --input seeds/appearance/inugami_korone.json
```

MCP 工具为 `get_character_appearance(character, variant=None, include_evidence=True, limit=100)`。例如 `get_character_appearance("inugami_korone")` 会返回基础外观以及已审核的 `1st_costume`、`street` 和 `new_year` 档案，不会混合不同服装的特征。

## 项目结构

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   活跃的 MCP 服务器
├── .venv/                  MCP 使用的 Python 运行环境
├── tag_library.db          统一的主知识库
├── raw/                    下载的原始来源数据
│   ├── animadex/           AnimaDex 原始数据库
│   ├── appearance/         已捕获的外观 wiki/帖子
│   ├── danbooru/
│   ├── e621/               已处理的 wiki 和标签数据
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                审计报告和人工审核列表
├── scripts/                数据维护和融合脚本
├── seeds/appearance/       已审核的外观种子
├── data/character_context.sqlite
│                           派生角色上下文索引（本地）
├── data/character_appearance.sqlite
│                           派生外观观测/候选数据库（本地）
├── data/tag_search.sqlite
│                           可选的 FTS5 标签搜索索引（本地）
├── data/backups/           数据库备份
├── CREDITS.md              致谢和来源信息
├── run.bat                 MCP 启动脚本
└── README.md
```

原始 AnimaDex Web 应用、旧版 MCP 和视觉资源不属于当前运行环境。它们被保存在以下位置，以便以后恢复：

```text
C:\Users\johin\Code_Library\AI\WeebAlexandria_legacy_archive
```

## 数据库

`tag_library.db` 包含：

- 标签和分类。
- Danbooru、e621 和 Gelbooru 的定义。
- 别名和蕴含关系。
- 标记为 `lang='llm'` 的合成定义。
- Weeb Alexandria 自有的结构化角色档案和特征映射（`character_profiles`、`trait_definitions`、`character_traits`）。
- 规范的外观/服装档案和 feature 级来源信息（`character_appearance_profiles`、`character_appearance_features`、`character_appearance_sources`、`character_appearance_feature_sources`）。
- 艺术家和作品搜索使用全局 `tags` 表。

`raw/animadex/animadex.db` 保留原始名称，仅用于审计和恢复初始种子。活跃的 MCP 不会打开它，也不需要任何旧版结构化数据表。

历史种子和迁移记录见 [`docs/ANIMADEX_VALUE_ANALYSIS.md`](docs/ANIMADEX_VALUE_ANALYSIS.md)。`search_knowledge` 会在 `entities` 命名空间下返回结构化结果。

## MCP

启动脚本：

```text
run.bat
```

可用工具：

- `search_knowledge`
- `get_tag_knowledge`
- `search_characters`
- `get_character`
- `get_character_appearance`
- `get_sources_status`

Weeb Alexandria 在本地执行查询，不需要运行原始的 AnimaDex Flask 服务器。

## 术语表

请参阅 [`GLOSSARY.zh-CN.md`](GLOSSARY.zh-CN.md) 了解数据库内容和 MCP 工具的简单说明。英文、西班牙语和日语版本位于 [`GLOSSARY.md`](GLOSSARY.md)、[`GLOSSARY.es.md`](GLOSSARY.es.md) 和 [`GLOSSARY.ja.md`](GLOSSARY.ja.md)。

## 致谢和数据来源

- [AnimaDex](https://github.com/zetaneko/AnimaDex) — 小型结构化种子的历史来源；保留用于署名和迁移溯源，但不是活跃运行时依赖。
- [Danbooru](https://danbooru.donmai.us/) — wiki、标签元数据、别名、蕴含关系和流行度数据。
- [e621](https://e621.net/) — wiki 和标签元数据。
- [Gelbooru](https://gelbooru.com/) — wiki 和标签元数据。
- [`CREDITS.md`](CREDITS.md) — 完整的致谢、署名和来源说明。
