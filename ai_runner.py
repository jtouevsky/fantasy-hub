"""One place that runs the AI agent (subscription by default, API optional) for every AI surface."""
from __future__ import annotations

import time

import agent
from ctx import Ctx


class AIUnavailable(Exception):
    pass


def run(ctx: Ctx, prompt: str, session_id=None, history=None) -> agent.TurnResult:
    cfg = ctx.cfg
    tools = ctx.agent_tools()
    if cfg.chat_backend == "api":
        if not cfg.anthropic_api_key:
            raise AIUnavailable("CHAT_BACKEND=api needs ANTHROPIC_API_KEY in .env. Remove CHAT_BACKEND to use your Claude subscription instead.")
        import anthropic
        return agent.run_turn(anthropic.Anthropic(api_key=cfg.anthropic_api_key), cfg.anthropic_model, tools, history or [], prompt)
    ok, why = agent.subscription_available()
    if not ok:
        raise AIUnavailable(f"The AI uses your Claude subscription through Claude Code. {why}")
    return agent.run_turn_subscription(cfg.anthropic_model, tools, session_id, prompt)


def context_chips(ctx: Ctx) -> list[tuple[str, str]]:
    s = ctx.snap
    notes = ", ".join(f"{k.replace('points_per_', '').replace('_', ' ')} {v:g}" for k, v in s.scoring_notes.items())
    return [(s.league_name, "groups"), (f"Week {s.week}, {s.year}", "calendar_month"), (ctx.me.name, "shield"), (f"Scoring: {notes}" if notes else "League scoring", "rule")]


def stamp() -> str:
    return time.strftime("%-I:%M %p")
