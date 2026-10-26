# Market data fixtures

Real responses captured on 2026-10-26 from the live APIs, trimmed.

- `boi_rate.csv`: `MNT_RIB_BOI_D?startperiod=2021-12-01&endperiod=2023-06-30&format=csv` on
  `https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/BR/1.0/`, requested
  with `User-Agent: Mozilla/5.0`.
- `consumer_rate.csv`: `BNK_99010_LR_BIR_1893?startperiod=2025-09-01&format=csv` on the same host
  under `BIR/1.0/`: the 12 months 2025-09 to 2026-08.
- `cpi.json`: `https://api.cbs.gov.il/index/data/price?id=120010&format=json&download=false&startPeriod=10-2024&endPeriod=03-2025&PageSize=1000`.
  The span crosses the base change of 2025-01 (base 2022 average to base 2024 average).
- `cpi_overlap.json`: the same CBS request with `startPeriod=01-2022&endPeriod=06-2023`, overlapping
  the span of `boi_rate.csv` so that the refresh tests align real months.
