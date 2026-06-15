## Workspace Layout

Workspace root: `{{ workspace }}`

### Memory

| 文件 | 说明 |
| ---- | ---- |
| `{{ workspace }}/memory/MEMORY.md` | 长期记忆，每次启动自动注入 system prompt |
| `{{ workspace }}/memory/history.jsonl` | 完整对话原始日志（追加写，勿直接修改） |
| `{{ workspace }}/memory/{YYYY-MM-DD}.md` | 每日情景记忆，压缩时自动生成 |
| `{{ workspace }}/templates/USER.md` | 用户偏好档案，压缩时按信号更新 |
| `{{ workspace }}/templates/SOUL.md` | 灵魂档案：记录 Agent 的核心身份（Identity）、长期使命（Mission）、价值原则（Principles）与行为边界（Constraints），用于确保系统在长期运行中保持一致性与稳定人格。该文件为只读级配置，默认不参与自动压缩。 |

### Skills

每个技能包目录位于 `{{ workspace }}/Skills/{skill-name}/`，包含：

- `SKILL.md` — 技能描述与知识内容（YAML frontmatter + Markdown）
- `_meta.json` — 元数据（名称、标签、触发条件）

按需用 `load_skill` 工具加载，避免占用过多 context。

### Search & Discovery

- 工作区搜索优先用内置 `grep` / `glob`，避免 `exec` 执行 shell 搜索命令。
- 大范围搜索先用 `grep(output_mode="count")` 定位范围，再读取具体内容。

