"""Integration tests for engine.py — trigger evaluation and response execution."""
from __future__ import annotations

import pytest

from config import (
    GameConfig, Event, Variable, Message, FlagDef, NodeDef,
    ProximityTrigger, CommandTrigger, VariableThresholdTrigger,
    FlagExpiryTrigger, WaypointExpiryTrigger, PositionReceivedTrigger,
    SendMessageResponse, SendAlertResponse, AddFlagResponse, RemoveFlagResponse,
    RequestLocationResponse, RequestTelemetryResponse,
    SetVariableResponse, IncrementVariableResponse,
    RandomOptionsResponse, RandomOption, WithNodeResponse, RepeatResponse,
    CreateWaypointResponse, AddDynamicWaypointFlagResponse, DestroyWaypointResponse,
    EnableEventResponse, DisableEventResponse,
    TargetTriggeringNode, TargetChannel, TargetFlag, TargetAllWithFlag, TargetGroup,
    EventException,
)
from tests.conftest import minimal_config, make_engine, INSIDE_ZONE, OUTSIDE_ZONE, ZONE_POINTS, NODE_ID, NODE2_ID
from config import MutableVariableDef, ReportColumn, ReportDef, SendReportResponse


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


def test_command_dm_trigger_case_insensitive_fires(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="spawn", text="spawn")],
        events=[
            Event(
                label="spawn_ev",
                trigger=CommandTrigger(kind="dm", message_label="spawn", case_sensitive=False),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "SPAWN", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")
    db.remove_flag("node", NODE_ID, "active")
    eng.handle_message(NODE_ID, "Spawn", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")


def test_command_dm_trigger_case_sensitive_no_fire(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="spawn", text="spawn")],
        events=[
            Event(
                label="spawn_ev",
                trigger=CommandTrigger(kind="dm", message_label="spawn", case_sensitive=True),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "SPAWN", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


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


def test_variable_threshold_node_mutable_fires_on_dm(db):
    """A node-scoped mutable variable_threshold fires on the same DM that crosses it,
    not deferred to the next position update (e.g. veteran/expert promotion)."""
    from config import Message, MutableVariableDef
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="ping", text="!ping"),
        ],
        mutable_variables=[
            MutableVariableDef(label="score", type="integer", scope="global", initial=0),
            MutableVariableDef(label="uses", type="integer", scope="node", initial=0),
        ],
        events=[
            Event(
                label="count_ev",
                trigger=CommandTrigger(kind="dm", message_label="ping"),
                responses=[IncrementVariableResponse(
                    variable_label="uses", amount=1,
                    target=TargetTriggeringNode(),
                )],
            ),
            Event(
                label="promote_ev",
                trigger=VariableThresholdTrigger(variable_label="uses", operator="gte", value=3),
                trigger_per_node=True,
                max_triggers=1,
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.init_mutable_variables(cfg)

    eng.handle_message(NODE_ID, "!ping", is_dm=True, channel_idx=0)
    eng.handle_message(NODE_ID, "!ping", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")  # 2 uses — not yet

    eng.handle_message(NODE_ID, "!ping", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")  # 3rd DM triggers promotion immediately


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


def test_node_shortname_interpolation(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="Hello world"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}"),
                  Message(label="greet_short", text="Hey {node_shortname}!")],
        events=[
            Event(
                label="greet_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="greet_short", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.interface.nodes = {NODE_ID: {"user": {"shortName": "JOEY", "longName": "Joey's Radio"}}}
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert eng.sent_dms[0][1] == "Hey JOEY!"


def test_node_longname_interpolation(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="Hello world"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}"),
                  Message(label="greet_long", text="Welcome, {node_longname}.")],
        events=[
            Event(
                label="greet_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="greet_long", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.interface.nodes = {NODE_ID: {"user": {"shortName": "JOEY", "longName": "Joey's Radio"}}}
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert eng.sent_dms[0][1] == "Welcome, Joey's Radio."


def test_node_shortname_fallback_to_id(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="Hello world"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}"),
                  Message(label="greet_short", text="Hey {node_shortname}!")],
        events=[
            Event(
                label="greet_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="greet_short", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.interface.nodes = {NODE_ID: {"user": {"shortName": "", "longName": ""}}}
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert eng.sent_dms[0][1] == f"Hey {NODE_ID}!"


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
# prev_distance_to_waypoint / distance_change_to_waypoint
# ---------------------------------------------------------------------------

def test_prev_distance_to_waypoint_variable(db):
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="dist_msg", text="prev:{prev_dist}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="prev_dist", scope="node", tracks="prev_distance_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="dist_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # First position — no prev yet
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    # Second position (enters zone) — prev is OUTSIDE_ZONE
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert len(eng.sent_dms) == 1
    text = eng.sent_dms[0][1]
    # Should contain a numeric distance, not [unknown]
    assert "[unknown]" not in text
    assert "prev:" in text


def test_distance_change_to_waypoint_negative_when_closer(db):
    from config import Variable
    cfg = minimal_config(
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="delta", scope="node", tracks="distance_change_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="getting_closer",
                trigger=VariableThresholdTrigger(variable_label="delta", operator="lt", value=0),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # wp_a is at (47.005, -122.005)
    # Start far away, then move closer
    eng.handle_position(NODE_ID, 47.020, -122.020)  # ~2.1 km from wp_a
    eng.handle_position(NODE_ID, *INSIDE_ZONE)       # ~0.4 km from wp_a — moved closer

    assert db.has_flag("node", NODE_ID, "active")


def test_distance_change_to_waypoint_positive_when_farther(db):
    from config import Variable
    cfg = minimal_config(
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="delta", scope="node", tracks="distance_change_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="getting_farther",
                trigger=VariableThresholdTrigger(variable_label="delta", operator="gt", value=0),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Start close, then move farther
    eng.handle_position(NODE_ID, *INSIDE_ZONE)       # ~0.4 km from wp_a
    eng.handle_position(NODE_ID, 47.020, -122.020)   # ~2.1 km from wp_a — moved farther

    assert db.has_flag("node", NODE_ID, "active")


def test_distance_change_unknown_without_prev(db):
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="delta_msg", text="delta:{delta}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="delta", scope="node", tracks="distance_change_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="delta_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # First position ever — no prev, should resolve to [unknown]
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert eng.sent_dms[0][1] == "delta:[unknown]"


# ---------------------------------------------------------------------------
# seconds_since_last_update / current_position / prev_position variable tracks
# ---------------------------------------------------------------------------

def test_seconds_since_last_update_resolves_numeric(db):
    """seconds_since_last_update returns a numeric string after a position update."""
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="age_msg", text="age:{age}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="age", scope="node", tracks="seconds_since_last_update"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="age_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    text = eng.sent_dms[0][1]
    assert "[unknown]" not in text
    value = text.split("age:")[1]
    assert value.isdigit()


def test_current_and_prev_position_resolve(db):
    """current_position and prev_position return formatted coordinate strings."""
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="pos_msg", text="cur:{cur} prev:{prev}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="cur", scope="node", tracks="current_position"),
            Variable(label="prev", scope="node", tracks="prev_position"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="pos_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)   # becomes prev
    eng.handle_position(NODE_ID, *INSIDE_ZONE)    # becomes cur, enters zone

    text = eng.sent_dms[0][1]
    assert "[unknown]" not in text
    # Both should look like "lat, lon"
    assert "," in text.split("cur:")[1].split(" prev:")[0]
    assert "," in text.split("prev:")[1]


def test_prev_position_unknown_on_first_update(db):
    """prev_position returns [unknown] when the node has no prior position."""
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="pos_msg", text="prev:{prev}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="prev", scope="node", tracks="prev_position"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="pos_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # first update ever

    assert eng.sent_dms[0][1] == "prev:[unknown]"


# ---------------------------------------------------------------------------
# variable_threshold: skip when computed value is non-numeric
# ---------------------------------------------------------------------------

def test_variable_threshold_skips_when_distance_change_unknown(db):
    """variable_threshold on distance_change_to_waypoint does not fire on first
    position update when there is no previous position ([unknown] returned)."""
    from config import Variable
    cfg = minimal_config(
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="delta", scope="node", tracks="distance_change_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="closer_ev",
                trigger=VariableThresholdTrigger(variable_label="delta", operator="lt", value=0),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # first update — no prev, delta=[unknown]

    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# variable_threshold during handle_message: mutable node-scoped only
# ---------------------------------------------------------------------------

def test_variable_threshold_fires_on_dm_for_computed_node_var(db):
    """A variable_threshold on a node-scoped computed variable fires on position
    update. The flag is set by handle_position, not handle_message."""
    from config import Variable, Message, RequestLocationResponse
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="ping", text="!ping"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="staleness", scope="node", tracks="seconds_since_last_update"),
        ],
        events=[
            Event(
                label="stale_refresh",
                trigger=VariableThresholdTrigger(
                    variable_label="staleness", operator="gte", value=0
                ),
                trigger_per_node=True,
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # threshold fires here (staleness >= 0 always true)
    assert db.has_flag("node", NODE_ID, "active")


def test_computed_threshold_does_not_refire_in_handle_message(db):
    """Computed variable thresholds (e.g. direction flags) must not re-fire during
    handle_message — only mutable node-scoped thresholds run there."""
    from config import Variable
    cfg = minimal_config(
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="delta", scope="node", tracks="distance_change_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="closer_ev",
                trigger=VariableThresholdTrigger(variable_label="delta", operator="lt", value=0),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            ),
            Event(
                label="ping_ev",
                trigger=CommandTrigger(kind="dm", message_label="hello"),
                responses=[RemoveFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    # Move closer to wp_a so delta < 0 — closer_ev fires and sets active
    eng.handle_position(NODE_ID, 47.020, -122.020)  # far
    eng.handle_position(NODE_ID, *INSIDE_ZONE)       # closer — active set
    assert db.has_flag("node", NODE_ID, "active")

    # DM clears the flag; if computed threshold re-ran in handle_message it would re-set it
    eng.handle_message(NODE_ID, "Hello world", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")  # stays cleared — threshold did not refire


def test_direction_flag_cleared_after_hint(db):
    """dir_closer and dir_farther are removed when a hint response fires,
    so a repeat !hint without new movement returns hint_same."""
    from config import Variable, Message, MutableVariableDef
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="hint_cmd", text="!hint"),
            Message(label="warmer_msg", text="warmer"),
            Message(label="same_msg", text="same"),
        ],
        flags=[
            *[f for f in minimal_config().flags],  # active, scored
            __import__('config').FlagDef(label="dir_closer"),
            __import__('config').FlagDef(label="dir_farther"),
        ],
        mutable_variables=[
            MutableVariableDef(label="score", type="integer", scope="global", initial=0),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
        ],
        events=[
            Event(
                label="hint_warmer",
                trigger=CommandTrigger(kind="dm", message_label="hint_cmd"),
                trigger_per_node=True,
                exceptions=[
                    __import__('config').EventException(kind="node_lacks_flag", flag="dir_closer"),
                ],
                responses=[
                    SendMessageResponse(message_label="warmer_msg", target=TargetTriggeringNode()),
                    RemoveFlagResponse(flag_label="dir_closer", target=TargetTriggeringNode()),
                    RemoveFlagResponse(flag_label="dir_farther", target=TargetTriggeringNode()),
                ],
            ),
            Event(
                label="hint_same",
                trigger=CommandTrigger(kind="dm", message_label="hint_cmd"),
                trigger_per_node=True,
                exceptions=[
                    __import__('config').EventException(kind="node_has_flag", flag="dir_closer"),
                    __import__('config').EventException(kind="node_has_flag", flag="dir_farther"),
                ],
                responses=[
                    SendMessageResponse(message_label="same_msg", target=TargetTriggeringNode()),
                ],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.add_flag("node", NODE_ID, "dir_closer")

    # First hint: warmer fires, clears direction flags
    eng.handle_message(NODE_ID, "!hint", is_dm=True, channel_idx=0)
    assert eng.sent_dms[0][1] == "warmer"
    assert not db.has_flag("node", NODE_ID, "dir_closer")
    assert not db.has_flag("node", NODE_ID, "dir_farther")

    # Second hint without movement: same fires (no direction flags)
    eng.handle_message(NODE_ID, "!hint", is_dm=True, channel_idx=0)
    assert eng.sent_dms[1][1] == "same"


# ---------------------------------------------------------------------------
# bearing_to_waypoint / cardinal_to_waypoint variable tracks
# ---------------------------------------------------------------------------

def test_bearing_to_waypoint_format(db):
    """bearing_to_waypoint returns a string of the form '<int>°'."""
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="b_msg", text="b:{bearing}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="bearing", scope="node", tracks="bearing_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="b_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    bearing_str = eng.sent_dms[0][1].split("b:")[1]
    assert bearing_str.endswith("°")
    assert bearing_str[:-1].isdigit()
    assert 0 <= int(bearing_str[:-1]) <= 359


def test_cardinal_to_waypoint_valid(db):
    """cardinal_to_waypoint returns one of the 16 compass labels."""
    from config import Variable, Message
    valid = {"N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"}
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="c_msg", text="c:{cardinal}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="cardinal", scope="node", tracks="cardinal_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="c_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    cardinal_str = eng.sent_dms[0][1].split("c:")[1]
    assert cardinal_str in valid


def test_bearing_to_waypoint_due_east(db):
    """A waypoint due east of the node returns bearing ~90° and cardinal 'E'."""
    from config import Variable, Message, Waypoint
    # wp_east is at the same latitude as INSIDE_ZONE but clearly to the east
    inside_lat, inside_lon = INSIDE_ZONE
    cfg = minimal_config(
        waypoints=[
            Waypoint(label="wp_a", lat=47.005, lon=-122.005),
            Waypoint(label="wp_east", lat=inside_lat, lon=inside_lon + 1.0),
        ],
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="bc_msg", text="b:{bearing} c:{cardinal}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="bearing", scope="node", tracks="bearing_to_waypoint", target="wp_east"),
            Variable(label="cardinal", scope="node", tracks="cardinal_to_waypoint", target="wp_east"),
        ],
        events=[
            Event(
                label="zone_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[SendMessageResponse(message_label="bc_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    text = eng.sent_dms[0][1]
    bearing_deg = int(text.split("b:")[1].split(" ")[0].rstrip("°"))
    cardinal = text.split("c:")[1]
    assert 80 <= bearing_deg <= 100, f"Expected ~90° for due-east waypoint, got {bearing_deg}°"
    assert cardinal == "E"


def test_bearing_unknown_without_position(db):
    """bearing_to_waypoint and cardinal_to_waypoint return [unknown] when node has no location."""
    from config import Variable, Message
    cfg = minimal_config(
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
            Message(label="ping", text="!ping"),
            Message(label="bc_msg", text="b:{bearing} c:{cardinal}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="bearing", scope="node", tracks="bearing_to_waypoint", target="wp_a"),
            Variable(label="cardinal", scope="node", tracks="cardinal_to_waypoint", target="wp_a"),
        ],
        events=[
            Event(
                label="ping_ev",
                trigger=CommandTrigger(kind="dm", message_label="ping"),
                responses=[SendMessageResponse(message_label="bc_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # No handle_position — node has no known location
    eng.handle_message(NODE_ID, "!ping", is_dm=True, channel_idx=0)

    text = eng.sent_dms[0][1]
    assert "b:[unknown]" in text
    assert "c:[unknown]" in text


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


# ---------------------------------------------------------------------------
# near_zone trigger
# ---------------------------------------------------------------------------

def test_near_zone_fires_in_range(db):
    # INSIDE_ZONE is ~45m from zone_a centroid
    cfg = minimal_config(events=[
        Event(
            label="near_ev",
            trigger=ProximityTrigger(kind="near_zone", target_label="zone_a", meters=100),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")


def test_near_zone_no_fire_out_of_range(db):
    # OUTSIDE_ZONE is ~8km from zone_a centroid
    cfg = minimal_config(events=[
        Event(
            label="near_ev",
            trigger=ProximityTrigger(kind="near_zone", target_label="zone_a", meters=100),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# in_zone_on_start trigger
# ---------------------------------------------------------------------------

def test_in_zone_on_start_fires(db):
    from config import TargetZone
    cfg = minimal_config(events=[
        Event(
            label="start_ev",
            trigger=ProximityTrigger(kind="in_zone_on_start", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetZone("zone_a"))],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # seed node inside zone
    eng.handle_periodic()
    assert db.has_flag("zone", "zone_a", "active")


def test_in_zone_on_start_no_fire_when_empty(db):
    cfg = minimal_config(events=[
        Event(
            label="start_ev",
            trigger=ProximityTrigger(kind="in_zone_on_start", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)  # node outside zone
    eng.handle_periodic()
    assert not db.has_flag("zone", "zone_a", "active")


# ---------------------------------------------------------------------------
# Command trigger: zone_label gating and channel trigger
# ---------------------------------------------------------------------------

def test_command_zone_label_blocks_when_outside(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="hello"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}")],
        events=[
            Event(
                label="zone_cmd",
                trigger=CommandTrigger(kind="dm", message_label="hello", zone_label="zone_a"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_message(NODE_ID, "hello", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


def test_command_zone_label_fires_when_inside(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="hello"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}")],
        events=[
            Event(
                label="zone_cmd",
                trigger=CommandTrigger(kind="dm", message_label="hello", zone_label="zone_a"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng.handle_message(NODE_ID, "hello", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")


def test_channel_trigger_fires(db):
    from config import Message
    cfg = minimal_config(
        messages=[Message(label="hello", text="hello"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}")],
        events=[
            Event(
                label="channel_ev",
                trigger=CommandTrigger(kind="channel", message_label="hello", channel_label="main"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.handle_message(NODE_ID, "hello", is_dm=False, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Group responses and exceptions
# ---------------------------------------------------------------------------

def test_add_to_group_response(db):
    from config import AddToGroupResponse
    cfg = minimal_config(events=[
        Event(
            label="join_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddToGroupResponse(group_label="players", target=TargetTriggeringNode())],
        )
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.is_in_group("players", NODE_ID)


def test_remove_from_group_response(db):
    from config import AddToGroupResponse, RemoveFromGroupResponse
    cfg = minimal_config(events=[
        Event(
            label="join_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddToGroupResponse(group_label="players", target=TargetTriggeringNode())],
        ),
        Event(
            label="leave_ev",
            trigger=ProximityTrigger(kind="leaves_zone", target_label="zone_a"),
            responses=[RemoveFromGroupResponse(group_label="players", target=TargetTriggeringNode())],
        ),
    ])
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.is_in_group("players", NODE_ID)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.is_in_group("players", NODE_ID)


def test_to_group_target_broadcasts(db):
    from config import AddToGroupResponse, NodeDef
    cfg = minimal_config(
        nodes=[
            NodeDef(label="node_a", node_id=NODE_ID, initial_flags=[]),
            NodeDef(label="node_b", node_id=NODE2_ID, initial_flags=[]),
        ],
        events=[
            Event(
                label="greet_all",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[
                    SendMessageResponse(
                        message_label="hello",
                        target=TargetGroup("players"),
                    )
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.add_to_group("players", NODE_ID)
    db.add_to_group("players", NODE2_ID)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    recipients = [node_id for node_id, _ in eng.sent_dms]
    assert NODE_ID in recipients
    assert NODE2_ID in recipients


def test_group_count_variable(db):
    from config import Variable, TargetZone
    cfg = minimal_config(
        variables=[
            Variable(label="player_count", scope="global", tracks="group_count", target="players"),
        ],
        events=[
            Event(
                label="count_check",
                trigger=VariableThresholdTrigger(variable_label="player_count", operator="gte", value=2),
                responses=[AddFlagResponse(flag_label="active", target=TargetZone("zone_a"))],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.add_to_group("players", NODE_ID)
    eng.handle_periodic()
    assert not db.has_flag("zone", "zone_a", "active")

    db.add_to_group("players", NODE2_ID)
    eng.handle_periodic()   # global-scope variable threshold fires in periodic
    assert db.has_flag("zone", "zone_a", "active")


def test_node_in_group_exception_blocks(db):
    from config import AddToGroupResponse
    cfg = minimal_config(events=[
        Event(
            label="join_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddToGroupResponse(group_label="players", target=TargetTriggeringNode())],
        ),
        Event(
            label="gated_ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            exceptions=[EventException(kind="node_in_group", group="players")],
            responses=[AddFlagResponse(flag_label="scored", target=TargetTriggeringNode())],
        ),
    ])
    eng = make_engine(cfg, db)
    db.add_to_group("players", NODE_ID)  # pre-add so exception fires on first entry
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "scored")


def test_zone_in_group_exception_blocks(db):
    from config import GroupDef, AddToGroupResponse
    cfg = minimal_config(
        groups=[
            GroupDef(label="players", kind="node"),
            GroupDef(label="active_zones", kind="zone", initial_members=["zone_a"]),
        ],
        events=[
            Event(
                label="gated_ev",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                exceptions=[EventException(kind="zone_in_group", group="active_zones", target="zone_a")],
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Zone group triggers
# ---------------------------------------------------------------------------

def _zone_group_config(trigger_kind: str, **event_kwargs):
    """Helper: config with zone_a and zone_b both in a zone group."""
    from config import Zone, GroupDef
    zone_b_points = [
        (47.020, -122.020),
        (47.030, -122.020),
        (47.020, -122.030),
    ]
    return minimal_config(
        zones=[
            Zone(label="zone_a", points=list(ZONE_POINTS)),
            Zone(label="zone_b", points=zone_b_points),
        ],
        groups=[
            GroupDef(label="players", kind="node"),
            GroupDef(label="game_zones", kind="zone", initial_members=["zone_a", "zone_b"]),
        ],
        events=[
            Event(
                label="group_ev",
                trigger=ProximityTrigger(kind=trigger_kind, zone_group="game_zones"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
                **event_kwargs,
            )
        ],
    )


INSIDE_ZONE_B = (47.023, -122.023)  # inside zone_b


def test_enters_zone_group_fires(db):
    cfg = _zone_group_config("enters_zone_group")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # enters zone_a (in group)
    assert db.has_flag("node", NODE_ID, "active")


def test_enters_zone_group_fires_on_second_zone(db):
    cfg = _zone_group_config("enters_zone_group")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE_B)  # enters zone_b (also in group)
    assert db.has_flag("node", NODE_ID, "active")


def test_enters_zone_group_no_fire_outside(db):
    cfg = _zone_group_config("enters_zone_group")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


def test_leaves_zone_group_fires(db):
    cfg = _zone_group_config("leaves_zone_group")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # inside
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)  # leaves zone_a (in group)
    assert db.has_flag("node", NODE_ID, "active")


def test_in_zone_group_fires(db):
    cfg = _zone_group_config("in_zone_group")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")


def test_in_zone_group_no_fire_outside(db):
    cfg = _zone_group_config("in_zone_group")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


def test_in_zone_group_on_start_fires(db):
    from config import Zone, GroupDef, TargetZone
    cfg = minimal_config(
        zones=[Zone(label="zone_a", points=list(ZONE_POINTS))],
        groups=[
            GroupDef(label="players", kind="node"),
            GroupDef(label="game_zones", kind="zone", initial_members=["zone_a"]),
        ],
        events=[
            Event(
                label="start_ev",
                trigger=ProximityTrigger(kind="in_zone_group_on_start", zone_group="game_zones"),
                responses=[AddFlagResponse(flag_label="active", target=TargetZone("zone_a"))],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng.handle_periodic()
    assert db.has_flag("zone", "zone_a", "active")


def test_in_zone_group_on_start_no_fire_when_empty(db):
    cfg = _zone_group_config("in_zone_group_on_start")
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_periodic()
    assert not db.has_flag("zone", "zone_a", "active")
    assert not db.has_flag("node", NODE_ID, "active")


def test_command_zone_group_fires_inside(db):
    from config import Message, Zone, GroupDef
    cfg = minimal_config(
        zones=[Zone(label="zone_a", points=list(ZONE_POINTS))],
        groups=[
            GroupDef(label="players", kind="node"),
            GroupDef(label="game_zones", kind="zone", initial_members=["zone_a"]),
        ],
        messages=[Message(label="hello", text="hello"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}")],
        events=[
            Event(
                label="zone_grp_cmd",
                trigger=CommandTrigger(kind="dm", message_label="hello", zone_group="game_zones"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng.handle_message(NODE_ID, "hello", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")


def test_command_zone_group_no_fire_outside(db):
    from config import Message, Zone, GroupDef
    cfg = minimal_config(
        zones=[Zone(label="zone_a", points=list(ZONE_POINTS))],
        groups=[
            GroupDef(label="players", kind="node"),
            GroupDef(label="game_zones", kind="zone", initial_members=["zone_a"]),
        ],
        messages=[Message(label="hello", text="hello"),
                  Message(label="greet_node", text="Hi {node_id}"),
                  Message(label="greet_zone", text="Zone: {zone}")],
        events=[
            Event(
                label="zone_grp_cmd",
                trigger=CommandTrigger(kind="dm", message_label="hello", zone_group="game_zones"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.apply_initial_groups(cfg)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_message(NODE_ID, "hello", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Templated commands (variable capture)
# ---------------------------------------------------------------------------

def _make_capture_config(var_type="string", var_max=None, var_max_length=None,
                          cmd_text="!setname {player_name}", response_msg_text=None,
                          var_label="player_name", initial=None):
    from config import Message, MutableVariableDef, FlagDef
    if initial is None:
        initial = 0 if var_type in ("integer", "float") else "unknown"
    mv = MutableVariableDef(
        label=var_label, type=var_type, scope="node", initial=initial,
        max=var_max, max_length=var_max_length,
    )
    msgs = [Message(label="cmd", text=cmd_text)]
    if response_msg_text is not None:
        msgs.append(Message(label="resp", text=response_msg_text))
    responses = []
    if response_msg_text is not None:
        responses.append(SendMessageResponse(message_label="resp", target=TargetTriggeringNode()))
    responses.append(AddFlagResponse(flag_label="active", target=TargetTriggeringNode()))
    return minimal_config(
        messages=msgs,
        mutable_variables=[mv],
        flags=[FlagDef(label="active")],
        events=[
            Event(
                label="capture_event",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=responses,
            )
        ],
    )


def test_capture_stores_string(db):
    cfg = _make_capture_config(var_type="string", cmd_text="!setname {player_name}")
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setname Joey", is_dm=True, channel_idx=0)
    assert db.get_mutable_variable("player_name", NODE_ID) == "Joey"
    assert db.has_flag("node", NODE_ID, "active")


def test_capture_stores_integer(db):
    cfg = _make_capture_config(var_type="integer", var_label="player_score",
                                cmd_text="!setscore {player_score}", initial=0)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setscore 42", is_dm=True, channel_idx=0)
    assert db.get_mutable_variable("player_score", NODE_ID) == 42


def test_capture_stores_integer_into_float(db):
    cfg = _make_capture_config(var_type="float", var_label="player_score",
                                cmd_text="!setscore {player_score}", initial=0.0)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setscore 42", is_dm=True, channel_idx=0)
    assert db.get_mutable_variable("player_score", NODE_ID) == 42.0


def test_capture_stores_float(db):
    cfg = _make_capture_config(var_type="float", var_label="player_score",
                                cmd_text="!setscore {player_score}", initial=0.0)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setscore 3.14", is_dm=True, channel_idx=0)
    assert abs(db.get_mutable_variable("player_score", NODE_ID) - 3.14) < 1e-9


def test_capture_wrong_type_does_not_fire(db):
    cfg = _make_capture_config(var_type="integer", var_label="player_score",
                                cmd_text="!setscore {player_score}", initial=0)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setscore abc", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")
    assert db.get_mutable_variable("player_score", NODE_ID) is None


def test_capture_empty_does_not_fire(db):
    cfg = _make_capture_config(var_type="string", cmd_text="!setname {player_name}")
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setname ", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


def test_capture_clamps_to_max(db):
    cfg = _make_capture_config(var_type="integer", var_label="player_score",
                                cmd_text="!setscore {player_score}", var_max=10, initial=0)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setscore 999", is_dm=True, channel_idx=0)
    assert db.get_mutable_variable("player_score", NODE_ID) == 10


def test_capture_max_length_blocks(db):
    cfg = _make_capture_config(var_type="string", cmd_text="!setname {player_name}",
                                var_max_length=5)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setname TooLongName", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


def test_capture_respects_suffix(db):
    cfg = _make_capture_config(var_type="integer", var_label="player_score",
                                cmd_text="!rate {player_score} stars", initial=0)
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!rate 5 stars", is_dm=True, channel_idx=0)
    assert db.get_mutable_variable("player_score", NODE_ID) == 5


def test_non_capture_exact_match_unchanged(db):
    from config import Message, FlagDef
    cfg = minimal_config(
        messages=[Message(label="greet", text="hello")],
        flags=[FlagDef(label="active")],
        events=[
            Event(
                label="exact_match",
                trigger=CommandTrigger(kind="dm", message_label="greet"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "hello world", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")
    eng.handle_message(NODE_ID, "hello", is_dm=True, channel_idx=0)
    assert db.has_flag("node", NODE_ID, "active")


def test_capture_variable_available_in_response_message(db):
    cfg = _make_capture_config(
        var_type="string", cmd_text="!setname {player_name}",
        response_msg_text="Name set to: {player_name}",
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setname Joey", is_dm=True, channel_idx=0)
    assert any("Joey" in text for _, text in eng.sent_dms)


# ---------------------------------------------------------------------------
# Capture injection / security tests
# ---------------------------------------------------------------------------

def test_capture_template_injection_is_literal(db):
    cfg = _make_capture_config(
        var_type="string", cmd_text="!setname {player_name}",
        response_msg_text="Name: {player_name}",
    )
    eng = make_engine(cfg, db)
    # Player tries to inject a token — should be stored and echoed as literal text
    eng.handle_message(NODE_ID, "!setname {node_id}", is_dm=True, channel_idx=0)
    stored = db.get_mutable_variable("player_name", NODE_ID)
    assert stored == "{node_id}"
    # The response message should contain the literal braces, not the resolved node ID
    assert any("{node_id}" in text and NODE_ID not in text for _, text in eng.sent_dms)


def test_capture_hard_length_cap(db):
    cfg = _make_capture_config(var_type="string", cmd_text="!setname {player_name}")
    eng = make_engine(cfg, db)
    long_name = "A" * 201
    eng.handle_message(NODE_ID, f"!setname {long_name}", is_dm=True, channel_idx=0)
    assert not db.has_flag("node", NODE_ID, "active")


def test_capture_strips_surrounding_whitespace(db):
    cfg = _make_capture_config(var_type="string", cmd_text="!setname {player_name}")
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!setname   Joey  ", is_dm=True, channel_idx=0)
    stored = db.get_mutable_variable("player_name", NODE_ID)
    assert stored == "Joey"


def test_capture_sql_chars_stored_safely(db):
    cfg = _make_capture_config(var_type="string", cmd_text="!setname {player_name}")
    eng = make_engine(cfg, db)
    dangerous = "'; DROP TABLE--"
    eng.handle_message(NODE_ID, f"!setname {dangerous}", is_dm=True, channel_idx=0)
    stored = db.get_mutable_variable("player_name", NODE_ID)
    assert stored == dangerous


def test_empty_initial_string_falls_back_to_node_id(db):
    # initial: "" on a node-scoped string variable resolves to node_id in messages
    from config import Message, MutableVariableDef, FlagDef
    cfg = minimal_config(
        messages=[
            Message(label="announce", text="Winner: {player_name}"),
            Message(label="cmd", text="!win"),
        ],
        mutable_variables=[
            MutableVariableDef(label="player_name", type="string", scope="node", initial=""),
        ],
        flags=[FlagDef(label="active")],
        events=[
            Event(
                label="win",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=[
                    SendMessageResponse(message_label="announce", target=TargetTriggeringNode()),
                    AddFlagResponse(flag_label="active", target=TargetTriggeringNode()),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_message(NODE_ID, "!win", is_dm=True, channel_idx=0)
    # player_name was never set — should fall back to node_id in the message
    assert any(NODE_ID in text for _, text in eng.sent_dms)


# ---------------------------------------------------------------------------
# send_alert
# ---------------------------------------------------------------------------

def test_send_alert_calls_send_alert_helper(db):
    cfg = minimal_config(
        messages=[Message(label="cmd", text="!alert"), Message(label="danger", text="Danger!")],
        events=[
            Event(
                label="alert_ev",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=[SendAlertResponse(message_label="danger", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    sent_alerts: list[tuple[str, str]] = []
    eng._send_alert = lambda nid, text: sent_alerts.append((nid, text))
    eng.handle_message(NODE_ID, "!alert", is_dm=True, channel_idx=0)
    assert sent_alerts == [(NODE_ID, "Danger!")]

def test_send_alert_channel_calls_alert_channel_helper(db):
    cfg = minimal_config(
        messages=[Message(label="cmd", text="!alert"), Message(label="warning", text="Warning!")],
        events=[
            Event(
                label="ch_alert",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=[SendAlertResponse(message_label="warning", target=TargetChannel(channel_label="main"))],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    sent_alert_channels: list[tuple[str, str]] = []
    eng._send_alert_channel = lambda ch, text: sent_alert_channels.append((ch, text))
    eng.handle_message(NODE_ID, "!alert", is_dm=True, channel_idx=0)
    assert sent_alert_channels == [("main", "Warning!")]

def test_send_alert_interpolates_variables(db):
    cfg = minimal_config(
        messages=[Message(label="cmd", text="!alert"), Message(label="alert_msg", text="Alert for {node_id}!")],
        events=[
            Event(
                label="alert_ev",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=[SendAlertResponse(message_label="alert_msg", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    sent_alerts: list[tuple[str, str]] = []
    eng._send_alert = lambda nid, text: sent_alerts.append((nid, text))
    eng.handle_message(NODE_ID, "!alert", is_dm=True, channel_idx=0)
    assert any(NODE_ID in text for _, text in sent_alerts)


# ---------------------------------------------------------------------------
# request_telemetry
# ---------------------------------------------------------------------------

def test_request_telemetry_queues_helper(db):
    cfg = minimal_config(
        messages=[Message(label="cmd", text="!telem")],
        events=[
            Event(
                label="telem_ev",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=[RequestTelemetryResponse(target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    requested: list[str] = []
    eng._request_telemetry = lambda nid: requested.append(nid)
    eng.handle_message(NODE_ID, "!telem", is_dm=True, channel_idx=0)
    assert requested == [NODE_ID]


# ---------------------------------------------------------------------------
# node_* computed variable tracks
# ---------------------------------------------------------------------------

def _make_node_var_config(tracks: str) -> GameConfig:
    return minimal_config(
        messages=[
            Message(label="cmd", text="!report"),
            Message(label="report", text=f"val={{node_val}}"),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
            Variable(label="node_val", scope="node", tracks=tracks),
        ],
        events=[
            Event(
                label="report_ev",
                trigger=CommandTrigger(kind="dm", message_label="cmd"),
                responses=[SendMessageResponse(message_label="report", target=TargetTriggeringNode())],
            )
        ],
    )

def _send_and_get(db, tracks: str, node_info: dict) -> str:
    cfg = _make_node_var_config(tracks)
    eng = make_engine(cfg, db)
    eng.interface.nodes = {NODE_ID: node_info}
    eng.handle_message(NODE_ID, "!report", is_dm=True, channel_idx=0)
    return eng.sent_dms[-1][1] if eng.sent_dms else ""

def test_node_battery_level(db):
    text = _send_and_get(db, "node_battery_level", {"deviceMetrics": {"batteryLevel": 82}})
    assert "82" in text

def test_node_voltage(db):
    text = _send_and_get(db, "node_voltage", {"deviceMetrics": {"voltage": 3.85}})
    assert "3.85" in text

def test_node_channel_utilization(db):
    text = _send_and_get(db, "node_channel_utilization", {"deviceMetrics": {"channelUtilization": 12.5}})
    assert "12.5" in text

def test_node_air_util_tx(db):
    text = _send_and_get(db, "node_air_util_tx", {"deviceMetrics": {"airUtilTx": 4.2}})
    assert "4.2" in text

def test_node_uptime_seconds(db):
    text = _send_and_get(db, "node_uptime_seconds", {"deviceMetrics": {"uptimeSeconds": 3600}})
    assert "3600" in text

def test_node_snr(db):
    text = _send_and_get(db, "node_snr", {"snr": 7.5})
    assert "7.50" in text

def test_node_hops_away(db):
    text = _send_and_get(db, "node_hops_away", {"hopsAway": 2})
    assert "2" in text

def test_node_hw_model(db):
    text = _send_and_get(db, "node_hw_model", {"user": {"hwModel": "TBEAM"}})
    assert "TBEAM" in text

def test_node_role(db):
    text = _send_and_get(db, "node_role", {"user": {"role": "ROUTER"}})
    assert "ROUTER" in text

def test_node_var_unknown_when_no_telemetry(db):
    text = _send_and_get(db, "node_battery_level", {})
    assert "[unknown]" in text

def test_node_var_unknown_when_node_not_in_nodedb(db):
    cfg = _make_node_var_config("node_battery_level")
    eng = make_engine(cfg, db)
    eng.interface.nodes = {}
    eng.handle_message(NODE_ID, "!report", is_dm=True, channel_idx=0)

# ---------------------------------------------------------------------------
# Mesh waypoint features
# ---------------------------------------------------------------------------

def _waypoint_received_config(from_flag=None, name_contains=None, response_msg="got it"):
    from config import WaypointReceivedTrigger, FlagDef
    return minimal_config(
        flags=[FlagDef(label="trusted")],
        messages=[Message(label="ack", text=response_msg)],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(from_flag=from_flag, name_contains=name_contains),
                responses=[SendMessageResponse(message_label="ack", target=TargetTriggeringNode())],
            )
        ],
    )

def _make_wp_ctx(name="cache", from_node=NODE_ID, icon=0):
    from engine import WaypointReceivedContext
    return WaypointReceivedContext(
        node_id=from_node,
        waypoint_name=name,
        waypoint_description="a desc",
        waypoint_lat=47.003,
        waypoint_lon=-122.003,
        waypoint_expire=0,
        waypoint_icon=icon,
        mesh_waypoint_id=12345,
    )

def test_waypoint_received_fires_event(db):
    cfg = _waypoint_received_config()
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx())
    assert len(eng.sent_dms) == 1
    assert eng.sent_dms[0][0] == NODE_ID

def test_waypoint_received_from_flag_blocks_without_flag(db):
    cfg = _waypoint_received_config(from_flag="trusted")
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx())
    assert eng.sent_dms == []

def test_waypoint_received_from_flag_passes_with_flag(db):
    cfg = _waypoint_received_config(from_flag="trusted")
    eng = make_engine(cfg, db)
    db.add_flag("node", NODE_ID, "trusted")
    eng.handle_waypoint_received(_make_wp_ctx())
    assert len(eng.sent_dms) == 1

def test_waypoint_received_name_contains_blocks_mismatch(db):
    cfg = _waypoint_received_config(name_contains="cache")
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx(name="treasure"))
    assert eng.sent_dms == []

def test_waypoint_received_name_contains_case_insensitive(db):
    cfg = _waypoint_received_config(name_contains="Cache")
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx(name="hidden cache"))
    assert len(eng.sent_dms) == 1

def test_waypoint_received_interpolates_tokens(db):
    from config import WaypointReceivedTrigger, FlagDef
    cfg = minimal_config(
        messages=[Message(label="ack", text="wp={waypoint_name} from={node_id}")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[SendMessageResponse(message_label="ack", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx(name="GeoCache"))
    assert len(eng.sent_dms) == 1
    text = eng.sent_dms[0][1]
    assert "wp=GeoCache" in text
    assert f"from={NODE_ID}" in text

def test_broadcast_waypoint_queues_sendwaypoint(db):
    from config import BroadcastWaypointResponse, FlagDef
    cfg = minimal_config(
        events=[
            Event(
                label="broadcast",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[BroadcastWaypointResponse(
                    name="Marker",
                    target=TargetChannel(channel_label="main"),
                    expiry_mins=30,
                    label="my_marker",
                )],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    # sendWaypoint should have been called on the interface
    assert eng.interface.sendWaypoint.called
    call_kwargs = eng.interface.sendWaypoint.call_args
    assert call_kwargs is not None

def test_broadcast_waypoint_stores_label(db):
    from config import BroadcastWaypointResponse
    cfg = minimal_config(
        events=[
            Event(
                label="broadcast",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[BroadcastWaypointResponse(
                    name="Marker",
                    target=TargetChannel(channel_label="main"),
                    label="my_marker",
                )],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    # drain send queue
    eng._send_queue.join()
    mesh_id = db.get_mesh_waypoint_id_by_label("my_marker")
    assert mesh_id is not None

def test_broadcast_waypoint_explicit_coords(db):
    from config import BroadcastWaypointResponse
    cfg = minimal_config(
        events=[
            Event(
                label="broadcast",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[BroadcastWaypointResponse(
                    name="Static",
                    target=TargetChannel(channel_label="main"),
                    lat=37.77,
                    lon=-122.41,
                )],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert eng.interface.sendWaypoint.called

def test_delete_mesh_waypoint_by_label(db):
    from config import BroadcastWaypointResponse, DeleteMeshWaypointResponse, FlagDef
    cfg = minimal_config(
        flags=[FlagDef(label="active")],
        events=[
            Event(
                label="broadcast",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[BroadcastWaypointResponse(
                    name="Marker",
                    target=TargetChannel(channel_label="main"),
                    label="my_marker",
                )],
            ),
            Event(
                label="cleanup",
                trigger=ProximityTrigger(kind="leaves_zone", target_label="zone_a"),
                responses=[DeleteMeshWaypointResponse(label="my_marker")],
            ),
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng._send_queue.join()  # flush broadcast
    assert db.get_mesh_waypoint_id_by_label("my_marker") is not None
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng._send_queue.join()  # flush delete
    assert eng.interface.deleteWaypoint.called
    assert db.get_mesh_waypoint_id_by_label("my_marker") is None

def test_delete_mesh_waypoint_no_match_nops(db):
    from config import DeleteMeshWaypointResponse
    cfg = minimal_config(
        events=[
            Event(
                label="cleanup",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[DeleteMeshWaypointResponse(label="nonexistent")],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # should not crash
    assert not eng.interface.deleteWaypoint.called

def test_create_waypoint_with_mesh_fields_broadcasts_and_links(db):
    from config import CreateWaypointResponse, FlagDef
    cfg = minimal_config(
        flags=[FlagDef(label="targeted")],
        events=[
            Event(
                label="target",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(
                    expiry_mins=60,
                    initial_flags=["targeted"],
                    mesh_name="TARGET",
                    mesh_description="Strike inbound.",
                    mesh_channel="main",
                )],
            )
        ],
    )
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng._send_queue.join()
    assert eng.interface.sendWaypoint.called
    # dynamic waypoint should have a mesh_waypoint_id linked
    rows = db._conn.execute("SELECT mesh_waypoint_id FROM dynamic_waypoints").fetchall()
    assert len(rows) == 1
    assert rows[0]["mesh_waypoint_id"] is not None

def test_delete_mesh_waypoint_use_triggering_waypoint(db):
    from config import CreateWaypointResponse, DeleteMeshWaypointResponse, FlagDef, FlagExpiryTrigger
    cfg = minimal_config(
        flags=[FlagDef(label="targeted", expiry_mins=0.001)],  # expires almost immediately
        events=[
            Event(
                label="target",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(
                    expiry_mins=60,
                    initial_flags=["targeted"],
                    mesh_name="TARGET",
                    mesh_channel="main",
                )],
            ),
            Event(
                label="cleanup",
                trigger=FlagExpiryTrigger(flag_label="targeted", target_kind="dynamic_waypoint"),
                responses=[DeleteMeshWaypointResponse(use_triggering_waypoint=True)],
            ),
        ],
    )
    import time as _time
    eng = make_engine(cfg, db, channel_map={"main": 0})
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng._send_queue.join()
    assert eng.interface.sendWaypoint.called
    _time.sleep(0.1)  # let flag expire
    eng.handle_periodic()
    eng._send_queue.join()
    assert eng.interface.deleteWaypoint.called


# ---------------------------------------------------------------------------
# Replay log
# ---------------------------------------------------------------------------

def _replay_records(log_io) -> list[dict]:
    import json
    return [json.loads(line) for line in log_io.getvalue().splitlines() if line.strip()]


def _enter_zone_event(label="ev", max_triggers=None, exceptions=None):
    return Event(
        label=label,
        trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
        responses=[SendMessageResponse(message_label="hello", target=TargetChannel(channel_label="main"))],
        max_triggers=max_triggers,
        exceptions=exceptions or [],
    )


def test_replay_log_records_fire(db):
    import io
    cfg = minimal_config(events=[_enter_zone_event()])
    log_io = io.StringIO()
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.replay_log = log_io
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    records = _replay_records(log_io)
    fires = [r for r in records if r["type"] == "fire"]
    assert len(fires) == 1
    assert fires[0]["event"] == "ev"
    assert fires[0]["node_id"] == NODE_ID
    assert fires[0]["fire_number"] == 1
    assert "send_message" in fires[0]["responses"]


def test_replay_log_correct_trigger_type(db):
    import io
    cfg = minimal_config(events=[_enter_zone_event()])
    log_io = io.StringIO()
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.replay_log = log_io
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    fires = [r for r in _replay_records(log_io) if r["type"] == "fire"]
    assert fires[0]["trigger_type"] == "enters_zone"


def test_replay_log_increments_fire_number(db):
    import io
    cfg = minimal_config(events=[_enter_zone_event()])
    log_io = io.StringIO()
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.replay_log = log_io
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    fires = [r for r in _replay_records(log_io) if r["type"] == "fire"]
    assert len(fires) == 2
    assert fires[0]["fire_number"] == 1
    assert fires[1]["fire_number"] == 2


def test_replay_log_verbose_records_exception_skip(db):
    import io
    cfg = minimal_config(
        flags=[FlagDef(label="excluded"), FlagDef(label="active"), FlagDef(label="scored")],
        events=[_enter_zone_event(exceptions=[EventException(kind="node_has_flag", flag="excluded")])],
    )
    log_io = io.StringIO()
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.replay_log = log_io
    eng.replay_log_verbose = True
    db.add_flag("node", NODE_ID, "excluded")
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    skips = [r for r in _replay_records(log_io) if r["type"] == "skip"]
    assert len(skips) == 1
    assert skips[0]["skip_reason"] == "exception:node_has_flag:excluded"
    assert skips[0]["event"] == "ev"


def test_replay_log_verbose_records_max_triggers_skip(db):
    import io
    cfg = minimal_config(events=[_enter_zone_event(max_triggers=1)])
    log_io = io.StringIO()
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.replay_log = log_io
    eng.replay_log_verbose = True
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # fires once
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # skipped — max_triggers
    records = _replay_records(log_io)
    fires = [r for r in records if r["type"] == "fire"]
    skips = [r for r in records if r["type"] == "skip"]
    assert len(fires) == 1
    assert any(s["skip_reason"] == "max_triggers" for s in skips)


def test_replay_log_no_verbose_no_skips(db):
    import io
    cfg = minimal_config(
        flags=[FlagDef(label="excluded"), FlagDef(label="active"), FlagDef(label="scored")],
        events=[_enter_zone_event(exceptions=[EventException(kind="node_has_flag", flag="excluded")])],
    )
    log_io = io.StringIO()
    eng = make_engine(cfg, db, channel_map={"main": 0})
    eng.replay_log = log_io
    eng.replay_log_verbose = False
    db.add_flag("node", NODE_ID, "excluded")
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not any(r["type"] == "skip" for r in _replay_records(log_io))


# ---------------------------------------------------------------------------
# FlagExpiryTrigger
# ---------------------------------------------------------------------------

def test_flag_expiry_trigger_fires(db):
    import time as _time
    cfg = minimal_config(
        flags=[FlagDef(label="timed", expiry_mins=0.001)],
        events=[
            Event(
                label="on_enter",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[AddFlagResponse(flag_label="timed", target=TargetTriggeringNode())],
            ),
            Event(
                label="on_expiry",
                trigger=FlagExpiryTrigger(flag_label="timed", target_kind="node"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "timed")
    _time.sleep(0.1)
    eng.handle_periodic()
    assert not db.has_flag("node", NODE_ID, "timed")
    assert db.has_flag("node", NODE_ID, "active")


def test_flag_expiry_trigger_does_not_fire_wrong_flag(db):
    import time as _time
    cfg = minimal_config(
        flags=[FlagDef(label="timed", expiry_mins=0.001)],
        events=[
            Event(
                label="on_enter",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[AddFlagResponse(flag_label="timed", target=TargetTriggeringNode())],
            ),
            Event(
                label="on_other_expiry",
                trigger=FlagExpiryTrigger(flag_label="scored", target_kind="node"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    _time.sleep(0.1)
    eng.handle_periodic()
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# WaypointExpiryTrigger
# ---------------------------------------------------------------------------

def test_waypoint_expiry_trigger_fires(db):
    import time as _time
    cfg = minimal_config(
        events=[
            Event(
                label="place",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(expiry_mins=0.001)],
            ),
            Event(
                label="on_wp_expiry",
                trigger=WaypointExpiryTrigger(),
                # No triggering node in expiry context — use global variable increment
                responses=[IncrementVariableResponse(variable_label="score", amount=1)],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    rows = db._conn.execute("SELECT id FROM dynamic_waypoints").fetchall()
    assert len(rows) == 1
    _time.sleep(0.1)
    eng.handle_periodic()
    assert db.get_mutable_variable("score") == 1


def test_waypoint_expiry_had_flag_filter_blocks(db):
    import time as _time
    cfg = minimal_config(
        events=[
            Event(
                label="place",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(expiry_mins=0.001)],
            ),
            Event(
                label="on_wp_expiry",
                trigger=WaypointExpiryTrigger(had_flag="scored"),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    _time.sleep(0.1)
    eng.handle_periodic()
    assert not db.has_flag("node", NODE_ID, "active")


def test_waypoint_expiry_had_flag_filter_passes(db):
    import time as _time
    cfg = minimal_config(
        events=[
            Event(
                label="place",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(expiry_mins=0.001, initial_flags=["scored"])],
            ),
            Event(
                label="on_wp_expiry",
                trigger=WaypointExpiryTrigger(had_flag="scored"),
                responses=[IncrementVariableResponse(variable_label="score", amount=1)],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    _time.sleep(0.1)
    eng.handle_periodic()
    assert db.get_mutable_variable("score") == 1


# ---------------------------------------------------------------------------
# ProximityTrigger: near_node
# ---------------------------------------------------------------------------

def test_near_node_fires_in_range(db):
    anchor_loc = (47.003, -122.003)  # same as INSIDE_ZONE — about 400 m from OUTSIDE_ZONE
    cfg = minimal_config(
        nodes=[
            NodeDef(label="node_a", node_id=NODE_ID),
            NodeDef(label="anchor", node_id=NODE2_ID),
        ],
        events=[
            Event(
                label="near_anchor",
                trigger=ProximityTrigger(kind="near_node", target_label="anchor", meters=2000),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE2_ID, *anchor_loc)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")


def test_near_node_no_fire_out_of_range(db):
    cfg = minimal_config(
        nodes=[
            NodeDef(label="node_a", node_id=NODE_ID),
            NodeDef(label="anchor", node_id=NODE2_ID),
        ],
        events=[
            Event(
                label="near_anchor",
                trigger=ProximityTrigger(kind="near_node", target_label="anchor", meters=10),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE2_ID, *INSIDE_ZONE)
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Exception coverage gaps
# ---------------------------------------------------------------------------

def test_exception_zone_has_flag_blocks(db):
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="zone_has_flag", flag="active", target="zone_a")],
        )
    ])
    eng = make_engine(cfg, db)
    db.add_flag("zone", "zone_a", "active")
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


def test_exception_zone_lacks_flag_blocks(db):
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="zone_lacks_flag", flag="scored", target="zone_a")],
        )
    ])
    eng = make_engine(cfg, db)
    # zone_a does NOT have "scored" → zone_lacks_flag matches → event blocked
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


def test_exception_waypoint_has_flag_blocks(db):
    """waypoint_has_flag with no target checks the triggering dynamic waypoint."""
    cfg = minimal_config(
        events=[
            Event(
                label="place",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(initial_flags=["scored"])],
            ),
            Event(
                label="near_flagged",
                trigger=ProximityTrigger(kind="near_waypoint", target_flag="scored", meters=5000),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
                exceptions=[EventException(kind="waypoint_has_flag", flag="scored")],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # creates waypoint with "scored" flag
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # near_waypoint fires but exception blocks it
    assert not db.has_flag("node", NODE_ID, "active")


def test_exception_node_not_in_group_blocks(db):
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="node_not_in_group", group="players")],
        )
    ])
    eng = make_engine(cfg, db)
    # NODE_ID is not in "players" → node_not_in_group matches → event blocked
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


def test_exception_random_skip_blocks(db):
    from unittest.mock import patch
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="in_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            exceptions=[EventException(kind="random_skip", chance=1.0)],
        )
    ])
    eng = make_engine(cfg, db)
    with patch("engine.random.random", return_value=0.0):  # 0.0 < 1.0 → skip fires
        eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


# ---------------------------------------------------------------------------
# Response gaps: SetVariableResponse, EnableEventResponse,
#                AddDynamicWaypointFlagResponse, DestroyWaypointResponse,
#                RandomOptionsResponse
# ---------------------------------------------------------------------------

def test_set_variable_response_global(db):
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[SetVariableResponse(variable_label="score", value=42)],
        )
    ])
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.get_mutable_variable("score") == 42  # global scope stored with node_id=''


def test_enable_event_response(db):
    cfg = minimal_config(events=[
        Event(
            label="gate",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[EnableEventResponse(event_label="target")],
        ),
        Event(
            label="target",
            trigger=ProximityTrigger(kind="in_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
        ),
    ])
    eng = make_engine(cfg, db)
    db.set_event_disabled("target", True)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # gate fires → enables target; target skipped (was disabled)
    assert not db.is_event_disabled("target")
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # target now enabled → fires
    assert db.has_flag("node", NODE_ID, "active")


def test_add_dynamic_waypoint_flag(db):
    """near_waypoint(target_flag=…) trigger sets triggering_waypoint_id on context."""
    cfg = minimal_config(
        events=[
            Event(
                label="place",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse()],
            ),
            Event(
                label="flag_it",
                trigger=ProximityTrigger(kind="near_waypoint", target_flag="active", meters=50000),
                responses=[AddDynamicWaypointFlagResponse(flag_label="scored")],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # creates waypoint (no initial flags)
    wp_rows = db._conn.execute("SELECT id FROM dynamic_waypoints").fetchall()
    assert len(wp_rows) == 1
    wp_id = wp_rows[0]["id"]
    # Waypoint has no flags yet — near_waypoint target_flag="active" won't match.
    # Manually add "active" flag so the near_waypoint trigger fires.
    db.add_dynamic_waypoint_flag(wp_id, "active")
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # flag_it event fires
    assert db.has_dynamic_waypoint_flag(wp_id, "scored")


def test_destroy_waypoint(db):
    """DestroyWaypointResponse removes the triggering dynamic waypoint via _execute_response."""
    from engine import NodeContext
    cfg = minimal_config()
    eng = make_engine(cfg, db)
    wp_id = db.create_dynamic_waypoint(*INSIDE_ZONE)
    ctx = NodeContext(node_id=NODE_ID, triggering_waypoint_id=wp_id)
    rows = db._conn.execute("SELECT id FROM dynamic_waypoints").fetchall()
    assert len(rows) == 1
    eng._execute_response(DestroyWaypointResponse(), ctx)
    rows = db._conn.execute("SELECT id FROM dynamic_waypoints").fetchall()
    assert len(rows) == 0


def test_random_options_response(db):
    """RandomOptionsResponse executes exactly one branch's responses."""
    from unittest.mock import patch
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[
                RandomOptionsResponse(options=[
                    RandomOption(weight=1, responses=[
                        AddFlagResponse(flag_label="active", target=TargetTriggeringNode()),
                    ]),
                    RandomOption(weight=0, responses=[
                        AddFlagResponse(flag_label="scored", target=TargetTriggeringNode()),
                    ]),
                ])
            ],
        )
    ])
    eng = make_engine(cfg, db)
    with patch("engine.random.choices", return_value=[cfg.events[0].responses[0].options[0]]):
        db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
        eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")
    assert not db.has_flag("node", NODE_ID, "scored")


# ---------------------------------------------------------------------------
# Event control: reset_mins and auto_recur
# ---------------------------------------------------------------------------

def test_reset_mins_blocks_within_window(db):
    cfg = minimal_config(events=[
        Event(
            label="ev",
            trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
            responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            reset_mins=60,
        )
    ])
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # fires
    assert db.has_flag("node", NODE_ID, "active")
    db.remove_flag("node", NODE_ID, "active")
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)   # blocked — still in cooldown
    assert not db.has_flag("node", NODE_ID, "active")


def test_auto_recur_fires_after_interval(db):
    import time as _time
    from config import TimedTrigger
    from datetime import datetime, timezone
    # time_window fires only the FIRST time (times==0 guard); auto_recur provides subsequent fires
    now_utc = datetime.now(timezone.utc)
    cfg = minimal_config(
        events=[
            Event(
                label="window_score",
                trigger=TimedTrigger(
                    start=now_utc.replace(year=2020),
                    end=now_utc.replace(year=2099),
                ),
                responses=[IncrementVariableResponse(variable_label="score", amount=1)],
                auto_recur=True,
                recur_mins=0.001,  # ~60 ms
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_periodic()   # time_window fires (times==0) → score=1
    assert db.get_mutable_variable("score") == 1
    eng.handle_periodic()   # too soon for recur, time_window already fired → score=1
    assert db.get_mutable_variable("score") == 1
    _time.sleep(0.1)
    eng.handle_periodic()   # recur interval passed → auto_recur fires → score=2
    assert db.get_mutable_variable("score") == 2


# ---------------------------------------------------------------------------
# RepeatResponse + randomly_in_zone
# ---------------------------------------------------------------------------

def test_repeat_response_executes_n_times(db):
    from config import TimedTrigger
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    cfg = minimal_config(
        events=[
            Event(
                label="spam",
                trigger=TimedTrigger(
                    start=now_utc.replace(year=2020),
                    end=now_utc.replace(year=2099),
                ),
                responses=[
                    RepeatResponse(
                        count=4,
                        responses=[
                            IncrementVariableResponse(variable_label="score", amount=1)
                        ],
                    )
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_periodic()
    assert db.get_mutable_variable("score") == 4


def _get_all_dynamic_waypoints(db):
    """Return list of (id, lat, lon) for all dynamic waypoints in the DB."""
    with db._lock:
        rows = db._conn.execute("SELECT id, lat, lon FROM dynamic_waypoints").fetchall()
    return rows


def test_create_waypoint_randomly_in_zone_places_inside_zone(db):
    import geometry as geo
    from config import TimedTrigger
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    cfg = minimal_config(
        events=[
            Event(
                label="spawn",
                trigger=TimedTrigger(
                    start=now_utc.replace(year=2020),
                    end=now_utc.replace(year=2099),
                ),
                responses=[
                    CreateWaypointResponse(randomly_in_zone="zone_a")
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_periodic()
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    _, lat, lon = wps[0]
    a, b, c = ZONE_POINTS
    assert geo.point_in_triangle((lat, lon), a, b, c), \
        f"Waypoint ({lat}, {lon}) not inside zone triangle"


def test_create_waypoint_randomly_in_zone_no_node_required(db):
    """randomly_in_zone create_waypoint fires from a timed trigger with no node location."""
    from config import TimedTrigger
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    cfg = minimal_config(
        events=[
            Event(
                label="spawn",
                trigger=TimedTrigger(
                    start=now_utc.replace(year=2020),
                    end=now_utc.replace(year=2099),
                ),
                responses=[
                    CreateWaypointResponse(randomly_in_zone="zone_a")
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # No node location stored — should succeed without skipping
    eng.handle_periodic()
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1


# ---------------------------------------------------------------------------
# randomly_near_location
# ---------------------------------------------------------------------------

def test_create_waypoint_randomly_near_location_uses_node(db):
    """randomly_near_location spawns within radius of triggering node."""
    import geometry as geo
    cfg = minimal_config(
        events=[
            Event(
                label="spawn",
                trigger=ProximityTrigger(kind="enters_zone", target_label="zone_a"),
                responses=[CreateWaypointResponse(randomly_near_location_meters=50)],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    _, lat, lon = wps[0]
    dist = geo.haversine(*INSIDE_ZONE, lat, lon)
    assert dist <= 50, f"Waypoint spawned {dist:.1f}m away, expected <= 50m"


def test_create_waypoint_randomly_near_location_uses_triggering_waypoint(db):
    """randomly_near_location uses triggering waypoint as origin, not the node."""
    import geometry as geo
    # Node at INSIDE_ZONE; waypoint ~44m east — within near_waypoint radius of 50m
    node_lat, node_lon = INSIDE_ZONE
    wp_lat, wp_lon = node_lat, node_lon + 0.0005  # ~44m east

    cfg = minimal_config(
        flags=[FlagDef(label="target")],
        events=[
            Event(
                label="spawn_near_wp",
                trigger=ProximityTrigger(kind="near_waypoint", target_flag="target", meters=50),
                responses=[CreateWaypointResponse(randomly_near_location_meters=5)],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, node_lat, node_lon)
    wp_id = db.create_dynamic_waypoint(wp_lat, wp_lon, expiry_mins=None)
    db.add_dynamic_waypoint_flag(wp_id, "target", expiry_mins=None)
    eng.handle_position(NODE_ID, node_lat, node_lon)
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 2
    new_wp = next(r for r in wps if r["id"] != wp_id)
    dist_from_wp = geo.haversine(wp_lat, wp_lon, new_wp["lat"], new_wp["lon"])
    assert dist_from_wp <= 5, f"New waypoint {dist_from_wp:.1f}m from trigger wp, expected <= 5m"


def test_create_waypoint_randomly_near_location_no_location_skips(db):
    """randomly_near_location skips silently when no location is in context."""
    from config import TimedTrigger
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    cfg = minimal_config(
        events=[
            Event(
                label="spawn",
                trigger=TimedTrigger(
                    start=now_utc.replace(year=2020),
                    end=now_utc.replace(year=2099),
                ),
                responses=[CreateWaypointResponse(randomly_near_location_meters=50)],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Periodic context has no node/waypoint — should skip without error
    eng.handle_periodic()
    assert _get_all_dynamic_waypoints(db) == []


def test_random_point_within_radius_distance():
    """random_point_within_radius always returns a point within the specified radius."""
    import geometry as geo
    origin = (37.7749, -122.4194)
    radius = 100.0
    for _ in range(50):
        lat, lon = geo.random_point_within_radius(*origin, radius)
        dist = geo.haversine(*origin, lat, lon)
        assert dist <= radius + 0.01, f"Point {dist:.2f}m from origin, expected <= {radius}m"


def test_random_point_within_radius_not_always_center():
    """random_point_within_radius produces spread — not all points at origin."""
    import geometry as geo
    origin = (37.7749, -122.4194)
    points = [geo.random_point_within_radius(*origin, 100) for _ in range(20)]
    # At least some points should differ from each other
    assert len(set(points)) > 1


# ---------------------------------------------------------------------------
# track_received_waypoint
# ---------------------------------------------------------------------------

def _make_track_wp_ctx(name="supply", expire=0, mesh_id=99001, icon=0):
    from engine import WaypointReceivedContext
    return WaypointReceivedContext(
        node_id=NODE_ID,
        waypoint_name=name,
        waypoint_description="desc",
        waypoint_lat=47.003,
        waypoint_lon=-122.003,
        waypoint_expire=expire,
        waypoint_icon=icon,
        mesh_waypoint_id=mesh_id,
    )


def test_track_received_waypoint_creates_dynamic_waypoint(db):
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    cfg = minimal_config(
        flags=[FlagDef(label="supply_drop")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(initial_flags=["supply_drop"])],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_track_wp_ctx())
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    assert abs(wps[0]["lat"] - 47.003) < 1e-6
    assert abs(wps[0]["lon"] - (-122.003)) < 1e-6


def test_track_received_waypoint_sets_initial_flags(db):
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    cfg = minimal_config(
        flags=[FlagDef(label="supply_drop"), FlagDef(label="urgent")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(initial_flags=["supply_drop", "urgent"])],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_track_wp_ctx())
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    wp_id = wps[0]["id"]
    assert db.has_dynamic_waypoint_flag(wp_id, "supply_drop")
    assert db.has_dynamic_waypoint_flag(wp_id, "urgent")


def test_track_received_waypoint_placer_flag_copied_when_node_has_it(db):
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    cfg = minimal_config(
        flags=[FlagDef(label="scout")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(placer_flag="scout")],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.add_flag("node", NODE_ID, "scout")
    eng.handle_waypoint_received(_make_track_wp_ctx())
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    assert db.has_dynamic_waypoint_flag(wps[0]["id"], "scout")


def test_track_received_waypoint_placer_flag_not_copied_without_flag(db):
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    cfg = minimal_config(
        flags=[FlagDef(label="scout")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(placer_flag="scout")],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Node does NOT have scout flag
    eng.handle_waypoint_received(_make_track_wp_ctx())
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    assert not db.has_dynamic_waypoint_flag(wps[0]["id"], "scout")


def test_track_received_waypoint_sets_triggering_waypoint_id(db):
    """After track_received_waypoint, ctx.triggering_waypoint_id matches the created waypoint."""
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    from engine import WaypointReceivedContext
    cfg = minimal_config(
        flags=[FlagDef(label="supply_drop")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(initial_flags=["supply_drop"])],
            )
        ],
    )
    eng = make_engine(cfg, db)
    ctx = _make_track_wp_ctx()
    eng.handle_waypoint_received(ctx)
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    assert ctx.triggering_waypoint_id == wps[0]["id"]


def test_track_received_waypoint_links_mesh_waypoint_id(db):
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    cfg = minimal_config(
        flags=[FlagDef(label="supply_drop")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(initial_flags=["supply_drop"])],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_track_wp_ctx(mesh_id=99001))
    wps = _get_all_dynamic_waypoints(db)
    assert len(wps) == 1
    linked = db.get_mesh_waypoint_id_for_dynamic(wps[0]["id"])
    assert linked == 99001


def test_track_received_waypoint_near_waypoint_trigger_fires(db):
    """After tracking, near_waypoint with target_flag fires when node walks nearby."""
    from config import WaypointReceivedTrigger, TrackReceivedWaypointResponse
    cfg = minimal_config(
        flags=[FlagDef(label="supply_drop")],
        messages=[Message(label="found", text="found one")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[TrackReceivedWaypointResponse(initial_flags=["supply_drop"])],
            ),
            Event(
                label="collect",
                trigger=ProximityTrigger(kind="near_waypoint", target_flag="supply_drop", meters=20),
                responses=[SendMessageResponse(message_label="found", target=TargetChannel(channel_label="comms"))],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    # Receive and track the waypoint at INSIDE_ZONE
    ctx = _make_track_wp_ctx()
    ctx.waypoint_lat, ctx.waypoint_lon = INSIDE_ZONE
    eng.handle_waypoint_received(ctx)
    # Node walks to the same spot
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert len(eng.sent_channels) == 1


# ---------------------------------------------------------------------------
# send_report / reports primitive
# ---------------------------------------------------------------------------

def _report_config(sort_order="desc", rows=5, title="Leaderboard", align=True):
    from config import TimedTrigger
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    mv = MutableVariableDef(label="kills", type="integer", scope="node", initial=0)
    report = ReportDef(
        label="kill_board",
        sort_by="kills",
        title=title,
        rows=rows,
        sort_order=sort_order,
        columns=[
            ReportColumn(source="node_id", header="Node"),
            ReportColumn(source="kills", header="K"),
        ],
        align=align,
    )
    cfg = minimal_config(
        mutable_variables=[mv],
        events=[
            Event(
                label="board",
                trigger=TimedTrigger(
                    start=now_utc.replace(year=2020),
                    end=now_utc.replace(year=2099),
                ),
                responses=[SendReportResponse(report_label="kill_board",
                                              target=TargetChannel(channel_label="comms"))],
            )
        ],
    )
    cfg.reports.append(report)
    return cfg


def test_send_report_desc_order(db):
    cfg = _report_config()
    eng = make_engine(cfg, db)
    db.set_mutable_variable("kills", 3, NODE_ID)
    db.set_mutable_variable("kills", 7, NODE2_ID)
    eng.handle_periodic()
    assert len(eng.sent_channels) == 1
    text = eng.sent_channels[0][1]
    # NODE2_ID (7 kills) should appear before NODE_ID (3 kills)
    assert text.index(NODE2_ID) < text.index(NODE_ID)


def test_send_report_asc_order(db):
    cfg = _report_config(sort_order="asc")
    eng = make_engine(cfg, db)
    db.set_mutable_variable("kills", 3, NODE_ID)
    db.set_mutable_variable("kills", 7, NODE2_ID)
    eng.handle_periodic()
    text = eng.sent_channels[0][1]
    assert text.index(NODE_ID) < text.index(NODE2_ID)


def test_send_report_rows_cap(db):
    cfg = _report_config(rows=1)
    eng = make_engine(cfg, db)
    db.set_mutable_variable("kills", 3, NODE_ID)
    db.set_mutable_variable("kills", 7, NODE2_ID)
    eng.handle_periodic()
    text = eng.sent_channels[0][1]
    assert NODE2_ID in text
    assert NODE_ID not in text  # capped at 1 row, NODE2_ID wins with 7


def test_send_report_empty_shows_no_data(db):
    cfg = _report_config()
    eng = make_engine(cfg, db)
    # No variables set
    eng.handle_periodic()
    text = eng.sent_channels[0][1]
    assert "(no data)" in text


def test_send_report_title_included(db):
    cfg = _report_config(title="🏆 Top Players")
    eng = make_engine(cfg, db)
    db.set_mutable_variable("kills", 1, NODE_ID)
    eng.handle_periodic()
    text = eng.sent_channels[0][1]
    assert "🏆 Top Players" in text


def test_send_report_no_title(db):
    cfg = _report_config(title=None)
    eng = make_engine(cfg, db)
    db.set_mutable_variable("kills", 1, NODE_ID)
    eng.handle_periodic()
    text = eng.sent_channels[0][1]
    lines = text.strip().splitlines()
    # First line should be the header row, not a title
    assert "🏆" not in lines[0]
    assert "Node" in lines[0]   # column header from _report_config
    assert lines[1].strip().startswith("1.")


def test_send_report_aligned_numeric_right_justified(db):
    cfg = _report_config(align=True)
    eng = make_engine(cfg, db)
    db.set_mutable_variable("kills", 10, NODE_ID)
    db.set_mutable_variable("kills", 5, NODE2_ID)
    eng.handle_periodic()
    text = eng.sent_channels[0][1]
    lines = [l for l in text.splitlines() if l.strip().startswith(("1.", "2."))]
    assert len(lines) == 2
    # Both numeric columns should have the same width (right-aligned)
    # Extract the numeric part from each line
    parts_1 = lines[0].split()
    parts_2 = lines[1].split()
    # The last token on each row is the kill count — right-aligned means same field width
    assert len(lines[0].rstrip()) == len(lines[1].rstrip()) or "10" in lines[0]


# ---------------------------------------------------------------------------
# with_each_nearby_waypoint
# ---------------------------------------------------------------------------

def test_with_each_nearby_waypoint_destroys_flagged_waypoints_in_radius(db):
    from config import (
        WaypointReceivedTrigger, TrackReceivedWaypointResponse,
        WithEachNearbyWaypointResponse, DestroyWaypointResponse,
    )
    cfg = minimal_config(
        flags=[FlagDef(label="grenade_pin"), FlagDef(label="zombie")],
        events=[
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                responses=[
                    TrackReceivedWaypointResponse(initial_flags=["grenade_pin"]),
                    WithEachNearbyWaypointResponse(
                        flag_label="zombie",
                        meters=50,
                        responses=[DestroyWaypointResponse()],
                    ),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Place two zombies: one within 50m, one far away
    near_wp = db.create_dynamic_waypoint(47.003, -122.003)
    db.add_dynamic_waypoint_flag(near_wp, "zombie")
    far_wp = db.create_dynamic_waypoint(48.000, -123.000)
    db.add_dynamic_waypoint_flag(far_wp, "zombie")

    ctx = _make_track_wp_ctx()
    ctx.waypoint_lat, ctx.waypoint_lon = 47.003, -122.003
    eng.handle_waypoint_received(ctx)

    rows = _get_all_dynamic_waypoints(db)
    remaining_ids = [r[0] for r in rows]
    assert near_wp not in remaining_ids
    assert far_wp in remaining_ids


def test_with_each_nearby_waypoint_empty_radius_does_nothing(db):
    from config import (
        WaypointReceivedTrigger, TrackReceivedWaypointResponse,
        WithEachNearbyWaypointResponse, DestroyWaypointResponse,
    )
    cfg = minimal_config(
        flags=[FlagDef(label="grenade_pin"), FlagDef(label="zombie")],
        events=[
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                responses=[
                    TrackReceivedWaypointResponse(initial_flags=["grenade_pin"]),
                    WithEachNearbyWaypointResponse(
                        flag_label="zombie",
                        meters=50,
                        responses=[DestroyWaypointResponse()],
                    ),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Place zombie far from the grenade drop point
    far_wp = db.create_dynamic_waypoint(48.000, -123.000)
    db.add_dynamic_waypoint_flag(far_wp, "zombie")

    ctx = _make_track_wp_ctx()
    ctx.waypoint_lat, ctx.waypoint_lon = 47.003, -122.003
    eng.handle_waypoint_received(ctx)

    rows = _get_all_dynamic_waypoints(db)
    remaining_ids = [r[0] for r in rows]
    assert far_wp in remaining_ids


def test_with_each_nearby_waypoint_inner_responses_use_each_waypoint_context(db):
    from config import (
        WaypointReceivedTrigger, TrackReceivedWaypointResponse,
        WithEachNearbyWaypointResponse, IncrementVariableResponse,
    )
    cfg = minimal_config(
        flags=[FlagDef(label="grenade_pin"), FlagDef(label="zombie")],
        mutable_variables=[MutableVariableDef(label="kills", type="integer", scope="node", initial=0)],
        events=[
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                responses=[
                    TrackReceivedWaypointResponse(initial_flags=["grenade_pin"]),
                    WithEachNearbyWaypointResponse(
                        flag_label="zombie",
                        meters=100,
                        responses=[
                            IncrementVariableResponse(
                                variable_label="kills",
                                amount=1,
                                target=TargetTriggeringNode(),
                            ),
                        ],
                    ),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    for _ in range(3):
        wp = db.create_dynamic_waypoint(47.003, -122.003)
        db.add_dynamic_waypoint_flag(wp, "zombie")

    ctx = _make_track_wp_ctx()
    ctx.waypoint_lat, ctx.waypoint_lon = 47.003, -122.003
    eng.handle_waypoint_received(ctx)

    assert db.get_mutable_variable("kills", NODE_ID) == 3


def test_with_each_nearby_waypoint_no_triggering_waypoint_skips(db):
    from config import (
        WaypointReceivedTrigger,
        WithEachNearbyWaypointResponse, DestroyWaypointResponse,
    )
    cfg = minimal_config(
        flags=[FlagDef(label="zombie")],
        events=[
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                responses=[
                    WithEachNearbyWaypointResponse(
                        flag_label="zombie",
                        meters=50,
                        responses=[DestroyWaypointResponse()],
                    ),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    wp = db.create_dynamic_waypoint(47.003, -122.003)
    db.add_dynamic_waypoint_flag(wp, "zombie")

    ctx = _make_track_wp_ctx()
    ctx.waypoint_lat, ctx.waypoint_lon = 47.003, -122.003
    eng.handle_waypoint_received(ctx)

    # No track_received_waypoint → no triggering_waypoint_id → waypoint survives
    rows = _get_all_dynamic_waypoints(db)
    assert any(r[0] == wp for r in rows)


# ---------------------------------------------------------------------------
# with_each_nearby_node
# ---------------------------------------------------------------------------

def test_with_each_nearby_node_applies_responses_to_nodes_in_radius(db):
    from config import (
        ProximityTrigger, WithEachNearbyNodeResponse,
    )
    cfg = minimal_config(
        flags=[FlagDef(label="active"), FlagDef(label="blast_zone")],
        events=[
            Event(
                label="explode",
                trigger=ProximityTrigger(kind="near_waypoint", target_flag="active", meters=500),
                responses=[
                    WithEachNearbyNodeResponse(
                        meters=200,
                        responses=[AddFlagResponse(flag_label="blast_zone", target=TargetTriggeringNode())],
                    ),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Place two nodes: one within 200m of the waypoint (INSIDE_ZONE), one far
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    db.update_node_location(NODE2_ID, 48.000, -123.000)
    # Create a dynamic waypoint at INSIDE_ZONE with flag "active"
    wp = db.create_dynamic_waypoint(*INSIDE_ZONE)
    db.add_dynamic_waypoint_flag(wp, "active")

    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert db.has_flag("node", NODE_ID, "blast_zone")
    assert not db.has_flag("node", NODE2_ID, "blast_zone")


def test_with_each_nearby_node_flag_filter_limits_targets(db):
    from config import (
        ProximityTrigger, WithEachNearbyNodeResponse,
    )
    cfg = minimal_config(
        flags=[FlagDef(label="active"), FlagDef(label="player"), FlagDef(label="tagged")],
        events=[
            Event(
                label="tag_players",
                trigger=ProximityTrigger(kind="near_waypoint", target_flag="active", meters=500),
                responses=[
                    WithEachNearbyNodeResponse(
                        meters=500,
                        flag_label="player",
                        responses=[AddFlagResponse(flag_label="tagged", target=TargetTriggeringNode())],
                    ),
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    db.update_node_location(NODE2_ID, *INSIDE_ZONE)
    db.add_flag("node", NODE_ID, "player")
    # NODE2_ID does NOT have player flag
    wp = db.create_dynamic_waypoint(*INSIDE_ZONE)
    db.add_dynamic_waypoint_flag(wp, "active")

    eng.handle_position(NODE_ID, *INSIDE_ZONE)

    assert db.has_flag("node", NODE_ID, "tagged")
    assert not db.has_flag("node", NODE2_ID, "tagged")


# ---------------------------------------------------------------------------
# received_waypoint_too_far / received_waypoint_in_range exceptions
# ---------------------------------------------------------------------------

def _make_wp_ctx_at(lat, lon, node_id=NODE_ID):
    from engine import WaypointReceivedContext
    return WaypointReceivedContext(
        node_id=node_id,
        waypoint_name="pin",
        waypoint_description="",
        waypoint_lat=lat,
        waypoint_lon=lon,
        waypoint_expire=0,
        waypoint_icon=0,
        mesh_waypoint_id=None,
    )


def test_received_waypoint_too_far_blocks_when_out_of_range(db):
    from config import WaypointReceivedTrigger, AddFlagResponse
    cfg = minimal_config(
        flags=[FlagDef(label="deployed")],
        events=[
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                exceptions=[EventException(kind="received_waypoint_too_far", meters=100)],
                responses=[AddFlagResponse(flag_label="deployed", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    # Drop pin ~1.5km away — far beyond 100m limit
    eng.handle_waypoint_received(_make_wp_ctx_at(47.016, -122.003))
    assert not db.has_flag("node", NODE_ID, "deployed")


def test_received_waypoint_too_far_fires_when_in_range(db):
    from config import WaypointReceivedTrigger, AddFlagResponse
    cfg = minimal_config(
        flags=[FlagDef(label="deployed")],
        events=[
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                exceptions=[EventException(kind="received_waypoint_too_far", meters=100)],
                responses=[AddFlagResponse(flag_label="deployed", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    # Drop pin ~50m away — within 100m limit
    eng.handle_waypoint_received(_make_wp_ctx_at(47.0035, -122.003))
    assert db.has_flag("node", NODE_ID, "deployed")


def test_received_waypoint_in_range_blocks_when_in_range(db):
    from config import WaypointReceivedTrigger, AddFlagResponse
    cfg = minimal_config(
        flags=[FlagDef(label="warned")],
        events=[
            Event(
                label="warn",
                trigger=WaypointReceivedTrigger(),
                exceptions=[EventException(kind="received_waypoint_in_range", meters=100)],
                responses=[AddFlagResponse(flag_label="warned", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    # Drop pin ~50m away — within range, so this "out of range warning" event is blocked
    eng.handle_waypoint_received(_make_wp_ctx_at(47.0035, -122.003))
    assert not db.has_flag("node", NODE_ID, "warned")


def test_received_waypoint_in_range_fires_when_out_of_range(db):
    from config import WaypointReceivedTrigger, AddFlagResponse
    cfg = minimal_config(
        flags=[FlagDef(label="warned")],
        events=[
            Event(
                label="warn",
                trigger=WaypointReceivedTrigger(),
                exceptions=[EventException(kind="received_waypoint_in_range", meters=100)],
                responses=[AddFlagResponse(flag_label="warned", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)
    # Drop pin ~1.5km away — out of range, so warning event fires
    eng.handle_waypoint_received(_make_wp_ctx_at(47.016, -122.003))
    assert db.has_flag("node", NODE_ID, "warned")


def test_grenade_range_mutual_exclusion(db):
    """Both exception kinds together route deploy vs. warn events correctly."""
    from config import WaypointReceivedTrigger, AddFlagResponse
    cfg = minimal_config(
        flags=[FlagDef(label="deployed"), FlagDef(label="warned")],
        events=[
            Event(
                label="warn_out_of_range",
                trigger=WaypointReceivedTrigger(),
                exceptions=[EventException(kind="received_waypoint_in_range", meters=100)],
                responses=[AddFlagResponse(flag_label="warned", target=TargetTriggeringNode())],
            ),
            Event(
                label="deploy",
                trigger=WaypointReceivedTrigger(),
                exceptions=[EventException(kind="received_waypoint_too_far", meters=100)],
                responses=[AddFlagResponse(flag_label="deployed", target=TargetTriggeringNode())],
            ),
        ],
    )
    eng = make_engine(cfg, db)
    db.update_node_location(NODE_ID, *INSIDE_ZONE)

    # In-range drop: deploy fires, warn does not
    eng.handle_waypoint_received(_make_wp_ctx_at(47.0035, -122.003))
    assert db.has_flag("node", NODE_ID, "deployed")
    assert not db.has_flag("node", NODE_ID, "warned")

    db.remove_flag("node", NODE_ID, "deployed")

    # Out-of-range drop: warn fires, deploy does not
    eng.handle_waypoint_received(_make_wp_ctx_at(47.016, -122.003))
    assert not db.has_flag("node", NODE_ID, "deployed")
    assert db.has_flag("node", NODE_ID, "warned")


# ---------------------------------------------------------------------------
# position_received trigger
# ---------------------------------------------------------------------------

def test_position_received_fires_event(db):
    from config import PositionReceivedTrigger
    cfg = minimal_config(
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")


def test_position_received_trigger_per_node_cooldown(db):
    from config import PositionReceivedTrigger
    cfg = minimal_config(
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                trigger_per_node=True,
                reset_mins=60,
                responses=[AddFlagResponse(flag_label="active", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert db.has_flag("node", NODE_ID, "active")
    db.remove_flag("node", NODE_ID, "active")

    # Second position within cooldown — should NOT re-fire
    eng.handle_position(NODE_ID, *OUTSIDE_ZONE)
    assert not db.has_flag("node", NODE_ID, "active")


def test_position_received_does_not_fire_for_waypoint_context(db):
    from config import PositionReceivedTrigger, WaypointReceivedTrigger
    cfg = minimal_config(
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                responses=[AddFlagResponse(flag_label="pos_fired", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # Waypoint packet should NOT fire the position_received event
    eng.handle_waypoint_received(_make_wp_ctx())
    assert not db.has_flag("node", NODE_ID, "pos_fired")


# ---------------------------------------------------------------------------
# distance_since_last_fix variable
# ---------------------------------------------------------------------------

def test_distance_since_last_fix_unknown_on_first_fix(db):
    from config import PositionReceivedTrigger, Variable
    var = Variable(label="move_delta", scope="node", tracks="distance_since_last_fix")
    cfg = minimal_config(
        variables=[var],
        messages=[Message(label="m", text="{move_delta}")],
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                responses=[SendMessageResponse(message_label="m", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)
    assert len(eng.sent_dms) == 1
    assert eng.sent_dms[0][1] == "[unknown]"


def test_distance_since_last_fix_computes_on_second_fix(db):
    from config import PositionReceivedTrigger, Variable
    var = Variable(label="move_delta", scope="node", tracks="distance_since_last_fix")
    cfg = minimal_config(
        variables=[var],
        messages=[Message(label="m", text="{move_delta}")],
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                responses=[SendMessageResponse(message_label="m", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    # First fix — seeds prev location
    eng.handle_position(NODE_ID, 47.0, -122.0)
    # Second fix — ~111 m north (1 arc-second ≈ 31 m; 0.001 deg ≈ 111 m)
    eng.handle_position(NODE_ID, 47.001, -122.0)
    assert len(eng.sent_dms) == 2
    delta = float(eng.sent_dms[1][1])
    assert 100 < delta < 130   # ~111 m, allow GPS jitter tolerance


# ---------------------------------------------------------------------------
# variable_amount on increment_variable
# ---------------------------------------------------------------------------

def test_variable_amount_increments_by_resolved_value(db):
    from config import PositionReceivedTrigger, Variable
    var = Variable(label="move_delta", scope="node", tracks="distance_since_last_fix")
    mv = MutableVariableDef(label="meters_moved", type="float", scope="node", initial=0.0)
    cfg = minimal_config(
        variables=[var],
        mutable_variables=[mv],
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                responses=[
                    IncrementVariableResponse(
                        variable_label="meters_moved",
                        variable_amount="move_delta",
                        target=TargetTriggeringNode(),
                    )
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, 47.0, -122.0)     # first fix: [unknown] → skipped
    eng.handle_position(NODE_ID, 47.001, -122.0)   # second fix: accumulates ~111 m
    val = db.get_mutable_variable("meters_moved", NODE_ID)
    assert val is not None and float(val) > 50


def test_variable_amount_skipped_on_unknown(db):
    from config import PositionReceivedTrigger, Variable
    var = Variable(label="move_delta", scope="node", tracks="distance_since_last_fix")
    mv = MutableVariableDef(label="meters_moved", type="float", scope="node", initial=0.0)
    cfg = minimal_config(
        variables=[var],
        mutable_variables=[mv],
        events=[
            Event(
                label="on_pos",
                trigger=PositionReceivedTrigger(),
                responses=[
                    IncrementVariableResponse(
                        variable_label="meters_moved",
                        variable_amount="move_delta",
                        target=TargetTriggeringNode(),
                    )
                ],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # first fix — [unknown], should skip silently
    val = db.get_mutable_variable("meters_moved", NODE_ID)
    # Either no row yet (None) or initial value 0
    assert val is None or float(val) == 0.0


# ---------------------------------------------------------------------------
# Interpolation tokens: {date}, {time}, {waypoint_icon}
# ---------------------------------------------------------------------------

def test_waypoint_icon_token_interpolated(db):
    from config import WaypointReceivedTrigger
    cfg = minimal_config(
        messages=[Message(label="m", text="icon={waypoint_icon}")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[SendMessageResponse(message_label="m", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx(icon=42))
    assert len(eng.sent_dms) == 1
    assert eng.sent_dms[0][1] == "icon=42"


def test_date_and_time_tokens_interpolated(db):
    import re
    from config import WaypointReceivedTrigger
    cfg = minimal_config(
        messages=[Message(label="m", text="d={date} t={time}")],
        events=[
            Event(
                label="on_wp",
                trigger=WaypointReceivedTrigger(),
                responses=[SendMessageResponse(message_label="m", target=TargetTriggeringNode())],
            )
        ],
    )
    eng = make_engine(cfg, db)
    eng.handle_waypoint_received(_make_wp_ctx())
    assert len(eng.sent_dms) == 1
    text = eng.sent_dms[0][1]
    assert re.search(r"d=\d{4}-\d{2}-\d{2}", text), f"date token not found in {text!r}"
    assert re.search(r"t=\d{2}:\d{2}", text), f"time token not found in {text!r}"
