from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NamedQuery:
    name: str
    sql: str


def read_queries(path: Path) -> Iterator[NamedQuery]:
    """read_queries yields one query per block separated by a blank line; a leading `-- name` line names the block."""
    for block in path.read_text().split("\n\n"):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0][2:].strip() if lines[0].startswith("--") else " ".join(lines)[:60]
        text = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
        if text:
            yield NamedQuery(name=name, sql=text)
