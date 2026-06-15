"""压缩器: 将过长的历史压缩成当天的情景记忆和核心事件，写入 MemoryStore。"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .memory import MemoryStore

_UTC8 = timezone(timedelta(hours=8))

_PROMPT_FILE = Path(__file__).parent.parent / "Templates" / "agent" / "compact_prompt.md"
_PROMPT_TEMPLATE = _PROMPT_FILE.read_text(encoding="utf-8")


def _extract(tag: str, text: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _messages_to_text(messages: list) -> str:
    parts = []

    for msg in messages:
        role = msg.get("role", "?")

        content = msg.get("content", "")

        if isinstance(content, str) and content:
            parts.append(f"[{role}] {content}")

        if role == "assistant":
            for tc in msg.get("tool_calls", []):
                name = tc["function"]["name"]
                args = tc["function"]["arguments"]

                parts.append(
                    f"[assistant:tool_call] {name}({args})"
                )

        elif role == "tool":
            snippet = str(content)[:300]

            parts.append(
                f"[tool_result] {snippet}"
            )

    return "\n".join(parts)


class Compactor:
    K = 10

    def __init__(self, client, model: str, memory_store: MemoryStore, max_tokens: int = 4000):
        self.client = client
        self.model = model
        self.memory = memory_store
        self.max_tokens = max_tokens

    def compact(self, history: list) -> list:
        """去掉过长的历史，保留 recent;将 old 压缩成 episode + memory + user更新写入 MemoryStore;返回 recent 供继续对话使用。"""
        
        if len(history) <= self.K:
            return history

        old = history[: -self.K]
        recent = history[-self.K :]

        prompt = _PROMPT_TEMPLATE.format(
            old_conversation=_messages_to_text(old),
            current_memory=self.memory.read_memory() or "(空)",
            current_user=self.memory.read_user() or "(空)",
            today_episode=self.memory.read_today_episode() or "(空)",
            now_hhmm=datetime.now(_UTC8).strftime("%H:%M"),
        )

        resp = self.client.chat.completions.create(
        model=self.model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=self.max_tokens,
        temperature=0,
        )

        text = resp.choices[0].message.content or ""

        episode = _extract("episode", text)
        new_memory = _extract("updated_memory", text)
        new_user = _extract("updated_user", text)

        if episode:
            self.memory.append_episode(episode)
        if new_memory:
            self.memory.write_memory(new_memory)
        if new_user:
            self.memory.write_user(new_user)
        self.memory.append_compact_marker()

        print(f"[Compacted: {len(old)} turns → today episode + MEMORY updated]")
        return recent

    def compact_startup(self, history: list) -> None:
        """启动时将未归档的历史全量归档，不保留 recent。"""
        if len(history) < 2:
            return
        prompt = _PROMPT_TEMPLATE.format(
            old_conversation=_messages_to_text(history),
            current_memory=self.memory.read_memory() or "(空)",
            current_user=self.memory.read_user() or "(空)",
            today_episode=self.memory.read_today_episode() or "(空)",
            now_hhmm=datetime.now(_UTC8).strftime("%H:%M"),
        )
        resp = self.client.chat.completions.create(
        model=self.model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=self.max_tokens,
        temperature=0,
        )
        text = resp.choices[0].message.content or ""    
        if episode := _extract("episode", text):
            self.memory.append_episode(episode)
        if new_memory := _extract("updated_memory", text):
            self.memory.write_memory(new_memory)
        if new_user := _extract("updated_user", text):
            self.memory.write_user(new_user)
        self.memory.append_compact_marker()
        print(f"[Startup compacted: {len(history)} unarchived turns → MEMORY updated]")