# TopicTracker — User Guide

TopicTracker is a web interface for systematic literature analysis on PubMed. It automates the full pipeline from search to semantic network — no coding required.

It is the web evolution of the tool described in:

> Spitale G, Germani A, Biller-Andorno N. *TopicTracker: A workflow for topic modelling and semantic network analysis of biomedical literature.* Heliyon. 2024. [Read the paper ↗](https://pmc.ncbi.nlm.nih.gov/articles/PMC11399583/)

The original pipeline ran across four sequential Jupyter notebooks. This interface wraps the same logic in a single web app — one run, four steps, exportable at every stage.

---

## Before you start: building a good query

TopicTracker uses standard **PubMed query syntax**. Getting the query right is the most important step — everything downstream depends on it.

**Always test your query on PubMed first:**
1. Go to [PubMed](https://pubmed.ncbi.nlm.nih.gov/)
2. Paste your query and run the search
3. Check the number of results and scan the top records — do they match what you expect?
4. Only then paste the query into TopicTracker

This lets you validate the syntax and get a sense of the corpus size before launching a download that may take hours.

### Useful syntax elements

| Syntax | Meaning | Example |
|--------|---------|---------|
| `[tiab]` | Search in title and abstract | `cancer[tiab]` |
| `[mh]` | Search MeSH terms | `"Neoplasms"[mh]` |
| `AND`, `OR`, `NOT` | Boolean operators | `cancer[tiab] AND screening[tiab]` |
| `"..."` | Exact phrase | `"informed consent"[tiab]` |
| `[pdat]` | Publication date filter | `2020:2024[pdat]` |

**Tips:**
- MeSH terms (`[mh]`) are more precise than free-text but may miss very recent papers not yet indexed.
- Combine both for broader coverage: `"informed consent"[tiab] OR "informed consent"[mh]`.
- The year range you set in the form will filter results — you don't need to add `[pdat]` to your query.
- Very broad queries (tens of thousands of results) will take significantly longer to download. A query returning 5,000–20,000 papers is a comfortable size for analysis.

**Resources:**
- [PubMed query syntax — official guide](https://pubmed.ncbi.nlm.nih.gov/help/#search-tags)
- [MeSH Browser (term search + tree)](https://meshb.nlm.nih.gov/treeView)

---

## Step 1 — Search & Download

TopicTracker queries PubMed automatically, one year at a time. This workaround is necessary because PubMed's API caps results at 100,000 per request — segmenting by year ensures complete coverage.

**What happens:**
- The query is sent to PubMed for each year in your range
- MEDLINE records are downloaded one by one (PubMed policy requires a pause between requests — expect roughly 0.6 seconds per paper)
- Records are parsed and assembled into a structured CSV

**Output files:**
- `PubMed full records.csv` — the main dataset (semicolon-separated); one row per paper with title, abstract, authors, journal, year, keywords, MeSH terms
- `medline.txt` — raw MEDLINE format, importable into reference managers (Zotero, Mendeley, EndNote)
- `log.txt` — download log with counts per year

**How long does it take?**
It depends on corpus size. Roughly: 1,000 papers ≈ 10 minutes; 10,000 papers ≈ 1.5 hours; 50,000 papers ≈ 8 hours. You can close the browser — the download runs on the server. Come back later and refresh the page.

---

## Step 2 — Content Analysis

Once the download is complete, Step 2 analyses the corpus and generates trend data for six entity types.

### Entity categories

| Category | What it tracks |
|----------|---------------|
| **Keywords** | Author-assigned keywords |
| **MeSH Terms** | Controlled vocabulary assigned by NLM indexers |
| **Authors** | Publication counts per author per year |
| **Journals** | Publication counts per journal per year |
| **TiAb Lemmas** | Lemmatized content from titles and abstracts (NLP via spaCy) |

**Keywords vs MeSH Terms:** Keywords are assigned by authors and vary in phrasing; MeSH terms are standardised. Use MeSH for cleaner trend analysis; use keywords to capture emerging terminology not yet in the controlled vocabulary.

**TiAb Lemmas** extract the most frequent meaningful words from titles and abstracts after lemmatization (reducing words to their base form). This reveals conceptual trends even when authors don't use consistent keywords.

### Raw vs Normalized

- **Raw count**: how many times an entity appears per year — affected by the overall growth of publications in a field.
- **Normalized (%)**: entity count divided by total papers that year × 100. Use this to compare trends across years when the corpus grows over time.

When in doubt, use normalized.

### Outputs

For each category: raw CSV, normalized CSV, top-5 trend plot (SVG), word cloud (SVG). Click any plot to enlarge it; use the download buttons for CSV or XLSX.

---

## Step 3 — Interactive Visualization

Step 3 lets you build custom interactive charts for any entity in your dataset.

**How to use:**
1. Select a category (Keywords, MeSH Terms, Authors, Journals, TiAb Lemmas)
2. The entity list loads automatically — type to filter
3. Select one or more entities (up to 10 lines on the same chart)
4. Toggle **Normalized** on or off
5. Click **Generate plot**

The Bokeh chart is interactive: zoom, pan, and click legend entries to show/hide individual lines. Use it to compare the trajectory of specific terms or authors over time.

---

## Step 4 — Semantic Network

Step 4 maps how keywords co-occur — which terms tend to appear together in the same papers. This reveals thematic clusters and relationships that trend analysis alone cannot show.

### Controls

- **Top N keywords**: how many keywords to include as nodes. Start with 50–100 for a readable network; increase for a more complete picture.
- **Edge weight**: how co-occurrence strength is measured.
  - *Jaccard similarity*: `co-occurrences / (papers with A + papers with B − co-occurrences)`. Recommended — corrects for the fact that very frequent terms would otherwise dominate all edges.
  - *Raw co-occurrence*: absolute number of papers where both terms appear together.
- **Min weight**: filters out weak edges. Increase it to reduce clutter and highlight only the strongest connections.
- **Layout**: *Force-directed* positions nodes so strongly connected ones cluster together; *Circular* is cleaner for counting but less informative for structure.

### Reading the network

- **Node size** = total frequency of that keyword in the corpus.
- **Node colour** = community (cluster detected automatically by label propagation).
- **Edge thickness** = co-occurrence strength.
- **Hover** over a node to highlight its connections; click a community chip in the legend to see which keywords belong to that cluster.

### Exporting to Gephi

The download buttons export three files for [Gephi](https://gephi.org/):
- `nodes_df.csv` — one row per keyword with frequency and weight
- `edges_df.csv` — one row per pair with co-occurrence count, raw weight, and Jaccard similarity
- `matrix_df.csv` — full adjacency matrix

In Gephi: import `nodes_df.csv` as a node table and `edges_df.csv` as an edge table (undirected, weighted). Use the *ForceAtlas 2* layout and *Modularity* for community detection.

---

## Tips for a good analysis

- **Start small**: test with a narrow query (a few hundred papers) to validate the pipeline before running a large corpus.
- **Normalized is usually better for comparisons**: raw counts grow with the field. Normalized trends reveal what's actually becoming more or less prominent.
- **MeSH + Keywords together**: run Step 3 on both and compare — they often tell slightly different stories.
- **Network density**: if the network looks like a hairball, increase the minimum edge weight or reduce Top N. If it's too sparse, lower the threshold.
