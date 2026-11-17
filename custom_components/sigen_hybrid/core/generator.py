"""Read-only generator support from the owner app's generator pages.

The mySigen owner client reads a generator's settings and live values from two
fixed GET paths. Values are validated and normalised here; nothing is written.
Unknown or malformed fields are omitted rather than guessed.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

SETTINGS_PATH = "device/tp-device/generator/v2/settings"
REAL_TIME_PATH = "device/tp-device/generator/v2/real-time-info"

# Native codes observed in the owner app (code -> app label). Unknown codes
# are shown as "code N" instead of being guessed.
OPERATION_MODES = {"0": "Auto"}
START_CONTROL_TYPES = {"1": "two-wire-start"}

_TIME = re.compile(r"(?:[01]\d|2[0-4]):[0-5]\d")


_LEADING_NUMBER = re.compile(r"\s*(-?\d+(?:\.\d+)?)")


def _number(value, low=None, high=None):
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, str):
        match = _LEADING_NUMBER.match(value)
        if not match or value[match.end():].strip() not in ("", "kW", "W", "A", "V", "Hz", "%", "kWh", "kvar", "kVar"):
            return None
        value = match.group(1)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result):
        return None
    if (low is not None and result < low) or (high is not None and result > high):
        return None
    return int(result) if result.is_integer() else result


def _flag(value):
    if type(value) is bool:
        return value
    if value in (0, 1) and type(value) is int:
        return bool(value)
    return None


def _text(value, limit=40):
    if isinstance(value, str) and 0 < len(value) <= limit:
        return value
    if type(value) is int:
        return str(value)
    return None


def _label(value, labels):
    code = _text(value)
    if code is None:
        return None
    return labels.get(code, code if not code.isdigit() else f"code {code}")


def _clock(value):
    if isinstance(value, str) and _TIME.fullmatch(value):
        return value
    number = _number(value, 0, 1440)
    if number is not None:
        return f"{int(number) // 60:02d}:{int(number) % 60:02d}"
    return None


def _weekdays(value):
    if not isinstance(value, list) or len(value) > 7:
        return None
    days = []
    for item in value:
        day = _number(item, 0, 7)
        if day is None:
            return None
        days.append(int(day))
    return days


def _period(raw):
    if not isinstance(raw, dict):
        return None
    return {
        "start": _clock(raw.get("startTime")),
        "duration_minutes": _number(raw.get("duration"), 0, 1440),
        "weekdays": _weekdays(raw.get("periodConfig")),
        "start_soc": _number(raw.get("autoPowerOnThresholdSoc"), 0, 100),
        "stop_soc": _number(raw.get("autoPowerOffThresholdSoc"), 0, 100),
        "max_load_percent": _number(raw.get("maxLoadRatio"), 0, 100),
    }


def generator_settings_data(raw):
    """Map the native settings DTO to a closed, read-only shape."""
    if not isinstance(raw, dict) or not raw:
        return {"present": False}
    tou = raw.get("loadTouParamsDTO") if isinstance(raw.get("loadTouParamsDTO"), dict) else {}
    periods = tou.get("touTimeParamsDTOList")
    exercise = raw.get("exerciseParamsDTO") if isinstance(raw.get("exerciseParamsDTO"), dict) else {}
    load = raw.get("loadConditionParamsDTO") if isinstance(raw.get("loadConditionParamsDTO"), dict) else {}
    switch = raw.get("onOffSwitchParams") if isinstance(raw.get("onOffSwitchParams"), dict) else {}
    enabled = _flag(raw.get("enableGenerator"))
    return {
        "present": enabled is not False,
        "enabled": enabled,
        "start_control_type": _label(raw.get("startControlType"), START_CONTROL_TYPES),
        "operation_mode": _label(raw.get("operationMode"), OPERATION_MODES),
        "manual_switch": _flag(raw.get("manualSwitch")),
        "rated_power_kw": _number(raw.get("ratedPower"), 0, 10000),
        "cooling": _flag(raw.get("coolingEnable")),
        "max_power_percent": _number(raw.get("bestPowerDuty"), 0, 100),
        "min_power_percent": _number(raw.get("minimumLoadRatio"), 0, 100),
        "charging_stop_soc": _number(raw.get("cutOffSoc"), 0, 100),
        "time_of_use": {
            "enabled": _flag(tou.get("touEnable")),
            "soc_enabled": _flag(tou.get("socEnable")),
            "periods": [item for item in (_period(row) for row in periods[:16]) if item]
            if isinstance(periods, list)
            else [],
        },
        "exercise": {
            "enabled": _flag(exercise.get("startEnable")),
            "interval_days": _number(exercise.get("startInterval"), 0, 366),
            "day": _number(exercise.get("startDay"), 0, 31),
            "start": _clock(exercise.get("startTime")),
            "run_minutes": _number(exercise.get("runTime"), 0, 1440),
        },
        "load_condition": {
            "enabled": _flag(load.get("startStopByLoadPower")),
            "measurement": _text(load.get("loadPowerMeasurementType")),
            "start_total_kw": _number(load.get("startTotalLoadPowerThreshold"), 0, 10000),
            "stop_total_kw": _number(load.get("endTotalLoadPowerThreshold"), 0, 10000),
            "start_phase_kw": _number(load.get("startPhaseLoadPowerThreshold"), 0, 10000),
            "stop_phase_kw": _number(load.get("endPhaseLoadPowerThreshold"), 0, 10000),
        },
        "transfer": {
            "over_voltage_v": _number(switch.get("overVoltageTransferPoint"), 0, 1000),
            "under_voltage_v": _number(switch.get("underVoltageTransferPoint"), 0, 1000),
            "over_frequency_hz": _number(switch.get("overFrequencyTransferPoint"), 0, 100),
            "under_frequency_hz": _number(switch.get("underFrequencyTransferPoint"), 0, 100),
        },
    }


_POWER_UNITS = {"kW": 1, "W": 0.001}


def generator_live_data(rows, now: datetime):
    """Keep labelled native rows, with per-phase values where supplied."""
    result = {"rows": [], "retrieved_at": now.isoformat()}
    if not isinstance(rows, list):
        return result
    for row in rows[:40]:
        if not isinstance(row, dict) or not isinstance(row.get("paramKey"), str):
            continue
        key = row["paramKey"][:80]
        unit = row.get("paramValueUnit") if isinstance(row.get("paramValueUnit"), str) else ""
        if not unit:
            # Some rows carry the unit only in their value texts ("1.002 kW").
            for field in ("paramValueText", "aphaseValueText", "bphaseValueText", "cphaseValueText"):
                text = row.get(field)
                match = _LEADING_NUMBER.match(text) if isinstance(text, str) else None
                suffix = text[match.end():].strip() if match else ""
                if suffix:
                    unit = suffix
                    break
        item = {
            "key": key,
            "unit": unit[:12],
            "value": _number(row.get("paramValue")),
            "text": _text(row.get("paramValueText"), 60),
        }
        phases = {}
        for phase in ("a", "b", "c"):
            value = _number(row.get(f"{phase}phaseValue"))
            if value is None:
                value = _number(row.get(f"{phase}phaseValueText"))
            if value is not None:
                phases[phase] = value
        if phases:
            item["phases"] = phases
        result["rows"].append(item)
    for item in result["rows"]:
        if "active" in item["key"].lower() and "power" in item["key"].lower():
            unit = item["unit"]
            if not unit:
                # The owner app labels these rows in kW. Without a unit, only
                # accept magnitudes that cannot be watts of a running generator.
                readings = list(item.get("phases", {}).values()) or [item["value"]]
                readings = [value for value in readings if value is not None]
                unit = "kW" if readings and max(abs(value) for value in readings) < 200 else ""
            if unit not in _POWER_UNITS:
                break
            scale = _POWER_UNITS[unit]
            if item.get("phases"):
                result["power_kw"] = round(sum(item["phases"].values()) * scale, 3)
            elif item["value"] is not None:
                result["power_kw"] = round(item["value"] * scale, 3)
            break
    return result
