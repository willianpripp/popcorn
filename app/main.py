# Popcorn: what we want to watch, what we watched, and the recap.
#
# Decided with Willian 2026-08-15 (the sketches artifact + homelab
# OBJECTIVES): a Jellyfin request queue and a watch diary in one app.
#   - adding anything goes through TMDB search: poster, year and runtime come
#     free, and the runtime is what makes the recap's hours real
#   - requests know Jellyfin: "already there" on add, and when a requested
#     title lands in the library the requester gets a Telegram ping
#   - the diary is FULLY AUTOMATIC where it can be: Jellyfin finishes log
#     themselves, calendar events in the Cinema category flow in (poller.py);
#     delete an entry to undo, series are logged per season
#   - ratings are per person; monthly grouping; a yearly "wrapped" recap
#
# Same skeleton as groceries/calendar: FastAPI + psycopg + Jinja, the SHARED
# gate (same cookie and secret as the calendar: one login), subpath-aware via
# X-Forwarded-Prefix, PWA manifest, phone and desktop from the same templates.

import asyncio
import json
import os
import time as systime
import urllib.parse
import urllib.request
from datetime import date

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import gate
import poller

DSN = os.environ.get("POP_DSN", "postgresql://popcorn:popcorn@db:5432/popcorn")
TMDB_KEY = os.environ.get("POP_TMDB_KEY", "")
IMG = "https://image.tmdb.org/t/p/w342"

PLATFORMS = ["Jellyfin", "Cinema", "Netflix", "AppleTV", "Prime", "Disney+",
             "Hulu", "Peacock", "HBO Max", "Crunchyroll", "Other"]

# The household's actual subscriptions (Willian, 2026-08-15). The rule they
# encode: if a picked title streams on one of these, it goes on the watchlist
# with that service's name; if nowhere the family already pays for, it becomes
# a Jellyfin request. Matched by substring against TMDB's US flatrate
# provider names, lowercase.
MY_SERVICES = {
    "netflix": "Netflix",
    "peacock": "Peacock",
    "disney": "Disney+",
    "hulu": "Hulu",
    "apple tv": "Apple TV",
    "hbo max": "HBO Max",
    "max ": "HBO Max",
    "amazon prime": "Prime Video",
    "crunchyroll": "Crunchyroll",
}
PEOPLE = ["Willian", "Aline", "Both"]

# Diary filter chips (Willian, 2026-08-15). The semantics live here, in SQL,
# so the 400-row window is filled with rows that survive the filter and the
# month grouping downstream needs no special case. "Movies" excludes Cinema
# because a cinema night is its own chip, not a movie watched at home.
TYPE_FILTERS = {
    "movies": "w.activity = '' and t.kind = 'movie' and w.platform <> 'Cinema'",
    "series": "w.activity = '' and t.kind = 'series'",
    "cinema": "w.platform = 'Cinema'",
    "concerts": "w.activity = 'concert'",
    "sports": "w.activity = 'sports'",
    "trips": "w.activity in ('travel', 'camping', 'beach')",
}
TYPE_CHIPS = [("", "All"), ("movies", "Movies"), ("series", "Series"),
              ("cinema", "Cinema"), ("concerts", "Concerts"),
              ("sports", "Sports"), ("trips", "Trips")]

# The genre of a title is TMDB's list; the first one is the one that reads as
# "what kind of thing is this", so it is what the diary shows and filters by.
FIRST_GENRE = "btrim(split_part(t.genres, ',', 1))"

# Recap person filter. Willian and Aline both own the rows watched together,
# "Together" is only the shared ones.
WHO_FILTERS = {
    "willian": "w.who in ('Willian', 'Both')",
    "aline": "w.who in ('Aline', 'Both')",
    "together": "w.who = 'Both'",
}
WHO_CHIPS = [("", "Everyone", ""), ("willian", "Willian", "cw"),
             ("aline", "Aline", "ca"), ("together", "Together", "cb")]

