"""Aggregate USACE NSI state extracts to an H3 resolution 7 grid.

Each ``*_NSI.zip`` in the input directory contains one state Parquet. States
are read one at a time. Cells that cross a state boundary are summed after
every state is aggregated, so the result can be joined to a hazard H3 grid
on the ``h3`` index.

``US_NSI.zip`` is skipped. It repeats the state files.

Containment: center (building longitude/latitude via ``h3.latlng_to_cell``).

Example:

    python scripts/aggregate_nsi_to_h3.py \
        --input-dir C:/Users/chad.kahler/Documents/ArcGIS/Projects/NSI_Econ/data/parquet/state_aggregated \
        --output data/processed/nsi_h3_res7.parquet
"""

from __future__ import annotations

import argparse
import re
import tempfile
import zipfile
from pathlib import Path

import h3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

SOURCE_COLUMNS = {
    "properties_x": "lon",
    "properties_y": "lat",
    "properties_occtype": "occtype",
    "properties_st_damcat": "st_damcat",
    "properties_pop2amo65": "pop_night_o65",
    "properties_pop2amu65": "pop_night_u65",
    "properties_pop2pmo65": "pop_day_o65",
    "properties_pop2pmu65": "pop_day_u65",
    "properties_students": "students",
    "properties_resunits": "resunits",
    "properties_sqft": "sqft",
    "properties_val_struct": "val_struct",
    "properties_val_cont": "val_cont",
    "properties_val_vehic": "val_vehic",
}

INTEGER_COLUMNS = {
    "structure_count",
    "pop_night",
    "pop_day",
    "pop_night_o65",
    "pop_night_u65",
    "pop_day_o65",
    "pop_day_u65",
    "students",
    "resunits",
}


def state_zip_paths(input_dir: Path, states: set[str] | None) -> list[Path]:
    """Return state NSI zips, excluding the national rollup."""
    paths: list[Path] = []
    for path in sorted(input_dir.glob("*_NSI.zip")):
        state = path.name.split("_", 1)[0].upper()
        if len(state) != 2 or state == "US":
            continue
        if states is not None and state not in states:
            continue
        paths.append(path)
    if not paths:
        raise FileNotFoundError(f"No state NSI zips found in {input_dir}")
    return paths


def _slug(label: str, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(label).strip().lower()).strip("_")
    return f"{prefix}_{slug or 'unknown'}"


def read_state_buildings(zip_path: Path) -> pd.DataFrame:
    """Read the building columns from one state zip and drop bad coordinates."""
    with tempfile.TemporaryDirectory() as temp_dir, zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".parquet")]
        if len(members) != 1:
            raise ValueError(f"{zip_path.name} contains {len(members)} parquet files")
        extracted = Path(archive.extract(members[0], temp_dir))
        frame = pq.read_table(extracted, columns=list(SOURCE_COLUMNS)).to_pandas()

    frame = frame.rename(columns=SOURCE_COLUMNS)
    valid = frame["lon"].between(-180, 180) & frame["lat"].between(-90, 90)
    dropped = int((~valid).sum())
    if dropped:
        print(f"  dropped {dropped:,} buildings with coordinates outside WGS84")
    return frame.loc[valid].copy()


def assign_h3(frame: pd.DataFrame, resolution: int) -> pd.Series:
    """Assign an H3 cell from each building's latitude and longitude."""
    cells = [
        h3.latlng_to_cell(lat, lon, resolution)
        for lon, lat in zip(frame["lon"].to_numpy(), frame["lat"].to_numpy(), strict=True)
    ]
    return pd.Series(cells, index=frame.index)


def _pivot_counts(frame: pd.DataFrame, column: str, prefix: str) -> pd.DataFrame:
    counts = frame.groupby(["h3", column]).size().unstack(fill_value=0)
    counts.columns = [_slug(name, prefix) for name in counts.columns]
    return counts.reset_index()


