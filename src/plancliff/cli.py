import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

from plancliff.guard import APPLICATION_NAME, busy_message, other_sessions
from plancliff.queries import read_queries
from plancliff.report import json_document, text_line, text_summary
from plancliff.scan import Finding, Verdict, scan_query
from plancliff.settings import Settings
from plancliff.stats import StatsRead, StatsUnavailable, hidden_message, read_stat_queries, scan_stat_query
from plancliff.style import BOLD, DIM, RED, YELLOW, Style, wants_color

EXIT_OK, EXIT_CLIFF, EXIT_USAGE = 0, 1, 2
EXIT_PIPE_CLOSED = 141


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plancliff", description="Find the queries that fall off a cliff when Postgres switches to a generic plan.")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="measure generic against custom plans for each query of a file or of pg_stat_statements")
    scan.add_argument("dsn", help="connection string of a database copy with realistic data, e.g. postgresql://user@host/db")
    scan.add_argument("file", type=Path, nargs="?", help="queries with $1, $2… placeholders, one per block separated by a blank line; "
                      "without it, the queries come from pg_stat_statements")
    scan.add_argument("--stats-from", metavar="DSN", help="read pg_stat_statements from this database (e.g. production, through a read-only "
                      "connection) instead of the scanned one")
    scan.add_argument("--allow-busy", action="store_true", help="scan even when other sessions are connected to the scanned database; "
                      "measured writes and FOR UPDATE reads lock rows while they run")
    scan.add_argument("--top", type=int, default=100, help="number of pg_stat_statements queries to scan, costliest first (default: %(default)s)")
    scan.add_argument("--threshold", type=float, default=Settings.ratio_threshold, help="slowdown ratio that counts as a cliff (default: %(default)s)")
    scan.add_argument("--min-gap-ms", type=float, default=Settings.min_gap_ms, help="smallest absolute slowdown that counts (default: %(default)s ms)")
    scan.add_argument("--timeout", type=float, default=Settings.timeout_s, help="statement timeout per execution, in seconds (default: %(default)s)")
    scan.add_argument("--no-verify", action="store_true", help="skip the 20 auto-mode calls that confirm each cliff; every measured cliff then fails the run")
    scan.add_argument("--format", choices=("text", "json"), default="text", help="report format (default: %(default)s)")
    scan.add_argument("-v", "--verbose", action="store_true", help="also list the queries that are fine, in the text report")
    scan.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="colour the report (default: %(default)s, off when NO_COLOR is set or the output is not a terminal)")
    return parser


def _fail(err: Style, message: str) -> int:
    print(f"{err('plancliff:', BOLD, RED)} {message}", file=sys.stderr)
    return EXIT_USAGE


def _stat_queries(dsn: str, top: int) -> StatsRead:
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on", application_name=APPLICATION_NAME) as conn:
        return read_stat_queries(conn, top)


def _main(argv: list[str] | None) -> int:
    args = _parser().parse_args(argv)
    s, err = Style(wants_color(args.color, sys.stdout)), Style(wants_color(args.color, sys.stderr))
    if args.file is not None and args.stats_from:
        return _fail(err, "give either a file or --stats-from, not both")
    if args.file is not None and not args.file.is_file():
        return _fail(err, f"no such file: {args.file}")
    settings = Settings(ratio_threshold=args.threshold, min_gap_ms=args.min_gap_ms, timeout_s=args.timeout, verify=not args.no_verify)
    if args.format == "json":
        s = Style(False)
    try:
        if args.file is not None:
            source = {"kind": "file", "path": str(args.file)}
            jobs = [lambda conn, q=query: scan_query(conn, q.name, q.sql, settings) for query in read_queries(args.file)]
        else:
            stats_dsn = args.stats_from or args.dsn
            stats = _stat_queries(stats_dsn, args.top)
            if not stats.queries and stats.hidden:
                return _fail(err, hidden_message(stats.hidden))
            source = {"kind": "pg_stat_statements", "database": conninfo_to_dict(stats_dsn).get("dbname"), "top": args.top, "hidden": stats.hidden}
            jobs = [lambda conn, q=stat: scan_stat_query(conn, q, settings) for stat in stats.queries]
            if args.format == "text":
                print(s(f"{len(jobs)} queries from pg_stat_statements of {source['database']}, costliest first", DIM), flush=True)
                if stats.hidden:
                    print(s(hidden_message(stats.hidden), YELLOW), flush=True)
        conn = psycopg.connect(args.dsn, application_name=APPLICATION_NAME)
    except StatsUnavailable as error:
        return _fail(err, str(error))
    except psycopg.Error as error:
        return _fail(err, f"cannot connect: {str(error).strip()}")
    if not args.allow_busy:
        sessions = other_sessions(conn)
        if sessions:
            conn.close()
            return _fail(err, busy_message(sessions))
    started, findings = time.perf_counter(), []
    try:
        for scan in jobs:
            finding: Finding = scan(conn)
            findings.append(finding)
            if args.format == "text" and (args.verbose or finding.verdict is not Verdict.OK):
                print(text_line(finding, s), flush=True)
    finally:
        conn.rollback()
        conn.close()
    seconds = time.perf_counter() - started
    if args.format == "json":
        print(json_document(findings, seconds, settings, source))
    else:
        print(text_summary(Counter(finding.verdict for finding in findings), seconds, s))
    return EXIT_CLIFF if any(finding.verdict is Verdict.CLIFF for finding in findings) else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """main returns 141, as a shell does on SIGPIPE, when the reader of the report goes away (`plancliff scan … | head`)."""
    try:
        return _main(argv)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return EXIT_PIPE_CLOSED


if __name__ == "__main__":
    sys.exit(main())
