import datetime

import watchlist as w

TODAY = datetime.date(2026, 11, 25)
D = datetime.date


def rd(*dates, country="US"):
    """A /movie/{id}/release_dates payload: (type, "YYYY-MM-DD") pairs."""
    return {"id": 1, "results": [
        {"iso_3166_1": "GB", "release_dates": [{"type": 4, "release_date": "2020-01-01T00:00:00.000Z"}]},
        {"iso_3166_1": country, "release_dates": [
            {"type": t, "release_date": f"{d}T00:00:00.000Z", "certification": "", "note": ""}
            for t, d in dates]},
    ]}


# --- release-date decision ------------------------------------------------------


def test_movie_with_a_past_digital_release_is_released():
    assert w.movie_release(rd((3, "2026-08-01"), (4, "2026-10-14")), "2026-08-01", TODAY) == (
        False, D(2026, 10, 14), "digital")


def test_physical_or_tv_release_also_counts_as_released():
    assert w.movie_release(rd((3, "2026-01-10"), (5, "2026-04-02")), "2026-01-10", TODAY)[0] is False
    assert w.movie_release(rd((6, "2026-06-01")), "2026-06-01", TODAY)[0] is False


def test_in_theaters_with_digital_date_announced_waits_for_the_digital_date():
    assert w.movie_release(rd((3, "2026-11-07"), (4, "2026-12-23")), "2026-11-07", TODAY) == (
        True, D(2026, 12, 23), "digital")


def test_future_theatrical_only_is_later_with_the_theatrical_date():
    # the wide release is preferred over the premiere and the limited one
    got = w.movie_release(rd((1, "2026-12-01"), (2, "2026-12-12"), (3, "2026-12-19")),
                          "2026-12-19", TODAY)
    assert got == (True, D(2026, 12, 19), "theatrical")


def test_future_primary_date_with_no_us_dates_is_later():
    assert w.movie_release(rd(country="FR"), "2027-03-05", TODAY) == (True, D(2027, 3, 5), "theatrical")


def test_no_dates_at_all_is_a_request():
    assert w.movie_release({"results": []}, "", TODAY) == (False, None, "")
    assert w.movie_release(None, None, TODAY) == (False, None, "")


def test_in_theaters_with_nothing_ahead_is_a_request():
    # still in theaters, no digital date: the plain add rule makes it a request
    assert w.movie_release(rd((3, "2026-11-14")), "2026-11-14", TODAY) == (
        False, D(2026, 11, 14), "theatrical")


def test_old_movie_with_only_a_primary_date():
    assert w.movie_release({"results": []}, "1999-03-31", TODAY) == (False, D(1999, 3, 31), "theatrical")


def test_series_and_season_premieres():
    detail = {"first_air_date": "2022-02-18", "seasons": [
        {"season_number": 0, "air_date": None},
        {"season_number": 1, "air_date": "2022-02-18"},
        {"season_number": 3, "air_date": "2027-01-15"},
        {"season_number": 4, "air_date": None}]}
    assert w.series_release(detail, None, TODAY) == (False, D(2022, 2, 18), "premiere")
    assert w.series_release(detail, 1, TODAY) == (False, D(2022, 2, 18), "premiere")
    assert w.series_release(detail, 3, TODAY) == (True, D(2027, 1, 15), "premiere")
    assert w.series_release(detail, 4, TODAY) == (True, None, "")      # announced, TBA
    assert w.series_release(detail, 9, TODAY) == (True, None, "")      # unknown season
    assert w.series_release({"first_air_date": "2027-02-01"}, None, TODAY) == (True, D(2027, 2, 1), "premiere")


def test_later_view():
    assert w.later_view(None, "", TODAY) == ("Not out yet", "Date TBA", False)
    assert w.later_view(D(2026, 12, 23), "digital", TODAY) == ("Not out yet", "Dec 23", False)
    assert w.later_view(D(2027, 1, 15), "premiere", TODAY) == ("Not out yet", "Jan 15, 2027", False)
    assert w.later_view(D(2026, 11, 25), "digital", TODAY) == ("Out now", "Out since Nov 25", True)
    assert w.later_view(D(2026, 12, 19), "theatrical", TODAY) == (
        "Not out yet", "In theaters Dec 19 · digital date TBA", False)
    # a theatrical date passing is not "out": Jellyfin cannot get it yet
    assert w.later_view(D(2026, 11, 14), "theatrical", TODAY) == ("In theaters", "Digital date TBA", False)


