from datetime import date
from types import SimpleNamespace

from omegaconf import open_dict

from zotero_arxiv_daily.retriever import get_retriever_cls
from zotero_arxiv_daily.retriever.pubmed_retriever import PubmedRetriever


_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation><PMID>123456</PMID><Article>
      <ArticleTitle>Untargeted LC-MS metabolomics annotation</ArticleTitle>
      <Abstract><AbstractText>Metabolite annotation study.</AbstractText></Abstract>
      <AuthorList><Author><ForeName>Jane</ForeName><LastName>Doe</LastName></Author></AuthorList>
    </Article></MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/example</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>'''


def _configure(config):
    with open_dict(config.source):
        config.source.pubmed = {
            "query": "untargeted metabolomics",
            "recent_days": 7,
            "historical_years": 5,
            "candidate_limit": 10,
            "api_key": None,
        }
    return PubmedRetriever(config)


def test_pubmed_is_registered():
    assert get_retriever_cls("pubmed") is PubmedRetriever


def test_pubmed_retrieves_recent_and_historical_channels(config, monkeypatch):
    calls = []

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 8)

    def fake_get(url, **kwargs):
        params = kwargs["params"]
        calls.append((url, params))
        if "esearch" in url:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"esearchresult": {"idlist": ["123456"]}},
            )
        return SimpleNamespace(raise_for_status=lambda: None, content=_XML)

    monkeypatch.setattr("zotero_arxiv_daily.retriever.pubmed_retriever.date", FixedDate)
    monkeypatch.setattr("zotero_arxiv_daily.retriever.pubmed_retriever.requests.get", fake_get)
    monkeypatch.setattr("zotero_arxiv_daily.retriever.base.sleep", lambda _: None)
    papers = _configure(config).retrieve_papers()

    assert [paper.channel for paper in papers] == ["recent", "historical"]
    assert papers[0].pmid == "123456"
    assert papers[0].doi == "10.1000/example"
    assert papers[0].pdf_url == "https://pubmed.ncbi.nlm.nih.gov/123456/"
    searches = [params for url, params in calls if "esearch" in url]
    assert searches[0]["reldate"] == "7"
    assert searches[0]["sort"] == "pub_date"
    assert searches[1]["mindate"] == "2021-03-08"
    assert searches[1]["maxdate"] == "2026-03-01"
    assert searches[1]["sort"] == "relevance"
