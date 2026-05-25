#!/usr/bin/env python3
"""expLoRation — Meshtastic geocaching/scavenger hunt bot."""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
import urllib.parse
from datetime import datetime

import meshtastic.serial_interface
import meshtastic.tcp_interface
from pubsub import pub

from config import load_config, ConfigError, GameConfig
from state import GameState
from engine import Engine
import geometry as geo

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Coordinate extraction
# ---------------------------------------------------------------------------

def _coords(sub: dict) -> tuple[float, float] | None:
    """Extract (lat, lon) from a decoded sub-message.

    Handles both encodings the library produces:
    - float  'latitude'  / 'longitude'  (POSITION_APP after library fixup)
    - int    'latitudeI' / 'longitudeI' × 1e-7 (MAP_REPORT_APP, ATAK_PLUGIN)
    Rejects (0, 0) — the protobuf default / null-island sentinel.
    """
    lat = sub.get("latitude")
    lon = sub.get("longitude")
    if lat is not None and lon is not None:
        lat, lon = float(lat), float(lon)
        if lat != 0.0 or lon != 0.0:
            return lat, lon
    lat_i = sub.get("latitudeI")
    lon_i = sub.get("longitudeI")
    if lat_i is not None and lon_i is not None and (lat_i != 0 or lon_i != 0):
        return lat_i * 1e-7, lon_i * 1e-7
    return None


# ---------------------------------------------------------------------------
# Console display helpers
# ---------------------------------------------------------------------------

def _zone_map_url(config: GameConfig) -> str:
    """Build a geojson.io URL with all zones and waypoints overlaid."""
    features = []
    for zone in config.zones:
        coords = [[pt[1], pt[0]] for pt in zone.points]  # (lat,lon) → [lon,lat]
        coords.append(coords[0])  # close polygon
        features.append({
            "type": "Feature",
            "properties": {"name": zone.label},
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        })
    for wp in config.waypoints:
        features.append({
            "type": "Feature",
            "properties": {"name": wp.label},
            "geometry": {"type": "Point", "coordinates": [wp.lon, wp.lat]},
        })
    geojson = json.dumps({"type": "FeatureCollection", "features": features}, separators=(',', ':'))
    return f"https://geojson.io/#data=data:application/json,{urllib.parse.quote(geojson)}"


def _node_display(node_id: str, interface) -> str:
    """Return 'Long Name (!abcd1234)' if the node is known, else just the ID."""
    node_info = (interface.nodes or {}).get(node_id, {})
    user = node_info.get("user", {})
    short = user.get("shortName", "").strip()
    long_ = user.get("longName", "").strip()
    name = long_ or short
    return f"{name} ({node_id})" if name else node_id


def _print_location(node_id: str, lat: float, lon: float, portnum: str,
                    engine: Engine, interface) -> None:
    name = _node_display(node_id, interface)
    if engine.config.zones:
        closest_zone, closest_dist = min(
            ((z, geo.haversine(lat, lon, *geo.zone_centroid(z))) for z in engine.config.zones),
            key=lambda x: x[1],
        )
        if geo.point_in_triangle((lat, lon), *closest_zone.points):
            zone_str = f"inside {closest_zone.label}"
        else:
            zone_str = f"{closest_dist:.0f} m from {closest_zone.label}"
    else:
        zone_str = "no zones defined"
    src = portnum.replace("_APP", "").lower()
    print(f"[loc/{src}] {name}: {lat:.5f}, {lon:.5f}  ({zone_str})", flush=True)


