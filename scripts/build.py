"""Builds the bento-grid profile README for github.com/shira421.

    python scripts/build.py          # from the repo root

GitHub strips <style>, class and Tailwind from README HTML, so every tile is an
SVG carrying Tailwind's design tokens (zinc + emerald palette, radius, font
stacks). Tiles sit on a 1000-unit-wide canvas with an 8-unit transparent
gutter baked in, so tiles placed edge to edge leave the same 16-unit gap in
both directions.

Static tiles (hero, projects, stack...) always build. Live tiles (stats,
streak, languages, repo cards) need GH_STATS_TOKEN or GITHUB_TOKEN; without a
token, or if the API fails, the previous live tiles are left untouched.
"""
import base64, json, math, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape

LOGIN = "shira421"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
ICONS = os.path.join(ROOT, "scripts", "icons")
SGT = timezone(timedelta(hours=8))
os.makedirs(ASSETS, exist_ok=True)

# Repo cards: (repo, course or context line, description override or None for the GitHub one)
REPO_CARDS = [
    ("shira421/cg2271_as4", "CG2271 Real-Time Operating Systems",
     "PetPal: an ESP32 and NXP MCXC444 device with a companion web dashboard."),
    ("shira421/cg2028_assignment", "CG2028 Computer Organisation",
     "Fall detection on an STM32L4S5 board that tells a fall apart from walking or bending."),
    ("shira421/cg2111_2425", "CG2111A Engineering Principles II",
     "Alex, a teleoperated robot that maps unknown terrain and finds casualties by colour."),
    ("shira421/cg1111a_project", "CG1111A Engineering Principles I",
     "An mBot that races through the A-maze-ing Race maze using ultrasonic and IR sensing."),
]
# Vendored/generated code that would otherwise swamp the language chart.
HIDE_LANGS = {"HTML", "CSS", "Tcl", "VHDL", "CMake", "Dockerfile", "Batchfile", "Shell",
              "Procfile", "TeX", "PowerShell", "Makefile"}
TOOL_ICONS = ["c", "cpp", "py", "java", "js", "react", "django", "aws", "postgres", "tensorflow",
              "sklearn", "opencv", "git", "linux", "gradle", "githubactions", "raspberrypi", "arduino"]

# ---- Primitives: Tailwind v3 palette -------------------------------------
ZINC = {"50": "#fafafa", "300": "#d4d4d8", "400": "#a1a1aa", "700": "#3f3f46",
        "800": "#27272a", "900": "#18181b", "950": "#09090b"}
EMERALD = {"300": "#6ee7b7", "400": "#34d399", "500": "#10b981", "700": "#047857", "900": "#064e3b"}

# ---- Semantic tokens: the only names tiles use ---------------------------
T = {
    "surface-card": ZINC["900"],
    "surface-inset": ZINC["950"],
    "surface-chip": ZINC["800"],
    "border-card": ZINC["800"],
    "border-chip": ZINC["700"],
    "decor-muted": ZINC["800"],
    "text-primary": ZINC["50"],
    "text-secondary": ZINC["300"],
    "text-tertiary": ZINC["400"],
    "accent-text": EMERALD["400"],
    "accent-decor": EMERALD["500"],
    # Sequential ramp for contribution intensity, empty -> busiest.
    "heat": [ZINC["800"], EMERALD["900"], EMERALD["700"], EMERALD["500"], EMERALD["300"]],
}

SANS = 'ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif'
MONO = 'ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace'

G = 8       # half gutter (gap between tiles = 16)
R = 20      # card radius
P = 28      # card padding
X0 = G + P  # content start = 36

STYLE = f"""<style>
.sans{{font-family:{SANS}}}
.mono{{font-family:{MONO}}}
.tp{{fill:{T['text-primary']}}}
.ts{{fill:{T['text-secondary']}}}
.tt{{fill:{T['text-tertiary']}}}
.ta{{fill:{T['accent-text']}}}
.blink{{animation:blink 1.1s steps(1) infinite}}
@keyframes blink{{50%{{opacity:0}}}}
.pulse{{transform-box:fill-box;transform-origin:center;animation:pulse 2s ease-out infinite}}
@keyframes pulse{{0%{{transform:scale(1);opacity:.7}}100%{{transform:scale(2.6);opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.blink{{animation:none}}.pulse{{animation:none;opacity:0}}}}
</style>"""


# ---- Drawing helpers --------------------------------------------------------
def text(x, y, s, size, cls="tp", weight=400, family="sans", anchor=None, ls=None, extra=""):
    a = f' text-anchor="{anchor}"' if anchor else ""
    l = f' letter-spacing="{ls}"' if ls is not None else ""
    return (f'<text x="{x}" y="{y}" class="{family} {cls}" font-size="{size}" '
            f'font-weight="{weight}"{a}{l}{extra}>{escape(str(s))}</text>')


def eyebrow(x, y, s, cls="tt"):
    return text(x, y, s.upper(), 12, cls, 500, "mono", ls=1)


