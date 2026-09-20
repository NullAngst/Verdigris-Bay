"""
ui.py -- Terminal presentation layer.

Everything the player sees is rendered here: colour, the persistent HUD,
gauges, boxed panels, section banners and the ASCII art. The rest of the
codebase stays pure logic and hands this module plain data.

DEPENDENCIES
    Standard library only. No curses, no colorama, no third party anything.
    Colour is raw ANSI SGR; boxes are Unicode box-drawing with an ASCII
    fallback. `python3 play.py` still runs on a bare CPython install.

DEGRADATION
    Three independent capability checks, each with a clean fallback:

        colour depth   truecolor -> 256 -> 16 -> none
        glyphs         Unicode -> ASCII (when the stream isn't UTF-8)
        colour at all  off when NO_COLOR is set, output isn't a TTY,
                       or TERM is 'dumb'

    So the game looks like a neon HUD in a modern terminal, and like clean
    monochrome text when piped to a file or run somewhere ancient. Set
    VERDIGRIS_ASCII=1 to force the ASCII glyph set, NO_COLOR=1 to kill colour.
"""

from __future__ import annotations

import os
import re
import sys
import shutil

# ==========================================================================
# CAPABILITY DETECTION
# ==========================================================================
def _stream_is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _want_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("VERDIGRIS_NOCOLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    if os.environ.get("VERDIGRIS_FORCE_COLOR"):
        return True
    return _stream_is_tty()


def _color_depth() -> int:
    """Return 24, 8 (=256) or 4 (=16) bits of colour."""
    ct = os.environ.get("COLORTERM", "").lower()
    if "truecolor" in ct or "24bit" in ct:
        return 24
    term = os.environ.get("TERM", "").lower()
    if "256" in term:
        return 8
    return 4


def _want_unicode() -> bool:
    if os.environ.get("VERDIGRIS_ASCII"):
        return False
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


COLOR = _want_color()
DEPTH = _color_depth() if COLOR else 0
UNICODE = _want_unicode()

# Terminal width, clamped to a readable band.
try:
    _TERM_COLS = shutil.get_terminal_size((80, 24)).columns
except Exception:
    _TERM_COLS = 80
WIDTH = max(60, min(84, _TERM_COLS - 1))


# ==========================================================================
# COLOUR & THEMES
# ==========================================================================
# Each theme is a full semantic palette. The active theme is swapped at
# runtime (persisted by the game in its save file). A theme may set mono=True
# to render as plain text with no colour at all.
_THEMES = {
    "neon": {
        "name": "Neon Noir",
        "blurb": "The default. Cyan, magenta and amber on black.",
        "pal": {
            "cyan": (0, 224, 255), "magenta": (255, 64, 168),
            "amber": (255, 176, 48), "green": (72, 226, 156),
            "red": (255, 78, 78), "blue": (96, 140, 255),
            "verd": (58, 176, 150), "grey": (138, 146, 128),
            "ink": (228, 226, 214), "white": (245, 245, 236),
        },
    },
    "vaporwave": {
        "name": "Vaporwave",
        "blurb": "80s pastel. Hot pink, lavender and teal.",
        "pal": {
            "cyan": (108, 223, 247), "magenta": (255, 113, 206),
            "amber": (255, 199, 125), "green": (149, 236, 190),
            "red": (255, 109, 150), "blue": (167, 132, 255),
            "verd": (129, 214, 214), "grey": (170, 150, 190),
            "ink": (233, 224, 245), "white": (247, 236, 252),
        },
    },
    "matrix": {
        "name": "Matrix",
        "blurb": "Green phosphor. Everything is the wire.",
        "pal": {
            "cyan": (120, 255, 170), "magenta": (0, 230, 110),
            "amber": (160, 255, 120), "green": (0, 255, 90),
            "red": (190, 255, 70), "blue": (60, 220, 140),
            "verd": (0, 220, 110), "grey": (60, 120, 70),
            "ink": (120, 220, 140), "white": (200, 255, 200),
        },
    },
    "amber": {
        "name": "Amber CRT",
        "blurb": "A dead terminal's warm monochrome glow.",
        "pal": {
            "cyan": (255, 200, 120), "magenta": (255, 150, 60),
            "amber": (255, 176, 48), "green": (255, 210, 130),
            "red": (255, 120, 40), "blue": (255, 190, 110),
            "verd": (240, 180, 90), "grey": (150, 110, 60),
            "ink": (240, 190, 120), "white": (255, 224, 170),
        },
    },
    "ice": {
        "name": "Ice",
        "blurb": "Cold blues and white. The Terraces at night.",
        "pal": {
            "cyan": (120, 230, 255), "magenta": (150, 180, 255),
            "amber": (180, 215, 255), "green": (150, 240, 230),
            "red": (255, 140, 160), "blue": (90, 150, 255),
            "verd": (120, 220, 220), "grey": (130, 150, 170),
            "ink": (210, 228, 245), "white": (240, 248, 255),
        },
    },
    "mono": {
        "name": "Mono (no theme)",
        "blurb": "No colour at all. Plain text.",
        "mono": True,
        "pal": {},
    },
}

DEFAULT_THEME = "neon"
_active_name = DEFAULT_THEME
_active_pal = dict(_THEMES[DEFAULT_THEME]["pal"])
_active_mono = False

_RESET = "\x1b[0m"

# 16-colour fallback map (nearest basic/bright ANSI foreground code).
_ANSI16 = {
    "cyan": 96, "magenta": 95, "amber": 93, "green": 92, "red": 91,
    "blue": 94, "verd": 36, "grey": 90, "ink": 37, "white": 97,
}


def theme_names() -> list[str]:
    return list(_THEMES.keys())


def theme_label(name: str) -> str:
    return _THEMES.get(name, {}).get("name", name)


def theme_blurb(name: str) -> str:
    return _THEMES.get(name, {}).get("blurb", "")


def active_theme() -> str:
    return _active_name


def set_theme(name: str) -> bool:
    """Switch the active theme. Returns False for an unknown name."""
    global _active_name, _active_pal, _active_mono
    if name not in _THEMES:
        return False
    _active_name = name
    spec = _THEMES[name]
    _active_mono = bool(spec.get("mono"))
    _active_pal = dict(_THEMES["neon"]["pal"])   # fall back for any missing key
    _active_pal.update(spec.get("pal", {}))
    return True


def _colored() -> bool:
    return COLOR and not _active_mono


def _rgb_to_256(r: int, g: int, b: int) -> int:
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)
    ri, gi, bi = (round(c / 255 * 5) for c in (r, g, b))
    return 16 + 36 * ri + 6 * gi + bi


