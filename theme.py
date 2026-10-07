"""Theme: Light / Dark / System tokens, persisted in SQLite, injected as one <style> block."""
from __future__ import annotations

import os
from typing import Optional

import db

MODES = ["System", "Light", "Dark"]
_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "theme.css")

LIGHT = """
  --bg-0:#e7eaef; --bg-1:#f5f6f8; --atmo-1:rgba(140,150,255,.20); --atmo-2:rgba(110,200,225,.16);
  --ink:#14171c; --ink-2:#464e5a; --ink-3:#737b88;
  --glass:rgba(255,255,255,.58); --glass-med:rgba(255,255,255,.78); --glass-line:rgba(255,255,255,.75); --glass-hi:rgba(255,255,255,.95);
  --solid:#fbfbfc; --solid-2:#eff1f4; --chip:rgba(20,23,28,.06); --hover:rgba(20,23,28,.045);
  --line:rgba(20,23,28,.09); --line-strong:rgba(20,23,28,.22); --shadow:rgba(30,40,70,.13); --shadow-soft:rgba(30,40,70,.06);
  --blur:20px; --ring-gap:rgba(255,255,255,.85); --logo-bg:rgba(255,255,255,.96);
  --good:#13804f; --good-bg:rgba(19,128,79,.11); --warn:#a85f00; --warn-bg:rgba(224,140,0,.14);
  --bad:#c0322f; --bad-bg:rgba(214,58,52,.11); --info:#2f5bd0; --info-bg:rgba(47,91,208,.10); --ai:#6c4bd1; --ai-bg:rgba(108,75,209,.11);
  color-scheme: light;
"""
DARK = """
  --bg-0:#0c0e11; --bg-1:#14171c; --atmo-1:rgba(95,110,255,.17); --atmo-2:rgba(60,170,200,.10);
  --ink:#f1f3f6; --ink-2:#b5bcc8; --ink-3:#858d9a;
  --glass:rgba(38,43,52,.58); --glass-med:rgba(46,52,62,.78); --glass-line:rgba(255,255,255,.13); --glass-hi:rgba(255,255,255,.14);
  --solid:#1a1e24; --solid-2:#232830; --chip:rgba(255,255,255,.08); --hover:rgba(255,255,255,.06);
  --line:rgba(255,255,255,.09); --line-strong:rgba(255,255,255,.26); --shadow:rgba(0,0,0,.5); --shadow-soft:rgba(0,0,0,.28);
  --blur:22px; --ring-gap:rgba(20,23,28,.9); --logo-bg:rgba(255,255,255,.92);
  --good:#4ad28f; --good-bg:rgba(74,210,143,.14); --warn:#f2b04a; --warn-bg:rgba(242,176,74,.15);
  --bad:#ff7a73; --bad-bg:rgba(255,122,115,.15); --info:#7fa0ff; --info-bg:rgba(127,160,255,.15); --ai:#b69cff; --ai-bg:rgba(182,156,255,.15);
  color-scheme: dark;
"""


def get_mode(db_path: Optional[str] = None) -> str:
    m = db.setting_get("theme_mode", "System", db_path)
    return m if m in MODES else "System"


def set_mode(mode: str, db_path: Optional[str] = None) -> None:
    if mode in MODES:
        db.setting_set("theme_mode", mode, db_path)


def get_accent_team(db_path: Optional[str] = None) -> str:
    return db.setting_get("accent_team", "", db_path)


def set_accent_team(abbr: str, db_path: Optional[str] = None) -> None:
    db.setting_set("accent_team", abbr, db_path)


def css(mode: str = "System", accent: str = "#4f74e3", accent_ink: str = "#ffffff") -> str:
    """Full stylesheet: tokens for the chosen mode + the design-system rules."""
    if mode == "Dark":
        tokens = f":root{{{DARK}}}"
    elif mode == "Light":
        tokens = f":root{{{LIGHT}}}"
    else:
        tokens = f":root{{{LIGHT}}} @media (prefers-color-scheme: dark){{:root{{{DARK}}}}}"
    accent_rule = f":root{{--accent:{accent}; --accent-ink:{accent_ink};}}"
    with open(_CSS, encoding="utf-8") as f:
        body = f.read()
    imports = "".join(line + "\n" for line in body.splitlines() if line.startswith("@import"))   # @import must come first
    body = "\n".join(line for line in body.splitlines() if not line.startswith("@import"))
    return f"<style>{imports}{tokens}\n{accent_rule}\n{body}</style>"


# "/" or Cmd/Ctrl+K focuses the player search; skipped while typing in any field.
SHORTCUT_JS = """
<script>
(function () {
  if (window.__fhKeys) return; window.__fhKeys = true;
  window.addEventListener('keydown', function (e) {
    var t = e.target, typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    var cmdk = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
    if (!(cmdk || (e.key === '/' && !typing))) return;
    var box = document.querySelector('.st-key-search input');
    if (box) { e.preventDefault(); box.focus(); box.select && box.select(); }
  });
})();
</script>
"""
