# The automatic feeds. Decided by Willian 2026-08-15: "automatic would be
# nice" — so nothing here asks for confirmation, and every entry it writes
# can be deleted in the UI (delete IS the undo).
#
# Three jobs, every 15 minutes, all idempotent through watches.source_key:
#   1. Jellyfin finishes: movies a user played, and series seasons where every
#      episode is played, become diary entries (source 'jellyfin', key
#      'jf:<user>:<item>' / 'jf:<user>:<series>:s<season>').
#   2. Request arrivals: an open request whose title now exists in the
#      Jellyfin library flips to 'available' and pings the requester's phone
#      through the household bot.
#   3. Calendar Cinema events (source 'calendar', key 'cal:<event id>'), read
#      from the calendar's /api/cinema on the LAN. Until the calendar ships
#      that endpoint this job just logs and moves on.

import asyncio
import json
import os
import urllib.parse
import urllib.request

JF = os.environ.get("POP_JF_URL", "http://192.0.2.213:8096").rstrip("/")
JF_KEY = os.environ.get("POP_JF_KEY", "")
CAL_API = os.environ.get("POP_CAL_API", "http://192.0.2.251:3002/api/cinema")
# Widened feed (attended events); falls back to CAL_API when unset or 404.
CAL_API_WIDE = os.environ.get("POP_CAL_API_WIDE", "http://192.0.2.251:3002/api/attended")
TICK = 900


def jf(path, **params):
    params["api_key"] = JF_KEY
    url = f"{JF}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def telegram(chat_name: str, text: str):
    token = os.environ.get("POP_TELEGRAM_TOKEN", "")
    chats = {}
    for pair in os.environ.get("POP_TELEGRAM_CHATS", "").split(","):
        if "=" in pair:
            name, _, cid = pair.partition("=")
            chats[name.strip().lower()] = cid.strip()
    targets = [chats[chat_name.lower()]] if chat_name.lower() in chats else list(chats.values())
    for cid in targets:
        try:
            data = urllib.parse.urlencode({"chat_id": cid, "text": text}).encode()
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10)
        except Exception:
            pass


# --- jellyfin library matching ----------------------------------------------------


def library_index():
    """name.lower() + year -> item, for movies and series."""
    items = jf("/Items", IncludeItemTypes="Movie,Series", Recursive="true",
               fields="ProductionYear")["Items"]
    idx = {}
    for it in items:
        idx[(it["Name"].strip().lower(), it.get("ProductionYear"))] = it
        idx.setdefault((it["Name"].strip().lower(), None), it)
    return idx


def in_library(idx, title) -> bool:
    key = (title["name"].strip().lower(), title["year"])
    return key in idx or (title["name"].strip().lower(), None) in idx


def _season_progress(idx, r):
    """For a season-specific series request: (have, want) episode counts.
    `want` comes from TMDB's season list; `have` from Jellyfin. A season is
    available only when have >= want, so one Dexter episode does not count as
    "on Jellyfin" for the season (Willian, 2026-08-15)."""
    key = (r["name"].strip().lower(), r["year"])
    item = idx.get(key) or idx.get((r["name"].strip().lower(), None))
    have = 0
    if item:
        eps = jf(f"/Shows/{item['Id']}/Episodes", season=r["season"])["Items"]
        have = len(eps)
    want = 0
    if r.get("tmdb_id"):
        try:
            import main
            detail = main.tmdb(f"/tv/{r['tmdb_id']}")
            want = next((sn.get("episode_count", 0) for sn in detail.get("seasons", [])
                         if sn.get("season_number") == r["season"]), 0)
        except Exception:
            want = 0
    return have, want


def _request_ready(idx, r):
    """available?, progress-text"""
    if r["season"] is None:
        return in_library(idx, {"name": r["name"], "year": r["year"]}), ""
    have, want = _season_progress(idx, r)
    if want:
        return have >= want, f"{have}/{want} eps"
    # TMDB silent about the season: fall back to "any episodes exist"
    return have > 0, (f"{have} eps" if have else "")


def check_one_request(q, q1, title, season=None):
    """Inline check on add, so the badge is honest immediately."""
    try:
        idx = library_index()
        r = {"name": title["name"], "year": title["year"],
             "tmdb_id": title.get("tmdb_id"), "season": season}
        ready, progress = _request_ready(idx, r)
        if ready:
            q("update requests set status = 'available', available_at = now()"
              " where title_id = %s and coalesce(season, 0) = %s and status = 'open'",
              (title["id"], season or 0))
        elif progress:
            q("update requests set progress = %s where title_id = %s"
              " and coalesce(season, 0) = %s", (progress, title["id"], season or 0))
    except Exception:
        pass