def _fg(name: str) -> str:
    if not _colored():
        return ""
    r, g, b = _active_pal.get(name, (228, 226, 214))
    if DEPTH >= 24:
        return f"\x1b[38;2;{r};{g};{b}m"
    if DEPTH >= 8:
        return f"\x1b[38;5;{_rgb_to_256(r, g, b)}m"
    return f"\x1b[{_ANSI16.get(name, 37)}m"


def color(text: str, name: str = "ink", *, bold: bool = False,
          dim: bool = False) -> str:
    """Wrap text in an SGR sequence for the given semantic colour."""
    if not _colored():
        return text
    seq = _fg(name)
    if bold:
        seq += "\x1b[1m"
    if dim:
        seq += "\x1b[2m"
    return f"{seq}{text}{_RESET}" if seq else text


def bold(text: str) -> str:
    return f"\x1b[1m{text}{_RESET}" if _colored() else text


def dim(text: str) -> str:
    return f"\x1b[2m{text}{_RESET}" if _colored() else text


_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def vis_len(text: str) -> int:
    """Visible length, ignoring SGR escapes."""
    return len(_SGR_RE.sub("", text))


def pad(text: str, width: int, align: str = "left") -> str:
    """Pad to a visible width, escape-aware."""
    gap = width - vis_len(text)
    if gap <= 0:
        return text
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


