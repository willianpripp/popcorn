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


def check_one_request(q, q1, title):
    """Inline check on add, so the badge is honest immediately."""
    try:
        if in_library(library_index(), title):
            q("update requests set status = 'available', available_at = now()"
              " where title_id = %s and status = 'open'", (title["id"],))
    except Exception:
        pass


def sync_arrivals(q, q1):
    rows = q("""select r.id, r.requested_by, t.name, t.year, t.id title_id
                from requests r join titles t on t.id = r.title_id
                where r.status = 'open'""")
    if not rows:
        return
    idx = library_index()
    for r in rows:
        if in_library(idx, {"name": r["name"], "year": r["year"]}):
            q("update requests set status = 'available', available_at = now()"
              " where id = %s", (r["id"],))
            telegram(r["requested_by"],
                     "🍿 %s is on Jellyfin now (you asked for it)" % r["name"])


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
        if q1("select 1 from watches where source_key = %s", (key,)):
            continue
        if ev.get("date", "9999") > today:
            continue  # future plans are not memories yet
        cat = (ev.get("category") or "cinema").lower()
        if cat == "cinema":
            t = _ensure_title(q, q1, ev["title"], None, "movie", 120)
            q("""insert into watches (title_id, platform, watched_on, who,
                 source, source_key) values (%s, 'Cinema', %s, %s, 'calendar', %s)
                 on conflict (source_key) do nothing""",
              (t["id"], ev["date"], ev.get("owner") or "Both", key))
        else:
            t = _ensure_title(q, q1, ev["title"], None, "movie", 0)
            q("""insert into watches (title_id, platform, watched_on, who,
                 source, source_key, activity) values (%s, 'Live', %s, %s,
                 'calendar', %s, %s)
                 on conflict (source_key) do nothing""",
              (t["id"], ev["date"], ev.get("owner") or "Both", key, cat))


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