SCHEMA = """
create table if not exists titles (
    id serial primary key,
    tmdb_id bigint unique,
    kind text not null default 'movie',      -- movie | series
    name text not null,
    year int,
    poster text not null default '',
    runtime_min int not null default 0,       -- per episode, for series
    genres text not null default '',
    created_at timestamptz not null default now()
);

create table if not exists requests (
    id serial primary key,
    title_id int not null references titles(id),
    -- null = the whole thing; a number = that season only ("I saw S1 and S2,
    -- bring me S3"), which also makes availability season-aware
    season int,
    requested_by text not null default '',
    requested_at timestamptz not null default now(),
    status text not null default 'open',      -- open | available | dismissed
    available_at timestamptz,
    -- poller-written progress for partial seasons, e.g. "3/10 eps"
    progress text not null default '',
    -- empty = a Jellyfin request; a service name = a watchlist entry for
    -- something already streamable ("Silo S3, Apple TV: just want to watch")
    watch_on text not null default ''
);
alter table requests add column if not exists watch_on text not null default '';
alter table requests add column if not exists season int;
alter table requests add column if not exists progress text not null default '';
alter table requests drop constraint if exists requests_title_id_key;
create unique index if not exists requests_title_season
    on requests (title_id, coalesce(season, 0));

create table if not exists watches (
    id serial primary key,
    title_id int not null references titles(id),
    season int,                                -- null for movies
    platform text not null default 'Other',
    watched_on date not null,
    who text not null default 'Both',
    rating_willian int,
    rating_aline int,
    note text not null default '',
    source text not null default 'manual',     -- manual | jellyfin | calendar
    source_key text unique,                    -- dedupe for the automatic feeds
    -- attended events from the calendar (concert/sports/travel/...): the
    -- category name, lowercase; empty for watched screen content
    activity text not null default '',
    -- length in days for attended events (a week in Pensacola counts as 7)
    days int not null default 1,
    created_at timestamptz not null default now()
);
alter table watches add column if not exists activity text not null default '';
alter table watches add column if not exists days int not null default 1;
-- "loved" is the option above five stars (Willian, 2026-08-15): a five-star
-- rating plus a heart, per person, so the recap can single those out.
alter table watches add column if not exists loved_willian boolean not null default false;
alter table watches add column if not exists loved_aline boolean not null default false;
create index if not exists watches_month on watches (watched_on);
"""

pool = ConnectionPool(DSN, min_size=1, max_size=4, open=False)
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def q(sql, params=()):
    with pool.connection() as conn:
        conn.row_factory = dict_row
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def q1(sql, params=()):
    rows = q(sql, params)
    return rows[0] if rows else None


@app.on_event("startup")
async def startup():
    pool.open()
    with pool.connection() as conn:
        conn.execute(SCHEMA)
    # The automatic feeds: jellyfin finishes, request arrivals + pings, and
    # the calendar's Cinema events. Same in-process arrangement as the
    # calendar's reminder loop; app_health watches this process from outside.
    asyncio.create_task(poller.loop(q, q1))


def base_of(request: Request) -> str:
    return request.headers.get("x-forwarded-prefix", "").rstrip("/")


@app.middleware("http")
async def front_door(request: Request, call_next):
    path = request.url.path
    if (
        path in ("/login", "/health")
        or path in ("/static/style.css", "/static/manifest.webmanifest",
                    "/static/icon-192.png", "/static/icon-512.png")
        or gate.trusted(request)
        or gate.session_user(request)
    ):
        return await call_next(request)
    nxt = urllib.parse.quote(path + (f"?{request.url.query}" if request.url.query else ""))
    return RedirectResponse(f"{base_of(request)}/login?next={nxt}", status_code=303)


@app.get("/health")
def health():
    q("select 1")
    return {"status": "ok"}


# --- TMDB ------------------------------------------------------------------------


