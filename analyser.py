"""
TopicTracker Step 2 — Content Analyser.

Reads the CSV produced by Step 1 and computes:
  - keyword trends (raw + normalized)
  - MeSH term trends
  - author trends
  - lemma trends (spaCy NLP on title + abstract)
  - COI statement trends
  - journal trends

For each entity type: per-year counts, normalized counts, descriptive stats,
top-5 SVG line plot, word cloud SVG.

Also runs Step 4 (semantic network tables) as part of the same job —
co-occurrence matrix for keywords.

Writes everything under export_dir/data/ and export_dir/plots/.
Updates ANALYSIS_JOBS dict (same pattern as pipeline.JOBS).
"""
import ast
import threading
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ANALYSIS_JOBS: dict[int, dict] = {}
_lock = threading.Lock()


def get_analysis_job(run_id: int) -> dict | None:
    with _lock:
        return ANALYSIS_JOBS.get(run_id)


def _set(run_id: int, data: dict):
    with _lock:
        ANALYSIS_JOBS[run_id] = data


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_list_col(val) -> list[str]:
    """Parse a column value that may be a Python-repr list string or empty."""
    if not val or (isinstance(val, float)):
        return []
    if isinstance(val, list):
        return [str(x).strip().lower() for x in val if x]
    s = str(val).strip()
    if s.startswith("["):
        try:
            return [str(x).strip().lower() for x in ast.literal_eval(s) if x]
        except Exception:
            pass
    return [x.strip().lower() for x in s.split(",") if x.strip()]


def _count_per_year(df: pd.DataFrame, col: str, years: list[int]) -> pd.DataFrame:
    """Count occurrences of each entity value per year."""
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for _, row in df.iterrows():
        year = row["Year"]
        if year not in years:
            continue
        items = _parse_list_col(row[col])
        for item in items:
            if item:
                counts[item][year] += 1
    records = []
    for entity, year_counts in counts.items():
        row_data = {"entity": entity}
        for y in years:
            row_data[str(y)] = year_counts.get(y, 0)
        records.append(row_data)
    return pd.DataFrame(records).fillna(0)


def _normalize(counts_df: pd.DataFrame, papers_per_year: dict[int, int]) -> pd.DataFrame:
    norm = counts_df.copy()
    for col in norm.columns:
        if col == "entity":
            continue
        year = int(col)
        denom = papers_per_year.get(year, 1)
        norm[col] = norm[col] / denom * 100
    return norm


def _add_stats(df: pd.DataFrame) -> pd.DataFrame:
    year_cols = [c for c in df.columns if c != "entity"]
    vals = df[year_cols]
    df = df.copy()
    df["total"] = vals.sum(axis=1)
    df["mean"]  = vals.mean(axis=1).round(3)
    df["std"]   = vals.std(axis=1).round(3)
    df["min"]   = vals.min(axis=1)
    df["max"]   = vals.max(axis=1)
    return df.sort_values("total", ascending=False).reset_index(drop=True)


def _plot_top5(counts_df: pd.DataFrame, years: list[int], title: str, ylabel: str) -> bytes:
    top5 = counts_df.head(5)
    fig, ax = plt.subplots(figsize=(10, 5))
    year_cols = [str(y) for y in years]
    for _, row in top5.iterrows():
        ax.plot(years, row[year_cols].values, marker="o", label=row["entity"])
    ax.set_title(title)
    ax.set_xlabel("Year")
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    return buf.getvalue()


def _wordcloud_svg(counts_df: pd.DataFrame) -> bytes | None:
    try:
        from wordcloud import WordCloud
    except ImportError:
        return None
    freq = dict(zip(counts_df["entity"], counts_df["total"]))
    if not freq:
        return None
    wc = WordCloud(width=800, height=400, background_color="white").generate_from_frequencies(freq)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    return buf.getvalue()


