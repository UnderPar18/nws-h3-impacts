# NWS H3 Impacts

H3-based impact analysis framework for overlaying NWS hazard polygons and NDFD forecast thresholds against population and structure data.

## Goals

- Aggregate population and national structure inventories to H3 resolution 7 (closest practical match to NDFD ~2.5 km)
- Efficiently evaluate impacts inside NWS hazard polygons via integer H3 joins
- Apply NDFD parameter thresholds to infer potential impacts
- Support interactive visualization of hazards and impact summaries

## Quick Start

```bash
# Create environment and install dependencies
uv sync

# Or with optional web dependencies later
uv sync --extra web --extra dev

# Activate (uv handles this automatically with uv run)
uv run python -m nws_h3_impacts
```

## Project Layout

```
src/nws_h3_impacts/     # Main package
scripts/                # Aggregation and conversion scripts
notebooks/              # Exploration
docs/                   # Field definitions and notes
data/                   # Local data (gitignored)
  raw/                  # Source downloads
  processed/            # H3-aggregated Parquet files
.cursor/rules/          # Cursor AI conventions
```

## Refresh active alerts

When the inventories are already built, update the hazard outputs with one script:

```bash
python scripts/refresh_active_alerts.py
```

That fetches the current alerts, writes `data/processed/active_alerts_polygons.gpkg`, and rebuilds `data/processed/active_alerts_h3_res7.gpkg` by joining those cells to the existing NSI and Census grids. Close both GeoPackages in ArcGIS Pro first.

Rebuild the static grids only when the source inventories change, not on a routine alert refresh:

```bash
python scripts/aggregate_nsi_to_h3.py --input-dir <state NSI zip folder> --output data/processed/nsi_h3_res7.parquet
python scripts/aggregate_eif_to_h3.py
```

## Data Notes

- **Structures**: USACE National Structure Inventory, aggregated to H3 in `data/processed/nsi_h3_res7.parquet`
- **Population**: NSI day and night population on that same grid. Census Gridded EIF age, race, and sex counts are in `data/processed/eif_ageracesex_h3_res7.parquet`. WorldPop or LandScan remain options for an independent check.
- **Field definitions**: [docs/fields.md](docs/fields.md)
- **Hazards**: `api.weather.gov/alerts/active` (GeoJSON)
- **Forecasts**: NDFD / GRIB converted to H3 via centroid sampling

Start with a single state or county subset. National full-resolution processing is feasible but memory- and time-intensive.

## Development

- Default H3 resolution: **7**
- Prefer integer H3 index joins over geometric intersections
- Store processed aggregates as Parquet keyed on H3 index
- Use `uv` for environment and dependency management
