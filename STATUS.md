# STATUS

**Where it stands (2026-08-15, end of day):** live and in real use; Willian's
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
category on the calendar keeps airport logistics out of the diary; the
Philadelphia flight (Sep 18) is still Travel and will double-count unless
recategorized before it passes.

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
