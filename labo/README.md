# Lab

The experiments that validated plancliff before any library code was written: two public victims of the generic-plan cliff reproduced on their real schema, and every query of a real application scanned. It is a separate uv project (`cd labo && uv sync`), written in French, and kept as the source of every figure published about plancliff.

| Path | What it holds |
| --- | --- |
| `plancliff.py`, `verifier.py` | the original detector and the 20-call verifier the library is built from |
| `prototype.py`, `epreuve_parade.py` | the first 55-line prototype; the cost of `force_custom_plan` |
| `openfga/` | OpenFGA issue #3444 reproduced: schema, skewed data, replay through psycopg 3 |
| `temporal/` | Temporal issue #12791 reproduced the same way |
| `temporal-complet/` | the 94 queries of Temporal 1.31.1 extracted from its Go code, its schema, a skewed data generator |

## Third-party code

| Files | Origin | Licence |
| --- | --- | --- |
| `openfga/00*.sql` | PostgreSQL migrations of [OpenFGA](https://github.com/openfga/openfga) | Apache-2.0, see `openfga/LICENSE` |
| `temporal-complet/go/*.go`, `temporal-complet/schema.sql` | PostgreSQL persistence plugin and schema of [Temporal](https://github.com/temporalio/temporal) 1.31.1 | MIT, see `temporal-complet/go/LICENSE` |

These files are copied unchanged, only to extract the queries and rebuild the schemas; they are not part of the plancliff package.
