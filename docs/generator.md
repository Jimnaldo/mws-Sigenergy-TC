# Generator (read-only)

When the plant has a fuel generator registered in mySigen (**Device → Sigen System Device → Generator**), Sigenergy TC reads it through the owner account's cloud connection, at the 15-minute detail cadence:

| Native read | Path |
| --- | --- |
| Generator settings | `device/tp-device/generator/v2/settings?stationId=…` |
| Live values | `device/tp-device/generator/v2/real-time-info?stationId=…` |

Entities (device **Sigen generator**):

| Entity | Source |
| --- | --- |
| Generator power | Sum of the live per-phase active power (kW) |
| Generator operating mode | `operationMode`; attributes carry start control type, minimum power duty, cooling, transfer points, exercise and load condition |
| Generator start SOC / stop SOC | First time-of-use period's auto power-on/off SOC |
| Generator charging stop SOC | `cutOffSoc` |
| Generator maximum power duty | `bestPowerDuty` |
| Generator rated power | `ratedPower` |
| Generator time-of-use schedule | `touEnable`; attribute `periods` lists every window |

The card shows a **Generator** tile under Devices and a detail page. Nothing is written: change generator settings in the mySigen app. Unknown or malformed native values are left empty, not guessed. A plant without a generator is re-checked once a day.

Writes are proposed separately (closed allowlist, preview, write-ahead journal and readback), see `proposal-generator.md`.
