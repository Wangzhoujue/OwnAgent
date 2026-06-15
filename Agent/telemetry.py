"""把每次模型调用的 token usage 记录成 JSONL,并支持按日期/模型做汇总。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class TokenTracker:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._last_input_tokens = 0

    def record(self, model: str, usage) -> None:
        """Append one row to tokens.jsonl from an Openai response.usage."""
        """usage 可能是 openai.types.usage.Usage 对象，也可能是一个 dict,甚至可能缺失某些字段,所以要兼容处理。"""

        """对输入tokens进行统计,包括实际输入和cache读取和cache创建的tokens,因为它们都占用上下文长度。"""
        input_tokens = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", 0)
        )
        """对输出tokens进行统计,如果output_tokens缺失,则退回到completion_tokens,如果仍然缺失则默认为0。"""
        output_tokens = (
        getattr(usage, "output_tokens", None)
        or getattr(usage,"completion_tokens",0)
        )
        
        row = {
            "ts": datetime.now().isoformat(
                timespec="seconds"
            ),
            "model": model,
            "input": input_tokens,
            "output": output_tokens, 
            "prompt_cache_hit_tokens": getattr(
                usage,
                "prompt_cache_hit_tokens",
                0,
            ),
            "prompt_cache_miss_tokens": getattr(
                usage,
                "prompt_cache_miss_tokens",
                0,
            )
        }
        self._last_input_tokens = row["input"] + row["prompt_cache_hit_tokens"] + row["prompt_cache_miss_tokens"]
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def last_input_tokens(self) -> int:
        return self._last_input_tokens

    def should_compact(self, max_context: int, threshold: float = 0.7) -> bool:
        return self._last_input_tokens > max_context * threshold

    def _iter_rows(self):
        if not self.log_file.exists():
            return
        with self.log_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def stats_by_date(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0})
        for r in self._iter_rows():
            date = r.get("ts", "")[:10]
            for k in ("input", "output", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                out[date][k] += r.get(k, 0)
        return dict(out)

    def stats_by_model(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0})
        for r in self._iter_rows():
            m = r.get("model", "unknown")
            for k in ("input", "output", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                out[m][k] += r.get(k, 0)
        return dict(out)