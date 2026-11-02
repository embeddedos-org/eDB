"""EoS eDB GraphStore — directed property graph with BFS/DFS traversal."""
from __future__ import annotations

import json
import uuid
from typing import Any

from .engine import StorageEngine

_SCHEMA = """
CREATE TABLE IF NOT EXISTS _graph_nodes (
    node_id    TEXT PRIMARY KEY,
    label      TEXT NOT NULL DEFAULT '',
    properties TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS _graph_edges (
    edge_id       TEXT PRIMARY KEY,
    src           TEXT NOT NULL,
    dst           TEXT NOT NULL,
    relationship  TEXT NOT NULL DEFAULT '',
    properties    TEXT NOT NULL DEFAULT '{}',
    weight        REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_edge_src ON _graph_edges(src);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON _graph_edges(dst);
"""


class GraphStore:
    """
    Directed property graph.

    API (matches test expectations):
        add_node(label, properties={}, node_id=None) -> dict
        get_node(node_id) -> dict | None
        find_nodes(label=None, limit=100) -> list[dict]
        delete_node(node_id) -> bool
        add_edge(src, dst, relationship, properties={}) -> dict
        get_edges(node_id, direction='out', relationship=None) -> list[dict]
        delete_edge(edge_id) -> bool
        traverse(start, relationship=None, depth=10) -> list[dict]
        shortest_path(src, dst) -> list[str] | None
        node_count() -> int
        edge_count() -> int
    """

    def __init__(self, engine: StorageEngine) -> None:
        self._e = engine
        for stmt in _SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                self._e.execute(s)
        self._e.commit()

    # ── Nodes ────────────────────────────────────────────────────────────────
    def add_node(self, label: str, properties: dict | None = None,
                 node_id: str | None = None) -> dict[str, Any]:
        nid = node_id or str(uuid.uuid4())
        props = properties or {}
        self._e.execute(
            "INSERT OR REPLACE INTO _graph_nodes (node_id, label, properties) VALUES (?, ?, ?)",
            (nid, label, json.dumps(props)),
        )
        self._e.commit()
        return {"id": nid, "label": label, "properties": props}

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        row = self._e.fetchone(
            "SELECT * FROM _graph_nodes WHERE node_id = ?", (node_id,)
        )
        if row is None:
            return None
        return {"id": row["node_id"], "label": row["label"],
                "properties": json.loads(row["properties"])}

    def find_nodes(self, label: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if label:
            rows = self._e.fetchall(
                "SELECT * FROM _graph_nodes WHERE label = ? LIMIT ?", (label, limit)
            )
        else:
            rows = self._e.fetchall("SELECT * FROM _graph_nodes LIMIT ?", (limit,))
        return [{"id": r["node_id"], "label": r["label"],
                 "properties": json.loads(r["properties"])} for r in rows]

    def delete_node(self, node_id: str) -> bool:
        self._e.execute(
            "DELETE FROM _graph_edges WHERE src = ? OR dst = ?", (node_id, node_id)
        )
        cur = self._e.execute(
            "DELETE FROM _graph_nodes WHERE node_id = ?", (node_id,)
        )
        self._e.commit()
        return cur.rowcount > 0

    # ── Edges ────────────────────────────────────────────────────────────────
    def add_edge(self, src: str, dst: str, relationship: str,
                 properties: dict | None = None, weight: float = 1.0) -> dict[str, Any]:
        eid = str(uuid.uuid4())
        props = properties or {}
        self._e.execute(
            "INSERT INTO _graph_edges (edge_id, src, dst, relationship, properties, weight) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, src, dst, relationship, json.dumps(props), weight),
        )
        self._e.commit()
        return {"id": eid, "source_id": src, "target_id": dst,
                "relationship": relationship, "properties": props, "weight": weight}

    def get_edges(self, node_id: str, direction: str = "out",
                  relationship: str | None = None) -> list[dict[str, Any]]:
        if direction == "out":
            query = "SELECT * FROM _graph_edges WHERE src = ?"
            params: tuple[Any, ...] = (node_id,)
        elif direction == "in":
            query = "SELECT * FROM _graph_edges WHERE dst = ?"
            params = (node_id,)
        else:  # both
            query = "SELECT * FROM _graph_edges WHERE src = ? OR dst = ?"
            params = (node_id, node_id)
        if relationship is not None:
            query += " AND relationship = ?"
            params = (*params, relationship)
        rows = self._e.fetchall(query, params)
        return [{"id": r["edge_id"], "source_id": r["src"], "target_id": r["dst"],
                 "relationship": r["relationship"],
                 "properties": json.loads(r["properties"]),
                 "weight": r["weight"]} for r in rows]

    def delete_edge(self, edge_id: str) -> bool:
        cur = self._e.execute(
            "DELETE FROM _graph_edges WHERE edge_id = ?", (edge_id,)
        )
        self._e.commit()
        return cur.rowcount > 0

    # ── Traversal ────────────────────────────────────────────────────────────
    def traverse(self, start: str, relationship: str | None = None,
                 depth: int = 10) -> list[dict[str, Any]]:
        """BFS traversal returning node dicts up to `depth` hops.

        When *relationship* is given, only edges with that relationship
        are followed.
        """
        visited: dict[str, int] = {start: 0}
        queue = [start]
        result = []
        node = self.get_node(start)
        if node:
            result.append(node)
        while queue:
            next_q = []
            for nid in queue:
                current_depth = visited[nid]
                if current_depth >= depth:
                    continue
                if relationship is not None:
                    rows = self._e.fetchall(
                        "SELECT dst FROM _graph_edges WHERE src = ? AND relationship = ?",
                        (nid, relationship),
                    )
                else:
                    rows = self._e.fetchall(
                        "SELECT dst FROM _graph_edges WHERE src = ?", (nid,)
                    )
                for row in rows:
                    nb = row["dst"]
                    if nb not in visited:
                        visited[nb] = current_depth + 1
                        nb_node = self.get_node(nb)
                        if nb_node:
                            result.append(nb_node)
                        next_q.append(nb)
            queue = next_q
        return result

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        """BFS shortest path. Returns None if no path exists."""
        if src == dst:
            return [src]
        visited: dict[str, str | None] = {src: None}
        queue = [src]
        found = False
        while queue and not found:
            node = queue.pop(0)
            rows = self._e.fetchall(
                "SELECT dst FROM _graph_edges WHERE src = ?", (node,)
            )
            for row in rows:
                nb = row["dst"]
                if nb not in visited:
                    visited[nb] = node
                    if nb == dst:
                        found = True
                        break
                    queue.append(nb)
        if not found:
            return None
        # Reconstruct path
        path: list[str] = []
        cur: str | None = dst
        while cur is not None:
            path.append(cur)
            cur = visited[cur]
        path.reverse()
        return path

    def node_count(self) -> int:
        row = self._e.fetchone("SELECT COUNT(*) FROM _graph_nodes")
        # COUNT(*) always returns exactly one row, but fetchone() is typed
        # Row | None; guard so both mypy and a closed DB stay honest.
        return int(row[0]) if row is not None else 0

    def edge_count(self) -> int:
        row = self._e.fetchone("SELECT COUNT(*) FROM _graph_edges")
        return int(row[0]) if row is not None else 0

