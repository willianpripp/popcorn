import discover as d

HEADER = ("country_name\tcountry_iso2\tweek\tcategory\tweekly_rank\tshow_title\t"
          "season_title\tcumulative_weeks_in_top_10")


def tsv(*rows):
    return [HEADER] + ["\t".join(map(str, r)) for r in rows]


SAMPLE = tsv(
    ("United States", "US", "2026-11-15", "TV", 1, "Old Hit", "Old Hit: Season 1", 3),
    ("Brazil", "BR", "2026-11-22", "TV", 1, "Other Country", "Season 1", 1),
    ("United States", "US", "2026-11-22", "Films", 1, "Big Movie", "N/A", 2),
    ("United States", "US", "2026-11-22", "TV", 2, "Show From", "Show From: Season 1", 5),
    ("United States", "US", "2026-11-22", "TV", 3, "Daily Thing", "Daily Thing: 2026-11-20", 1),
    ("United States", "US", "2026-11-22", "TV", 4, "Show From", "Show From: Season 3", 4),
    ("United States", "US", "2026-11-22", "Films", 5, "Small Movie", "N/A", 1),
    ("United States", "US", "2026-11-22", "TV", 6, "Show From", "Show From: Season 2", 4),
    ("United States", "US", "2026-11-22", "TV", 7, "Solo", "Solo: Season 2", 1),
    ("United States", "US", "2026-11-22", "TV", 8, "Gap", "Gap: Season 1", 1),
    ("United States", "US", "2026-11-22", "TV", 9, "Gap", "Gap: Season 3", 1),
)


def test_parse_keeps_us_and_latest_week_only():
    week, films, shows = d.parse_netflix_tsv(SAMPLE)
    assert week == "2026-11-22"
    names = [s["name"] for s in shows] + [f["name"] for f in films]
    assert "Old Hit" not in names and "Other Country" not in names


def test_films_keep_published_rank():
    _, films, _ = d.parse_netflix_tsv(SAMPLE)
    assert [(f["name"], f["rank"]) for f in films] == [("Big Movie", 1), ("Small Movie", 5)]


def test_show_seasons_merge_at_best_rank_and_renumber():
    _, _, shows = d.parse_netflix_tsv(SAMPLE)
    assert [(s["rank"], s["name"], s["sub"]) for s in shows] == [
        (1, "Show From", "S1–S3"),   # S1, S3, S2 charted: contiguous
        (2, "Daily Thing", ""),           # episode-date title gets no label
        (3, "Solo", "S2"),
        (4, "Gap", "S1, S3"),             # not contiguous
    ]


def test_parse_rejects_a_file_that_is_not_the_top10():
    for bad in (["<html>"], tsv(("x", "BR", "2026-11-22", "TV", 1, "A", "", 1))):
        try:
            d.parse_netflix_tsv(bad)
        except ValueError:
            continue
        raise AssertionError("should have raised")


def test_seasons_label():
    assert d.seasons_label([]) == ""
    assert d.seasons_label([2]) == "S2"
    assert d.seasons_label([3, 1, 2]) == "S1–S3"
    assert d.seasons_label([1, 3]) == "S1, S3"
    assert d.season_number("N/A") is None and d.season_number("X: Season 12") == 12


def test_week_range():
    assert d.week_range("2026-11-22") == "Nov 16 – Nov 22"
    assert d.week_range("2026-03-01") == "Feb 23 – Mar 1"


def test_shorten_providers():
    assert d.shorten_providers(["Amazon Prime Video", "Netflix"]) == ["Prime Video", "Netflix"]
    assert d.shorten_providers(["Disney Plus"]) == ["Disney+"]
    assert d.shorten_providers(["Paramount Plus Premium", "Paramount Plus Essential", "Hulu"]) == [
        "Paramount+", "Hulu"]
    assert d.shorten_providers(["Peacock Premium"]) == ["Peacock"]
    assert d.shorten_providers(["Amazon Prime Video with Ads", "Amazon Prime Video"]) == ["Prime Video"]
    assert d.shorten_providers(["Max with Ads"]) == ["Max"]
    assert d.shorten_providers(["fuboTV", "Philo", "YouTube TV", "FXNow"]) == []
    assert d.shorten_providers(["fuboTV", "Hulu", "Apple TV", "Peacock"]) == ["Hulu", "Apple TV"]
    assert d.shorten_providers(None) == []


def test_back_guard_honors_only_relative_discover_paths():
    assert d.safe_back("/discover") == "/discover"
    assert d.safe_back("/discover?service=Hulu") == "/discover?service=Hulu"
    assert d.safe_back("/discover/x") == "/discover/x"
    for bad in ("", "/", "/watched", "/discoverx", "//discover", "//evil.example/discover",
                "https://evil.example/discover", "/discover\\@evil", "/discover\r\nX: y",
                "/discover?a=b c", "discover", None, "/discover//evil.example"):
        # the last case stays a relative path on this host; check it is not
        # parsed as a netloc
        if bad == "/discover//evil.example":
            assert d.safe_back(bad) == bad
        else:
            assert d.safe_back(bad) == "", bad


def test_flixpatrol_links():
    assert d.flixpatrol_url("Netflix").endswith("/netflix/united-states/")
    assert d.flixpatrol_url("Hulu").endswith("/streaming/united-states/")
