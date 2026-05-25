"""Integration tests for engine.py — trigger evaluation and response execution."""
from __future__ import annotations

import pytest

from config import (
    GameConfig, Event, Variable, Message, FlagDef,
    ProximityTrigger, CommandTrigger, VariableThresholdTrigger,
    SendMessageResponse, SendAlertResponse, AddFlagResponse, RemoveFlagResponse,
    RequestLocationResponse, RequestTelemetryResponse,
    SetVariableResponse, IncrementVariableResponse,
    RandomOptionsResponse, RandomOption, WithNodeResponse,
    TargetTriggeringNode, TargetChannel, TargetFlag, TargetAllWithFlag, TargetGroup,
    EventException,
)
from tests.conftest import minimal_config, make_engine, INSIDE_ZONE, OUTSIDE_ZONE, ZONE_POINTS, NODE_ID, NODE2_ID


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

def _make_wp_ctx(name="cache", from_node=NODE_ID):
    from engine import WaypointReceivedContext
    return WaypointReceivedContext(
        node_id=from_node,
        waypoint_name=name,
        waypoint_description="a desc",
        waypoint_lat=47.003,
        waypoint_lon=-122.003,
        waypoint_expire=0,
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
