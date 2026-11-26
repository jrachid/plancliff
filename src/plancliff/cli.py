import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg

from plancliff.queries import read_queries
from plancliff.report import json_document, text_line, text_summary
from plancliff.scan import Verdict, scan_query
from plancliff.settings import Settings
from plancliff.style import BOLD, RED, Style, wants_color

EXIT_OK, EXIT_CLIFF, EXIT_USAGE = 0, 1, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plancliff", description="Find the queries that fall off a cliff when Postgres switches to a generic plan.")
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="measure generic against custom plans for each query of a file")
    scan.add_argument("dsn", help="connection string of a database copy with realistic data, e.g. postgresql://user@host/db")
    scan.add_argument("file", type=Path, help="queries with $1, $2… placeholders, one per block separated by a blank line")
    scan.add_argument("--threshold", type=float, default=Settings.ratio_threshold, help="slowdown ratio that counts as a cliff (default: %(default)s)")
    scan.add_argument("--min-gap-ms", type=float, default=Settings.min_gap_ms, help="smallest absolute slowdown that counts (default: %(default)s ms)")
    scan.add_argument("--timeout", type=float, default=Settings.timeout_s, help="statement timeout per execution, in seconds (default: %(default)s)")
    scan.add_argument("--no-verify", action="store_true", help="skip the 20 auto-mode calls that confirm each cliff; every measured cliff then fails the run")
    scan.add_argument("--format", choices=("text", "json"), default="text", help="report format (default: %(default)s)")
    scan.add_argument("-v", "--verbose", action="store_true", help="also list the queries that are fine, in the text report")
    scan.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="colour the report (default: %(default)s, off when NO_COLOR is set or the output is not a terminal)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    s, err = Style(wants_color(args.color, sys.stdout)), Style(wants_color(args.color, sys.stderr))
    if not args.file.is_file():
        print(f"{err('plancliff:', BOLD, RED)} no such file: {args.file}", file=sys.stderr)
        return EXIT_USAGE
    settings = Settings(ratio_threshold=args.threshold, min_gap_ms=args.min_gap_ms, timeout_s=args.timeout, verify=not args.no_verify)
    if args.format == "json":
        s = Style(False)
    try:
        conn = psycopg.connect(args.dsn)
    except psycopg.Error as error:
        print(f"{err('plancliff:', BOLD, RED)} cannot connect: {str(error).strip()}", file=sys.stderr)
        return EXIT_USAGE
    started, findings = time.perf_counter(), []
    try:
        for query in read_queries(args.file):
            finding = scan_query(conn, query.name, query.sql, settings)
            findings.append(finding)
            if args.format == "text" and (args.verbose or finding.verdict is not Verdict.OK):
                print(text_line(finding, s), flush=True)
    finally:
        conn.rollback()
        conn.close()
    seconds = time.perf_counter() - started
    if args.format == "json":
        print(json_document(findings, seconds, settings))
    else:
        print(text_summary(Counter(finding.verdict for finding in findings), seconds, s))
    return EXIT_CLIFF if any(finding.verdict is Verdict.CLIFF for finding in findings) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
