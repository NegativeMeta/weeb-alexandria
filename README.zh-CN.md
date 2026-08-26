# Weeb Alexandria

## 快速开始

### 1. 获取项目

将仓库克隆或下载到本地目录：

```bash
git clone https://github.com/NegativeMeta/weeb-alexandria.git "<WEEB_ALEXANDRIA_DIR>"
```

### 2. 下载数据库

从 Hugging Face 下载公开的数据库快照：

```bash
hf download negativemeta/weeb-alexandria tag_library.db \
  --repo-type dataset \
  --local-dir "<WEEB_ALEXANDRIA_DIR>"
```

数据库文件必须位于：

```text
<WEEB_ALEXANDRIA_DIR>\tag_library.db
```

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

打开一个新对话，并确认 Weeb Alexandria 的五个工具已经可用。

## 项目简介

Weeb Alexandria 是一个项目，旨在将动漫、御宅族、Weeb、NSFW 和 SFW 相关知识统一到一个简单且可在本地运行的知识库中。

它可以让本地 AI 智能体访问与用户问题相关的可靠信息，帮助智能体获取有依据的数据，并减少其在这一知识领域中的幻觉。

该项目整合了标签定义、别名、蕴含关系、角色、作品系列、艺术家、特征、数据来源，以及其他适用于动漫研究和图像生成的有用信息。

## 项目结构

```text
WeebAlexandria/
├── weeb_alexandria_mcp/   活跃的 MCP 服务器
├── .venv/                  MCP 使用的 Python 运行环境
├── tag_library.db          统一的主知识库
├── raw/                    下载的原始来源数据
│   ├── animadex/           AnimaDex 原始数据库
│   ├── danbooru/
│   ├── e621/               已处理的 wiki 和标签数据
│   ├── gelbooru/
│   └── danbooru_wiki_extra/
├── reports/                审计报告和人工审核列表
├── scripts/                数据维护和融合脚本
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
- 从 AnimaDex 迁移的角色、特征、艺术家和 LoRA 数据表。

`raw/animadex/animadex.db` 使用原始名称保存，作为参考副本。活跃的 MCP 使用 `tag_library.db` 中迁移后的 AnimaDex 数据表。

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
- `get_sources_status`

Weeb Alexandria 在本地执行查询，不需要运行原始的 AnimaDex Flask 服务器。

原始项目和数据来源请参阅 `CREDITS.md`。
