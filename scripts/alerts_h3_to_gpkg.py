"""Build H3 hexagon polygons from an alert-cell Parquet file.

Writes one polygon per unique H3 cell so ArcGIS Pro can draw the layer.
Source cells keep center containment from ``h3.polygon_to_cells``.

Example:

    python scripts/alerts_h3_to_gpkg.py \
        --input data/processed/active_alerts_h3_res7.parquet \
        --output data/processed/active_alerts_h3_res7.gpkg
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import Polygon

DEFAULT_INPUT = Path("data/processed/active_alerts_h3_res7.parquet")
DEFAULT_OUTPUT = Path("data/processed/active_alerts_h3_res7.gpkg")
LAYER_NAME = "alerts_h3"


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


def cells_to_geodataframe(frame: pd.DataFrame) -> gpd.GeoDataFrame:
    """Attach an H3 hexagon polygon to each aggregated cell."""
    cells = aggregate_alert_cells(frame)
    cells["geometry"] = cells["h3"].map(hex_polygon)
    return gpd.GeoDataFrame(cells, geometry="geometry", crs="EPSG:4326")


def write_alert_hexes(frame: pd.DataFrame, output_path: Path) -> None:
    """Write hexagon polygons to a GeoPackage layer."""
    gdf = cells_to_geodataframe(frame)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    gdf.to_file(output_path, layer=LAYER_NAME, driver="GPKG")
    print(f"Wrote {len(gdf):,} H3 polygons to {output_path} (layer {LAYER_NAME})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export alert H3 cells to a GeoPackage")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Alert H3 Parquet")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output GeoPackage")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    frame = pd.read_parquet(args.input)
    write_alert_hexes(frame, args.output)


if __name__ == "__main__":
    main()
