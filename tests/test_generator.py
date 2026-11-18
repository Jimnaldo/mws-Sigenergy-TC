from datetime import datetime, timezone

import pytest
from test_cloud import PrivateClient

from custom_components.sigen_hybrid.core.cloud import CloudAdapter
from custom_components.sigen_hybrid.core.generator import generator_live_data, generator_settings_data

SETTINGS = {
    "stationId": 1,
    "enableGenerator": True,
    "startControlType": 1,
    "operationMode": 0,
    "ratedPower": 6,
    "coolingEnable": False,
    "bestPowerDuty": 50,
    "manualSwitch": False,
    "cutOffSoc": 95,
    "minimumLoadRatio": 0,
    "loadTouParamsDTO": {
        "socEnable": True,
        "touEnable": True,
        "touNum": 1,
        "touTimeParamsDTOList": [
            {
                "startTime": "00:00",
                "duration": 1440,
                "periodConfig": [1, 2, 3, 4, 5, 6, 7],
                "autoPowerOnThresholdSoc": 35,
                "autoPowerOffThresholdSoc": 65,
                "maxLoadRatio": 100,
            }
        ],
    },
    "exerciseParamsDTO": {"startEnable": False},
    "loadConditionParamsDTO": {"startStopByLoadPower": False},
    "onOffSwitchParams": {
        "overVoltageTransferPoint": 253,
        "underVoltageTransferPoint": 184,
        "overFrequencyTransferPoint": 55,
        "underFrequencyTransferPoint": 45,
    },
}

LIVE = [
    {"paramKey": "Current", "paramValueUnit": "A", "aphaseValue": "4.62", "bphaseValue": "4.68", "cphaseValue": "4.41"},
    {"paramKey": "Active Power", "paramValueUnit": "kW", "aphaseValue": 0.99, "bphaseValue": 1.002, "cphaseValue": 0.976},
    {"paramKey": "Voltage Frequency", "paramValueUnit": "Hz", "paramValue": 50},
]


def test_settings_are_mapped_to_a_closed_read_only_shape():
    data = generator_settings_data(SETTINGS)
    assert data["present"] is True
    assert data["operation_mode"] == "Auto"
    assert data["rated_power_kw"] == 6
    assert data["max_power_percent"] == 50
    assert data["charging_stop_soc"] == 95
    period = data["time_of_use"]["periods"][0]
    assert period == {
        "start": "00:00",
        "duration_minutes": 1440,
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "start_soc": 35,
        "stop_soc": 65,
        "max_load_percent": 100,
    }
    assert data["transfer"]["under_voltage_v"] == 184
    assert "stationId" not in str(data)


@pytest.mark.parametrize("raw", [None, {}, [], "x", {"enableGenerator": False}])
def test_missing_or_disabled_generator_is_not_present(raw):
    assert generator_settings_data(raw)["present"] is False


def test_invalid_numbers_are_omitted_not_guessed():
    data = generator_settings_data({**SETTINGS, "cutOffSoc": 140, "bestPowerDuty": True, "ratedPower": "nan"})
    assert data["charging_stop_soc"] is None
    assert data["max_power_percent"] is None
    assert data["rated_power_kw"] is None


