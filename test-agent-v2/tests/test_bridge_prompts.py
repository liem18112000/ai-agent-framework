"""The bridge/gateway prompts moved into the store: rendering, fallback, validation, reachability."""

from __future__ import annotations

from common.admin import prompts as admin
from common.bridge import prompts as bridge
from common.prompts import store_for, validate


def test_bodies_are_image_defaults():
    """Version 0 = the body compiled into the image; DB-published versions start at 1."""
    store = store_for(bridge.DEFAULTS)
    assert store.get(bridge.TRIGGER).version == 0
    assert store.get(bridge.INSTRUCTIONS_KEY).version == 0
    assert store.get(bridge.TEST_PROMPT).version == 0


def test_test_prompt_renders_key_and_depth():
    out = bridge.test_prompt("LUZ-1", "3")
    assert "LUZ-1" in out and "depth 3" in out
    assert 'seed="LUZ-1", depth=3' in out
    assert "$" not in out                       # nothing left unsubstituted


def test_test_prompt_falls_back_when_no_key():
    assert "<JIRA-KEY" in bridge.test_prompt("")


def test_server_and_trigger_render_the_shipped_text():
    assert "Single MCP gateway" in bridge.server_instructions()
    assert "TESTING-AGENT TRIGGER" in bridge.trigger_instructions()


def test_every_body_passes_validation():
    for key, tpl in bridge.DEFAULTS.items():
        validate(key, tpl.body, tpl.engine, tpl.required_vars,
                 contract=tpl.contract, forbids=tpl.forbids)


def test_keys_are_reachable_through_the_admin_surface():
    keys = admin._all_keys()
    for key in bridge.DEFAULTS:
        assert key in keys
