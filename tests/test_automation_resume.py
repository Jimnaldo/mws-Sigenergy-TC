"""Owner pause after a manual setting, explicit resume, and opt-out of the pause.

Reproduces the field case where an administrator restored a native mode from the
UI (pausing automation) and a later Home Assistant automation that needed to
restore the same mode was refused with "Scheduling is paused after an owner change".
"""

from types import SimpleNamespace

import pytest
import voluptuous as vol
from test_manual_service_schema import manual_schema
from test_owner_settings import setup_settings

from custom_components.sigen_hybrid.core.models import Source

AI = {"mode": 1, "profile_id": -1}
SELF = {"mode": 0, "profile_id": -1}


async def run(controls, value, request_id, source, **kwargs):
    response = await controls.setting(
        "native_mode", value, request_id=request_id, source=source, dry_run=False, **kwargs
    )
    assert response["phase"] == "queued"
    await controls._job
    return controls.operation


async def test_manual_setting_pauses_automation_until_explicitly_resumed():
    controls, _, appliance, store, _ = setup_settings()
    assert (await run(controls, SELF, "owner", Source.MANUAL))["phase"] == "confirmed"
    assert store.value["automation_pause"]["paused"] is True

    refused = await run(controls, AI, "auto-1", Source.AUTOMATION)
    assert refused["phase"] == "failed" and "paused" in refused["message"]
    assert appliance.mode["currentMode"] == 0

    await controls.resume_automation()
    assert store.value["automation_pause"]["paused"] is False
    assert (await run(controls, AI, "auto-2", Source.AUTOMATION))["phase"] == "confirmed"
    assert appliance.mode["currentMode"] == 1
    await controls.close()


async def test_manual_setting_can_opt_out_of_pausing_automation():
    controls, _, appliance, store, _ = setup_settings()
    operation = await run(controls, SELF, "owner", Source.MANUAL, pause_automation=False)
    assert operation["phase"] == "confirmed"
    assert store.value.get("automation_pause", {}).get("paused") is not True
    assert (await run(controls, AI, "auto", Source.AUTOMATION))["phase"] == "confirmed"
    assert appliance.mode["currentMode"] == 1
    await controls.close()


async def test_automation_source_never_pauses_even_if_asked():
    controls, _, _, store, _ = setup_settings()
    assert (await run(controls, AI, "auto", Source.AUTOMATION, pause_automation=True))["phase"] == "confirmed"
    assert store.value.get("automation_pause", {}).get("paused") is not True
    await controls.close()


async def test_default_manual_behaviour_is_unchanged():
    controls, _, _, store, _ = setup_settings()
    await run(controls, SELF, "owner", Source.MANUAL, pause_automation=None)
    assert store.value["automation_pause"]["paused"] is True
    await controls.close()


async def test_owner_setting_schema_accepts_only_boolean_pause_flag():
    _, schemas, _ = await manual_schema(capture=True)
    schema = schemas["owner_setting"]
    base = {"config_entry": "synthetic", "setting": "native_mode", "value": AI, "request_id": "x"}
    assert "pause_automation" not in schema(base)
    assert schema({**base, "pause_automation": False})["pause_automation"] is False
    with pytest.raises(vol.Invalid):
        schema({**base, "pause_automation": "no"})


async def paused_service(user_admin):
    controls, coordinator, _, store, _ = setup_settings()
    await run(controls, SELF, "owner", Source.MANUAL)
    assert store.value["automation_pause"]["paused"] is True
    hass, schemas, callbacks = await manual_schema(capture=True)

    async def user(_user_id):
        return SimpleNamespace(is_admin=user_admin)

    hass.auth = SimpleNamespace(async_get_user=user)
    hass.config_entries = SimpleNamespace(
        async_get_entry=lambda _: SimpleNamespace(domain="sigen_hybrid", state="loaded", runtime_data=coordinator)
    )
    return controls, store, schemas, callbacks


@pytest.mark.parametrize("user_id", [None, "admin"])
async def test_resume_service_clears_the_pause_for_automations_and_admins(user_id):
    controls, store, schemas, callbacks = await paused_service(user_admin=True)
    call = SimpleNamespace(data=schemas["resume_automation"]({"config_entry": "synthetic"}),
                           context=SimpleNamespace(user_id=user_id))
    assert await callbacks["resume_automation"](call) == {"paused": False}
    assert store.value["automation_pause"]["paused"] is False
    assert (await run(controls, AI, "auto", Source.AUTOMATION))["phase"] == "confirmed"
    await controls.close()


async def test_resume_service_requires_an_administrator():
    controls, store, schemas, callbacks = await paused_service(user_admin=False)
    call = SimpleNamespace(data=schemas["resume_automation"]({"config_entry": "synthetic"}),
                           context=SimpleNamespace(user_id="ordinary"))
    with pytest.raises(RuntimeError, match="administrator"):
        await callbacks["resume_automation"](call)
    assert store.value["automation_pause"]["paused"] is True
    await controls.close()
