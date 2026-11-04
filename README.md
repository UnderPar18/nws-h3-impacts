# NWS H3 Impacts

Polyfill active National Weather Service alerts onto H3 resolution 7 and join those cells to structure and population counts.

This project stays separate from `nws-h3-ndfd`. Both use the same H3 index string, so a forecast Parquet can be joined to these alert cells without combining the repositories.

## Run

```powershell
uv sync

uv run python scripts/refresh_active_alerts.py
```

That downloads the current alerts and writes three files under `data/processed/`. That directory is gitignored. Close the GeoPackages in ArcGIS Pro first. A file that is open in Pro cannot be replaced.

The refresh expects these grids to already exist:

- `data/processed/nsi_h3_res7.parquet`
- `data/processed/eif_ageracesex_h3_res7.parquet`
- `data/processed/eif_raceincome_h3_res7.parquet`

## Output

| File | Contents |
| --- | --- |
| `active_alerts_polygons.gpkg` | One feature per active alert polygon, for display in ArcGIS Pro |
| `active_alerts_h3_res7.parquet` | One row per H3 cell and alert |
| `active_alerts_h3_res7.gpkg` | One hexagon per H3 cell, joined to the structure and population grids |

`h3` is the resolution 7 index string. Alert cells use center containment: `h3.polygon_to_cells` keeps a cell when its center falls inside the polygon. When several alerts cover one cell, the hexagon lists every event and keeps the single highest-priority event, using the weather.gov hazards-map colors. Column definitions are in [docs/fields.md](docs/fields.md).

An alert cell with no buildings is kept. Its inventory fields are 0.

## Inventories

Rebuild the static grids only when the source inventories change, not on a routine alert refresh.

```powershell
uv run python scripts/aggregate_nsi_to_h3.py --input-dir <state NSI zip folder> --output data/processed/nsi_h3_res7.parquet
uv run python scripts/aggregate_eif_to_h3.py
```

`--input-dir` is a folder of state `*_NSI.zip` extracts from the USACE National Structure Inventory. `US_NSI.zip` is skipped because it repeats the state files. Each building is assigned with `h3.latlng_to_cell` from its longitude and latitude. Cells that cross a state line are summed after the states are aggregated.

`aggregate_eif_to_h3.py` reads `data/raw/gridded_eif_pop_ageracesex_2025_realtime.parquet` and writes the age, race, and sex grid. The race-income grid, `eif_raceincome_h3_res7.parquet`, is a separate file and stays in place. A grid point is placed in the H3 cell that contains its centroid. Counts are Census `n_noise_postprocessed` values. They can be fractional, and they differ from the NSI day and night population.

`scripts/aggregate_structures_to_h3.py` aggregates a local structure shapefile, such as a district extract. The alert refresh joins the national NSI grid.

## Source

Active alerts come from `https://api.weather.gov/alerts/active`. The request sends a descriptive User-Agent. The NWS API rejects calls that omit one.

Structure counts come from the [USACE National Structure Inventory](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/technical-documentation). Dollar values are depreciated replacement value.

Population counts come from the Census Bureau Gridded Environmental Impacts Frame, 2025 realtime age-by-race-by-sex file: `https://www2.census.gov/ces/gridded_eif/gridded_eif_pop_ageracesex_2025_realtime.parquet`.
