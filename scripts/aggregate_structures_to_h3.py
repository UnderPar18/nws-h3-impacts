"""Aggregate structure points or polygons to H3 resolution 7.

Example usage (after downloading a state-level USA Structures file):

    uv run python scripts/aggregate_structures_to_h3.py \
        --input data/raw/utah_structures.gpkg \
        --output data/processed/utah_h3_res7.parquet \
        --resolution 7
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def assign_h3(gdf: gpd.GeoDataFrame, resolution: int) -> pd.Series:
    """Assign H3 index based on geometry centroid."""
    # Ensure we have a projected or geographic CRS; H3 expects WGS84
    if gdf.crs is None:
        raise ValueError("Input GeoDataFrame must have a CRS defined")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    centroids = gdf.geometry.centroid
    return centroids.apply(
        lambda pt: h3.latlng_to_cell(pt.y, pt.x, resolution) if pt else None
    )


def aggregate_structures(
    input_path: Path,
    output_path: Path,
    resolution: int = 7,
    count_column: str = "structure_count",
) -> None:
    """Load structures, assign H3 cells, and aggregate counts."""
    print(f"Loading {input_path}...")
    gdf = gpd.read_file(input_path)

    print(f"Assigning H3 resolution {resolution}...")
    gdf["h3"] = assign_h3(gdf, resolution)

    # Drop any rows that failed H3 assignment
    gdf = gdf.dropna(subset=["h3"])

    print("Aggregating...")
    # Basic count aggregation. Extend with occupancy type, value, etc. as needed.
    agg = (
        gdf.groupby("h3", as_index=False)
        .size()
        .rename(columns={"size": count_column})
    )

    # Optional: add more aggregations here (e.g., by occupancy type)
    # Example placeholder for occupancy if the column exists:
    # if "OCC_TYPE" in gdf.columns:
    #     occ = gdf.groupby(["h3", "OCC_TYPE"]).size().unstack(fill_value=0)
    #     agg = agg.merge(occ, on="h3", how="left")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(agg)
    pq.write_table(table, output_path)
    print(f"Wrote {len(agg):,} H3 cells to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate structures to H3")
    parser.add_argument("--input", type=Path, required=True, help="Input vector file")
    parser.add_argument("--output", type=Path, required=True, help="Output Parquet path")
    parser.add_argument("--resolution", type=int, default=7, help="H3 resolution")
    args = parser.parse_args()

    aggregate_structures(args.input, args.output, args.resolution)


if __name__ == "__main__":
    main()
