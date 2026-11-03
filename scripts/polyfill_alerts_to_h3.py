"""Polyfill active NWS alert polygons to H3 cells.

Data source: https://api.weather.gov/alerts/active
Containment: center (``h3.polygon_to_cells`` — cell centroid inside the polygon).
Output grain: one row per unique (h3, alert_id). Long CAP text (description,
instruction) is omitted so it is not repeated on every cell.

Example:

    uv run python scripts/polyfill_alerts_to_h3.py \
        --output data/processed/active_alerts_h3_res7.parquet \
        --resolution 7
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from shapely.geometry import shape
from tqdm import tqdm

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nws_h3_impacts.nws_hazard_styles import hazard_style

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"
# api.weather.gov rejects requests that do not send a descriptive User-Agent.
USER_AGENT = "nws-h3-impacts/0.1.0 (research; h3 alert polyfill)"
DEFAULT_OUTPUT = Path("data/processed/active_alerts_h3_res7.parquet")
DEFAULT_POLYGONS = Path("data/processed/active_alerts_polygons.gpkg")
POLYGON_LAYER = "alerts"

METADATA_COLUMNS = (
    "alert_id",
    "event",
    "severity",
    "urgency",
    "certainty",
    "headline",
    "area_desc",
    "sender_name",
    "status",
    "message_type",
    "response",
    "onset",
    "effective",
    "ends",
    "expires",
    "sent",
)

POLYGON_TYPES = {"Polygon", "MultiPolygon"}


def fetch_active_alerts(url: str, timeout: float) -> list[dict]:
    """Download the active NWS alert feed as GeoJSON features."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 403:
            raise SystemExit(
                "NWS API returned 403. A descriptive User-Agent header is required."
            ) from exc
        raise

    features = response.json().get("features", [])
    if not isinstance(features, list):
        raise ValueError("Alert feed did not contain a GeoJSON features array")
    return features


def polygon_to_h3_cells(geometry: dict, resolution: int) -> set[str]:
    """Convert a GeoJSON Polygon or MultiPolygon to H3 cell ids.

    ``h3.polygon_to_cells`` uses center containment: a cell is included when
    its centroid lies inside the polygon (holes excluded).
    """
    shape = h3.geo_to_h3shape(geometry)
    return {str(cell) for cell in h3.polygon_to_cells(shape, resolution)}


def alert_metadata(feature: dict) -> dict[str, str | None]:
    """Operational alert fields copied onto each H3 cell of the polygon."""
    props = feature.get("properties") or {}
    return {
        "alert_id": props.get("id") or feature.get("id"),
        "event": props.get("event"),
        "severity": props.get("severity"),
        "urgency": props.get("urgency"),
        "certainty": props.get("certainty"),
        "headline": props.get("headline"),
        "area_desc": props.get("areaDesc"),
        "sender_name": props.get("senderName"),
        "status": props.get("status"),
        "message_type": props.get("messageType"),
        "response": props.get("response"),
        "onset": props.get("onset"),
        "effective": props.get("effective"),
        "ends": props.get("ends"),
        "expires": props.get("expires"),
        "sent": props.get("sent"),
    }


def _empty_columns() -> dict[str, list]:
    columns: dict[str, list] = {"h3": []}
    for name in METADATA_COLUMNS:
        columns[name] = []
    return columns


def _append_alert_cells(
    columns: dict[str, list],
    cells: set[str],
    meta: dict[str, str | None],
) -> None:
    columns["h3"].extend(cells)
    for name in METADATA_COLUMNS:
        columns[name].extend([meta[name]] * len(cells))


def alerts_to_cells(features: list[dict], resolution: int) -> pd.DataFrame:
    """Explode alert polygons into unique (h3, alert_id) rows."""
    columns = _empty_columns()
    skipped = 0
    empty = 0
    failed = 0

    for feature in tqdm(features, desc="Polyfilling alerts", unit="alert"):
        geometry = feature.get("geometry")
        geom_type = geometry.get("type") if isinstance(geometry, dict) else None
        if geom_type not in POLYGON_TYPES:
            skipped += 1
            continue

        meta = alert_metadata(feature)
        try:
            cells = polygon_to_h3_cells(geometry, resolution)
        except Exception as exc:
            failed += 1
            print(f"Skipping {meta['alert_id']}: {type(exc).__name__}: {exc}")
            continue

        if not cells:
            empty += 1
            continue
        _append_alert_cells(columns, cells, meta)

    frame = pd.DataFrame(columns)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["h3", "alert_id"]).sort_values(
            ["h3", "alert_id"], ignore_index=True
        )

    unique_cells = frame["h3"].nunique() if not frame.empty else 0
    print(
        f"Features: {len(features):,} | no polygon: {skipped:,} | "
        f"no cell center: {empty:,} | failed: {failed:,} | "
        f"rows: {len(frame):,} | unique H3 cells: {unique_cells:,}"
    )
    return frame


def write_alerts_parquet(
    frame: pd.DataFrame,
    output_path: Path,
    resolution: int,
    fetched_at: str,
    source_url: str,
) -> None:
    """Write the cell table and record source metadata on the Parquet file."""
    frame = frame.copy()
    frame["resolution"] = resolution
    frame["fetched_at"] = fetched_at

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    extra = {
        b"source": source_url.encode(),
        b"fetched_at": fetched_at.encode(),
        b"h3_resolution": str(resolution).encode(),
        b"containment": b"center",
        b"h3_function": b"h3.polygon_to_cells",
    }
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **extra})
    pq.write_table(table, output_path)
    print(f"Wrote {len(frame):,} rows to {output_path}")


def write_alert_polygons(features: list[dict], output_path: Path, fetched_at: str) -> None:
    """Write one GeoPackage feature per alert polygon, with NWS color and priority."""
    rows: list[dict[str, str | int | None]] = []
    geometries = []
    for feature in features:
        geometry = feature.get("geometry")
        geom_type = geometry.get("type") if isinstance(geometry, dict) else None
        if geom_type not in POLYGON_TYPES:
            continue
        row = alert_metadata(feature)
        row.update(hazard_style(row["event"]))
        row["fetched_at"] = fetched_at
        rows.append(row)
        geometries.append(shape(geometry))

    frame = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    frame.to_file(output_path, layer=POLYGON_LAYER, driver="GPKG")
    missing = int(frame["nws_priority"].isna().sum()) if not frame.empty else 0
    print(
        f"Wrote {len(frame):,} alert polygons to {output_path} "
        f"({missing:,} events without an NWS map color)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Polyfill active NWS alerts to H3 cells")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output Parquet path",
    )
    parser.add_argument(
        "--polygons",
        type=Path,
        default=DEFAULT_POLYGONS,
        help="Output GeoPackage of the original alert polygons",
    )
    parser.add_argument("--resolution", type=int, default=7, help="H3 resolution")
    parser.add_argument("--url", default=NWS_ALERTS_URL, help="Active alerts GeoJSON URL")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Fetching {args.url}...")
    features = fetch_active_alerts(args.url, args.timeout)
    print(f"Received {len(features):,} features at {fetched_at}")

    frame = alerts_to_cells(features, args.resolution)
    write_alerts_parquet(frame, args.output, args.resolution, fetched_at, args.url)
    write_alert_polygons(features, args.polygons, fetched_at)


if __name__ == "__main__":
    main()
