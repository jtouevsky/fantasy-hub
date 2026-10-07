"""MANUAL suite: asks the REAL assistant (your Claude subscription) each scenario question and checks the wording of its answer.

    RUN_AGENT_SCENARIOS=1 .venv/bin/python -m tests.agent_scenarios.run_live

It is not part of the normal pytest run (it needs a logged-in Claude and takes a minute per scenario).
"""
from __future__ import annotations

import os
import re
import sys

import agent
from tests.agent_scenarios import scenarios as sc


def _has(pattern: str, text: str) -> bool:
    """'re:...' entries are regexes; plain entries are substrings."""
    return bool(re.search(pattern[3:], text)) if pattern.startswith("re:") else pattern in text


def main() -> int:
    if os.getenv("RUN_AGENT_SCENARIOS") != "1":
        print("Set RUN_AGENT_SCENARIOS=1 to run the live assistant scenarios.")
        return 0
    ok, why = agent.subscription_available()
    if not ok:
        print("Claude subscription not available:", why)
        return 1
    failed = 0
    for make in sc.ALL:
        s = make()
        res = agent.run_turn_subscription("", s.tools, None, s.question)
        text = res.text.lower()
        used = {t["tool"] for t in res.tool_trace}
        problems = []
        if not used & {"find_moves", "evaluate_move"}:
            problems.append("did not call find_moves/evaluate_move")
        problems += [f"missing '{m}'" for m in s.must if not _has(m, text)]
        problems += [f"contains '{m}'" for m in s.must_not if _has(m, text)]
        print(f"[{'PASS' if not problems else 'FAIL'}] {s.name}: {s.question}")
        if problems:
            failed += 1
            print("   ", "; ".join(problems))
            print("    answer:", res.text[:500].replace("\n", " "))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