# ==========================================================================
# GLYPHS
# ==========================================================================
_U = {
    "hp": "\u2665", "coh": "\u25c8", "trace": "\u25ce", "heat": "\u25b2",
    "cred": "\u00a4", "xp": "\u2605", "lvl": "\u2691",
    "bar_full": "\u2588", "bar_half": "\u2593", "bar_empty": "\u2591",
    "tl": "\u256d", "tr": "\u256e", "bl": "\u2570", "br": "\u256f",
    "h": "\u2500", "v": "\u2502", "lt": "\u251c", "rt": "\u2524",
    "dh": "\u2550", "cross": "\u256a",
    "dot": "\u25aa", "arrow": "\u25b8", "chev": "\u203a", "diamond": "\u2666",
    "skull": "\u2620", "warn": "\u26a0", "check": "\u2713", "cross_x": "\u2717",
    "target": "\u25c9", "spark": "\u2742", "node": "\u25c6", "empty_node": "\u25c7",
    "up": "\u25b4", "down": "\u25be", "sep": "\u00b7",
}
_A = {
    "hp": "HP", "coh": "CO", "trace": "TR", "heat": "HT",
    "cred": "$", "xp": "*", "lvl": "^",
    "bar_full": "#", "bar_half": "=", "bar_empty": ".",
    "tl": "+", "tr": "+", "bl": "+", "br": "+",
    "h": "-", "v": "|", "lt": "+", "rt": "+",
    "dh": "=", "cross": "+",
    "dot": "*", "arrow": ">", "chev": ">", "diamond": "*",
    "skull": "X", "warn": "!", "check": "+", "cross_x": "x",
    "target": "O", "spark": "*", "node": "#", "empty_node": "o",
    "up": "^", "down": "v", "sep": "-",
}


def g(name: str) -> str:
    return (_U if UNICODE else _A).get(name, "?")


# ==========================================================================
# PRIMITIVES
# ==========================================================================
def rule(char: str | None = None, name: str = "grey") -> str:
    ch = char or g("h")
    return color(ch * WIDTH, name, dim=True)


def gauge(value: int, maxv: int, width: int = 16, name: str = "green") -> str:
    """A block bar: filled/half/empty cells scaled to width."""
    maxv = max(1, maxv)
    frac = max(0.0, min(1.0, value / maxv))
    filled = int(frac * width)
    rem = frac * width - filled
    cells = g("bar_full") * filled
    if filled < width and rem >= 0.5:
        cells += g("bar_half")
        filled += 1
    cells += g("bar_empty") * (width - filled)
    return color(cells, name)


def _threshold_color(frac: float, invert: bool = False) -> str:
    """Green/amber/red by fraction. invert=True for meters where high is bad."""
    if invert:
        if frac >= 0.75:
            return "red"
        if frac >= 0.40:
            return "amber"
        return "green"
    if frac <= 0.25:
        return "red"
    if frac <= 0.55:
        return "amber"
    return "green"


# ==========================================================================
# PANELS AND BANNERS
# ==========================================================================
def banner(text: str, name: str = "magenta") -> str:
    """A section header: brand-coloured rule, title, rule."""
    title = text.upper()
    label = f"{g('arrow')} {title} "
    tail = vis_len(label)
    line = color(label, name, bold=True) + color(g("h") * max(0, WIDTH - tail), name, dim=True)
    top = color(g("dh") * WIDTH, name, dim=True)
    return f"\n{top}\n{line}"


def panel(title: str, lines: list[str], name: str = "cyan",
          inner_width: int | None = None) -> str:
    """A boxed panel. `lines` are pre-formatted (may contain colour)."""
    iw = inner_width or (WIDTH - 4)
    out = []
    tl, tr, bl, br = g("tl"), g("tr"), g("bl"), g("br")
    h, v = g("h"), g("v")

    if title:
        cap = f"{h} {color(title.upper(), name, bold=True)} "
        fill = WIDTH - 2 - vis_len(cap)
        out.append(color(tl, name) + color(h, name, dim=True)
                   + cap + color(h * max(0, fill), name, dim=True) + color(tr, name))
    else:
        out.append(color(tl + h * (WIDTH - 2) + tr, name, dim=True))

    for ln in lines:
        body = pad(ln, WIDTH - 4)
        out.append(color(v, name, dim=True) + " " + body + " " + color(v, name, dim=True))

    out.append(color(bl + h * (WIDTH - 2) + br, name, dim=True))
    return "\n".join(out)


