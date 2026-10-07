"""Assistant: general chat, with visible context."""
from __future__ import annotations

import json

import streamlit as st

import ai_runner
import ui
from ctx import Ctx
from views_common import html, moves_from_trace

EXAMPLES = [
    ("Who should I start this week?", "Who should I start this week and why?"),
    ("Find me a trade", "Scan the whole league for a trade that helps my lineup, slightly in my favor (about 60/40 in my value), that the other manager would plausibly accept. Show the offer ladder."),
    ("Any waiver moves?", "Do I need any add/drop or streaming move this week? If not, say so."),
    ("Is anyone injured?", "Is anyone on my team injured or on a bye, and what should I do?"),
]


def render(ctx: Ctx) -> None:
    ss = st.session_state
    ss.setdefault("chat_api", []); ss.setdefault("chat_session", None); ss.setdefault("chat_ui", [])
    html('<div class="ctxbar">' + ui.chip("AI advice, not ESPN data", "ai", "auto_awesome") + "".join(ui.chip(t, "", i) for t, i in ai_runner.context_chips(ctx)) + "</div>")
    top = st.columns([6, 1])
    top[0].caption(f"Uses {'your Claude subscription' if ctx.cfg.chat_backend != 'api' else 'the Anthropic API'} · reads your league through tools · read-only")
    if top[1].button("Clear", key="chat_clear", icon=":material/delete_sweep:"):
        ss["chat_api"], ss["chat_ui"], ss["chat_session"] = [], [], None
        st.rerun()

    pending = None
    if not ss["chat_ui"]:
        html(ui.empty("Ask anything about your team", "I read your roster, the waiver wire, trades and news through tools, and never invent stats.", "forum"))
        cols = st.columns(len(EXAMPLES))
        for c, (label, prompt) in zip(cols, EXAMPLES):
            if c.button(label, key=f"ex_{label}", use_container_width=True):
                pending = prompt
    for role, text, trace in ss["chat_ui"]:
        with st.chat_message(role):
            st.markdown(text)
            moves_from_trace(trace, f"h{abs(hash(text)) % 10**6}")
            if trace:
                with st.expander(f"What I looked up ({len(trace)})"):
                    for t in trace:
                        st.html(f'<div class="tool">{ui.icon("data_object")} {ui.esc(t["tool"])}({ui.esc(json.dumps(t["input"])[:140])}){" - failed" if t["error"] else ""}</div>')

    prompt = pending or st.chat_input("Ask about your lineup, waivers, trades, injuries...")
    if not prompt:
        return
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Looking at your league..."):
            try:
                res = ai_runner.run(ctx, prompt, ss["chat_session"], ss["chat_api"])
            except ai_runner.AIUnavailable as e:
                html(ui.notice(ui.esc(str(e)), "warn", "smart_toy"))
                return
            except Exception as e:
                html(ui.notice(f"That request failed ({ui.esc(type(e).__name__)}). Everything else still works; try again.", "bad", "error"))
                return
        st.markdown(res.text)
    ss["chat_api"], ss["chat_session"] = res.history, res.session_id
    ss["chat_ui"] += [("user", prompt, []), ("assistant", res.text, res.tool_trace)]
    st.rerun()