def _print_status(config: GameConfig, state: GameState) -> None:
    located = state.get_all_located_nodes()
    lines: list[str] = []
    ts = datetime.now().strftime("%H:%M:%S")
    lines.append(f"── Status {ts} ({len(located)} located node{'s' if len(located) != 1 else ''}) ──────────────────────────")

    # Zones: node count + list + flags
    if config.zones:
        lines.append("  Zones:")
        for zone in config.zones:
            nodes = geo.nodes_in_zone(zone, located)
            flags = state.get_flags("zone", zone.label)
            node_str = (f"{len(nodes)} node{'s' if len(nodes) != 1 else ''} — {', '.join(nodes)}"
                        if nodes else "empty")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            lines.append(f"    {zone.label}: {node_str}{flag_str}")

    # Waypoints: closest node, distance, and flags
    if config.waypoints:
        lines.append("  Waypoints:")
        for wp in config.waypoints:
            flags = state.get_flags("waypoint", wp.label)
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            if not located:
                lines.append(f"    {wp.label}: no located nodes{flag_str}")
                continue
            closest_id, closest_dist = min(
                ((nid, geo.haversine(lat, lon, wp.lat, wp.lon))
                 for nid, (lat, lon) in located.items()),
                key=lambda x: x[1],
            )
            lines.append(f"    {wp.label}: closest {closest_id} at {closest_dist:.0f} m{flag_str}")

    # Events: disabled / exhausted
    disabled = [e.label for e in config.events if state.is_event_disabled(e.label)]
    triggered_out = [
        e.label for e in config.events
        if e.max_triggers is not None and state.get_event_state(e.label)[0] >= e.max_triggers
    ]
    if disabled:
        lines.append(f"  Disabled events: {', '.join(disabled)}")
    if triggered_out:
        lines.append(f"  Exhausted events: {', '.join(triggered_out)}")

    lines.append("─" * 60)
    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# Packet handlers
# ---------------------------------------------------------------------------

def on_receive(packet: dict, interface, engine: Engine, verbose: bool = False) -> None:
    decoded = packet.get("decoded", {})
    portnum = decoded.get("portnum")
    log.debug("[pkt] from=!%08x portnum=%s", packet.get("from", 0), portnum)
    from_num = packet.get("from")
    if from_num is None:
        return
    node_id = f"!{from_num:08x}"

    # --- Position-bearing packets ---
    coords: tuple[float, float] | None = None

    if portnum == "POSITION_APP":
        # Library applies fixup: latitudeI/longitudeI → latitude/longitude (float)
        coords = _coords(decoded.get("position", {}))

    elif portnum == "MAP_REPORT_APP":
        # Unencrypted MQTT position report; library does NOT fixup, remains as latitudeI/longitudeI
        coords = _coords(decoded.get("mapreport", {}))

    elif portnum == "ATAK_PLUGIN":
        # TAKPacket PLI (Position Location Information); absent when packet is a chat
        coords = _coords(decoded.get("pli", {}))

    if coords is not None:
        lat, lon = coords
        log.debug("Position from %s via %s: %.5f, %.5f", node_id, portnum, lat, lon)
        engine.handle_position(node_id, lat, lon)
        if verbose:
            _print_location(node_id, lat, lon, portnum, engine, interface)

    # --- Text messages ---
    if portnum == "TEXT_MESSAGE_APP":
        text = decoded.get("text", "")
        is_dm = packet.get("to") == engine.my_node_num
        channel_idx = packet.get("channel", 0)

        tag = "DM" if is_dm else f"ch{channel_idx}"
        print(f"[{tag}] {_node_display(node_id, interface)}: {text}", flush=True)

        if is_dm or channel_idx in engine.channel_index_map.values():
            log.debug("Message from %s (dm=%s ch=%d): %r", node_id, is_dm, channel_idx, text[:60])
            engine.handle_message(node_id, text, is_dm, channel_idx)

    # --- Waypoints ---
    elif portnum == "WAYPOINT_APP":
        waypoint = decoded.get("waypoint", {})
        # expire=0 with no name = deletion packet from another node — ignore
        if not waypoint.get("name") and waypoint.get("expire", 0) == 0:
            return
        from engine import WaypointReceivedContext
        lat = waypoint.get("latitudeI", 0) * 1e-7
        lon = waypoint.get("longitudeI", 0) * 1e-7
        ctx = WaypointReceivedContext(
            node_id=node_id,
            waypoint_name=waypoint.get("name", ""),
            waypoint_description=waypoint.get("description", ""),
            waypoint_lat=lat,
            waypoint_lon=lon,
            waypoint_expire=waypoint.get("expire", 0),
            mesh_waypoint_id=waypoint.get("id"),
        )
        log.debug("Waypoint received from %s: %r", node_id, waypoint.get("name", ""))
        engine.handle_waypoint_received(ctx)


