"""Tests for config.py — YAML loading and validation."""
from __future__ import annotations

import pytest

from config import load_config, ConfigError, GameConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_VALID = """\
channels:
  - label: main
    name: LongFast
    psk: AQ==
"""

ZONE_YAML = """\
zones:
  - label: zone_a
    points:
      - [47.000, -122.000]
      - [47.010, -122.000]
      - [47.000, -122.010]
"""

FLAG_YAML = """\
flags:
  - label: active
"""

MESSAGE_YAML = """\
messages:
  - label: hello
    text: "Hello world"
"""

NODE_YAML = """\
nodes:
  - label: node_a
    node_id: "!aabbccdd"
"""


def valid_yaml(*sections: str) -> str:
    return MINIMAL_VALID + "".join(sections)


# ---------------------------------------------------------------------------
# Basic loading
# ---------------------------------------------------------------------------

def test_empty_yaml_loads(tmp_yaml):
    cfg = load_config(tmp_yaml("{}"))
    assert isinstance(cfg, GameConfig)
    assert cfg.channels == []
    assert cfg.events == []


def test_minimal_valid_loads(tmp_yaml):
    cfg = load_config(tmp_yaml(MINIMAL_VALID))
    assert len(cfg.channels) == 1
    assert cfg.channels[0].label == "main"


def test_zone_parses(tmp_yaml):
    cfg = load_config(tmp_yaml(MINIMAL_VALID + ZONE_YAML))
    assert len(cfg.zones) == 1
    assert cfg.zones[0].label == "zone_a"
    assert len(cfg.zones[0].points) == 3


def test_flag_parses(tmp_yaml):
    cfg = load_config(tmp_yaml(MINIMAL_VALID + FLAG_YAML))
    assert cfg.flags[0].label == "active"
    assert cfg.flags[0].expiry_mins is None


def test_flag_with_expiry(tmp_yaml):
    cfg = load_config(tmp_yaml(MINIMAL_VALID + """\
flags:
  - label: active
    expiry_mins: 30
"""))
    assert cfg.flags[0].expiry_mins == 30


def test_node_parses(tmp_yaml):
    cfg = load_config(tmp_yaml(MINIMAL_VALID + NODE_YAML))
    assert cfg.nodes[0].node_id == "!aabbccdd"


# ---------------------------------------------------------------------------
# Trigger parsing
# ---------------------------------------------------------------------------

def test_enters_zone_trigger(tmp_yaml):
    cfg = load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, MESSAGE_YAML, """\
events:
  - label: on_enter
    trigger:
      type: enters_zone
      target: zone_a
    responses: []
""")))
    assert cfg.events[0].trigger.kind == "enters_zone"


def test_timed_trigger(tmp_yaml):
    cfg = load_config(tmp_yaml(valid_yaml(FLAG_YAML, MESSAGE_YAML, """\
events:
  - label: timed_ev
    trigger:
      type: time_window
      start: "2026-01-01T00:00:00"
      end: "2026-12-31T23:59:59"
    responses: []
""")))
    from config import TimedTrigger
    assert isinstance(cfg.events[0].trigger, TimedTrigger)


def test_unknown_trigger_type_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="Unknown trigger type"):
        load_config(tmp_yaml(valid_yaml(FLAG_YAML, MESSAGE_YAML, """\
events:
  - label: bad_event
    trigger:
      type: nonexistent_trigger
    responses: []
""")))


def test_variable_threshold_mutable_var(tmp_yaml):
    cfg = load_config(tmp_yaml(valid_yaml(FLAG_YAML, MESSAGE_YAML, """\
mutable_variables:
  - label: score
    type: integer
    scope: global
    initial: 0
events:
  - label: score_ev
    trigger:
      type: variable_threshold
      variable: score
      operator: gte
      value: 10
    responses: []
""")))
    from config import VariableThresholdTrigger
    assert isinstance(cfg.events[0].trigger, VariableThresholdTrigger)


def test_variable_threshold_computed_var(tmp_yaml):
    """variable_threshold should accept computed variables (from variables:)."""
    cfg = load_config(tmp_yaml(valid_yaml(FLAG_YAML, MESSAGE_YAML, """\
variables:
  - label: flag_total
    scope: global
    tracks: flag_count
    target: active
events:
  - label: flag_ev
    trigger:
      type: variable_threshold
      variable: flag_total
      operator: gte
      value: 5
    responses: []
""")))
    assert cfg.events[0].trigger.variable_label == "flag_total"


def test_variable_threshold_unknown_var_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="not in variables or mutable_variables"):
        load_config(tmp_yaml(valid_yaml(FLAG_YAML, """\
events:
  - label: bad_ev
    trigger:
      type: variable_threshold
      variable: no_such_var
      operator: eq
      value: 0
    responses: []
""")))


