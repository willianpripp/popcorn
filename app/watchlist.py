# Pure logic for the Watchlist: no database, no network, no framework, so the
# tests import it directly. main.py and poller.py fetch and store.
#
# Jellyfin is the household's only library, so every add is a request. What
# this module decides is the shape around that request: is the title out yet
# (or does it wait in Coming later), how a typed "where I stopped" is stored,
# and how a Jellyfin playback position reads on a card.

import datetime
import re

# TMDB release types (/movie/{id}/release_dates): 1 premiere, 2 limited
# theatrical, 3 theatrical, 4 digital, 5 physical, 6 TV. A home release
# (4, 5, 6) is what makes a movie something Jellyfin can get.
HOME_TYPES = (4, 5, 6)
THEATER_TYPES = (3, 2, 1)   # in order of preference for "in theaters on"

TICKS_PER_SECOND = 10_000_000


def _day(value):
    """A date from TMDB's "2026-12-18" or "2026-12-18T00:00:00.000Z"."""
    try:
        return datetime.date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _us_dates(release_dates):
    for country in (release_dates or {}).get("results") or []:
        if country.get("iso_3166_1") == "US":
            out = []
            for d in country.get("release_dates") or []:
                day = _day(d.get("release_date"))
                if day and d.get("type") in (1, 2, 3, 4, 5, 6):
                    out.append((d["type"], day))
            return out
    return []


def movie_release(release_dates, primary_date, today):
    """(later, release_date, release_kind) for a movie.

    later: no US home release in the past, and something still ahead (a
    theatrical, home or primary date after today). A movie in theaters with
    nothing announced after it is "out" for this rule and becomes a request.
    release_date: the US digital/home date when TMDB has one; otherwise the
    theatrical date, with release_kind 'theatrical' so the page says the
    digital date is still to be announced. None when TMDB knows no date."""
    us = _us_dates(release_dates)
    home = sorted(day for t, day in us if t in HOME_TYPES)
    primary = _day(primary_date)
    if home and home[0] <= today:
        return False, home[0], "digital"
    ahead = [day for _, day in us if day > today] + ([primary] if primary and primary > today else [])
    later = bool(ahead)
    if home:
        return later, home[0], "digital"
    for t in THEATER_TYPES:
        days = sorted(day for tt, day in us if tt == t)
        if days:
            return later, days[0], "theatrical"
    if primary:
        return later, primary, "theatrical"
    return later, None, ""


def series_release(detail, season, today):
    """(later, release_date, release_kind) for a series or one season of it:
    the premiere date (the season's air date, or the show's first air date).
    No date at all reads as not out yet, with the date to be announced."""
    if season:
        s = next((s for s in (detail or {}).get("seasons") or []
                  if s.get("season_number") == season), None)
        day = _day(s.get("air_date")) if s else None
    else:
        day = _day((detail or {}).get("first_air_date"))
    return (day is None or day > today), day, ("premiere" if day else "")


def later_view(release_date, release_kind, today):
    """How a Coming later card reads: (badge, line, out_now).

    out_now is the one moment the card offers "Request now". A theatrical
    date passing does not count: in theaters is not something Jellyfin can
    get, so the card says "In theaters" until a home date shows up."""
    if release_date is None:
        return "Not out yet", "Date TBA", False
    when = fmt_day(release_date, today)
    if release_kind == "theatrical":
        if release_date <= today:
            return "In theaters", "Digital date TBA", False
        return "Not out yet", f"In theaters {when} · digital date TBA", False
    if release_date <= today:
        return "Out now", f"Out since {when}", True
    return "Not out yet", when, False


def fmt_day(d, today):
    return d.strftime("%b ") + str(d.day) + ("" if d.year == today.year else f", {d.year}")


# --- Discover's Remind me -------------------------------------------------------


def remind_season(sub):
    """The season a Remind me on an anticipated-series card asks for, from the
    cache's extra.sub: "Season 4" -> 4, "New series" (or anything else) ->
    None, which means the whole series."""
    m = re.fullmatch(r"\s*Season\s+(\d+)\s*", sub or "", re.I)
    return int(m.group(1)) if m else None


# --- where you stopped (typed by a person) -----------------------------------------

_EPISODE = re.compile(r"\s*s\s*(\d{1,3})\s*e\s*(\d{1,4})\s*", re.I)


def parse_episode(text):
    """(3, 14) for "S3E14", "s3 e14", "S03E014"; None for anything else."""
    m = _EPISODE.fullmatch(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def episode_code(season, episode):
    return f"S{season} E{episode}"


def stopped_text(text, episode_name=""):
    """What gets stored for a typed "stopped at". An episode code is
    normalized ("S3 E14", plus " · “Name”" when the episode name is known);
    anything else is kept as typed; empty clears."""
    text = (text or "").strip()[:80]
    ep = parse_episode(text)
    if not ep:
        return text
    code = episode_code(*ep)
    return f"{code} · “{episode_name.strip()}”" if (episode_name or "").strip() else code


# --- where you stopped (read from Jellyfin) --------------------------------------


def clock(ticks):
    """Jellyfin ticks as a player clock: "8:48", "1:12:05"."""
    total = int(ticks or 0) // TICKS_PER_SECOND
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _episode_label(ep):
    sn, en = ep.get("ParentIndexNumber"), ep.get("IndexNumber")
    if sn is None or en is None:
        return ep.get("Name") or "next episode"
    return episode_code(sn, en)


def series_resume(next_up, played_any=False):
    """The resume line from a /Shows/NextUp response for one series and user.
    "S1 E9 · 8:48 in" when the next-up episode was started, "Next: S1 E10"
    when it was not. No next episode: "All caught up" if this user played
    any of it, else ""."""
    items = (next_up or {}).get("Items") or []
    if not items:
        return "All caught up" if played_any else ""
    ep = items[0]
    pos = (ep.get("UserData") or {}).get("PlaybackPositionTicks") or 0
    label = _episode_label(ep)
    return f"{label} · {clock(pos)} in" if pos > 0 else f"Next: {label}"


def movie_resume(user_data):
    """"1:12:05 in" for a movie stopped part way, "Watched" when it was played
    to the end, "" when it was never played."""
    ud = user_data or {}
    pos = ud.get("PlaybackPositionTicks") or 0
    if pos > 0:
        return f"{clock(pos)} in"
    return "Watched" if ud.get("Played") else ""


def played_at(value):
    """Jellyfin's LastPlayedDate ("2026-11-20T21:14:03.1234567Z", always UTC)
    cut to whole seconds, as an ISO string Postgres reads as timestamptz.
    None when absent or not a date."""
    v = (value or "")[:19]
    try:
        datetime.datetime.fromisoformat(v)
    except ValueError:
        return None
    return v + "+00:00"


def latest_resume(candidates):
    """candidates: (played_at, text, person) per Jellyfin user. The most
    recent one with something to say wins, tagged with the person's initial:
    ("S1 E9 · 8:48 in · W", played_at). ("", None) when nobody played it."""
    best = max((c for c in candidates if c[0] and c[1]), key=lambda c: c[0], default=None)
    if not best:
        return "", None
    return f"{best[1]} · {best[2][:1].upper()}", best[0]