def chip(x, y, label, size=13):
    w = round(len(label) * 0.6 * size + 22, 1)
    return (f'<rect x="{x}" y="{y}" width="{w}" height="28" rx="14" fill="{T["surface-chip"]}" '
            f'stroke="{T["border-chip"]}"/>'
            + text(round(x + w / 2, 1), y + 18.5, label, size, "ts", 500, "mono", anchor="middle")), w


def chips(x, y, labels, gap=8):
    out, cx = [], x
    for lab in labels:
        s, w = chip(cx, y, lab)
        out.append(s)
        cx += w + gap
    return "".join(out)


def link_arrow(w, y=38):
    """Top-right arrow: the visual cue that a tile is a link."""
    x = w - X0 - 14
    return (f'<path d="M{x} {y+14} L{x+14} {y} M{x+4} {y} H{x+14} V{y+10}" fill="none" '
            f'stroke="{T["text-tertiary"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')


def wrap(s, width, max_lines):
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    lines.append(cur)
    if len(lines) > max_lines:
        last = lines[max_lines - 1]
        lines = lines[:max_lines - 1] + [last[: width - 1].rstrip() + "…"]
    return lines


TILES = {}


def tile(name, w, h, body, title, defs=""):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'role="img" aria-labelledby="t"><title id="t">{escape(title)}</title>{STYLE}'
           f'<defs><clipPath id="card"><rect x="{G}" y="{G}" width="{w-2*G}" height="{h-2*G}" rx="{R}"/></clipPath>{defs}</defs>'
           f'<rect x="{G}" y="{G}" width="{w-2*G}" height="{h-2*G}" rx="{R}" fill="{T["surface-card"]}"/>'
           f'{body}'
           f'<rect x="{G+.5}" y="{G+.5}" width="{w-2*G-1}" height="{h-2*G-1}" rx="{R-.5}" fill="none" stroke="{T["border-card"]}"/>'
           f'</svg>')
    with open(os.path.join(ASSETS, f"{name}.svg"), "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    TILES[name] = (w, h)


def register_existing(name, w, h):
    """Live tile we could not rebuild: keep the old file in the grid if it exists."""
    if os.path.exists(os.path.join(ASSETS, f"{name}.svg")):
        TILES[name] = (w, h)


# ---- Static tiles -----------------------------------------------------------
def build_static():
    # Hero
    w, h = 580, 360
    defs = (f'<pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">'
            f'<circle cx="2" cy="2" r="1.1" fill="{T["decor-muted"]}"/></pattern>'
            f'<radialGradient id="glow" cx="1" cy="0" r="0.9"><stop offset="0" stop-color="{T["accent-decor"]}" stop-opacity=".22"/>'
            f'<stop offset="1" stop-color="{T["accent-decor"]}" stop-opacity="0"/></radialGradient>')
    body = (f'<g clip-path="url(#card)"><rect width="{w}" height="{h}" fill="url(#dots)"/>'
            f'<rect width="{w}" height="{h}" fill="url(#glow)"/></g>'
            + text(X0, 60, "canary@nus:~$ whoami", 14, "ta", 500, "mono")
            + f'<rect class="blink" x="{X0 + 20*8.4 + 6}" y="48" width="8" height="15" fill="{T["accent-text"]}"/>'
            + text(X0, 124, "Ksheerabthi Nathan", 42, "tp", 700, ls=-0.6)
            + text(X0, 160, "Computer Engineering @ NUS · Year 3", 19, "ts", 500)
            + text(X0, 206, "Embedded software, FPGA design and real-time", 17, "tt")
            + text(X0, 232, "computer vision: fast, reliable systems, from", 17, "tt")
            + text(X0, 258, "the circuit board up.", 17, "tt")
            + chips(X0, 296, ["Singapore", "Embedded Computing", "Large-Scale Computing"]))
    tile("hero", w, h, body,
         "Ksheerabthi Nathan, also known as Canary. Computer Engineering at NUS, Year 3. Embedded software, FPGA design and "
         "real-time computer vision: fast, reliable systems, from the circuit board up. Singapore. "
         "Embedded Computing and Large-Scale Computing.", defs)

    # Experience
    w, h = 420, 360
    px, py, pw, ph = X0, 36, w - 2 * X0, 104
    defs = (f'<clipPath id="panel"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="12"/></clipPath>'
            '<radialGradient id="heat"><stop offset="0" stop-color="#fffbeb"/><stop offset=".22" stop-color="#fde68a"/>'
            '<stop offset=".48" stop-color="#f97316"/><stop offset=".74" stop-color="#be123c" stop-opacity=".75"/>'
            '<stop offset="1" stop-color="#4c0519" stop-opacity="0"/></radialGradient>')
    gx, gy, gw, gh = 238, 50, 128, 76
    cx, cy = 300, 90
    body = (f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="12" fill="{T["surface-inset"]}"/>'
            f'<g clip-path="url(#panel)">'
            f'<ellipse cx="112" cy="96" rx="58" ry="62" fill="url(#heat)"/>'
            f'<ellipse cx="{cx}" cy="{cy}" rx="34" ry="36" fill="url(#heat)" opacity=".5"/></g>'
            f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="6" fill="none" stroke="{T["text-tertiary"]}" stroke-opacity=".6" stroke-dasharray="4 4"/>'
            + text(gx + 8, gy + 15, "GLASS", 10, "tt", 500, "mono", ls=1)
            + f'<g fill="none" stroke="{T["accent-text"]}" stroke-width="1.5"><circle cx="{cx}" cy="{cy}" r="11"/>'
              f'<path d="M{cx-19} {cy} h10 M{cx+9} {cy} h10 M{cx} {cy-19} v10 M{cx} {cy+9} v10"/></g>'
            + f'<rect x="{px+.5}" y="{py+.5}" width="{pw-1}" height="{ph-1}" rx="11.5" fill="none" stroke="{T["border-card"]}"/>'
            + eyebrow(X0, 176, "Experience · Dec 2025 – Jan 2026")
            + link_arrow(w, 164)
            + text(X0, 212, "PROX SG", 26, "tp", 700)
            + text(X0, 240, "Embedded Software Engineer Intern", 16, "ts", 500)
            + text(X0, 272, "Thermal imaging that detects and ranges", 15, "tt")
            + text(X0, 294, "clear glass for robots, with a real-time", 15, "tt")
            + text(X0, 316, "C++ vision pipeline on embedded Linux.", 15, "tt"))
    tile("experience", w, h, body,
         "Experience, Dec 2025 to Jan 2026: Embedded Software Engineer Intern at PROX SG. Thermal imaging that "
         "detects and ranges clear glass for robots, with a real-time C++ vision pipeline on embedded Linux.", defs)

    def project(name, w, eyebrow_s, title_s, sub, lines, chip_labels, deco="", linked=True, pulse=False, alt=""):
        pre, ex = "", X0
        if pulse:
            pre = (f'<circle class="pulse" cx="{X0+4}" cy="45.5" r="4" fill="{T["accent-text"]}"/>'
                   f'<circle cx="{X0+4}" cy="45.5" r="4" fill="{T["accent-text"]}"/>')
            ex = X0 + 16
        body = (pre + eyebrow(ex, 50, eyebrow_s, "ta" if pulse else "tt")
                + (link_arrow(w) if linked else "") + deco
                + text(X0, 96, title_s, 26, "tp", 700)
                + text(X0, 122, sub, 14, "tt")
                + "".join(text(X0, 160 + 22 * i, s, 15, "ts") for i, s in enumerate(lines))
                + chips(X0, 236, chip_labels))
        tile(name, w, 300, body, alt)

    rx, ry = 324, 70
    pins = "".join(
        f'<path d="M{rx+10+i*10} {ry-6} v6 M{rx+10+i*10} {ry+44} v6 M{rx-6} {ry+10+i*10} h6 M{rx+44} {ry+10+i*10} h6"/>'
        for i in range(3))
    deco = (f'<g stroke="{T["border-chip"]}" stroke-width="2" stroke-linecap="round">{pins}</g>'
            f'<rect x="{rx}" y="{ry}" width="44" height="44" rx="6" fill="{T["surface-inset"]}" stroke="{T["border-chip"]}"/>'
            + text(rx + 22, ry + 26, "RV32", 10, "ta", 600, "mono", anchor="middle"))
    project("riscv", 420, "Now building", "RISC-V CPU", "CG3207 Computer Architecture",
            ["A RISC-V processor in Verilog on a", "Nexys 4 FPGA, with a multi-cycle", "radix-4 Booth multiply/divide unit."],
            ["Verilog", "Vivado", "RARS"], deco, pulse=True,
            alt="Now building: RISC-V CPU, CG3207 Computer Architecture. A RISC-V processor in Verilog on a Nexys 4 "
                "FPGA, with a multi-cycle radix-4 Booth multiply/divide unit. Verilog, Vivado, RARS.")

    nodes = [(204, 82), (244, 74), (236, 112), (200, 118)]
    deco = (f'<g fill="none" stroke="{T["border-chip"]}" stroke-width="1.5">'
            f'<path d="M204 82 L244 74 L236 112 L204 82 M236 112 L200 118"/></g>'
            + "".join(f'<circle cx="{x}" cy="{y}" r="{5 if i else 6}" fill="{T["surface-card"]}" '
                      f'stroke="{T["accent-decor"] if i == 0 else T["text-tertiary"]}" stroke-width="2"/>'
                      for i, (x, y) in enumerate(nodes)))
    project("zettelcli", 290, "SWE project", "ZettelCLI", "CS2113 team project",
            ["A command-line app for", "linked, atomic notes in", "the Zettelkasten method."],
            ["Java", "Gradle", "JUnit"], deco,
            alt="Software engineering project: ZettelCLI, a CS2113 team project. A command-line app for linked, atomic "
                "notes in the Zettelkasten method. Java, Gradle, JUnit.")

    ox, oy = 196, 228
    wave = " ".join(f"{'M' if i == 0 else 'L'}{ox+6+i*2} {oy+18 - 9*math.sin(i/3.2):.1f}" for i in range(24))
    deco = (f'<rect x="{ox}" y="{oy}" width="58" height="36" rx="5" fill="{T["surface-inset"]}" stroke="{T["border-chip"]}"/>'
            f'<path d="M{ox+6} {oy+18} h46 M{ox+29} {oy+5} v26" stroke="{T["border-chip"]}"/>'
            f'<path d="{wave}" fill="none" stroke="{T["accent-text"]}" stroke-width="1.5"/>')
    project("fpga", 290, "FPGA project", "FPGA Calculator", "EE2026 Digital Design",
            ["Arithmetic and graphing", "calculator on a Basys3,", "driving dual 96×64 OLEDs."],
            ["Verilog", "Basys3"], deco,
            alt="FPGA project: FPGA Calculator, EE2026 Digital Design. Arithmetic and graphing calculator on a Basys3, "
                "driving dual 96 by 64 OLED displays. Verilog, Basys3.")

    mx, my = 204, 66
    deco = (f'<rect x="{mx}" y="{my}" width="44" height="52" rx="6" fill="{T["surface-inset"]}" stroke="{T["text-tertiary"]}" stroke-width="1.5"/>'
            f'<path d="M{mx} {my+12} h44" stroke="{T["text-tertiary"]}" stroke-width="1.5"/>'
            f'<circle cx="{mx+8}" cy="{my+6}" r="2" fill="{T["text-tertiary"]}"/>'
            f'<circle cx="{mx+22}" cy="{my+32}" r="12" fill="none" stroke="{T["text-tertiary"]}" stroke-width="1.5"/>'
            f'<path d="M{mx-8} {my+22} q-4 10 0 20 M{mx+52} {my+22} q4 10 0 20" fill="none" stroke="{T["accent-text"]}" '
            f'stroke-width="1.5" stroke-linecap="round"/>')
    project("uwash", 290, "Hackathon · Top 8", "UWash", "NUS Student Life Hack",
            ["An ESP32 vibration sensor", "and web dashboard that", "track NUS laundry rooms."],
            ["ESP32", "IoT", "Web"], deco,
            alt="Hackathon, Top 8: UWash, NUS Student Life Hack. An ESP32 vibration sensor and web dashboard that track "
                "NUS laundry rooms. ESP32, IoT, Web.")

    deco = text(290 - X0, 98, "48h", 32, "ta", 700, "mono", anchor="end", extra=' opacity=".35"')
    project("brainhack", 290, "Hackathon · Finalist", "BrainHack", "DSTA · June 2024",
            ["A sustainability-focused", "mobile app, from idea to", "working MVP in 48 hours."],
            ["React Native", "Django"], deco, linked=False,
            alt="Hackathon, Finalist: DSTA BrainHack, June 2024. A sustainability-focused mobile app, from idea to "
                "working MVP in 48 hours. React Native, Django.")

    dx, dy = 296, 66  # two stacked pages + spark
    deco = (f'<rect x="{dx+14}" y="{dy}" width="38" height="48" rx="5" fill="{T["surface-inset"]}" stroke="{T["border-chip"]}" stroke-width="1.5"/>'
            f'<rect x="{dx}" y="{dy+10}" width="38" height="48" rx="5" fill="{T["surface-inset"]}" stroke="{T["text-tertiary"]}" stroke-width="1.5"/>'
            f'<path d="M{dx+8} {dy+24} h22 M{dx+8} {dy+32} h22 M{dx+8} {dy+40} h14" stroke="{T["border-chip"]}" stroke-width="2" stroke-linecap="round"/>'
            f'<path d="M{dx+52} {dy-6} q1.5 6.5 8 8 q-6.5 1.5 -8 8 q-1.5 -6.5 -8 -8 q6.5 -1.5 8 -8 z" fill="{T["accent-text"]}"/>')
    project("opensuite", 420, "Hackathon · Claude", "OpenSuite", "Team project",
            ["A free, local-first desktop app that", "replaces paid PDF and slide tools, with", "an AI design helper on the Claude API."],
            ["TypeScript", "Python", "Claude API"], deco,
            alt="Hackathon, Claude: OpenSuite, team project. A free, local-first desktop app that replaces paid PDF and "
                "slide tools, with an AI design helper on the Claude API. TypeScript, Python, Claude API.")

    w, h = 420, 300
    body = (eyebrow(X0, 50, "Education · 2024 – 2028")
            + text(X0, 112, "4.31", 56, "ta", 700, ls=-1)
            + text(X0 + 128, 112, "/ 5.0 GPA", 20, "tt", 500)
            + text(X0, 156, "B.Eng (Hons) Computer Engineering", 17, "tp", 600)
            + text(X0, 180, "National University of Singapore", 15, "ts")
            + text(X0, 222, "Embedded & Large-Scale Computing", 14, "tt")
            + text(X0, 244, "Minor in Quantitative Finance", 14, "tt"))
    tile("education", w, h, body,
         "Education, 2024 to 2028: B.Eng (Hons) Computer Engineering, National University of Singapore. "
         "GPA 4.31 out of 5.0. Embedded and Large-Scale Computing concentrations, minor in Quantitative Finance.")

    # Tech stack: icon row (skillicons, inlined as data URIs) + labelled chip rows
    w, h = 1000, 362
    groups = [
        ("Languages", ["C", "C++", "Python", "Java", "JavaScript", "Verilog"]),
        ("ML & Data", ["TensorFlow", "YOLO", "scikit-learn", "OpenCV", "PostgreSQL"]),
        ("Web & Cloud", ["React Native", "Django", "REST APIs", "AWS"]),
        ("Tooling", ["Git", "Linux", "Gradle", "JUnit", "CI/CD", "Vivado", "STM32CubeIDE"]),
        ("Hardware", ["FPGA", "Microcontrollers", "Raspberry Pi", "Circuit Design", "3D Modelling"]),
    ]
    size = 44
    gap = (w - 2 * X0 - len(TOOL_ICONS) * size) / (len(TOOL_ICONS) - 1)
    icons = ""
    for i, name in enumerate(TOOL_ICONS):
        with open(os.path.join(ICONS, f"{name}.svg"), "rb") as f:
            data = base64.b64encode(f.read()).decode()
        icons += (f'<image x="{X0 + i*(size+gap):.1f}" y="70" width="{size}" height="{size}" '
                  f'href="data:image/svg+xml;base64,{data}"/>')
    rows = ""
    for i, (g, labs) in enumerate(groups):
        y = 138 + i * 40
        rows += text(X0, y + 18.5, g.upper(), 12, "tt", 500, "mono", ls=1) + chips(196, y, labs)
    m, a = T["decor-muted"], T["border-chip"]
    traces = (f'<g transform="translate(0 66)"><g fill="none" stroke="{m}" stroke-width="2" stroke-linecap="round">'
              f'<path d="M820 72 H880 L900 92 V150 L920 170 H964"/><path d="M840 120 H870 L880 130 V210 L900 230 H964"/>'
              f'<path d="M830 250 H850 L870 230 V190"/><path d="M930 72 V110 L950 130 H964"/></g>'
              + "".join(f'<circle cx="{x}" cy="{y}" r="4" fill="{T["surface-card"]}" stroke="{a}" stroke-width="2"/>'
                        for x, y in [(820, 72), (840, 120), (830, 250), (930, 72), (870, 190)]) + "</g>")
    body = f'<g clip-path="url(#card)">{traces}</g>' + eyebrow(X0, 50, "Tech stack") + icons + rows
    tile("stack", w, h, body, "Tech stack. " + " ".join(f"{g}: {', '.join(l)}." for g, l in groups))

    # Highlights + contact
    w, h = 580, 300
    items = [("2021", "RoboCup Worldwide", "Represented Singapore"),
             ("2021", "RoboCup Singapore Open", "Best Engineering & Distinction"),
             ("Now", "Teaching Assistant", "EG1311 Design and Make, NUS"),
             ("2018", "YDSP Data Analytics", "Champions, IoT smart home")]
    body = eyebrow(X0, 50, "Highlights")
    for i, (yr, t1, t2) in enumerate(items):
        x, y = X0 + (i % 2) * 276, 100 + (i // 2) * 96
        body += eyebrow(x, y, yr) + text(x, y + 24, t1, 17, "tp", 600) + text(x, y + 46, t2, 14, "tt")
    tile("highlights", w, h, body, "Highlights. " + " ".join(f"{yr}: {t1}, {t2}." for yr, t1, t2 in items))

    w, h = 500, 150
    ic, iy = T["text-primary"], 55
    body = (f'<rect x="{X0}" y="{iy}" width="40" height="40" rx="9" fill="{ic}"/>'
            + text(X0 + 20, iy + 28, "in", 22, "", 800, extra=f' fill="{T["surface-card"]}" text-anchor="middle"')
            + link_arrow(w, 68) + text(X0 + 60, 72, "LinkedIn", 20, "tp", 700)
            + text(X0 + 60, 96, "linkedin.com/in/ksheerabthi", 13, "tt", 400, "mono"))
    tile("linkedin", w, h, body, "LinkedIn: linkedin.com/in/ksheerabthi")
    body = (f'<g fill="none" stroke="{ic}" stroke-width="2.2" stroke-linejoin="round">'
            f'<rect x="{X0+1}" y="{iy+5}" width="38" height="30" rx="5"/>'
            f'<path d="M{X0+3} {iy+9} L{X0+20} {iy+22} L{X0+37} {iy+9}" stroke-linecap="round"/></g>'
            + link_arrow(w, 68) + text(X0 + 60, 72, "Email", 20, "tp", 700)
            + text(X0 + 60, 96, "k.nathan@u.nus.edu", 13, "tt", 400, "mono"))
    tile("email", w, h, body, "Email: k.nathan@u.nus.edu")


# ---- Live data --------------------------------------------------------------
def gql(token, query, variables=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": f"{LOGIN}-profile-builder"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


def fetch(token):
    d = gql(token, """query($login:String!){ user(login:$login){ createdAt
      repositories(ownerAffiliations:OWNER, first:100, privacy:PUBLIC){ totalCount nodes{ isFork stargazerCount
        languages(first:20, orderBy:{field:SIZE,direction:DESC}){ edges{ size node{ name color } } } } }
      pullRequests{ totalCount } issues{ totalCount }
      repositoriesContributedTo(contributionTypes:[COMMIT,PULL_REQUEST,ISSUE,REPOSITORY]){ totalCount }
      contributionsCollection{ totalCommitContributions } } }""", {"login": LOGIN})["user"]

    # Every contribution day since the account was created, one year per query.
    days = {}
    now = datetime.now(timezone.utc)
    for year in range(int(d["createdAt"][:4]), now.year + 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        cal = gql(token, """query($login:String!,$from:DateTime!,$to:DateTime!){ user(login:$login){
          contributionsCollection(from:$from,to:$to){ contributionCalendar{ weeks{ contributionDays{ date contributionCount } } } } } }""",
                  {"login": LOGIN, "from": start.isoformat(), "to": end.isoformat()})
        for wk in cal["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in wk["contributionDays"]:
                days[date.fromisoformat(day["date"])] = day["contributionCount"]

    aliases = []
    for i, (full, _, _) in enumerate(REPO_CARDS):
        owner, name = full.split("/")
        aliases.append(f'r{i}: repository(owner:"{owner}", name:"{name}"){{ name url description isFork '
                       f'stargazerCount forkCount primaryLanguage{{ name color }} parent{{ nameWithOwner }} }}')
    repos = gql(token, "query{ " + " ".join(aliases) + " }")
    return d, days, [repos[f"r{i}"] for i in range(len(REPO_CARDS))]


def streaks(days):
    today = datetime.now(SGT).date()
    current, d = 0, today if days.get(today, 0) else today - timedelta(days=1)
    while days.get(d, 0) > 0:
        current += 1
        d -= timedelta(days=1)
    longest = run = 0
    for day in sorted(days):
        run = run + 1 if days[day] > 0 else 0
        longest = max(longest, run)
    return current, longest, sum(days.values()), today


def build_live(user, days, repos):
    updated = datetime.now(SGT).strftime("%d %b %Y")

    # Stats
    own = [r for r in user["repositories"]["nodes"] if not r["isFork"]]
    stats = [("Commits, past year", user["contributionsCollection"]["totalCommitContributions"]),
             ("Pull requests", user["pullRequests"]["totalCount"]),
             ("Issues", user["issues"]["totalCount"]),
             ("Contributed to, past year", user["repositoriesContributedTo"]["totalCount"]),
             ("Public repositories", user["repositories"]["totalCount"]),
             ("Stars earned", sum(r["stargazerCount"] for r in own))]
    w, h = 340, 300
    body = eyebrow(X0, 50, "GitHub stats")
    for i, (label, val) in enumerate(stats):
        y = 94 + i * 32
        body += text(X0, y, label, 15, "ts") + text(w - X0, y, f"{val:,}", 15, "tp", 600, "mono", anchor="end")
    tile("stats", w, h, body, "GitHub stats. " + " ".join(f"{l}: {v:,}." for l, v in stats))

    # Streak
    current, longest, total, today = streaks(days)
    last = [days.get(today - timedelta(days=13 - i), 0) for i in range(14)]
    peak = max(last) or 1
    w, h = 320, 300
    num = f"{current:,}"
    body = (eyebrow(X0, 50, "Contribution streak")
            + text(X0, 116, num, 56, "ta", 700, ls=-1)
            + text(X0 + len(num) * 33 + 10, 116, "day" if current == 1 else "days", 18, "tt", 500)
            + text(X0, 142, "Current streak", 14, "tt"))
    sq, sg = 14, (w - 2 * X0 - 14 * 14) / 13
    for i, c in enumerate(last):
        lvl = 0 if c == 0 else min(4, 1 + int(3 * c / peak))
        body += (f'<rect x="{X0 + i*(sq+sg):.1f}" y="164" width="{sq}" height="{sq}" rx="3" '
                 f'fill="{T["heat"][lvl]}"/>')
    body += text(X0, 196, "LAST 14 DAYS", 11, "tt", 500, "mono", ls=1)
    for i, (label, val) in enumerate([("Longest streak", f"{longest:,} days"), ("Total contributions", f"{total:,}")]):
        x = X0 + i * 132
        body += text(x, 240, val, 20, "tp", 700) + text(x, 262, label, 13, "tt")
    tile("streak", w, h, body,
         f"Contribution streak: current {current} days, longest {longest} days, {total:,} total contributions. "
         f"Contributions over the last 14 days: {', '.join(map(str, last))}.")

    # Top languages (by code size across own, non-fork repos)
    sizes, colors = {}, {}
    for r in own:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            if n in HIDE_LANGS:
                continue
            sizes[n] = sizes.get(n, 0) + e["size"]
            colors[n] = e["node"]["color"] or T["text-tertiary"]
    total_b = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    w, h = 340, 300
    bw = w - 2 * X0
    defs = f'<clipPath id="bar"><rect x="{X0}" y="72" width="{bw}" height="10" rx="5"/></clipPath>'
    body = eyebrow(X0, 50, "Top languages") + f'<rect x="{X0}" y="72" width="{bw}" height="10" fill="{T["surface-chip"]}" rx="5"/>'
    bx, seg = X0, ""
    for n, s in top:
        sw = bw * s / total_b
        seg += f'<rect x="{bx:.1f}" y="72" width="{max(sw - 2, 1):.1f}" height="10" fill="{colors[n]}"/>'
        bx += sw
    body += f'<g clip-path="url(#bar)">{seg}</g>'
    for i, (n, s) in enumerate(top):
        y = 122 + i * 30
        body += (f'<circle cx="{X0+5}" cy="{y-5}" r="5" fill="{colors[n]}"/>' + text(X0 + 18, y, n, 15, "ts")
                 + text(w - X0, y, f"{100*s/total_b:.1f}%", 14, "tt", 500, "mono", anchor="end"))
    body += text(X0, 270, f"BY CODE SIZE · UPDATED {updated.upper()}", 11, "tt", 500, "mono", ls=0.5)
    tile("languages", w, h, body,
         "Top languages by code size: " + ", ".join(f"{n} {100*s/total_b:.1f}%" for n, s in top) + ".", defs)

    # Repo cards
    for i, ((full, context, desc_override), r) in enumerate(zip(REPO_CARDS, repos)):
        w, h = 500, 200
        desc = desc_override or r["description"] or "No description yet."
        meta = context + (f" · forked from {r['parent']['nameWithOwner']}" if r["isFork"] and r["parent"] else "")
        lines = wrap(desc, 52, 2)
        lang = r["primaryLanguage"] or {"name": "—", "color": T["text-tertiary"]}
        bx, by = X0, 166
        foot = (f'<circle cx="{bx+5}" cy="{by-5}" r="5" fill="{lang["color"] or T["text-tertiary"]}"/>'
                + text(bx + 16, by, lang["name"], 14, "tt"))
        sx = bx + 16 + len(lang["name"]) * 8 + 20
        star = " ".join(f"{sx+6.5+6.5*math.sin(k*math.pi/5)*(1 if k%2==0 else .45):.1f},"
                        f"{by-5.5-6.5*math.cos(k*math.pi/5)*(1 if k%2==0 else .45):.1f}" for k in range(10))
        foot += f'<polygon points="{star}" fill="none" stroke="{T["text-tertiary"]}" stroke-width="1.4" stroke-linejoin="round"/>'
        foot += text(sx + 18, by, r["stargazerCount"], 14, "tt", 500, "mono")
        fx = sx + 18 + len(str(r["stargazerCount"])) * 8.4 + 18
        foot += (f'<g fill="none" stroke="{T["text-tertiary"]}" stroke-width="1.4">'
                 f'<circle cx="{fx+2}" cy="{by-10}" r="2"/><circle cx="{fx+10}" cy="{by-10}" r="2"/><circle cx="{fx+6}" cy="{by+1}" r="2"/>'
                 f'<path d="M{fx+2} {by-8} v2 q0 2 4 2 q4 0 4 -2 v-2 M{fx+6} {by-4} v3"/></g>'
                 + text(fx + 16, by, r["forkCount"], 14, "tt", 500, "mono"))
        book = (f'<path d="M{X0} {X0+4} h10 a3 3 0 0 1 3 3 v12 a2 2 0 0 0 -2 -2 h-11 z M{X0+3} {X0+4} v13" '
                f'fill="none" stroke="{T["text-tertiary"]}" stroke-width="1.5" stroke-linejoin="round"/>')
        body = (book + text(X0 + 24, 54, r["name"], 18, "tp", 700) + link_arrow(w)
                + text(X0, 82, meta, 13, "tt")
                + "".join(text(X0, 112 + 22 * k, ln, 15, "ts") for k, ln in enumerate(lines))
                + foot)
        name = f"repo{i+1}"
        tile(name, w, h, body,
             f"Repository {r['name']}. {meta}. {desc} Language: {lang['name']}. "
             f"{r['stargazerCount']} stars, {r['forkCount']} forks.")
        LINKS[name] = r["url"]


# ---- README -----------------------------------------------------------------
LINKS = {
    "experience": "https://github.com/shira421/seekcamera-glass-detection",
    "riscv": "https://github.com/shira421/cg3207_labs",
    "zettelcli": "https://github.com/AY2526S1-CS2113-W13-1/tp",
    "fpga": "https://github.com/shira421/ee2026_b02_g10",
    "uwash": "https://github.com/shira421/uwash-dashboard",
    "opensuite": "https://github.com/lukeai-tan/claude-hackathon",
    "linkedin": "https://www.linkedin.com/in/ksheerabthi/",
    "email": "mailto:k.nathan@u.nus.edu",
}
GRID = [["hero", "experience"], ["riscv", "zettelcli", "fpga"], ["uwash", "brainhack", "opensuite"],
        ["education", "highlights"], ["stack"], ["stats", "streak", "languages"], ["repo1", "repo2"],
        ["repo3", "repo4"], ["linkedin", "email"]]

BADGE = "https://img.shields.io/badge/{}-{}-27272a?style=flat-square&labelColor=18181b"
BADGES = [("NUS", "Computer Engineering"), ("Year", "3"), ("Based in", "Singapore"),
          ("Focus", "Embedded · FPGA · Computer Vision")]


def badge_url(label, msg):
    q = lambda s: urllib.parse.quote(s.replace("-", "--").replace("_", "__"), safe="")
    return BADGE.format(q(label), q(msg))


def alt_of(name):
    with open(os.path.join(ASSETS, f"{name}.svg"), encoding="utf-8") as f:
        return f.read().split('<title id="t">')[1].split("</title>")[0]


def cell(name):
    w, _ = TILES[name]
    img = f'<img src="assets/{name}.svg" width="{w/10:g}%" align="top" alt="{alt_of(name)}">'
    return f'<a href="{LINKS[name]}">{img}</a>' if name in LINKS else img


def write_readme():
    rows = []
    for row in GRID:
        present = [n for n in row if n in TILES]
        if len(present) == len(row):  # never ship a half-filled row
            rows.append("".join(cell(n) for n in present))
    views = (f"https://komarev.com/ghpvc/?username={LOGIN}&label=Profile%20views"
             f"&color=047857&labelColor=18181b&style=flat-square")
    badges = "\n".join([f'<img src="{views}" alt="Profile views">']
                       + [f'<img src="{badge_url(l, m)}" alt="{escape(l)}: {escape(m)}">' for l, m in BADGES])
    grid = "<br>\n".join(rows)
    readme = f"""<!--
  Generated by scripts/build.py; edit that, not this file.
  Bento grid: each tile is an SVG in /assets. Keep every row on one line with no
  spaces between tags: the gaps live inside the SVGs.
-->
<p align="center">
{badges}
</p>

<p align="center">
{grid}
</p>

<details>
<summary>Read as plain text</summary>

### Ksheerabthi Nathan (Canary)
Year 3 Computer Engineering at the National University of Singapore. I work on embedded software, FPGA design and real-time computer vision.

**Experience**
- **PROX SG**, Embedded Software Engineer Intern (Dec 2025 – Jan 2026). Built a real-time thermal imaging system that detects and ranges clear glass for robots, with a C++ vision pipeline on embedded Linux. [Repo](https://github.com/shira421/seekcamera-glass-detection)

**Projects**
- **RISC-V CPU** (CG3207, now). RISC-V processor in Verilog on a Nexys 4 FPGA, with a multi-cycle radix-4 Booth multiply/divide unit. [Repo](https://github.com/shira421/cg3207_labs)
- **ZettelCLI** (CS2113). Java CLI for Zettelkasten notes; Gradle, JUnit, Checkstyle and CI on GitHub Actions. [Repo](https://github.com/AY2526S1-CS2113-W13-1/tp)
- **FPGA Calculator** (EE2026). Arithmetic and graphing calculator on a Basys3 driving dual 96×64 OLEDs over custom SPI. [Repo](https://github.com/shira421/ee2026_b02_g10)
- **UWash** (NUS Student Life Hack, Top 8). ESP32 vibration sensor and web dashboard for NUS laundry rooms. [Repo](https://github.com/shira421/uwash-dashboard)
- **OpenSuite** (Claude hackathon, team). Free, local-first desktop app replacing paid PDF and slide tools: in-place PDF editing, redaction and OCR, a slide canvas that exports editable `.pptx`, and an AI design helper on the Claude API. [Repo](https://github.com/lukeai-tan/claude-hackathon)
- **DSTA BrainHack 2024** (Finalist). Sustainability-focused mobile app built in 48 hours with React Native, Django and AWS.

**Education**: B.Eng (Hons) Computer Engineering, NUS, 2024 – 2028. GPA 4.31/5.0. Embedded and Large-Scale Computing, minor in Quantitative Finance. TA for EG1311.

**Highlights**: Represented Singapore at RoboCup Worldwide 2021 · Best Engineering & Distinction, RoboCup Singapore Open 2021 · Champions, YDSP Data Analytics 2018.

**Contact**: [LinkedIn](https://www.linkedin.com/in/ksheerabthi/) · [k.nathan@u.nus.edu](mailto:k.nathan@u.nus.edu)

</details>
"""
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(readme)


def main():
    build_static()
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    ok = False
    if token:
        try:
            build_live(*fetch(token))
            ok = True
        except Exception as e:  # keep yesterday's tiles rather than ship broken ones
            print(f"Live tiles skipped: {e}", file=sys.stderr)
    else:
        print("No GH_STATS_TOKEN or GITHUB_TOKEN set: live tiles skipped.", file=sys.stderr)
    if not ok:
        for name, (w, h) in {"stats": (340, 300), "streak": (320, 300), "languages": (340, 300),
                             "repo1": (500, 200), "repo2": (500, 200), "repo3": (500, 200), "repo4": (500, 200)}.items():
            register_existing(name, w, h)
        for i, (full, _, _) in enumerate(REPO_CARDS):
            LINKS.setdefault(f"repo{i+1}", f"https://github.com/{full}")
    write_readme()
    print("Built:", ", ".join(sorted(TILES)))
    return 0 if ok or not token else 1


if __name__ == "__main__":
    sys.exit(main())
