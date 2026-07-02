"""
TopicTracker Step 1 — Search & Download.

Runs in a background thread. Progress tracked via the global JOBS dict,
keyed by run_id. main.py reads JOBS for status polling.

Job dict structure:
  status:      'searching' | 'downloading' | 'done' | 'error'
  message:     human-readable status string
  total:       total papers found (set after search)
  downloaded:  papers downloaded so far
  paper_count: final filtered paper count (set on success)
  error:       error message (set on failure)
"""
import ast
import time
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import urllib3

http = urllib3.PoolManager()

RATE_LIMIT = 0.6  # seconds between NCBI requests (policy)

JOBS: dict[int, dict] = {}
_lock = threading.Lock()


def get_job(run_id: int) -> dict | None:
    with _lock:
        return JOBS.get(run_id)


def _set_job(run_id: int, data: dict):
    with _lock:
        JOBS[run_id] = data


# ── NCBI helpers ──────────────────────────────────────────────────────────────

def _get_pmids(query: str) -> list[str]:
    import xml.etree.ElementTree as ET
    from urllib.parse import quote_plus
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax=100000&term={quote_plus(query)}"
    content = http.request("GET", url).data.decode("utf-8")
    root = ET.fromstring(content)
    return [x.text for x in root.findall("IdList/Id")]


def _fetch_medline(pmid: str) -> str:
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&rettype=medline&id={pmid}"
    return http.request("GET", url).data.decode("utf-8")


def _parse_medline(article: str, pmid: str) -> list:
    import re

    newlines = re.compile(r"\n\s{2,}", re.MULTILINE)
    article = re.sub(newlines, " ", article)

    def _find(pattern):
        m = re.search(pattern, article)
        return m.group(0).strip() if m else ""

    def _findall(pattern):
        return [x.strip() for x in re.findall(re.compile(pattern), article)]

    pid_type_raw = _findall(r"(?<=PT\s\s-\s).*")
    if "Book Chapter" in pid_type_raw or "book chapter" in pid_type_raw:
        pid_type = "Book chapter"
    elif "Book" in pid_type_raw or "book" in pid_type_raw:
        pid_type = "Book"
    else:
        pid_type = "Article"

    year = _find(r"(?<=DP\s\s-\s)\d{4}")
    journal   = _find(r"(?<=JT\s\s-\s).*")
    publisher = _find(r"(?<=PB\s\s-\s).*")
    title     = _find(r"(?<=TI\s\s-\s).*")
    book_title = _find(r"(?<=BTI\s-\s).*")
    abstract  = _find(r"(?<=AB\s\s-\s).*")
    oabstract = _find(r"(?<=OAB\s-\s).*")
    authors   = ", ".join(_findall(r"(?<=AU\s\s-\s).*"))
    editors   = ", ".join(_findall(r"(?<=ED\s\s-\s).*"))
    language  = _find(r"(?<=LA\s\s-\s).*")
    meshterms = _findall(r"(?<=MH\s\s-\s).*")
    keywords  = _findall(r"(?<=OT\s\s-\s).*")
    coi       = _find(r"(?<=COIS-\s).*")
    doi       = _find(r"(?<=AID\s-\s).*(?=\s\[doi)")
    grant     = _find(r"(?<=GR\s\s-\s).*")

    return [pmid, pid_type, year, journal, publisher, title, book_title,
            abstract, oabstract, authors, editors, language,
            meshterms, keywords, coi, grant, doi]


COLUMNS = ["PMID", "Type", "Year", "Journal", "Publisher", "Title", "Book Title",
           "Abstract", "Other Abstract", "Authors", "Editors", "Language",
           "MeSH Terms", "Keywords", "COI", "Grant", "DOI"]


# ── Main job ─────────────────────────────────────────────────────────────────

def run_download_job(run_id: int, query: str, year_from: int, year_to: int, export_dir: Path):
    """Entry point called in a background thread."""
    _set_job(run_id, {"status": "searching", "message": "Searching PubMed…", "total": 0, "downloaded": 0})

    try:
        # Search per year to stay under the 100k-per-query NCBI limit
        all_ids: list[str] = []
        for year in range(year_from, year_to + 1):
            year_query = f"{query} AND {year}[pdat]"
            ids = _get_pmids(year_query)
            all_ids.extend(ids)
            time.sleep(RATE_LIMIT)

        # Deduplicate, preserving order
        all_ids = list(dict.fromkeys(all_ids))
        total = len(all_ids)

        _set_job(run_id, {
            "status": "downloading",
            "message": f"Found {total} papers. Downloading…",
            "total": total,
            "downloaded": 0,
        })

        rows = []
        medline_path = export_dir / "medline.txt"

        for i, pmid in enumerate(all_ids):
            try:
                raw = _fetch_medline(pmid)
                row = _parse_medline(raw, pmid)
                rows.append(row)
                with open(medline_path, "a", encoding="utf-8") as f:
                    f.write(raw + "\n")
            except Exception:
                pass
            with _lock:
                JOBS[run_id]["downloaded"] = i + 1
            time.sleep(RATE_LIMIT)

        # Build DataFrame and filter to requested year range
        df = pd.DataFrame(rows, columns=COLUMNS)
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df = df.dropna(subset=["Year"])
        df["Year"] = df["Year"].astype(int)
        df = df[(df["Year"] >= year_from) & (df["Year"] <= year_to)].reset_index(drop=True)

        df.to_csv(export_dir / "PubMed full records.csv", sep=";", index=False)

        paper_count = len(df)
        (export_dir / "log.txt").write_text(
            f"Query: {query}\nYears: {year_from}-{year_to}\n"
            f"Found (pre-filter): {total}\nFinal: {paper_count}\n"
            f"Date: {datetime.now().isoformat()}\n",
            encoding="utf-8",
        )

        _set_job(run_id, {
            "status": "done",
            "message": f"Download complete. {paper_count} papers.",
            "total": total,
            "downloaded": total,
            "paper_count": paper_count,
        })

    except Exception as exc:
        _set_job(run_id, {
            "status": "error",
            "message": str(exc),
            "total": 0,
            "downloaded": 0,
            "error": str(exc),
        })


def start_download(run_id: int, query: str, year_from: int, year_to: int, export_dir: Path):
    t = threading.Thread(
        target=run_download_job,
        args=(run_id, query, year_from, year_to, export_dir),
        daemon=True,
    )
    t.start()
