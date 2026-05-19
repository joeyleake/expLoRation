"""Tests for state.py — GameState CRUD and flag expiry."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import pytest

from state import GameState


# ---------------------------------------------------------------------------
# Node locations
# ---------------------------------------------------------------------------

def test_get_node_location_missing(db):
    assert db.get_node_location("!unknown") is None


def test_update_and_get_node_location(db):
    db.update_node_location("!aabb", 47.0, -122.0)
    assert db.get_node_location("!aabb") == (47.0, -122.0)


def test_update_node_location_overwrites(db):
    db.update_node_location("!aabb", 47.0, -122.0)
    db.update_node_location("!aabb", 48.0, -121.0)
    assert db.get_node_location("!aabb") == (48.0, -121.0)


def test_get_all_located_nodes_empty(db):
    assert db.get_all_located_nodes() == {}


def test_get_all_located_nodes_populated(db):
    db.update_node_location("!aa", 47.0, -122.0)
    db.update_node_location("!bb", 48.0, -121.0)
    result = db.get_all_located_nodes()
    assert result == {"!aa": (47.0, -122.0), "!bb": (48.0, -121.0)}


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def test_has_flag_missing(db):
    assert not db.has_flag("node", "!aa", "active")


def test_add_and_has_flag(db):
    db.add_flag("node", "!aa", "active")
    assert db.has_flag("node", "!aa", "active")


def test_remove_flag(db):
    db.add_flag("node", "!aa", "active")
    db.remove_flag("node", "!aa", "active")
    assert not db.has_flag("node", "!aa", "active")


def test_get_flags(db):
    db.add_flag("node", "!aa", "active")
    db.add_flag("node", "!aa", "scored")
    flags = db.get_flags("node", "!aa")
    assert set(flags) == {"active", "scored"}


def test_get_flags_empty(db):
    assert db.get_flags("node", "!missing") == []


def test_zone_flag(db):
    db.add_flag("zone", "zone_a", "locked")
    assert db.has_flag("zone", "zone_a", "locked")
    assert not db.has_flag("zone", "zone_b", "locked")


def test_get_nodes_with_flag(db):
    db.add_flag("node", "!aa", "active")
    db.add_flag("node", "!bb", "active")
    result = db.get_nodes_with_flag("active")
    assert set(result) == {"!aa", "!bb"}


def test_flag_expiry_in_has_flag(db):
    # Add a flag that expired 1 second ago
    from state import _now_iso
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db._conn.execute(
        "INSERT INTO node_flags(node_id, flag_label, set_at, expires_at) VALUES(?,?,?,?)",
        ("!aa", "active", _now_iso(), past),
    )
    db._conn.commit()
    assert not db.has_flag("node", "!aa", "active")


def test_expire_flags_returns_expired(db):
    from state import _now_iso
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db._conn.execute(
        "INSERT INTO node_flags(node_id, flag_label, set_at, expires_at) VALUES(?,?,?,?)",
        ("!aa", "active", _now_iso(), past),
    )
    db._conn.commit()
    expired = db.expire_flags()
    assert ("node", "!aa", "active") in expired
    assert not db.has_flag("node", "!aa", "active")


def test_expire_flags_ignores_non_expired(db):
    db.add_flag("node", "!aa", "active", expiry_mins=60)
    expired = db.expire_flags()
    assert len(expired) == 0
    assert db.has_flag("node", "!aa", "active")


# ---------------------------------------------------------------------------
# Mutable variables
# ---------------------------------------------------------------------------

def test_get_mutable_variable_unset(db):
    assert db.get_mutable_variable("score") is None


def test_set_and_get_integer(db):
    db.set_mutable_variable("score", 42)
    assert db.get_mutable_variable("score") == 42


def test_set_and_get_float(db):
    db.set_mutable_variable("ratio", 3.14)
    assert abs(db.get_mutable_variable("ratio") - 3.14) < 1e-9


def test_set_and_get_string(db):
    db.set_mutable_variable("name", "hello")
    assert db.get_mutable_variable("name") == "hello"


def test_set_mutable_variable_overwrites(db):
    db.set_mutable_variable("score", 1)
    db.set_mutable_variable("score", 99)
    assert db.get_mutable_variable("score") == 99


def test_mutable_variable_node_scope(db):
    db.set_mutable_variable("kills", 3, node_id="!aa")
    db.set_mutable_variable("kills", 7, node_id="!bb")
    assert db.get_mutable_variable("kills", "!aa") == 3
    assert db.get_mutable_variable("kills", "!bb") == 7
    assert db.get_mutable_variable("kills") is None  # global slot unset


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def test_is_in_group_false(db):
    assert not db.is_in_group("players", "!aa")


def test_add_to_group(db):
    db.add_to_group("players", "!aa")
    assert db.is_in_group("players", "!aa")


def test_remove_from_group(db):
    db.add_to_group("players", "!aa")
    db.remove_from_group("players", "!aa")
    assert not db.is_in_group("players", "!aa")


def test_get_group_members(db):
    db.add_to_group("players", "!aa")
    db.add_to_group("players", "!bb")
    assert set(db.get_group_members("players")) == {"!aa", "!bb"}


def test_get_group_members_empty(db):
    assert db.get_group_members("nobody") == []


# ---------------------------------------------------------------------------
# Event state
# ---------------------------------------------------------------------------

def test_get_event_state_default(db):
    count, last = db.get_event_state("my_event")
    assert count == 0
    assert last is None


def test_increment_event_triggers(db):
    db.increment_event_triggers("my_event")
    db.increment_event_triggers("my_event")
    count, last = db.get_event_state("my_event")
    assert count == 2
    assert last is not None


def test_set_event_triggers(db):
    db.increment_event_triggers("my_event")
    db.set_event_triggers("my_event", 5)
    count, _ = db.get_event_state("my_event")
    assert count == 5


def test_is_event_disabled_default(db):
    assert not db.is_event_disabled("my_event")


def test_set_event_disabled(db):
    db.set_event_disabled("my_event", True)
    assert db.is_event_disabled("my_event")


def test_set_event_enabled(db):
    db.set_event_disabled("my_event", True)
    db.set_event_disabled("my_event", False)
    assert not db.is_event_disabled("my_event")


def test_node_event_state_default(db):
    count, last = db.get_node_event_state("ev", "!aa")
    assert count == 0
    assert last is None


def test_increment_node_event_triggers(db):
    db.increment_node_event_triggers("ev", "!aa")
    db.increment_node_event_triggers("ev", "!aa")
    count, _ = db.get_node_event_state("ev", "!aa")
    assert count == 2
    # Different node — independent counter
    count2, _ = db.get_node_event_state("ev", "!bb")
    assert count2 == 0


# ---------------------------------------------------------------------------
# Dynamic waypoints
# ---------------------------------------------------------------------------

def test_create_and_get_dynamic_waypoint(db):
    wp_id = db.create_dynamic_waypoint(47.0, -122.0)
    assert isinstance(wp_id, int)
    assert db.get_dynamic_waypoint_location(wp_id) == (47.0, -122.0)


def test_get_dynamic_waypoint_location_missing(db):
    assert db.get_dynamic_waypoint_location(9999) is None


def test_add_and_has_dynamic_waypoint_flag(db):
    wp_id = db.create_dynamic_waypoint(47.0, -122.0)
    db.add_dynamic_waypoint_flag(wp_id, "marked")
    assert db.has_dynamic_waypoint_flag(wp_id, "marked")


def test_remove_dynamic_waypoint_flag(db):
    wp_id = db.create_dynamic_waypoint(47.0, -122.0)
    db.add_dynamic_waypoint_flag(wp_id, "marked")
    db.remove_dynamic_waypoint_flag(wp_id, "marked")
    assert not db.has_dynamic_waypoint_flag(wp_id, "marked")


def test_get_dynamic_waypoints_with_flag(db):
    wp1 = db.create_dynamic_waypoint(47.0, -122.0)
    wp2 = db.create_dynamic_waypoint(48.0, -121.0)
    db.add_dynamic_waypoint_flag(wp1, "active")
    result = db.get_dynamic_waypoints_with_flag("active")
    ids = [r[0] for r in result]
    assert wp1 in ids
    assert wp2 not in ids


def test_destroy_dynamic_waypoint(db):
    wp_id = db.create_dynamic_waypoint(47.0, -122.0)
    db.add_dynamic_waypoint_flag(wp_id, "active")
    db.destroy_dynamic_waypoint(wp_id)
    assert db.get_dynamic_waypoint_location(wp_id) is None
    assert not db.has_dynamic_waypoint_flag(wp_id, "active")


def test_expire_dynamic_waypoints(db):
    from state import _now_iso
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db._conn.execute(
        "INSERT INTO dynamic_waypoints(lat, lon, created_at, expires_at) VALUES(?,?,?,?)",
        (47.0, -122.0, _now_iso(), past),
    )
    db._conn.commit()
    expired = db.expire_dynamic_waypoints()
    assert len(expired) == 1
    wp_id, flags = expired[0]
    assert isinstance(flags, frozenset)


def test_dynamic_waypoint_count(db):
    db.create_dynamic_waypoint(47.0, -122.0)
    db.create_dynamic_waypoint(48.0, -121.0)
    assert db.get_dynamic_waypoint_count() == 2
