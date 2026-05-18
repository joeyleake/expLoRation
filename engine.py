"""Event trigger evaluation and response execution for expLoRation."""
from __future__ import annotations
import logging
import queue
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from config import (
    GameConfig, Event, Variable, MutableVariableDef,
    ProximityTrigger, TimedTrigger, CommandTrigger, VariableThresholdTrigger,
    SendMessageResponse, AddFlagResponse, RemoveFlagResponse,
    RequestLocationResponse, SetEventTriggersResponse,
    DisableEventResponse, EnableEventResponse,
    AddToGroupResponse, RemoveFromGroupResponse,
    SetVariableResponse, IncrementVariableResponse,
    RandomOptionsResponse,
    TargetTriggeringNode, TargetNode, TargetZone, TargetFlag,
    TargetWaypointRadius, TargetAllInZone, TargetAllWithFlag,
    TargetAllNearWaypoint, TargetAllNearNode, TargetChannel, TargetGroup,
    EventException,
)
from state import GameState
import geometry as geo

log = logging.getLogger(__name__)

_MAX_MSG_BYTES = 200
_VAR_RE = re.compile(r'\{(\w+)\}')


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


@dataclass
class MessageContext:
    node_id: str
    text: str
    is_dm: bool
    channel_idx: int


@dataclass
class PeriodicContext:
    pass


