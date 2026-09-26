#!/usr/bin/env python3
"""
Regenerates assets/git-stats.svg, assets/contrib-heatmap.svg and
assets/top-langs.svg from real, live GitHub data:

  - Contribution totals + streaks: scraped from the public
    https://github.com/users/<user>/contributions page (no auth needed).
  - Language breakdown: GitHub REST API, using GITHUB_TOKEN so it
    runs well within Actions' rate limits.

Run by .github/workflows/update-stats.yml on a daily schedule.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime

USERNAME = os.environ.get("GH_USERNAME", "AmitFrontEnd")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")

MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------- #
# 1. Contribution calendar (public page, no auth required)
# ---------------------------------------------------------------- #

def fetch_contributions():
    html = http_get(
        f"https://github.com/users/{USERNAME}/contributions",
        headers={"User-Agent": "Mozilla/5.0 (stats-bot)"},
    )

    ids_dates = re.findall(
        r'<td[^>]*data-date="(\d{4}-\d{2}-\d{2})"[^>]*id="(contribution-day-component-\d+-\d+)"',
        html,
    )
    tooltips = dict(
        re.findall(
            r'for="(contribution-day-component-\d+-\d+)"[^>]*>\s*([\d]+|No)\s+contributions?',
            html,
        )
    )

    data = []
    for d, cid in ids_dates:
        raw = tooltips.get(cid, "0")
        cnt = 0 if raw == "No" else int(raw)
        data.append((datetime.strptime(d, "%Y-%m-%d").date(), cnt))
    data.sort()
    return data


def level_of(count, nonzero_sorted):
    if count == 0:
        return 0
    if not nonzero_sorted:
        return 1
    n = len(nonzero_sorted)
    q1 = nonzero_sorted[int(n * 0.25)] if n >= 4 else nonzero_sorted[0]
    q2 = nonzero_sorted[int(n * 0.5)] if n >= 4 else nonzero_sorted[0]
    q3 = nonzero_sorted[int(n * 0.75)] if n >= 4 else nonzero_sorted[-1]
    if count <= q1:
        return 1
    if count <= q2:
        return 2
    if count <= q3:
        return 3
    return 4


def compute_stats(data):
    total = sum(c for _, c in data)

    longest = cur = 0
    run_start = None
    longest_range = (None, None)
    for d, c in data:
        if c > 0:
            if cur == 0:
                run_start = d
            cur += 1
            if cur > longest:
                longest = cur
                longest_range = (run_start, d)
        else:
            cur = 0

    cur_streak = 0
    idx = len(data) - 1
    cur_end = data[-1][0]
    while idx >= 0 and data[idx][1] > 0:
        cur_streak += 1
        idx -= 1
    cur_start = data[idx + 1][0] if cur_streak > 0 else None

    return {
        "total": total,
        "current_streak": cur_streak,
        "current_range": (cur_start, cur_end) if cur_streak else None,
        "longest_streak": longest,
        "longest_range": longest_range,
    }


def build_grid(data):
    nonzero = sorted(c for _, c in data if c > 0)

    def sun_index(d):
        return (d.weekday() + 1) % 7

    grid, week_idx, prev_date = [], 0, None
    for d, c in data:
        si = sun_index(d)
        if prev_date is not None and si == 0 and d != data[0][0]:
            week_idx += 1
        grid.append(
            {"w": week_idx, "d": si, "date": str(d), "count": c, "level": level_of(c, nonzero)}
        )
        prev_date = d
    return grid


# ---------------------------------------------------------------- #
# 2. Language breakdown (REST API, authenticated)
# ---------------------------------------------------------------- #

def fetch_top_languages():
    headers = {"User-Agent": "stats-bot", "Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    repos_json = http_get(
        f"https://api.github.com/users/{USERNAME}/repos?per_page=100&type=owner",
        headers=headers,
    )
    repos = json.loads(repos_json)
    if isinstance(repos, dict):
        # API error (rate limit etc.) - signal caller to keep existing file
        raise RuntimeError(repos.get("message", "unknown API error"))

    totals = {}
    for r in repos:
        if r.get("fork"):
            continue
        try:
            langs_json = http_get(r["languages_url"], headers=headers)
            langs = json.loads(langs_json)
        except Exception:
            continue
        for lang, bytes_ in langs.items():
            totals[lang] = totals.get(lang, 0) + bytes_

    grand_total = sum(totals.values())
    if grand_total == 0:
        return []

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[:3]
    other = sum(v for _, v in ranked[3:])

    result = [(name, round(v / grand_total * 100)) for name, v in top]
    if other > 0:
        result.append(("Other", round(other / grand_total * 100)))
    return result


# ---------------------------------------------------------------- #
# 3. SVG renderers (terminal theme, matches hero-terminal.svg)
# ---------------------------------------------------------------- #

def fmt_range(r):
    if not r or not r[0]:
        return "—"
    a, b = r
    return f"{a.strftime('%b %d')} – {b.strftime('%b %d')}"


def render_git_stats(stats):
    total = stats["total"]
    cur = stats["current_streak"]
    longest = stats["longest_streak"]
    cur_range = fmt_range(stats["current_range"])
    longest_range = fmt_range(stats["longest_range"])

    return f'''<svg width="700" height="196" viewBox="0 0 700 196" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Git stats: {total} total contributions in the last 12 months, current streak {cur} days {cur_range}, longest streak {longest} days {longest_range}">
  <defs><clipPath id="rd"><rect width="700" height="196" rx="14"/></clipPath></defs>
  <g clip-path="url(#rd)">
    <rect width="700" height="196" fill="#1e1e1e"/>
    <rect x="0" y="0" width="700" height="1" fill="#000"/>
  </g>
  <rect x="0.5" y="0.5" width="699" height="195" rx="13.5" fill="none" stroke="#333844"/>
  <g font-family="{MONO}">
    <text x="24" y="34" font-size="14"><tspan fill="#89d185">&#10148;</tspan><tspan fill="#61AFEF">  ~ </tspan><tspan fill="#d4d4d4">git stats --global</tspan></text>
    <line x1="233" y1="56" x2="233" y2="172" stroke="#333844" stroke-width="1"/>
    <line x1="466" y1="56" x2="466" y2="172" stroke="#333844" stroke-width="1"/>
    <g text-anchor="middle">
      <text x="116" y="112" font-size="42" font-weight="700" fill="#79c0ff">{total}</text>
      <text x="116" y="138" font-size="11" letter-spacing="1" fill="#9da5b4">TOTAL CONTRIBUTIONS</text>
      <text x="116" y="158" font-size="11" fill="#6a737d">last 12 months</text>
    </g>
    <g text-anchor="middle">
      <text x="349" y="112" font-size="42" font-weight="700" fill="#f0883e">{cur}</text>
      <text x="392" y="98" font-size="18" fill="#f0883e">&#128293;</text>
      <text x="349" y="138" font-size="11" letter-spacing="1" fill="#9da5b4">CURRENT STREAK</text>
      <text x="349" y="158" font-size="11" fill="#6a737d">{cur_range}</text>
    </g>
    <g text-anchor="middle">
      <text x="583" y="112" font-size="42" font-weight="700" fill="#7ee787">{longest}</text>
      <text x="583" y="138" font-size="11" letter-spacing="1" fill="#9da5b4">LONGEST STREAK</text>
      <text x="583" y="158" font-size="11" fill="#6a737d">{longest_range}</text>
    </g>
  </g>
</svg>
'''


def render_heatmap(grid):
    weeks = max(g["w"] for g in grid) + 1
    cell, gap = 11, 3
    step = cell + gap
    left_pad, top_pad = 30, 46
    width = left_pad + weeks * step + 16
    height = top_pad + 7 * step + 20

    level_colors = {0: "#2d2d2d", 1: "#1f3a5f", 2: "#2a5d8f", 3: "#3fa7d6", 4: "#61DAFB"}
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Contribution heatmap, last 12 months">',
        f'<defs><clipPath id="rd"><rect width="{width}" height="{height}" rx="14"/></clipPath></defs>',
        f'<g clip-path="url(#rd)"><rect width="{width}" height="{height}" fill="#1e1e1e"/></g>',
        f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="13.5" fill="none" stroke="#333844"/>',
        f'<text x="24" y="28" font-family="{MONO}" font-size="14"><tspan fill="#89d185">&#10148;</tspan><tspan fill="#61AFEF">  ~ </tspan><tspan fill="#d4d4d4">git log --graph --since="1 year ago"</tspan></text>',
    ]

    week_first_date = {}
    for g in grid:
        week_first_date.setdefault(g["w"], g["date"])

    last_month = None
    for w in range(weeks):
        if w not in week_first_date:
            continue
        dt = date.fromisoformat(week_first_date[w])
        if dt.month != last_month:
            x = left_pad + w * step
            parts.append(
                f'<text x="{x}" y="{top_pad-8}" font-family="{MONO}" font-size="10" fill="#6a737d">{month_names[dt.month-1]}</text>'
            )
            last_month = dt.month

    for g in grid:
        x = left_pad + g["w"] * step
        y = top_pad + g["d"] * step
        color = level_colors[g["level"]]
        delay = 0.1 + (g["w"] * 7 + g["d"]) * 0.0022
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{color}" opacity="0">'
            f'<animate attributeName="opacity" from="0" to="1" begin="{delay:.3f}s" dur="0.25s" fill="freeze"/></rect>'
        )

    ly = height - 14
    parts.append(f'<text x="{left_pad}" y="{ly+5}" font-family="{MONO}" font-size="10" fill="#6a737d">less</text>')
    lx = left_pad + 34
    for lvl in range(5):
        parts.append(f'<rect x="{lx}" y="{ly-2}" width="10" height="10" rx="2" fill="{level_colors[lvl]}"/>')
        lx += 14
    parts.append(f'<text x="{lx+4}" y="{ly+5}" font-family="{MONO}" font-size="10" fill="#6a737d">more</text>')
    parts.append("</svg>\n")
    return "\n".join(parts)


LANG_GRADIENTS = [
    ("l1", "#F7DF1E", "#e8c400"),
    ("l2", "#61DAFB", "#2f9fd0"),
    ("l3", "#F472B6", "#e0578f"),
    ("l4", "#9da5b4", "#6a737d"),
]
LANG_TEXT_COLORS = ["#dcdcaa", "#79c0ff", "#f0a6ca", "#c9d1d9"]


def render_top_langs(langs):
    if not langs:
        return None  # caller keeps existing file

    rows = []
    max_bar = 500
    top_val = max(v for _, v in langs) or 1
    y0 = 70
    for i, (name, pct) in enumerate(langs[:4]):
        gid, c1, c2 = LANG_GRADIENTS[i]
        bar_w = round(max_bar * (pct / 100) / (max(l[1] for l in langs) / 100))
        bar_w = min(bar_w, max_bar)
        label_y = y0 + i * 46
        bar_y = label_y + 10
        rows.append(
            f'<text x="24" y="{label_y}" font-size="13" fill="#9da5b4">{name}</text>\n'
            f'    <rect x="24" y="{bar_y}" width="{max_bar}" height="10" rx="5" fill="#2d2d2d"/>\n'
            f'    <rect x="24" y="{bar_y}" width="{bar_w}" height="10" rx="5" fill="url(#{gid})"/>\n'
            f'    <text x="650" y="{bar_y+9}" font-size="13" fill="{LANG_TEXT_COLORS[i%4]}" text-anchor="end">{pct}%</text>'
        )

    height = y0 + len(langs[:4]) * 46 + 40
    grad_defs = "\n    ".join(
        f'<linearGradient id="{gid}" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>'
        for gid, c1, c2 in LANG_GRADIENTS
    )

    return f'''<svg width="700" height="{height}" viewBox="0 0 700 {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Top languages by bytes across public repositories">
  <defs>
    {grad_defs}
    <clipPath id="rd"><rect width="700" height="{height}" rx="14"/></clipPath>
  </defs>
  <g clip-path="url(#rd)">
    <rect width="700" height="{height}" fill="#1e1e1e"/>
    <rect x="0" y="0" width="700" height="1" fill="#000"/>
  </g>
  <rect x="0.5" y="0.5" width="699" height="{height-1}" rx="13.5" fill="none" stroke="#333844"/>
  <g font-family="{MONO}">
    <text x="24" y="34" font-size="14"><tspan fill="#89d185">&#10148;</tspan><tspan fill="#61AFEF">  ~ </tspan><tspan fill="#d4d4d4">top --languages</tspan></text>
    {chr(10).join(rows)}
    <text x="24" y="{height-14}" font-size="12" fill="#6a737d"># auto-updated daily via GitHub Actions</text>
  </g>
</svg>
'''


# ---------------------------------------------------------------- #
# main
# ---------------------------------------------------------------- #

def write(path, content):
    with open(path, "w") as f:
        f.write(content)
    print("wrote", path)


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)

    try:
        data = fetch_contributions()
        stats = compute_stats(data)
        grid = build_grid(data)
        write(os.path.join(ASSETS_DIR, "git-stats.svg"), render_git_stats(stats))
        write(os.path.join(ASSETS_DIR, "contrib-heatmap.svg"), render_heatmap(grid))
    except Exception as e:
        print("contribution scrape failed, keeping existing files:", e, file=sys.stderr)

    try:
        langs = fetch_top_languages()
        svg = render_top_langs(langs)
        if svg:
            write(os.path.join(ASSETS_DIR, "top-langs.svg"), svg)
        else:
            print("no language data returned, keeping existing file")
    except Exception as e:
        print("language fetch failed, keeping existing file:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
