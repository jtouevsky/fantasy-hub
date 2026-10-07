"""Theme: Light / Dark / System tokens, persisted in SQLite, injected as one <style> block."""
from __future__ import annotations

import os
from typing import Optional

import db

MODES = ["System", "Light", "Dark"]
_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "theme.css")

LIGHT = """
  --bg-0:#e7eaef; --bg-1:#f5f6f8; --atmo-1:rgba(255,255,255,.80); --atmo-2:rgba(160,168,182,.20); --hi-wash:rgba(255,255,255,.50);
  --ink:#14171c; --ink-2:#464e5a; --ink-3:#737b88;
  --glass:rgba(255,255,255,.58); --glass-med:rgba(255,255,255,.78); --glass-line:rgba(255,255,255,.75); --glass-hi:rgba(255,255,255,.95);
  --solid:#fbfbfc; --solid-2:#eff1f4; --chip:rgba(20,23,28,.06); --hover:rgba(20,23,28,.045);
  --line:rgba(20,23,28,.09); --line-strong:rgba(20,23,28,.22); --shadow:rgba(30,40,70,.13); --shadow-soft:rgba(30,40,70,.06);
  --blur:20px; --ring-gap:rgba(255,255,255,.85); --logo-bg:rgba(255,255,255,.96);
  --good:#13804f; --good-bg:rgba(19,128,79,.11); --warn:#a85f00; --warn-bg:rgba(224,140,0,.14);
  --bad:#c0322f; --bad-bg:rgba(214,58,52,.11); --info:#3b4452; --info-bg:rgba(59,68,82,.09); --ai:#3b4452; --ai-bg:rgba(59,68,82,.09);
  --accent:#3a424e; --accent-ink:#ffffff;
  /* graphite-silver: stays visible on off-white */
  --silver-edge:linear-gradient(135deg,#a0a8b4 0%,#5b6471 26%,#c0c6cf 50%,#68717e 74%,#a6aeb9 100%); --sheen:rgba(255,255,255,.96);
  color-scheme: light;
"""
DARK = """
  --bg-0:#0c0e11; --bg-1:#14171c; --atmo-1:rgba(255,255,255,.07); --atmo-2:rgba(150,160,176,.06); --hi-wash:rgba(255,255,255,.05);
  --ink:#f1f3f6; --ink-2:#b5bcc8; --ink-3:#858d9a;
  --glass:rgba(38,43,52,.58); --glass-med:rgba(46,52,62,.78); --glass-line:rgba(255,255,255,.13); --glass-hi:rgba(255,255,255,.14);
  --solid:#1a1e24; --solid-2:#232830; --chip:rgba(255,255,255,.08); --hover:rgba(255,255,255,.06);
  --line:rgba(255,255,255,.09); --line-strong:rgba(255,255,255,.26); --shadow:rgba(0,0,0,.5); --shadow-soft:rgba(0,0,0,.28);
  --blur:22px; --ring-gap:rgba(20,23,28,.9); --logo-bg:rgba(255,255,255,.92);
  --good:#4ad28f; --good-bg:rgba(74,210,143,.14); --warn:#f2b04a; --warn-bg:rgba(242,176,74,.15);
  --bad:#ff7a73; --bad-bg:rgba(255,122,115,.15); --info:#c6cdd8; --info-bg:rgba(198,205,216,.12); --ai:#d5dbe4; --ai-bg:rgba(213,219,228,.12);
  --accent:#d3d9e2; --accent-ink:#12151a;
  /* brighter cool silver on graphite */
  --silver-edge:linear-gradient(135deg,#e8edf4 0%,#8993a2 26%,#f6f8fb 50%,#97a1b0 74%,#dde3ec 100%); --sheen:rgba(255,255,255,1);
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


def css(mode: str = "System", accent: Optional[str] = None, accent_ink: str = "#ffffff") -> str:
    """Full stylesheet: tokens for the chosen mode + the design-system rules."""
    if mode == "Dark":
        tokens = f":root{{{DARK}}}"
    elif mode == "Light":
        tokens = f":root{{{LIGHT}}}"
    else:
        tokens = f":root{{{LIGHT}}} @media (prefers-color-scheme: dark){{:root{{{DARK}}}}}"
    # default accent is neutral graphite/silver (set per mode in the tokens); only a chosen accent team overrides it
    accent_rule = f":root{{--accent:{accent}; --accent-ink:{accent_ink};}}" if accent else ""
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