def bullet(text: str, name: str = "cyan") -> str:
    return f"  {color(g('chev'), name)} {text}"


# ==========================================================================
# HUD
# ==========================================================================
def _stat_block(char) -> str:
    from . import content
    parts = []
    for k in content.ATTRIBUTES:
        eff = char.attr(k)
        base = char.base_attr(k)
        if eff > base:
            parts.append(f"{color(k, 'grey')} {color(str(eff), 'green', bold=True)}")
        elif eff < base:
            parts.append(f"{color(k, 'grey')} {color(str(eff), 'red', bold=True)}")
        else:
            parts.append(f"{color(k, 'grey')} {color(str(eff), 'ink')}")
    return "  ".join(parts)


def wound_label(hp: int, hp_max: int) -> tuple[str, str]:
    """(label, colour) for the current wound state. '' when healthy."""
    frac = hp / max(1, hp_max)
    if hp <= 0:
        return "FLATLINE", "red"
    if frac <= 0.25:
        return "MORTAL", "red"
    if frac <= 0.50:
        return "WOUNDED", "amber"
    return "", "green"


def hud(db, char, *, compact: bool = True) -> str:
    """
    The persistent status bar shown before each command prompt.

    compact=True  -> three tight lines with gauges (every-turn readout)
    compact=False -> the full character sheet (the 'status' command)
    """
    from . import content, netrun
    from .rules import get_heat

    p = char.row
    dist = content.DISTRICTS[p["district"]]
    band, _ = char.coherence_band()
    heat = get_heat(db, p["district"])
    tband = netrun.trace_band(p["trace"])
    wl, wc = wound_label(p["hp"], p["hp_max"])

    hp_c = _threshold_color(p["hp"] / max(1, p["hp_max"]))
    coh_c = _threshold_color(p["coherence"] / 100)
    trace_c = _threshold_color(p["trace"] / 100, invert=True)
    heat_c = _threshold_color(heat / 100, invert=True)

    name = color(p["name"], "white", bold=True)
    handle = color(f'"{p["handle"]}"', "magenta")
    role = color(p["role"].upper(), "cyan")
    loc = color(dist["name"], "verd", bold=True)

    hp = p["hp"]
    hp_max = p["hp_max"]
    coh = p["coherence"]
    trace = p["trace"]
    creds = p["credits"]

    hp_txt = "{:>3}/{:<3}".format(hp, hp_max)
    coh_txt = "{:>3}".format(coh)
    trace_txt = "{:>3}".format(trace)
    heat_txt = "{:>3}".format(heat)
    cred_txt = "{:,}cr".format(creds)

    sep = color(g("sep"), "grey")

    lines = []
    # Row 1: identity + place
    ident = name + " " + handle + " " + sep + " " + role
    place = (color(g("lvl"), "amber") + " L" + str(p["level"]) + "   "
             + loc + "   " + color("T" + str(db.turn), "grey"))
    lines.append(pad(ident, WIDTH - vis_len(place)) + place)

    # Row 2: HP + Coherence gauges
    hp_seg = (color(g("hp"), hp_c) + " HP " + gauge(hp, hp_max, 14, hp_c) + " "
              + color(hp_txt, hp_c, bold=True))
    coh_seg = (color(g("coh"), coh_c) + " COH " + gauge(coh, 100, 12, coh_c) + " "
               + color(coh_txt, coh_c, bold=True) + " " + color(band, "grey"))
    lines.append(pad(hp_seg, WIDTH - vis_len(coh_seg)) + coh_seg)

    # Row 3: trace + heat + credits
    trace_seg = (color(g("trace"), trace_c) + " TRACE " + gauge(trace, 100, 10, trace_c)
                 + " " + color(trace_txt, trace_c) + " " + color(tband, "grey"))
    heat_seg = (color(g("heat"), heat_c) + " HEAT " + gauge(heat, 100, 10, heat_c)
                + " " + color(heat_txt, heat_c))
    cred_seg = color(g("cred"), "amber") + " " + color(cred_txt, "amber", bold=True)
    right = heat_seg + "   " + cred_seg
    lines.append(pad(trace_seg, WIDTH - vis_len(right)) + right)

    # Optional status / wound / skill-point flags
    flags = []
    if wl:
        flags.append(color(f"{g('warn')} {wl}", wc, bold=True))
    st = char.statuses()
    if st:
        flags.append(color(g("sep"), "grey") + " " + ", ".join(
            color(f"{e['effect']}({e['turns']})", "amber") for e in st))
    pts = db.flag("skill_points", 0)
    if pts:
        flags.append(color(f"{g('spark')} {pts} skill pts (train)", "green", bold=True))
    if flags:
        lines.append("  ".join(flags))

    if compact:
        body = "\n".join("  " + ln for ln in lines)
        top = (color(g("tl"), "verd", dim=True) + color(
            g("h") * (WIDTH - 2), "verd", dim=True) + color(g("tr"), "verd", dim=True))
        bot = color(g("bl") + g("h") * (WIDTH - 2) + g("br"), "verd", dim=True)
        return f"{top}\n{body}\n{bot}"

    # Full sheet
    extra = [
        "",
        _stat_block(char),
        f"{color('Armour SP', 'grey')} {color(str(char.armor_sp()), 'blue', bold=True)}   "
        f"{color('XP', 'grey')} {color(str(p['xp']), 'ink')}",
    ]
    return panel(f'{p["name"]} "{p["handle"]}" {g("sep")} {p["role"]}',
                 lines + extra, "cyan")