# --- Remind me season ------------------------------------------------------------


def test_remind_season_from_extra_sub():
    assert w.remind_season("Season 4") == 4
    assert w.remind_season("Season 12") == 12
    assert w.remind_season("New series") is None
    assert w.remind_season("") is None
    assert w.remind_season(None) is None
    assert w.remind_season("S1–S3") is None


# --- typed "stopped at" ------------------------------------------------------------


def test_episode_codes_normalize():
    for typed in ("S3E14", "s3 e14", "S3 E14", " S03E014 ", "s 3 e 14"):
        assert w.parse_episode(typed) == (3, 14), typed
        assert w.stopped_text(typed) == "S3 E14"
    assert w.stopped_text("s3e14", "Party") == "S3 E14 · “Party”"


def test_free_text_is_kept_and_empty_clears():
    assert w.parse_episode("halfway through the finale") is None
    assert w.stopped_text("  halfway through the finale ") == "halfway through the finale"
    assert w.stopped_text("S3E14 and a bit", "Party") == "S3E14 and a bit"
    assert w.stopped_text("") == ""
    assert w.stopped_text(None) == ""
    assert len(w.stopped_text("x" * 200)) == 80


# --- Jellyfin resume text ----------------------------------------------------------


def test_clock_from_ticks():
    assert w.clock(0) == "0:00"
    assert w.clock(528 * 10_000_000) == "8:48"
    assert w.clock((72 * 60 + 5) * 10_000_000) == "1:12:05"
    assert w.clock(None) == "0:00"


def ep(sn, en, pos=0, name="Ep"):
    return {"Name": name, "ParentIndexNumber": sn, "IndexNumber": en,
            "UserData": {"PlaybackPositionTicks": pos, "Played": False}}


def test_series_resume_shapes():
    assert w.series_resume({"Items": [ep(1, 9, 528 * 10_000_000)]}) == "S1 E9 · 8:48 in"
    assert w.series_resume({"Items": [ep(1, 10)], "TotalRecordCount": 1}) == "Next: S1 E10"
    assert w.series_resume({"Items": [], "TotalRecordCount": 0}) == ""
    assert w.series_resume({"Items": []}, played_any=True) == "All caught up"
    assert w.series_resume({"Items": [{"Name": "Pilot", "UserData": {}}]}) == "Next: Pilot"
    assert w.series_resume(None) == ""


def test_movie_resume():
    assert w.movie_resume({"PlaybackPositionTicks": (72 * 60 + 5) * 10_000_000}) == "1:12:05 in"
    assert w.movie_resume({"PlaybackPositionTicks": 0, "Played": True}) == "Watched"
    assert w.movie_resume({"PlaybackPositionTicks": 0, "Played": False}) == ""
    assert w.movie_resume(None) == ""


def test_played_at():
    assert w.played_at("2026-11-20T21:14:03.1234567Z") == "2026-11-20T21:14:03+00:00"
    assert w.played_at("") is None
    assert w.played_at(None) is None
    assert w.played_at("not a date") is None


def test_latest_resume_keeps_the_most_recent_with_the_initial():
    cands = [("2026-11-20T21:14:03+00:00", "S1 E9 · 8:48 in", "willian"),
             ("2026-11-22T10:00:00+00:00", "Next: S1 E4", "aline"),
             (None, "", "willian")]
    assert w.latest_resume(cands) == ("Next: S1 E4 · A", "2026-11-22T10:00:00+00:00")
    assert w.latest_resume([(None, "", "willian"), (None, "", "aline")]) == ("", None)
    assert w.latest_resume([]) == ("", None)


def test_store_channels_are_not_services():
    import discover
    assert discover.shorten_providers(["Prime Video", "HBO Max Amazon Channel", "Apple TV Amazon Channel", "Hulu"]) == ["Prime Video", "Hulu"]
