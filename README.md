# Popcorn

Movie requests and the household watch diary, in one app with three tabs:

- **Want to watch**: the Jellyfin request queue. Adding goes through TMDB
  search (posters, years, runtimes come free). Cards know Jellyfin: "on
  Jellyfin" instead of queueing what already exists, and when a requested
  title lands in the library the requester gets a Telegram ping.
- **Watched**: the diary. What, where (Jellyfin/Cinema/Netflix/AppleTV/...),
  when, who, per-person ratings. FULLY AUTOMATIC where it can be: Jellyfin
  finishes log themselves (movies, and series per completed season), and
  calendar events in the Cinema category flow in via the calendar's
  /api/cinema. Delete an entry to undo; that is the whole contract.
- **Recap**: per year: titles, hours, by-month bars, platform split, best
  rated. Built to be screenshotted.

Same conventions as groceries/family-calendar: FastAPI + Postgres + Jinja,
the SHARED gate (same cookie and secret: one login for the household),
subpath-aware, PWA, phone and desktop from the same templates.

- Tailnet: https://home.example.ts.net:8450/
- Home LAN: http://192.0.2.251:3040/
- Public (login): https://home.example.ts.net:10000/popcorn/
- Portal: the 🍿 tile at https://home.example.ts.net:10000/

Deploy: `make deploy`. Host-only `.env`: POP_DB_PASSWORD, GATE_SECRET,
GATE_USERS (same values as the calendar's CAL_GATE_*), POP_TMDB_KEY (v3 key
or v4 bearer, both accepted), POP_JF_KEY (Jellyfin API key named "popcorn"),
POP_TELEGRAM_TOKEN/CHATS. Backups nightly 07:55 UTC; probed every 2 min.
