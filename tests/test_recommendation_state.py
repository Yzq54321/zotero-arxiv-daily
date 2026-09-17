from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.recommendation_state import SentPaperStore, deduplicate_papers


def _paper(**overrides):
    defaults = {
        "source": "pubmed",
        "title": "An untargeted metabolomics paper",
        "authors": ["A Author"],
        "abstract": "Abstract",
        "url": "https://example.org",
        "doi": None,
        "pmid": None,
    }
    defaults.update(overrides)
    return Paper(**defaults)


def test_deduplicate_prefers_pubmed_for_the_same_doi():
    preprint = _paper(source="chemrxiv", doi="10.1000/example", title="Preprint title")
    published = _paper(source="pubmed", doi="https://doi.org/10.1000/EXAMPLE", title="Published title", pmid="123")
    papers = deduplicate_papers([preprint, published])
    assert papers == [published]


def test_sent_state_persists_and_filters_by_doi_or_title_fallback(tmp_path):
    state_path = tmp_path / "sent_papers.json"
    sent = _paper(doi="10.1000/example", pmid="123")
    store = SentPaperStore(state_path)
    store.record([sent])
    reloaded = SentPaperStore(state_path)
    assert reloaded.has_seen(_paper(doi="10.1000/EXAMPLE", title="Different title"))
    title_only = _paper(title="Title without identifiers")
    SentPaperStore(state_path).record([title_only])
    assert SentPaperStore(state_path).has_seen(_paper(title="Title without identifiers"))
