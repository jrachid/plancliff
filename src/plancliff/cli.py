import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg

from plancliff.queries import read_queries
from plancliff.scan import Finding, Settings, Verdict, scan_query
from plancliff.style import BOLD, CLIFF_BADGE, CYAN, DIM, ERROR_BADGE, GREEN, OK_BADGE, RED, YELLOW, Style, wants_color

EXIT_OK, EXIT_CLIFF, EXIT_USAGE = 0, 1, 2
SHOWN_VALUES = 6


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plancliff", description="Find the queries that fall off a cliff when Postgres switches to a generic plan.")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="measure generic against custom plans for each query of a file")
    scan.add_argument("dsn", help="connection string of a database copy with realistic data, e.g. postgresql://user@host/db")
    scan.add_argument("file", type=Path, help="queries with $1, $2… placeholders, one per block separated by a blank line")
    scan.add_argument("--threshold", type=float, default=Settings.ratio_threshold, help="slowdown ratio that counts as a cliff (default: %(default)s)")
    scan.add_argument("--min-gap-ms", type=float, default=Settings.min_gap_ms, help="smallest absolute slowdown that counts (default: %(default)s ms)")
    scan.add_argument("--timeout", type=float, default=Settings.timeout_s, help="statement timeout per execution, in seconds (default: %(default)s)")
    scan.add_argument("-v", "--verbose", action="store_true", help="also list the queries that are fine")
    scan.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="colour the report (default: %(default)s, off when NO_COLOR is set or the output is not a terminal)")
    return parser


def _line(finding: Finding, s: Style) -> str:
    indent = " " * 8
    if finding.verdict is Verdict.ERROR:
        return f"{s(' ERROR ', ERROR_BADGE)} {s(finding.name, BOLD)}\n{indent}{s(finding.error, YELLOW)}"
    is_cliff = finding.verdict is Verdict.CLIFF
    badge = s(" CLIFF ", CLIFF_BADGE) if is_cliff else s(" ok    ", OK_BADGE)
    ratio = s(f"{finding.ratio:8.1f}×", BOLD, RED) if is_cliff else s(f"{finding.ratio:8.1f}×", DIM)
    timings = f"{s('generic', DIM)} {finding.generic_ms:9.2f} ms{s(',', DIM)} {s('custom', DIM)} {finding.custom_ms:8.2f} ms"
    head = f"{badge} {ratio}  {timings}  {s(finding.name, BOLD) if is_cliff else finding.name}"
    if not is_cliff:
        return head
    shown = ", ".join(finding.values[:SHOWN_VALUES]) + (f", … ({len(finding.values)} values)" if len(finding.values) > SHOWN_VALUES else "")
    return f"{head}\n{indent}{s(f'triggered by the {finding.scenario} values:', DIM)} {s(shown, CYAN)}"


def _summary(counts: Counter, seconds: float, s: Style) -> str:
    cliffs, oks, errors = counts[Verdict.CLIFF], counts[Verdict.OK], counts[Verdict.ERROR]
    parts = [
        s(f"{cliffs} cliff", BOLD, RED) if cliffs else s(f"{cliffs} cliff", DIM),
        s(f"{oks} ok", GREEN),
        s(f"{errors} error", YELLOW) if errors else s(f"{errors} error", DIM),
    ]
    return f"\n{sum(counts.values())} queries in {seconds:.1f} s: {', '.join(parts)}"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    s, err = Style(wants_color(args.color, sys.stdout)), Style(wants_color(args.color, sys.stderr))
    if not args.file.is_file():
        print(f"{err('plancliff:', BOLD, RED)} no such file: {args.file}", file=sys.stderr)
        return EXIT_USAGE
    settings = Settings(ratio_threshold=args.threshold, min_gap_ms=args.min_gap_ms, timeout_s=args.timeout)
    try:
        conn = psycopg.connect(args.dsn)
    except psycopg.Error as error:
        print(f"{err('plancliff:', BOLD, RED)} cannot connect: {str(error).strip()}", file=sys.stderr)
        return EXIT_USAGE
    started, counts = time.perf_counter(), Counter()
    try:
        for query in read_queries(args.file):
            finding = scan_query(conn, query.name, query.sql, settings)
            counts[finding.verdict] += 1
            if args.verbose or finding.verdict is not Verdict.OK:
                print(_line(finding, s), flush=True)
    finally:
        conn.rollback()
        conn.close()
    print(_summary(counts, time.perf_counter() - started, s))
    return EXIT_CLIFF if counts[Verdict.CLIFF] else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
