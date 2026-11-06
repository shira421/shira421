"""Builds the card images used by the profile README at github.com/shira421.

    python scripts/build.py          # from the repo root

README.md is edited by hand; this script never touches it. It only redraws the
SVG cards in assets/ (stats, streak, top languages, repo1-repo6) from the
GitHub API, because the public github-readme-stats instance is down. Each card
sits on a 1000-unit-wide canvas with an 8-unit transparent gutter, so cards
placed edge to edge in the README leave an even 16-unit gap.

repoN.svg follows the order of REPO_CARDS below, whatever order the README
shows them in.

Cards need GH_STATS_TOKEN or GITHUB_TOKEN; without a token, or if the API
fails, the previous cards are left untouched.
"""
import json, math, os, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape

LOGIN = "shira421"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SGT = timezone(timedelta(hours=8))
os.makedirs(ASSETS, exist_ok=True)

# Repo cards: (repo, context line, description override or None for the GitHub one)
REPO_CARDS = [
    ("shira421/seekcamera-glass-detection", "Internship",
     "Detects and ranges clear glass from its reflected heat signature, using a Seek Thermal camera."),
    ("shira421/cg3207_labs", "CG3207 Computer Architecture",
     "A RISC-V processor in Verilog on a Nexys 4 FPGA."),
    ("shira421/ee2026_b02_g10", "EE2026 Digital Design",
     "Arithmetic and graphing calculator on a Basys3 FPGA."),
    ("shira421/tp", "CS2113 SWE & OOP",
     "ZettelCLI: a Java command-line app for linked, atomic notes in the Zettelkasten method."),
    ("shira421/open-suite", "Hackathon",
     "OpenSuite: a free, local-first desktop app that replaces paid PDF and slide tools."),
    ("shira421/cg2111_2425", "CG2111A EPP2",
     "Alex, a teleoperated robot that maps unknown terrain and finds casualties by colour."),
]
# Vendored/generated code that would otherwise swamp the language chart.
HIDE_LANGS = {"HTML", "CSS", "Tcl", "VHDL", "CMake", "Dockerfile", "Batchfile", "Shell",
              "Procfile", "TeX", "PowerShell", "Makefile"}

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


# ---- Entry point ----------------------------------------------------------------
LINKS = {}


def main():
    token = os.environ.get("GH_STATS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("No GH_STATS_TOKEN or GITHUB_TOKEN set: cards left unchanged.", file=sys.stderr)
        return 0
    try:
        build_live(*fetch(token))
    except Exception as e:  # keep the previous cards rather than ship broken ones
        print(f"Cards left unchanged: {e}", file=sys.stderr)
        return 1
    print("Built:", ", ".join(sorted(TILES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
