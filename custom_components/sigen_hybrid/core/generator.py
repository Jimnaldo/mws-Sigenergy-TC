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
OPERATION_MODES = {"0": "Auto", "1": "Manual"}
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
        "generator_start": _flag(raw.get("manualSwitch")),
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


# --- Owner writes (closed allowlist) -------------------------------------
#
# The owner app saves the whole settings DTO with POST to the same path it
# reads. TC always starts from a fresh read, changes only the requested
# field(s), validates the result and verifies by reading back.

# Observed from the owner app: POST to the read path with exactly the fields of
# its own settings model. Sending the read response as-is (with its extra
# fields) is answered with code 13000 "device base not found".
WRITE_PATH = SETTINGS_PATH
_PAYLOAD_SHAPE = {
    "stationId": None,
    "enableGenerator": None,
    "startControlType": None,
    "operationMode": None,
    "ratedPower": None,
    "bestPowerDuty": None,
    "manualSwitch": None,
    "loadTouParamsDTO": {
        "socEnable": None,
        "touEnable": None,
        "touNum": None,
        "touTimeParamsDTOList": [
            {
                "startTime": None,
                "duration": None,
                "periodConfig": None,
                "autoPowerOnThresholdSoc": None,
                "autoPowerOffThresholdSoc": None,
                "maxLoadRatio": None,
            }
        ],
    },
    "cutOffSoc": None,
    "exerciseParamsDTO": {
        "startEnable": None,
        "startInterval": None,
        "startDay": None,
        "startTime": None,
        "runTime": None,
    },
    "loadConditionParamsDTO": {
        "startStopByLoadPower": None,
        "loadPowerMeasurementType": None,
        "startTotalLoadPowerThreshold": None,
        "endTotalLoadPowerThreshold": None,
        "startPhaseLoadPowerThreshold": None,
        "endPhaseLoadPowerThreshold": None,
    },
    "minimumLoadRatio": None,
    "coolingEnable": None,
    "onOffSwitchParams": {
        "overVoltageTransferPoint": None,
        "underVoltageTransferPoint": None,
        "overFrequencyTransferPoint": None,
        "underFrequencyTransferPoint": None,
    },
}


def _project(value, shape):
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return None
        return {key: _project(value.get(key), sub) for key, sub in shape.items()}
    if isinstance(shape, list):
        if not isinstance(value, list):
            return None
        return [_project(item, shape[0]) for item in value]
    return value


def owner_payload(dto, station_id):
    """The settings exactly as the owner app posts them: its own fields only.

    The read response omits the plant and the enabled flag; the owner app fills
    both in (an existing generator page is always enabled). Without them the
    cloud answers code 13000 "device base not found".
    """
    payload = _project(dto, _PAYLOAD_SHAPE)
    payload["stationId"] = int(station_id)
    if payload["enableGenerator"] is None:
        payload["enableGenerator"] = 1
    return payload
WRITABLE = (
    "operation_mode",
    "generator_start",
    "start_soc",
    "stop_soc",
    "charging_stop_soc",
    "max_power_percent",
    "time_of_use",
)
MODE_CODES = {"auto": 0, "manual": 1}


def _same_type(current, code):
    """Keep the native wire type (int or numeric string)."""
    return str(code) if isinstance(current, str) else code


def _soc(value):
    if type(value) is not int or not 0 <= value <= 100:
        from .errors import SafetyError

        raise SafetyError("SOC must be a whole percentage from 0 to 100")
    return value


def _period_value(value):
    """An int targets period 1; {"period": n, "value": x} targets period n."""
    from .errors import SafetyError

    if type(value) is int:
        return 0, value
    if isinstance(value, dict) and set(value) == {"period", "value"} and type(value["period"]) is int and value["period"] >= 1:
        return value["period"] - 1, value["value"]
    raise SafetyError("Give a whole SOC, or {period, value}")


