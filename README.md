# OwnAgent

> 一个从零手写的极简 Agent 运行时：ReAct 循环、可插拔工具、三层记忆、上下文压缩、技能库、子代理与持久 Agent Team。

OwnAgent 不依赖任何 Agent 框架（LangChain / AutoGen 等），仅使用 `openai`、`jinja2`、`pyyaml` 三个依赖，把「一个能长期运行、可自我记忆与协作的 Agent」所需的机制逐层实现出来。它适合作为学习 Agent 内部原理的参考实现，也适合作为自建 Agent 的起点骨架。

---

## 目录

- [项目简介](#项目简介)
- [主要功能与特性](#主要功能与特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速上手](#快速上手)
- [基本使用示例](#基本使用示例)
- [常见配置说明](#常见配置说明)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

OwnAgent 是一个面向终端（REPL）的通用 Agent 运行时。它的核心是一条标准的 ReAct 循环：模型返回 `tool_calls` → 运行时执行工具 → 结果回填进 `history` → 再次调用模型，直到模型给出最终自然语言回复。

在此之上，项目补齐了让 Agent「可持续工作」的关键组件：

- **记忆**：三层结构（原始日志 / 每日情景 / 长期记忆），跨会话保留上下文。
- **压缩**：上下文接近模型上限时，自动把旧历史蒸馏为情景记忆与长期记忆，避免爆窗。
- **技能**：以 `SKILL.md` 组织的知识包，按需注入，避免常驻占用上下文。
- **扩展**：子代理（独立上下文的一次性执行单元）与持久队友（长期协作、可互相通信）。

模型侧只要求 **OpenAI 兼容的 Chat Completions 接口**，因此可对接任意兼容网关（vLLM、Ollama、One-API、各家云厂商等）。

## 主要功能与特性

| 能力 | 说明 |
| ---- | ---- |
| **ReAct 循环** | `AgentRunner.step()` 完成「模型 → 工具 → 模型」的完整单轮推进，支持 `max_turns` 上限保护 |
| **声明式工具系统** | 继承 `Tool` 抽象基类，用 `@tool_parameters` 装饰器 + Schema 类族声明参数，自动生成 JSON Schema、自动类型转换与校验 |
| **工具错误回灌** | 未知工具、参数非法、执行异常都会转成文本结果返回模型，并附「请修正参数重试」提示，让模型自我纠错 |
| **内置工具集** | 文件读写编辑、glob/grep 搜索、Shell 执行、网页抓取、技能加载、待办管理、子代理派遣、团队协作 |
| **容错文件编辑** | `edit_file` 支持缩进差异与中英文引号风格差异匹配，多处命中时给出警告，未命中时返回 diff 供模型参考 |
| **三层记忆** | `history.jsonl`（原始层，追加不修改）→ `YYYY-MM-DD.md`（中期情景层）→ `MEMORY.md`（长期层，常驻 system prompt） |
| **上下文压缩** | 输入 token 超过阈值时自动压缩：保留最近 K 条，其余蒸馏为 episode / 长期记忆 / 用户档案 |
| **启动归档** | 启动时自动把上次未归档的对话压缩入库，实现跨会话记忆延续 |
| **Token 计量** | 每次模型调用记录到 `tokens.jsonl`，支持按日期、按模型汇总统计 |
| **技能系统** | `SKILL.md`（YAML frontmatter + Markdown），`always: true` 常驻注入，其余按需 `load_skill` |
| **子代理派遣** | 子代理拥有独立 `history` 与工具白名单，只回传一段总结，不污染主上下文；同帧多个派遣可并发执行 |
| **持久 Agent Team** | 基于线程 + JSONL 收件箱的固定队友，支持 spawn / send / read / broadcast / shutdown 协议 |
| **提示词模板化** | system prompt 由 Jinja2 模板组装（身份、工作区布局、记忆、技能摘要） |

## 环境要求

- **Python >= 3.13**（见 `pyproject.toml` 与 `.python-version`）
- 一个 OpenAI 兼容的模型服务端点（本地或远程均可）
- 建议使用 [uv](https://docs.astral.sh/uv/) 管理依赖（仓库自带 `uv.lock`）

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/Wangzhoujue/OwnAgent.git
cd OwnAgent

# 2A. 使用 uv（推荐）
uv sync
uv run runner.py

# 2B. 或使用标准 venv + pip
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
python runner.py
```

## 快速上手

### 1. 配置模型端点

编辑根目录的 `config.py`，把三处占位符替换为你自己的值：

```python
class Config:
    def __init__(self):
        # AI模型配置
        self.api_base_url = "Your_API_Url"   # OpenAI 兼容地址，需带 /v1 后缀
        self.api_key = "apikey"              # 你的密钥
        self.ai_model = "Model_Name"         # 模型名

config = Config()
```

> ⚠️ **请勿把真实密钥提交到公开仓库。** 推荐改为从环境变量读取（见 [常见配置说明](#常见配置说明)）。由于 `config.py` 已被 Git 跟踪，仅加入 `.gitignore` 不会生效——若曾提交过真实密钥，请立即在服务端轮换该密钥。

### 2. 启动

```bash
uv run runner.py
# 或
python runner.py
```

启动后进入交互式 REPL，直接用自然语言下达任务：

```
You : 帮我看一下 Agent/tools 目录下有哪些文件，并总结每个工具的用途
Agent: ...
```

### 3. 交互命令

| 命令 | 作用 |
| ---- | ---- |
| `/team` | 查看当前 Agent Team 成员与状态 |
| `/inbox` | 读取 lead 自己的收件箱 |

按 `Ctrl+C` 退出。

## 基本使用示例

### 示例 1：一次多步任务

```
You : 统计 Agent 目录下所有 .py 文件的总行数，把结果写入 stats.md
```

运行时内部的执行链路：

1. 模型调用 `glob` 列出 `Agent/**/*.py`；
2. 模型调用 `run_command` 执行统计命令；
3. 模型调用 `write_file` 写入 `stats.md`；
4. 模型返回最终总结文本，本轮结束。

中途所有工具调用与结果都会回填进 `history`，并追加写入 `memory/history.jsonl`。

### 示例 2：新增一个自定义工具

```python
# Agent/tools/weather.py
from .tool_runtime_base import Tool, tool_parameters
from .schema import StringSchema, tool_parameters_schema


@tool_parameters(tool_parameters_schema(
    city=StringSchema("城市名称"),
))
class WeatherTool(Tool):
    name = "get_weather"
    description = "查询指定城市的当前天气"
    read_only = True          # 只读且非独占 → 可并发执行

    def execute(self, city: str) -> str:
        return f"{city}：晴，26℃"
```

在 `Agent/agent_runtime.py` 中注册即可生效：

```python
from .tools.weather import WeatherTool
registry.register(WeatherTool())
```

### 示例 3：新增一个技能

在技能目录下创建 `SKILL.md`，加载器会自动扫描 `**/SKILL.md`：

```markdown
---
name: sql-review
description: SQL 语句审查规范
tags: database, review
always: false
---

# SQL 审查规范

1. 禁止 `SELECT *`，必须显式列出字段。
2. 所有写操作必须包裹事务。
```

- `always: true` → 内容常驻 system prompt；
- `always: false`（默认）→ 仅在技能摘要中列出，模型需要时通过 `load_skill` 拉取全文。

### 示例 4：派遣子代理与组建团队

模型可自行调用以下工具，你也可以在提示中明确要求：

```
You : 派一个子代理去抓取这 3 个网页并分别总结，最后合并成一份对比表
```

- `dispatch_subagent(agent_type, task, purpose)`：一次性子代理，独立上下文，只回传总结。
- `spawn_teammate(name, role, prompt)`：召入持久队友（独立线程 + 收件箱），适合长期分工。
- `send_message` / `read_inbox` / `broadcast`：队友间通信。

## 常见配置说明

### 模型配置（`config.py`）

| 字段 | 说明 | 仓库内占位值 |
| ---- | ---- | ---- |
| `api_base_url` | OpenAI 兼容接口地址，需带 `/v1` 后缀 | `Your_API_Url` |
| `api_key` | 接口密钥，本地服务可填任意占位符 | `apikey` |
| `ai_model` | 模型名称 | `Model_Name` |

**推荐做法**——改为环境变量读取，避免密钥入库：

```python
import os

class Config:
    def __init__(self):
        self.api_base_url = os.getenv("OPENAI_BASE_URL", "Your_API_Url")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.ai_model = os.getenv("AI_MODEL", "Model_Name")
```

### 运行时参数（`Agent/agent_runner.py`）

| 参数 | 说明 | 默认值 |
| ---- | ---- | ---- |
| `max_tokens` | 单次模型回复的最大输出 token | `20000` |
| `max_context` | 模型上下文窗口大小，用于压缩判定 | `200000` |
| `compact_threshold` | 输入 token 达到 `max_context × threshold` 时触发压缩 | `0.7` |
| `max_turns` | 单轮任务的最大模型调用次数（子代理/队友会设上限） | `None`（不限制） |

### 压缩行为（`Agent/compactor.py`）

| 参数 | 说明 | 默认值 |
| ---- | ---- | ---- |
| `K` | 压缩时保留的最近消息条数 | `10` |
| `max_tokens` | 压缩摘要请求的最大输出 token | `4000` |

压缩产物写回位置：

- `<episode>` → `memory/{YYYY-MM-DD}.md`（追加）
- `<updated_memory>` → `memory/MEMORY.md`（覆盖）
- `<updated_user>` → `Templates/USER.md`（仅在检测到明确偏好信号时更新）

### 数据文件与忽略规则

以下路径为运行期产生的私人数据，已在 `.gitignore` 中排除，请勿提交：

| 路径 | 内容 |
| ---- | ---- |
| `memory/` | 会话原始日志、情景记忆、长期记忆、token 用量 |
| `Templates/USER.md` | 用户偏好档案 |
| `Templates/SOUL.md` | Agent 身份档案 |
| `.team/` | 队友配置与收件箱 |
| `.env` / `.venv/` | 环境变量与虚拟环境 |

## 项目结构

```
OwnAgent/
├── runner.py                 # 程序入口
├── config.py                 # 模型与接口配置
├── pyproject.toml            # 依赖与项目元数据
├── Agent/
│   ├── agent_runtime.py      # AgentLoop：装配全部组件 + 交互主循环
│   ├── agent_runner.py       # AgentRunner：单轮 ReAct 循环
│   ├── compactor.py          # 上下文压缩器
│   ├── context.py            # system prompt 组装（Jinja2）
│   ├── memory.py             # 三层记忆存储
│   ├── skills.py             # SKILL.md 加载器
│   ├── telemetry.py          # Token 计量与统计
│   ├── team.py               # 消息总线 + 持久队友管理
│   ├── subagent/             # 子代理规格与注册表
│   └── tools/                # 工具实现与注册表
│       ├── tool_runtime_base.py  # Tool 基类、参数转换与校验
│       ├── schema.py             # 声明式 JSON Schema 类族
│       ├── registry.py           # ToolRegistry
│       ├── filesystem.py         # read_file / write_file / edit_file
│       ├── search.py             # glob / grep
│       ├── shell.py              # run_command
│       ├── web.py                # web_fetch
│       ├── todo.py               # update_todos
│       ├── skills.py             # load_skill
│       ├── dispatch.py           # dispatch_subagent
│       └── team.py               # 团队协作工具
├── Templates/
│   └── agent/                # identity.md / compact_prompt.md 等模板
└── memory/                   # 运行期数据（gitignore）
```

### 内置工具一览

| 工具名 | 说明 | 只读 |
| ------ | ---- | :--: |
| `run_command` | 执行 Shell 命令并返回输出（独占执行） | ✗ |
| `web_fetch` | 抓取 URL，支持 `text` / `raw` 两种提取模式 | ✓ |
| `read_file` | 读取文本文件，支持 `offset` / `limit` 分页 | ✓ |
| `write_file` | 覆盖写入文件 | ✗ |
| `edit_file` | 文本替换，容忍缩进与引号差异 | ✗ |
| `glob` | 按文件名/路径模式查找文件 | ✓ |
| `grep` | 按内容正则搜索 | ✓ |
| `load_skill` | 按名称加载技能全文 | ✓ |
| `update_todos` | 全量更新待办列表（同时至多一个 `in_progress`） | ✗ |
| `dispatch_subagent` | 派遣子代理，仅回传总结 | ✗ |
| `spawn_teammate` / `list_teammates` | 召入/查看持久队友 | ✗ / ✓ |
| `send_message` / `read_inbox` / `broadcast` | 队友间消息收发 | ✗ |

## 常见问题

**Q：可以对接非 OpenAI 的模型服务吗？**
可以。只要服务提供 OpenAI 兼容的 `/v1/chat/completions` 且支持 `tools`（function calling）字段即可，例如 vLLM、Ollama、One-API、LM Studio 等。部分推理模型还支持通过 `extra_body` 传入 `thinking` 等扩展参数。

**Q：为什么启动时会打印 `[Startup: found N unarchived turns, compacting...]`？**
上次退出时还有未归档的对话，运行时会先调用压缩器把它们写入情景记忆与长期记忆，再开始新会话。这是跨会话记忆延续的正常行为。

**Q：`memory/` 目录越来越大怎么办？**
建议定期把 30 天前的每日情景文件归并进 `MEMORY.md`，然后删除旧文件。`MEMORY.md` 本身建议控制在 3000 字以内（压缩提示词已内置该约束）。

**Q：在 Linux/macOS 上路径报错？**
代码中模板目录使用了小写 `templates`，而仓库目录名为 `Templates`。Windows 文件系统大小写不敏感，因此本机可正常运行；在区分大小写的系统上请确保目录名与代码引用一致。

**Q：`edit_file` 提示 `old_text not found`？**
工具会返回最相似的片段及 diff。把 `old_text` 替换为 diff 中显示的实际内容后重试即可。

## 贡献指南

欢迎通过 Issue 与 Pull Request 参与改进。

### 提交流程

1. **Fork** 本仓库并克隆到本地；
2. 从 `main` 创建特性分支：`git checkout -b feat/your-feature`；
3. 完成修改并自测（至少保证 `python -c "import Agent.agent_runtime"` 无导入错误）；
4. 提交时使用清晰的提交信息，推荐 [Conventional Commits](https://www.conventionalcommits.org/) 风格：
   - `feat: 新增 xxx 工具`
   - `fix: 修复 edit_file 在多处命中时的提示`
   - `docs: 补充配置说明`
   - `refactor: 拆分 compactor 的提示词模板`
5. 推送分支并提交 Pull Request，在描述中说明：**改了什么、为什么改、如何验证**。

### 代码约定

- 新增工具：继承 `Tool`，用 `@tool_parameters` 声明参数，准确设置 `read_only` 与 `exclusive`（影响并发安全判定）；`execute` 返回 `str`，错误以 `Error: ...` 开头。
- 新增提示词/身份文案：放入 `Templates/`，不要在 Python 中硬编码长文本。
- 工具白名单（子代理、队友）属于安全配置，应写在代码中，不要放入模板文件。
- 避免提交任何运行期数据与密钥（见 `.gitignore`）。

### 报告问题

提交 Issue 时请附上：运行环境（操作系统、Python 版本）、模型服务类型、可复现的最小输入、完整错误输出。

## 许可证

本项目采用 **MIT License** 发布。

```
MIT License

Copyright (c) 2026 OwnAgent Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> 若需改用其他许可证，请替换本节内容，并在仓库根目录添加对应的 `LICENSE` 文件。
