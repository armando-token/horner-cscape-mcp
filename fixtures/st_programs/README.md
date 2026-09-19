# IEC 61131-3 Structured Text Benchmark Program Fixtures

Collection of complete, self-contained IEC 61131-3 Structured Text `PROGRAM` units designed for automated testing, simulation, parser benchmarking, and Cscape 10.2 error-check compilation.

Strictly adheres to **Pure Structured Text** standards (zero ladder artifacts, contacts, or coils). Fully verified by AST lexical parsing (`STParser`), block-nesting validation (`IECValidator`), and static semantic safety analysis (`STValidator`).

---

## 🛠️ Program Fixture Catalog

| Program Name | POU Kind | File | Description |
| :--- | :--- | :--- | :--- |
| `PumpAlternationApp` | `PROGRAM` | [`pump_alternation_program.st`](file:///C:/HornerAI/horner-cscape-mcp/fixtures/st_programs/pump_alternation_program.st) | Duplex sump pump cyclic controller with 4 float switches, wear-hour alternation, and overload lockout. |
| `PIDTemperatureApp` | `PROGRAM` | [`pid_temp_control_program.st`](file:///C:/HornerAI/horner-cscape-mcp/fixtures/st_programs/pid_temp_control_program.st) | Industrial oven heating control with raw ADC conversion, anti-windup PID, PWM SSR output, and over-temp latch. |
| `ConveyorSorterApp` | `PROGRAM` | [`conveyor_sorter_program.st`](file:///C:/HornerAI/horner-cscape-mcp/fixtures/st_programs/conveyor_sorter_program.st) | Packaging sorter with infeed photoeye, optical part height classification, pneumatic diverters, and jam timer. |
| `AnalogScalingApp` | `PROGRAM` | [`analog_scaling_program.st`](file:///C:/HornerAI/horner-cscape-mcp/fixtures/st_programs/analog_scaling_program.st) | 4-channel analog transmitter conditioner (Pressure, Temp, Flow, Level) with wire-break and short detection. |
| `BatchReactorApp` | `PROGRAM` | [`batch_reactor_program.st`](file:///C:/HornerAI/horner-cscape-mcp/fixtures/st_programs/batch_reactor_program.st) | Sequential multi-phase batch synthesis (Charge, Dose, Heat/Mix, Soak, Cool, Drain) with safety abort. |
| `TrafficControlApp` | `PROGRAM` | [`traffic_control_program.st`](file:///C:/HornerAI/horner-cscape-mcp/fixtures/st_programs/traffic_control_program.st) | Dual-phase intersection controller with vehicle inductive loops, pedestrian walk calls, and green conflict monitor. |

---

## 🧪 Automated Verification

All fixtures are covered by the unit test suite in [`tests/test_st_applications_library.py`](file:///C:/HornerAI/horner-cscape-mcp/tests/test_st_applications_library.py):

```bash
pytest tests/test_st_applications_library.py
```