def tmdb(path, **params):
    """TMDB offers two credential shapes and it is easy to copy the wrong one:
    a short v3 api_key for the query string, and a long v4 JWT ("eyJ...") for
    an Authorization header. Accept both, same as the calendar's news.py,
    because the household .env carries the v4 one."""
    headers = {"accept": "application/json"}
    if TMDB_KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {TMDB_KEY}"
    else:
        params["api_key"] = TMDB_KEY
    url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


@app.get("/tmdb/providers")
def tmdb_providers(tmdb_id: int, kind: str = "movie"):
    """Where a title streams (US flatrate), split into services the household
    has and everything else. Drives the add flow's watchlist-vs-request call."""
    try:
        res = tmdb(f"/{'movie' if kind == 'movie' else 'tv'}/{tmdb_id}/watch/providers")
        flat = res.get("results", {}).get("US", {}).get("flatrate", [])
    except Exception:
        flat = []
    mine, others = [], []
    for p in flat:
        name = p.get("provider_name", "")
        hit = next((label for frag, label in MY_SERVICES.items()
                    if frag in name.lower()), None)
        if hit and hit not in mine:
            mine.append(hit)
        elif not hit and name not in others:
            others.append(name)
    return JSONResponse({"mine": mine, "others": others[:4]})


@app.get("/tmdb/search")
def tmdb_search(query: str = ""):
    """Search proxy for the add boxes. Movies and TV, ranked as TMDB ranks."""
    if not query.strip() or not TMDB_KEY:
        return JSONResponse([])
    res = tmdb("/search/multi", query=query.strip(), include_adult="false")
    out = []
    for r in res.get("results", [])[:8]:
        if r.get("media_type") not in ("movie", "tv"):
            continue
        out.append({
            "tmdb_id": r["id"],
            "kind": "movie" if r["media_type"] == "movie" else "series",
            "name": r.get("title") or r.get("name") or "?",
            "year": (r.get("release_date") or r.get("first_air_date") or "")[:4],
            "poster": (IMG + r["poster_path"]) if r.get("poster_path") else "",
        })
    return JSONResponse(out)


def upsert_title(tmdb_id: int, kind: str) -> dict:
    t = q1("select * from titles where tmdb_id = %s", (tmdb_id,))
    if t:
        return t
    detail = tmdb(f"/{'movie' if kind == 'movie' else 'tv'}/{tmdb_id}")
    name = detail.get("title") or detail.get("name") or "?"
    year = (detail.get("release_date") or detail.get("first_air_date") or "")[:4]
    runtime = detail.get("runtime") or (detail.get("episode_run_time") or [45])[0] or 0
    genres = ", ".join(g["name"] for g in detail.get("genres", [])[:3])
    poster = (IMG + detail["poster_path"]) if detail.get("poster_path") else ""
    return q1(
        "insert into titles (tmdb_id, kind, name, year, poster, runtime_min, genres)"
        " values (%s, %s, %s, %s, %s, %s, %s)"
        " on conflict (tmdb_id) do update set name = excluded.name returning *",
        (tmdb_id, kind, name, int(year) if year else None, poster, runtime, genres))


def who(request: Request) -> str:
    u = gate.session_user(request)
    if u:
        return u.capitalize()
    ip = gate.real_client(request)
    for pair in os.environ.get("POP_DEVICES", "").split(","):
        if "=" in pair:
            addr, _, name = pair.partition("=")
            if addr.strip() == str(ip):
                return name.strip().capitalize()
    return "Both"


