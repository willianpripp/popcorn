# Pure logic for the Discover tab: no database, no network, no framework, so
# the tests import it directly. The poller fetches and stores; main.py renders.

import datetime
import re
import urllib.parse

# Services shown in "Popular now", in tab order, with their TMDB watch
# provider ids (US region). Netflix is listed for its tab and its id, but its
# rows come from Netflix's own Top 10 file when that is reachable.
SERVICES = [
    ("Netflix", 8), ("Prime Video", 9), ("Disney+", 337), ("HBO Max", 1899),
    ("Hulu", 15), ("Paramount+", 2303), ("Apple TV", 350), ("Peacock", 386),
    ("Crunchyroll", 283),
]
SERVICE_NAMES = [s for s, _ in SERVICES]
DEFAULT_SERVICE = "Netflix"

NETFLIX_TOP10_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
FLIXPATROL_NETFLIX = "https://flixpatrol.com/top10/netflix/united-states/"
FLIXPATROL_OTHER = "https://flixpatrol.com/top10/streaming/united-states/"

# TMDB provider name -> what the cards say. Anything not listed is shown as
# TMDB names it, except the ones in _DROP (live-TV bundles and channel apps
# that say nothing about where to watch).
_SHORT = {
    "amazon prime video": "Prime Video",
    "amazon prime video with ads": "Prime Video",
    "disney plus": "Disney+",
    "paramount plus premium": "Paramount+",
    "paramount plus essential": "Paramount+",
    "paramount plus": "Paramount+",
    "peacock premium": "Peacock",
    "peacock premium plus": "Peacock",
    "netflix standard with ads": "Netflix",
    "netflix basic with ads": "Netflix",
    "hbo max": "HBO Max",
}
_DROP = {"fubotv", "philo", "youtube tv", "fxnow"}
_ADS = re.compile(r"\s+with ads$", re.I)


def shorten_providers(names, limit=2):
    """Up to `limit` distinct, shortened US flatrate provider names."""
    out = []
    for n in names or []:
        key = (n or "").strip().lower()
        if not key or key in _DROP:
            continue
        s = _SHORT.get(key) or _SHORT.get(_ADS.sub("", key)) or _ADS.sub("", n.strip())
        if s not in out:
            out.append(s)
    return out[:limit]


# --- Netflix Top 10 -------------------------------------------------------------


def season_number(season_title):
    """3 for "From: Season 3" / "Season 3", None for "N/A", "" or an episode
    date such as "Hospital Playlist: 2026-11-12"."""
    last = (season_title or "").split(": ")[-1].strip()
    m = re.fullmatch(r"Season (\d+)", last)
    return int(m.group(1)) if m else None


def seasons_label(seasons):
    """"S1" / "S1–S3" when contiguous / "S1, S3" when not / "" for none."""
    ss = sorted(set(seasons))
    if not ss:
        return ""
    if len(ss) == 1:
        return f"S{ss[0]}"
    if ss == list(range(ss[0], ss[-1] + 1)):
        return f"S{ss[0]}–S{ss[-1]}"
    return ", ".join(f"S{s}" for s in ss)


def parse_netflix_tsv(lines, country="US"):
    """Stream-parse Netflix's all-weeks-countries file (an iterable of text
    lines; the file is ~33 MB, so nothing else is ever held in memory).
    Keeps `country` rows only, then the latest week. Returns
    (week, films, shows): films ranked as published; shows merged per title
    (Netflix ranks every season as its own row) at their best rank and
    renumbered 1..n, each with its charted seasons in `sub`."""
    header = None
    rows = []
    for line in lines:
        cols = line.rstrip("\r\n").split("\t")
        if header is None:
            header = {name: i for i, name in enumerate(cols)}
            need = ("country_iso2", "week", "category", "weekly_rank", "show_title")
            if not all(k in header for k in need):
                raise ValueError("unexpected Netflix Top 10 header")
            continue
        if len(cols) < len(header) - 1 or cols[header["country_iso2"]] != country:
            continue
        rows.append(cols)
    if not rows:
        raise ValueError("no rows for " + country)
    ix = header
    week = max(r[ix["week"]] for r in rows)
    films, shows = [], {}
    for r in sorted((r for r in rows if r[ix["week"]] == week),
                    key=lambda r: int(r[ix["weekly_rank"]])):
        rank = int(r[ix["weekly_rank"]])
        title = r[ix["show_title"]].strip()
        if r[ix["category"]].lower().startswith("film"):
            films.append({"name": title, "rank": rank})
            continue
        d = shows.setdefault(title, {"name": title, "rank": rank, "seasons": []})
        sn = season_number(r[ix["season_title"]] if "season_title" in ix and len(r) > ix["season_title"] else "")
        if sn is not None:
            d["seasons"].append(sn)
    out = []
    for i, d in enumerate(shows.values(), 1):  # insertion order = best rank first
        out.append({"name": d["name"], "rank": i, "sub": seasons_label(d["seasons"])})
    return week, films, out


def week_range(week):
    """Netflix's `week` is the Sunday a Monday-to-Sunday week ends on.
    "2026-11-22" -> "Nov 16 – Nov 22" (the year is added when it is not the
    current one's concern: Netflix weeks are always recent)."""
    end = datetime.date.fromisoformat(week)
    start = end - datetime.timedelta(days=6)
    f = lambda d: d.strftime("%b ") + str(d.day)
    return f"{f(start)} – {f(end)}"


# --- links ----------------------------------------------------------------------


def safe_back(back, base_path="/discover"):
    """A redirect target from a form field: only a relative path under
    /discover is honored (optionally with a query). Anything else, including
    other paths, absolute URLs, protocol-relative `//host`, backslashes and
    control characters, gives "" (the caller falls back to its default)."""
    if not isinstance(back, str) or not back.startswith(base_path):
        return ""
    rest = back[len(base_path):]
    if rest and rest[0] not in "?/":
        return ""
    if any(c in back for c in "\\\r\n\t ") or any(ord(c) < 32 for c in back):
        return ""
    parsed = urllib.parse.urlsplit(back)
    if parsed.scheme or parsed.netloc:
        return ""
    return back


def flixpatrol_url(service):
    return FLIXPATROL_NETFLIX if service == "Netflix" else FLIXPATROL_OTHER
