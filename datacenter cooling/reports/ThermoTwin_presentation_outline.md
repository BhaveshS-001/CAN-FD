# ThermoTwin — Presentation Outline

## Slide 1 — Title
**ThermoTwin: AI-assisted data-center cooling optimization**  
Research synthesis and illustrative cooling-control simulation.

## Slide 2 — Problem
- IT workloads and heat generation vary over time and across racks.
- Fixed cooling can waste energy or miss local thermal excursions.
- Objective: minimize cooling overhead subject to thermal and reliability constraints.

## Slide 3 — Research landscape
- Reinforcement learning for adaptive cooling control.
- Thermal forecasting for early hotspot detection.
- Sensor fault detection and physics-informed ML.
- Digital twins for testing operating strategies.
- Liquid/hybrid cooling, non-uniform load distribution and heat reuse.

## Slide 4 — Proposed architecture
Sensors → edge acquisition → thermal state estimation/digital twin → forecasting and fault detection → constrained optimizer → cooling actuators.  
Safety layer: hard limits, fallback setpoints and operator override.

## Slide 5 — Simulation design
- Same synthetic 24-hour workload for both strategies.
- Fixed cooling baseline versus adaptive rule-based controller.
- Inputs: mean IT load, ambient temperature and cooling aggressiveness.
- Outputs: temperature, cooling power, cooling energy and illustrative PUE.

## Slide 6 — Evaluation metrics
- Cooling energy (kWh).
- Peak and high-percentile rack inlet temperature.
- Hours above the chosen thermal threshold.
- PUE, only when total facility and IT energy are measured.
- Energy reduction is valid only when thermal constraints remain satisfied.

## Slide 7 — Demo walkthrough
Run the Python simulation, inspect the generated temperature and cooling-power plots, then vary load and ambient conditions. Explain how the energy/temperature trade-off changes.

## Slide 8 — Limitations
- Synthetic workload and simplified response curves.
- No CFD, real sensor data or calibrated equipment model.
- Controller is rule-based, not trained RL.
- PUE is illustrative, not metered.
- No claim of real-world savings.

## Slide 9 — Conclusion and next steps
- The demonstrator connects thermal monitoring with constrained cooling decisions.
- Next: analyze the Zenodo experimental archive, establish baseline-versus-retrofit thermal evidence, then evaluate forecasting only if data support it.