# --- want to watch ----------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    rows = q("""
        select r.*, t.name, t.year, t.kind, t.poster, t.genres
        from requests r join titles t on t.id = r.title_id
        where r.status in ('open', 'available')
        order by r.status = 'available' desc, r.requested_at desc""")
    return templates.TemplateResponse(request, "index.html", {
        "request": request, "base": base_of(request), "rows": rows,
        "tab": "want", "who": who(request)})


@app.post("/request")
def add_request(request: Request, tmdb_id: int = Form(...), kind: str = Form("movie"),
                season: str = Form(""), watch_on: str = Form("")):
    t = upsert_title(tmdb_id, kind)
    sn = int(season) if season.strip().isdigit() else None
    # A dismissed title can be requested again: revive the row rather than
    # letting the unique constraint eat the request silently (found by
    # Willian with Constantine, 2026-08-15).
    q("""insert into requests (title_id, season, requested_by, watch_on)
         values (%s, %s, %s, %s)
         on conflict (title_id, coalesce(season, 0)) do update
         set status = 'open', requested_by = excluded.requested_by,
             requested_at = now(), available_at = null,
             watch_on = excluded.watch_on
         where requests.status = 'dismissed'""",
      (t["id"], sn, who(request), watch_on.strip()))
    # Jellyfin checks only make sense for jellyfin-bound requests.
    if not watch_on.strip():
        poller.check_one_request(q, q1, t, sn)
    return RedirectResponse(base_of(request) + "/", status_code=303)


@app.post("/request/{rid}/dismiss")
def dismiss(request: Request, rid: int):
    q("update requests set status = 'dismissed' where id = %s", (rid,))
    return RedirectResponse(base_of(request) + "/", status_code=303)


# --- the diary --------------------------------------------------------------------


def _parse_rating(v: str):
    """The rate selects carry one option above five stars, "★★★★★ ❤"
    (Willian, 2026-08-15). It travels as the string "5love" so the plain
    numeric options keep posting exactly what they posted before."""
    v = (v or "").strip()
    loved = v.endswith("love")
    n = v[:-4] if loved else v
    return (int(n) if n.isdigit() else None), loved


def _diary_qs(back: str) -> str:
    """Rating or deleting from a filtered diary must come back to the same
    filters, so the row forms carry the query string. Only the two known keys
    are echoed into the redirect, never whatever else was in the URL."""
    parsed = urllib.parse.parse_qs(back or "")
    keep = {k: parsed[k][0] for k in ("type", "genre") if parsed.get(k)}
    return ("?" + urllib.parse.urlencode(keep)) if keep else ""


@app.get("/watched", response_class=HTMLResponse)
def watched(request: Request, kind_f: str = Query("", alias="type"),
            genre_f: str = Query("", alias="genre")):
    kind_f = kind_f.strip().lower()
    genre_f = genre_f.strip()
    conds, params = [], []
    if kind_f in TYPE_FILTERS:
        conds.append(TYPE_FILTERS[kind_f])
    else:
        kind_f = ""
    if genre_f:
        # A genre only exists for screen content, so filtering by one is also
        # what hides the attended events.
        conds.append(f"w.activity = '' and {FIRST_GENRE} = %s")
        params.append(genre_f)
    sql = ("select w.*, t.name, t.year, t.kind, t.poster, t.genres"
           " from watches w join titles t on t.id = w.title_id")
    if conds:
        sql += " where " + " and ".join(conds)
    rows = q(sql + " order by w.watched_on desc, w.id desc limit 400", tuple(params))
    # The chip row lists what the diary actually holds, not TMDB's catalogue,
    # and stays put while the type filter moves.
    genres = [r["g"] for r in q(
        f"select distinct {FIRST_GENRE} g from watches w"
        f" join titles t on t.id = w.title_id"
        f" where w.activity = '' and {FIRST_GENRE} <> '' order by g")]
    months: dict = {}
    for r in rows:
        key = r["watched_on"].strftime("%B %Y")
        months.setdefault(key, []).append(r)
    return templates.TemplateResponse(request, "watched.html", {
        "request": request, "base": base_of(request), "months": months,
        "platforms": PLATFORMS, "people": PEOPLE, "tab": "watched",
        "today": date.today().isoformat(), "who": who(request),
        "type_chips": TYPE_CHIPS, "genres": genres,
        "sel_type": kind_f, "sel_genre": genre_f,
        "qs": request.url.query})


@app.post("/watch")
def log_watch(request: Request, tmdb_id: int = Form(...), kind: str = Form("movie"),
              platform: str = Form("Jellyfin"), watched_on: str = Form(...),
              who_watched: str = Form("Both"), season: str = Form(""),
              rating: str = Form(""), note: str = Form("")):
    t = upsert_title(tmdb_id, kind)
    r, loved = _parse_rating(rating)
    me = who(request)
    # The rating (and the heart) belong to whoever is logging, never to the
    # other person, even when the entry says "Both".
    q("""insert into watches (title_id, season, platform, watched_on, who,
         rating_willian, rating_aline, loved_willian, loved_aline, note)
         values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      (t["id"], int(season) if season.isdigit() else None, platform,
       watched_on, who_watched,
       r if me == "Willian" else None, r if me == "Aline" else None,
       bool(loved and me == "Willian"), bool(loved and me == "Aline"),
       note.strip()))
    return RedirectResponse(base_of(request) + "/watched", status_code=303)


