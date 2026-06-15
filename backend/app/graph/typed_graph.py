"""
Phase 4 — Typed University GraphRAG: data structure.

A typed property graph over UMB entities (built from the Phase-2 entity tables),
distinct from the co-occurrence ``KnowledgeGraph`` in ``graph_index.py``.

  * Typed nodes: faculty, program, person, campus, facility, scholarship,
    contact, service.
  * Typed relations: FACULTY_HAS_PROGRAM, FACULTY_HAS_DEAN, PROGRAM_HAS_HEAD,
    PROGRAM_BELONGS_TO_FACULTY (inverse), CAMPUS_HAS_FACILITY,
    SCHOLARSHIP_AVAILABLE_FOR_PROGRAM, SERVICE_BELONGS_TO_UNIT.

The structure supports deterministic, multi-hop relational answers
("which programs does Fakultas Teknik offer?", "which faculty offers Teknik
Informatika?") and is serialisable to/from JSON for offline rebuilds.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

# Relation vocabulary (typed edges).
FACULTY_HAS_PROGRAM = "FACULTY_HAS_PROGRAM"
FACULTY_HAS_DEAN = "FACULTY_HAS_DEAN"
PROGRAM_HAS_HEAD = "PROGRAM_HAS_HEAD"
PROGRAM_BELONGS_TO_FACULTY = "PROGRAM_BELONGS_TO_FACULTY"
CAMPUS_HAS_FACILITY = "CAMPUS_HAS_FACILITY"
SCHOLARSHIP_AVAILABLE_FOR_PROGRAM = "SCHOLARSHIP_AVAILABLE_FOR_PROGRAM"
SERVICE_BELONGS_TO_UNIT = "SERVICE_BELONGS_TO_UNIT"

# Node types.
NODE_FACULTY = "faculty"
NODE_PROGRAM = "program"
NODE_PERSON = "person"
NODE_CAMPUS = "campus"
NODE_FACILITY = "facility"
NODE_SCHOLARSHIP = "scholarship"
NODE_CONTACT = "contact"
NODE_SERVICE = "service"


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def node_id(node_type: str, name: str) -> str:
    return f"{node_type}:{slugify(name)}"


@dataclass
class TypedNode:
    id: str
    type: str
    name: str
    attrs: dict = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "name": self.name, "attrs": self.attrs, "aliases": self.aliases}

    @classmethod
    def from_dict(cls, data: dict) -> "TypedNode":
        return cls(
            id=data["id"],
            type=data["type"],
            name=data["name"],
            attrs=data.get("attrs") or {},
            aliases=data.get("aliases") or [],
        )


@dataclass
class TypedEdge:
    src: str
    rel: str
    dst: str

    def to_dict(self) -> dict:
        return {"src": self.src, "rel": self.rel, "dst": self.dst}

    @classmethod
    def from_dict(cls, data: dict) -> "TypedEdge":
        return cls(src=data["src"], rel=data["rel"], dst=data["dst"])


class TypedGraph:
    """A small in-memory typed property graph with name/alias lookup + adjacency."""

    def __init__(self) -> None:
        self.nodes: dict[str, TypedNode] = {}
        self.edges: list[TypedEdge] = []
        self._out: dict[str, list[TypedEdge]] = defaultdict(list)
        self._in: dict[str, list[TypedEdge]] = defaultdict(list)
        # normalized name/alias -> node id (word-boundary matched at query time)
        self._name_index: dict[str, str] = {}

    # --- build -----------------------------------------------------------
    def upsert_node(
        self,
        node_type: str,
        name: str,
        *,
        attrs: dict | None = None,
        aliases: list[str] | None = None,
    ) -> str:
        nid = node_id(node_type, name)
        existing = self.nodes.get(nid)
        if existing is None:
            existing = TypedNode(id=nid, type=node_type, name=name, attrs=dict(attrs or {}), aliases=list(aliases or []))
            self.nodes[nid] = existing
        else:
            if attrs:
                existing.attrs.update({k: v for k, v in attrs.items() if v is not None})
            for alias in aliases or []:
                if alias not in existing.aliases:
                    existing.aliases.append(alias)
        self._index_node(existing)
        return nid

    def _index_node(self, node: TypedNode) -> None:
        for label in [node.name, *node.aliases]:
            key = _normalize(label)
            if key and len(key) >= 2:
                # Prefer the first (canonical) binding; don't let an alias clobber a name.
                self._name_index.setdefault(key, node.id)

    def add_edge(self, src: str, rel: str, dst: str) -> None:
        if src not in self.nodes or dst not in self.nodes:
            return
        edge = TypedEdge(src=src, rel=rel, dst=dst)
        self.edges.append(edge)
        self._out[src].append(edge)
        self._in[dst].append(edge)

    # --- query -----------------------------------------------------------
    def out_edges(self, nid: str, rel: str | None = None) -> list[TypedEdge]:
        return [e for e in self._out.get(nid, []) if rel is None or e.rel == rel]

    def in_edges(self, nid: str, rel: str | None = None) -> list[TypedEdge]:
        return [e for e in self._in.get(nid, []) if rel is None or e.rel == rel]

    def neighbors(self, nid: str, rel: str, *, direction: str = "out") -> list[TypedNode]:
        edges = self.out_edges(nid, rel) if direction == "out" else self.in_edges(nid, rel)
        key = "dst" if direction == "out" else "src"
        return [self.nodes[getattr(e, key)] for e in edges if getattr(e, key) in self.nodes]

    def match_nodes(self, query: str, *, types: set[str] | None = None, limit: int = 6) -> list[TypedNode]:
        """Return nodes whose name/alias appears as a word-boundary span in the query."""
        normalized = _normalize(query)
        if not normalized:
            return []
        matched: list[tuple[int, TypedNode]] = []
        seen: set[str] = set()
        for key, nid in self._name_index.items():
            if nid in seen:
                continue
            node = self.nodes.get(nid)
            if node is None or (types and node.type not in types):
                continue
            if _word_in(key, normalized):
                # Longer matches are more specific → rank first.
                matched.append((len(key), node))
                seen.add(nid)
        matched.sort(key=lambda kv: kv[0], reverse=True)
        return [node for _, node in matched[:limit]]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            counts[node.type] += 1
        return dict(counts)

    # --- persistence -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TypedGraph":
        graph = cls()
        for node_data in data.get("nodes") or []:
            node = TypedNode.from_dict(node_data)
            graph.nodes[node.id] = node
            graph._index_node(node)
        for edge_data in data.get("edges") or []:
            edge = TypedEdge.from_dict(edge_data)
            if edge.src in graph.nodes and edge.dst in graph.nodes:
                graph.edges.append(edge)
                graph._out[edge.src].append(edge)
                graph._in[edge.dst].append(edge)
        return graph


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _word_in(needle: str, haystack: str) -> bool:
    """True if ``needle`` occurs in ``haystack`` on word boundaries."""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None
