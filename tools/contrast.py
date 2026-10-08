"""WCAG contrast check of the v4 palette pairs (light and dark). Fails (exit 1) if a text pair is below 4.5:1 (3:1 for the large display text pairs)."""
import sys


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def over(fg, a, bg):
    f, b = rgb(fg), rgb(bg)
    return "#%02x%02x%02x" % tuple(round(a * x + (1 - a) * y) for x, y in zip(f, b))


def lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb(h))
    return .2126 * r + .7152 * g + .0722 * b


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + .05) / (lb + .05)


LIGHT = dict(bg="#fbf5e8", card="#ffffff", ink="#16130f", ink2="#4a443a", ink3="#766f62", cobalt="#446bf2", lime="#c5e647", coral="#f56d5c", sun="#f5c753", grape="#805be8", teal="#24aea0",
             good="#087a45", warn="#8f5200", bad="#c8102e", info="#2d4fd0")
DARK = dict(bg="#14131c", card="#211f30", ink="#f6f1e4", ink2="#c9c2b2", ink3="#9a9384", cobalt="#556ddd", lime="#c5e647", coral="#f58271", sun="#f5c753", grape="#835edd", teal="#3ec8b9",
            good="#4ad28f", warn="#ffc83d", bad="#ff7a8e", info="#9db2ff")


def pairs(t, dark):
    on = {"cobalt": "#ffffff", "lime": "#16130f", "coral": "#16130f", "sun": "#16130f", "grape": "#ffffff", "teal": "#16130f"}
    out = [("body text", t["ink"], t["bg"], 4.5), ("body text on card", t["ink"], t["card"], 4.5), ("secondary text on card", t["ink2"], t["card"], 4.5), ("muted text on card", t["ink3"], t["card"], 4.5),
           ("muted text on page", t["ink3"], t["bg"], 4.5)]
    for k, fg in on.items():
        out.append((f"band/button text on {k}", fg, t[k], 4.5))
    for k, a in (("good", .13), ("warn", .34 if not dark else .17), ("bad", .11 if not dark else .16), ("info", .11 if not dark else .2)):
        tint = {"good": t["good"], "warn": "#ffc83d", "bad": t["bad"], "info": t["cobalt"]}[k]
        out.append((f"{k} text on its tint (over card)", t[k], over(tint, a, t["card"]), 4.5))
    out.append(("ink text on lime value panel", "#16130f", t["lime"], 4.5)); out.append(("ink text on sunflower value panel", "#16130f", t["sun"], 4.5))
    return out


def main() -> int:
    bad = 0
    for name, t, dark in (("LIGHT", LIGHT, False), ("DARK", DARK, True)):
        print(f"\n{name}")
        for label, fg, bg, need in pairs(t, dark):
            r = ratio(fg, bg)
            ok = r >= need
            bad += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {r:5.2f}:1 (need {need}) {label}  {fg} on {bg}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
