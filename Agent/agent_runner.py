from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
from .tools.registry import ToolRegistry


class AgentRunner:
    def __init__(
        self,
        client,
        model: str,
        registry: ToolRegistry,
        system_prompt: str,
        max_tokens: int = 20000,
        memory_store=None,
        token_tracker=None,
        compactor=None,
        max_context: int = 200_000,
        compact_threshold: float = 0.7,
        max_turns: int | None = None,
    ):
        self.client = client
        self.model = model
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.memory_store = memory_store
        self.token_tracker = token_tracker
        self.compactor = compactor
        self.max_context = max_context
        self.compact_threshold = compact_threshold
        self.max_turns = max_turns

    def step(self, history: list) -> str:
        """Run one full turn (user→...→final-text). Mutates `history` in place."""
        turns = 0
        while True:
            if self.max_turns is not None and turns >= self.max_turns:
                return f"（达到 max_turns={self.max_turns} 上限, 未办妥;history 中已有部分进展）"
            turns += 1
            message = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                {"role": "system", "content": self.system_prompt},
                *history
                ],  
                tools=self.registry.get_definitions() or None,
               
            )
            if self.token_tracker:
                self.token_tracker.record(self.model, message.usage)
            msg = message.choices[0].message
            # print("\n===== MODEL OUTPUT =====")
            # print("finish_reason:", message.choices[0].finish_reason)
            # print("content:", msg.content)
            # print("tool_calls:", msg.tool_calls)
            # print("========================\n")

            assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
            }

            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]

            history.append(assistant_msg)

            finish_reason = message.choices[0].finish_reason
            if finish_reason != "tool_calls":
                reply = message.choices[0].message.content
                if self.memory_store:
                    self.memory_store.append_history("assistant", reply)
                self._maybe_compact(history)
                return reply

            tool_calls = msg.tool_calls or []

            for tool_call in tool_calls:
                result = self.registry.execute(
                    tool_call.function.name,
                    json.loads(tool_call.function.arguments)
                )

                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

   
    def _maybe_compact(self, history: list) -> None:
        if not (self.compactor and self.token_tracker):
            return
        if not self.token_tracker.should_compact(self.max_context, self.compact_threshold):
            return
        history[:] = self.compactor.compact(history)