def sync_arrivals(q, q1):
    rows = q("""select r.id, r.season, r.requested_by, t.name, t.year,
                       t.tmdb_id, t.id title_id
                from requests r join titles t on t.id = r.title_id
                where r.status = 'open' and r.watch_on = ''""")
    if not rows:
        return
    idx = library_index()
    for r in rows:
        ready, progress = _request_ready(idx, r)
        if ready:
            q("update requests set status = 'available', available_at = now(),"
              " progress = '' where id = %s", (r["id"],))
            label = r["name"] + (f" S{r['season']}" if r["season"] else "")
            telegram(r["requested_by"],
                     "🍿 %s is on Jellyfin now (you asked for it)" % label)
        else:
            q("update requests set progress = %s where id = %s", (progress, r["id"]))


# --- jellyfin finishes --------------------------------------------------------------


def _person_users():
    """Jellyfin users that map to household people."""
    return {u["Name"].strip().lower(): u["Id"] for u in jf("/Users")
            if u["Name"].strip().lower() in ("willian", "aline")}


def _ensure_title(q, q1, name, year, kind, runtime_min):
    t = q1("select * from titles where lower(name) = lower(%s)"
           " and year is not distinct from %s", (name, year))
    if t:
        return t
    return q1("insert into titles (kind, name, year, runtime_min)"
              " values (%s, %s, %s, %s) returning *",
              (kind, name, year, runtime_min or 0))


def sync_jellyfin_watches(q, q1):
    for person, uid in _person_users().items():
        # movies played by this user
        movies = jf(f"/Users/{uid}/Items", IncludeItemTypes="Movie",
                    Recursive="true", Filters="IsPlayed",
                    fields="ProductionYear,RunTimeTicks,UserDataLastPlayedDate")["Items"]
        for m in movies:
            key = f"jf:{person}:{m['Id']}"
            if q1("select 1 from watches where source_key = %s", (key,)):
                continue
            played = (m.get("UserData", {}).get("LastPlayedDate") or "")[:10] or None
            t = _ensure_title(q, q1, m["Name"], m.get("ProductionYear"), "movie",
                              int((m.get("RunTimeTicks") or 0) / 600_000_000))
            q("""insert into watches (title_id, platform, watched_on, who,
                 source, source_key) values (%s, 'Jellyfin',
                 coalesce(%s::date, current_date), %s, 'jellyfin', %s)
                 on conflict (source_key) do nothing""",
              (t["id"], played, person.capitalize(), key))
        # series: a season is finished when every episode is played
        series = jf(f"/Users/{uid}/Items", IncludeItemTypes="Series",
                    Recursive="true", fields="ProductionYear")["Items"]
        for s in series:
            eps = jf(f"/Shows/{s['Id']}/Episodes", userId=uid,
                     fields="UserDataLastPlayedDate")["Items"]
            seasons: dict = {}
            for e in eps:
                sn = e.get("ParentIndexNumber")
                if sn is None:
                    continue
                ud = e.get("UserData", {})
                seasons.setdefault(sn, []).append(ud)
            for sn, uds in seasons.items():
                if not uds or not all(u.get("Played") for u in uds):
                    continue
                key = f"jf:{person}:{s['Id']}:s{sn}"
                if q1("select 1 from watches where source_key = %s", (key,)):
                    continue
                last = max((u.get("LastPlayedDate") or "")[:10] for u in uds) or None
                t = _ensure_title(q, q1, s["Name"], s.get("ProductionYear"), "series", 45)
                q("""insert into watches (title_id, season, platform, watched_on,
                     who, source, source_key) values (%s, %s, 'Jellyfin',
                     coalesce(%s::date, current_date), %s, 'jellyfin', %s)
                     on conflict (source_key) do nothing""",
                  (t["id"], sn, last, person.capitalize(), key))


# --- calendar cinema events ---------------------------------------------------------


def _norm_title(t):
    return "".join(c for c in t.lower() if c.isalnum() or c == " ").strip()


