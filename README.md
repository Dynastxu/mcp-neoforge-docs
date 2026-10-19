# mcp-neoforge-docs

本地离线的 NeoForge 文档 MCP 服务器。把仓库里的 `neoforge-docs/`
建成一个 SQLite FTS5 索引，通过 stdio 暴露 6 个检索工具给任意 MCP 客户端。

## 依赖：

- Python 3.12
- mcp
- pyyaml

## 快速开始

```powershell
# 1) 安装（可编辑模式）
uv pip install --python .venv\Scripts\python.exe -e .

# 2) 建索引（首次或文档更新后）
.\.venv\Scripts\neoforge-docs-index.exe

# 3) 命令行试查
.\.venv\Scripts\neoforge-docs-search.exe "custom armor" --limit 3

# 4) 启动 MCP（stdio，客户端会自动拉起）
.\.venv\Scripts\neoforge-docs-mcp.exe
```

服务器启动时会自动检查语料指纹（文件数、大小、mtime），过期就重建，无需手动干预。

## 接入客户端

解释器路径和仓库路径都跟本机绑定，用生成器按当前解释器 `sys.executable` 和仓库位置实时产出：

```powershell
# 打印配置（mcpServers 格式，多数 stdio 客户端通用）
.\.venv\Scripts\python.exe -m neoforge_docs_mcp.setup_config

# 写入客户端要求的配置文件
.\.venv\Scripts\python.exe -m neoforge_docs_mcp.setup_config --output <config.json> --force

# VS Code 风格（servers + type: stdio）
.\.venv\Scripts\python.exe -m neoforge_docs_mcp.setup_config --client vscode
```

生成结果（`<repo>` 为当前仓库绝对路径）：

```json
{
  "mcpServers": {
    "neoforge-docs": {
      "command": "<repo>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "neoforge_docs_mcp"],
      "env": { "NEOFORGE_DOCS_ROOT": "<repo>\\neoforge-docs" }
    }
  }
}
```

把这段 JSON 放进客户端自己的 MCP 配置（Cursor 的 `~/.cursor/mcp.json`、
VS Code 的 `.vscode/mcp.json`），或按客户端字段填 `command` / `args` / `env`。
`NEOFORGE_DOCS_ROOT` / `NEOFORGE_DOCS_DB` 可覆盖文档目录与索引位置。

### DSH

`integrations/dsh/` 是一个 DSH profile bundle，通过 `@deepseek-ai/dsh-mcp-client`
以 stdio 拉起本服务器，工具名形如 `mcp__neoforge-docs__search_docs`。
`cordis.patch.yml` 里写的是本机解释器与仓库的绝对路径，仓库搬家后要同步修改，
再重新安装：

```powershell
# 在 DSH 里重新安装该 bundle（target 为绝对目录；已装过会原地覆盖）
# plugin_manager install_bundle "C:\Users\dynas\Documents\Code\mcp-neoforge-docs\integrations\dsh"
```

安装后 DSH 的插件/连接列表里会多出「NeoForge 文档 MCP」一项。

## 工具

| 工具               | 作用                                                                                                                      |
|--------------------|---------------------------------------------------------------------------------------------------------------------------|
| `search_docs`      | 主入口：BM25 检索，返回 chunk 级片段、版本、URL；`version` 支持 `current` / `1.21.1` / `all`；`mode="api"` 只搜代码标识符 |
| `get_section`      | 取单节全文（anchor / 标题 / 标题片段均可定位），省 token 主力                                                             |
| `get_doc`          | 取整页 markdown + 标题大纲（15k 字符级别的页慎用）                                                                        |
| `find_symbol`      | API 名精确/子串查找，如 `Item.Properties#of`                                                                              |
| `list_docs`        | 列出版本内全部页面（标题、分组、URL）                                                                                     |
| `compare_versions` | 同一页面跨版本 diff，做迁移/版本差异问题                                                                                  |

中文提问可直接传入（内置常用术语映射，如 注册→register、数据组件→data component），
但英文关键词检索质量更高，server instructions 里也这样提示模型。

## 结构

```
src/neoforge_docs_mcp/
  config.py   路径、版本标签、各文档分区（docs/toolchain/user/modpack）的路由前缀
  parse.py    去 frontmatter、展开引用式链接、剥离 JSX、抽 H1 标题
  chunk.py    按 H2/H3 切块，代码块与表格不切分，单块上限 ~1100 token
  index.py    建 SQLite：docs / chunks / chunks_fts / symbols / links / meta
  search.py   BM25 + 标题加权 + 版本去重 + 符号查询 + 跨版本 diff
  server.py   MCPServer（6 个 tool）
data/         索引产物（已 gitignore）
```

索引失败回退：`mode=api` 与普通检索都走 FTS5；如果目标机器的 sqlite3 没编进 FTS5，
建索引时会直接报 `no such module: fts5`，此时改用官方 CPython 或安装带 FTS5 的 sqlite。

## 更新文档

```powershell
git submodule update --remote neoforge-docs   # 拉取最新文档
.\.venv\Scripts\neoforge-docs-index.exe       # 重建索引
```

## 测试

```powershell
.\.venv\Scripts\python.exe tests\check_search.py          # 检索质量回归
.\.venv\Scripts\python.exe tests\test_server_inprocess.py # 工具注册 + 参数 schema + 调用
.\.venv\Scripts\python.exe tests\probe_stdio.py           # 真实 stdio 管道 JSON-RPC
```

`tests/test_mcp_e2e.py` 用 MCP 官方 client 跑完整握手。