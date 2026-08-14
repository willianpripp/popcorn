# STATUS

**Where it stands (2026-08-15):** v1 live, built the same day as Groceries.
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
