"""Cross-source de-duplication and persistent sent-paper state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .protocol import Paper

_TITLE_TOKEN = re.compile(r"[a-z0-9]+")
_SOURCE_PRIORITY = {"pubmed": 0, "chemrxiv": 1, "biorxiv": 2, "medrxiv": 3, "arxiv": 4}


def _normalize_doi(doi: str) -> str:
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def _normalize_title(title: str) -> str:
    return " ".join(_TITLE_TOKEN.findall(title.lower()))


def paper_identifiers(paper: Paper) -> set[str]:
    """Return stable IDs, using title only when no DOI or PMID is available."""
    identifiers = set()
    if paper.doi:
        identifiers.add(f"doi:{_normalize_doi(paper.doi)}")
    if paper.pmid:
        identifiers.add(f"pmid:{paper.pmid.strip()}")
    if not identifiers and paper.title:
        identifiers.add(f"title:{_normalize_title(paper.title)}")
    return identifiers


def deduplicate_papers(papers: list[Paper]) -> list[Paper]:
    """De-duplicate candidates, preferring the published PubMed record."""
    selected: list[Paper] = []
    index_by_identifier: dict[str, int] = {}
    for paper in papers:
        identifiers = paper_identifiers(paper)
        conflicts = {index_by_identifier[key] for key in identifiers if key in index_by_identifier}
        if not conflicts:
            selected.append(paper)
            index = len(selected) - 1
        else:
            index = min(conflicts)
            existing = selected[index]
            if _SOURCE_PRIORITY.get(paper.source, 99) < _SOURCE_PRIORITY.get(existing.source, 99):
                selected[index] = paper
        for key in paper_identifiers(selected[index]):
            index_by_identifier[key] = index
    return selected


class SentPaperStore:
    """A small, repository-tracked record of papers successfully emailed."""

    def __init__(self, path: str | Path, max_records: int = 2000):
        self.path = Path(path)
        self.max_records = max_records
        self.records = self._load()

    def _load(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = data.get("papers", [])
            return records if isinstance(records, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    @property
    def seen_identifiers(self) -> set[str]:
        return {
            identifier
            for record in self.records
            for identifier in record.get("identifiers", [])
            if isinstance(identifier, str)
        }

    def has_seen(self, paper: Paper) -> bool:
        return bool(paper_identifiers(paper) & self.seen_identifiers)

    def record(self, papers: list[Paper]) -> None:
        existing = self.seen_identifiers
        now = datetime.now(timezone.utc).isoformat()
        for paper in papers:
            identifiers = sorted(paper_identifiers(paper))
            if not identifiers or set(identifiers) & existing:
                continue
            self.records.append({"identifiers": identifiers, "sent_at": now})
            existing.update(identifiers)
        self.records = self.records[-self.max_records :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "papers": self.records}
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self.path)