_MODEM_PRESET_NAMES = {
    0: "LONG_FAST", 1: "LONG_SLOW", 2: "VERY_LONG_SLOW", 3: "MEDIUM_SLOW",
    4: "MEDIUM_FAST", 5: "SHORT_SLOW", 6: "SHORT_FAST", 7: "LONG_MODERATE",
    8: "SHORT_TURBO",
}


def _norm_ch_name(s: str) -> str:
    """Normalize channel names for comparison: strip underscores/spaces, lowercase.

    Allows 'MediumFast', 'MEDIUM_FAST', 'Medium Fast' all to match each other.
    """
    return s.replace("_", "").replace(" ", "").lower()


def on_connection(interface, engine: Engine, config) -> None:
    log.info("Connected to Meshtastic device")
    engine.my_node_num = interface.myInfo.my_node_num

    # Slot 0 (primary channel) has settings.name="" — derive its name from modem preset
    try:
        preset_val = interface.localNode.localConfig.lora.modem_preset
        primary_name = _MODEM_PRESET_NAMES.get(preset_val, "")
    except Exception:
        primary_name = ""

    # Map config channel names → device channel indices
    device_channels = interface.localNode.channels
    for ch_config in config.channels:
        if not ch_config.monitor and not ch_config.participate:
            continue
        for idx, dev_ch in enumerate(device_channels):
            raw_name = dev_ch.settings.name or (primary_name if idx == 0 else "")
            if _norm_ch_name(raw_name) == _norm_ch_name(ch_config.name):
                engine.channel_index_map[ch_config.label] = idx
                log.info("Channel %r mapped to device index %d", ch_config.label, idx)
                break
        else:
            log.warning(
                "Config channel %r (name=%r) not found on device — skipping",
                ch_config.label, ch_config.name,
            )

    # Seed locations from device node DB.
    # Positions in interface.nodes use latitudeI/longitudeI (integer × 1e-7)
    # for nodeDB entries; _coords() handles both that and the float format.
    located = {}
    for hex_id, node_info in (interface.nodes or {}).items():
        coords = _coords(node_info.get("position", {}))
        if coords is not None:
            located[hex_id] = coords

    for node_id, (lat, lon) in located.items():
        engine.seed_node_location(node_id, lat, lon)
    if located:
        log.info("Seeded %d node locations from device", len(located))


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _interface_alive(interface) -> bool:
    """Return False if the interface reader thread has exited (connection dropped)."""
    reader = getattr(interface, "_reader", None)
    return reader is None or reader.is_alive()


def _close_quietly(interface) -> None:
    """Close interface, suppressing errors from an already-dead connection."""
    try:
        interface.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Background loops
# ---------------------------------------------------------------------------

