"""Build H3 hexagon polygons from an alert-cell Parquet file.

Writes one polygon per unique H3 cell so ArcGIS Pro can draw the layer.
The static NSI grid and both Census Gridded EIF population grids are left-joined
on ``h3`` before the polygons are built.
Source cells keep center containment from ``h3.polygon_to_cells``.

Example:

    python scripts/alerts_h3_to_gpkg.py \
        --input data/processed/active_alerts_h3_res7.parquet \
        --nsi data/processed/nsi_h3_res7.parquet \
        --eif data/processed/eif_ageracesex_h3_res7.parquet \
        --eif-income data/processed/eif_raceincome_h3_res7.parquet \
        --output data/processed/active_alerts_h3_res7.gpkg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import Polygon

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nws_h3_impacts.nws_hazard_styles import UNKNOWN_PRIORITY, hazard_style

DEFAULT_INPUT = Path("data/processed/active_alerts_h3_res7.parquet")
DEFAULT_NSI = Path("data/processed/nsi_h3_res7.parquet")
DEFAULT_EIF = Path("data/processed/eif_ageracesex_h3_res7.parquet")
DEFAULT_EIF_INCOME = Path("data/processed/eif_raceincome_h3_res7.parquet")
DEFAULT_OUTPUT = Path("data/processed/active_alerts_h3_res7.gpkg")
LAYER_NAME = "alerts_h3"
INCOME_RENAMES = {
    "eif_pop": "eif_income_pop",
    "eif_white": "eif_income_white",
    "eif_black": "eif_income_black",
    "eif_hispanic": "eif_income_hispanic",
    "eif_asian": "eif_income_asian",
    "eif_aian": "eif_income_aian",
    "eif_other": "eif_income_other",
}


def hex_polygon(cell: str) -> Polygon:
    """Return the WGS84 hexagon boundary for one H3 cell."""
    ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return Polygon(ring)


def _join_unique(values: pd.Series) -> str:
    labels = sorted({str(value) for value in values.dropna() if value})
    return "; ".join(labels)


def aggregate_alert_cells(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse alert rows to one record per H3 cell."""
    aggregated = frame.groupby("h3", as_index=False).agg(
        alert_count=("alert_id", "nunique"),
        events=("event", _join_unique),
        severities=("severity", _join_unique),
    )
    if "fetched_at" in frame.columns and not frame.empty:
        aggregated["fetched_at"] = frame["fetched_at"].iloc[0]
    if "resolution" in frame.columns and not frame.empty:
        aggregated["resolution"] = frame["resolution"].iloc[0]
    return aggregated


def dominant_hazard(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the weather.gov color of the highest-priority alert in each cell.

    Priority 1 is the most significant threat. A cell keeps that event's color
    even when other alerts overlap it, matching the hazards map rule.
    """
    ranked = frame[["h3", "alert_id", "event"]].copy()
    styles = ranked["event"].map(hazard_style)
    ranked["nws_priority"] = styles.map(
        lambda style: style["nws_priority"] if style["nws_priority"] is not None else UNKNOWN_PRIORITY
    )
    ranked["nws_event"] = ranked["event"]
    ranked["nws_color_name"] = styles.map(lambda style: style["nws_color_name"])
    ranked["nws_color_hex"] = styles.map(lambda style: style["nws_color_hex"])
    ranked["nws_color_rgb"] = styles.map(lambda style: style["nws_color_rgb"])
    ranked = ranked.sort_values(["h3", "nws_priority", "alert_id"])
    winners = ranked.drop_duplicates("h3", keep="first")
    winners.loc[winners["nws_priority"] == UNKNOWN_PRIORITY, "nws_priority"] = pd.NA
    return winners.drop(columns=["alert_id", "event"])


def attach_table(
    cells: pd.DataFrame,
    path: Path,
    label: str,
    indicator: str,
    renames: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Left-join an H3 attribute grid onto alert cells."""
    if not path.exists():
        raise FileNotFoundError(f"{label} grid not found: {path}")

    table = pd.read_parquet(path)
    if renames:
        table = table.rename(columns=renames)
        indicator = renames.get(indicator, indicator)
    table = table.loc[table["h3"].isin(set(cells["h3"]))]
    merged = cells.merge(table, on="h3", how="left")
    missing = int(merged[indicator].isna().sum()) if indicator in merged.columns else 0
    value_columns = [column for column in table.columns if column != "h3"]
    merged[value_columns] = merged[value_columns].fillna(0)
    for column in value_columns:
        if pd.api.types.is_integer_dtype(table[column]):
            merged[column] = merged[column].round().astype("int64")
    print(
        f"Joined {len(table):,} {label} cells from {path} "
        f"({missing:,} alert cells with no {label} records)"
    )
    return merged


def cells_to_geodataframe(
    frame: pd.DataFrame,
    nsi_path: Path,
    eif_path: Path,
    eif_income_path: Path,
) -> gpd.GeoDataFrame:
    """Attach NSI and EIF attributes and an H3 hexagon to each alert cell."""
    cells = aggregate_alert_cells(frame)
    cells = cells.merge(dominant_hazard(frame), on="h3", how="left")
    cells = attach_table(cells, nsi_path, "NSI", "structure_count")
    cells = attach_table(cells, eif_path, "EIF age-race-sex", "eif_pop")
    cells = attach_table(
        cells,
        eif_income_path,
        "EIF race-income",
        "eif_pop",
        INCOME_RENAMES,
    ).copy()
    cells["geometry"] = cells["h3"].map(hex_polygon)
    return gpd.GeoDataFrame(cells, geometry="geometry", crs="EPSG:4326")


def write_alert_hexes(
    frame: pd.DataFrame,
    output_path: Path,
    nsi_path: Path,
    eif_path: Path,
    eif_income_path: Path,
) -> None:
    """Write hexagon polygons to a GeoPackage layer."""
    gdf = cells_to_geodataframe(frame, nsi_path, eif_path, eif_income_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    gdf.to_file(output_path, layer=LAYER_NAME, driver="GPKG")
    print(f"Wrote {len(gdf):,} H3 polygons to {output_path} (layer {LAYER_NAME})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export alert H3 cells to a GeoPackage")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Alert H3 Parquet")
    parser.add_argument("--nsi", type=Path, default=DEFAULT_NSI, help="NSI H3 Parquet")
    parser.add_argument("--eif", type=Path, default=DEFAULT_EIF, help="Gridded EIF age-race-sex Parquet")
    parser.add_argument(
        "--eif-income",
        type=Path,
        default=DEFAULT_EIF_INCOME,
        help="Gridded EIF race-income Parquet",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output GeoPackage")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    frame = pd.read_parquet(args.input)
    write_alert_hexes(frame, args.output, args.nsi, args.eif, args.eif_income)


if __name__ == "__main__":
    main()