def generator_update(raw, setting, value):
    """Return (new_dto, changes) for one closed generator setting.

    `changes` lists (field, old, new). Nothing outside the allowlist changes.
    """
    import copy

    from .errors import CapabilityError, SafetyError

    if setting not in WRITABLE:
        raise SafetyError("Unsupported generator setting")
    if not isinstance(raw, dict) or not raw or raw.get("enableGenerator") is False:
        raise CapabilityError("No generator is configured for this plant")
    new = copy.deepcopy(raw)
    changes = []

    def put(container, key, label, target):
        old = container.get(key)
        if old != target:
            container[key] = target
            changes.append((label, old, target))

    if setting == "operation_mode":
        if value not in MODE_CODES:
            raise SafetyError("Generator mode must be auto or manual")
        put(new, "operationMode", "operationMode", _same_type(raw.get("operationMode"), MODE_CODES[value]))
        if value == "auto":
            # Leaving manual must never leave a manual start latched.
            if new.get("manualSwitch") not in (None, False, 0):
                put(new, "manualSwitch", "manualSwitch", False if type(raw.get("manualSwitch")) is bool else 0)
    elif setting == "generator_start":
        if type(value) is not bool:
            raise SafetyError("Generator start must be true or false")
        mode = str(new.get("operationMode"))
        if value and mode != str(MODE_CODES["manual"]):
            raise SafetyError("Switch the generator to manual before starting it")
        put(new, "manualSwitch", "manualSwitch", value if type(raw.get("manualSwitch")) is not int else int(value))
    elif setting == "charging_stop_soc":
        put(new, "cutOffSoc", "cutOffSoc", _soc(value))
    elif setting == "max_power_percent":
        if type(value) is not int or not 1 <= value <= 100:
            raise SafetyError("Maximum power duty must be 1–100 %")
        minimum = new.get("minimumLoadRatio")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise SafetyError("Maximum power duty must not be below the minimum power duty")
        put(new, "bestPowerDuty", "bestPowerDuty", value)
    elif setting == "time_of_use":
        if type(value) is not bool:
            raise SafetyError("Time of use must be true or false")
        tou = new.get("loadTouParamsDTO")
        if not isinstance(tou, dict):
            raise SafetyError("Time-of-use settings are missing")
        put(tou, "touEnable", "loadTouParamsDTO.touEnable", value)
    else:  # start_soc / stop_soc
        index, soc = _period_value(value)
        soc = _soc(soc)
        periods = (new.get("loadTouParamsDTO") or {}).get("touTimeParamsDTOList")
        if not isinstance(periods, list) or not 0 <= index < len(periods) or not isinstance(periods[index], dict):
            raise SafetyError("That time-of-use period does not exist")
        period = periods[index]
        key = "autoPowerOnThresholdSoc" if setting == "start_soc" else "autoPowerOffThresholdSoc"
        put(period, key, f"touTimeParamsDTOList[{index}].{key}", soc)
        start, stop = period.get("autoPowerOnThresholdSoc"), period.get("autoPowerOffThresholdSoc")
        if isinstance(start, (int, float)) and isinstance(stop, (int, float)) and stop <= start:
            raise SafetyError("The stop SOC must be above the start SOC")
    return new, changes


def verify_update(readback, changes):
    """True when every changed field reads back with its new value."""

    def get(data, path):
        for part in path.replace("]", "").split("."):
            if "[" in part:
                name, index = part.split("[")
                data = (data or {}).get(name)
                data = data[int(index)] if isinstance(data, list) and int(index) < len(data) else None
            else:
                data = data.get(part) if isinstance(data, dict) else None
        return data

    def same(a, b):
        return str(a).lower() == str(b).lower() or (a in (0, False) and b in (0, False)) or (a in (1, True) and b in (1, True))

    path_of = {"operationMode": "operationMode", "manualSwitch": "manualSwitch", "cutOffSoc": "cutOffSoc", "bestPowerDuty": "bestPowerDuty"}
    for field, _old, new in changes:
        path = path_of.get(field) or field.replace("touTimeParamsDTOList", "loadTouParamsDTO.touTimeParamsDTOList")
        if not same(get(readback, path), new):
            return False
    return True
