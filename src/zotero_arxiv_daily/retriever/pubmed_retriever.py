"""PubMed retrieval for both recent developments and historical backfill."""

from __future__ import annotations

from datetime import date, timedelta
import xml.etree.ElementTree as ET
from time import sleep
from typing import Any

import requests
from loguru import logger

from .base import BaseRetriever, register_retriever
from ..protocol import Paper


@register_retriever("pubmed")
class PubmedRetriever(BaseRetriever):
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    request_headers = {"User-Agent": "zotero-arxiv-daily/1.0 (PubMed digest)"}

    def _request(self, url: str, params: dict[str, Any]) -> requests.Response:
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, headers=self.request_headers, timeout=60)
                response.raise_for_status()
                return response
            except Exception as exc:
                if attempt == 2:
                    raise
                logger.warning(f"PubMed request failed: {exc}. Retrying in 5 seconds.")
                sleep(5)
        raise RuntimeError("unreachable")

    def _base_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"db": "pubmed", "tool": "zotero_arxiv_daily"}
        api_key = getattr(self.retriever_config, "api_key", None)
        if api_key:
            params["api_key"] = api_key
        return params

    def _search(self, *, channel: str, date_params: dict[str, str], sort: str) -> list[dict[str, str]]:
        params = {
            **self._base_params(),
            "term": self.retriever_config.query,
            "retmode": "json",
            "retmax": int(self.retriever_config.candidate_limit),
            "sort": sort,
            **date_params,
        }
        result = self._request(self.search_url, params).json().get("esearchresult", {})
        pmids = result.get("idlist", [])
        if not pmids:
            logger.info(f"No PubMed {channel} candidates found.")
            return []
        fetch_params = {**self._base_params(), "id": ",".join(pmids), "retmode": "xml"}
        root = ET.fromstring(self._request(self.fetch_url, fetch_params).content)
        papers = []
        for article in root.findall("./PubmedArticle"):
            paper = self._parse_article(article)
            if paper:
                paper["channel"] = channel
                papers.append(paper)
        return papers

    @staticmethod
    def _text(element: ET.Element | None) -> str:
        return " ".join(element.itertext()).strip() if element is not None else ""

    def _parse_article(self, article: ET.Element) -> dict[str, str] | None:
        medline = article.find("./MedlineCitation")
        article_data = medline.find("./Article") if medline is not None else None
        pmid = self._text(medline.find("./PMID") if medline is not None else None)
        title = self._text(article_data.find("./ArticleTitle") if article_data is not None else None)
        if not pmid or not title:
            return None
        abstract_parts = [self._text(node) for node in article_data.findall("./Abstract/AbstractText")] if article_data is not None else []
        authors = []
        for author in article_data.findall("./AuthorList/Author") if article_data is not None else []:
            name = self._text(author.find("./CollectiveName")) or " ".join(
                part for part in (self._text(author.find("./ForeName")), self._text(author.find("./LastName"))) if part
            )
            if name:
                authors.append(name)
        doi = ""
        for identifier in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            if identifier.attrib.get("IdType") == "doi":
                doi = self._text(identifier)
                break
        return {"pmid": pmid, "doi": doi, "title": title, "authors": authors, "abstract": " ".join(abstract_parts)}

    def _retrieve_raw_papers(self) -> list[dict[str, str]]:
        recent_days = int(self.retriever_config.recent_days)
        historical_years = int(self.retriever_config.historical_years)
        today = date.today()
        try:
            historical_start = today.replace(year=today.year - historical_years)
        except ValueError:  # February 29 in a non-leap historical year
            historical_start = today - timedelta(days=365 * historical_years)
        historical_end = today - timedelta(days=recent_days)
        recent = self._search(
            channel="recent",
            date_params={"datetype": "pdat", "reldate": str(recent_days)},
            sort="pub_date",
        )
        historical = self._search(
            channel="historical",
            date_params={
                "datetype": "pdat",
                "mindate": historical_start.isoformat(),
                "maxdate": historical_end.isoformat(),
            },
            sort="relevance",
        )
        return recent + historical

    def convert_to_paper(self, raw_paper: dict[str, str]) -> Paper | None:
        pmid = raw_paper["pmid"]
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        return Paper(
            source=self.name,
            title=raw_paper["title"],
            authors=raw_paper["authors"],
            abstract=raw_paper["abstract"],
            url=url,
            pdf_url=url,
            doi=raw_paper.get("doi") or None,
            pmid=pmid,
            channel=raw_paper["channel"],
        )
