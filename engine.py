"""Event trigger evaluation and response execution for expLoRation."""
from __future__ import annotations
import json
import logging
import queue
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import IO, Any

import math
import secrets

from config import (
    GameConfig, Event, Variable, MutableVariableDef,
    ProximityTrigger, TimedTrigger, CommandTrigger, VariableThresholdTrigger,
    FlagExpiryTrigger, WaypointExpiryTrigger, WaypointReceivedTrigger,
    SendMessageResponse, SendAlertResponse, AddFlagResponse, RemoveFlagResponse,
    RequestLocationResponse, RequestTelemetryResponse, SetEventTriggersResponse,
    DisableEventResponse, EnableEventResponse,
    AddToGroupResponse, RemoveFromGroupResponse,
    SetVariableResponse, IncrementVariableResponse,
    RandomOptionsResponse, WithNodeResponse,
    CreateWaypointResponse, AddDynamicWaypointFlagResponse,
    RemoveDynamicWaypointFlagResponse, DestroyWaypointResponse,
    BroadcastWaypointResponse, DeleteMeshWaypointResponse,
    TargetTriggeringNode, TargetNode, TargetZone, TargetFlag,
    TargetWaypointRadius, TargetAllInZone, TargetAllWithFlag,
    TargetAllNearWaypoint, TargetAllNearTriggeringWaypoint, TargetAllNearNode, TargetChannel, TargetGroup,
    EventException,
)
from state import GameState
import geometry as geo

log = logging.getLogger(__name__)

_MAX_MSG_BYTES = 200
_VAR_RE = re.compile(r'\{(\w+)\}')
_BUILTIN_TOKENS = frozenset({"node_id", "node_shortname", "node_longname", "zone"})
_CAPTURE_HARD_CAP = 200


def _find_capture_var(template: str, mutable_var_defs: dict) -> str | None:
    tokens = _VAR_RE.findall(template)
    captures = [t for t in tokens if t in mutable_var_defs and t not in _BUILTIN_TOKENS]
    return captures[0] if len(captures) == 1 else None


def _split_capture_pattern(template: str, var_label: str) -> tuple[str, str]:
    token = f"{{{var_label}}}"
    idx = template.index(token)
    return template[:idx].rstrip(), template[idx + len(token):].lstrip()


def _can_coerce_capture(var_type: str, value: str) -> bool:
    if var_type == "integer":
        try:
            int(value)
            return True
        except ValueError:
            return False
    if var_type == "float":
        try:
            float(value)
            return True
        except ValueError:
            return False
    return True


