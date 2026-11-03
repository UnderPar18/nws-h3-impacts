# Field reference

Definitions for `data/processed/active_alerts_h3_res7.gpkg`, the NSI grid `data/processed/nsi_h3_res7.parquet`, and the Census population grid `data/processed/eif_ageracesex_h3_res7.parquet`.

Each row is one H3 resolution 7 cell. Alert polygons use center containment (`h3.polygon_to_cells`: the cell center falls inside the polygon). Each NSI building is assigned with `h3.latlng_to_cell` from its WGS84 longitude and latitude. Inventory values are sums of the buildings in the cell. An alert cell with no NSI buildings is kept and its inventory fields are 0.

NSI attributes follow the [USACE National Structure Inventory 2026 technical documentation](https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2026/technical-documentation). Dollar values are depreciated replacement value in U.S. dollars.

## Alert fields

| Field | Meaning |
| --- | --- |
| `h3` | H3 index at resolution 7. Join key for the NSI grid. |
| `alert_count` | Number of unique active alerts whose polygons contain the cell. |
| `events` | Alert event names in the cell, separated by `; `. |
| `severities` | Alert severity values in the cell, separated by `; `. |
| `fetched_at` | UTC time the active-alert feed was downloaded. |
| `resolution` | H3 resolution. This layer is 7. |
| `geometry` | Hexagon boundary of the cell, WGS84 (EPSG:4326). |
| `nws_event` | Highest-priority alert event in the cell. Priority 1 is the most significant. |
| `nws_priority` | weather.gov display priority of `nws_event`. |
| `nws_color_name` | weather.gov color name for `nws_event`. |
| `nws_color_hex` | Hex color for `nws_event`, such as `#FF0000`. |
| `nws_color_rgb` | RGB color for `nws_event`, such as `255,0,0`. |

Colors and priorities are the March 10, 2025 hazards-map list at https://www.weather.gov/help-map. When several alerts cover one cell, these fields keep the single highest-priority event, which is the event the weather.gov map would draw.

## Alert polygons

`data/processed/active_alerts_polygons.gpkg` is one feature per active alert polygon, in WGS84, for display in ArcGIS Pro. It is not an H3 grid. Each feature has the alert fields from the feed (`alert_id`, `event`, `severity`, `headline`, and the time fields) plus `nws_priority`, `nws_color_name`, `nws_color_hex`, and `nws_color_rgb` for that alert's own event.

## Structure, population, and value fields

These columns are copied from `nsi_h3_res7.parquet`.

| Field | NSI source | Meaning |
| --- | --- | --- |
| `structure_count` | one row per building | Buildings in the cell. |
| `pop_night` | `pop2amo65` + `pop2amu65` | Nighttime population. |
| `pop_day` | `pop2pmo65` + `pop2pmu65` | Daytime population. |
| `pop_night_o65` | `pop2amo65` | Nighttime population age 65 and over. |
| `pop_night_u65` | `pop2amu65` | Nighttime population under age 65. |
| `pop_day_o65` | `pop2pmo65` | Daytime population age 65 and over. |
| `pop_day_u65` | `pop2pmu65` | Daytime population under age 65. |
| `students` | `students` | School enrollment from NCES. Stored separately from `pop_night` and `pop_day`. |
| `resunits` | `resunits` | Housing units. |
| `sqft` | `sqft` | Estimated building floor area, square feet. |
| `val_struct` | `val_struct` | Structure value, dollars. |
| `val_cont` | `val_cont` | Contents value, dollars. |
| `val_vehic` | `val_vehic` | Vehicle value, dollars. |

## Damage category

`count_*` is the number of buildings in that NSI `st_damcat`. `val_struct_*` is their structure value. Occupancy types are the finer codes inside these categories.

| Field | `st_damcat` | Meaning |
| --- | --- | --- |
| `count_res`, `val_struct_res` | `RES` | Residential |
| `count_com`, `val_struct_com` | `COM` | Commercial |
| `count_ind`, `val_struct_ind` | `IND` | Industrial |
| `count_pub`, `val_struct_pub` | `PUB` | Public |

## Occupancy counts

Each `occ_*` field is the number of buildings with that NSI `occtype`. The prefix is lowercase and hyphens in the NSI code are underscores, so `RES1-2SWB` is `occ_res1_2swb`.

