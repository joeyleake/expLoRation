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
# variable_threshold fires during handle_message for node-scoped computed vars
# ---------------------------------------------------------------------------

def test_variable_threshold_fires_on_dm_for_computed_node_var(db):
    """A variable_threshold on a node-scoped computed variable evaluates at DM
    receipt time, enabling patterns like the stale-location refresh."""
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
    eng.handle_position(NODE_ID, *INSIDE_ZONE)  # give node a known location + timestamp

    # threshold (gte 0) will always be true once a position is known;
    # verify it fires when a DM arrives, not just on position/periodic
    eng.handle_message(NODE_ID, "!ping", is_dm=True, channel_idx=0)

    assert db.has_flag("node", NODE_ID, "active")


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
