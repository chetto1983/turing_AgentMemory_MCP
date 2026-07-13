"""Shared fake ArcadeDB client for the 04-08 rebuild test suite (not collected
as tests -- mirrors `tests/_batch_memory_shared.py`'s convention).

`_FakeArcadeDBClient` is a small in-memory stand-in for `ArcadeDBClient` (same
convention as `tests/test_store_arcadedb_documents.py`'s fake), extended with
a SET-clause interpreter that supports both bound-param assignment and
same-record field-to-field copies -- the D-07 atomic swap's
`UPDATE Type SET embedding = <staging_property>` shape -- plus `sqlscript()`
(`BEGIN;`/`LET $var = ...`/`CREATE EDGE ... TO $var`/`COMMIT;`) support for
`_replace_community_graph`. Split out of `test_store_arcadedb_rebuild.py`
purely to keep that file under the 600-LOC cap.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory

_CREATE_VERTEX_SET_RE = re.compile(r"CREATE VERTEX (\w+) SET (.*)$", re.IGNORECASE)
_UPDATE_TYPE_RE = re.compile(r"UPDATE (\w+) SET (.*?) WHERE (.*)$", re.IGNORECASE)
_UPDATE_NO_WHERE_RE = re.compile(r"UPDATE (\w+) SET (.*)$", re.IGNORECASE)
_SELECT_RE = re.compile(r"SELECT (.*?) FROM (\w+)(?: WHERE (.*))?$", re.IGNORECASE)
_SET_TERM_RE = re.compile(r"\s*(\w+)\s*=\s*(:\w+|'[^']*'|\w+)\s*")
_WHERE_EQ_RE = re.compile(r"\s*(\w+)\s*=\s*(:\w+|'[^']*')\s*")
_WHERE_IN_RE = re.compile(r"\s*(\w+)\s+IN\s+(:\w+)\s*", re.IGNORECASE)
_EDGE_OUT_RE = re.compile(r"out\('(\w+)'\)\.(\w+)(?:\s+AS\s+(\w+))?", re.IGNORECASE)
_PLAIN_FIELD_RE = re.compile(r"(\w+)(?:\s+AS\s+(\w+))?$", re.IGNORECASE)
_LET_RE = re.compile(r"LET \$(\w+) = (.*)$", re.IGNORECASE)
_CREATE_EDGE_RE = re.compile(r"CREATE EDGE (\w+) FROM (.*?) TO (.*)$", re.IGNORECASE)
_SUBQUERY_ID_RE = re.compile(r"\(SELECT FROM \w+ WHERE id = (:\w+)\)", re.IGNORECASE)


def _resolve_rhs(token: str, row: dict[str, object], params: dict[str, object]) -> object:
    token = token.strip()
    if token.startswith(":"):
        return params.get(token[1:])
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    return row.get(token)


def _split_top_level(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


class FakeArcadeDBClient:
    """Session-aware in-memory stand-in for `ArcadeDBClient`. Interprets this
    plan's exact statement shapes: `CREATE VERTEX <Type> SET ...`,
    `UPDATE <Type> SET <bound-param|self-field-copy>... WHERE ...`,
    `SELECT ... FROM <Type> [WHERE ...]` (including `out('Kind').field` edge
    collection and `IN :param`), schema DDL (`CREATE VERTEX TYPE`/
    `CREATE PROPERTY`/`CREATE INDEX`/`DROP INDEX`/`DROP PROPERTY`, all
    no-op/tracked), `CREATE EDGE ... FROM (...) TO (...)`, and `sqlscript()`
    (`BEGIN;`/`LET $var = ...`/`CREATE EDGE ... TO $var`/`COMMIT;`).
    """

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, object] | None, str | None]] = []
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.sqlscripts: list[tuple[str, dict[str, object] | None]] = []
        self.schema_ddl: list[str] = []
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self._committed: list[dict[str, object]] = []
        self._edges: list[tuple[str, str, str]] = []
        self._session_rows: dict[str, list[dict[str, object]]] = {}
        self._session_edges: dict[str, list[tuple[str, str, str]]] = {}
        self._session_counter = 0

    # -- transaction control --

    def begin(self) -> str:
        self.begin_calls += 1
        self._session_counter += 1
        session_id = f"session-{self._session_counter}"
        self._session_rows[session_id] = []
        self._session_edges[session_id] = []
        return session_id

    def commit(self, session_id: str) -> None:
        self.commit_calls += 1
        self._committed.extend(self._session_rows.pop(session_id, []))
        self._edges.extend(self._session_edges.pop(session_id, []))

    def rollback(self, session_id: str) -> None:
        self.rollback_calls += 1
        self._session_rows.pop(session_id, None)
        self._session_edges.pop(session_id, None)

    def run_in_transaction(self, body: Any, *, commit_retries: int | None = None) -> Any:
        session_id = self.begin()
        try:
            result = body(session_id)
        except Exception:
            self.rollback(session_id)
            raise
        self.commit(session_id)
        return result

    def is_ready(self) -> bool:
        return True

    # -- query/command --

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.queries.append((statement, params))
        return self._select(statement, params, session_id)

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.commands.append((statement, params, session_id))
        return self._apply_command(statement, params, session_id)

    def sqlscript(
        self,
        body: str,
        *,
        params: dict[str, object] | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.sqlscripts.append((body, params))
        params = params or {}
        let_vars: dict[str, dict[str, object]] = {}
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line in ("BEGIN;", "COMMIT;"):
                continue
            line = line[:-1] if line.endswith(";") else line
            let_match = _LET_RE.match(line)
            if let_match:
                var_name, inner = let_match.groups()
                self._apply_command(inner, params, None)
                let_vars[var_name] = self._session_rows["__no_session__"][-1]
                continue
            edge_match = _CREATE_EDGE_RE.match(line)
            if edge_match:
                edge_type, from_clause, to_clause = edge_match.groups()
                source_id = self._resolve_endpoint(from_clause, params, let_vars)
                target_id = self._resolve_endpoint(to_clause, params, let_vars)
                self._session_edges.setdefault("__no_session__", []).append(
                    (edge_type, source_id, target_id)
                )
                continue
            self._apply_command(line, params, None)
        return []

    def _resolve_endpoint(
        self, clause: str, params: dict[str, object], let_vars: dict[str, dict[str, object]]
    ) -> str:
        clause = clause.strip()
        if clause.startswith("$"):
            return str(let_vars[clause[1:]].get("id", ""))
        match = _SUBQUERY_ID_RE.search(clause)
        if match:
            return str(_resolve_rhs(match.group(1), {}, params) or "")
        return ""

    # -- statement interpreters --

    def _apply_command(
        self, statement: str, params: dict[str, object] | None, session_id: str | None
    ) -> list[dict[str, object]]:
        upper = statement.strip().upper()
        params = params or {}
        if upper.startswith("SELECT"):
            return self._select(statement, params, session_id)
        if upper.startswith("CREATE VERTEX TYPE") or upper.startswith("CREATE EDGE TYPE"):
            self.schema_ddl.append(statement)
            return []
        if upper.startswith("CREATE PROPERTY") or upper.startswith("CREATE INDEX"):
            self.schema_ddl.append(statement)
            return []
        if upper.startswith("DROP INDEX") or upper.startswith("DROP PROPERTY"):
            self.schema_ddl.append(statement)
            return []
        if upper.startswith("CREATE VERTEX"):
            match = _CREATE_VERTEX_SET_RE.match(statement.strip())
            type_name, set_clause = match.groups()
            row: dict[str, object] = {"_type": type_name}
            for term in _split_top_level(set_clause):
                field, rhs = _SET_TERM_RE.match(term).groups()
                row[field] = _resolve_rhs(rhs, row, params)
            bucket = session_id or "__no_session__"
            self._session_rows.setdefault(bucket, []).append(row)
            return []
        if upper.startswith("CREATE EDGE"):
            match = _CREATE_EDGE_RE.match(statement)
            if match:
                edge_type, from_clause, to_clause = match.groups()
                source_id = self._resolve_endpoint(from_clause, params, {})
                target_id = self._resolve_endpoint(to_clause, params, {})
                bucket = session_id or "__no_session__"
                self._session_edges.setdefault(bucket, []).append((edge_type, source_id, target_id))
            return []
        if upper.startswith("UPDATE"):
            return self._update(statement, params, session_id)
        return []

    def _visible_rows(self, session_id: str | None) -> list[dict[str, object]]:
        bucket = session_id or "__no_session__"
        return self._committed + self._session_rows.get(bucket, [])

    def _visible_edges(self, session_id: str | None) -> list[tuple[str, str, str]]:
        bucket = session_id or "__no_session__"
        return self._edges + self._session_edges.get(bucket, [])

    def _update(
        self, statement: str, params: dict[str, object], session_id: str | None
    ) -> list[dict[str, object]]:
        match = _UPDATE_TYPE_RE.match(statement.strip())
        if match:
            record_type, set_clause, where_clause = match.groups()
        else:
            no_where = _UPDATE_NO_WHERE_RE.match(statement.strip())
            record_type, set_clause = no_where.groups()
            where_clause = ""
        set_terms = [_SET_TERM_RE.match(term).groups() for term in _split_top_level(set_clause)]
        where_terms = self._parse_where(where_clause)
        for row in self._visible_rows(session_id):
            if row.get("_type") != record_type:
                continue
            if not self._matches_where(row, where_terms, params):
                continue
            for field, rhs in set_terms:
                row[field] = _resolve_rhs(rhs, row, params)
        return []

    @staticmethod
    def _parse_where(where_clause: str) -> list[tuple[str, str, str]]:
        # Each term is (field, kind, rhs) where kind is "eq" or "in".
        if not where_clause.strip():
            return []
        terms: list[tuple[str, str, str]] = []
        for part in re.split(r"\bAND\b", where_clause, flags=re.IGNORECASE):
            in_match = _WHERE_IN_RE.match(part.strip())
            if in_match:
                field, rhs = in_match.groups()
                terms.append((field, "in", rhs))
                continue
            eq_match = _WHERE_EQ_RE.match(part.strip())
            if eq_match:
                field, rhs = eq_match.groups()
                terms.append((field, "eq", rhs))
        return terms

    @staticmethod
    def _matches_where(
        row: dict[str, object], terms: list[tuple[str, str, str]], params: dict[str, object]
    ) -> bool:
        for field, kind, rhs in terms:
            if kind == "in":
                candidates = params.get(rhs[1:]) or []
                if row.get(field) not in candidates:
                    return False
                continue
            expected = _resolve_rhs(rhs, row, params)
            if row.get(field) != expected:
                return False
        return True

    def _select(
        self, statement: str, params: dict[str, object] | None, session_id: str | None
    ) -> list[dict[str, object]]:
        params = params or {}
        match = _SELECT_RE.match(statement.strip())
        if not match:
            return []
        fields_text, record_type, where_clause = match.groups()
        where_terms = self._parse_where(where_clause or "")
        rows = [
            row
            for row in self._visible_rows(session_id)
            if row.get("_type") == record_type and self._matches_where(row, where_terms, params)
        ]
        field_specs = _split_top_level(fields_text)
        results: list[dict[str, object]] = []
        for row in rows:
            projected: dict[str, object] = {}
            for spec in field_specs:
                edge_match = _EDGE_OUT_RE.match(spec.strip())
                if edge_match:
                    edge_kind, target_field, alias = edge_match.groups()
                    targets = [
                        target
                        for kind, source, target in self._visible_edges(session_id)
                        if kind == edge_kind and source == row.get("id")
                    ]
                    target_rows = [
                        target_row
                        for target_row in self._visible_rows(session_id)
                        if target_row.get("id") in targets
                    ]
                    projected[alias or f"out_{edge_kind}_{target_field}"] = [
                        target_row.get(target_field) for target_row in target_rows
                    ]
                    continue
                plain_match = _PLAIN_FIELD_RE.match(spec.strip())
                field, alias = plain_match.groups()
                projected[alias or field] = row.get(field)
            results.append(projected)
        return results


def make_store(client: FakeArcadeDBClient, tmp_path: Path, embedder: Any) -> TuringAgentMemory:
    return TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=embedder,
        reranker=None,
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
    )


def seed_vertex(client: FakeArcadeDBClient, type_name: str, **fields: object) -> None:
    row = dict(fields)
    row["_type"] = type_name
    row.setdefault("status", "active")
    client._committed.append(row)


def seed_edge(client: FakeArcadeDBClient, kind: str, source_id: str, target_id: str) -> None:
    client._edges.append((kind, source_id, target_id))


def all_rows(client: FakeArcadeDBClient) -> list[dict[str, object]]:
    # `sqlscript()`'s own writes never go through an explicit `commit()` call
    # (it is self-contained per `ArcadeDBClient.sqlscript`'s docstring) --
    # they land in the "__no_session__" bucket, which `_visible_rows`/`_select`
    # already always include. Test-side assertions need the same union.
    return client._committed + client._session_rows.get("__no_session__", [])


def row(client: FakeArcadeDBClient, type_name: str, record_id: str) -> dict[str, object]:
    return next(
        item
        for item in all_rows(client)
        if item.get("_type") == type_name and item.get("id") == record_id
    )
