"""WCAG contrast check of the dark-only silver palette (text on every surface, status colors, button text on the silver gradient).
Exits non-zero if any text pair is below 4.5:1 (3:1 for the large 28px+ numbers)."""
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


P = dict(bg="#121214", surface="#1a1a1d", raised="#222226", border="#303036", text="#ececf0", muted="#a1a1aa", silver="#c9ccd6", silver_hi="#e6e8ef",
         good="#86d4ab", warn="#e4bf80", bad="#f09aa2")


def pairs():
    out = []
    for s in ("bg", "surface", "raised"):
        out += [(f"text on {s}", P["text"], P[s], 4.5), (f"muted text on {s}", P["muted"], P[s], 4.5), (f"silver text on {s}", P["silver"], P[s], 4.5)]
    out += [("muted text on hover wash", P["muted"], over("#ececf0", .1, P["surface"]), 4.5), ("active nav text (bright silver) on its highlight", P["silver_hi"], over("#ececf0", .1, P["surface"]), 4.5)]
    out += [("near-black text on silver button (top)", "#121214", "#e6e8ef", 4.5), ("near-black text on silver button (bottom)", "#121214", "#b9bcc8", 4.5)]
    for k, tint in (("good", P["good"]), ("warn", P["warn"]), ("bad", P["bad"])):
        out += [(f"{k} text on its tint over surface", P[k], over(tint, .12, P["surface"]), 4.5), (f"{k} text on surface", P[k], P["surface"], 4.5)]
    out.append(("placeholder text on input", "#7a7a84", P["bg"], 3.0))
    return out


def main() -> int:
    bad = 0
    for label, fg, bg, need in pairs():
        r = ratio(fg, bg)
        ok = r >= need
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {r:5.2f}:1 (need {need}) {label}  {fg} on {bg}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