def _save(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _analyse_entity(df: pd.DataFrame, col: str, years: list[int],
                    papers_per_year: dict[int, int], data_dir: Path, plots_dir: Path,
                    label: str):
    counts = _count_per_year(df, col, years)
    if counts.empty:
        return
    norm   = _normalize(counts, papers_per_year)
    counts = _add_stats(counts)
    norm   = _add_stats(norm)

    counts.to_csv(data_dir / f"{label}.csv", index=False)
    norm.to_csv(data_dir / f"{label}_norm.csv", index=False)

    svg = _plot_top5(counts, years, f"Top 5 {label} — raw count", "Count")
    _save(plots_dir / f"{label}.svg", svg)
    svg_n = _plot_top5(norm, years, f"Top 5 {label} — normalized (%)", "% of papers")
    _save(plots_dir / f"{label}_norm.svg", svg_n)

    wc = _wordcloud_svg(counts)
    if wc:
        _save(plots_dir / f"wordcloud_{label}.svg", wc)


def _analyse_lemmas(df: pd.DataFrame, years: list[int],
                    papers_per_year: dict[int, int], data_dir: Path, plots_dir: Path):
    try:
        import spacy
        nlp = spacy.load("en_core_web_md", disable=["tagger", "parser"])
    except Exception:
        return  # skip gracefully if spaCy not installed

    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for _, row in df.iterrows():
        year = row["Year"]
        if year not in years:
            continue
        text = " ".join([str(row.get("Title", "") or ""), str(row.get("Abstract", "") or "")])
        doc = nlp(text)
        for token in doc:
            if token.is_alpha and not token.is_stop and len(token.lemma_) > 2:
                counts[token.lemma_.lower()][year] += 1

    records = []
    for entity, year_counts in counts.items():
        row_data = {"entity": entity}
        for y in years:
            row_data[str(y)] = year_counts.get(y, 0)
        records.append(row_data)

    ldf = pd.DataFrame(records).fillna(0)
    if ldf.empty:
        return

    norm = _normalize(ldf, papers_per_year)
    ldf  = _add_stats(ldf)
    norm = _add_stats(norm)

    ldf.to_csv(data_dir / "Lemmas.csv", index=False)
    norm.to_csv(data_dir / "Lemmas_norm.csv", index=False)

    svg = _plot_top5(ldf, years, "Top 5 lemmas — raw count", "Count")
    _save(plots_dir / "Lemmas.svg", svg)
    svg_n = _plot_top5(norm, years, "Top 5 lemmas — normalized (freq/paper)", "Freq/paper")
    _save(plots_dir / "Lemmas_norm.svg", svg_n)

    wc = _wordcloud_svg(ldf)
    if wc:
        _save(plots_dir / "wordcloud_Lemmas.svg", wc)


def _build_network(df: pd.DataFrame, top_n: int, gephi_dir: Path):
    """Step 4: keyword co-occurrence tables for Gephi."""
    all_kw: Counter = Counter()
    for val in df["Keywords"]:
        for kw in _parse_list_col(val):
            all_kw[kw] += 1

    top_kw = {kw for kw, _ in all_kw.most_common(top_n)}

    node_records = [{"Id": kw, "Label": kw, "Count": all_kw[kw],
                     "Weight": all_kw[kw] / max(all_kw.values())}
                    for kw in top_kw]
    nodes_df = pd.DataFrame(node_records)
    nodes_df.to_csv(gephi_dir / "nodes_df.csv", index=False)

    co: dict[tuple[str, str], int] = Counter()
    for val in df["Keywords"]:
        kws = [k for k in _parse_list_col(val) if k in top_kw]
        for i in range(len(kws)):
            for j in range(i + 1, len(kws)):
                pair = tuple(sorted([kws[i], kws[j]]))
                co[pair] += 1  # type: ignore[index]

    max_co = max(co.values()) if co else 1
    edge_records = [{"Source": s, "Target": t, "Count": c,
                     "Weight": c / max_co,
                     "Jaccard": c / (all_kw[s] + all_kw[t] - c)}
                    for (s, t), c in co.items()]
    edges_df = pd.DataFrame(edge_records)
    edges_df.to_csv(gephi_dir / "edges_df.csv", index=False)

    # Adjacency matrix
    kw_list = sorted(top_kw)
    matrix = pd.DataFrame(0, index=kw_list, columns=kw_list)
    for (s, t), c in co.items():
        matrix.loc[s, t] = c
        matrix.loc[t, s] = c
    matrix.to_csv(gephi_dir / "matrix_df.csv")


# ── Main job ─────────────────────────────────────────────────────────────────

def run_analysis_job(run_id: int, export_dir: Path, top_n_network: int = 300):
    _set(run_id, {"status": "analysing", "message": "Loading dataset…", "step": 0, "steps": 7})
    try:
        csv_path = export_dir / "PubMed full records.csv"
        df = pd.read_csv(csv_path, sep=";", low_memory=False)
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce").dropna()
        df = df.dropna(subset=["Year"])
        df["Year"] = df["Year"].astype(int)

        years = sorted(df["Year"].unique().tolist())
        papers_per_year = df.groupby("Year").size().to_dict()

        data_dir  = export_dir / "data"
        plots_dir = export_dir / "plots"
        gephi_dir = export_dir / "gephi tables"
        for d in [data_dir, plots_dir, gephi_dir]:
            d.mkdir(parents=True, exist_ok=True)

        steps = [
            ("Keywords",  lambda: _analyse_entity(df, "Keywords",  years, papers_per_year, data_dir, plots_dir, "Keywords")),
            ("MeSH terms", lambda: _analyse_entity(df, "MeSH Terms", years, papers_per_year, data_dir, plots_dir, "Meshterms")),
            ("Authors",   lambda: _analyse_entity(df, "Authors",   years, papers_per_year, data_dir, plots_dir, "Authors")),
            ("Journals",  lambda: _analyse_entity(df, "Journal",   years, papers_per_year, data_dir, plots_dir, "Journal")),
            ("Lemmas (NLP)", lambda: _analyse_lemmas(df, years, papers_per_year, data_dir, plots_dir)),
            ("Semantic network", lambda: _build_network(df, top_n_network, gephi_dir)),
        ]

        for i, (label, fn) in enumerate(steps):
            _set(run_id, {"status": "analysing", "message": f"Analysing {label}…", "step": i, "steps": len(steps)})
            fn()

        _set(run_id, {"status": "done", "message": "Analysis complete.", "step": len(steps), "steps": len(steps)})

    except Exception as exc:
        _set(run_id, {"status": "error", "message": str(exc), "error": str(exc)})


def start_analysis(run_id: int, export_dir: Path, top_n_network: int = 300):
    t = threading.Thread(
        target=run_analysis_job,
        args=(run_id, export_dir, top_n_network),
        daemon=True,
    )
    t.start()
