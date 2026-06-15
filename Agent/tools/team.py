from __future__ import annotations

import json

from .tool_runtime_base import Tool
from .schema import StringSchema, tool_parameters_schema
from ..team import MessageBus, TeammateManager, VALID_MSG_TYPES


class SpawnTeammateTool(Tool):
    name = "spawn_teammate"
    description = (
        "召入一个持久队友,加入 agent team。队友有名字、职司、独立线程和 inbox;"
        "适合长期项目、固定角色协作,或需要多人互相沟通的差事。"
        "如果队友状态是 offline,也用这个工具重新启动其线程。"
    )

    def __init__(self, manager: TeammateManager):
        self._manager = manager

    @property
    def parameters(self) -> dict:
        return tool_parameters_schema(
            name=StringSchema("队友名字,例如 alice、coder、reviewer"),
            role=StringSchema("队友职司,例如 coder、reviewer、researcher"),
            prompt=StringSchema("交给该队友的第一件差事"),
        )

    def execute(self, name: str, role: str, prompt: str) -> str:
        return self._manager.spawn(name, role, prompt)


class ListTeammatesTool(Tool):
    name = "list_teammates"
    description = "列出 agent team 中所有队友的名字、职司和状态。"
    read_only = True

    def __init__(self, manager: TeammateManager):
        self._manager = manager

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self) -> str:
        return self._manager.list_all()


class SendMessageTool(Tool):
    name = "send_message"

    def __init__(self, bus: MessageBus, *, sender: str):
        self._bus = bus
        self._sender = sender

    @property
    def description(self) -> str:
        return (
            f"以 {self._sender} 的身份给某位固定队友或 lead 发送 inbox 消息。"
            "msg_type 默认为 message。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "to": StringSchema("收件人名字,例如 lead、alice、reviewer").to_json_schema(),
                "content": StringSchema("消息内容").to_json_schema(),
                "msg_type": StringSchema(
                    "消息类型,默认 message",
                    enum=sorted(VALID_MSG_TYPES),
                ).to_json_schema(),
            },
            "required": ["to", "content"],
        }

    def execute(self, to: str, content: str, msg_type: str = "message") -> str:
        return self._bus.send(self._sender, to, content, msg_type)


class ReadInboxTool(Tool):
    name = "read_inbox"
    read_only = False

    def __init__(self, bus: MessageBus, *, reader: str):
        self._bus = bus
        self._reader = reader

    @property
    def description(self) -> str:
        return f"读取并清空 {self._reader} 自己的 inbox。"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self) -> str:
        return json.dumps(self._bus.read_inbox(self._reader), ensure_ascii=False, indent=2)


class BroadcastTool(Tool):
    name = "broadcast"
    description = "向所有固定队友广播一条消息。"

    def __init__(self, bus: MessageBus, manager: TeammateManager, *, sender: str = "lead"):
        self._bus = bus
        self._manager = manager
        self._sender = sender

    @property
    def parameters(self) -> dict:
        return tool_parameters_schema(
            content=StringSchema("广播消息内容"),
        )

    def execute(self, content: str) -> str:
        return self._bus.broadcast(self._sender, content, self._manager.member_names())