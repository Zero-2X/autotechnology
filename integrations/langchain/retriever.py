"""Tenant and evidence-aware retrieval port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class RetrieverError(ValueError): pass


@dataclass(frozen=True)
class RetrievedDocument:
    id: str
    org_id: str
    text_ref: str
    score: float
    evidence_refs: tuple[str, ...]
    source_snapshot_ref: str


class RetrieverPort(Protocol):
    def search(self, *, org_id: str, query: str, limit: int = 10, required_evidence: tuple[str, ...] = ()) -> tuple[RetrievedDocument, ...]: ...


class InMemoryRetriever:
    def __init__(self) -> None: self.documents: list[RetrievedDocument] = []

    def add(self, document: RetrievedDocument) -> None:
        if not document.source_snapshot_ref.startswith("private://"):
            raise RetrieverError("retriever source must be private")
        if not 0 <= document.score <= 1: raise RetrieverError("score must be between 0 and 1")
        self.documents.append(document)

    def search(self, *, org_id: str, query: str, limit: int = 10, required_evidence: tuple[str, ...] = ()) -> tuple[RetrievedDocument, ...]:
        if not isinstance(query, str) or not query.strip() or limit < 1 or limit > 100:
            raise RetrieverError("invalid retrieval query")
        required = set(required_evidence)
        values = [doc for doc in self.documents if doc.org_id == str(org_id) and required.issubset(doc.evidence_refs)]
        return tuple(sorted(values, key=lambda doc: (-doc.score, doc.id))[:limit])


__all__ = ["InMemoryRetriever", "RetrievedDocument", "RetrieverError", "RetrieverPort"]
