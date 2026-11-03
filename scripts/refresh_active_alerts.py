"""Refresh the active-alert outputs used in ArcGIS Pro.

Runs the live steps in order:

1. Fetch ``api.weather.gov/alerts/active`` and write the H3 cell Parquet
   plus the original alert polygons.
2. Join those cells to the existing NSI and Census H3 grids and write the
   hexagon GeoPackage.

The structure and population grids are left as they are. Rebuild them only
when the source inventories change:

- ``scripts/aggregate_nsi_to_h3.py`` for the USACE NSI grid
- ``scripts/aggregate_eif_to_h3.py`` for the Census age-race-sex grid

Close ``active_alerts_h3_res7.gpkg`` and ``active_alerts_polygons.gpkg`` in
ArcGIS Pro before running. A GeoPackage that is open in Pro cannot be replaced.

Example:

    python scripts/refresh_active_alerts.py
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import alerts_h3_to_gpkg as hexes
import polyfill_alerts_to_h3 as polyfill


def require_static_grids(nsi_path: Path, eif_path: Path, eif_income_path: Path) -> None:
    """Stop before the alert fetch if a joined inventory file is missing."""
    required = (
        (nsi_path, "scripts/aggregate_nsi_to_h3.py"),
        (eif_path, "scripts/aggregate_eif_to_h3.py"),
        (
            eif_income_path,
            "the existing race-income Parquet; aggregate_eif_to_h3.py does not rebuild it",
        ),
    )
    missing = [(path, hint) for path, hint in required if not path.exists()]
    if not missing:
        return
    lines = ["Static H3 grids are missing. Rebuild those before refreshing alerts:"]
    for path, hint in missing:
        lines.append(f"  {path}  ({hint})")
    raise SystemExit("\n".join(lines))


def _replace(output_path: Path, write: Callable[[], None]) -> None:
    """Rewrite a GeoPackage and explain a Windows lock from ArcGIS Pro."""
    try:
        write()
    except PermissionError as exc:
        raise SystemExit(
            f"Could not replace {output_path}. Close that GeoPackage in ArcGIS Pro "
            f"and run this again.\n{exc}"
        ) from exc


def refresh(
    resolution: int,
    url: str,
    timeout: float,
    cells_path: Path,
    polygons_path: Path,
    hex_path: Path,
    nsi_path: Path,
    eif_path: Path,
    eif_income_path: Path,
) -> None:
    """Fetch current alerts and rebuild the polygon and hexagon GeoPackages."""
    started = time.perf_counter()
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"Fetching {url}...")
    features = polyfill.fetch_active_alerts(url, timeout)
    print(f"Received {len(features):,} features at {fetched_at}")
    cells = polyfill.alerts_to_cells(features, resolution)
    polyfill.write_alerts_parquet(cells, cells_path, resolution, fetched_at, url)
    _replace(
        polygons_path,
        lambda: polyfill.write_alert_polygons(features, polygons_path, fetched_at),
    )

    print(f"Joining inventories and writing {hex_path}...")
    _replace(
        hex_path,
        lambda: hexes.write_alert_hexes(cells, hex_path, nsi_path, eif_path, eif_income_path),
    )

    elapsed = time.perf_counter() - started
    print(f"Alert refresh finished in {elapsed:.1f}s")
    print(f"  cells:    {cells_path}")
    print(f"  polygons: {polygons_path}")
    print(f"  hexes:    {hex_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh active alerts and the joined hex GeoPackage"
    )
    parser.add_argument("--resolution", type=int, default=7, help="H3 resolution")
    parser.add_argument("--url", default=polyfill.NWS_ALERTS_URL, help="Active alerts GeoJSON URL")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")
    parser.add_argument(
        "--cells",
        type=Path,
        default=polyfill.DEFAULT_OUTPUT,
        help="Alert H3 Parquet",
    )
    parser.add_argument(
        "--polygons",
        type=Path,
        default=polyfill.DEFAULT_POLYGONS,
        help="Alert polygon GeoPackage",
    )
    parser.add_argument("--output", type=Path, default=hexes.DEFAULT_OUTPUT, help="Hex GeoPackage")
    parser.add_argument("--nsi", type=Path, default=hexes.DEFAULT_NSI, help="NSI H3 Parquet")
    parser.add_argument(
        "--eif",
        type=Path,
        default=hexes.DEFAULT_EIF,
        help="EIF age-race-sex Parquet",
    )
    parser.add_argument(
        "--eif-income",
        type=Path,
        default=hexes.DEFAULT_EIF_INCOME,
        help="EIF race-income Parquet",
    )
    args = parser.parse_args()
    require_static_grids(args.nsi, args.eif, args.eif_income)
    refresh(
        args.resolution,
        args.url,
        args.timeout,
        args.cells,
        args.polygons,
        args.output,
        args.nsi,
        args.eif,
        args.eif_income,
    )


if __name__ == "__main__":
    main()
