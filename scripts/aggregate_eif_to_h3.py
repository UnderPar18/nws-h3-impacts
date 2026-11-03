"""Aggregate Census Gridded EIF age-race-sex counts to H3.

Source rows are population counts on a 0.01-degree grid, one row per grid
point, age group, race/ethnicity, and sex. Each grid point is assigned by
its centroid (``h3.latlng_to_cell``). Counts are the Census post-processed
values (``n_noise_postprocessed``), which are non-negative and can be
fractional.

Example:

    python scripts/aggregate_eif_to_h3.py \
        --input data/raw/gridded_eif_pop_ageracesex_2025_realtime.parquet \
        --output data/processed/eif_ageracesex_h3_res7.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import h3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

EIF_URL = (
    "https://www2.census.gov/ces/gridded_eif/"
    "gridded_eif_pop_ageracesex_2025_realtime.parquet"
)
DEFAULT_INPUT = Path("data/raw/gridded_eif_pop_ageracesex_2025_realtime.parquet")
DEFAULT_OUTPUT = Path("data/processed/eif_ageracesex_h3_res7.parquet")

RACE_SLUGS = {
    "White": "white",
    "Black": "black",
    "Hispanic": "hispanic",
    "Asian": "asian",
    "AIAN": "aian",
    "Other/Unknown": "other",
}
AGE_SLUGS = {
    "Under 18": "under18",
    "19-65": "age19_65",
    "Over 65": "over65",
    "Missing Age": "age_missing",
}
SEX_SLUGS = {
    "F": "female",
    "M": "male",
    "Missing Gender": "sex_missing",
}
RACE_ORDER = ("white", "black", "hispanic", "asian", "aian", "other")
AGE_ORDER = ("under18", "age19_65", "over65", "age_missing")
SEX_ORDER = ("female", "male", "sex_missing")


def assign_h3(frame: pd.DataFrame, resolution: int) -> pd.DataFrame:
    """Attach an H3 cell to each distinct grid-point centroid."""
    points = frame[["grid_lon", "grid_lat"]].drop_duplicates()
    lon = points["grid_lon"].astype(float)
    lat = points["grid_lat"].astype(float)
    valid = lon.between(-180, 180) & lat.between(-90, 90)
    points = points.loc[valid].copy()
    points["h3"] = [
        h3.latlng_to_cell(lat_value, lon_value, resolution)
        for lon_value, lat_value in zip(lon.loc[valid], lat.loc[valid], strict=True)
    ]
    return frame.merge(points, on=["grid_lon", "grid_lat"], how="inner")


def aggregate_eif(frame: pd.DataFrame, resolution: int) -> pd.DataFrame:
    """Sum age, race, and sex counts to one row per H3 cell."""
    assigned = assign_h3(frame, resolution)
    assigned["pop"] = assigned["n_noise_postprocessed"].fillna(0)
    assigned["race"] = assigned["race_ethnicity"].map(RACE_SLUGS).fillna("other")
    assigned["age"] = assigned["age_group"].map(AGE_SLUGS).fillna("age_missing")
    assigned["sex"] = assigned["sex"].map(SEX_SLUGS).fillna("sex_missing")

    total = assigned.groupby("h3", as_index=False)["pop"].sum().rename(columns={"pop": "eif_pop"})
    age = _pivot_sum(assigned, "age", "eif_")
    sex = _pivot_sum(assigned, "sex", "eif_")
    race = _pivot_sum(assigned, "race", "eif_")
    cross_label = "eif_" + assigned["race"] + "_" + assigned["age"] + "_" + assigned["sex"]
    cross = _sum_by_label(assigned, cross_label)
    grid = (
        total.merge(age, on="h3", how="left")
        .merge(sex, on="h3", how="left")
        .merge(race, on="h3", how="left")
        .merge(cross, on="h3", how="left")
    )
    return _order_columns(grid)


def _pivot_sum(frame: pd.DataFrame, column: str, prefix: str) -> pd.DataFrame:
    grouped = frame.groupby(["h3", column], as_index=False)["pop"].sum()
    grouped["column"] = prefix + grouped[column].astype(str)
    return _sum_by_label(grouped, grouped["column"])


def _sum_by_label(frame: pd.DataFrame, labels: pd.Series) -> pd.DataFrame:
    labeled = frame.assign(column=labels)
    grouped = labeled.groupby(["h3", "column"], as_index=False)["pop"].sum()
    wide = grouped.pivot(index="h3", columns="column", values="pop").fillna(0)
    return wide.reset_index()


def _order_columns(grid: pd.DataFrame) -> pd.DataFrame:
    age_columns = [f"eif_{age}" for age in AGE_ORDER if f"eif_{age}" in grid.columns]
    sex_columns = [f"eif_{sex}" for sex in SEX_ORDER if f"eif_{sex}" in grid.columns]
    race_columns = [f"eif_{race}" for race in RACE_ORDER if f"eif_{race}" in grid.columns]
    cross_columns = [
        f"eif_{race}_{age}_{sex}"
        for race in RACE_ORDER
        for age in AGE_ORDER
        for sex in SEX_ORDER
        if f"eif_{race}_{age}_{sex}" in grid.columns
    ]
    ordered = ["h3", "eif_pop", *age_columns, *sex_columns, *race_columns, *cross_columns]
    remaining = [column for column in grid.columns if column not in ordered]
    return grid[ordered + remaining].sort_values("h3").reset_index(drop=True)


def write_eif_grid(frame: pd.DataFrame, output_path: Path, resolution: int, source: Path) -> None:
    """Write the H3 population grid and record the Census source."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    extra = {
        b"source": str(source).encode(),
        b"source_url": EIF_URL.encode(),
        b"h3_resolution": str(resolution).encode(),
        b"containment": b"center",
        b"h3_function": b"h3.latlng_to_cell",
        b"count_field": b"n_noise_postprocessed",
        b"inventory": b"Census Gridded EIF age-race-sex 2025 realtime",
    }
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **extra})
    pq.write_table(table, output_path)
    print(f"Wrote {len(frame):,} H3 cells to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate Gridded EIF population to H3")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="EIF age-race-sex Parquet")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output H3 Parquet")
    parser.add_argument("--resolution", type=int, default=7, help="H3 resolution")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    frame = pd.read_parquet(args.input)
    print(f"{len(frame):,} grid rows")
    grid = aggregate_eif(frame, args.resolution)
    print(f"Population total {grid['eif_pop'].sum():,.0f}")
    write_eif_grid(grid, args.output, args.resolution, args.input)


if __name__ == "__main__":
    main()
