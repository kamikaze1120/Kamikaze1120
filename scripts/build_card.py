"""Regenerate dark_mode.svg (ASCII profile card) from live GitHub data.

Runs daily in .github/workflows/profile-card.yml. Uses PROFILE_TOKEN when set
(a PAT with read:user + repo scopes, so private work is counted), otherwise
falls back to the workflow's GITHUB_TOKEN (public data + any private
contribution counts you've chosen to show on your profile).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import urllib.request
from xml.sax.saxutils import escape

LOGIN = os.environ.get("PROFILE_LOGIN", "kamikaze1120")
ROLE = "AI Engineer // Builder"
ROOT = pathlib.Path(__file__).resolve().parent.parent
ART = ROOT / "assets" / "art.fragment"
OUT = ROOT / "dark_mode.svg"

FONT = "'Consolas', 'Menlo', 'DejaVu Sans Mono', monospace"
C_RULE, C_HEAD, C_KEY, C_DOT, C_TEXT, C_NUM, C_GREEN = (
    "#3d444d", "#58a6ff", "#ffa657", "#484f58", "#c9d1d9", "#79c0ff", "#39d353")
LINE_W = 58          # characters per panel line
HALF_W = 27          # characters per half of a two-column line
X, Y0, STEP = 636, 141, 20


def gql(query: str, token: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-card"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch(token: str) -> dict:
    base = gql(f"""{{ user(login: "{LOGIN}") {{
        createdAt location
        followers {{ totalCount }}
        pullRequests {{ totalCount }}
        issues {{ totalCount }}
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100,
                     orderBy: {{field: PUSHED_AT, direction: DESC}}) {{
          totalCount
          nodes {{ name isPrivate stargazerCount forkCount
                  languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
                    edges {{ size node {{ name }} }} }} }} }}
        contributionsCollection {{
          restrictedContributionsCount
          contributionCalendar {{ totalContributions
            weeks {{ contributionDays {{ date contributionCount }} }} }} }}
    }} }}""", token)["user"]

    created = dt.datetime.fromisoformat(base["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    years, parts = [], []
    for y in range(created.year, now.year + 1):
        years.append(y)
        parts.append(f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", '
                     f'to: "{y}-12-31T23:59:59Z") {{ totalCommitContributions '
                     f'contributionCalendar {{ totalContributions }} }}')
    per_year = gql(f'{{ user(login: "{LOGIN}") {{ {" ".join(parts)} }} }}', token)["user"]
    base["allTimeCommits"] = sum(per_year[f"y{y}"]["totalCommitContributions"] for y in years)
    base["allTimeContrib"] = sum(per_year[f"y{y}"]["contributionCalendar"]["totalContributions"] for y in years)
    base["created"], base["now"] = created, now
    return base


def uptime(start: dt.datetime, now: dt.datetime) -> str:
    y, m, d = now.year - start.year, now.month - start.month, now.day - start.day
    if d < 0:
        m -= 1
        d += (now.replace(day=1) - dt.timedelta(days=1)).day
    if m < 0:
        y, m = y - 1, m + 12
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{plural(y, 'year')}, {plural(m, 'month')}, {plural(d, 'day')}"


def streaks(days: list[dict], today: dt.date) -> tuple[int, int, int]:
    longest = run = active = 0
    for day in days:
        if day["contributionCount"] > 0:
            run += 1
            active += 1
            longest = max(longest, run)
        else:
            run = 0
    current = 0
    for day in reversed(days):
        date = dt.date.fromisoformat(day["date"])
        if date > today:
            continue
        if day["contributionCount"] > 0:
            current += 1
        elif date == today:
            continue  # today isn't over yet: don't break the streak
        else:
            break
    return current, longest, active


def sparkline(weeks: list[dict], width: int) -> str:
    totals = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks][-width:]
    peak = max(totals) or 1
    bars = " ▁▂▃▄▅▆▇█"
    return "".join(bars[0 if t == 0 else max(1, round(t / peak * 8))] for t in totals)


# ---------- rendering ----------
def span(color: str, text: str) -> str:
    return f'<tspan fill="{color}">{escape(text)}</tspan>'


def field(key: str, value: str, width: int, color: str) -> str:
    k = f". {key}: "
    dots = max(2, width - len(k) - len(value) - 1)
    return span(C_KEY, k) + span(C_DOT, "." * dots) + span(color, f" {value}")


def header(title: str) -> str:
    return span(C_RULE, "─") + span(C_HEAD, f" {title} ") + span(C_RULE, "─" * (LINE_W - len(title) - 3))


def text_line(y: float, inner: str) -> str:
    return (f'  <text x="{X}" y="{y:g}" font-family="{FONT}" xml:space="preserve" '
            f'font-size="16">{inner}</text>')


def build(data: dict) -> str:
    repos = data["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    forks = sum(r["forkCount"] for r in repos)
    lang_bytes: dict[str, int] = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            lang_bytes[e["node"]["name"]] = lang_bytes.get(e["node"]["name"], 0) + e["size"]
    total_bytes = sum(lang_bytes.values()) or 1
    top_langs = sorted(lang_bytes.items(), key=lambda kv: -kv[1])[:3]
    langs = ", ".join(f"{n} {round(b * 100 / total_bytes)}%" for n, b in top_langs)

    cal = data["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    _current, longest, active = streaks(days, data["now"].date())
    public = [r for r in repos if not r["isPrivate"] and r["name"].lower() != LOGIN.lower()]
    starred = max(public, key=lambda r: r["stargazerCount"], default=None)
    if starred and starred["stargazerCount"] > 0:
        spotlight_key, spotlight = "Top repo", f'{starred["name"]} ({starred["stargazerCount"]} ★)'
    else:
        spotlight_key, spotlight = "Shipping", public[0]["name"] if public else "—"

    n = lambda v: f"{v:,}"
    pair = lambda a, b: a + span(C_RULE, " | ") + b
    rows: list[str | None] = [
        header(f"{LOGIN}@github"),
        field("Uptime", uptime(data["created"], data["now"]), LINE_W, C_TEXT),
        field("Role", ROLE, LINE_W, C_TEXT),
        field("Location", data["location"] or "Earth", LINE_W, C_TEXT),
        field("Languages", langs, LINE_W, C_TEXT),
        None,
        header("GitHub Stats"),
        pair(field("Repos", n(data["repositories"]["totalCount"]), HALF_W, C_NUM),
             field("Stars", n(stars), HALF_W + 1, C_NUM)),
        pair(field("Forks", n(forks), HALF_W, C_NUM),
             field("Followers", n(data["followers"]["totalCount"]), HALF_W + 1, C_NUM)),
        pair(field("Commits", n(data["allTimeCommits"]), HALF_W, C_NUM),
             field("All-time", n(data["allTimeContrib"]), HALF_W + 1, C_NUM)),
        pair(field("PRs", n(data["pullRequests"]["totalCount"]), HALF_W, C_NUM),
             field("Issues", n(data["issues"]["totalCount"]), HALF_W + 1, C_NUM)),
        field(spotlight_key, spotlight, LINE_W, C_TEXT),
        None,
        header("Last 12 Months"),
        pair(field("Contributions", n(cal["totalContributions"]), HALF_W, C_NUM),
             field("Active days", n(active), HALF_W + 1, C_NUM)),
        pair(field("Peak day", n(max((d["contributionCount"] for d in days), default=0)), HALF_W, C_NUM),
             field("Best streak", f"{longest}d", HALF_W + 1, C_NUM)),
        span(C_GREEN, sparkline(cal["weeks"], 52)),
        span(C_DOT, f"  synced {data['now']:%Y-%m-%d} · weekly activity, oldest → newest"),
    ]
    lines, y = [], Y0
    for row in rows:
        if row is not None:
            lines.append(text_line(y, row))
        y += STEP

    svg_head = ('<svg xmlns="http://www.w3.org/2000/svg" width="1221" height="632" '
                'viewBox="0 0 1221 632" role="img" '
                f'aria-label="ASCII GitHub profile card for {LOGIN}">\n'
                '  <rect x="0.5" y="0.5" width="1220" height="631" rx="8" '
                'fill="#0d1117" stroke="#30363d"/>\n')
    return svg_head + ART.read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join(lines) + "\n</svg>\n"


if __name__ == "__main__":
    token = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set PROFILE_TOKEN or GITHUB_TOKEN")
    OUT.write_text(build(fetch(token)), encoding="utf-8")
    print(f"wrote {OUT}")