def aggregate_buildings(frame: pd.DataFrame, resolution: int) -> pd.DataFrame:
    """Sum building attributes to one row per H3 cell."""
    frame = frame.copy()
    frame["h3"] = assign_h3(frame, resolution)
    frame["pop_night"] = frame["pop_night_o65"].fillna(0) + frame["pop_night_u65"].fillna(0)
    frame["pop_day"] = frame["pop_day_o65"].fillna(0) + frame["pop_day_u65"].fillna(0)
    fill_columns = (
        "pop_night_o65",
        "pop_night_u65",
        "pop_day_o65",
        "pop_day_u65",
        "students",
        "resunits",
        "sqft",
        "val_struct",
        "val_cont",
        "val_vehic",
    )
    for column in fill_columns:
        frame[column] = frame[column].fillna(0)
    frame["occtype"] = frame["occtype"].fillna("unknown").astype(str)
    frame["st_damcat"] = frame["st_damcat"].fillna("unknown").astype(str)

    metrics = frame.groupby("h3", as_index=False).agg(
        structure_count=("lon", "size"),
        pop_night=("pop_night", "sum"),
        pop_day=("pop_day", "sum"),
        pop_night_o65=("pop_night_o65", "sum"),
        pop_night_u65=("pop_night_u65", "sum"),
        pop_day_o65=("pop_day_o65", "sum"),
        pop_day_u65=("pop_day_u65", "sum"),
        students=("students", "sum"),
        resunits=("resunits", "sum"),
        sqft=("sqft", "sum"),
        val_struct=("val_struct", "sum"),
        val_cont=("val_cont", "sum"),
        val_vehic=("val_vehic", "sum"),
    )
    occupancy = _pivot_counts(frame, "occtype", "occ")
    damage = _pivot_counts(frame, "st_damcat", "count")
    damage_value = frame.groupby(["h3", "st_damcat"])["val_struct"].sum().unstack(fill_value=0)
    damage_value.columns = [_slug(name, "val_struct") for name in damage_value.columns]
    damage_value = damage_value.reset_index()
    return metrics.merge(occupancy, on="h3", how="left").merge(damage, on="h3", how="left").merge(
        damage_value, on="h3", how="left"
    )


def combine_states(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Sum state aggregates so buildings in a shared border cell stay together."""
    combined = pd.concat(frames, ignore_index=True)
    value_columns = [column for column in combined.columns if column != "h3"]
    combined[value_columns] = combined[value_columns].fillna(0)
    totals = combined.groupby("h3", as_index=False)[value_columns].sum()
    for column in totals.columns:
        if column in INTEGER_COLUMNS or column.startswith(("count_", "occ_")):
            totals[column] = totals[column].round().astype("int64")
    return totals.sort_values("h3").reset_index(drop=True)


def write_nsi_grid(frame: pd.DataFrame, output_path: Path, resolution: int, source_dir: Path) -> None:
    """Write the national H3 grid and record the source location."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    extra = {
        b"source": str(source_dir).encode(),
        b"h3_resolution": str(resolution).encode(),
        b"containment": b"center",
        b"h3_function": b"h3.latlng_to_cell",
        b"inventory": b"USACE NSI",
    }
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **extra})
    pq.write_table(table, output_path)
    print(f"Wrote {len(frame):,} H3 cells to {output_path}")


def aggregate_nsi(input_dir: Path, output_path: Path, resolution: int, states: set[str] | None) -> None:
    """Aggregate every requested state zip into one H3 Parquet."""
    paths = state_zip_paths(input_dir, states)
    print(f"Processing {len(paths)} state zips at H3 resolution {resolution}")
    state_frames: list[pd.DataFrame] = []
    for zip_path in tqdm(paths, desc="States", unit="state"):
        buildings = read_state_buildings(zip_path)
        aggregated = aggregate_buildings(buildings, resolution)
        state_frames.append(aggregated)
        print(f"  {zip_path.stem}: {len(buildings):,} buildings -> {len(aggregated):,} cells")

    grid = combine_states(state_frames)
    write_nsi_grid(grid, output_path, resolution, input_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate NSI structures to H3")
    parser.add_argument("--input-dir", type=Path, required=True, help="Directory of state NSI zips")
    parser.add_argument("--output", type=Path, required=True, help="Output Parquet path")
    parser.add_argument("--resolution", type=int, default=7, help="H3 resolution")
    parser.add_argument(
        "--states",
        help="Comma-separated state abbreviations to process. Default is every state zip",
    )
    args = parser.parse_args()
    selected = None
    if args.states:
        selected = {state.strip().upper() for state in args.states.split(",") if state.strip()}
    aggregate_nsi(args.input_dir, args.output, args.resolution, selected)


if __name__ == "__main__":
    main()
