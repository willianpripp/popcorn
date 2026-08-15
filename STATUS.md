# STATUS

**Friction round 2 (2026-08-15, evening, relayed live from Willian):** person
filter chips on the diary (Everyone/Willian/Aline/Together, person colors,
same semantics as the recap, composes with type and genre, survives
rate/delete round-trips), deployed and verified. The who-watched select on
manual add already existed since v1 (pointed out, nothing built). And all
5-star ratings were RESET at Willian's order so both can re-score with the
new heart option (backup first: `/srv/lab/popcorn/
ratings-5star-backup-20260815.csv` on the lab host, 14 entries; the UPDATE
ran from the calendar session with his explicit go after this session's
permission layer refused the destructive write, zero fives left, verified).
Clearing a person's rating makes the rate select reappear for that person:
that is the re-scoring mechanism.

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
🏠 home link to the Casa portal in the header; rating/deleting from a
filtered diary returns to the same filter; the poller skips attended events
titled "flight" (trip logistics are not trips). Playwright-verified at 390px
and 1280px, loved flow tested end to end with a throwaway entry.

**Where it stood (2026-08-15, end of the build day):** live and in real use; Willian's
AMC history backfilled, ratings flowing, first requests queued. Same-day
evolution from real feedback: the Watched tab became **Diary** (it holds
concerts and trips now); attended events (concert/sports/travel + future
camping/beach) flow from the calendar's /api/attended with **days** for
trips; cinema entries are **TMDB-matched** (posters, genres, honest
runtimes); concerts get **band photos** (TheAudioDB); **who-chips**
(W blue, A pink) on requests, diary and recap plus a Who split section;
**per-season series requests** with honest episode progress ("1/10 eps",
ping only when complete); **watchlist vs request**: TMDB streaming providers
checked against the household's services (Netflix, Peacock, Disney+/Hulu,
Apple TV+, HBO Max, Prime, Crunchyroll), streamable titles become watchlist
entries, everything else goes to Jellyfin; dismissed titles revivable;
calendar edits propagate (upsert on source_key). Flights: the Visitors
category keeps airport logistics out of the diary, and since the friction
round the poller also skips any attended event titled "flight", so the
Philadelphia flight (Sep 18) can stay Travel and still will not double-count.

**v1 as originally built:** the same day as Groceries.
All three tabs work end to end (verified: TMDB search with posters, request
cards, diary with month grouping, recap page). The poller runs in-process
every 15 min: jellyfin finishes (movies + per-season), request arrivals with
Telegram ping to the requester, calendar Cinema events via /api/cinema.
Verified against live Jellyfin (both users mapped); zero auto-entries so far
is correct, nothing is fully played yet.

**Owned by the homelab session** (same exception as groceries). Test data
wiped after verification; the diary starts empty and fills itself.

Soft spots to watch:
- Series season hours in the recap are approximated (episodes x per-episode
  runtime, assumed 10 eps when TMDB lacks detail).
- Jellyfin title matching is name+year; a rename in Jellyfin can double-log
  after the fact (delete the duplicate, it will not come back: source_key).
- The cinema feed trusts the calendar's event title verbatim; no TMDB match
  is attempted for those entries (poster-less diary rows, by design).
