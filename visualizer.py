"""
TopicTracker Step 3 — Interactive Visualization.

Generates Bokeh HTML embeds on demand.
Called from main.py via AJAX: user selects entities + category,
server returns an HTML fragment to inject into the page.
"""
from pathlib import Path

import bokeh
import pandas as pd
from bokeh.embed import json_item
from bokeh.models import HoverTool
from bokeh.palettes import Category10
from bokeh.plotting import figure

BOKEH_VERSION = bokeh.__version__


def load_entity_list(export_dir: Path, category: str) -> list[str]:
    """Return sorted list of entity names for the given category."""
    filename_map = {
        "keywords":  "Keywords.csv",
        "mesh":      "Meshterms.csv",
        "authors":   "Authors.csv",
        "journals":  "Journal.csv",
        "coi":       "Coi.csv",
        "lemmas":    "Lemmas.csv",
    }
    fname = filename_map.get(category)
    if not fname:
        return []
    path = export_dir / "data" / fname
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if "entity" not in df.columns:
        return []
    return sorted(df["entity"].tolist())


def generate_plot(export_dir: Path, category: str, entities: list[str], normalized: bool) -> dict:
    """
    Returns (script, div) Bokeh components for embedding.
    entities: list of entity names to plot.
    normalized: if True, use *_norm.csv file.
    """
    filename_map = {
        "keywords":  ("Keywords.csv",  "Keywords_norm.csv"),
        "mesh":      ("Meshterms.csv", "Meshterms_norm.csv"),
        "authors":   ("Authors.csv",   "Authors_norm.csv"),
        "journals":  ("Journal.csv",   "Journal_norm.csv"),
        "coi":       ("Coi.csv",       "Coi_norm.csv"),
        "lemmas":    ("Lemmas.csv",    "Lemmas_norm.csv"),
    }
    pair = filename_map.get(category)
    if not pair:
        raise ValueError(f"Unknown category: {category}")

    fname = pair[1] if normalized else pair[0]
    path = export_dir / "data" / fname
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {fname}")

    df = pd.read_csv(path)
    if "entity" not in df.columns:
        raise ValueError("Malformed data file: missing 'entity' column")

    year_cols = [c for c in df.columns if c.isdigit()]
    years = [int(c) for c in year_cols]

    ylabel = "% of papers" if normalized else "Count"
    title  = f"{category.capitalize()} — {'normalized' if normalized else 'raw count'}"

    p = figure(
        title=title,
        x_axis_label="Year",
        y_axis_label=ylabel,
        width=820,
        height=420,
        tools="pan,wheel_zoom,box_zoom,reset,save",
    )
    p.add_tools(HoverTool(tooltips=[("Year", "$x{0}"), ("Value", "$y{0.000}")]))

    colors = Category10[max(3, min(10, len(entities)))]

    for i, entity in enumerate(entities[:10]):  # cap at 10 lines
        row = df[df["entity"] == entity]
        if row.empty:
            continue
        vals = row[year_cols].values[0].tolist()
        color = colors[i % len(colors)]
        p.line(years, vals, legend_label=entity, line_color=color, line_width=2)
        p.circle(years, vals, color=color, size=5)

    p.legend.location = "top_left"
    p.legend.click_policy = "hide"

    return json_item(p, "bokeh-plot")