| Field | NSI code | Description |
| --- | --- | --- |
| `occ_res1_1snb` | RES1-1SNB | Single family, 1 story, no basement |
| `occ_res1_1swb` | RES1-1SWB | Single family, 1 story, with basement |
| `occ_res1_2snb` | RES1-2SNB | Single family, 2 story, no basement |
| `occ_res1_2swb` | RES1-2SWB | Single family, 2 story, with basement |
| `occ_res1_3snb` | RES1-3SNB | Single family, 3 story, no basement |
| `occ_res1_3swb` | RES1-3SWB | Single family, 3 story, with basement |
| `occ_res2` | RES2 | Manufactured home |
| `occ_res3a` | RES3A | Multi-family, 2 units |
| `occ_res3b` | RES3B | Multi-family, 3–4 units |
| `occ_res3c` | RES3C | Multi-family, 5–10 units |
| `occ_res3d` | RES3D | Multi-family, 10–19 units |
| `occ_res3e` | RES3E | Multi-family, 20–50 units |
| `occ_res3f` | RES3F | Multi-family, 50 or more units |
| `occ_res4` | RES4 | Hotel |
| `occ_res5` | RES5 | Institutional dormitory |
| `occ_res6` | RES6 | Nursing home |
| `occ_com1` | COM1 | Retail |
| `occ_com2` | COM2 | Wholesale |
| `occ_com3` | COM3 | Personal and repair services |
| `occ_com4` | COM4 | Professional and technical services |
| `occ_com5` | COM5 | Bank |
| `occ_com6` | COM6 | Hospital |
| `occ_com7` | COM7 | Medical office |
| `occ_com8` | COM8 | Entertainment and recreation |
| `occ_com9` | COM9 | Theater |
| `occ_com10` | COM10 | Garage |
| `occ_ind1` | IND1 | Heavy industrial |
| `occ_ind2` | IND2 | Light industrial |
| `occ_ind3` | IND3 | Food, drug, and chemical |
| `occ_ind4` | IND4 | Metals and minerals processing |
| `occ_ind5` | IND5 | High technology |
| `occ_ind6` | IND6 | Construction |
| `occ_agr1` | AGR1 | Agriculture |
| `occ_rel1` | REL1 | Church |
| `occ_gov1` | GOV1 | Government services |
| `occ_gov2` | GOV2 | Emergency response |
| `occ_edu1` | EDU1 | School |
| `occ_edu2` | EDU2 | College or university |

NSI also defines `RES1-SLNB` and `RES1-SLWB` (split-level single family, without and with a basement). This extract has no buildings in those classes, so the grid has no columns for them.

## Gridded EIF population

These columns are copied from `eif_ageracesex_h3_res7.parquet`. The source is the Census Bureau Gridded Environmental Impacts Frame, 2025 realtime age-by-race-by-sex file:

https://www2.census.gov/ces/gridded_eif/gridded_eif_pop_ageracesex_2025_realtime.parquet

Each source row is a privacy-protected population count for one 0.01-degree grid point, one age group, one race/ethnicity, and one sex. The count used here is `n_noise_postprocessed`. Counts can be fractional. They are not a Decennial Census enumeration, and they will not match `pop_night` or `pop_day` from the NSI.

A grid point is placed in the H3 resolution 7 cell that contains its centroid. Counts in the same cell are summed. Age, sex, and race totals equal the sum of the matching cross-tab columns. `eif_pop` equals each of those totals.

| Field | Meaning |
| --- | --- |
| `eif_pop` | Total population in the cell. |
| `eif_under18` | Age group `Under 18`. |
| `eif_age19_65` | Age group `19-65`, the label used in this file. |
| `eif_over65` | Age group `Over 65`. |
| `eif_age_missing` | Age group `Missing Age`. |
| `eif_female` | Sex `F`. |
| `eif_male` | Sex `M`. |
| `eif_sex_missing` | Sex `Missing Gender`. |
| `eif_white` | Non-Hispanic White. File value `White`. |
| `eif_black` | Non-Hispanic Black. File value `Black`. |
| `eif_hispanic` | Hispanic, any race. File value `Hispanic`. |
| `eif_asian` | Non-Hispanic Asian. File value `Asian`. |
| `eif_aian` | Non-Hispanic American Indian and Alaska Native. File value `AIAN`. |
| `eif_other` | Other race, multiracial, or missing race. File value `Other/Unknown`. |
| `eif_{race}_{age}_{sex}` | Population in that race, age, and sex group. Example: `eif_black_over65_female`. |

The race-by-income file is joined as well. Columns that would otherwise repeat the age-race-sex names are prefixed with `eif_income_`. Decile columns are unchanged.

| Field | Meaning |
| --- | --- |
| `eif_income_pop` | Total population in the race-by-income file. |
| `eif_income_white`, `eif_income_black`, `eif_income_hispanic`, `eif_income_asian`, `eif_income_aian`, `eif_income_other` | Race/ethnicity totals from the race-by-income file. |
| `eif_inc1` … `eif_inc10` | Household income deciles. Decile 1 is the lowest tenth and decile 10 is the highest. |
| `eif_inc0` | Income code 0. Kept separate because the Census documentation does not define it. |
| `eif_{race}_inc{decile}` | Population in that race/ethnicity and income group. Example: `eif_black_inc1`. |