# ==========================================================================
# ASCII ART
# ==========================================================================
_LOGO = r"""
 __   __  ____  ____  ____  ____  ___  ____  ____  ____
(  \ / )( ___)(  _ \(  _ \(_  _)/ __)(  _ \(_  _)/ ___)
 \ V /  )__)  )   / )(_) ) )(( (_-. )   / _)(_ \___ \
  \_/  (____)(_)\_)(____/ (__) \___/(_)\_)(____)(____/
              B   A   Y
"""


def title_screen() -> str:
    lines = []
    for raw in _LOGO.strip("\n").splitlines():
        lines.append(color(raw, "magenta", bold=True))
    art = "\n".join(lines)
    sub = color("  a cyberpunk survival RPG " + g("sep") + " Verdigris Bay", "cyan")
    tag = dim("  the tide comes in twice a day through streets nobody condemned")
    frame_top = color(g("dh") * WIDTH, "verd", dim=True)
    return f"\n{frame_top}\n{art}\n\n{sub}\n{tag}\n{frame_top}"


def scene_frame(kind: str, title: str) -> str:
    """A small motif + banner for a specific screen kind."""
    motifs = {
        "combat":  ("red",     g("target")),
        "netrun":  ("cyan",    g("node")),
        "clinic":  ("green",   g("coh")),
        "market":  ("amber",   g("cred")),
        "story":   ("magenta", g("diamond")),
        "travel":  ("verd",    g("arrow")),
        "explore": ("blue",    g("spark")),
        "ending":  ("magenta", g("skull")),
    }
    name, icon = motifs.get(kind, ("magenta", g("diamond")))
    label = f"{icon} {title.upper()} {icon}"
    tail = vis_len(label) + 2
    line = (color(label, name, bold=True) + " "
            + color(g("h") * max(0, WIDTH - tail), name, dim=True))
    top = color(g("dh") * WIDTH, name, dim=True)
    return f"\n{top}\n{line}"


# ==========================================================================
# NETRUN VISUALS
# ==========================================================================
def net_ladder(nodes: list, position: int, name: str = "cyan") -> str:
    """A vertical ladder of nodes showing progress into a host."""
    cells = []
    for i in range(len(nodes)):
        if i < position:
            cells.append(color(g("node"), "green"))
        elif i == position:
            cells.append(color(g("target"), name, bold=True))
        else:
            cells.append(color(g("empty_node"), "grey", dim=True))
    link = color(g("h"), name, dim=True)
    return "  " + link.join(cells)


# ==========================================================================
# ROLE ICONS
# ==========================================================================
ROLE_ICON = {
    "Runner":   g("node"),
    "Enforcer": g("target"),
    "Fixer":    g("diamond"),
    "Techie":   g("spark"),
    "Medic":    g("coh"),
    "Scavver":  g("arrow"),
}
