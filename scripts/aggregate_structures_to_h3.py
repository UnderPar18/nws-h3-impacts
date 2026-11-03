"""Aggregate structure polygons to H3 cells.

Each building is assigned by its centroid (center containment). When an
occupancy column is present, counts are pivoted to one column per class.
USA Structures uses ``OCC_CLS``. The DC District Structures shapefile uses
``DESCRIPTIO``.

Example:

    python scripts/aggregate_structures_to_h3.py \
        --input data/raw/district_structures.shp \
        --output data/processed/district_structures_h3_res7.parquet \
        --resolution 7
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

OCCUPANCY_CANDIDATES = ("OCC_CLS", "PRIM_OCC", "OCC_TYPE", "DESCRIPTION", "DESCRIPTIO")


def _find_column(columns: list[str], names: tuple[str, ...]) -> str | None:
    lookup = {column.lower(): column for column in columns}
    for name in names:
        match = lookup.get(name.lower())
        if match is not None:
            return match
    return None


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return f"occ_{slug or 'unknown'}"


def assign_h3(gdf: gpd.GeoDataFrame, resolution: int) -> pd.Series:
    """Assign the H3 cell that contains each structure centroid."""
    if gdf.crs is None:
        raise ValueError("Input GeoDataFrame must have a CRS defined")

    centroids = gdf.geometry.centroid
    if gdf.crs.to_epsg() != 4326:
        centroids = centroids.to_crs(epsg=4326)

    cells: list[str | None] = []
    for point in centroids:
        if point is None or point.is_empty:
            cells.append(None)
            continue
        cells.append(h3.latlng_to_cell(point.y, point.x, resolution))
    return pd.Series(cells, index=gdf.index, dtype="object")


def occupancy_counts(gdf: gpd.GeoDataFrame, column: str) -> pd.DataFrame:
    """Count structures in each H3 cell by occupancy class."""
    labels = gdf[column].fillna("unknown").astype(str).map(_slug)
    counts = gdf.assign(_occ=labels).groupby(["h3", "_occ"]).size().unstack(fill_value=0)
    return counts.reset_index()


def aggregate_structures(
    input_path: Path,
    output_path: Path,
    resolution: int = 7,
    occupancy_column: str | None = None,
) -> None:
    """Load structures, assign H3 cells, and write cell counts."""
    print(f"Loading {input_path}...")
    gdf = gpd.read_file(input_path)
    print(f"{len(gdf):,} structures, CRS {gdf.crs}")

    occupancy_field = occupancy_column or _find_column(list(gdf.columns), OCCUPANCY_CANDIDATES)
    if occupancy_column and occupancy_field not in gdf.columns:
        raise ValueError(f"Occupancy column {occupancy_column!r} was not found")

    print(f"Assigning H3 resolution {resolution}...")
    gdf["h3"] = assign_h3(gdf, resolution)
    gdf = gdf.dropna(subset=["h3"])

    print("Aggregating...")
    aggregated = gdf.groupby("h3", as_index=False).size().rename(columns={"size": "structure_count"})
    if occupancy_field:
        print(f"Occupancy field: {occupancy_field}")
        aggregated = aggregated.merge(occupancy_counts(gdf, occupancy_field), on="h3", how="left")
    else:
        print("No occupancy column found; writing structure_count only")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(aggregated, preserve_index=False)
    extra = {
        b"source": str(input_path).encode(),
        b"h3_resolution": str(resolution).encode(),
        b"containment": b"center",
        b"occupancy_field": (occupancy_field or "").encode(),
    }
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **extra})
    pq.write_table(table, output_path)
    print(f"Wrote {len(aggregated):,} H3 cells to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate structures to H3")
    parser.add_argument("--input", type=Path, required=True, help="Input vector file")
    parser.add_argument("--output", type=Path, required=True, help="Output Parquet path")
    parser.add_argument("--resolution", type=int, default=7, help="H3 resolution")
    parser.add_argument(
        "--occupancy",
        help="Occupancy column. Detected automatically when omitted",
    )
    args = parser.parse_args()
    aggregate_structures(args.input, args.output, args.resolution, args.occupancy)


if __name__ == "__main__":
    main()
