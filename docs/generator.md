# Generator

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

## Changing generator settings

With cloud control enabled, an administrator can change a closed set of fields with the `sigen_hybrid.generator_setting` action (and from the Generator detail page: Auto/Manual, Start/Stop):

| `setting` | `value` | Native field |
| --- | --- | --- |
| `operation_mode` | `auto` / `manual` | `operationMode` (0/1). Returning to Auto also releases a manual start. |
| `generator_start` | `true` / `false` | `manualSwitch`; start only in Manual |
| `start_soc` / `stop_soc` | whole % (period 1) or `{period, value}` | TOU auto power-on/off SOC; stop must stay above start |
| `charging_stop_soc` | whole % | `cutOffSoc` |
| `max_power_percent` | 1–100 | `bestPowerDuty`, not below the minimum duty |
| `time_of_use` | `true` / `false` | `loadTouParamsDTO.touEnable` |

Every call reads the settings fresh, changes only that field and keeps every other native field as read. `dry_run: true` (default) returns the change without sending it. A real change is posted like the owner app does (`POST device/tp-device/generator/v2/settings` with the full settings), read back and reported as `applied` only when the new value is confirmed.
