"""YAML config loading, dataclasses, and validation for expLoRation."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import yaml


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------
# Game objects
# ---------------------------------------------------------------------------

@dataclass
class Channel:
    label: str
    name: str
    psk: str
    monitor: bool = True
    participate: bool = False


@dataclass
class Zone:
    label: str
    points: list[tuple[float, float]]  # exactly 3 (lat, lon) pairs


@dataclass
class Waypoint:
    label: str
    lat: float
    lon: float


@dataclass
class Message:
    label: str
    text: str


@dataclass
class FlagDef:
    label: str
    expiry_mins: float | None = None


@dataclass
class NodeDef:
    label: str
    node_id: str          # e.g. "!ab12cd34"
    initial_flags: list[str] = field(default_factory=list)


@dataclass
class GroupDef:
    label: str
    kind: str             # "node" | "zone" | "waypoint"
    initial_members: list[str] = field(default_factory=list)


@dataclass
class MutableVariableDef:
    label: str
    type: str               # "integer" | "float" | "string"
    scope: str              # "global" | "node"
    initial: int | float | str
    min: int | float | None = None
    max: int | float | None = None
    max_length: int | None = None  # string type only; hard cap of 200 always applies


@dataclass
class Variable:
    label: str
    scope: str            # global | node | zone | waypoint | event
    tracks: str           # static | node_count | event_trigger_count | flag_count |
                          # waypoint_node_count | distance_to_waypoint | distance_to_zone |
                          # distance_to_node | nearest_node_distance | nearest_node_name |
                          # node_battery_level | node_voltage | node_channel_utilization |
                          # node_air_util_tx | node_uptime_seconds | node_snr |
                          # node_hops_away | node_hw_model | node_role
    target: str | None = None        # zone/waypoint/event/flag label (tracks-dependent)
    value: str | None = None         # required for tracks: static
    event: str | None = None         # required for tracks: event_trigger_count
    meters: float | None = None      # required for tracks: waypoint_node_count
    zone_measure: str | None = None  # centroid | border — for distance_to_zone
    node: str | None = None          # node label — for distance_to_node
    exclude_flag: str | None = None  # for nearest_node_distance / nearest_node_name


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------

@dataclass
class ProximityTrigger:
    kind: str             # near_waypoint | near_zone | near_node | in_zone_on_start |
                          # in_zone | enters_zone | leaves_zone |
                          # enters_zone_group | leaves_zone_group | in_zone_group | in_zone_group_on_start
    target_label: str | None = None
    target_flag: str | None = None  # near_waypoint only: match any dynamic waypoint with this flag
    meters: float | None = None  # required for near_* kinds
    zone_group: str | None = None  # for *_zone_group trigger kinds


@dataclass
class TimedTrigger:
    start: datetime
    end: datetime



@dataclass
class CommandTrigger:
    kind: str             # dm | channel
    message_label: str
    zone_label: str | None = None
    zone_group: str | None = None   # mutually exclusive with zone_label
    channel_label: str | None = None  # required when kind == channel


@dataclass
class VariableThresholdTrigger:
    variable_label: str
    operator: str         # "lt" | "lte" | "eq" | "neq" | "gte" | "gt"
    value: int | float | str


@dataclass
class FlagExpiryTrigger:
    flag_label: str
    target_kind: str      # "node" | "zone" | "waypoint" | "dynamic_waypoint"


@dataclass
class WaypointExpiryTrigger:
    had_flag: str | None = None  # optional — only fire for waypoints that had this flag


@dataclass
class WaypointReceivedTrigger:
    from_flag: str | None = None       # only fire if sending node has this flag
    name_contains: str | None = None   # only fire if waypoint name contains this substring (case-insensitive)


# ---------------------------------------------------------------------------
# Response targets
# ---------------------------------------------------------------------------

@dataclass
class TargetTriggeringNode:
    pass


@dataclass
class TargetNode:
    node_label: str


@dataclass
class TargetZone:
    zone_label: str


@dataclass
class TargetFlag:
    flag_label: str


@dataclass
class TargetWaypointRadius:
    waypoint_label: str
    meters: float


@dataclass
class TargetAllInZone:
    zone_label: str
    random_n: int | None = None


@dataclass
class TargetAllWithFlag:
    flag_label: str
    random_n: int | None = None


@dataclass
class TargetAllNearWaypoint:
    waypoint_label: str
    meters: float
    random_n: int | None = None


@dataclass
class TargetAllNearNode:
    node_label: str
    meters: float
    random_n: int | None = None


@dataclass
class TargetChannel:
    channel_label: str


@dataclass
class TargetGroup:
    group_label: str
    random_n: int | None = None


@dataclass
class TargetAllNearTriggeringWaypoint:
    meters: float
    random_n: int | None = None


Target = (
    TargetTriggeringNode
    | TargetNode
    | TargetZone
    | TargetFlag
    | TargetWaypointRadius
    | TargetAllInZone
    | TargetAllWithFlag
    | TargetAllNearWaypoint
    | TargetAllNearTriggeringWaypoint
    | TargetAllNearNode
    | TargetChannel
    | TargetGroup
)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

@dataclass
class SendMessageResponse:
    message_label: str
    target: Target


@dataclass
class SendAlertResponse:
    message_label: str
    target: Target


@dataclass
class AddFlagResponse:
    flag_label: str
    target: Target


@dataclass
class RemoveFlagResponse:
    flag_label: str
    target: Target


@dataclass
class RequestLocationResponse:
    target: Target


@dataclass
class RequestTelemetryResponse:
    target: Target




@dataclass
class SetEventTriggersResponse:
    event_label: str
    value: int


@dataclass
class DisableEventResponse:
    event_label: str


@dataclass
class EnableEventResponse:
    event_label: str


@dataclass
class AddToGroupResponse:
    group_label: str
    target: Target


@dataclass
class RemoveFromGroupResponse:
    group_label: str
    target: Target


@dataclass
class SetVariableResponse:
    variable_label: str
    value: int | float | str
    target: Target | None = None


@dataclass
class IncrementVariableResponse:
    variable_label: str
    amount: int | float
    target: Target | None = None


@dataclass
class RandomOption:
    weight: float
    responses: list   # list[Response] — unparameterized to avoid forward-ref issues


@dataclass
class RandomOptionsResponse:
    options: list[RandomOption]


@dataclass
class WithNodeResponse:
    target: Target
    responses: list   # list[Response] — unparameterized to avoid forward-ref issues


@dataclass
class RepeatResponse:
    count: int
    responses: list   # list[Response]


@dataclass
class CreateWaypointResponse:
    expiry_mins: float | None = None
    initial_flags: list[str] = field(default_factory=list)
    randomly_in_zone: str | None = None            # place at a random point inside this zone
    randomly_in_zone_group: str | None = None      # pick a random zone from the group, then a random point
    # Optional: also push to the Meshtastic mesh map
    mesh_name: str | None = None
    mesh_description: str = ""
    mesh_icon: int = 0
    mesh_channel: str | None = None        # channel label — broadcast to channel
    mesh_to_triggering_node: bool = False  # DM to triggering node
    mesh_label: str | None = None          # store for label-based deletion later
    refresh_mins: float | None = None          # rebroadcast to mesh every N minutes
    refresh_cooldown_mins: float | None = None  # minimum gap between force_refresh_waypoint re-broadcasts


@dataclass
class AddDynamicWaypointFlagResponse:
    flag_label: str


@dataclass
class RemoveDynamicWaypointFlagResponse:
    flag_label: str


@dataclass
class DestroyWaypointResponse:
    pass


@dataclass
class BroadcastWaypointResponse:
    name: str
    target: "Target"
    description: str = ""
    icon: int = 0
    expiry_mins: float | None = None
    lat: float | None = None
    lon: float | None = None
    label: str | None = None


@dataclass
class DeleteMeshWaypointResponse:
    label: str | None = None
    use_triggering_waypoint: bool = False


@dataclass
class ForceRefreshWaypointResponse:
    flag_label: str | None = None
    max_meters: float | None = None


Response = (
    SendMessageResponse
    | SendAlertResponse
    | AddFlagResponse
    | RemoveFlagResponse
    | RequestLocationResponse
    | RequestTelemetryResponse
    | SetEventTriggersResponse
    | DisableEventResponse
    | EnableEventResponse
    | AddToGroupResponse
    | RemoveFromGroupResponse
    | SetVariableResponse
    | IncrementVariableResponse
    | RandomOptionsResponse
    | WithNodeResponse
    | RepeatResponse
    | CreateWaypointResponse
    | AddDynamicWaypointFlagResponse
    | RemoveDynamicWaypointFlagResponse
    | DestroyWaypointResponse
    | BroadcastWaypointResponse
    | DeleteMeshWaypointResponse
    | ForceRefreshWaypointResponse
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

@dataclass
class EventException:
    kind: str   # node_has_flag | node_lacks_flag | zone_has_flag | zone_lacks_flag |
                # waypoint_has_flag | waypoint_lacks_flag | random_skip |
                # node_in_group | node_not_in_group |
                # zone_in_group | zone_not_in_group |
                # waypoint_in_group | waypoint_not_in_group
    flag: str | None = None    # required for flag-check kinds
    target: str | None = None  # zone/waypoint label; also used for zone/waypoint_in_group checks
    chance: float | None = None  # required for random_skip; 0.0–1.0
    group: str | None = None   # required for *_in_group kinds


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@dataclass
class Event:
    label: str
    trigger: ProximityTrigger | TimedTrigger | CommandTrigger | VariableThresholdTrigger | FlagExpiryTrigger | WaypointExpiryTrigger | WaypointReceivedTrigger
    responses: list[Response]
    exceptions: list[EventException] = field(default_factory=list)
    max_triggers: int | None = None
    reset_mins: float | None = None
    disabled: bool = False
    trigger_per_node: bool = False
    auto_recur: bool = False
    recur_mins: float | None = None


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

@dataclass
class GameConfig:
    channels: list[Channel] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    flags: list[FlagDef] = field(default_factory=list)
    nodes: list[NodeDef] = field(default_factory=list)
    groups: list[GroupDef] = field(default_factory=list)
    variables: list[Variable] = field(default_factory=list)
    mutable_variables: list[MutableVariableDef] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_target(raw: dict) -> Target:
    if raw.get("to_triggering_node"):
        return TargetTriggeringNode()
    if "to_node" in raw:
        return TargetNode(raw["to_node"])
    if "to_zone" in raw:
        return TargetZone(raw["to_zone"])
    if "to_channel" in raw:
        return TargetChannel(raw["to_channel"])
    if "to_flag" in raw:
        return TargetFlag(raw["to_flag"])
    if "to_waypoint_radius" in raw:
        r = raw["to_waypoint_radius"]
        return TargetWaypointRadius(r["waypoint"], float(r["meters"]))
    if "to_all_in_zone" in raw:
        return TargetAllInZone(raw["to_all_in_zone"], random_n=raw.get("random_n"))
    if "to_all_with_flag" in raw:
        return TargetAllWithFlag(raw["to_all_with_flag"], random_n=raw.get("random_n"))
    if "to_all_near_waypoint" in raw:
        r = raw["to_all_near_waypoint"]
        return TargetAllNearWaypoint(r["waypoint"], float(r["meters"]), random_n=raw.get("random_n"))
    if "to_all_near_node" in raw:
        r = raw["to_all_near_node"]
        return TargetAllNearNode(r["node"], float(r["meters"]), random_n=raw.get("random_n"))
    if "to_all_near_triggering_waypoint" in raw:
        val = raw["to_all_near_triggering_waypoint"]
        meters = float(val["meters"]) if isinstance(val, dict) else float(val)
        return TargetAllNearTriggeringWaypoint(meters=meters, random_n=raw.get("random_n"))
    if "to_group" in raw:
        return TargetGroup(raw["to_group"], random_n=raw.get("random_n"))
    raise ConfigError(f"Unrecognised target in response: {raw}")


def _parse_response(raw: dict) -> Response:
    kind = raw.get("type")
    if kind == "send_message":
        return SendMessageResponse(raw["message_label"], _parse_target(raw))
    if kind == "send_alert":
        return SendAlertResponse(raw["message_label"], _parse_target(raw))
    if kind == "add_flag":
        return AddFlagResponse(raw["flag_label"], _parse_target(raw))
    if kind == "remove_flag":
        return RemoveFlagResponse(raw["flag_label"], _parse_target(raw))
    if kind == "request_location":
        return RequestLocationResponse(_parse_target(raw))
    if kind == "request_telemetry":
        return RequestTelemetryResponse(_parse_target(raw))
    if kind == "set_event_triggers":
        return SetEventTriggersResponse(raw["event_label"], int(raw["value"]))
    if kind == "disable_event":
        return DisableEventResponse(raw["event_label"])
    if kind == "enable_event":
        return EnableEventResponse(raw["event_label"])
    if kind == "add_to_group":
        return AddToGroupResponse(raw["group_label"], _parse_target(raw))
    if kind == "remove_from_group":
        return RemoveFromGroupResponse(raw["group_label"], _parse_target(raw))
    _TARGET_KEYS = frozenset({
        "to_triggering_node", "to_node", "to_zone", "to_channel", "to_flag",
        "to_waypoint_radius", "to_all_in_zone", "to_all_with_flag",
        "to_all_near_waypoint", "to_all_near_triggering_waypoint", "to_all_near_node", "to_group",
    })
    if kind == "set_variable":
        tgt = _parse_target(raw) if _TARGET_KEYS & raw.keys() else None
        return SetVariableResponse(variable_label=raw["variable_label"], value=raw["value"], target=tgt)
    if kind == "increment_variable":
        tgt = _parse_target(raw) if _TARGET_KEYS & raw.keys() else None
        return IncrementVariableResponse(variable_label=raw["variable_label"], amount=raw["amount"], target=tgt)
    if kind == "random_options":
        options = []
        for opt in raw.get("options", []):
            options.append(RandomOption(
                weight=float(opt["weight"]),
                responses=[_parse_response(r) for r in opt.get("responses", [])],
            ))
        return RandomOptionsResponse(options=options)
    if kind == "with_node":
        return WithNodeResponse(
            target=_parse_target(raw),
            responses=[_parse_response(r) for r in raw.get("responses", [])],
        )
    if kind == "repeat":
        if "count" not in raw:
            raise ConfigError("repeat response requires 'count'")
        return RepeatResponse(
            count=int(raw["count"]),
            responses=[_parse_response(r) for r in raw.get("responses", [])],
        )
    if kind == "create_waypoint":
        return CreateWaypointResponse(
            expiry_mins=float(raw["expiry_mins"]) if "expiry_mins" in raw else None,
            initial_flags=raw.get("initial_flags", []),
            randomly_in_zone=raw.get("randomly_in_zone"),
            randomly_in_zone_group=raw.get("randomly_in_zone_group"),
            mesh_name=raw.get("mesh_name"),
            mesh_description=raw.get("mesh_description", ""),
            mesh_icon=int(raw.get("mesh_icon", 0)),
            mesh_channel=raw.get("mesh_channel"),
            mesh_to_triggering_node=bool(raw.get("mesh_to_triggering_node", False)),
            mesh_label=raw.get("mesh_label"),
            refresh_mins=float(raw["refresh_mins"]) if "refresh_mins" in raw else None,
            refresh_cooldown_mins=float(raw["refresh_cooldown_mins"]) if "refresh_cooldown_mins" in raw else None,
        )
    if kind == "broadcast_waypoint":
        if "name" not in raw:
            raise ConfigError("broadcast_waypoint requires 'name'")
        return BroadcastWaypointResponse(
            name=raw["name"],
            target=_parse_target(raw),
            description=raw.get("description", ""),
            icon=int(raw.get("icon", 0)),
            expiry_mins=float(raw["expiry_mins"]) if "expiry_mins" in raw else None,
            lat=float(raw["lat"]) if "lat" in raw else None,
            lon=float(raw["lon"]) if "lon" in raw else None,
            label=raw.get("label"),
        )
    if kind == "delete_mesh_waypoint":
        return DeleteMeshWaypointResponse(
            label=raw.get("label"),
            use_triggering_waypoint=bool(raw.get("use_triggering_waypoint", False)),
        )
    if kind == "add_waypoint_flag":
        return AddDynamicWaypointFlagResponse(flag_label=raw["flag_label"])
    if kind == "remove_waypoint_flag":
        return RemoveDynamicWaypointFlagResponse(flag_label=raw["flag_label"])
    if kind == "destroy_waypoint":
        return DestroyWaypointResponse()
    if kind == "force_refresh_waypoint":
        return ForceRefreshWaypointResponse(
            flag_label=raw.get("flag_label"),
            max_meters=float(raw["max_meters"]) if "max_meters" in raw else None,
        )
    raise ConfigError(f"Unknown response type: {kind!r}")


def _parse_trigger(raw: dict):
    kind = raw.get("type")
    _ZONE_GROUP_KINDS = frozenset(
        ("enters_zone_group", "leaves_zone_group", "in_zone_group", "in_zone_group_on_start")
    )
    if kind in ("near_waypoint", "near_zone", "near_node", "in_zone_on_start", "in_zone", "enters_zone", "leaves_zone",
                "enters_zone_group", "leaves_zone_group", "in_zone_group", "in_zone_group_on_start"):
        is_group = kind in _ZONE_GROUP_KINDS
        return ProximityTrigger(
            kind=kind,
            target_label=None if is_group else raw.get("target"),
            target_flag=raw.get("target_flag"),
            meters=float(raw["meters"]) if "meters" in raw else None,
            zone_group=raw.get("target") if is_group else None,
        )
    if kind == "time_window":
        return TimedTrigger(
            start=datetime.fromisoformat(raw["start"]),
            end=datetime.fromisoformat(raw["end"]),
        )
    if kind in ("dm", "channel"):
        return CommandTrigger(
            kind=kind,
            message_label=raw["message_label"],
            zone_label=raw.get("zone_label"),
            zone_group=raw.get("zone_group"),
            channel_label=raw.get("channel_label"),
        )
    if kind == "variable_threshold":
        return VariableThresholdTrigger(
            variable_label=raw["variable"],
            operator=raw["operator"],
            value=raw["value"],
        )
    if kind == "flag_expired":
        return FlagExpiryTrigger(
            flag_label=raw["flag_label"],
            target_kind=raw["target_kind"],
        )
    if kind == "waypoint_expired":
        return WaypointExpiryTrigger(
            had_flag=raw.get("had_flag"),
        )
    if kind == "waypoint_received":
        return WaypointReceivedTrigger(
            from_flag=raw.get("from_flag"),
            name_contains=raw.get("name_contains"),
        )
    raise ConfigError(f"Unknown trigger type: {kind!r}")


def _parse_exception(raw: dict) -> EventException:
    return EventException(
        kind=raw["kind"],
        flag=raw.get("flag"),
        target=raw.get("target"),
        chance=float(raw["chance"]) if "chance" in raw else None,
        group=raw.get("group"),
    )


def _parse_variable(raw: dict) -> Variable:
    return Variable(
        label=raw["label"],
        scope=raw["scope"],
        tracks=raw["tracks"],
        target=raw.get("target"),
        value=str(raw["value"]) if "value" in raw else None,
        event=raw.get("event"),
        meters=float(raw["meters"]) if "meters" in raw else None,
        zone_measure=raw.get("zone_measure"),
        node=raw.get("node"),
        exclude_flag=raw.get("exclude_flag"),
    )


def _parse_event(raw: dict) -> Event:
    return Event(
        label=raw["label"],
        trigger=_parse_trigger(raw["trigger"]),
        responses=[_parse_response(r) for r in raw.get("responses", [])],
        exceptions=[_parse_exception(e) for e in raw.get("exceptions", [])],
        max_triggers=raw.get("max_triggers"),
        reset_mins=raw.get("reset_mins"),
        disabled=bool(raw.get("disabled", False)),
        trigger_per_node=bool(raw.get("trigger_per_node", False)),
        auto_recur=bool(raw.get("auto_recur", False)),
        recur_mins=float(raw["recur_mins"]) if "recur_mins" in raw else None,
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _check_label(label: str, pool: set, ctx: str) -> None:
    if label not in pool:
        raise ConfigError(f"{ctx}: label {label!r} not defined")


def _validate_response(
    resp,
    message_labels: set, flag_labels: set, event_labels: set,
    zone_labels: set, waypoint_labels: set, node_labels: set,
    channel_labels: set, group_labels: set,
    ctx: str,
) -> None:
    if isinstance(resp, (SendMessageResponse, SendAlertResponse)):
        _check_label(resp.message_label, message_labels, ctx)
    if isinstance(resp, (AddFlagResponse, RemoveFlagResponse)):
        _check_label(resp.flag_label, flag_labels, ctx)
    if isinstance(resp, (SetEventTriggersResponse, DisableEventResponse, EnableEventResponse)):
        _check_label(resp.event_label, event_labels, ctx)
    if isinstance(resp, (AddToGroupResponse, RemoveFromGroupResponse)):
        _check_label(resp.group_label, group_labels, ctx)
    target = getattr(resp, "target", None)
    if target is not None:
        _validate_target(target, zone_labels, waypoint_labels, flag_labels, node_labels,
                         channel_labels, group_labels, ctx)
    if isinstance(resp, RandomOptionsResponse):
        if len(resp.options) < 2:
            raise ConfigError(f"{ctx}: random_options must have at least 2 options")
        for i, opt in enumerate(resp.options):
            if opt.weight <= 0:
                raise ConfigError(f"{ctx}: random_options option[{i}] weight must be > 0")
            if not opt.responses:
                raise ConfigError(f"{ctx}: random_options option[{i}] has no responses")
            for nested_resp in opt.responses:
                _validate_response(
                    nested_resp, message_labels, flag_labels, event_labels,
                    zone_labels, waypoint_labels, node_labels, channel_labels, group_labels,
                    f"{ctx} random_options[{i}]",
                )
    if isinstance(resp, CreateWaypointResponse):
        if resp.expiry_mins is not None and resp.expiry_mins <= 0:
            raise ConfigError(f"{ctx}: create_waypoint expiry_mins must be positive")
        for flag_label in resp.initial_flags:
            _check_label(flag_label, flag_labels, f"{ctx} create_waypoint initial_flags")
    if isinstance(resp, (AddDynamicWaypointFlagResponse, RemoveDynamicWaypointFlagResponse)):
        _check_label(resp.flag_label, flag_labels, ctx)
    if isinstance(resp, WithNodeResponse):
        if isinstance(resp.target, TargetChannel):
            raise ConfigError(f"{ctx}: with_node target cannot be a channel")
        if not resp.responses:
            raise ConfigError(f"{ctx}: with_node must have at least one inner response")
        for i, inner in enumerate(resp.responses):
            if isinstance(inner, (DestroyWaypointResponse, AddDynamicWaypointFlagResponse,
                                  RemoveDynamicWaypointFlagResponse)):
                raise ConfigError(
                    f"{ctx} with_node[{i}]: {type(inner).__name__} is not valid inside "
                    f"with_node (no triggering waypoint context)"
                )
            inner_target = getattr(inner, "target", None)
            if isinstance(inner_target, TargetAllNearTriggeringWaypoint):
                raise ConfigError(
                    f"{ctx} with_node[{i}]: to_all_near_triggering_waypoint is not valid inside "
                    f"with_node (no triggering waypoint context)"
                )
            _validate_response(
                inner, message_labels, flag_labels, event_labels,
                zone_labels, waypoint_labels, node_labels, channel_labels, group_labels,
                f"{ctx} with_node[{i}]",
            )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_mutable_response(resp, mutable_var_def_map: dict, ctx: str) -> None:
    if isinstance(resp, SetVariableResponse):
        if resp.variable_label not in mutable_var_def_map:
            raise ConfigError(f"{ctx}: set_variable: {resp.variable_label!r} not in mutable_variables")
        mv = mutable_var_def_map[resp.variable_label]
        if mv.scope == "node" and resp.target is None:
            raise ConfigError(f"{ctx}: set_variable on node-scoped variable requires a target")
        if mv.scope == "global" and resp.target is not None:
            raise ConfigError(f"{ctx}: set_variable on global variable must not have a target")
    elif isinstance(resp, IncrementVariableResponse):
        if resp.variable_label not in mutable_var_def_map:
            raise ConfigError(f"{ctx}: increment_variable: {resp.variable_label!r} not in mutable_variables")
        mv = mutable_var_def_map[resp.variable_label]
        if mv.type == "string":
            raise ConfigError(f"{ctx}: increment_variable not valid for string-type variables")
        if mv.scope == "node" and resp.target is None:
            raise ConfigError(f"{ctx}: increment_variable on node-scoped variable requires a target")
        if mv.scope == "global" and resp.target is not None:
            raise ConfigError(f"{ctx}: increment_variable on global variable must not have a target")
    elif isinstance(resp, RandomOptionsResponse):
        for i, opt in enumerate(resp.options):
            for nested in opt.responses:
                _validate_mutable_response(nested, mutable_var_def_map, f"{ctx} random_options[{i}]")
    elif isinstance(resp, WithNodeResponse):
        for i, inner in enumerate(resp.responses):
            _validate_mutable_response(inner, mutable_var_def_map, f"{ctx} with_node[{i}]")


def _validate(cfg: GameConfig) -> None:
    channel_labels = {c.label for c in cfg.channels}
    zone_labels = {z.label for z in cfg.zones}
    waypoint_labels = {w.label for w in cfg.waypoints}
    message_labels = {m.label for m in cfg.messages}
    flag_labels = {f.label for f in cfg.flags}
    node_labels = {n.label for n in cfg.nodes}
    event_labels = {e.label for e in cfg.events}
    group_labels = {g.label for g in cfg.groups}
    group_kind = {g.label: g.kind for g in cfg.groups}
    mutable_var_labels = {mv.label for mv in cfg.mutable_variables}
    mutable_var_def_map = {mv.label: mv for mv in cfg.mutable_variables}

    variable_labels = {v.label for v in cfg.variables}
    for label in mutable_var_labels & variable_labels:
        raise ConfigError(f"Label {label!r} defined in both variables and mutable_variables")

    _MV_TYPES = ("integer", "float", "string")
    _MV_SCOPES = ("global", "node")
    for mv in cfg.mutable_variables:
        mvctx = f"MutableVariable {mv.label!r}"
        if mv.type not in _MV_TYPES:
            raise ConfigError(f"{mvctx}: type must be one of {_MV_TYPES}")
        if mv.scope not in _MV_SCOPES:
            raise ConfigError(f"{mvctx}: scope must be one of {_MV_SCOPES}")
        if mv.type == "string" and (mv.min is not None or mv.max is not None):
            raise ConfigError(f"{mvctx}: min/max not valid for string type")
        if mv.max_length is not None:
            if mv.type != "string":
                raise ConfigError(f"{mvctx}: max_length only valid for type: string")
            if not isinstance(mv.max_length, int) or isinstance(mv.max_length, bool) or mv.max_length < 1:
                raise ConfigError(f"{mvctx}: max_length must be a positive integer")
        if mv.type == "integer" and (not isinstance(mv.initial, int) or isinstance(mv.initial, bool)):
            raise ConfigError(f"{mvctx}: initial must be an integer")
        elif mv.type == "float" and (not isinstance(mv.initial, (int, float)) or isinstance(mv.initial, bool)):
            raise ConfigError(f"{mvctx}: initial must be numeric")
        if mv.min is not None and mv.max is not None and mv.min > mv.max:
            raise ConfigError(f"{mvctx}: min must be <= max")
        if mv.min is not None and mv.initial < mv.min:
            raise ConfigError(f"{mvctx}: initial must be >= min")
        if mv.max is not None and mv.initial > mv.max:
            raise ConfigError(f"{mvctx}: initial must be <= max")

    _GROUP_KINDS = ("node", "zone", "waypoint")
    _member_pool = {"node": node_labels, "zone": zone_labels, "waypoint": waypoint_labels}
    for grp in cfg.groups:
        if grp.kind not in _GROUP_KINDS:
            raise ConfigError(f"Group {grp.label!r}: kind must be one of {_GROUP_KINDS}")
        pool = _member_pool[grp.kind]
        for member in grp.initial_members:
            _check_label(member, pool, f"Group {grp.label!r} initial_members")

    for event in cfg.events:
        ctx = f"Event {event.label!r}"
        t = event.trigger

        if isinstance(t, ProximityTrigger):
            if t.kind == "near_waypoint":
                has_target = t.target_label is not None
                has_flag = t.target_flag is not None
                if has_target == has_flag:
                    raise ConfigError(f"{ctx} trigger near_waypoint requires exactly one of 'target' or 'target_flag'")
                if has_target:
                    _check_label(t.target_label, waypoint_labels, f"{ctx} trigger")
                else:
                    _check_label(t.target_flag, flag_labels, f"{ctx} trigger")
            else:
                if t.target_flag is not None:
                    raise ConfigError(f"{ctx} trigger: 'target_flag' is only valid on near_waypoint triggers")
                _ZONE_GROUP_KINDS = ("enters_zone_group", "leaves_zone_group", "in_zone_group", "in_zone_group_on_start")
                if t.kind in _ZONE_GROUP_KINDS:
                    if t.zone_group is None:
                        raise ConfigError(f"{ctx} trigger {t.kind!r} requires 'target'")
                    _check_label(t.zone_group, group_labels, f"{ctx} trigger")
                    if group_kind.get(t.zone_group) != "zone":
                        raise ConfigError(f"{ctx} trigger {t.kind!r}: group {t.zone_group!r} must be kind 'zone'")
                elif t.kind in ("near_zone", "in_zone_on_start", "in_zone", "enters_zone", "leaves_zone"):
                    if t.zone_group is not None:
                        raise ConfigError(f"{ctx} trigger {t.kind!r}: 'target' must be a zone label, not a group")
                    _check_label(t.target_label, zone_labels, f"{ctx} trigger")
                elif t.kind == "near_node":
                    _check_label(t.target_label, node_labels, f"{ctx} trigger")
            _NO_METERS_KINDS = ("in_zone_on_start", "in_zone", "enters_zone", "leaves_zone",
                                "enters_zone_group", "leaves_zone_group", "in_zone_group", "in_zone_group_on_start")
            if t.kind not in _NO_METERS_KINDS and t.meters is None:
                raise ConfigError(f"{ctx} trigger {t.kind!r} requires 'meters'")

        elif isinstance(t, CommandTrigger):
            _check_label(t.message_label, message_labels, f"{ctx} trigger")
            if t.zone_label is not None and t.zone_group is not None:
                raise ConfigError(f"{ctx} trigger: 'zone_label' and 'zone_group' are mutually exclusive")
            if t.zone_label is not None:
                _check_label(t.zone_label, zone_labels, f"{ctx} trigger")
            if t.zone_group is not None:
                _check_label(t.zone_group, group_labels, f"{ctx} trigger")
                if group_kind.get(t.zone_group) != "zone":
                    raise ConfigError(f"{ctx} trigger: zone_group {t.zone_group!r} must be kind 'zone'")
            if t.kind == "channel":
                if t.channel_label is None:
                    raise ConfigError(f"{ctx} channel trigger requires 'channel_label'")
                _check_label(t.channel_label, channel_labels, f"{ctx} trigger")

        elif isinstance(t, VariableThresholdTrigger):
            _THRESHOLD_OPS = ("lt", "lte", "eq", "neq", "gte", "gt")
            if t.variable_label not in mutable_var_labels and t.variable_label not in variable_labels:
                raise ConfigError(
                    f"{ctx} trigger: variable {t.variable_label!r} not in variables or mutable_variables"
                )
            if t.operator not in _THRESHOLD_OPS:
                raise ConfigError(f"{ctx} trigger: operator must be one of {_THRESHOLD_OPS}")
            if t.variable_label in mutable_var_def_map and \
                    mutable_var_def_map[t.variable_label].type == "string" and t.operator not in ("eq", "neq"):
                raise ConfigError(f"{ctx} trigger: string variables only support eq/neq operators")

        elif isinstance(t, FlagExpiryTrigger):
            _FLAG_EXPIRY_KINDS = ("node", "zone", "waypoint", "dynamic_waypoint")
            _check_label(t.flag_label, flag_labels, f"{ctx} trigger")
            if t.target_kind not in _FLAG_EXPIRY_KINDS:
                raise ConfigError(
                    f"{ctx} trigger: flag_expired target_kind must be one of {_FLAG_EXPIRY_KINDS}"
                )

        elif isinstance(t, WaypointExpiryTrigger):
            if t.had_flag is not None:
                _check_label(t.had_flag, flag_labels, f"{ctx} trigger")

        elif isinstance(t, WaypointReceivedTrigger):
            if t.from_flag is not None:
                _check_label(t.from_flag, flag_labels, f"{ctx} trigger waypoint_received from_flag")

        # Whether the trigger provides a live dynamic waypoint ID (for add/remove_waypoint_flag)
        _is_dynamic_waypoint_trigger = (
            isinstance(t, ProximityTrigger)
            and t.kind == "near_waypoint"
            and t.target_flag is not None
        )
        _flag_expired_dynamic = (
            isinstance(t, FlagExpiryTrigger)
            and t.target_kind == "dynamic_waypoint"
        )
        _can_add_remove_waypoint_flag = _is_dynamic_waypoint_trigger or _flag_expired_dynamic
        _has_node_context = not (
            isinstance(t, TimedTrigger)
            or isinstance(t, WaypointExpiryTrigger)
            or (isinstance(t, ProximityTrigger) and t.kind == "in_zone_on_start")
            or (isinstance(t, FlagExpiryTrigger) and t.target_kind != "node")
        )
        _has_dynamic_waypoint_context = _is_dynamic_waypoint_trigger or _flag_expired_dynamic

        for resp in event.responses:
            _validate_response(
                resp, message_labels, flag_labels, event_labels,
                zone_labels, waypoint_labels, node_labels, channel_labels, group_labels,
                f"{ctx} response",
            )
            _validate_mutable_response(resp, mutable_var_def_map, f"{ctx} response")
            if not _has_node_context:
                target = getattr(resp, "target", None)
                if isinstance(target, TargetTriggeringNode):
                    raise ConfigError(
                        f"{ctx}: to_triggering_node is not valid for this trigger type (no node context)"
                    )
            if isinstance(resp, CreateWaypointResponse):
                if resp.randomly_in_zone is not None and resp.randomly_in_zone_group is not None:
                    raise ConfigError(f"{ctx}: create_waypoint randomly_in_zone and randomly_in_zone_group are mutually exclusive")
                if resp.randomly_in_zone is not None:
                    _check_label(resp.randomly_in_zone, zone_labels, f"{ctx} create_waypoint randomly_in_zone")
                elif resp.randomly_in_zone_group is not None:
                    _check_label(resp.randomly_in_zone_group, group_labels, f"{ctx} create_waypoint randomly_in_zone_group")
                    if group_kind.get(resp.randomly_in_zone_group) != "zone":
                        raise ConfigError(f"{ctx}: create_waypoint randomly_in_zone_group: group {resp.randomly_in_zone_group!r} must be kind 'zone'")
                elif not _has_node_context:
                    raise ConfigError(f"{ctx}: create_waypoint without randomly_in_zone requires a trigger that provides node context")
                if resp.mesh_name is not None:
                    if len(resp.mesh_name) > 30:
                        raise ConfigError(f"{ctx}: create_waypoint mesh_name exceeds 30-character Meshtastic limit")
                    if len(resp.mesh_description) > 100:
                        raise ConfigError(f"{ctx}: create_waypoint mesh_description exceeds 100-character Meshtastic limit")
                    if resp.mesh_channel and resp.mesh_to_triggering_node:
                        raise ConfigError(f"{ctx}: create_waypoint mesh_channel and mesh_to_triggering_node are mutually exclusive")
                    if not resp.mesh_channel and not resp.mesh_to_triggering_node:
                        raise ConfigError(f"{ctx}: create_waypoint with mesh_name requires mesh_channel or mesh_to_triggering_node")
                    if resp.mesh_channel:
                        _check_label(resp.mesh_channel, channel_labels, f"{ctx} create_waypoint mesh_channel")
            if isinstance(resp, BroadcastWaypointResponse):
                if len(resp.name) > 30:
                    raise ConfigError(f"{ctx}: broadcast_waypoint name exceeds 30-character Meshtastic limit")
                if len(resp.description) > 100:
                    raise ConfigError(f"{ctx}: broadcast_waypoint description exceeds 100-character Meshtastic limit")
                if (resp.lat is None) != (resp.lon is None):
                    raise ConfigError(f"{ctx}: broadcast_waypoint lat and lon must both be provided or both omitted")
                if resp.expiry_mins is not None and resp.expiry_mins <= 0:
                    raise ConfigError(f"{ctx}: broadcast_waypoint expiry_mins must be positive")
                if resp.lat is None and not _has_node_context:
                    raise ConfigError(f"{ctx}: broadcast_waypoint with no explicit lat/lon requires a trigger that provides node context")
            if isinstance(resp, DeleteMeshWaypointResponse):
                if not resp.label and not resp.use_triggering_waypoint:
                    raise ConfigError(f"{ctx}: delete_mesh_waypoint requires 'label' or 'use_triggering_waypoint'")
                if resp.label and resp.use_triggering_waypoint:
                    raise ConfigError(f"{ctx}: delete_mesh_waypoint 'label' and 'use_triggering_waypoint' are mutually exclusive")
            if isinstance(resp, DestroyWaypointResponse):
                if not _is_dynamic_waypoint_trigger:
                    raise ConfigError(
                        f"{ctx}: destroy_waypoint is only valid in near_waypoint + target_flag events"
                    )
            if isinstance(resp, (AddDynamicWaypointFlagResponse, RemoveDynamicWaypointFlagResponse)):
                if not _can_add_remove_waypoint_flag:
                    raise ConfigError(
                        f"{ctx}: {type(resp).__name__} requires a dynamic waypoint context "
                        f"(near_waypoint + target_flag, or flag_expired + target_kind: dynamic_waypoint)"
                    )
            target = getattr(resp, "target", None)
            if isinstance(target, TargetAllNearTriggeringWaypoint) and not _has_dynamic_waypoint_context:
                raise ConfigError(
                    f"{ctx}: to_all_near_triggering_waypoint requires a dynamic waypoint context "
                    f"(near_waypoint + target_flag, or flag_expired + target_kind: dynamic_waypoint)"
                )

        for exc in event.exceptions:
            if exc.kind == "random_skip":
                if exc.chance is None:
                    raise ConfigError(f"{ctx} exception 'random_skip': 'chance' field required")
                if not (0.0 <= exc.chance <= 1.0):
                    raise ConfigError(f"{ctx} exception 'random_skip': 'chance' must be 0.0–1.0")
            elif exc.kind in ("node_in_group", "node_not_in_group"):
                if not exc.group:
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: 'group' field required")
                _check_label(exc.group, group_labels, f"{ctx} exception")
                if group_kind.get(exc.group) != "node":
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: group {exc.group!r} must be kind 'node'")
            elif exc.kind in ("zone_in_group", "zone_not_in_group"):
                if not exc.group or not exc.target:
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: 'group' and 'target' fields required")
                _check_label(exc.group, group_labels, f"{ctx} exception")
                _check_label(exc.target, zone_labels, f"{ctx} exception target zone")
                if group_kind.get(exc.group) != "zone":
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: group {exc.group!r} must be kind 'zone'")
            elif exc.kind in ("waypoint_in_group", "waypoint_not_in_group"):
                if not exc.group or not exc.target:
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: 'group' and 'target' fields required")
                _check_label(exc.group, group_labels, f"{ctx} exception")
                _check_label(exc.target, waypoint_labels, f"{ctx} exception target waypoint")
                if group_kind.get(exc.group) != "waypoint":
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: group {exc.group!r} must be kind 'waypoint'")
            else:
                if exc.flag is None:
                    raise ConfigError(f"{ctx} exception {exc.kind!r}: 'flag' field required")
                _check_label(exc.flag, flag_labels, f"{ctx} exception")
                if exc.kind in ("zone_has_flag", "zone_lacks_flag") and exc.target:
                    _check_label(exc.target, zone_labels, f"{ctx} exception")
                if exc.kind in ("waypoint_has_flag", "waypoint_lacks_flag"):
                    if exc.target:
                        _check_label(exc.target, waypoint_labels, f"{ctx} exception")
                    elif not _has_dynamic_waypoint_context:
                        raise ConfigError(
                            f"{ctx}: exception {exc.kind!r} without 'target' is only valid "
                            f"in events with a dynamic waypoint context"
                        )

    for node in cfg.nodes:
        for fl in node.initial_flags:
            _check_label(fl, flag_labels, f"Node {node.label!r} initial_flags")

    for var in cfg.variables:
        vctx = f"Variable {var.label!r}"
        if var.tracks == "static":
            if var.value is None:
                raise ConfigError(f"{vctx}: 'value' required for tracks: static")
        elif var.tracks == "node_count":
            if var.target is None or var.target not in zone_labels:
                raise ConfigError(f"{vctx} field 'target': must be a zone label")
        elif var.tracks == "event_trigger_count":
            if var.event is None or var.event not in event_labels:
                raise ConfigError(f"{vctx} field 'event': must be an event label")
        elif var.tracks == "flag_count":
            if var.target is None or var.target not in flag_labels:
                raise ConfigError(f"{vctx} field 'target': must be a flag label")
        elif var.tracks == "group_count":
            if var.target is None or var.target not in group_labels:
                raise ConfigError(f"{vctx} field 'target': must be a group label")
        elif var.tracks == "waypoint_node_count":
            if var.target is None or var.target not in waypoint_labels:
                raise ConfigError(f"{vctx} field 'target': must be a waypoint label")
            if var.meters is None:
                raise ConfigError(f"{vctx}: 'meters' required for tracks: waypoint_node_count")
        elif var.tracks == "distance_to_waypoint":
            if var.target is None or var.target not in waypoint_labels:
                raise ConfigError(f"{vctx} field 'target': must be a waypoint label")
        elif var.tracks in ("prev_distance_to_waypoint", "distance_change_to_waypoint",
                            "bearing_to_waypoint", "cardinal_to_waypoint"):
            if var.target is None or var.target not in waypoint_labels:
                raise ConfigError(f"{vctx} field 'target': must be a waypoint label")
        elif var.tracks == "distance_to_zone":
            if var.target is None or var.target not in zone_labels:
                raise ConfigError(f"{vctx} field 'target': must be a zone label")
            if var.zone_measure not in ("centroid", "border", None):
                raise ConfigError(f"{vctx} field 'zone_measure': must be 'centroid' or 'border'")
        elif var.tracks == "distance_to_node":
            if var.scope == "zone" and (var.target is None or var.target not in zone_labels):
                raise ConfigError(f"{vctx} field 'target': must be a zone label for scope: zone")
            if var.scope == "waypoint" and (var.target is None or var.target not in waypoint_labels):
                raise ConfigError(f"{vctx} field 'target': must be a waypoint label for scope: waypoint")
            if var.node is None or var.node not in node_labels:
                raise ConfigError(f"{vctx} field 'node': must be a node label")
        elif var.tracks in ("seconds_since_last_update", "current_position", "prev_position"):
            pass  # no target required — computed from triggering node's location history
        elif var.tracks in (
            "node_battery_level", "node_voltage", "node_channel_utilization",
            "node_air_util_tx", "node_uptime_seconds", "node_snr",
            "node_hops_away", "node_hw_model", "node_role",
        ):
            if var.scope != "node":
                raise ConfigError(f"{vctx}: tracks: {var.tracks!r} requires scope: node")
        elif var.tracks in ("nearest_node_distance", "nearest_node_name"):
            if var.scope == "zone" and (var.target is None or var.target not in zone_labels):
                raise ConfigError(f"{vctx} field 'target': must be a zone label for scope: zone")
            if var.scope == "waypoint" and (var.target is None or var.target not in waypoint_labels):
                raise ConfigError(f"{vctx} field 'target': must be a waypoint label for scope: waypoint")
            if var.exclude_flag is not None and var.exclude_flag not in flag_labels:
                raise ConfigError(f"{vctx} field 'exclude_flag': flag {var.exclude_flag!r} not defined")
        else:
            raise ConfigError(f"{vctx}: unknown tracks value {var.tracks!r}")

    all_variable_labels = variable_labels | mutable_var_labels
    _BUILTIN_TOKENS = frozenset({"node_id", "node_shortname", "node_longname", "zone"})
    _VAR_TOKEN_RE = re.compile(r'\{(\w+)\}')
    for msg in cfg.messages:
        for token in _VAR_TOKEN_RE.findall(msg.text):
            if token not in all_variable_labels and token not in _BUILTIN_TOKENS:
                raise ConfigError(
                    f"Message {msg.label!r}: interpolation token '{{{token}}}' not defined in variables"
                )

    # Validate capture templates: CommandTrigger messages with mutable variable tokens
    _cmd_events = [e for e in cfg.events if isinstance(e.trigger, CommandTrigger)]
    for event in _cmd_events:
        t = event.trigger
        msg = next((m for m in cfg.messages if m.label == t.message_label), None)
        if msg is None:
            continue
        tokens = _VAR_TOKEN_RE.findall(msg.text)
        capture_vars = [tok for tok in tokens if tok in mutable_var_def_map and tok not in _BUILTIN_TOKENS]
        if len(capture_vars) > 1:
            raise ConfigError(
                f"Event {event.label!r}: command message {msg.label!r} has more than one "
                f"capture variable ({capture_vars!r}); only one allowed per command"
            )
        if len(capture_vars) == 1:
            var_def = mutable_var_def_map[capture_vars[0]]
            if var_def.scope != "node":
                raise ConfigError(
                    f"Event {event.label!r}: capture variable {capture_vars[0]!r} "
                    f"must be scope: node"
                )


def _validate_target(
    target: Target,
    zone_labels, waypoint_labels, flag_labels, node_labels,
    channel_labels, group_labels,
    ctx: str,
) -> None:
    random_n = getattr(target, "random_n", None)
    if random_n is not None and (not isinstance(random_n, int) or isinstance(random_n, bool) or random_n < 1):
        raise ConfigError(f"{ctx}: random_n must be a positive integer")
    if isinstance(target, TargetZone):
        if target.zone_label not in zone_labels:
            raise ConfigError(f"{ctx}: zone {target.zone_label!r} not defined")
    elif isinstance(target, TargetFlag):
        if target.flag_label not in flag_labels:
            raise ConfigError(f"{ctx}: flag {target.flag_label!r} not defined")
    elif isinstance(target, TargetChannel):
        if target.channel_label not in channel_labels:
            raise ConfigError(f"{ctx}: channel {target.channel_label!r} not defined")
    elif isinstance(target, TargetWaypointRadius):
        if target.waypoint_label not in waypoint_labels:
            raise ConfigError(f"{ctx}: waypoint {target.waypoint_label!r} not defined")
    elif isinstance(target, TargetAllInZone):
        if target.zone_label not in zone_labels:
            raise ConfigError(f"{ctx}: zone {target.zone_label!r} not defined")
    elif isinstance(target, TargetAllWithFlag):
        if target.flag_label not in flag_labels:
            raise ConfigError(f"{ctx}: flag {target.flag_label!r} not defined")
    elif isinstance(target, TargetAllNearWaypoint):
        if target.waypoint_label not in waypoint_labels:
            raise ConfigError(f"{ctx}: waypoint {target.waypoint_label!r} not defined")
    elif isinstance(target, TargetAllNearNode):
        if target.node_label not in node_labels:
            raise ConfigError(f"{ctx}: node {target.node_label!r} not defined")
    elif isinstance(target, TargetNode):
        if target.node_label not in node_labels:
            raise ConfigError(f"{ctx}: node {target.node_label!r} not defined")
    elif isinstance(target, TargetGroup):
        if target.group_label not in group_labels:
            raise ConfigError(f"{ctx}: group {target.group_label!r} not defined")
    elif isinstance(target, TargetAllNearTriggeringWaypoint):
        if target.meters <= 0:
            raise ConfigError(f"{ctx}: to_all_near_triggering_waypoint meters must be positive")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_config(path: str) -> GameConfig:
    with open(path) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    cfg = GameConfig(
        channels=[
            Channel(
                label=c["label"],
                name=c["name"],
                psk=c["psk"],
                monitor=c.get("monitor", True),
                participate=c.get("participate", False),
            )
            for c in raw.get("channels", [])
        ],
        zones=[
            Zone(label=z["label"], points=[tuple(p) for p in z["points"]])
            for z in raw.get("zones", [])
        ],
        waypoints=[
            Waypoint(label=w["label"], lat=float(w["lat"]), lon=float(w["lon"]))
            for w in raw.get("waypoints", [])
        ],
        messages=[
            Message(label=m["label"], text=m["text"])
            for m in raw.get("messages", [])
        ],
        flags=[
            FlagDef(label=f["label"], expiry_mins=f.get("expiry_mins"))
            for f in raw.get("flags", [])
        ],
        nodes=[
            NodeDef(
                label=n["label"],
                node_id=n["node_id"],
                initial_flags=n.get("initial_flags", []),
            )
            for n in raw.get("nodes", [])
        ],
        groups=[
            GroupDef(
                label=g["label"],
                kind=g["kind"],
                initial_members=g.get("initial_members", []),
            )
            for g in raw.get("groups", [])
        ],
        variables=[_parse_variable(v) for v in raw.get("variables", [])],
        mutable_variables=[
            MutableVariableDef(
                label=mv["label"],
                type=mv["type"],
                scope=mv["scope"],
                initial=mv["initial"],
                min=mv.get("min"),
                max=mv.get("max"),
                max_length=mv.get("max_length"),
            )
            for mv in raw.get("mutable_variables", [])
        ],
        events=[_parse_event(e) for e in raw.get("events", [])],
    )

    _validate(cfg)
    return cfg