def _periodic_loop(engine: Engine, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            engine.handle_periodic()
        except Exception:
            log.exception("Error in periodic check")


def _status_loop(config: GameConfig, state: GameState, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            _print_status(config, state)
        except Exception:
            log.exception("Error in status display")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="expLoRation geocaching bot")
    conn = p.add_mutually_exclusive_group()
    conn.add_argument("--port", default=None, metavar="PORT",
                      help="Serial port for Meshtastic device (e.g. /dev/ttyUSB0)")
    conn.add_argument("--host", default=None, metavar="HOST",
                      help="Hostname or IP address for TCP connection to Meshtastic device")
    p.add_argument("--tcp-port", type=int, default=4403, metavar="PORT",
                   help="TCP port when using --host (default: 4403)")
    p.add_argument("--config", default="game.yaml", help="Path to game config YAML")
    p.add_argument("--db", default="exploration.db", help="Path to SQLite state file")
    p.add_argument("--periodic", type=int, default=60,
                   help="Trigger/flag check interval in seconds (default: 60)")
    p.add_argument("--status-interval", type=int, default=300, metavar="SECS",
                   help="Console status display interval in seconds (0 to disable, default: 300)")
    p.add_argument("--send-delay", type=float, default=4.0, metavar="SECS",
                   help="Delay in seconds between outgoing transmissions (default: 1.5)")
    p.add_argument("--verbose", action="store_true",
                   help="Print all location updates with zone proximity")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
    except ConfigError as e:
        log.error("Config error: %s", e)
        raise SystemExit(1)
    except FileNotFoundError:
        log.error("Config file not found: %s", args.config)
        raise SystemExit(1)

    log.info(
        "Loaded config: %d channels, %d zones, %d waypoints, %d events",
        len(config.channels), len(config.zones), len(config.waypoints), len(config.events),
    )
    if config.zones or config.waypoints:
        print(f"Zone map: {_zone_map_url(config)}", flush=True)

    state = GameState(args.db)
    state.init_schema()
    state.apply_initial_flags(config)
    state.apply_initial_groups(config)
    state.init_mutable_variables(config)
    state.init_event_states(config)

    # The meshtastic library dispatches via a publishingThread that queues pub.sendMessage
    # calls — this breaks pypubsub v4 parent-topic propagation, so subscribing to the
    # generic "meshtastic.receive" parent never fires.  Subscribe to the exact subtopics
    # the library actually publishes to instead.
    #
    # Engine is created with interface=None and updated immediately after the interface
    # constructor returns so it's set before any event response runs.
    #
    # connection.established fires inside __init__() so we call on_connection directly.
    engine = Engine(config, state, None, send_delay=args.send_delay)

    def _receive(packet, interface):
        on_receive(packet, interface, engine, args.verbose)

    for _topic in (
        "meshtastic.receive.text",       # TEXT_MESSAGE_APP
        "meshtastic.receive.position",   # POSITION_APP
        "meshtastic.receive.mapreport",  # MAP_REPORT_APP
        "meshtastic.receive.data.ATAK_PLUGIN",  # ATAK_PLUGIN (no registered handler)
        "meshtastic.receive.waypoint",   # WAYPOINT_APP
    ):
        pub.subscribe(_receive, _topic)

    _RECONNECT_DELAYS = (5, 10, 30, 60, 120)

    def _connect() -> meshtastic.tcp_interface.TCPInterface | meshtastic.serial_interface.SerialInterface:
        engine.channel_index_map.clear()
        if args.host:
            log.info("Connecting via TCP to %s:%d", args.host, args.tcp_port)
            iface = meshtastic.tcp_interface.TCPInterface(
                hostname=args.host, portNumber=args.tcp_port
            )
        else:
            log.info("Connecting via serial port %s", args.port or "(auto-detect)")
            iface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
        engine.interface = iface
        on_connection(iface, engine, config)
        return iface

    interface = _connect()

    threading.Thread(target=_periodic_loop, args=(engine, args.periodic), daemon=True).start()

    if args.status_interval > 0:
        threading.Thread(
            target=_status_loop, args=(config, state, args.status_interval), daemon=True
        ).start()

    log.info("Bot running. Press Ctrl+C to stop.")
    reconnect_attempt = 0
    try:
        while True:
            time.sleep(1)
            if not _interface_alive(interface):
                log.warning("Connection lost — will attempt to reconnect")
                _close_quietly(interface)
                delay = _RECONNECT_DELAYS[min(reconnect_attempt, len(_RECONNECT_DELAYS) - 1)]
                reconnect_attempt += 1
                log.info("Waiting %ds before reconnect attempt %d...", delay, reconnect_attempt)
                time.sleep(delay)
                try:
                    interface = _connect()
                    reconnect_attempt = 0
                    log.info("Reconnected successfully")
                except Exception:
                    log.exception("Reconnect attempt %d failed — will retry", reconnect_attempt)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        _close_quietly(interface)


if __name__ == "__main__":
    main()
