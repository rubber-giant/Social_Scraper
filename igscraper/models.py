"""Data structures for multi-strategy discovery.

A :class:`Candidate` accumulates every way an account was surfaced (its
``sources``) so the pipeline can rank/truncate by provenance and show the
user *why* an account was found.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class Source:
    """One discovery surface that produced a candidate.

    strategy: hashtag | keyword | chaining
    ref:      what was queried (a tag, a search query, or "@seedaccount")
    weight:   provenance priority (higher survives the per-niche cap first)
    """

    strategy: str
    ref: str
    weight: float = 1.0

    @property
    def label(self) -> str:
        if self.strategy == "hashtag":
            return f"#{self.ref}"
        if self.strategy == "keyword":
            return f"search: '{self.ref}'"
        if self.strategy == "chaining":
            seed = self.ref if self.ref.startswith("@") else f"@{self.ref}"
            return f"similar to {seed}"
        return f"{self.strategy}: {self.ref}"


@dataclass
class Candidate:
    username: str
    pk: Optional[str] = None
    sources: List[Source] = field(default_factory=list)
    niches: Set[str] = field(default_factory=set)

    def add_source(self, src: Source) -> None:
        # De-duplicate identical (strategy, ref) pairs.
        if not any(s.strategy == src.strategy and s.ref == src.ref for s in self.sources):
            self.sources.append(src)

    @property
    def weight(self) -> float:
        """Strongest provenance weight (max), used to rank within a niche cap."""
        return max((s.weight for s in self.sources), default=0.0)

    @property
    def primary_source(self) -> Optional[Source]:
        return max(self.sources, key=lambda s: s.weight) if self.sources else None


@dataclass
class DiscoveryResult:
    candidates: Dict[str, Candidate] = field(default_factory=dict)
    authors_by_niche: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def provenance(self) -> Dict[str, List[Source]]:
        return {u: c.sources for u, c in self.candidates.items()}

    def to_legacy(
        self,
    ) -> Tuple[Dict[str, List[str]], Dict[str, Set[str]], Dict[str, str]]:
        """Re-emit the old (authors_by_niche, niches_by_author, found_tag) tuple.

        ``found_tag_by_author`` only carries hashtag provenance (the old column
        shape); non-hashtag candidates get an empty string.
        """
        niches_by_author: Dict[str, Set[str]] = {
            u: set(c.niches) for u, c in self.candidates.items()
        }
        found_tag_by_author: Dict[str, str] = {}
        for u, c in self.candidates.items():
            for s in c.sources:
                if s.strategy == "hashtag":
                    found_tag_by_author[u] = s.ref
                    break
        return self.authors_by_niche, niches_by_author, found_tag_by_author
