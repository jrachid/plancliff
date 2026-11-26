from dataclasses import dataclass

from pglast import ast, parse_sql
from pglast.enums import A_Expr_Kind
from pglast.visitors import Visitor


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    schema: str | None = None


class _Binder(Visitor):
    def __init__(self) -> None:
        self.tables: dict[str, tuple[str | None, str]] = {}
        self.bindings: dict[int, list[str]] = {}
        self.ctes: set[str] = set()

    def visit_CommonTableExpr(self, ancestors, node):
        self.ctes.add(node.ctename)

    def visit_RangeVar(self, ancestors, node):
        alias = node.alias.aliasname if node.alias else node.relname
        self.tables[alias] = (node.schemaname, node.relname)

    def bind(self, column, param) -> None:
        if isinstance(column, ast.ColumnRef) and isinstance(param, ast.ParamRef):
            self.bindings.setdefault(param.number, [f.sval for f in column.fields if isinstance(f, ast.String)])

    def visit_InsertStmt(self, ancestors, node):
        columns = [ast.ColumnRef(fields=(ast.String(sval=target.name),)) for target in node.cols or ()]
        for row in getattr(node.selectStmt, "valuesLists", None) or ():
            for column, value in zip(columns, row):
                self.bind(column, value)

    def visit_UpdateStmt(self, ancestors, node):
        for target in node.targetList or ():
            if target.name:
                self.bind(ast.ColumnRef(fields=(ast.String(sval=target.name),)), target.val)

    def visit_A_Expr(self, ancestors, node):
        left, right = node.lexpr, node.rexpr
        if node.kind == A_Expr_Kind.AEXPR_OP:
            self.bind(left, right)
            self.bind(right, left)
        elif node.kind == A_Expr_Kind.AEXPR_IN:
            for element in right:
                if isinstance(left, ast.RowExpr) and isinstance(element, ast.RowExpr):
                    for column, param in zip(left.args, element.args):
                        self.bind(column, param)
                else:
                    self.bind(left, element)


def parameter_columns(query: str) -> dict[int, Column]:
    """parameter_columns maps each `$n` to the column it is compared with; a parameter whose table is ambiguous is left out."""
    binder = _Binder()
    binder(parse_sql(query))
    binder.tables = {alias: table for alias, table in binder.tables.items() if not (table[0] is None and table[1] in binder.ctes)}
    only_table = next(iter(binder.tables.values())) if len(set(binder.tables.values())) == 1 else None
    columns = {}
    for number, path in binder.bindings.items():
        if not path:
            continue
        table = binder.tables.get(path[-2]) if len(path) >= 2 else only_table
        if table is not None:
            columns[number] = Column(schema=table[0], table=table[1], name=path[-1])
    return columns