def _split_message(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    buf: list[str] = []
    buf_bytes = 0
    for line in lines:
        lb = len(line.encode())
        if buf and buf_bytes + lb > _MAX_MSG_BYTES:
            chunks.append("".join(buf))
            buf, buf_bytes = [], 0
        if lb > _MAX_MSG_BYTES:
            # single line too long — split at byte boundary
            enc = line.encode()
            while enc:
                chunks.append(enc[:_MAX_MSG_BYTES].decode("utf-8", errors="ignore"))
                enc = enc[_MAX_MSG_BYTES:]
        else:
            buf.append(line)
            buf_bytes += lb
    if buf:
        chunks.append("".join(buf))
    return chunks or [""]


# ---------------------------------------------------------------------------
# Trigger context
# ---------------------------------------------------------------------------

@dataclass
class NodeContext:
    node_id: str
    entered_zones: frozenset[str] = field(default_factory=frozenset)
    left_zones: frozenset[str] = field(default_factory=frozenset)
    triggering_waypoint_id: int | None = None


@dataclass
class MessageContext:
    node_id: str
    text: str
    is_dm: bool
    channel_idx: int


@dataclass
class PeriodicContext:
    pass


@dataclass
class ExpiryContext:
    target_kind: str           # "node" | "zone" | "waypoint" | "dynamic_waypoint"
    target: str | int          # entity identifier (node_id, zone_label, waypoint_label, or wp int id)
    flag_label: str | None     # flag that expired; None for waypoint_expired events
    waypoint_flags: frozenset = field(default_factory=frozenset)  # flags waypoint had at expiry

    @property
    def node_id(self) -> str | None:
        return self.target if self.target_kind == "node" else None  # type: ignore[return-value]

    @property
    def triggering_waypoint_id(self) -> int | None:
        return self.target if self.target_kind == "dynamic_waypoint" else None  # type: ignore[return-value]


@dataclass
class WaypointReceivedContext:
    node_id: str | None           # sending node ID (!hex format)
    waypoint_name: str
    waypoint_description: str
    waypoint_lat: float
    waypoint_lon: float
    waypoint_expire: int          # Unix timestamp; 0 if no expiry
    mesh_waypoint_id: int | None


Context = NodeContext | MessageContext | PeriodicContext | ExpiryContext | WaypointReceivedContext


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Engine:
    def __init__(
        self,
        config: GameConfig,
        state: GameState,
        interface: Any,
        send_delay: float = 1.5,
        replay_log: IO[str] | None = None,
        replay_log_verbose: bool = False,
    ):
        self.config = config
        self.state = state
        self.interface = interface
        self.send_delay = send_delay
        self.replay_log = replay_log
        self.replay_log_verbose = replay_log_verbose
        self._group_kind: dict[str, str] = {g.label: g.kind for g in config.groups}
        self._mutable_var_defs: dict[str, MutableVariableDef] = {
            mv.label: mv for mv in config.mutable_variables
        }

        # populated by bot.py on connection
        self.channel_index_map: dict[str, int] = {}   # channel_label → device index
        self.my_node_num: int | None = None

        self._send_queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._sender_loop, daemon=True).start()

        # Tracks which zone labels each node is currently inside, for transition detection
        self._node_zones: dict[str, frozenset[str]] = {}
        self._suppress_messages = False

    # ------------------------------------------------------------------
    # Replay log helpers
    # ------------------------------------------------------------------

    def _write_replay(self, record: dict) -> None:
        if self.replay_log is None:
            return
        self.replay_log.write(json.dumps(record, default=str) + "\n")
        self.replay_log.flush()

    def _ctx_fields(self, ctx: Context) -> dict:
        d: dict = {"context_type": type(ctx).__name__}
        node_id = getattr(ctx, "node_id", None)
        if node_id:
            d["node_id"] = node_id
        if isinstance(ctx, NodeContext):
            if ctx.entered_zones:
                d["entered_zones"] = sorted(ctx.entered_zones)
            if ctx.left_zones:
                d["left_zones"] = sorted(ctx.left_zones)
        elif isinstance(ctx, MessageContext):
            if ctx.channel_label:
                d["channel"] = ctx.channel_label
        elif isinstance(ctx, ExpiryContext):
            d["target_kind"] = ctx.target_kind
            if ctx.flag_label:
                d["flag_label"] = ctx.flag_label
        elif isinstance(ctx, WaypointReceivedContext):
            d["waypoint_name"] = ctx.waypoint_name
            d["waypoint_lat"] = round(ctx.waypoint_lat, 5)
            d["waypoint_lon"] = round(ctx.waypoint_lon, 5)
        return d

    @staticmethod
    def _trigger_typename(trigger) -> str:
        if hasattr(trigger, "kind"):
            return trigger.kind
        name = type(trigger).__name__
        if name.endswith("Trigger"):
            name = name[:-7]
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()

    @staticmethod
    def _resp_typename(resp) -> str:
        name = type(resp).__name__
        if name.endswith("Response"):
            name = name[:-8]
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()

    def _log_skip(self, event: Event, ctx: Context, reason: str) -> None:
        if not self.replay_log_verbose:
            return
        self._write_replay({
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "skip",
            "event": event.label,
            "trigger_type": self._trigger_typename(event.trigger),
            "skip_reason": reason,
            **self._ctx_fields(ctx),
        })

    def seed_node_location(self, node_id: str, lat: float, lon: float) -> None:
        """Process a node's starting location through the normal event pipeline but suppress all outbound messages."""
        self._suppress_messages = True
        try:
            self.handle_position(node_id, lat, lon)
        finally:
            self._suppress_messages = False

    def _sender_loop(self) -> None:
        while True:
            fn = self._send_queue.get()
            try:
                fn()
            except Exception:
                log.exception("Error in sender thread")
            finally:
                self._send_queue.task_done()
            time.sleep(self.send_delay)

    # ------------------------------------------------------------------
    # Public handlers (called by bot.py)
    # ------------------------------------------------------------------

    def handle_position(self, node_id: str, lat: float, lon: float) -> None:
        self.state.update_node_location(node_id, lat, lon)
        expired_flags = self.state.expire_flags()
        expired_dynamic_flags = self.state.expire_dynamic_waypoint_flags()
        expired_waypoints = self.state.expire_dynamic_waypoints()
        self._dispatch_expiry_events(expired_flags, expired_dynamic_flags, expired_waypoints)
        self._delete_expired_mesh_waypoints(self.state.expire_mesh_waypoints())

        prev_zones = self._node_zones.get(node_id, frozenset())
        curr_zones = frozenset(
            z.label for z in self.config.zones
            if geo.point_in_triangle((lat, lon), *z.points)
        )
        self._node_zones[node_id] = curr_zones

        ctx = NodeContext(
            node_id,
            entered_zones=curr_zones - prev_zones,
            left_zones=prev_zones - curr_zones,
        )
        for event in self.config.events:
            if isinstance(event.trigger, ProximityTrigger) and event.trigger.kind != "in_zone_on_start":
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)
        for event in self.config.events:
            if isinstance(event.trigger, VariableThresholdTrigger):
                var_def = self._mutable_var_defs.get(event.trigger.variable_label)
                computed_var = None if var_def else self._get_variable(event.trigger.variable_label)
                is_node_scoped = (
                    (var_def is not None and var_def.scope == "node") or
                    (computed_var is not None and computed_var.scope == "node")
                )
                if is_node_scoped:
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

    def handle_message(
        self, node_id: str, text: str, is_dm: bool, channel_idx: int
    ) -> None:
        expired_flags = self.state.expire_flags()
        expired_dynamic_flags = self.state.expire_dynamic_waypoint_flags()
        expired_waypoints = self.state.expire_dynamic_waypoints()
        self._dispatch_expiry_events(expired_flags, expired_dynamic_flags, expired_waypoints)
        self._delete_expired_mesh_waypoints(self.state.expire_mesh_waypoints())
        ctx = MessageContext(node_id, text, is_dm, channel_idx)
        for event in self.config.events:
            if isinstance(event.trigger, CommandTrigger):
                if self._should_fire(event, ctx):
                    self._apply_command_capture(event, ctx)
                    self._fire_event(event, ctx)
        for event in self.config.events:
            if isinstance(event.trigger, VariableThresholdTrigger):
                var_def = self._mutable_var_defs.get(event.trigger.variable_label)
                if var_def is not None and var_def.scope == "node":
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

    def handle_periodic(self) -> None:
        expired_flags = self.state.expire_flags()
        expired_dynamic_flags = self.state.expire_dynamic_waypoint_flags()
        expired_waypoints = self.state.expire_dynamic_waypoints()
        self._dispatch_expiry_events(expired_flags, expired_dynamic_flags, expired_waypoints)
        self._delete_expired_mesh_waypoints(self.state.expire_mesh_waypoints())
        ctx = PeriodicContext()
        for event in self.config.events:
            if isinstance(event.trigger, TimedTrigger):
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)
            elif (
                isinstance(event.trigger, ProximityTrigger)
                and event.trigger.kind in ("in_zone_on_start", "in_zone_group_on_start")
            ):
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)

            if event.auto_recur and event.recur_mins is not None:
                self._maybe_auto_recur(event)

        for event in self.config.events:
            if isinstance(event.trigger, VariableThresholdTrigger):
                var_def = self._mutable_var_defs.get(event.trigger.variable_label)
                # var_def is None for computed variables (from variables:) — check those in periodic too
                if var_def is None or var_def.scope == "global":
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

    def handle_waypoint_received(self, ctx: WaypointReceivedContext) -> None:
        expired_flags = self.state.expire_flags()
        expired_dynamic_flags = self.state.expire_dynamic_waypoint_flags()
        expired_waypoints = self.state.expire_dynamic_waypoints()
        self._dispatch_expiry_events(expired_flags, expired_dynamic_flags, expired_waypoints)
        self._delete_expired_mesh_waypoints(self.state.expire_mesh_waypoints())
        for event in self.config.events:
            if isinstance(event.trigger, WaypointReceivedTrigger):
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)

    def _delete_expired_mesh_waypoints(self, expired_ids: list[int]) -> None:
        for mesh_wp_id in expired_ids:
            def _fn(mid=mesh_wp_id):
                if self.interface is None:
                    return
                try:
                    self.interface.deleteWaypoint(waypoint_id=mid)
                    log.info("Deleted expired mesh waypoint id=%d", mid)
                except Exception:
                    log.warning("Failed to delete expired mesh waypoint id=%d", mid, exc_info=True)
            self._send_queue.put(_fn)

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def _should_fire(self, event: Event, ctx: Context) -> bool:
        if self.state.is_event_disabled(event.label):
            self._log_skip(event, ctx, "disabled")
            return False

        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext, ExpiryContext)) else None
        if event.trigger_per_node and node_id is not None:
            times, last = self.state.get_node_event_state(event.label, node_id)
        else:
            times, last = self.state.get_event_state(event.label)

        if event.max_triggers is not None and times >= event.max_triggers:
            self._log_skip(event, ctx, "max_triggers")
            return False

        if event.reset_mins is not None and last is not None:
            cutoff = last + timedelta(minutes=event.reset_mins)
            if datetime.now(timezone.utc) < cutoff:
                self._log_skip(event, ctx, "cooldown")
                return False

        if not self._check_trigger(event, ctx):
            return False

        exc_reason = self._check_exceptions(event, ctx)
        if exc_reason:
            self._log_skip(event, ctx, exc_reason)
            return False

        return True

    def _check_trigger(self, event: Event, ctx: Context) -> bool:
        t = event.trigger

        if isinstance(t, ProximityTrigger):
            if not isinstance(ctx, (NodeContext, PeriodicContext)):
                return False

            located = self.state.get_all_located_nodes()

            if t.kind == "near_waypoint":
                if not isinstance(ctx, NodeContext):
                    return False
                node_loc = located.get(ctx.node_id)
                if node_loc is None:
                    return False
                if t.target_label:
                    waypoint = self._get_waypoint(t.target_label)
                    if waypoint is None:
                        return False
                    return geo.haversine(*node_loc, waypoint.lat, waypoint.lon) <= t.meters
                else:
                    candidates = self.state.get_dynamic_waypoints_with_flag(t.target_flag)
                    in_range = [
                        (geo.haversine(*node_loc, lat, lon), wp_id)
                        for wp_id, lat, lon in candidates
                        if geo.haversine(*node_loc, lat, lon) <= t.meters
                    ]
                    if not in_range:
                        return False
                    ctx.triggering_waypoint_id = min(in_range)[1]
                    return True

            if t.kind == "near_zone":
                if not isinstance(ctx, NodeContext):
                    return False
                zone = self._get_zone(t.target_label)
                if zone is None:
                    return False
                node_loc = located.get(ctx.node_id)
                if node_loc is None:
                    return False
                clat, clon = geo.zone_centroid(zone)
                return geo.haversine(*node_loc, clat, clon) <= t.meters

            if t.kind == "in_zone":
                if not isinstance(ctx, NodeContext):
                    return False
                zone = self._get_zone(t.target_label)
                if zone is None:
                    return False
                node_loc = located.get(ctx.node_id)
                if node_loc is None:
                    return False
                return geo.point_in_triangle(node_loc, *zone.points)

            if t.kind == "enters_zone":
                if not isinstance(ctx, NodeContext):
                    return False
                return t.target_label in ctx.entered_zones

            if t.kind == "leaves_zone":
                if not isinstance(ctx, NodeContext):
                    return False
                return t.target_label in ctx.left_zones

            if t.kind == "enters_zone_group":
                if not isinstance(ctx, NodeContext):
                    return False
                members = self.state.get_group_members(t.zone_group)
                return bool(ctx.entered_zones & set(members))

            if t.kind == "leaves_zone_group":
                if not isinstance(ctx, NodeContext):
                    return False
                members = self.state.get_group_members(t.zone_group)
                return bool(ctx.left_zones & set(members))

            if t.kind == "in_zone_group":
                if not isinstance(ctx, NodeContext):
                    return False
                node_loc = located.get(ctx.node_id)
                if node_loc is None:
                    return False
                return any(
                    geo.point_in_triangle(node_loc, *z.points)
                    for lbl in self.state.get_group_members(t.zone_group)
                    if (z := self._get_zone(lbl)) is not None
                )

            if t.kind == "in_zone_group_on_start":
                if not isinstance(ctx, PeriodicContext):
                    return False
                return any(
                    node_id
                    for lbl in self.state.get_group_members(t.zone_group)
                    if (z := self._get_zone(lbl)) is not None
                    for node_id in geo.nodes_in_zone(z, located)
                )

            if t.kind == "near_node":
                if not isinstance(ctx, NodeContext):
                    return False
                target_node = self._get_node_def(t.target_label)
                if target_node is None:
                    return False
                node_loc = located.get(ctx.node_id)
                target_loc = located.get(target_node.node_id)
                if node_loc is None or target_loc is None:
                    return False
                return geo.haversine(*node_loc, *target_loc) <= t.meters

            if t.kind == "in_zone_on_start":
                if not isinstance(ctx, PeriodicContext):
                    return False
                zone = self._get_zone(t.target_label)
                if zone is None:
                    return False
                in_zone = geo.nodes_in_zone(zone, located)
                return len(in_zone) > 0

        elif isinstance(t, TimedTrigger):
            if not isinstance(ctx, PeriodicContext):
                return False
            now = datetime.now(timezone.utc)
            start = t.start if t.start.tzinfo else t.start.replace(tzinfo=timezone.utc)
            end = t.end if t.end.tzinfo else t.end.replace(tzinfo=timezone.utc)
            times, _ = self.state.get_event_state(event.label)
            return times == 0 and start <= now <= end

        elif isinstance(t, CommandTrigger):
            if not isinstance(ctx, MessageContext):
                return False
            message = self._get_message(t.message_label)
            if message is None:
                return False
            var_label = _find_capture_var(message.text, self._mutable_var_defs)
            if var_label is None:
                if ctx.text.strip() != message.text.strip():
                    return False
            else:
                prefix, suffix = _split_capture_pattern(message.text, var_label)
                incoming = ctx.text.strip()
                if not incoming.startswith(prefix):
                    return False
                remainder = incoming[len(prefix):].lstrip()
                if suffix:
                    if not remainder.endswith(suffix):
                        return False
                    captured = remainder[: len(remainder) - len(suffix)].rstrip()
                else:
                    captured = remainder
                if not captured:
                    return False
                if len(captured) > _CAPTURE_HARD_CAP:
                    return False
                var_def = self._mutable_var_defs[var_label]
                if var_def.max_length is not None and len(captured) > var_def.max_length:
                    return False
                if not _can_coerce_capture(var_def.type, captured):
                    return False
            if t.kind == "dm" and not ctx.is_dm:
                return False
            if t.kind == "channel":
                if ctx.is_dm:
                    return False
                expected_idx = self.channel_index_map.get(t.channel_label)
                if expected_idx is None or ctx.channel_idx != expected_idx:
                    return False
            if t.zone_label is not None:
                zone = self._get_zone(t.zone_label)
                if zone is None:
                    return False
                node_loc = self.state.get_node_location(ctx.node_id)
                if node_loc is None:
                    return False
                if not geo.point_in_triangle(node_loc, *zone.points):
                    return False
            if t.zone_group is not None:
                node_loc = self.state.get_node_location(ctx.node_id)
                if node_loc is None:
                    return False
                if not any(
                    geo.point_in_triangle(node_loc, *z.points)
                    for lbl in self.state.get_group_members(t.zone_group)
                    if (z := self._get_zone(lbl)) is not None
                ):
                    return False
            return True

        elif isinstance(t, VariableThresholdTrigger):
            var_def = self._mutable_var_defs.get(t.variable_label)
            if var_def is None:
                computed_var = self._get_variable(t.variable_label)
                if computed_var is None:
                    return False
                triggering_node_id = getattr(ctx, "node_id", None)
                raw_str = self._resolve_variable(computed_var, triggering_node_id)
                try:
                    raw: int | float | str = int(raw_str)
                except ValueError:
                    try:
                        raw = float(raw_str)
                    except ValueError:
                        raw = raw_str
                # Non-numeric result (e.g. "[unknown]") can't satisfy numeric operators
                if isinstance(raw, str) and t.operator not in ("eq", "neq"):
                    return False
                return self._evaluate_threshold(raw, t.operator, t.value)
            if var_def.scope == "node":
                if not isinstance(ctx, (NodeContext, MessageContext)):
                    return False
                raw = self.state.get_mutable_variable(t.variable_label, ctx.node_id)
            else:
                raw = self.state.get_mutable_variable(t.variable_label)
            if raw is None:
                raw = var_def.initial
            return self._evaluate_threshold(raw, t.operator, t.value)

        elif isinstance(t, FlagExpiryTrigger):
            if not isinstance(ctx, ExpiryContext):
                return False
            return ctx.flag_label == t.flag_label and ctx.target_kind == t.target_kind

        elif isinstance(t, WaypointExpiryTrigger):
            if not isinstance(ctx, ExpiryContext):
                return False
            if ctx.flag_label is not None:  # flag_expired context, not waypoint_expired
                return False
            if t.had_flag is not None and t.had_flag not in ctx.waypoint_flags:
                return False
            return True

        elif isinstance(t, WaypointReceivedTrigger):
            if not isinstance(ctx, WaypointReceivedContext):
                return False
            if t.from_flag and ctx.node_id:
                if not self.state.has_flag("node", ctx.node_id, t.from_flag):
                    return False
            if t.name_contains:
                if t.name_contains.lower() not in ctx.waypoint_name.lower():
                    return False
            return True

        return False

    @staticmethod
    def _evaluate_threshold(current, operator: str, threshold) -> bool:
        ops = {
            "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b,
            "eq": lambda a, b: a == b, "neq": lambda a, b: a != b,
            "gte": lambda a, b: a >= b, "gt": lambda a, b: a > b,
        }
        fn = ops.get(operator)
        return fn(current, threshold) if fn else False

    def _check_exceptions(self, event: Event, ctx: Context) -> str | None:
        """Returns the blocking exception reason string, or None if no exception fires."""
        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext, ExpiryContext)) else None
        # Evaluate deterministic exceptions first
        for exc in event.exceptions:
            if exc.kind == "random_skip":
                continue
            if self._exception_matches(exc, node_id, ctx):
                reason = f"exception:{exc.kind}"
                if exc.flag:
                    reason += f":{exc.flag}"
                return reason
        # Roll random_skip only if all deterministic exceptions passed
        for exc in event.exceptions:
            if exc.kind == "random_skip" and self._exception_matches(exc, node_id, ctx):
                return "exception:random_skip"
        return None

    def _exception_matches(self, exc: EventException, node_id: str | None, ctx: Context) -> bool:
        kind = exc.kind
        if kind == "random_skip":
            return random.random() < (exc.chance or 0.0)
        if kind in ("node_has_flag", "node_lacks_flag"):
            if node_id is None:
                return False
            has = self.state.has_flag("node", node_id, exc.flag)
            return has if kind == "node_has_flag" else not has
        if kind in ("zone_has_flag", "zone_lacks_flag"):
            if exc.target is None:
                return False
            has = self.state.has_flag("zone", exc.target, exc.flag)
            return has if kind == "zone_has_flag" else not has
        if kind in ("waypoint_has_flag", "waypoint_lacks_flag"):
            if exc.target is not None:
                has = self.state.has_flag("waypoint", exc.target, exc.flag)
            else:
                wp_id = ctx.triggering_waypoint_id if isinstance(ctx, (NodeContext, ExpiryContext)) else None
                if wp_id is None:
                    return False
                has = self.state.has_dynamic_waypoint_flag(wp_id, exc.flag)
            return has if kind == "waypoint_has_flag" else not has
        if kind in ("node_in_group", "node_not_in_group"):
            if node_id is None or exc.group is None:
                return False
            result = self.state.is_in_group(exc.group, node_id)
            return result if kind == "node_in_group" else not result
        if kind in ("zone_in_group", "zone_not_in_group"):
            if exc.target is None or exc.group is None:
                return False
            result = self.state.is_in_group(exc.group, exc.target)
            return result if kind == "zone_in_group" else not result
        if kind in ("waypoint_in_group", "waypoint_not_in_group"):
            if exc.target is None or exc.group is None:
                return False
            result = self.state.is_in_group(exc.group, exc.target)
            return result if kind == "waypoint_in_group" else not result
        return False

    def _dispatch_expiry_events(
        self,
        expired_flags: list[tuple[str, str, str]],
        expired_dynamic_flags: list[tuple[int, str]],
        expired_waypoints: list[tuple[int, frozenset]],
    ) -> None:
        for kind, entity_id, flag_label in expired_flags:
            ctx = ExpiryContext(target_kind=kind, target=entity_id, flag_label=flag_label)
            for event in self.config.events:
                if isinstance(event.trigger, FlagExpiryTrigger):
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

        for wp_id, flag_label in expired_dynamic_flags:
            ctx = ExpiryContext(target_kind="dynamic_waypoint", target=wp_id, flag_label=flag_label)
            for event in self.config.events:
                if isinstance(event.trigger, FlagExpiryTrigger):
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

        for wp_id, flags in expired_waypoints:
            # flag_label=None signals waypoint_expired (not individual flag expiry)
            ctx = ExpiryContext(
                target_kind="dynamic_waypoint",
                target=wp_id,
                flag_label=None,
                waypoint_flags=flags,
            )
            for event in self.config.events:
                if isinstance(event.trigger, WaypointExpiryTrigger):
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

    # ------------------------------------------------------------------
    # Response execution
    # ------------------------------------------------------------------

    def _maybe_auto_recur(self, event: Event) -> None:
        if self.state.is_event_disabled(event.label):
            return
        times, last = self.state.get_event_state(event.label)
        if times == 0:
            return  # hasn't fired yet through its normal trigger
        if event.max_triggers is not None and times >= event.max_triggers:
            return
        if last is not None:
            now = datetime.now(timezone.utc)
            last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            if now < last_aware + timedelta(minutes=event.recur_mins):
                return
        ctx = PeriodicContext()
        if not self._check_exceptions(event, ctx):
            self._fire_event(event, ctx)

    def _apply_command_capture(self, event: Event, ctx: MessageContext) -> None:
        trigger = event.trigger
        if not isinstance(trigger, CommandTrigger):
            return
        message = self._get_message(trigger.message_label)
        if message is None:
            return
        var_label = _find_capture_var(message.text, self._mutable_var_defs)
        if var_label is None:
            return
        var_def = self._mutable_var_defs[var_label]
        prefix, suffix = _split_capture_pattern(message.text, var_label)
        incoming = ctx.text.strip()
        remainder = incoming[len(prefix):].lstrip()
        captured = remainder[: len(remainder) - len(suffix)].rstrip() if suffix else remainder
        if var_def.type == "integer":
            value = int(captured)
        elif var_def.type == "float":
            value = float(captured)
        else:
            value = captured
        value = self._clamp_value(var_def, value)
        self.state.set_mutable_variable(var_def.label, value, ctx.node_id)
        log.info("capture_command: set %r[%s] = %r", var_def.label, ctx.node_id, value)

    def _fire_event(self, event: Event, ctx: Context) -> None:
        log.info("Firing event %r (ctx=%s)", event.label, ctx)
        for resp in event.responses:
            try:
                self._execute_response(resp, ctx)
            except Exception:
                log.exception("Error executing response in event %r", event.label)
        self.state.increment_event_triggers(event.label)
        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext, ExpiryContext, WaypointReceivedContext)) else None
        if event.trigger_per_node and node_id is not None:
            self.state.increment_node_event_triggers(event.label, node_id)
        if self.replay_log is not None:
            times, _ = self.state.get_event_state(event.label)
            self._write_replay({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": "fire",
                "event": event.label,
                "trigger_type": self._trigger_typename(event.trigger),
                "responses": [self._resp_typename(r) for r in event.responses],
                "fire_number": times,
                **self._ctx_fields(ctx),
            })

    def _execute_response(self, resp, ctx: Context) -> None:
        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext, ExpiryContext, WaypointReceivedContext)) else None
        wp_id = getattr(ctx, "triggering_waypoint_id", None)
        entered_zones = ctx.entered_zones if isinstance(ctx, NodeContext) else frozenset()
        if entered_zones:
            zone_id = next(iter(entered_zones))
        elif node_id and self._node_zones.get(node_id):
            zone_id = next(iter(self._node_zones[node_id]))
        else:
            zone_id = None
        extra_tokens: dict[str, str] | None = None
        if isinstance(ctx, WaypointReceivedContext):
            extra_tokens = {
                "waypoint_name": ctx.waypoint_name,
                "waypoint_description": ctx.waypoint_description,
                "waypoint_lat": f"{ctx.waypoint_lat:.5f}",
                "waypoint_lon": f"{ctx.waypoint_lon:.5f}",
            }

        if isinstance(resp, SendMessageResponse):
            message = self._get_message(resp.message_label)
            if message is None:
                return
            text = self._interpolate(message.text, node_id, zone_id, extra_tokens)
            if isinstance(resp.target, TargetChannel):
                self._send_channel(resp.target.channel_label, text)
            else:
                nodes = self._resolve_node_targets(resp.target, node_id, wp_id)
                for nid in nodes:
                    self._send_dm(nid, text)

        elif isinstance(resp, SendAlertResponse):
            message = self._get_message(resp.message_label)
            if message is None:
                return
            text = self._interpolate(message.text, node_id, zone_id, extra_tokens)
            if isinstance(resp.target, TargetChannel):
                self._send_alert_channel(resp.target.channel_label, text)
            else:
                nodes = self._resolve_node_targets(resp.target, node_id, wp_id)
                for nid in nodes:
                    self._send_alert(nid, text)

        elif isinstance(resp, (AddFlagResponse, RemoveFlagResponse)):
            adding = isinstance(resp, AddFlagResponse)
            flag_def = self._get_flag_def(resp.flag_label)
            expiry_mins = flag_def.expiry_mins if flag_def else None
            targets = self._resolve_flag_targets(resp.target, node_id, wp_id)
            for kind, target in targets:
                if adding:
                    self.state.add_flag(kind, target, resp.flag_label, expiry_mins=expiry_mins)
                    log.info("Added flag %r to %s %r", resp.flag_label, kind, target)
                else:
                    self.state.remove_flag(kind, target, resp.flag_label)
                    log.info("Removed flag %r from %s %r", resp.flag_label, kind, target)

        elif isinstance(resp, RequestLocationResponse):
            nodes = self._resolve_node_targets(resp.target, node_id, wp_id)
            for nid in nodes:
                self._request_location(nid)

        elif isinstance(resp, RequestTelemetryResponse):
            nodes = self._resolve_node_targets(resp.target, node_id, wp_id)
            for nid in nodes:
                self._request_telemetry(nid)

        elif isinstance(resp, SetEventTriggersResponse):
            self.state.set_event_triggers(resp.event_label, resp.value)
            log.info("Set event %r times_triggered=%d", resp.event_label, resp.value)

        elif isinstance(resp, DisableEventResponse):
            self.state.set_event_disabled(resp.event_label, True)
            log.info("Disabled event %r", resp.event_label)

        elif isinstance(resp, EnableEventResponse):
            self.state.set_event_disabled(resp.event_label, False)
            log.info("Enabled event %r", resp.event_label)

        elif isinstance(resp, (AddToGroupResponse, RemoveFromGroupResponse)):
            adding = isinstance(resp, AddToGroupResponse)
            op = "add_to_group" if adding else "remove_from_group"
            kind = self._group_kind.get(resp.group_label, "node")
            if kind == "node":
                members = self._resolve_node_targets(resp.target, node_id, wp_id)
            elif kind == "zone":
                members = [resp.target.zone_label] if isinstance(resp.target, TargetZone) else []
            else:  # waypoint
                members = [resp.target.waypoint_label] if hasattr(resp.target, "waypoint_label") else []
            for member in members:
                if adding:
                    self.state.add_to_group(resp.group_label, member)
                else:
                    self.state.remove_from_group(resp.group_label, member)
                log.info("%s %s → %s", op, resp.group_label, member)

        elif isinstance(resp, SetVariableResponse):
            var_def = self._mutable_var_defs.get(resp.variable_label)
            if var_def is None:
                return
            if var_def.scope == "node":
                for nid in self._resolve_node_targets(resp.target, node_id, wp_id):
                    self._set_variable(var_def, resp.value, nid)
            else:
                self._set_variable(var_def, resp.value)

        elif isinstance(resp, IncrementVariableResponse):
            var_def = self._mutable_var_defs.get(resp.variable_label)
            if var_def is None:
                return
            if var_def.scope == "node":
                for nid in self._resolve_node_targets(resp.target, node_id, wp_id):
                    self._increment_variable(var_def, resp.amount, nid)
            else:
                self._increment_variable(var_def, resp.amount)

        elif isinstance(resp, RandomOptionsResponse):
            weights = [opt.weight for opt in resp.options]
            chosen = random.choices(resp.options, weights=weights, k=1)[0]
            log.info("random_options selected option with weight %s", chosen.weight)
            for nested_resp in chosen.responses:
                try:
                    self._execute_response(nested_resp, ctx)
                except Exception:
                    log.exception("Error executing response in random_options branch")

        elif isinstance(resp, WithNodeResponse):
            selected_ids = self._resolve_node_targets(resp.target, node_id, wp_id)
            if not selected_ids:
                log.warning("with_node: no nodes resolved; skipping")
                return
            for selected_id in selected_ids:
                loc = self.state.get_node_location(selected_id)
                if loc is None:
                    log.warning("with_node: skipping node %s — no known location", selected_id)
                    continue
                inner_ctx = NodeContext(
                    node_id=selected_id,
                    triggering_waypoint_id=getattr(ctx, "triggering_waypoint_id", None),
                )
                log.info("with_node: executing %d responses in context of %s",
                         len(resp.responses), selected_id)
                for inner_resp in resp.responses:
                    try:
                        self._execute_response(inner_resp, inner_ctx)
                    except Exception:
                        log.exception("Error in with_node response for node %s", selected_id)

        elif isinstance(resp, CreateWaypointResponse):
            loc = self.state.get_node_location(node_id) if node_id else None
            if loc is None:
                log.warning("create_waypoint: no location for node %s; skipping", node_id)
                return
            lat, lon = loc
            flag_map = {f.label: f for f in self.config.flags}
            new_wp_id = self.state.create_dynamic_waypoint(lat, lon, resp.expiry_mins)
            for flag_label in resp.initial_flags:
                expiry = flag_map[flag_label].expiry_mins if flag_label in flag_map else None
                self.state.add_dynamic_waypoint_flag(new_wp_id, flag_label, expiry)
            log.info("Created dynamic waypoint %d at %.5f,%.5f flags=%s", new_wp_id, lat, lon, resp.initial_flags)
            if resp.mesh_name is not None:
                expire_ts = int(time.time()) + int(resp.expiry_mins * 60) if resp.expiry_mins else 0
                mesh_wp_id = math.floor(secrets.randbits(32) * math.pow(2, -32) * 1e9)
                if resp.mesh_channel:
                    ch_idx = self._resolve_channel_index(resp.mesh_channel)
                    if ch_idx is None:
                        log.warning("create_waypoint mesh broadcast: channel %r not mapped", resp.mesh_channel)
                    else:
                        from meshtastic import BROADCAST_ADDR as _BCAST
                        def _fn(n=resp.mesh_name, d=resp.mesh_description, ic=resp.mesh_icon,
                                ex=expire_ts, wid=mesh_wp_id, la=lat, lo=lon, ci=ch_idx, ba=_BCAST):
                            if self.interface is None:
                                return
                            self.interface.sendWaypoint(
                                name=n, description=d, icon=ic, expire=ex,
                                waypoint_id=wid, latitude=la, longitude=lo,
                                destinationId=ba, channelIndex=ci,
                            )
                            log.info("create_waypoint mesh broadcast %r ch%d (id=%d)", n, ci, wid)
                        self._send_queue.put(_fn)
                        self.state.set_mesh_waypoint_id_for_dynamic(new_wp_id, mesh_wp_id)
                        if resp.mesh_label:
                            self.state.store_mesh_waypoint(
                                mesh_wp_id, resp.mesh_name, lat, lon,
                                label=resp.mesh_label, expiry_mins=resp.expiry_mins,
                            )
                elif resp.mesh_to_triggering_node and node_id:
                    try:
                        dest = int(node_id.lstrip("!"), 16)
                    except ValueError:
                        log.warning("create_waypoint mesh broadcast: invalid node_id %r", node_id)
                    else:
                        def _fn(n=resp.mesh_name, d=resp.mesh_description, ic=resp.mesh_icon,
                                ex=expire_ts, wid=mesh_wp_id, la=lat, lo=lon, de=dest):
                            if self.interface is None:
                                return
                            self.interface.sendWaypoint(
                                name=n, description=d, icon=ic, expire=ex,
                                waypoint_id=wid, latitude=la, longitude=lo,
                                destinationId=de, channelIndex=0,
                            )
                            log.info("create_waypoint mesh DM %r → !%08x (id=%d)", n, de, wid)
                        self._send_queue.put(_fn)
                        self.state.set_mesh_waypoint_id_for_dynamic(new_wp_id, mesh_wp_id)
                        if resp.mesh_label:
                            self.state.store_mesh_waypoint(
                                mesh_wp_id, resp.mesh_name, lat, lon,
                                label=resp.mesh_label, expiry_mins=resp.expiry_mins,
                            )

        elif isinstance(resp, AddDynamicWaypointFlagResponse):
            wp_id = ctx.triggering_waypoint_id if isinstance(ctx, NodeContext) else None
            if wp_id is None:
                log.warning("add_waypoint_flag: no triggering waypoint in context; skipping")
                return
            flag_map = {f.label: f for f in self.config.flags}
            expiry = flag_map[resp.flag_label].expiry_mins if resp.flag_label in flag_map else None
            self.state.add_dynamic_waypoint_flag(wp_id, resp.flag_label, expiry)
            log.info("Added flag %r to dynamic waypoint %d", resp.flag_label, wp_id)

        elif isinstance(resp, RemoveDynamicWaypointFlagResponse):
            wp_id = ctx.triggering_waypoint_id if isinstance(ctx, NodeContext) else None
            if wp_id is None:
                log.warning("remove_waypoint_flag: no triggering waypoint in context; skipping")
                return
            self.state.remove_dynamic_waypoint_flag(wp_id, resp.flag_label)
            log.info("Removed flag %r from dynamic waypoint %d", resp.flag_label, wp_id)

        elif isinstance(resp, DestroyWaypointResponse):
            wp_id = ctx.triggering_waypoint_id if isinstance(ctx, NodeContext) else None
            if wp_id is None:
                log.warning("destroy_waypoint: no triggering waypoint in context; skipping")
                return
            self.state.destroy_dynamic_waypoint(wp_id)
            log.info("Destroyed dynamic waypoint %d", wp_id)

        elif isinstance(resp, BroadcastWaypointResponse):
            if resp.lat is not None and resp.lon is not None:
                lat, lon = resp.lat, resp.lon
            else:
                loc = self.state.get_node_location(node_id) if node_id else None
                if loc is None:
                    log.warning("broadcast_waypoint: no location for node %s; skipping", node_id)
                    return
                lat, lon = loc
            expire_ts = int(time.time()) + int(resp.expiry_mins * 60) if resp.expiry_mins else 0
            mesh_wp_id = math.floor(secrets.randbits(32) * math.pow(2, -32) * 1e9)
            from meshtastic import BROADCAST_ADDR as _BCAST
            if isinstance(resp.target, TargetChannel):
                ch_idx = self._resolve_channel_index(resp.target.channel_label)
                if ch_idx is None:
                    log.warning("broadcast_waypoint: channel %r not mapped", resp.target.channel_label)
                    return
                def _fn(n=resp.name, d=resp.description, ic=resp.icon,
                        ex=expire_ts, wid=mesh_wp_id, la=lat, lo=lon, ci=ch_idx, ba=_BCAST):
                    if self.interface is None:
                        return
                    self.interface.sendWaypoint(
                        name=n, description=d, icon=ic, expire=ex,
                        waypoint_id=wid, latitude=la, longitude=lo,
                        destinationId=ba, channelIndex=ci,
                    )
                    log.info("broadcast_waypoint %r on ch%d (id=%d)", n, ci, wid)
                self._send_queue.put(_fn)
            else:
                node_ids = self._resolve_node_targets(resp.target, node_id, wp_id)
                for nid in node_ids:
                    try:
                        dest = int(nid.lstrip("!"), 16)
                    except ValueError:
                        continue
                    def _fn(n=resp.name, d=resp.description, ic=resp.icon,
                            ex=expire_ts, wid=mesh_wp_id, la=lat, lo=lon, de=dest):
                        if self.interface is None:
                            return
                        self.interface.sendWaypoint(
                            name=n, description=d, icon=ic, expire=ex,
                            waypoint_id=wid, latitude=la, longitude=lo,
                            destinationId=de, channelIndex=0,
                        )
                        log.info("broadcast_waypoint %r DM → !%08x (id=%d)", n, de, wid)
                    self._send_queue.put(_fn)
            if resp.label:
                self.state.store_mesh_waypoint(
                    mesh_wp_id, resp.name, lat, lon,
                    label=resp.label, expiry_mins=resp.expiry_mins,
                )
            if wp_id is not None:
                self.state.set_mesh_waypoint_id_for_dynamic(wp_id, mesh_wp_id)

        elif isinstance(resp, DeleteMeshWaypointResponse):
            mesh_wp_id = None
            if resp.use_triggering_waypoint and wp_id is not None:
                mesh_wp_id = self.state.get_mesh_waypoint_id_for_dynamic(wp_id)
            elif resp.label:
                mesh_wp_id = self.state.get_mesh_waypoint_id_by_label(resp.label)
            if mesh_wp_id is None:
                log.warning("delete_mesh_waypoint: no mesh_waypoint_id found (label=%r, wp=%s)",
                            resp.label, wp_id)
                return
            def _fn(mid=mesh_wp_id):
                if self.interface is None:
                    return
                self.interface.deleteWaypoint(waypoint_id=mid)
                log.info("delete_mesh_waypoint id=%d", mid)
            self._send_queue.put(_fn)
            self.state.delete_mesh_waypoint_record(mesh_wp_id)

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    def _set_variable(self, var_def: MutableVariableDef, value, node_id: str = '') -> None:
        value = self._coerce_value(var_def, value)
        value = self._clamp_value(var_def, value)
        self.state.set_mutable_variable(var_def.label, value, node_id)
        log.info("set_variable %r[%s] = %r", var_def.label, node_id or 'global', value)

    def _increment_variable(self, var_def: MutableVariableDef, amount, node_id: str = '') -> None:
        current = self.state.get_mutable_variable(var_def.label, node_id)
        if current is None:
            current = var_def.initial
        new_value = self._clamp_value(var_def, current + amount)
        self.state.set_mutable_variable(var_def.label, new_value, node_id)
        log.info("increment_variable %r[%s] %+g → %r", var_def.label, node_id or 'global', amount, new_value)

    def _coerce_value(self, var_def: MutableVariableDef, value):
        if var_def.type == "integer":
            return int(value)
        elif var_def.type == "float":
            return float(value)
        return str(value)

    def _clamp_value(self, var_def: MutableVariableDef, value):
        if var_def.min is not None:
            value = max(var_def.min, value)
        if var_def.max is not None:
            value = min(var_def.max, value)
        return value

    @staticmethod
    def _apply_random_n(items: list, target) -> list:
        n = getattr(target, "random_n", None)
        if n is not None and len(items) > n:
            return random.sample(items, n)
        return items

    def _resolve_node_targets(
        self, target, triggering_node_id: str | None,
        triggering_waypoint_id: int | None = None,
    ) -> list[str]:
        located = self.state.get_all_located_nodes()

        if isinstance(target, TargetTriggeringNode):
            return [triggering_node_id] if triggering_node_id else []

        if isinstance(target, TargetNode):
            node_def = self._get_node_def(target.node_label)
            return [node_def.node_id] if node_def else []

        if isinstance(target, TargetAllInZone):
            zone = self._get_zone(target.zone_label)
            result = geo.nodes_in_zone(zone, located) if zone else []
            return self._apply_random_n(result, target)

        if isinstance(target, (TargetFlag, TargetAllWithFlag)):
            result = self.state.get_nodes_with_flag(target.flag_label)
            return self._apply_random_n(result, target)

        if isinstance(target, (TargetWaypointRadius, TargetAllNearWaypoint)):
            waypoint = self._get_waypoint(target.waypoint_label)
            result = geo.nodes_near_waypoint(waypoint, target.meters, located) if waypoint else []
            return self._apply_random_n(result, target)

        if isinstance(target, TargetAllNearTriggeringWaypoint):
            if triggering_waypoint_id is None:
                log.warning("to_all_near_triggering_waypoint: no triggering waypoint in context; skipping")
                return []
            loc = self.state.get_dynamic_waypoint_location(triggering_waypoint_id)
            if loc is None:
                log.warning("to_all_near_triggering_waypoint: waypoint %d not found; skipping",
                            triggering_waypoint_id)
                return []
            result = [nid for nid, nloc in located.items()
                      if geo.haversine(*nloc, *loc) <= target.meters]
            return self._apply_random_n(result, target)

        if isinstance(target, TargetAllNearNode):
            node_def = self._get_node_def(target.node_label)
            if node_def is None:
                return []
            result = geo.nodes_near_node(node_def.node_id, target.meters, located)
            return self._apply_random_n(result, target)

        if isinstance(target, TargetGroup):
            result = self.state.get_group_members(target.group_label)
            return self._apply_random_n(result, target)

        return []

    def _resolve_flag_targets(
        self, target, triggering_node_id: str | None,
        triggering_waypoint_id: int | None = None,
    ) -> list[tuple[str, str]]:
        """Returns list of (kind, target_label) pairs for state.add/remove_flag."""
        located = self.state.get_all_located_nodes()

        if isinstance(target, TargetTriggeringNode):
            if triggering_node_id:
                return [("node", triggering_node_id)]

        elif isinstance(target, TargetNode):
            node_def = self._get_node_def(target.node_label)
            if node_def:
                return [("node", node_def.node_id)]

        elif isinstance(target, TargetZone):
            return [("zone", target.zone_label)]

        elif isinstance(target, TargetAllInZone):
            zone = self._get_zone(target.zone_label)
            result = [("node", nid) for nid in geo.nodes_in_zone(zone, located)] if zone else []
            return self._apply_random_n(result, target)

        elif isinstance(target, (TargetFlag, TargetAllWithFlag)):
            result = [("node", nid) for nid in self.state.get_nodes_with_flag(target.flag_label)]
            return self._apply_random_n(result, target)

        elif isinstance(target, TargetWaypointRadius):
            return [("waypoint", target.waypoint_label)]

        elif isinstance(target, TargetAllNearWaypoint):
            wp = self._get_waypoint(target.waypoint_label)
            result = [("node", nid) for nid in geo.nodes_near_waypoint(wp, target.meters, located)] if wp else []
            return self._apply_random_n(result, target)

        elif isinstance(target, TargetAllNearTriggeringWaypoint):
            if triggering_waypoint_id is None:
                log.warning("to_all_near_triggering_waypoint: no triggering waypoint in context; skipping")
                return []
            loc = self.state.get_dynamic_waypoint_location(triggering_waypoint_id)
            if loc is None:
                log.warning("to_all_near_triggering_waypoint: waypoint %d not found; skipping",
                            triggering_waypoint_id)
                return []
            result = [("node", nid) for nid, nloc in located.items()
                      if geo.haversine(*nloc, *loc) <= target.meters]
            return self._apply_random_n(result, target)

        elif isinstance(target, TargetAllNearNode):
            node_def = self._get_node_def(target.node_label)
            if node_def:
                result = [("node", nid) for nid in geo.nodes_near_node(node_def.node_id, target.meters, located)]
                return self._apply_random_n(result, target)

        elif isinstance(target, TargetGroup):
            kind = self._group_kind.get(target.group_label, "node")
            result = [(kind, m) for m in self.state.get_group_members(target.group_label)]
            return self._apply_random_n(result, target)

        return []

    # ------------------------------------------------------------------
    # Meshtastic send helpers
    # ------------------------------------------------------------------

    def _send_dm(self, node_id: str, text: str) -> None:
        if self._suppress_messages:
            return
        try:
            dest = int(node_id.lstrip("!"), 16)
        except ValueError:
            log.warning("Invalid node_id for DM: %r", node_id)
            return
        for chunk in _split_message(text):
            def _fn(c=chunk, d=dest):
                self.interface.sendText(c, destinationId=d, channelIndex=0)
                log.info("DM → %s: %r", node_id, c[:60])
            self._send_queue.put(_fn)

    def _send_alert(self, node_id: str, text: str) -> None:
        if self._suppress_messages:
            return
        try:
            dest = int(node_id.lstrip("!"), 16)
        except ValueError:
            log.warning("Invalid node_id for alert: %r", node_id)
            return
        from meshtastic import mesh_pb2, portnums_pb2
        for chunk in _split_message(text):
            def _fn(c=chunk, d=dest):
                self.interface.sendData(
                    c.encode("utf-8"),
                    destinationId=d,
                    portNum=portnums_pb2.PortNum.TEXT_MESSAGE_APP,
                    channelIndex=0,
                    priority=mesh_pb2.MeshPacket.Priority.ALERT,
                )
                log.info("Alert → %s: %r", node_id, c[:60])
            self._send_queue.put(_fn)

    def _send_alert_channel(self, channel_label: str, text: str) -> None:
        if self._suppress_messages:
            return
        idx = self.channel_index_map.get(channel_label)
        if idx is None:
            log.warning("Channel %r not mapped to a device index", channel_label)
            return
        from meshtastic import mesh_pb2, portnums_pb2
        for chunk in _split_message(text):
            def _fn(c=chunk, i=idx):
                self.interface.sendData(
                    c.encode("utf-8"),
                    portNum=portnums_pb2.PortNum.TEXT_MESSAGE_APP,
                    channelIndex=i,
                    priority=mesh_pb2.MeshPacket.Priority.ALERT,
                )
                log.info("Alert channel[%d] broadcast: %r", i, c[:60])
            self._send_queue.put(_fn)

    def _resolve_channel_index(self, channel_label: str) -> int | None:
        return self.channel_index_map.get(channel_label)

    def _send_channel(self, channel_label: str, text: str) -> None:
        if self._suppress_messages:
            return
        idx = self.channel_index_map.get(channel_label)
        if idx is None:
            log.warning("Channel %r not mapped to a device index", channel_label)
            return
        for chunk in _split_message(text):
            def _fn(c=chunk, i=idx):
                self.interface.sendText(c, channelIndex=i)
                log.info("Channel[%d] broadcast: %r", i, c[:60])
            self._send_queue.put(_fn)

    def _request_location(self, node_id: str) -> None:
        try:
            dest = int(node_id.lstrip("!"), 16)
        except ValueError:
            log.warning("Invalid node_id for location request: %r", node_id)
            return
        def _fn(d=dest):
            from meshtastic import portnums_pb2
            self.interface.sendData(
                data=b"",
                destinationId=d,
                portNum=portnums_pb2.PortNum.POSITION_APP,
                wantResponse=True,
            )
            log.info("Location request → %s", node_id)
        self._send_queue.put(_fn)

    def _request_telemetry(self, node_id: str) -> None:
        try:
            dest = int(node_id.lstrip("!"), 16)
        except ValueError:
            log.warning("Invalid node_id for telemetry request: %r", node_id)
            return
        def _fn(d=dest):
            from meshtastic import portnums_pb2
            from meshtastic.protobuf import telemetry_pb2
            r = telemetry_pb2.Telemetry()
            r.device_metrics.CopyFrom(telemetry_pb2.DeviceMetrics())
            self.interface.sendData(
                data=r,
                destinationId=d,
                portNum=portnums_pb2.PortNum.TELEMETRY_APP,
                wantResponse=True,
            )
            log.info("Telemetry request → %s", node_id)
        self._send_queue.put(_fn)

    # ------------------------------------------------------------------
    # Config lookups
    # ------------------------------------------------------------------

    def _interpolate(
        self, text: str, triggering_node_id: str | None,
        triggering_zone: str | None = None,
        extra_tokens: dict[str, str] | None = None,
    ) -> str:
        def replace(m: re.Match) -> str:
            label = m.group(1)
            if extra_tokens and label in extra_tokens:
                return extra_tokens[label]
            if label == "node_id":
                return triggering_node_id or "[unknown]"
            if label == "node_shortname":
                if triggering_node_id is None:
                    return "[unknown]"
                info = (self.interface.nodes or {}).get(triggering_node_id, {})
                return info.get("user", {}).get("shortName", "").strip() or triggering_node_id
            if label == "node_longname":
                if triggering_node_id is None:
                    return "[unknown]"
                info = (self.interface.nodes or {}).get(triggering_node_id, {})
                return info.get("user", {}).get("longName", "").strip() or triggering_node_id
            if label == "zone":
                return triggering_zone or "[unknown]"
            var = self._get_variable(label)
            if var is not None:
                return self._resolve_variable(var, triggering_node_id)
            mv_def = self._mutable_var_defs.get(label)
            if mv_def is not None:
                return self._resolve_mutable_variable(mv_def, triggering_node_id)
            log.warning("Unknown variable %r referenced in message", label)
            return "[unknown]"
        return _VAR_RE.sub(replace, text)

    def _resolve_variable(self, var: Variable, triggering_node_id: str | None) -> str:
        located = self.state.get_all_located_nodes()

        if var.tracks == "static":
            return var.value or ""

        if var.tracks == "node_count":
            zone = self._get_zone(var.target)
            return str(len(geo.nodes_in_zone(zone, located))) if zone else "[unknown]"

        if var.tracks == "event_trigger_count":
            if var.scope == "node":
                if triggering_node_id is None:
                    return "[no node context]"
                times, _ = self.state.get_node_event_state(var.event, triggering_node_id)
            else:
                times, _ = self.state.get_event_state(var.event)
            return str(times)

        if var.tracks == "flag_count":
            return str(len(self.state.get_nodes_with_flag(var.target)))

        if var.tracks == "group_count":
            return str(len(self.state.get_group_members(var.target)))

        if var.tracks == "waypoint_node_count":
            wp = self._get_waypoint(var.target)
            return str(len(geo.nodes_near_waypoint(wp, var.meters, located))) if wp else "[unknown]"

        if var.tracks == "distance_to_waypoint":
            if triggering_node_id is None:
                return "[no node context]"
            node_loc = located.get(triggering_node_id)
            wp = self._get_waypoint(var.target)
            if node_loc is None or wp is None:
                return "[unknown]"
            return str(round(geo.haversine(*node_loc, wp.lat, wp.lon)))

        if var.tracks in ("bearing_to_waypoint", "cardinal_to_waypoint"):
            if triggering_node_id is None:
                return "[no node context]"
            node_loc = located.get(triggering_node_id)
            wp = self._get_waypoint(var.target)
            if node_loc is None or wp is None:
                return "[unknown]"
            deg = geo.bearing(*node_loc, wp.lat, wp.lon)
            if var.tracks == "bearing_to_waypoint":
                return f"{round(deg)}°"
            return geo.bearing_to_cardinal(deg)

        if var.tracks == "seconds_since_last_update":
            if triggering_node_id is None:
                return "[no node context]"
            updated_at = self.state.get_node_location_updated_at(triggering_node_id)
            if updated_at is None:
                return "[unknown]"
            from datetime import datetime, timezone
            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)
            return str(int(elapsed.total_seconds()))

        if var.tracks == "current_position":
            if triggering_node_id is None:
                return "[no node context]"
            loc = located.get(triggering_node_id)
            if loc is None:
                return "[unknown]"
            return f"{loc[0]:.5f}, {loc[1]:.5f}"

        if var.tracks == "prev_position":
            if triggering_node_id is None:
                return "[no node context]"
            loc = self.state.get_prev_node_location(triggering_node_id)
            if loc is None:
                return "[unknown]"
            return f"{loc[0]:.5f}, {loc[1]:.5f}"

        if var.tracks == "prev_distance_to_waypoint":
            if triggering_node_id is None:
                return "[no node context]"
            prev_loc = self.state.get_prev_node_location(triggering_node_id)
            wp = self._get_waypoint(var.target)
            if prev_loc is None or wp is None:
                return "[unknown]"
            return str(round(geo.haversine(*prev_loc, wp.lat, wp.lon)))

        if var.tracks == "distance_change_to_waypoint":
            if triggering_node_id is None:
                return "[no node context]"
            curr_loc = located.get(triggering_node_id)
            prev_loc = self.state.get_prev_node_location(triggering_node_id)
            wp = self._get_waypoint(var.target)
            if curr_loc is None or prev_loc is None or wp is None:
                return "[unknown]"
            curr_dist = geo.haversine(*curr_loc, wp.lat, wp.lon)
            prev_dist = geo.haversine(*prev_loc, wp.lat, wp.lon)
            return str(round(curr_dist - prev_dist, 1))

        if var.tracks == "distance_to_zone":
            if triggering_node_id is None:
                return "[no node context]"
            node_loc = located.get(triggering_node_id)
            zone = self._get_zone(var.target)
            if node_loc is None or zone is None:
                return "[unknown]"
            if var.zone_measure == "border":
                dist = geo.distance_to_triangle_border(node_loc, *zone.points)
            else:
                clat, clon = geo.zone_centroid(zone)
                dist = geo.haversine(*node_loc, clat, clon)
            return str(round(dist))

        if var.tracks == "distance_to_node":
            node_def = self._get_node_def(var.node)
            if node_def is None:
                return "[unknown]"
            target_loc = located.get(node_def.node_id)
            if target_loc is None:
                return "[unknown]"
            if var.scope == "zone":
                zone = self._get_zone(var.target)
                if zone is None:
                    return "[unknown]"
                ref = geo.zone_centroid(zone)
            else:
                wp = self._get_waypoint(var.target)
                if wp is None:
                    return "[unknown]"
                ref = (wp.lat, wp.lon)
            return str(round(geo.haversine(*ref, *target_loc)))

        if var.tracks in (
            "node_battery_level", "node_voltage", "node_channel_utilization",
            "node_air_util_tx", "node_uptime_seconds", "node_snr",
            "node_hops_away", "node_hw_model", "node_role",
        ):
            if triggering_node_id is None:
                return "[no node context]"
            node_info = (self.interface.nodes or {}).get(triggering_node_id, {})
            if var.tracks == "node_battery_level":
                val = node_info.get("deviceMetrics", {}).get("batteryLevel")
                return str(val) if val is not None else "[unknown]"
            if var.tracks == "node_voltage":
                val = node_info.get("deviceMetrics", {}).get("voltage")
                return f"{val:.2f}" if val is not None else "[unknown]"
            if var.tracks == "node_channel_utilization":
                val = node_info.get("deviceMetrics", {}).get("channelUtilization")
                return f"{val:.1f}" if val is not None else "[unknown]"
            if var.tracks == "node_air_util_tx":
                val = node_info.get("deviceMetrics", {}).get("airUtilTx")
                return f"{val:.1f}" if val is not None else "[unknown]"
            if var.tracks == "node_uptime_seconds":
                val = node_info.get("deviceMetrics", {}).get("uptimeSeconds")
                return str(val) if val is not None else "[unknown]"
            if var.tracks == "node_snr":
                val = node_info.get("snr")
                return f"{val:.2f}" if val is not None else "[unknown]"
            if var.tracks == "node_hops_away":
                val = node_info.get("hopsAway")
                return str(val) if val is not None else "[unknown]"
            if var.tracks == "node_hw_model":
                return node_info.get("user", {}).get("hwModel", "[unknown]")
            if var.tracks == "node_role":
                return node_info.get("user", {}).get("role", "[unknown]")

        if var.tracks in ("nearest_node_distance", "nearest_node_name"):
            excluded = set(self.state.get_nodes_with_flag(var.exclude_flag)) if var.exclude_flag else set()
            if var.scope == "zone":
                zone = self._get_zone(var.target)
                if zone is None:
                    return "[unknown]"
                ref = geo.zone_centroid(zone)
            else:
                wp = self._get_waypoint(var.target)
                if wp is None:
                    return "[unknown]"
                ref = (wp.lat, wp.lon)
            candidates = {nid: loc for nid, loc in located.items() if nid not in excluded}
            if not candidates:
                return "[no nodes]"
            nearest_id, nearest_loc = min(
                candidates.items(), key=lambda x: geo.haversine(*ref, *x[1])
            )
            if var.tracks == "nearest_node_distance":
                return str(round(geo.haversine(*ref, *nearest_loc)))
            node_info = (self.interface.nodes or {}).get(nearest_id, {})
            name = node_info.get("user", {}).get("shortName", "").strip()
            return name or nearest_id

        return "[unknown]"

    def _resolve_mutable_variable(self, var_def: MutableVariableDef, triggering_node_id: str | None) -> str:
        if var_def.scope == "node":
            if triggering_node_id is None:
                return "[no node context]"
            raw = self.state.get_mutable_variable(var_def.label, triggering_node_id)
        else:
            raw = self.state.get_mutable_variable(var_def.label)
        if raw is None:
            raw = var_def.initial
        result = str(raw)
        # initial: "" means "use node_id as display fallback" — never show a blank name
        if not result and var_def.scope == "node" and triggering_node_id is not None:
            return triggering_node_id
        return result

    def _get_variable(self, label: str) -> Variable | None:
        return next((v for v in self.config.variables if v.label == label), None)

    def _get_zone(self, label: str):
        return next((z for z in self.config.zones if z.label == label), None)

    def _get_waypoint(self, label: str):
        return next((w for w in self.config.waypoints if w.label == label), None)

    def _get_message(self, label: str):
        return next((m for m in self.config.messages if m.label == label), None)

    def _get_flag_def(self, label: str):
        return next((f for f in self.config.flags if f.label == label), None)

    def _get_node_def(self, label: str):
        return next((n for n in self.config.nodes if n.label == label), None)
