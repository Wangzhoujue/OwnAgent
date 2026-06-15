from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from config import config

from openai import OpenAI

from .compactor import Compactor
from .memory import MemoryStore
from .agent_runner import AgentRunner
from .telemetry import TokenTracker
from .tools.registry import (
    ToolRegistry
)
from .context import ContextBuilder
from .skills import SkillsLoader
from .subagent  import SubagentRegistry
from .team import MessageBus, TeammateManager
from .tools import (
    LoadSkill, RunCommand, ToolRegistry, WebFetch,
    ReadFileTool, WriteFileTool, EditFileTool, GlobTool, GrepTool,
    TodoStore, UpdateTodosTool, DispatchSubagentTool,
)
from .tools.team import (
    SpawnTeammateTool, ListTeammatesTool, SendMessageTool, ReadInboxTool,
    BroadcastTool,
)


class AgentLoop:
    def __init__(self, root: Path | None = None,
                 model: str = config.ai_model):
        self.root = root or Path(__file__).parent.parent

        client = OpenAI(
            base_url=config.api_base_url,
            api_key=config.api_key
        )

        self.memory = MemoryStore(
            memory_dir=self.root / "memory",
            user_file=self.root / "templates" / "USER.md",
        )
        token_tracker = TokenTracker(self.root / "memory" / "tokens.jsonl")
        compactor = Compactor(client, model, self.memory)

        skills = SkillsLoader(self.root / "skills")
        ctx = ContextBuilder(self.root / "templates", skills, memory=self.memory)

        workspace = self.root
        registry = ToolRegistry()
        registry.register(RunCommand())
        registry.register(WebFetch())
        registry.register(LoadSkill(skills))
        registry.register(ReadFileTool(workspace))
        registry.register(WriteFileTool(workspace))
        registry.register(EditFileTool(workspace))
        registry.register(GlobTool(workspace))
        registry.register(GrepTool(workspace))

        self.todos = TodoStore()
        registry.register(UpdateTodosTool(self.todos))

        self.team_bus = MessageBus(self.root / ".team" / "inbox")

        def _make_teammate_tools(sender: str):
            return [
                SendMessageTool(self.team_bus, sender=sender),
                ReadInboxTool(self.team_bus, reader=sender),
            ]

        self.team = TeammateManager(
            team_dir=self.root / ".team",
            bus=self.team_bus,
            client=client,
            model=model,
            workspace=workspace,
            parent_registry=registry,
            teammate_tool_factory=_make_teammate_tools,
        )
        registry.register(SpawnTeammateTool(self.team))
        registry.register(ListTeammatesTool(self.team))
        registry.register(SendMessageTool(self.team_bus, sender="lead"))
        registry.register(ReadInboxTool(self.team_bus, reader="lead"))
        registry.register(BroadcastTool(self.team_bus, self.team, sender="lead"))

        # 子代理: 必须最后注册 dispatch 工具, 让它能拿到完整的 parent_registry
        # 传 skills 让子代理 system prompt 也能看到 skills 摘要
        subagent_registry = SubagentRegistry(
            self.root / "templates" / "subagents",
            skills_loader=skills,
        )

        def _make_subagent_runner(*, spec, sub_registry):
            return AgentRunner(
                client=client,
                model=model,
                registry=sub_registry,
                system_prompt=spec.system_prompt,
                max_tokens=2000,
                memory_store=None,
                token_tracker=None,
                compactor=None,
                max_turns=spec.max_turns,
            )

        registry.register(DispatchSubagentTool(
            client=client,
            model=model,
            parent_registry=registry,
            subagent_registry=subagent_registry,
            runner_factory=_make_subagent_runner,
        ))

        unarchived = self.memory.load_unarchived_history()
        if len(unarchived) >= 2:
            print(f"[Startup: found {len(unarchived)} unarchived turns, compacting...]")
            try:
                compactor.compact_startup(unarchived)
            except Exception as exc:
                print(f"[warning] startup compaction failed: {exc}", file=sys.stderr)

        system_prompt = ctx.build_system_prompt()
        print(f"[System Prompt]\n{system_prompt}\n{'='*60}\n")

        self.runner = AgentRunner(
            client=client,
            model=model,
            registry=registry,
            system_prompt=system_prompt,
            memory_store=self.memory,
            token_tracker=token_tracker,
            compactor=compactor,
        )
        self.history: list = []

    def run(self) -> None:
        while True:
            user_input = input("You : ")
            command = user_input.strip()
            if command == "/team":
                print(self.team.list_all())
                print()
                continue
            if command == "/inbox":
                print(json.dumps(self.team_bus.read_inbox("lead"), ensure_ascii=False, indent=2))
                print()
                continue
            self.history.append({"role": "user", "content": user_input})
            self.memory.append_history("user", user_input)
            reply = self.runner.step(self.history)
            print(f"AI\u200d♂️: {reply}\n")