def test_variable_threshold_string_var_numeric_op_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="string variables only support eq/neq"):
        load_config(tmp_yaml(valid_yaml(FLAG_YAML, """\
mutable_variables:
  - label: name
    type: string
    scope: global
    initial: "hello"
events:
  - label: bad_ev
    trigger:
      type: variable_threshold
      variable: name
      operator: gt
      value: 5
    responses: []
""")))


# ---------------------------------------------------------------------------
# Response parsing and validation
# ---------------------------------------------------------------------------

def test_unknown_response_type_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="Unknown response type"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, MESSAGE_YAML, """\
events:
  - label: bad_ev
    trigger:
      type: enters_zone
      target: zone_a
    responses:
      - type: do_the_thing
""")))


def test_send_message_undeclared_message_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="not defined"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
events:
  - label: ev
    trigger:
      type: enters_zone
      target: zone_a
    responses:
      - type: send_message
        message_label: no_such_message
        to_triggering_node: true
""")))


def test_add_flag_undeclared_flag_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="not defined"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, """\
events:
  - label: ev
    trigger:
      type: enters_zone
      target: zone_a
    responses:
      - type: add_flag
        flag_label: undefined_flag
        to_triggering_node: true
""")))


def test_random_options_requires_two_options(tmp_yaml):
    with pytest.raises(ConfigError, match="at least 2 options"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, MESSAGE_YAML, """\
events:
  - label: ev
    trigger:
      type: enters_zone
      target: zone_a
    responses:
      - type: random_options
        options:
          - weight: 1
            responses:
              - type: send_message
                message_label: hello
                to_triggering_node: true
""")))


def test_random_options_zero_weight_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="weight must be > 0"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, MESSAGE_YAML, """\
events:
  - label: ev
    trigger:
      type: enters_zone
      target: zone_a
    responses:
      - type: random_options
        options:
          - weight: 0
            responses:
              - type: send_message
                message_label: hello
                to_triggering_node: true
          - weight: 1
            responses:
              - type: send_message
                message_label: hello
                to_triggering_node: true
""")))


# ---------------------------------------------------------------------------
# Message token validation
# ---------------------------------------------------------------------------

def test_unknown_message_token_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="interpolation token"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
messages:
  - label: bad_msg
    text: "Hello {undefined_token}"
events: []
""")))


def test_builtin_token_node_id_valid(tmp_yaml):
    cfg = load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
messages:
  - label: msg
    text: "Hi {node_id}"
events: []
""")))
    assert cfg.messages[0].text == "Hi {node_id}"


def test_builtin_token_zone_valid(tmp_yaml):
    cfg = load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
messages:
  - label: msg
    text: "You are in {zone}"
events: []
""")))
    assert "{zone}" in cfg.messages[0].text


def test_mutable_variable_token_valid(tmp_yaml):
    cfg = load_config(tmp_yaml(valid_yaml(FLAG_YAML, """\
mutable_variables:
  - label: score
    type: integer
    scope: global
    initial: 0
messages:
  - label: msg
    text: "Score: {score}"
events: []
""")))
    assert "{score}" in cfg.messages[0].text


# ---------------------------------------------------------------------------
# Exception validation
# ---------------------------------------------------------------------------

def test_random_skip_requires_chance(tmp_yaml):
    with pytest.raises(ConfigError, match="'chance' field required"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
events:
  - label: ev
    trigger:
      type: enters_zone
      target: zone_a
    responses: []
    exceptions:
      - kind: random_skip
""")))


def test_node_has_flag_requires_flag(tmp_yaml):
    with pytest.raises(ConfigError, match="'flag' field required"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
events:
  - label: ev
    trigger:
      type: enters_zone
      target: zone_a
    responses: []
    exceptions:
      - kind: node_has_flag
""")))


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

def test_duplicate_label_in_variables_and_mutable_raises(tmp_yaml):
    with pytest.raises(ConfigError, match="defined in both"):
        load_config(tmp_yaml(valid_yaml(FLAG_YAML, """\
variables:
  - label: score
    scope: global
    tracks: flag_count
    target: active
mutable_variables:
  - label: score
    type: integer
    scope: global
    initial: 0
events: []
""")))


def test_create_waypoint_without_node_context_raises(tmp_yaml):
    """create_waypoint is invalid inside a timed trigger (no node context)."""
    with pytest.raises(ConfigError, match="create_waypoint requires"):
        load_config(tmp_yaml(valid_yaml(ZONE_YAML, FLAG_YAML, """\
events:
  - label: ev
    trigger:
      type: time_window
      start: "2026-01-01T00:00:00"
      end: "2026-12-31T23:59:59"
    responses:
      - type: create_waypoint
        expiry_mins: 60
""")))