def _cinema_title(q, q1, ev):
    """A cinema event's title, TMDB-matched when possible so the diary gets
    the real poster, genres and runtime instead of a flat 2h guess. The match
    must actually look like the event's title (normalized equality or
    containment), because "One Night Only" was an AMC Screen Unseen session
    and a confident wrong poster is worse than none. Matched once per entry:
    an existing entry already pointing at a TMDB-backed title is left alone."""
    existing = q1("""select t.id title_id, t.tmdb_id from watches w
                     join titles t on t.id = w.title_id
                     where w.source_key = %s""", (f"cal:{ev['id']}",))
    if existing and existing["tmdb_id"]:
        return existing["title_id"]
    import main
    year = (ev.get("date") or "")[:4]
    try:
        res = main.tmdb("/search/movie", query=ev["title"],
                        primary_release_year=year, include_adult="false")
        hits = res.get("results", [])
        if not hits:
            hits = main.tmdb("/search/movie", query=ev["title"],
                             include_adult="false").get("results", [])
        want = _norm_title(ev["title"])
        for h in hits[:3]:
            got = _norm_title(h.get("title") or "")
            if got and (got == want or want in got or got in want):
                return main.upsert_title(h["id"], "movie")["id"]
    except Exception:
        pass
    return _ensure_title(q, q1, ev["title"], None, "movie", 120)["id"]


def _artist_image(name):
    """A band photo for concert entries, via TheAudioDB's free tier. The
    event title carries tour names ("Alex Warren: Finding Family on the
    Road") and Portuguese prefixes ("Show AC/DC"), so try progressively
    cleaned forms. Absent is fine: the row falls back to its emoji tile."""
    cands = [name]
    if ":" in name:
        cands.append(name.split(":")[0])
    if " - " in name:
        cands.append(name.split(" - ")[0])
    low = name.lower()
    if low.startswith("show "):
        cands.append(name[5:])
    for c in cands:
        try:
            url = ("https://www.theaudiodb.com/api/v1/json/2/search.php?s="
                   + urllib.parse.quote(c.strip()))
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
            artists = data.get("artists") or []
            thumb = artists[0].get("strArtistThumb") if artists else None
            if thumb:
                return thumb + "/preview"
        except Exception:
            continue
    return ""


def sync_cinema(q, q1):
    """The calendar feed. Prefers the widened endpoint (cinema + attended
    events: concert/sports/travel/...); falls back to the original
    cinema-only one so neither side has to deploy first."""
    events = None
    for url in (CAL_API_WIDE, CAL_API):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                events = json.load(r)
            break
        except Exception:
            continue
    if events is None:
        return  # calendar down: next tick retries
    import datetime
    today = str(datetime.date.today())
    for ev in events:
        key = f"cal:{ev['id']}"
        if ev.get("date", "9999") > today:
            continue  # future plans are not memories yet
        cat = (ev.get("category") or "cinema").lower()
        if cat == "cinema":
            tid = _cinema_title(q, q1, ev)
            q("""insert into watches (title_id, platform, watched_on, who,
                 source, source_key) values (%s, 'Cinema', %s, %s, 'calendar', %s)
                 on conflict (source_key) do update
                 set title_id = excluded.title_id,
                     watched_on = excluded.watched_on, who = excluded.who""",
              (tid, ev["date"], ev.get("owner") or "Both", key))
        else:
            t = _ensure_title(q, q1, ev["title"], None, "movie", 0)
            if cat == "concert" and not t.get("poster"):
                img = _artist_image(ev["title"])
                if img:
                    q("update titles set poster = %s where id = %s", (img, t["id"]))
            # UPSERT, not insert-once: editing the event (dates stretched,
            # title fixed, owner changed) updates the diary entry in place.
            q("""insert into watches (title_id, platform, watched_on, who,
                 source, source_key, activity, days) values (%s, 'Live', %s,
                 %s, 'calendar', %s, %s, %s)
                 on conflict (source_key) do update
                 set title_id = excluded.title_id,
                     watched_on = excluded.watched_on,
                     who = excluded.who, activity = excluded.activity,
                     days = excluded.days""",
              (t["id"], ev["date"], ev.get("owner") or "Both", key, cat,
               int(ev.get("days") or 1)))


async def loop(q, q1):
    if not JF_KEY:
        print("popcorn poller: POP_JF_KEY unset; automatic feeds disabled")
        return
    await asyncio.sleep(10)
    while True:
        for job in (sync_jellyfin_watches, sync_arrivals, sync_cinema):
            try:
                await asyncio.to_thread(job, q, q1)
            except Exception as e:
                print(f"popcorn poller: {job.__name__}: {e}")
        await asyncio.sleep(TICK)
