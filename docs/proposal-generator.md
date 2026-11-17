# Feature request: generator support (device + owner settings)

## Situation

Off-grid SigenStor plant with a fuel generator connected to the Energy Gateway. In the mySigen
owner app the generator appears under **Device → Sigen System Device → Generator**, with live
per-phase values and an owner-editable **Generator Settings** page. Sigenergy TC 0.2.10 (cloud
connection, owner account):

- does not list the generator under **Devices**;
- shows the generator power under the Gateway's **Grid side info** while **Generator side info**
  stays empty, and reports the plant as *On Grid*;
- offers no generator owner settings (`owner_setting` has no generator key).

## Native API used by the mySigen web client (owner account)

| Purpose | Method | Path |
| --- | --- | --- |
| Generator settings (read) | GET | `/device/tp-device/generator/v2/settings?stationId=…` |
| Generator settings (save) | POST (JSON body = full settings DTO) | `/device//tp-device/generator/v2/settings` (sic, double slash in client) |
| Live values | GET | `/device/tp-device/generator/v2/real-time-info?stationId=…` |
| Generator info | GET | `/device/system/device/generator/info?stationId=…` |
| Supported devices | GET | `/device/tp-device/generator/v2/support-devices?stationId=…` |
| Device cards | GET | `/third-party-device/tp-device/manage/card/{static,dynamic}-info?stationId=…` |

Write method inferred from the client's HTTP helper (not yet confirmed by a live save).

### Settings DTO (field names from the client's decoder)

```
stationId, enableGenerator, startControlType, operationMode, ratedPower, coolingEnable,
bestPowerDuty (max power duty %), manualSwitch, cutOffSoc (generator charging stop SOC %),
minimumLoadRatio (min power duty %),
loadTouParamsDTO { socEnable, touEnable, touNum,
  touTimeParamsDTOList[ { startTime, duration, periodConfig[weekdays],
                          autoPowerOnThresholdSoc, autoPowerOffThresholdSoc, maxLoadRatio } ] },
exerciseParamsDTO { startEnable, startInterval, startDay, startTime, runTime },
loadConditionParamsDTO { startStopByLoadPower, loadPowerMeasurementType,
  startTotalLoadPowerThreshold, endTotalLoadPowerThreshold,
  startPhaseLoadPowerThreshold, endPhaseLoadPowerThreshold },
onOffSwitchParams { overVoltageTransferPoint, underVoltageTransferPoint,
  overFrequencyTransferPoint, underFrequencyTransferPoint, voltageBaseValue, frequencyBaseValue }
```

Example values shown by the owner app on a test plant: two-wire start, Auto, rated 6 kW,
max duty 50 %, min duty 0 %, charging stop SOC 95 %, transfer points 253 V / 184 V / 55 Hz / 45 Hz,
exercise off, load condition off, TOU on: one period 00:00–24:00 all days, auto start 35 %,
auto stop 65 %, max load 100 %.

## Proposed scope

1. **Read-only first:** generator as a device (Devices tab, house/flow node), live per-phase
   values, settings shown in Settings → Energy settings → Generator.
2. **Owner writes, closed allowlist:** `generator` owner setting changing only
   `operationMode`, `cutOffSoc`, `bestPowerDuty`, `minimumLoadRatio`, `loadTouParamsDTO.touEnable`
   and the TOU periods' start/stop SOC, max load and windows. All other DTO fields are preserved
   from the fresh read (incl. start control type, rated power, transfer points). Same
   preview → write-ahead journal → readback flow as the existing native settings.
   Stop SOC must stay above start SOC and both within the owner SOC bounds.
3. Optionally map the Gateway's generator-side values so the plant is not reported as on-grid
   when only a generator is connected.

Happy to contribute an implementation PR after agreement on scope.
