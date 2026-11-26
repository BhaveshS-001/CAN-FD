# ThermoTwin: Illustrative Cooling-Control Demonstrator

> **Evidence status:** This document describes a synthetic, simplified simulation. It does not report measured facility savings, a trained AI model, or a validated digital twin.

## Objective

Demonstrate how a data-center cooling controller can compare a fixed cooling strategy with a load- and temperature-aware adaptive strategy. The design objective is to reduce cooling energy while maintaining rack thermal conditions within an explicitly defined operating envelope.

## Why this problem matters

IT equipment converts electrical power into heat. Cooling must remove that heat without creating avoidable facility overhead. IT load varies over time, and heat distribution can be spatially non-uniform. A controller that relies only on a fixed setpoint may overcool some operating periods and still fail to anticipate localized thermal excursions.

## Proposed architecture

1. **Telemetry:** rack inlet/outlet temperature, IT load and power, fan speed, supply/return temperature, and coolant flow/pressure where liquid cooling is installed.
2. **Edge acquisition:** timestamp alignment, range checks, missing-value handling and filtering.
3. **Thermal state estimation:** estimate rack thermal state from measurements and a calibrated plant model.
4. **Forecasting and fault detection:** predict short-horizon temperature excursions and flag stuck, drifting or inconsistent sensors.
5. **Constrained optimizer:** select supply-temperature, fan-speed or coolant-flow targets subject to thermal and equipment limits.
6. **Safety layer:** hard interlocks, bounded actuator commands, operator override and deterministic fallback control.
7. **KPI dashboard:** temperature distributions, cooling energy, facility/IT energy and alarms.

## Simulation methodology

The accompanying Python script generates a deterministic synthetic 24-hour IT-load profile and evaluates two illustrative strategies:

- **Fixed baseline:** fixed cooling response.
- **Adaptive rule-based:** cooling response varies with load, ambient temperature and a user-controlled aggressiveness parameter.

The model uses algebraic response curves. It is deliberately simple and transparent; it is not CFD, a chiller performance model, a calibrated first-order plant model, or reinforcement learning.

### Metrics

- Cooling energy (kWh) = mean cooling power (kW) × duration (h).
- Peak inlet temperature (°C) and hours above the illustrative 27 °C threshold.
- PUE = total facility energy / IT equipment energy. The script's PUE is only an illustrative estimate based on assumed IT and cooling power; it is not a measured facility PUE.
- Cooling-energy change (%) = (baseline energy − adaptive energy) / baseline energy × 100.

A lower energy estimate is not an improvement if the thermal constraint is violated.

## Literature alignment

The supplied research collection covers complementary themes: reinforcement-learning cooling control, cooling-system fault detection, physics-informed machine learning, digital-twin architecture, thermal forecasting, HVAC optimization, non-uniform load distribution, liquid cooling and heat reuse. These themes motivate the architecture, but the demonstrator does not reproduce the methods or results of those papers.

The repository README's dataset register should remain the source of truth for dataset provenance and limitations:

- **D1 (Epoch AI):** facility-scale estimates and separate chiller/cooling-tower equipment reference tables. Equipment reference data are not measured cooling energy or verified installed-site inventories.
- **D2 (Zenodo):** experimental and CFD data for an air-cooled data center. The experimental archive is appropriate for descriptive baseline-versus-retrofit thermal comparison after metadata and units are checked.
- **D3 (Kula et al., 2025):** forecasting methodology paper; its underlying operational data are available from the corresponding author on request.
- **D4 (Kaggle):** candidate facility dataset; inspect schema, provenance, units and license before use.

Do not concatenate D1–D4 into one table: they represent different entities, spatial scales, time resolutions and measurement processes.

## Limitations

- Workload and outputs are synthetic.
- No facility telemetry, CFD field, rack geometry or equipment performance curves are used.
- The adaptive strategy is rule-based; no ML/RL model is trained.
- The 27 °C line is an illustrative threshold for visualization, not a universal equipment safety limit.
- The estimated PUE is not a substitute for metered facility and IT energy.

## Validation plan

1. Inspect D2 archive metadata, sensor mapping, units, sampling interval and equivalent operating conditions.
2. Compare previous and retrofitted thermal measurements sensor-by-sensor; report mean, maximum and high-percentile temperatures.
3. Use D1 only for facility-scale context and separate equipment-reference analysis.
4. Validate D4 before assigning it an analytical role.
5. Only train forecasting models if a sufficiently long, correctly timestamped time series is available; use chronological splits and compare against persistence/linear baselines.
6. Make energy-optimization claims only if cooling-energy and relevant operational measurements are available.

## Reproduction

From the repository root:

```bash
python -m pip install numpy pandas matplotlib
python "datacenter cooling/src/thermotwin_simulation.py"
```

Outputs are written to `datacenter cooling/results/`. The default run is deterministic. Change conditions with `--it-load`, `--ambient` and `--aggressiveness`.

