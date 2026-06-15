from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .agent_runner import AgentRunner
from .tools.tool_runtime_base import Tool
from .tools.registry import ToolRegistry


VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}
RUNTIME_STATUSES = {"idle", "working"}
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _valid_name(name: str) -> bool:
    return bool(_NAME_RE.fullmatch(name))


class MessageBus:
    """File-backed JSONL inboxes. Sending appends, reading drains."""

    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict | None = None,
    ) -> str:
        sender = sender.strip()
        to = to.strip()
        if not _valid_name(sender):
            return f"Error: invalid sender '{sender}'"
        if not _valid_name(to):
            return f"Error: invalid inbox name '{to}'"
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: invalid msg_type '{msg_type}', valid={sorted(VALID_MSG_TYPES)}"

        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)

        inbox_path = self.dir / f"{to}.jsonl"
        with self._lock:
            inbox_path.parent.mkdir(parents=True, exist_ok=True)
            with inbox_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return f"已送达 {to} 的 inbox:{msg_type}"

    def read_inbox(self, name: str) -> list[dict]:
        name = name.strip()
        if not _valid_name(name):
            return [{
                "type": "message",
                "from": "system",
                "content": f"Error: invalid inbox name '{name}'",
                "timestamp": time.time(),
            }]

        inbox_path = self.dir / f"{name}.jsonl"
        with self._lock:
            if not inbox_path.exists():
                return []
            lines = inbox_path.read_text(encoding="utf-8").splitlines()
            inbox_path.write_text("", encoding="utf-8")

        messages = []
        for line in lines:
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError as e:
                messages.append({
                    "type": "message",
                    "from": "system",
                    "content": f"Error: inbox line parse failed: {e}",
                    "timestamp": time.time(),
                })
        return messages

    def broadcast(self, sender: str, content: str, teammates: list[str]) -> str:
        count = 0
        for name in teammates:
            if name == sender:
                continue
            result = self.send(sender, name, content, "broadcast")
            if not result.startswith("Error"):
                count += 1
        return f"已广播给 {count} 位队友"


class TeammateManager:
    """Persistent named teammate agents with status and inboxes."""

    _BASE_TOOL_NAMES = (
        "run_command",
        "web_fetch",
        "load_skill",
        "read_file",
        "write_file",
        "glob",
        "grep",
    )

    def __init__(
        self,
        *,
        team_dir: Path,
        bus: MessageBus,
        client,
        model: str,
        workspace: Path,
        parent_registry: ToolRegistry,
        teammate_tool_factory: Callable[[str], list[Tool]],
    ):
        self.dir = team_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.bus = bus
        self.client = client
        self.model = model
        self.workspace = workspace
        self.parent_registry = parent_registry
        self.teammate_tool_factory = teammate_tool_factory
        self.config = self._load_config()
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()
        self._mark_stale_members_offline()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("members"), list):
                    return data
            except json.JSONDecodeError:
                pass
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _mark_stale_members_offline(self) -> None:
        changed = False
        for member in self.config.get("members", []):
            if member.get("status") in RUNTIME_STATUSES:
                member["status"] = "offline"
                changed = True
        if changed:
            self._save_config()

    def _find_member(self, name: str) -> dict | None:
        for member in self.config["members"]:
            if member["name"] == name:
                return member
        return None

    def _set_status(self, name: str, status: str) -> None:
        with self.lock:
            member = self._find_member(name)
            if member:
                member["status"] = status
                self._save_config()

    def spawn(self, name: str, role: str, prompt: str) -> str:
        name = name.strip()
        role = role.strip() or "teammate"
        if not _valid_name(name):
            return "Error: name 只能包含字母、数字、下划线、点和短横线，且长度不超过 64"

        with self.lock:
            member = self._find_member(name)
            if member:
                running = self.threads.get(name)
                if running and running.is_alive():
                    self.bus.send("lead", name, prompt)
                    member["role"] = role
                    member["status"] = "working"
                    self._save_config()
                    return f"'{name}' 已在队中，已把新差事送入 inbox"
                member["role"] = role
                member["status"] = "working"
            else:
                member = {"name": name, "role": role, "status": "working"}
                self.config["members"].append(member)
            self._save_config()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"已召入/唤回队友 '{name}'(职司:{role})，队友线程已启动"

    def _teammate_loop(self, name: str, role: str, prompt: str) -> None:
        system_prompt = (
            f"你是大内团队中的固定队友，名叫 {name}，职司是 {role}。\n"
            f"当前工作区:{self.workspace}。\n"
            "你不是一次性小太监，而是 agent team 的持久成员。\n"
            "你可以通过 send_message 给 lead 或其他队友发消息，也可以 read_inbox 读取自己的 inbox。\n"
            "收到差事后尽快办妥；办完用 send_message 向 lead 回禀简短结果，然后等待下一封 inbox。\n"
            "若收到 shutdown_request，可回禀 shutdown_response 后停止。"
        )
        registry = self._build_teammate_registry(name)
        runner = AgentRunner(
            client=self.client,
            model=self.model,
            registry=registry,
            system_prompt=system_prompt,
            max_tokens=4000,
            memory_store=None,
            token_tracker=None,
            compactor=None,
            max_turns=20,
        )
        messages = [{"role": "user", "content": prompt}]
        has_work = True

        while True:
            inbox = self.bus.read_inbox(name)
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    self.bus.send(
                        name,
                        msg.get("from", "lead"),
                        "准许退下，队友线程即将停止。",
                        "shutdown_response",
                    )
                    self._set_status(name, "shutdown")
                    return
                messages.append({
                    "role": "user",
                    "content": "<inbox>\n" + json.dumps(msg, ensure_ascii=False, indent=2) + "\n</inbox>",
                })
                has_work = True

            if not has_work:
                time.sleep(1)
                continue

            self._set_status(name, "working")
            try:
                final = runner.step(messages)
            except Exception as exc:
                final = f"Error: 队友 {name} 调用模型失败:{exc}"

            if final.strip():
                self.bus.send(name, "lead", final.strip())
            print(f"[队友 {name} 空闲]: 回到 idle，等待下一封 inbox")
            self._set_status(name, "idle")
            has_work = False

    def _build_teammate_registry(self, sender: str) -> ToolRegistry:
        registry = ToolRegistry()
        for name in self._BASE_TOOL_NAMES:
            tool = self.parent_registry.get(name)
            if tool is not None:
                registry.register(tool)
        for tool in self.teammate_tool_factory(sender):
            registry.register(tool)
        return registry

    def list_all(self) -> str:
        with self.lock:
            if not self.config["members"]:
                return "暂无队友。"
            lines = [f"Team: {self.config.get('team_name', 'default')}"]
            for member in self.config["members"]:
                status = member["status"]
                note = "(需重新 spawn 才会处理 inbox)" if status == "offline" else ""
                lines.append(f"  - {member['name']}({member['role']}):{status}{note}")
            return "\n".join(lines)

    def member_names(self) -> list[str]:
        with self.lock:
            return [m["name"] for m in self.config["members"]]