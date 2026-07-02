<p align="center">
  <b>Systematic literature analysis for PubMed — search to semantic network.</b><br>
  No coding required.
</p>

---

TopicTracker is a self-hosted web app for systematic PubMed literature analysis. It's the
web evolution of the pipeline described in:

> Spitale G, Germani A, Biller-Andorno N. *TopicTracker: A workflow for topic modelling and
> semantic network analysis of biomedical literature.* Heliyon. 2024.
> [Read the paper ↗](https://pmc.ncbi.nlm.nih.gov/articles/PMC11399583/)

<p align="center">
  <a href="LICENSE"><img alt="License: AGPL v3" src="https://img.shields.io/badge/License-AGPLv3-blue.svg"></a>
</p>

The original pipeline ran across four sequential Jupyter notebooks and required a local
Python/spaCy setup. This app moves the heavy computation server-side, runs jobs in the
background, and gives collaborators a no-setup interface. Multi-user with login; each run
goes through four steps.

## Pipeline

1. **Search & download** — queries PubMed year by year (works around the 100k-result API
   cap), downloads MEDLINE records at the NCBI-mandated pace, and assembles a structured
   CSV. Runs in the background — come back later.
2. **Content analysis** — trends for Keywords, MeSH Terms, Authors, Journals, COI statements,
   and lemmatized title/abstract text (spaCy). Raw + normalized counts, top-5 trend plots,
   word clouds.
3. **Interactive visualization** — on-demand Bokeh charts: pick any entities, compare their
   trajectories, toggle normalization.
4. **Semantic network** — keyword co-occurrence network (Jaccard or raw weight, community
   detection), exportable as node/edge/matrix CSVs for [Gephi](https://gephi.org/).

See **[guide.md](guide.md)** for the full user guide (query syntax, reading the outputs,
tips for a good analysis).

## Quick start

```bash
git clone https://github.com/that-ugly-cat/topictracker.git
cd topictracker
pip install -r requirements.txt
python -m spacy download en_core_web_md   # optional — lemma analysis needs it
cp .env.example .env                       # set JWT_SECRET
uvicorn main:app --reload
python seed_admin.py you@example.com yourpassword "Your Name"
```

Open http://localhost:8000/login.

## Stack

FastAPI · SQLite (SQLAlchemy) · Jinja2 · Bokeh · spaCy (`en_core_web_md`, optional — lemma
analysis is skipped if not installed) · matplotlib · wordcloud.

```
main.py         — all FastAPI routes
auth.py         — JWT, get_current_user, require_admin
models.py       — User + Run (SQLite)
pipeline.py     — step 1: search/download in a background thread
analyser.py     — step 2 (content analysis) + step 4 (semantic networks)
visualizer.py   — step 3: Bokeh embed on demand via AJAX
seed_admin.py   — creates the first admin user
templates/      — login, index, new, run, admin
```

Background jobs use a plain thread + in-memory dict (no Celery/Redis) — fine for
low-traffic academic use, polled via AJAX every 2s from the run page.

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for production setup.

## Relation to the published pipeline

This app is not a new version of the scientific method — it's an access layer over the same
notebook pipeline (`PubGetParse.py` and downstream analysis), rebuilt in `pipeline.py` and
`analyser.py`. The methodology is the one described in the Heliyon paper above.

## Tech notes

- Set `JWT_SECRET` in production — the app refuses to start without it.
- Each run's outputs (CSVs, plots) live under `data/` and `export/` — back those up like any
  other file storage.

## License

Copyright (C) 2026 Giovanni Spitale. Licensed under AGPL-3.0 — fork it, host it, sell access
to it, but keep it closed-source and you're in violation. No SaaS forks that don't share
back. See [LICENSE](LICENSE).