Context = NodeContext | MessageContext | PeriodicContext


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Engine:
    def __init__(self, config: GameConfig, state: GameState, interface: Any, send_delay: float = 1.5):
        self.config = config
        self.state = state
        self.interface = interface
        self.send_delay = send_delay
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
        self.state.expire_flags()

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
                if var_def and var_def.scope == "node":
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

    def handle_message(
        self, node_id: str, text: str, is_dm: bool, channel_idx: int
    ) -> None:
        self.state.expire_flags()
        ctx = MessageContext(node_id, text, is_dm, channel_idx)
        for event in self.config.events:
            if isinstance(event.trigger, CommandTrigger):
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)

    def handle_periodic(self) -> None:
        self.state.expire_flags()
        ctx = PeriodicContext()
        for event in self.config.events:
            if isinstance(event.trigger, TimedTrigger):
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)
            elif (
                isinstance(event.trigger, ProximityTrigger)
                and event.trigger.kind == "in_zone_on_start"
            ):
                if self._should_fire(event, ctx):
                    self._fire_event(event, ctx)

            if event.auto_recur and event.recur_mins is not None:
                self._maybe_auto_recur(event)

        for event in self.config.events:
            if isinstance(event.trigger, VariableThresholdTrigger):
                var_def = self._mutable_var_defs.get(event.trigger.variable_label)
                if var_def and var_def.scope == "global":
                    if self._should_fire(event, ctx):
                        self._fire_event(event, ctx)

    # ------------------------------------------------------------------
    # Trigger evaluation
    # ------------------------------------------------------------------

    def _should_fire(self, event: Event, ctx: Context) -> bool:
        if self.state.is_event_disabled(event.label):
            return False

        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext)) else None
        if event.trigger_per_node and node_id is not None:
            times, last = self.state.get_node_event_state(event.label, node_id)
        else:
            times, last = self.state.get_event_state(event.label)

        if event.max_triggers is not None and times >= event.max_triggers:
            return False

        if event.reset_mins is not None and last is not None:
            cutoff = last + timedelta(minutes=event.reset_mins)
            if datetime.now(timezone.utc) < cutoff:
                return False

        if not self._check_trigger(event, ctx):
            return False

        if self._check_exceptions(event, ctx):
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
                waypoint = self._get_waypoint(t.target_label)
                if waypoint is None:
                    return False
                node_loc = located.get(ctx.node_id)
                if node_loc is None:
                    return False
                return geo.haversine(*node_loc, waypoint.lat, waypoint.lon) <= t.meters

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
            if ctx.text.strip() != message.text.strip():
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
            return True

        elif isinstance(t, VariableThresholdTrigger):
            var_def = self._mutable_var_defs.get(t.variable_label)
            if var_def is None:
                return False
            if var_def.scope == "node":
                if not isinstance(ctx, (NodeContext, MessageContext)):
                    return False
                raw = self.state.get_mutable_variable(t.variable_label, ctx.node_id)
            else:
                raw = self.state.get_mutable_variable(t.variable_label)
            if raw is None:
                raw = var_def.initial
            return self._evaluate_threshold(raw, t.operator, t.value)

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

    def _check_exceptions(self, event: Event, ctx: Context) -> bool:
        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext)) else None
        # Evaluate deterministic exceptions first
        for exc in event.exceptions:
            if exc.kind == "random_skip":
                continue
            if self._exception_matches(exc, node_id):
                return True
        # Roll random_skip only if all deterministic exceptions passed
        for exc in event.exceptions:
            if exc.kind == "random_skip" and self._exception_matches(exc, node_id):
                return True
        return False

    def _exception_matches(self, exc: EventException, node_id: str | None) -> bool:
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
            if exc.target is None:
                return False
            has = self.state.has_flag("waypoint", exc.target, exc.flag)
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

    def _fire_event(self, event: Event, ctx: Context) -> None:
        log.info("Firing event %r (ctx=%s)", event.label, ctx)
        for resp in event.responses:
            try:
                self._execute_response(resp, ctx)
            except Exception:
                log.exception("Error executing response in event %r", event.label)
        self.state.increment_event_triggers(event.label)
        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext)) else None
        if event.trigger_per_node and node_id is not None:
            self.state.increment_node_event_triggers(event.label, node_id)

    def _execute_response(self, resp, ctx: Context) -> None:
        node_id = ctx.node_id if isinstance(ctx, (NodeContext, MessageContext)) else None

        if isinstance(resp, SendMessageResponse):
            message = self._get_message(resp.message_label)
            if message is None:
                return
            text = self._interpolate(message.text, node_id)
            if isinstance(resp.target, TargetChannel):
                self._send_channel(resp.target.channel_label, text)
            else:
                nodes = self._resolve_node_targets(resp.target, node_id)
                for nid in nodes:
                    self._send_dm(nid, text)

        elif isinstance(resp, (AddFlagResponse, RemoveFlagResponse)):
            adding = isinstance(resp, AddFlagResponse)
            flag_def = self._get_flag_def(resp.flag_label)
            expiry_mins = flag_def.expiry_mins if flag_def else None
            targets = self._resolve_flag_targets(resp.target, node_id)
            for kind, target in targets:
                if adding:
                    self.state.add_flag(kind, target, resp.flag_label, expiry_mins=expiry_mins)
                    log.info("Added flag %r to %s %r", resp.flag_label, kind, target)
                else:
                    self.state.remove_flag(kind, target, resp.flag_label)
                    log.info("Removed flag %r from %s %r", resp.flag_label, kind, target)

        elif isinstance(resp, RequestLocationResponse):
            nodes = self._resolve_node_targets(resp.target, node_id)
            for nid in nodes:
                self._request_location(nid)

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
                members = self._resolve_node_targets(resp.target, node_id)
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
                for nid in self._resolve_node_targets(resp.target, node_id):
                    self._set_variable(var_def, resp.value, nid)
            else:
                self._set_variable(var_def, resp.value)

        elif isinstance(resp, IncrementVariableResponse):
            var_def = self._mutable_var_defs.get(resp.variable_label)
            if var_def is None:
                return
            if var_def.scope == "node":
                for nid in self._resolve_node_targets(resp.target, node_id):
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

    def _resolve_node_targets(self, target, triggering_node_id: str | None) -> list[str]:
        located = self.state.get_all_located_nodes()

        if isinstance(target, TargetTriggeringNode):
            return [triggering_node_id] if triggering_node_id else []

        if isinstance(target, TargetNode):
            node_def = self._get_node_def(target.node_label)
            return [node_def.node_id] if node_def else []

        if isinstance(target, TargetAllInZone):
            zone = self._get_zone(target.zone_label)
            return geo.nodes_in_zone(zone, located) if zone else []

        if isinstance(target, (TargetFlag, TargetAllWithFlag)):
            fl = target.flag_label if isinstance(target, TargetAllWithFlag) else target.flag_label
            return self.state.get_nodes_with_flag(fl)

        if isinstance(target, (TargetWaypointRadius, TargetAllNearWaypoint)):
            wp_label = target.waypoint_label
            waypoint = self._get_waypoint(wp_label)
            return geo.nodes_near_waypoint(waypoint, target.meters, located) if waypoint else []

        if isinstance(target, TargetAllNearNode):
            node_def = self._get_node_def(target.node_label)
            if node_def is None:
                return []
            return geo.nodes_near_node(node_def.node_id, target.meters, located)

        if isinstance(target, TargetGroup):
            # Only valid for node-kind groups
            return self.state.get_group_members(target.group_label)

        return []

    def _resolve_flag_targets(self, target, triggering_node_id: str | None) -> list[tuple[str, str]]:
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
            if zone:
                return [("node", nid) for nid in geo.nodes_in_zone(zone, located)]

        elif isinstance(target, (TargetFlag, TargetAllWithFlag)):
            fl = target.flag_label
            return [("node", nid) for nid in self.state.get_nodes_with_flag(fl)]

        elif isinstance(target, TargetWaypointRadius):
            return [("waypoint", target.waypoint_label)]

        elif isinstance(target, TargetAllNearWaypoint):
            wp = self._get_waypoint(target.waypoint_label)
            if wp:
                return [("node", nid) for nid in geo.nodes_near_waypoint(wp, target.meters, located)]

        elif isinstance(target, TargetAllNearNode):
            node_def = self._get_node_def(target.node_label)
            if node_def:
                nearby = geo.nodes_near_node(node_def.node_id, target.meters, located)
                return [("node", nid) for nid in nearby]

        elif isinstance(target, TargetGroup):
            kind = self._group_kind.get(target.group_label, "node")
            return [(kind, m) for m in self.state.get_group_members(target.group_label)]

        return []

    # ------------------------------------------------------------------
    # Meshtastic send helpers
    # ------------------------------------------------------------------

    def _send_dm(self, node_id: str, text: str) -> None:
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

    def _send_channel(self, channel_label: str, text: str) -> None:
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
            self.interface.sendText("", destinationId=d, wantResponse=True)
            log.info("Location request → %s", node_id)
        self._send_queue.put(_fn)

    # ------------------------------------------------------------------
    # Config lookups
    # ------------------------------------------------------------------

    def _interpolate(self, text: str, triggering_node_id: str | None) -> str:
        def replace(m: re.Match) -> str:
            label = m.group(1)
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
        return str(raw)

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
