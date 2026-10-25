# Every environment variable the app reads must be passed to the app
# container by docker-compose.yml. Compose only forwards what the service's
# `environment:` block names, so a variable missing there is silently unset in
# a real deploy even with the right value in .env.

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
READ = re.compile(r"""os\.environ(?:\.get\(|\[)\s*["']([A-Z0-9_]+)["']""")


def _read_by_app() -> set[str]:
    names = set()
    for path in (ROOT / "app").glob("*.py"):
        names |= set(READ.findall(path.read_text()))
    return names


def _app_service_environment() -> set[str]:
    text = (ROOT / "docker-compose.yml").read_text()
    app = text.split("\n  app:\n", 1)[1]
    env_block = app.split("    environment:\n", 1)[1]
    names = set()
    for line in env_block.splitlines():
        if line.strip() and not line.startswith("      "):
            break
        m = re.match(r"\s{6}([A-Z0-9_]+):", line)
        if m:
            names.add(m.group(1))
    return names


def test_the_scan_finds_what_the_app_reads():
    assert {"POP_DSN", "POP_TMDB_KEY", "GATE_SECRET"} <= _read_by_app()


def test_every_variable_the_app_reads_is_passed_by_docker_compose():
    missing = _read_by_app() - _app_service_environment()
    assert missing == set(), f"docker-compose.yml's app service does not pass: {sorted(missing)}"