def test_live_power_is_the_sum_of_phase_active_power():
    live = generator_live_data(LIVE, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert live["power_kw"] == pytest.approx(2.968)
    assert live["rows"][0]["phases"] == {"a": 4.62, "b": 4.68, "c": 4.41}


def test_live_power_in_watts_is_converted():
    rows = [{"paramKey": "Active Power", "paramValueUnit": "W", "paramValue": 2500}]
    assert generator_live_data(rows, datetime(2026, 1, 1, tzinfo=timezone.utc))["power_kw"] == 2.5


class GeneratorClient(PrivateClient):
    def __init__(self, settings=SETTINGS):
        super().__init__()
        self.settings, self.setting_reads = settings, 0

    async def instant_manual_control(self):
        from types import SimpleNamespace

        return SimpleNamespace(enabled=False, end_time=None)

    async def battery_power_limit(self):
        return {}

    async def prediction_data(self):
        return {}

    async def current_operational_mode(self):
        return 1

    async def generator_settings(self):
        self.setting_reads += 1
        return self.settings

    async def generator_real_time(self):
        return LIVE


@pytest.mark.asyncio
async def test_cloud_details_include_read_only_generator():
    client = GeneratorClient()
    cloud = CloudAdapter(client, "synthetic-station", unofficial_opt_in=True)
    data = await cloud.refresh()
    assert data["generator"]["settings"]["operation_mode"] == "Auto"
    assert data["generator"]["live"]["power_kw"] == pytest.approx(2.968)


@pytest.mark.asyncio
async def test_plant_without_generator_is_rechecked_daily_not_every_cycle():
    client = GeneratorClient(settings={})
    cloud = CloudAdapter(client, "synthetic-station", unofficial_opt_in=True)
    assert (await cloud.refresh())["generator"] == {}
    cloud._details_fetched = float("-inf")
    cloud._fetched = float("-inf")
    await cloud.refresh()
    assert client.setting_reads == 1


def test_unknown_native_codes_are_not_guessed():
    data = generator_settings_data({**SETTINGS, "operationMode": 7, "startControlType": "x"})
    assert data["operation_mode"] == "code 7"
    assert data["start_control_type"] == "x"


def test_phase_text_with_units_is_parsed():
    rows = [{"paramKey": "Active Power", "paramValueUnit": "kW", "aphaseValueText": "0.990 kW", "bphaseValueText": "1.002", "cphaseValueText": "0.976 kW"}]
    assert generator_live_data(rows, datetime(2026, 1, 1, tzinfo=timezone.utc))["power_kw"] == pytest.approx(2.968)


def test_unit_is_taken_from_value_text_when_the_unit_field_is_empty():
    rows = [{"paramKey": "Active Power", "paramValueUnit": "", "aphaseValueText": "1.002 kW", "bphaseValueText": "1.002 kW", "cphaseValueText": "1.018 kW"}]
    live = generator_live_data(rows, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert live["rows"][0]["unit"] == "kW"
    assert live["power_kw"] == pytest.approx(3.022)


def test_unitless_active_power_in_kw_range_is_accepted():
    rows = [{"paramKey": "Active Power", "aphaseValue": 1.002, "bphaseValue": 1.002, "cphaseValue": 1.018}]
    assert generator_live_data(rows, datetime(2026, 1, 1, tzinfo=timezone.utc))["power_kw"] == pytest.approx(3.022)


def test_unitless_active_power_in_watt_range_is_not_guessed():
    rows = [{"paramKey": "Active Power", "aphaseValue": 1002, "bphaseValue": 1002, "cphaseValue": 1018}]
    assert "power_kw" not in generator_live_data(rows, datetime(2026, 1, 1, tzinfo=timezone.utc))


# --- writes -----------------------------------------------------------------
from custom_components.sigen_hybrid.core.errors import CapabilityError, SafetyError  # noqa: E402
from custom_components.sigen_hybrid.core.generator import generator_update, verify_update  # noqa: E402

NATIVE = {**SETTINGS, "operationMode": 0, "startControlType": 1}


def test_switching_to_manual_changes_only_the_mode():
    new, changes = generator_update(NATIVE, "operation_mode", "manual")
    assert changes == [("operationMode", 0, 1)]
    assert {k: v for k, v in new.items() if k != "operationMode"} == {k: v for k, v in NATIVE.items() if k != "operationMode"}


def test_back_to_auto_releases_a_latched_manual_start():
    manual = {**NATIVE, "operationMode": 1, "manualSwitch": True}
    new, changes = generator_update(manual, "operation_mode", "auto")
    assert new["operationMode"] == 0 and new["manualSwitch"] is False
    assert ("manualSwitch", True, False) in changes


def test_native_string_mode_codes_stay_strings():
    new, _ = generator_update({**NATIVE, "operationMode": "0"}, "operation_mode", "manual")
    assert new["operationMode"] == "1"


def test_start_is_refused_in_auto_mode():
    with pytest.raises(SafetyError):
        generator_update(NATIVE, "generator_start", True)


def test_start_in_manual_mode():
    new, changes = generator_update({**NATIVE, "operationMode": 1}, "generator_start", True)
    assert new["manualSwitch"] is True and changes == [("manualSwitch", False, True)]


def test_stop_soc_must_stay_above_start_soc():
    with pytest.raises(SafetyError):
        generator_update(NATIVE, "stop_soc", 30)
    with pytest.raises(SafetyError):
        generator_update(NATIVE, "start_soc", 65)
    new, changes = generator_update(NATIVE, "start_soc", 40)
    assert new["loadTouParamsDTO"]["touTimeParamsDTOList"][0]["autoPowerOnThresholdSoc"] == 40
    assert NATIVE["loadTouParamsDTO"]["touTimeParamsDTOList"][0]["autoPowerOnThresholdSoc"] == 35


def test_unknown_period_and_bad_values_are_refused():
    for setting, value in [("start_soc", {"period": 2, "value": 30}), ("charging_stop_soc", 101), ("charging_stop_soc", 9.5),
                           ("max_power_percent", 0), ("time_of_use", "yes"), ("operation_mode", "on"), ("rated_power", 5)]:
        with pytest.raises(SafetyError):
            generator_update(NATIVE, setting, value)


def test_no_generator_is_a_capability_error():
    with pytest.raises(CapabilityError):
        generator_update({}, "operation_mode", "auto")


def test_unchanged_value_has_no_changes():
    assert generator_update(NATIVE, "charging_stop_soc", 95)[1] == []


def test_readback_verification():
    new, changes = generator_update(NATIVE, "start_soc", 40)
    assert verify_update(new, changes)
    assert not verify_update(NATIVE, changes)
    manual, changes = generator_update(NATIVE, "operation_mode", "manual")
    assert verify_update({**manual, "operationMode": "1"}, changes)
