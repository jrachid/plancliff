"""Package plancliff finds the queries that get much slower once Postgres switches a prepared statement to its generic plan."""

from plancliff.scan import Finding, Verdict, scan_query

__all__ = ["Finding", "Verdict", "scan_query"]
