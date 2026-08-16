# STATUS

A running record of what was built, what was decided, and what was
deliberately left out. Newest first.

**Friction round 2 (2026-08-15, evening):** person filter chips on the diary
(Everyone/Willian/Aline/Together, person colors, same semantics as the
recap, composes with type and genre, survives rate/delete round-trips). The
who-watched select on manual add already existed since v1 (pointed out,
nothing built). All 5-star ratings were RESET at Willian's request so both
people could re-score with the new heart option (a backup was taken first,
14 entries; the write went ahead only after his explicit go, since a
destructive UPDATE like that is exactly the kind of thing that gets refused
until someone says so directly). Clearing a person's rating makes the rate
select reappear for that person: that is the re-scoring mechanism.

**Friction round 1 (2026-08-15, afternoon), all deployed and verified live:**
diary filter chips in two composable dimensions (type: movies/series/cinema/
concerts/sports/trips, plus genre from the data), first genre shown on each
row; the rate select is now strictly per person (gone the moment YOU rated,
still there for the other); **loved**: a "5 stars + heart" option in both
rating selects (loved_willian/loved_aline columns), hearts on diary rows;
recap gained a person filter (Everyone/Willian/Aline/Together, every stat
recomputes), a poster shelf, a Loved row, colored who-bars and fun-facts
cards (busiest month, cinema visits, days out, average stars W/A, top genre
each); person colors changed app-wide: W blue, **A purple**, Both yellow;
🏠 home link in the header, prefix-aware and otherwise pointed at a
configurable portal URL; rating/deleting from a filtered diary returns to
the same filter; the poller skips attended events titled "flight" (trip
logistics are not trips). Playwright-verified at 390px and 1280px, loved
flow tested end to end with a throwaway entry.

**Where it stood (2026-08-15, end of the build day):** live and in real use;
Willian's AMC history backfilled, ratings flowing, first requests queued.
Same-day evolution from real feedback: the Watched tab became **Diary** (it
holds concerts and trips now); attended events (concert/sports/travel +
future camping/beach) flow from the calendar's attended-events endpoint with
**days** for trips; cinema entries are **TMDB-matched** (posters, genres,
honest runtimes); concerts get **band photos** (TheAudioDB); **who-chips**
(W blue, A pink) on requests, diary and recap plus a Who split section;
**per-season series requests** with honest episode progress ("1/10 eps",
ping only when complete); **watchlist vs request**: TMDB streaming providers
checked against the household's services (Netflix, Peacock, Disney+/Hulu,
Apple TV+, HBO Max, Prime, Crunchyroll), streamable titles become watchlist
entries, everything else goes to Jellyfin; dismissed titles revivable;
calendar edits propagate (upsert on source_key). Flights: a logistics
category keeps airport events out of the diary, and since the friction round
the poller also skips any attended event titled "flight", so a trip's flight
leg stays out of the Travel count instead of double-counting it.

**v1 as originally built:** the same day as Groceries. All three tabs work
end to end (verified: TMDB search with posters, request cards, diary with
month grouping, recap page). The poller runs in-process every 15 min:
jellyfin finishes (movies + per-season), request arrivals with a Telegram
ping to the requester, calendar Cinema events via the calendar's API.
Verified against a live Jellyfin instance (both people mapped to Jellyfin
users); zero auto-entries at first is correct, nothing had been fully played
yet.

Test data was wiped after verification; the diary starts empty for a fresh
install and fills itself from there.

Soft spots to watch:
- Series season hours in the recap are approximated (episodes x per-episode
  runtime, assumed 10 eps when TMDB lacks detail).
- Jellyfin title matching is name+year; a rename in Jellyfin can double-log
  after the fact (delete the duplicate, it will not come back: source_key).
- The cinema feed trusts the calendar's event title verbatim; no TMDB match
  is attempted for those entries (poster-less diary rows, by design).

The infrastructure this runs on (reverse proxy, backups, uptime probes) is
not in this repo. The app is only the app.
