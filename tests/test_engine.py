"""Integration tests for engine.py — trigger evaluation and response execution."""
from __future__ import annotations

import pytest

from config import (
    GameConfig, Event,
    ProximityTrigger, CommandTrigger, VariableThresholdTrigger,
    SendMessageResponse, AddFlagResponse, RemoveFlagResponse,
    SetVariableResponse, IncrementVariableResponse,
    RandomOptionsResponse, RandomOption, WithNodeResponse,
    TargetTriggeringNode, TargetChannel, TargetFlag, TargetAllWithFlag,
    EventException,
)
from tests.conftest import minimal_config, make_engine, INSIDE_ZONE, OUTSIDE_ZONE, NODE_ID, NODE2_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg():
    return minimal_config()


@pytest.fixture
def eng(cfg, db):
    return make_engine(cfg, db, channel_map={"main": 0})


# ---------------------------------------------------------------------------
# Zone triggers
# ---------------------------------------------------------------------------

def test_enters_zone_fires_on_entry(db):
    cfg = minimal_config(events=[
        Event(
            label="on_enter",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)

    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)  # seed — not in zone
    assert not db.has_flag("node", NODE_ID, "active")

    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # enters zone
    assert db.has_flag("node", NODE_ID, "active")


def test_enters_zone_does_not_refire_while_stationary(db):
    cfg = minimal_config(events=[
        Event(
            label="on_enter",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)

    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    db.remove_flag("node", NODE_ID, "active")

    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # still inside — no new enters_zone
    assert not db.has_flag("node", NODE_ID, "active")


def test_leaves_zone_fires_on_exit(db):
    cfg = minimal_config(events=[
        Event(
            label="on_exit",
            trigger=ProximityTrigger(kind="leaves_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="scored", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)

    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # enters
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)  # leaves
    assert db.has_flag("node", NODE_ID, "scored")


def test_in_zone_fires_when_inside(db):
    cfg = minimal_config(events=[
        Event(
            label="in_zone_ev",
            trigger=ProximityTrigger(kind="in_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)

    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")

    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")


def test_near_waypoint_fires_in_range(db):
    cfg = minimal_config(events=[
        Event(
            label="near_wp",
            trigger=ProximityTrigger(kind="near_waypoint", target_label="wp_a", meters=2000),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    # wp_a is at (47.005, -122.005); INSIDE_ZONE is (47.003, -122.003) — <400 m away
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")


def test_near_waypoint_does_not_fire_out_of_range(db):
    cfg = minimal_config(events=[
        Event(
            label="near_wp",
            trigger=ProximityTrigger(kind="near_waypoint", target_label="wp_a", meters=10),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# max_triggers
# ---------------------------------------------------------------------------

def test_max_triggers_respected(db):
    cfg = minimal_config(events=[
        Event(
            label="once",
            trigger=ProximityTrigger(kind="in_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            max_triggers=1,
        )
    ])
    eng = make_engine(cfg, db)

    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # fires (count=1)
    db.remove_flag("node", NODE_ID, "active")
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # max reached — should not fire
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Command trigger
# ---------------------------------------------------------------------------

def test_command_dm_trigger_fires(db):
    from config import Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="hello"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
        ],
        events=[
            Event(
                label="hello_ev",
                trigger=CommandTrigger(kind="dm", message_label="hello"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "hello", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")


def test_command_dm_trigger_wrong_text_no_fire(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="hello"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}")],
        events=[
            Event(
                label="hello_ev",
                trigger=CommandTrigger(kind="dm", message_label="hello"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "wrong text", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Variable threshold
# ---------------------------------------------------------------------------

def test_variable_threshold_mutable_fires(db):
    from config import AddFlagResponse, TargetZone
    cfg = minimal_config(events=[
        Event(
            label="score_ev",
            trigger=VariableThresholdTrigger(variable_label="score", operator="gte", value=10),
            responses=[AddFlagResponse(flag_label="active", target=TargetZone("zone_a"))],
        )
    ])
    eng = make_engine(cfg, db)
    db.init_mutable_variables(cfg)

    # score=0 — should not fire
    eng.handle_periodic()
    assert not db.has_flag("zone", "zone_a", "active")

    db.set_mutable_variable("score", 10)
    eng.handle_periodic()
    assert db.has_flag("zone", "zone_a", "active")


def test_variable_threshold_computed_fires(db):
    """variable_threshold on a flag_count computed variable triggers when count matches."""
    from config import Variable
    cfg = minimal_config(events=[
        Event(
            label="count_ev",
            trigger=VariableThresholdTrigger(variable_label="active_count", operator="gte", value=2),
            responses=[AddFlagResponse(flag_label="scored", target=TargetAllWithFlag(flag_label="active"))],
        )
    ])
    eng = make_engine(cfg, db)

    # Seed two nodes with 'active' flag
    db.add_flag("node", NODE_ID, "active")
    db.add_flag("node", NODE2_ID, "active")

    eng.handle_periodic()
    # scored flag should be added to both active nodes
    assert db.has_flag("node", NODE_ID, "scored")
    assert db.has_flag("node", NODE2_ID, "scored")


# ---------------------------------------------------------------------------
# Responses: send_message
# ---------------------------------------------------------------------------

def test_send_message_dm(db):
    cfg = minimal_config(events=[
        Event(
            label="greet_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SendMessageResponse(message_label="hello", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert len(eng.sent_dms) == 1
    assert eng.sent_dms[0][0] == NODE_ID
    assert eng.sent_dms[0][1] == "Hello world"


def test_send_message_channel(db):
    cfg = minimal_config(events=[
        Event(
            label="broadcast_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SendMessageResponse(message_label="hello", target=TargetChannel("main"))],
        )
    ])
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert len(eng.sent_channels) == 1
    assert eng.sent_channels[0] == ("main", "Hello world")


# ---------------------------------------------------------------------------
# Message interpolation
# ---------------------------------------------------------------------------

def test_node_id_interpolation(db):
    cfg = minimal_config(events=[
        Event(
            label="greet_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SendMessageResponse(message_label="greet_node", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert eng.sent_dms[0][1] == f"Hi {NODE_ID}"


def test_zone_interpolation(db):
    cfg = minimal_config(events=[
        Event(
            label="zone_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SendMessageResponse(message_label="greet_zone", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert "zone_a" in eng.sent_dms[0][1]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

def test_node_has_flag_exception_blocks_event(db):
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="scored", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="node_has_flag", flag="active")],
        )
    ])
    eng = make_engine(cfg, db)
    db.add_flag("node", NODE_ID, "active")  # exception condition met → event blocked

    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "scored")


def test_node_lacks_flag_exception_blocks_event(db):
    """node_lacks_flag exception fires (blocks event) when node does NOT have the flag."""
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="scored", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="node_lacks_flag", flag="active")],
        )
    ])
    eng = make_engine(cfg, db)
    # Node has no 'active' flag → exception triggers → event blocked
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "scored")


def test_exception_passes_when_condition_not_met(db):
    """node_has_flag exception does NOT block when node lacks the flag."""
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="scored", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="node_has_flag", flag="active")],
        )
    ])
    eng = make_engine(cfg, db)
    # Node has no 'active' flag → exception does not apply → event fires
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "scored")


# ---------------------------------------------------------------------------
# seed_node_location
# ---------------------------------------------------------------------------

def test_seed_applies_zone_flags_silently(db):
    """seed_node_location runs the event pipeline but sends no messages."""
    cfg = minimal_config(events=[
        Event(
            label="on_enter",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[
                AddFlagResponse(flag_label="active", target=TargetTriggeringNode()),
                SendMessageResponse(message_label="hello", target=TargetTriggeringNode()),
            ],
        )
    ])
    eng = make_engine(cfg, db)
    eng.seed_node_location(NODE_ID, *INSIDE_ZONE)

    # Flag should be applied
    assert db.has_flag("node", NODE_ID, "active")
    # No messages should have been sent
    assert eng.sent_dms == []
    assert eng.sent_channels == []


def test_seed_subsequent_update_no_refire(db):
    """After seeding a node inside a zone, a re-received position does not refire enters_zone."""
    cfg = minimal_config(events=[
        Event(
            label="on_enter",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SendMessageResponse(message_label="hello", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.seed_node_location(NODE_ID, *INSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # same position — not an enters_zone

    assert eng.sent_dms == []


# ---------------------------------------------------------------------------
# increment_variable response
# ---------------------------------------------------------------------------

def test_increment_variable_response(db):
    cfg = minimal_config(events=[
        Event(
            label="score_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[IncrementVariableResponse(variable_label="score", amount=5)],
        )
    ])
    eng = make_engine(cfg, db)
    db.init_mutable_variables(cfg)

    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert db.get_mutable_variable("score") == 5


# ---------------------------------------------------------------------------
# with_node
# ---------------------------------------------------------------------------

def test_with_node_resolves_flag_target(db):
    """with_node: target=to_all_with_flag; inner response sends DM to each resolved node."""
    cfg = minimal_config(events=[
        Event(
            label="blast_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[
                WithNodeResponse(
                    target=TargetAllWithFlag(flag_label="active"),
                    responses=[
                        SendMessageResponse(message_label="hello", target=TargetTriggeringNode()),
                    ],
                )
            ],
        )
    ])
    eng = make_engine(cfg, db)

    # Give two nodes the 'active' flag and known locations
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    db.update_node_location(NODE2_ID, *OUTSIDE_ZONE)
    db.add_flag("node", NODE_ID, "active")
    db.add_flag("node", NODE2_ID, "active")

    # Trigger the event by having a third node enter the zone
    TRIGGER_ID = "!deadbeef"
    db.update_node_location(TRIGGER_ID, *OUTSIDE_ZONE)
    eng._node_zones[TRIGGER_ID] = frozenset()
    eng.handle_position(TRIGGER_ID, *INSIDE_ZONE)

    # Both active nodes should receive a DM
    dm_recipients = {nid for nid, _ in eng.sent_dms}
    assert NODE_ID in dm_recipients
    assert NODE2_ID in dm_recipients


def test_with_node_skips_unlocated(db):
    """with_node skips nodes that have no known location."""
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[
                WithNodeResponse(
                    target=TargetAllWithFlag(flag_label="active"),
                    responses=[
                        SendMessageResponse(message_label="hello", target=TargetTriggeringNode()),
                    ],
                )
            ],
        )
    ])
    eng = make_engine(cfg, db)

    # active node has no location stored
    db.add_flag("node", NODE2_ID, "active")

    TRIGGER_ID = "!deadbeef"
    db.update_node_location(TRIGGER_ID, *OUTSIDE_ZONE)
    eng._node_zones[TRIGGER_ID] = frozenset()
    eng.handle_position(TRIGGER_ID, *INSIDE_ZONE)

    assert eng.sent_dms == []


# ---------------------------------------------------------------------------
# random_n target restriction
# ---------------------------------------------------------------------------

def test_random_n_limits_targets(db):
    """With random_n=1, only one of many flagged nodes should receive a message."""
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[
                SendMessageResponse(
                    message_label="hello",
                    target=TargetAllWithFlag(flag_label="active", random_n=1),
                )
            ],
        )
    ])
    eng = make_engine(cfg, db)

    for i in range(5):
        nid = f"!node{i:04x}"
        db.add_flag("node", nid, "active")

    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert len(eng.sent_dms) == 1


# ---------------------------------------------------------------------------
# disable_event / enable_event responses
# ---------------------------------------------------------------------------

def test_disable_event_response(db):
    from config import DisableEventResponse, EnableEventResponse
    cfg = minimal_config(events=[
        Event(
            label="self_disabling",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[DisableEventResponse(event_label="self_disabling")],
        )
    ])
    eng = make_engine(cfg, db)
    db.init_event_states(cfg)

    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.is_event_disabled("self_disabling")


def test_set_event_triggers_response(db):
    from config import SetEventTriggersResponse
    cfg = minimal_config(events=[
        Event(
            label="reset_target",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SetEventTriggersResponse(event_label="reset_target", value=0)],
        )
    ])
    eng = make_engine(cfg, db)
    db.init_event_states(cfg)

    db.increment_event_triggers("reset_target")
    db.increment_event_triggers("reset_target")
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    count, _ = db.get_event_state("reset_target")
    # The response set it to 0; then _fire_event incremented it to 1
    assert count == 1
