# Data Centre Cooling Performance Study

## Executive summary

This study analyses the supplied experimental rack-exhaust measurements, cooling-unit telemetry and OpenFOAM post-processing outputs. Across 12 rack heights, the retrofitted-minus-previous exhaust-temperature difference averages **+1.13 °C**. The retrofitted measurements are hotter at 9 positions, cooler at 2 and unchanged at 1. The largest increase is **+3.3 °C at 40U**. These are observations, not proof that the retrofit caused the difference.

## Dataset provenance

| Evidence | Source archive | Valid use | Limitation |
|---|---|---|---|
| Experimental rack and cooling-unit telemetry | `data.tar.xz` | Compare supplied sessions and rack-height exhaust temperatures | Previous session: 03 June 2022, 15:00–17:00, door open; retrofitted: 12:40–14:40, door closed. Sessions are not synchronized. |
| CFD outputs and OpenFOAM cases | `data.tar.xz`, `fictiousScenarios.tar.xz`, `postProcess.tar.xz` | Inspect spatial temperature profiles and simulation setup | Scenario/geometry/boundary-condition mapping is required before quantitative validation. |
| Synthetic telemetry | `archive.zip` | Demonstrate a data/ML pipeline | 100,000 rows × 35 columns; explicitly synthetic, not measured facility data. |
| Data-centre inventory | `data_centers.zip` | Facility-scale context | Not rack-level temperature or cooling-energy telemetry. |

The paper's original 10,849-sample operational dataset is not included in the supplied files.

## Rack exhaust results

| Rack height | Previous (°C) | Retrofitted (°C) | Delta (°C) |
|---:|---:|---:|---:|
| 20U | 24.2 | 23.9 | -0.3 |
| 22U | 24.7 | 24.7 | 0.0 |
| 24U | 24.5 | 24.4 | -0.1 |
| 26U | 23.6 | 23.9 | +0.3 |
| 28U | 24.9 | 25.3 | +0.4 |
| 30U | 24.2 | 24.5 | +0.3 |
| 32U | 25.3 | 27.1 | +1.8 |
| 34U | 32.2 | 35.1 | +2.9 |
| 36U | 31.6 | 34.1 | +2.5 |
| 38U | 33.1 | 34.1 | +1.0 |
| 40U | 28.3 | 31.6 | +3.3 |
| 42U | 28.6 | 30.1 | +1.5 |

## Interpretation

- Several upper rack positions show higher measured exhaust temperatures in the retrofitted configuration.
- Door state and time of measurement differ between sessions, so load, ambient conditions and operating conditions may confound the comparison.
- Cooling-unit logs contain inlet, supply and return temperatures, fan speed, airflow and a field labelled cooling output. The field semantics must be confirmed before treating it as metered energy.
- No synchronized, calibrated cooling-energy series is supplied. Do not claim a percentage energy saving or compute PUE/COP from these files.

## CFD and modelling plan

The archives include OpenFOAM-8 case files using `buoyantPimpleFoam`, buoyancy treatment and the k-ω SST turbulence model, along with probe-line temperature outputs and rack power allocation tables. These support spatial thermal investigation. A defensible CFD validation needs matching geometry, boundary conditions, sensor coordinates, rack load and steady/transient assumptions.

Recommended modelling sequence:

1. Establish persistence and moving-average baselines.
2. Build Random Forest and XGBoost only after time alignment, quality checks and adequate coverage.
3. Use chronological train/validation/test splits; do not randomly split time-series rows.
4. Consider TiDE/TSMixer only with a longer, regularly sampled multivariate series.
5. Predict an upper thermal bound and retain operator override and hard safety limits.

Candidate inputs: IT/rack load, supply/return/inlet temperatures, airflow, fan speed, ambient temperature, humidity, rack position, door state and time features. Candidate target: maximum rack exhaust or hot-aisle temperature at a defined forecast horizon.

## Proposed architecture

`Sensors / BMS / CFD / inventory → ingestion → timestamp & unit validation → normalized data → thermal baseline + ML forecast → safety-bound evaluation → operator advisory dashboard`.

Closed-loop actuation is out of scope until longer synchronized operational data, validated plant models and fail-safe controls are available.

## Conclusion

The supplied data support a comparative thermal study and identify upper-rack positions that warrant investigation. The next experiment should repeat both configurations under matched IT load, door state, ambient conditions and cooling setpoints, while synchronizing calibrated temperature and power meters. Only then can causal retrofit effects and cooling-energy savings be assessed.