@app.post("/watch/{wid}/rate")
def rate(request: Request, wid: int, rating: str = Form(...), back: str = Form("")):
    me = who(request)
    n, loved = _parse_rating(rating)
    cols = {"Willian": ("rating_willian", "loved_willian"),
            "Aline": ("rating_aline", "loved_aline")}.get(me)
    if cols and n and 1 <= n <= 5:
        q(f"update watches set {cols[0]} = %s, {cols[1]} = %s where id = %s",
          (n, loved, wid))
    return RedirectResponse(base_of(request) + "/watched" + _diary_qs(back),
                            status_code=303)


@app.post("/watch/{wid}/delete")
def delete_watch(request: Request, wid: int, back: str = Form("")):
    """The undo for the automatic feeds (and for fat fingers)."""
    q("delete from watches where id = %s", (wid,))
    return RedirectResponse(base_of(request) + "/watched" + _diary_qs(back),
                            status_code=303)


# --- recap ------------------------------------------------------------------------


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def _top_genre(rs) -> str:
    """Most frequent first-genre among screen content. Empty when there is
    nothing to count, which the template renders as a dash."""
    g: dict = {}
    for r in rs:
        if r["activity"]:
            continue
        first = (r["genres"] or "").split(",")[0].strip()
        if first:
            g[first] = g.get(first, 0) + 1
    return max(g.items(), key=lambda kv: kv[1])[0] if g else ""


def _avg(vals):
    vals = [v for v in vals if v]
    return round(sum(vals) / len(vals), 1) if vals else None


@app.get("/recap", response_class=HTMLResponse)
def recap_now(request: Request, whof: str = Query("", alias="who")):
    return recap(request, date.today().year, whof)


