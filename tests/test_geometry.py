"""Tests for geometry.py."""
import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import geometry as geo
from config import Zone, Waypoint


# ---------------------------------------------------------------------------
# haversine
# ---------------------------------------------------------------------------

def test_haversine_same_point():
    assert geo.haversine(47.0, -122.0, 47.0, -122.0) == 0.0


def test_haversine_known_distance():
    # 1 degree of latitude ≈ 111,195 m at any longitude
    d = geo.haversine(0.0, 0.0, 1.0, 0.0)
    assert abs(d - 111_195) < 100


def test_haversine_east_west():
    # At equator, 1 degree longitude ≈ 111,195 m
    d = geo.haversine(0.0, 0.0, 0.0, 1.0)
    assert abs(d - 111_195) < 100


def test_haversine_symmetry():
    a, b = geo.haversine(47.0, -122.0, 48.0, -121.0), geo.haversine(48.0, -121.0, 47.0, -122.0)
    assert abs(a - b) < 1e-6


def test_haversine_short_distance():
    # ~111 m for 0.001 degree latitude
    d = geo.haversine(47.0, -122.0, 47.001, -122.0)
    assert 100 < d < 130


# ---------------------------------------------------------------------------
# point_in_triangle
# ---------------------------------------------------------------------------

TRI = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]


def test_point_in_triangle_inside():
    assert geo.point_in_triangle((0.2, 0.2), *TRI)


def test_point_in_triangle_outside():
    assert not geo.point_in_triangle((1.0, 1.0), *TRI)


def test_point_in_triangle_on_vertex():
    # Corner vertex counts as inside
    assert geo.point_in_triangle((0.0, 0.0), *TRI)


def test_point_in_triangle_far_outside():
    assert not geo.point_in_triangle((5.0, 5.0), *TRI)


def test_point_in_triangle_centroid():
    centroid = (1 / 3, 1 / 3)
    assert geo.point_in_triangle(centroid, *TRI)


# ---------------------------------------------------------------------------
# zone_centroid
# ---------------------------------------------------------------------------

def test_zone_centroid():
    zone = Zone(label="z", points=[(0.0, 0.0), (3.0, 0.0), (0.0, 3.0)])
    lat, lon = geo.zone_centroid(zone)
    assert abs(lat - 1.0) < 1e-9
    assert abs(lon - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# nodes_in_zone
# ---------------------------------------------------------------------------

def test_nodes_in_zone_empty():
    zone = Zone(label="z", points=list(TRI))
    assert geo.nodes_in_zone(zone, {}) == []


def test_nodes_in_zone_filters():
    zone = Zone(label="z", points=list(TRI))
    located = {
        "!inside": (0.2, 0.2),
        "!outside": (1.0, 1.0),
    }
    result = geo.nodes_in_zone(zone, located)
    assert "!inside" in result
    assert "!outside" not in result


# ---------------------------------------------------------------------------
# nodes_near_waypoint
# ---------------------------------------------------------------------------

def test_nodes_near_waypoint_in_range():
    wp = Waypoint(label="w", lat=47.0, lon=-122.0)
    located = {"!close": (47.001, -122.0), "!far": (48.0, -122.0)}
    result = geo.nodes_near_waypoint(wp, 500, located)
    assert "!close" in result
    assert "!far" not in result


def test_nodes_near_waypoint_empty():
    wp = Waypoint(label="w", lat=47.0, lon=-122.0)
    assert geo.nodes_near_waypoint(wp, 100, {}) == []


# ---------------------------------------------------------------------------
# nodes_near_node
# ---------------------------------------------------------------------------

def test_nodes_near_node_excludes_self():
    located = {"!a": (47.0, -122.0), "!b": (47.001, -122.0)}
    result = geo.nodes_near_node("!a", 500, located)
    assert "!a" not in result
    assert "!b" in result


def test_nodes_near_node_unknown_target():
    located = {"!b": (47.0, -122.0)}
    assert geo.nodes_near_node("!missing", 1000, located) == []
