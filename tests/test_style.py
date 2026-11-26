import io
import re

import pytest

from plancliff.cli import main
from plancliff.style import RED, Style, wants_color

ANSI = re.compile(r"\033\[[0-9;]*m")


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(name, raising=False)


def test_auto_colours_a_terminal_but_not_a_pipe_or_a_file():
    assert wants_color("auto", _Terminal()) is True
    assert wants_color("auto", io.StringIO()) is False


def test_no_color_wins_over_a_terminal_and_over_force_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert wants_color("auto", _Terminal()) is False


def test_force_color_colours_a_pipe_such_as_a_ci_log(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert wants_color("auto", io.StringIO()) is True


def test_a_dumb_terminal_gets_no_colour(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert wants_color("auto", _Terminal()) is False


def test_always_and_never_ignore_the_environment(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert wants_color("always", io.StringIO()) is True
    monkeypatch.delenv("NO_COLOR")
    assert wants_color("never", _Terminal()) is False


def test_a_disabled_style_returns_the_text_untouched():
    assert Style(False)("CLIFF", RED) == "CLIFF"
    assert Style(True)("CLIFF", RED) == "\033[31mCLIFF\033[0m"


def test_the_coloured_report_reads_the_same_once_colours_are_stripped(dsn, tmp_path, capsys):
    queries = tmp_path / "queries.sql"
    queries.write_text("-- queue\nselect id from jobs where status = $1 order by created_at limit 10\n\n-- by key\nselect id from jobs where id = $1\n")
    main(["scan", dsn, str(queries), "-v", "--color", "never"])
    plain = capsys.readouterr().out
    main(["scan", dsn, str(queries), "-v", "--color", "always"])
    coloured = capsys.readouterr().out
    assert ANSI.search(coloured) and not ANSI.search(plain)
    strip_timings = re.compile(r"[\d.]+")
    assert strip_timings.sub("#", ANSI.sub("", coloured)) == strip_timings.sub("#", plain)