@app.get("/recap/{year}", response_class=HTMLResponse)
def recap(request: Request, year: int, whof: str = Query("", alias="who")):
    whof = whof.strip().lower()
    if whof not in WHO_FILTERS:
        whof = ""
    sql = ("select w.*, t.name, t.kind, t.runtime_min, t.genres, t.poster"
           " from watches w join titles t on t.id = w.title_id"
           " where extract(year from w.watched_on) = %s")
    if whof:
        sql += " and " + WHO_FILTERS[whof]
    rows = q(sql + " order by w.watched_on", (year,))
    # Series seasons count their episodes' runtime approximately: runtime_min
    # is per episode and a season is ~10; movies carry their real runtime.
    # Attended events (activity set) carry no screen time.
    hours = sum((r["runtime_min"] * (10 if r["kind"] == "series" else 1))
                for r in rows if not r["activity"]) / 60
    acts: dict = {}
    for r in rows:
        if r["activity"]:
            c, d = acts.get(r["activity"], (0, 0))
            acts[r["activity"]] = (c + 1, d + (r["days"] or 1))
    plat: dict = {}
    genre: dict = {}
    for r in rows:
        if r["activity"]:
            continue
        plat[r["platform"]] = plat.get(r["platform"], 0) + 1
        for g in (r["genres"] or "").split(","):
            g = g.strip()
            if g:
                genre[g] = genre.get(g, 0) + 1
    def rated(r):
        vals = [v for v in (r["rating_willian"], r["rating_aline"]) if v]
        return sum(vals) / len(vals) if vals else 0
    best = sorted((r for r in rows if rated(r)), key=rated, reverse=True)[:5]
    # Under a person's chip, "loved" means loved BY that person; Everyone and
    # Together show anything either of them hearted.
    if whof == "willian":
        loved = [r for r in rows if r["loved_willian"]]
    elif whof == "aline":
        loved = [r for r in rows if r["loved_aline"]]
    else:
        loved = [r for r in rows if r["loved_willian"] or r["loved_aline"]]
    loved = loved[:8]
    months: dict = {}
    whos: dict = {}
    for r in rows:
        months[r["watched_on"].month] = months.get(r["watched_on"].month, 0) + 1
        whos[r["who"]] = whos.get(r["who"], 0) + 1
    # The poster wall: one tile per distinct artwork, in the order the year
    # happened. Capped so a heavy year does not turn into a 300-image page.
    shelf, seen = [], set()
    for r in rows:
        if r["poster"] and r["poster"] not in seen:
            seen.add(r["poster"])
            shelf.append(r["poster"])
    shelf = shelf[:60]
    busiest = max(months.items(), key=lambda kv: kv[1])[0] if months else 0
    if whof:
        topgen = [("", "", _top_genre(rows))]
    else:
        topgen = [
            ("W", "cw", _top_genre([r for r in rows if r["who"] in ("Willian", "Both")])),
            ("A", "ca", _top_genre([r for r in rows if r["who"] in ("Aline", "Both")])),
        ]
    facts = {
        "busiest": MONTH_NAMES[busiest - 1] if busiest else "",
        "cinema": sum(1 for r in rows if r["platform"] == "Cinema"),
        "days_out": sum((r["days"] or 1) for r in rows if r["activity"]),
        "avg_w": _avg([r["rating_willian"] for r in rows]),
        "avg_a": _avg([r["rating_aline"] for r in rows]),
        "topgen": topgen,
        "has_topgen": any(g for _, _, g in topgen),
    }
    years = [r["y"] for r in q(
        "select distinct extract(year from watched_on)::int y from watches order by y desc")]
    return templates.TemplateResponse(request, "recap.html", {
        "request": request, "base": base_of(request), "tab": "recap",
        "year": year, "years": years, "count": sum(1 for r in rows if not r["activity"]), "hours": round(hours),
        "plat": sorted(plat.items(), key=lambda kv: -kv[1]),
        "acts": sorted(acts.items(), key=lambda kv: -kv[1][0]),
        "genre": sorted(genre.items(), key=lambda kv: -kv[1])[:6],
        "best": best, "rated": rated, "months": months, "loved": loved,
        "shelf": shelf, "facts": facts,
        "whos": sorted(whos.items(), key=lambda kv: -kv[1]),
        "who_chips": WHO_CHIPS, "sel_who": whof,
        "who": who(request)})


# --- the front door (public visitors only; see gate.py) ---------------------------


def _safe_next(n: str) -> str:
    return n if n.startswith("/") and not n.startswith("//") else "/"


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    if gate.trusted(request) or gate.session_user(request):
        return RedirectResponse(base_of(request) + _safe_next(next), status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "request": request, "base": base_of(request),
        "next": _safe_next(next), "error": None, "configured": gate.configured()})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, who_: str = Form("", alias="who"),
                 password: str = Form(""), next: str = Form("/")):
    name = who_.strip().lower()
    if not gate.configured() or not gate.check_password(name, password):
        systime.sleep(1)
        return templates.TemplateResponse(request, "login.html", {
            "request": request, "base": base_of(request),
            "next": _safe_next(next), "configured": gate.configured(),
            "error": "Wrong name or password." if gate.configured() else None})
    resp = RedirectResponse(base_of(request) + _safe_next(next), status_code=303)
    resp.set_cookie(gate.COOKIE, gate.mint(name), max_age=gate.SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", secure=True, path="/")
    return resp
