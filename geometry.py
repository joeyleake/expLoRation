"""Geographic utility functions: haversine distance and point-in-triangle."""
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Zone, Waypoint


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def point_in_triangle(p, a, b, c) -> bool:
    """Return True if point p=(lat,lon) is inside triangle (a,b,c)."""
    d1 = _cross(p, a, b)
    d2 = _cross(p, b, c)
    d3 = _cross(p, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def zone_centroid(zone: "Zone") -> tuple[float, float]:
    lats = [p[0] for p in zone.points]
    lons = [p[1] for p in zone.points]
    return sum(lats) / 3, sum(lons) / 3


def _point_to_segment_dist_m(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance in meters from point p to line segment a-b on flat lat/lon plane."""
    ax, ay = a[1], a[0]
    bx, by = b[1], b[0]
    px, py = p[1], p[0]
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return haversine(*p, *a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    closest = (ay + t * dy, ax + t * dx)
    return haversine(*p, *closest)


def distance_to_triangle_border(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    """Minimum distance in meters from p to the nearest edge of triangle abc."""
    return min(
        _point_to_segment_dist_m(p, a, b),
        _point_to_segment_dist_m(p, b, c),
        _point_to_segment_dist_m(p, c, a),
    )


def nodes_in_zone(zone: "Zone", located_nodes: dict[str, tuple[float, float]]) -> list[str]:
    a, b, c = zone.points
    return [
        node_id for node_id, (lat, lon) in located_nodes.items()
        if point_in_triangle((lat, lon), a, b, c)
    ]


def nodes_near_waypoint(
    waypoint: "Waypoint", radius_m: float, located_nodes: dict[str, tuple[float, float]]
) -> list[str]:
    return [
        node_id for node_id, (lat, lon) in located_nodes.items()
        if haversine(lat, lon, waypoint.lat, waypoint.lon) <= radius_m
    ]


def nodes_near_zone(
    zone: "Zone", radius_m: float, located_nodes: dict[str, tuple[float, float]]
) -> list[str]:
    clat, clon = zone_centroid(zone)
    return [
        node_id for node_id, (lat, lon) in located_nodes.items()
        if haversine(lat, lon, clat, clon) <= radius_m
    ]


def nodes_near_node(
    target_node_id: str, radius_m: float, located_nodes: dict[str, tuple[float, float]]
) -> list[str]:
    target = located_nodes.get(target_node_id)
    if target is None:
        return []
    tlat, tlon = target
    return [
        node_id for node_id, (lat, lon) in located_nodes.items()
        if node_id != target_node_id and haversine(lat, lon, tlat, tlon) <= radius_m
    ]
