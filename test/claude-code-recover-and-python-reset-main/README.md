# Hare — Claude Code Python Port


# 家人们 我在做小型化移植到我机器人项目 所以重心都在机器人项目 请大佬见谅哈 当前是 opus4.6 写的 我没怎么测试 请见谅哈

Hare 是 [Anthropic Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (v2.1.88) 的 Python 移植版本。源代码从 TypeScript/React (Ink) 架构忠实翻译为 Python 3.11+，保留了原始的模块结构、业务逻辑和数据流，同时排除了所有 UI 层（`.tsx` / React / Ink 组件）。

## 项目概览

| 指标 | 数值 |
|------|------|
| Python 文件 | 1,310 |
| 代码行数 | 61,385 |
| 覆盖 TS 核心模块 | 1,172 / 1,131 (103%) |
| 导入错误 | 0 |

> 覆盖率超过 100% 是因为部分 TypeScript 模块在 Python 中被拆分为更细粒度的文件。

## 目录结构

```
hare/
├── bridge/          # IDE/扩展通信桥接 (30 files)
├── buddy/           # 上下文助手提示 (7 files)
├── cli/             # 结构化 IO、传输层、处理器 (23 files)
├── commands_impl/   # 斜杠命令实现 (/compact, /diff, /doctor 等) (105 files)
├── constants/       # 全局常量、系统提示片段、限制 (22 files)
├── entrypoints/     # CLI 入口、SDK 类型、MCP 服务 (18 files)
├── keybindings/     # 键绑定定义与解析 (14 files)
├── memdir/          # 内存目录 (CLAUDE.md) 管理 (9 files)
├── migrations/      # 配置迁移脚本 (14 files)
├── plugins/         # 插件加载器 (2 files)
├── query/           # 查询引擎依赖、停止钩子、token 预算 (5 files)
├── remote/          # WebSocket 远程会话管理 (5 files)
├── schemas/         # JSON Schema 定义 (3 files)
├── server/          # HTTP/WebSocket 服务器 (5 files)
├── services/        # 核心服务层 (160 files)
│   ├── analytics/       # 事件日志与遥测
│   ├── api/             # API 客户端、认证、限流
│   ├── auto_dream/      # 自动后台任务
│   ├── compact/         # 对话压缩
│   ├── extract_memories/ # 记忆提取
│   ├── lsp/             # LSP 服务器管理
│   ├── mcp/             # MCP 协议客户端
│   ├── oauth/           # OAuth 认证流
│   ├── session_memory/  # 会话记忆 (CLAUDE.md)
│   ├── team_memory_sync/ # 团队记忆同步
│   ├── tips/            # 上下文提示
│   ├── tools/           # 工具执行与流式处理
│   └── ...
├── skills/          # 技能加载与内置技能 (13 files)
├── state/           # 应用状态管理 (4 files)
├── task/            # 任务类型与管理器 (3 files)
├── tasks/           # 任务实现 (Shell/Dream/Teammate) (9 files)
├── tools_impl/      # 工具实现 (191 files)
│   ├── AgentTool/       # 子代理创建与管理
│   ├── BashTool/        # Shell 命令执行
│   ├── FileEditTool/    # 文件编辑 (sed/patch)
│   ├── FileReadTool/    # 文件读取
│   ├── FileWriteTool/   # 文件写入
│   ├── GlobTool/        # 文件搜索
│   ├── GrepTool/        # 内容搜索 (ripgrep)
│   ├── MCPTool/         # MCP 工具代理
│   ├── PowerShellTool/  # PowerShell 执行
│   ├── WebFetchTool/    # HTTP 请求
│   ├── WebSearchTool/   # 网络搜索
│   ├── TodoWriteTool/   # TODO 管理
│   └── ...              # 30+ 其他工具
├── types/           # 类型定义 (Message, Tool, Config 等) (12 files)
├── utils/           # 工具函数库 (630 files)
│   ├── bash/            # Bash 解析、引用、命令规格
│   ├── claude_in_chrome/ # Chrome 原生主机集成
│   ├── computer_use/    # 计算机使用工具
│   ├── deep_link/       # 深度链接解析
│   ├── git/             # Git diff/status/log
│   ├── hooks/           # 钩子系统
│   ├── model/           # 模型配置与选择
│   ├── permissions/     # 权限系统
│   ├── plugins/         # 插件管理
│   ├── secure_storage/  # 安全存储
│   ├── settings/        # 设置管理
│   ├── shell/           # Shell 提供者
│   ├── swarm/           # 多代理后端
│   ├── task/            # 任务输出与格式化
│   ├── telemetry/       # 遥测与日志
│   ├── teleport/        # 远程环境
│   └── ...              # 200+ 其他工具模块
└── vim/             # Vim 模式支持 (8 files)
```

## 技术选型

| TypeScript 概念 | Python 等价 |
|------------------|-------------|
| `interface` / `type` | `dataclass` / `TypedDict` / `Protocol` |
| Zod schemas | `dict[str, Any]` + JSON Schema |
| `async/await` + Promises | `asyncio` + `async/await` |
| React/Ink 组件 | 排除（非 UI 移植） |
| `lodash` 工具函数 | Python 标准库等价实现 |
| Node.js `child_process` | `asyncio.create_subprocess_exec` |
| `AbortController` | `asyncio.Event` / cancellation patterns |
| ES Modules | Python packages + `__init__.py` |

## 环境要求

- Python 3.11+
- `anthropic` SDK（调用 Anthropic API 必需）

## 快速开始

### 1. 安装依赖

```bash
pip install anthropic
```

### 2. 设置 API Key

```bash
# Linux / macOS
export ANTHROPIC_API_KEY="sk-ant-api03-你的key"

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-api03-你的key"

# Windows CMD
set ANTHROPIC_API_KEY=sk-ant-api03-你的key
```

### 3. 运行

```bash
# 交互模式（REPL）
python -m hare

# 非交互模式（单次问答，结果直接输出到 stdout）
python -m hare -p "帮我写一个 Python hello world"

# 指定模型
python -m hare -p "hello" --model claude-sonnet-4-6-20260301

# 指定工作目录
python -m hare --cwd /path/to/project

# 查看所有选项
python -m hare --help
```

### 4. 作为库使用

```python
import asyncio
from hare.main import cli_main

# 等价于命令行 python -m hare -p "hello"
asyncio.run(cli_main(["-p", "hello"]))
```

### 可选环境变量

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | **必需** — Anthropic API 密钥 |
| `ANTHROPIC_BASE_URL` | 自定义 API 端点（代理/自托管） |
| `CLAUDE_CODE_SIMPLE` | 设为 `1` 启用精简模式（仅 Bash + Read + Edit 三个工具） |

## 模块统计

| 模块 | 文件数 | 代码行数 | 说明 |
|------|--------|----------|------|
| `utils/` | 630 | 35,710 | 工具函数、权限、插件、Shell、Git 等 |
| `tools_impl/` | 191 | 7,285 | 所有工具的 prompt + schema + 实现 |
| `services/` | 160 | 5,761 | API、MCP、OAuth、分析、压缩等服务 |
| `commands_impl/` | 105 | 1,472 | 斜杠命令 |
| `bridge/` | 30 | 811 | IDE 桥接通信 |
| `cli/` | 23 | 639 | CLI 传输与处理 |
| `constants/` | 22 | 543 | 常量定义 |
| `entrypoints/` | 18 | 417 | 入口点 |
| `keybindings/` | 14 | 1,367 | 键绑定 |
| `migrations/` | 14 | 495 | 配置迁移 |
| `skills/` | 13 | 394 | 技能系统 |
| `types/` | 12 | 831 | 核心类型 |
| 其他 | 58 | 4,660 | memdir, vim, tasks, remote 等 |
| **总计** | **1,310** | **61,385** | |

## 排除内容

以下 TypeScript 模块被有意排除，因为它们是 UI 层（React/Ink）专用代码：

- `components/` — React 组件 (111 个 `.tsx` 文件)
- `hooks/` — React Hooks (68 个 `.ts` + 15 个 `.tsx`)
- `ink/` — Ink 终端 UI 框架 (41 个 `.ts`)
- `screens/` — 屏幕组件
- `context/` — React Context
- `state/` — UI 状态管理（部分）

## 模块级使用示例

```python
# 工具注册表
from hare.tools import get_all_base_tools
tools = get_all_base_tools()  # [Agent, Bash, Glob, Grep, Read, Edit, Write, ...]

# QueryEngine（对话引擎核心）
from hare.query_engine import QueryEngine, QueryEngineConfig

# 环境信息
from hare.utils.env import env
print(env.platform, env.arch)

# 单独调用内置工具
from hare.tools_impl.FileReadTool.file_read_tool import call as read_file
import asyncio
result = asyncio.run(read_file(file_path="/etc/hosts"))
```

## 源码对照

| 源码 (TypeScript) | 移植 (Python) |
|-------------------|---------------|
| `src/utils/env.ts` | `hare/utils/env.py` |
| `src/tools/BashTool/` | `hare/tools_impl/BashTool/` |
| `src/services/api/` | `hare/services/api/` |
| `src/commands/compact/` | `hare/commands_impl/compact.py` |
| `src/utils/permissions/` | `hare/utils/permissions/` |
| `src/bridge/` | `hare/bridge/` |

命名转换规则：
- 文件名: `camelCase.ts` → `snake_case.py`
- 目录名: `camelCase/` → `snake_case/`
- 特殊映射: `tools/` → `tools_impl/`, `commands/` → `commands_impl/`

## License

本项目为 Anthropic Claude Code 的非官方 Python 移植，仅供学习和研究用途。
