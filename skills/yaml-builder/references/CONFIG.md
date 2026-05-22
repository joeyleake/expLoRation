# expLoRation Configuration Reference

The game is defined entirely by a single YAML file (default: `game.yaml`). Every
object — zones, messages, events — is referenced by a short string called a
**label**. Labels must be unique within their type. The bot validates all
cross-references on startup and exits with a descriptive error if any label is
missing or misused.

---

## Top-level structure

```yaml
channels:           [ ... ]
zones:              [ ... ]
waypoints:          [ ... ]
messages:           [ ... ]
flags:              [ ... ]
nodes:              [ ... ]
groups:             [ ... ]
variables:          [ ... ]
mutable_variables:  [ ... ]
events:             [ ... ]
```

All sections are optional; omitting a section is the same as providing an empty
list. Sections may appear in any order.

---

## Channels

Channels tell the bot which Meshtastic radio channels to listen on and/or send
messages to.

```yaml
channels:
  - label: main          # required — unique identifier used in events
    name: LongFast       # required — must match the channel name configured on the device
    psk: AQ==            # required — base64-encoded PSK; "AQ==" is the Meshtastic default key
    monitor: true        # optional — listen for messages on this channel (default: true)
    participate: false   # optional — allow the bot to broadcast on this channel (default: false)
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used to reference this channel in events |
| `name` | string | yes | Channel name as set on the Meshtastic device |
| `psk` | string | yes | Base64 pre-shared key. Use `"AQ=="` for the built-in default |
| `monitor` | bool | no | If true, the bot processes messages received on this channel (default: `true`) |
| `participate` | bool | no | If true, the bot is allowed to broadcast messages on this channel (default: `false`) |

On startup the bot reads channel names from the connected device and matches
them to the `name` field. If a config channel cannot be matched to a device
channel index, a warning is logged and that channel is skipped.

---

## Zones

Zones are triangular geographic areas defined by exactly three latitude/longitude
vertices. They are used in proximity triggers, command triggers, and as flag
targets.

```yaml
zones:
  - label: park_entrance
    points:
      - [37.7749, -122.4194]   # vertex 1: [lat, lon]
      - [37.7752, -122.4188]   # vertex 2
      - [37.7745, -122.4185]   # vertex 3
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used to reference this zone in events |
| `points` | list of [lat, lon] | yes | Exactly three vertices in decimal degrees. Order does not matter. |

**Notes:**
- The point-in-triangle test uses a flat-plane approximation of latitude and
  longitude, which is accurate for areas under ~10 km across.
- The zone centroid (average of all three vertices) is used when computing
  distance-to-zone in `near_zone` triggers.
- **Covering a rectangle or other non-triangular area:** split the shape into
  two triangles sharing a diagonal (`_a` / `_b` by convention), define both as
  zones, then add them to a zone group. Use `enters_zone_group` /
  `leaves_zone_group` / `in_zone_group` triggers against the group rather than
  writing separate events per triangle. See the `groups:` section and the
  `enters_zone_group` trigger.

---

## Waypoints

Waypoints are single points on the map. They are used as proximity trigger
targets and as flag targets.

```yaml
waypoints:
  - label: hidden_cache
    lat: 37.7773
    lon: -122.4158
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used to reference this waypoint in events |
| `lat` | float | yes | Latitude in decimal degrees |
| `lon` | float | yes | Longitude in decimal degrees |

---

## Messages

Messages are the text strings the bot can send. Define all text centrally here
and reference it by label in event responses and command triggers.

```yaml
messages:
  - label: welcome
    text: "Welcome to expLoRation! Head north to find the first clue."

  - label: hint_request
    text: "!hint"

  - label: multi_line
    text: |
      Line one of a longer message.
      Line two. The bot splits at 200 bytes automatically.
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used in event responses and command triggers |
| `text` | string | yes | The text to send or match. Multi-line YAML strings are supported. |

**Notes:**
- Outgoing messages longer than 200 bytes are split at line boundaries and sent
  as multiple packets. Single lines longer than 200 bytes are split at the byte
  boundary.
- For `dm` / `channel` triggers, the incoming message text is compared against
  `text` after stripping leading/trailing whitespace. Comparison is exact
  (case-sensitive).

**Variable interpolation in messages:**

Place `{variable_label}` anywhere in a message `text` field. Tokens are replaced
at send time with the resolved value.

Four built-in tokens are always available:

| Token | Resolves to |
|---|---|
| `{node_id}` | The triggering node's ID (e.g. `!aabbccdd`), or `[unknown]` if no node context |
| `{node_shortname}` | The triggering node's shortName (e.g. `JOEY`), falling back to node ID if name is unavailable |
| `{node_longname}` | The triggering node's longName (e.g. `Joey's Radio`), falling back to node ID if name is unavailable |
| `{zone}` | The zone label the triggering node most recently entered or is currently in, or `[unknown]` |

For user-defined variable tokens, see the [Variables](#variables) section. If
resolution fails, the fallback strings are:

- `[unknown]` — label undefined or required data unavailable
- `[no node context]` — `scope: node` variable used in an event with no triggering node
- `[no nodes]` — no eligible nodes for `nearest_node_*`

All variable labels referenced in message text are validated at startup.

```yaml
messages:
  - label: status
    text: "There are {hunters_in_zone} hunters in the area. You are {dist_to_cache}m from the cache."

  - label: found_announcement
    text: "🎉 {node_id} found the cache in zone {zone}!"
```

---

## Flags

Flags are labels that can be attached to nodes, zones, or waypoints to track
game state. Define all flags here before referencing them in events.

```yaml
flags:
  - label: winner           # permanent flag

  - label: has_clue
    expiry_mins: 120        # flag expires 2 hours after being set
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used throughout events |
| `expiry_mins` | float | no | Minutes after which the flag automatically expires. Omit or set to `null` for a permanent flag. |

**Notes:**
- Expiry is relative to when the flag is *set*, not when it is first defined.
- Expiry is enforced both lazily (on every `has_flag` check) and eagerly (on
  every periodic tick and packet arrival).
- Flags can be applied to three target types: **nodes** (individual radios),
  **zones** (geographic areas), and **waypoints** (single points).

---

## Nodes

Hard-coded nodes allow you to reference specific devices by a friendly label and
set flags on them as initial game conditions.

```yaml
nodes:
  - label: game_master
    node_id: "!deadbeef"    # Meshtastic node ID in hex format
    initial_flags:
      - game_master         # flags set on this node when the bot starts
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used in node-targeting responses and `near_node` triggers |
| `node_id` | string | yes | Meshtastic node ID in `!xxxxxxxx` hex format (8 hex digits) |
| `initial_flags` | list of flag labels | no | Flags applied to this node when the bot starts. Applied every restart, so flags with expiry will be refreshed each time the bot starts. |

**Notes:**
- Nodes not listed here are still discovered and tracked automatically as the
  bot receives location packets from them.
- Most nodes do not need to be defined here. Only add a node when you need to
  reference it by label in a trigger or response, or need initial flags set on it.

---

## Groups

Groups are named collections of nodes, zones, or waypoints that can be used as
targets for responses, `to_group` targeting, and group-based exception checks.
Every group has a single `kind` — all members must be of the same type.

```yaml
groups:
  - label: red_team
    kind: node              # "node" | "zone" | "waypoint"
    initial_members:        # optional — labels of the same kind as initial members
      - scout_alpha
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used in responses and exceptions |
| `kind` | string | yes | One of `node`, `zone`, or `waypoint`. All members must match. |
| `initial_members` | list of labels | no | Labels of nodes/zones/waypoints to pre-populate at startup. Each must be defined in the corresponding top-level section. |

Groups are populated dynamically via `add_to_group` / `remove_from_group`
responses. `initial_members` seeds the group on startup (applied every restart).

---

## Variables

Computed variables read live values from engine state and expose them for
message interpolation (`{label}`) and `variable_threshold` triggers. Values are
read-only — computed on demand, never stored.

```yaml
variables:
  - label: hunters_in_zone       # unique identifier used in {interpolation}
    scope: zone                  # global | node | zone | waypoint | event
    tracks: node_count           # what this variable computes
    target: start_zone           # required for most tracks types (see below)

  - label: game_name
    scope: global
    tracks: static
    value: "The Woodstock Hunt"
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used in `{label}` interpolation tokens |
| `scope` | string | yes | Context for resolution: `global`, `node`, `zone`, `waypoint`, or `event` |
| `tracks` | string | yes | What value to compute — see tracked types below |
| `target` | string | conditional | Label of the zone, waypoint, flag, or event to query (required by most tracked types) |
| `value` | string | conditional | Required for `tracks: static` |
| `event` | string | conditional | Event label — required for `tracks: event_trigger_count` |
| `meters` | float | conditional | Radius in metres — required for `tracks: waypoint_node_count` |
| `zone_measure` | string | no | `centroid` (default) or `border` — used by `tracks: distance_to_zone` |
| `node` | string | conditional | Node label — required for `tracks: distance_to_node` |
| `exclude_flag` | string | no | Flag label — nodes carrying this flag are excluded from `nearest_node_distance` / `nearest_node_name` |

### Tracked types

#### `static` — fixed string

Returns the literal `value` string. Never changes.

```yaml
- label: game_name
  scope: global
  tracks: static
  value: "The Woodstock Hunt"
```

#### `node_count` — nodes inside a zone

Returns the count of nodes with a known location currently inside the target zone polygon.

```yaml
- label: seekers_in_zone
  scope: zone
  tracks: node_count
  target: start_zone       # zone label
```

#### `event_trigger_count` — times an event has fired

Returns the `times_triggered` counter for the target event. When `scope: node`,
returns how many times that event has fired with the triggering node specifically
(requires `trigger_per_node: true` on the event to be meaningful).

```yaml
- label: hints_used
  scope: node
  tracks: event_trigger_count
  event: hint_command        # event label
```

#### `flag_count` — nodes carrying a flag

Returns the count of nodes currently carrying the target flag.

```yaml
- label: active_players
  scope: global
  tracks: flag_count
  target: player             # flag label
```

#### `group_count` — members in a group

Returns the count of current members in the named group.

```yaml
- label: red_team_size
  scope: global
  tracks: group_count
  target: red_team           # group label
```

#### `waypoint_node_count` — nodes near a waypoint

Returns the count of nodes within `meters` of the target waypoint.

```yaml
- label: near_cache
  scope: global
  tracks: waypoint_node_count
  target: hidden_cache       # waypoint label
  meters: 50
```

#### `distance_to_waypoint` — triggering node's distance to a waypoint

Returns distance in metres (rounded to nearest integer) from the triggering node
to the target waypoint. Requires a triggering node (`scope: node`).

```yaml
- label: cache_distance
  scope: node
  tracks: distance_to_waypoint
  target: hidden_cache       # waypoint label
```

#### `prev_distance_to_waypoint` — previous distance to a waypoint

Distance in metres from the node's *previous* recorded position to the waypoint.
Returns `[unknown]` if no prior position has been recorded.

```yaml
- label: prev_cache_distance
  scope: node
  tracks: prev_distance_to_waypoint
  target: hidden_cache
```

#### `distance_change_to_waypoint` — movement toward or away from a waypoint

Difference in metres between the current and previous distance to the waypoint:
`current_dist − prev_dist`. Negative = moved closer; positive = moved farther.
Rounded to one decimal place. Returns `[unknown]` if no prior position exists.

Primary use: `variable_threshold` trigger to set direction flags (warmer/colder).

```yaml
- label: hint_delta
  scope: node
  tracks: distance_change_to_waypoint
  target: hidden_cache

# Use in a variable_threshold trigger:
- label: mark_dir_closer
  trigger:
    type: variable_threshold
    variable: hint_delta
    operator: lt
    value: -1         # moved more than 1 m closer
  trigger_per_node: true
  responses:
    - type: add_flag
      flag_label: dir_closer
      to_triggering_node: true
```

#### `bearing_to_waypoint` — compass bearing to a waypoint

Returns the forward bearing in whole degrees (0–359, formatted as e.g. `"247°"`)
from the triggering node's current position to the target waypoint. 0° is north,
90° is east. Returns `[unknown]` if the node has no known location.

```yaml
- label: bearing_to_cache
  scope: node
  tracks: bearing_to_waypoint
  target: hidden_cache       # waypoint label
```

#### `cardinal_to_waypoint` — 16-point compass direction to a waypoint

Returns the nearest 16-point compass label (`N`, `NNE`, `NE`, `ENE`, `E`, `ESE`,
`SE`, `SSE`, `S`, `SSW`, `SW`, `WSW`, `W`, `WNW`, `NW`, `NNW`) for the direction
from the triggering node to the target waypoint. Returns `[unknown]` if the node
has no known location.

```yaml
- label: cardinal_to_cache
  scope: node
  tracks: cardinal_to_waypoint
  target: hidden_cache       # waypoint label
```

Combine with `bearing_to_waypoint` for a human-friendly display:
```yaml
messages:
  - label: direction_msg
    text: "Cache is {bearing_to_cache} ({cardinal_to_cache}) from your position."
```

#### `seconds_since_last_update` — seconds since node's last position fix

Returns the number of whole seconds elapsed since the triggering node last sent
a GPS position update. Returns `[unknown]` if no position has ever been received.

```yaml
- label: staleness
  scope: node
  tracks: seconds_since_last_update
```

#### `current_position` — triggering node's current coordinates

Returns the node's current latitude and longitude as a formatted string
(`"lat, lon"` to 5 decimal places). Returns `[unknown]` if no location known.

```yaml
- label: cur_pos
  scope: node
  tracks: current_position
```

#### `prev_position` — triggering node's previous coordinates

Returns the node's *previous* recorded latitude and longitude, i.e. its location
before the most recent position update. Returns `[unknown]` if no prior position.

```yaml
- label: prev_pos
  scope: node
  tracks: prev_position
```

#### `distance_to_zone` — triggering node's distance to a zone

Returns distance in metres from the triggering node to the target zone.
`zone_measure: centroid` (default) measures from the zone's centroid.
`zone_measure: border` measures to the nearest point on any triangle edge —
more accurate for large zones.

```yaml
- label: zone_dist
  scope: node
  tracks: distance_to_zone
  target: start_zone         # zone label
  zone_measure: border       # centroid (default) | border
```

#### `distance_to_node` — distance from a zone or waypoint to a named node

Returns distance in metres from the zone centroid or waypoint to a specific
hard-coded node's last known location. If the named node has no known location,
resolves to `[unknown]`.

```yaml
- label: gm_dist_from_cache
  scope: waypoint
  tracks: distance_to_node
  target: hidden_cache       # waypoint label (or zone label if scope: zone)
  node: game_master          # node label
```

#### `nearest_node_distance` — distance to the nearest node

Returns distance in metres from the zone centroid or waypoint to the nearest
node with a known location. Optionally excludes nodes carrying a specific flag.

```yaml
- label: closest_seeker_dist
  scope: zone
  tracks: nearest_node_distance
  target: start_zone         # zone label
  exclude_flag: homeowner    # optional — omit nodes with this flag
```

#### `nearest_node_name` — name of the nearest node

Same resolution logic as `nearest_node_distance` but returns the node's short
name (from the Meshtastic node database) or its node ID if no name is known.
Supports the same optional `exclude_flag` field.

```yaml
- label: closest_seeker_name
  scope: zone
  tracks: nearest_node_name
  target: start_zone
  exclude_flag: homeowner
```

---

## Mutable Variables

Mutable variables store per-node or global integer, float, or string state that
can be read, written, and incremented by event responses. Define them in the
`mutable_variables:` section before referencing them.

```yaml
mutable_variables:
  - label: score
    type: integer
    scope: global
    initial: 0
    min: 0          # optional — clamp floor (integer/float only)
    max: 100        # optional — clamp ceiling

  - label: hint_count
    type: integer
    scope: node     # tracked independently per node
    initial: 0
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name. Must not conflict with any label in `variables:`. |
| `type` | string | yes | `integer`, `float`, or `string` |
| `scope` | string | yes | `global` (one value shared across all nodes) or `node` (one value per node) |
| `initial` | int/float/string | yes | Starting value. Must match `type`. |
| `min` | number | no | Clamp floor for integer/float. Ignored for string. |
| `max` | number | no | Clamp ceiling for integer/float. Ignored for string. |

**Notes:**
- `min` and `max` are enforced by `set_variable` and `increment_variable` at
  write time. The `initial` value must fall within `[min, max]` if both are set.
- Mutable variable labels are interpolated in messages the same way as computed
  variables: `{hint_count}` in a message resolves to the triggering node's
  current value when `scope: node`, or the global value when `scope: global`.
- Use `variable_threshold` triggers on mutable variables to react to value changes.

---

## Events

Events are the core of the game logic. Each event has a single **trigger**, one
or more **responses**, and optional **exceptions** and rate-limiting controls.

```yaml
events:
  - label: my_event        # required — unique identifier
    trigger: { ... }       # required — see Triggers below
    responses:             # required — at least one
      - { ... }
    exceptions:            # optional — skip the event if any exception matches
      - { ... }
    max_triggers: 1        # optional — stop firing after this many times (null = unlimited)
    reset_mins: 5          # optional — cooldown in minutes between firings (null = no cooldown)
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name for this event |
| `trigger` | object | yes | Condition that causes the event to fire |
| `responses` | list | yes | Actions executed when the event fires, in order |
| `exceptions` | list | no | If any exception matches, the event is skipped entirely |
| `max_triggers` | int or null | no | Maximum number of times this event can fire. `null` means unlimited. |
| `reset_mins` | float or null | no | Minimum minutes between firings. `null` means no cooldown. |
| `disabled` | bool | no | If `true`, the trigger is never evaluated and the event never fires. Default: `false`. |
| `trigger_per_node` | bool | no | If `true`, `max_triggers` and `reset_mins` are tracked independently per node rather than globally. Default: `false`. |
| `auto_recur` | bool | no | If `true`, once the event has fired through its normal trigger, it will automatically re-fire every `recur_mins` minutes without needing the original trigger condition to be met again. Default: `false`. |
| `recur_mins` | float | conditional | Required when `auto_recur: true`. Minutes between automatic re-firings. |

`max_triggers`, `reset_mins`, and `disabled` can all be active simultaneously.
The event will not fire if any of the three conditions block it.

`disabled` is persisted in the database, so the runtime state survives restarts.
The config value is used only to seed the database the *first time* the bot
encounters a given event label. After that, the database value is authoritative
and the config value is ignored. To force a reset of a running game's disabled
state, either delete the database or use a `disable_event`/`enable_event`
response from another event.

---

### Triggers

Each event has exactly one trigger, defined as an object with a `type` field.

#### `near_waypoint` — node enters waypoint radius

Fires when the bot receives a location update from any node and that node is
within `meters` of the named waypoint.

**Static waypoint variant:**
```yaml
trigger:
  type: near_waypoint
  target: hidden_cache     # waypoint label
  meters: 20               # radius in metres
```

**Dynamic waypoint variant** (any waypoint carrying a specific flag):
```yaml
trigger:
  type: near_waypoint
  target_flag: laser_target   # fires for any dynamic waypoint with this flag
  meters: 1609
```

| Field | Required | Description |
|---|---|---|
| `target` | one of | A `waypoints` label — targets a single static waypoint |
| `target_flag` | one of | A `flags` label — targets any *dynamic* waypoint currently carrying this flag. Exactly one of `target` or `target_flag` must be set. |
| `meters` | yes | Radius in metres. The trigger fires if the node is within this distance. |

When `target_flag` is used, the nearest in-range dynamic waypoint becomes the
`triggering_waypoint_id` for responses like `to_all_near_triggering_waypoint`,
`add_waypoint_flag`, `remove_waypoint_flag`, and `destroy_waypoint`.

#### `near_zone` — node enters zone proximity

Fires when a location update is received and the node is within `meters` of the
zone's centroid (the average of its three vertices).

```yaml
trigger:
  type: near_zone
  target: park_entrance    # zone label
  meters: 50
```

| Field | Required | Description |
|---|---|---|
| `target` | yes | A `zones` label |
| `meters` | yes | Radius from zone centroid in metres |

**Note:** `near_zone` measures from the zone centroid, so an elongated or large
zone may produce surprising results. For exact polygon containment use `in_zone`
or `enters_zone` instead.

#### `near_node` — node comes within range of another node

Fires when a location update is received and the triggering node is within
`meters` of a named hard-coded node. Both nodes must have known locations.

```yaml
trigger:
  type: near_node
  target: game_master      # node label (must be defined in nodes:)
  meters: 30
```

| Field | Required | Description |
|---|---|---|
| `target` | yes | A `nodes` label |
| `meters` | yes | Distance threshold in metres |

#### `in_zone` — node's position is inside the zone polygon

Fires when the bot receives a location update and the node's position falls
inside the zone triangle, using an exact point-in-triangle test. No radius or
centroid approximation — the node must be geometrically inside the polygon.

```yaml
trigger:
  type: in_zone
  target: park_entrance    # zone label
```

| Field | Required | Description |
|---|---|---|
| `target` | yes | A `zones` label |

**Note:** Because zones are triangles, complex areas may require multiple
overlapping zones to cover correctly.

#### `enters_zone` — node transitions from outside to inside the zone

Edge-triggered: fires only when a position update moves a node from outside the
zone polygon to inside it. Does not fire on subsequent updates while the node
remains inside. No `meters` parameter.

```yaml
trigger:
  type: enters_zone
  target: park_entrance    # zone label
```

#### `leaves_zone` — node transitions from inside to outside the zone

Edge-triggered: fires only when a position update moves a node from inside the
zone polygon to outside it. Does not fire while the node remains outside.
No `meters` parameter.

```yaml
trigger:
  type: leaves_zone
  target: park_entrance    # zone label
```

**Note on first position update:** Zone membership is tracked in memory and
resets when the bot restarts. On a node's first position update after startup,
any zone it is currently inside will register as `enters_zone` (since the
previous state is unknown). `leaves_zone` will not fire until the bot has seen
the node inside the zone at least once.

#### `in_zone_on_start` — nodes already inside zone at check time

Fires during periodic checks (every 60 seconds by default) rather than on
individual packet receipt. The trigger condition is: at least one node with a
known location is currently inside the zone.

This trigger is typically used with `max_triggers: 1` to fire once at game
start when players are already positioned inside the start area.

```yaml
trigger:
  type: in_zone_on_start
  target: start_zone       # zone label
```

| Field | Required | Description |
|---|---|---|
| `target` | yes | A `zones` label |

**Note:** `meters` is not used for this trigger type.

#### `enters_zone_group` — node enters any zone in a group

Fires when a node moves into any zone that is a member of the named zone group.
This is the group equivalent of `enters_zone` and is the preferred way to handle
multi-triangle areas (where a single shape is split across `_a`/`_b` zones) without
duplicating event blocks.

```yaml
trigger:
  type: enters_zone_group
  zone_group: game_zones    # groups label — must be kind: zone
```

| Field | Required | Description |
|---|---|---|
| `zone_group` | yes | A `groups` label of kind `zone` |

**Note:** `target` and `zone_group` are mutually exclusive. `{zone}` in message templates resolves to the specific zone the node entered.

#### `leaves_zone_group` — node leaves any zone in a group

Fires when a node moves out of any zone that is a member of the named zone group.

```yaml
trigger:
  type: leaves_zone_group
  zone_group: game_zones
```

| Field | Required | Description |
|---|---|---|
| `zone_group` | yes | A `groups` label of kind `zone` |

#### `in_zone_group` — node is currently inside any group zone

Fires on every position update from a node if the node's current location is
inside any member zone of the named group. Use `max_triggers` or `reset_mins`
to avoid continuous firing.

```yaml
trigger:
  type: in_zone_group
  zone_group: game_zones
```

| Field | Required | Description |
|---|---|---|
| `zone_group` | yes | A `groups` label of kind `zone` |

#### `in_zone_group_on_start` — any node is in any group zone at check time

Fires during periodic checks (every 60 seconds by default) when at least one
node with a known location is currently inside any member zone of the group.
Group equivalent of `in_zone_on_start`.

```yaml
trigger:
  type: in_zone_group_on_start
  zone_group: game_zones
```

| Field | Required | Description |
|---|---|---|
| `zone_group` | yes | A `groups` label of kind `zone` |

#### `time_window` — current time falls within a window

Fires during periodic checks when the current time is between `start` and `end`
and the event has not yet been triggered (`times_triggered == 0`). Because of
this built-in "fire once" condition, `max_triggers: 1` is implied and does not
need to be set explicitly.

```yaml
trigger:
  type: time_window
  start: "2024-06-01T10:00:00"   # ISO 8601 datetime
  end:   "2024-06-01T17:00:00"
```

| Field | Required | Description |
|---|---|---|
| `start` | yes | ISO 8601 datetime string. Timezone-naive values are treated as UTC. |
| `end` | yes | ISO 8601 datetime string |

#### `dm` — node sends a matching DM to the bot

Fires when any node sends a direct message to the bot whose text matches a
defined message. If `zone_label` or `zone_group` is set, the sender must also
be inside that zone (or any zone in the group). When omitted, the trigger fires
for any node regardless of location.

```yaml
trigger:
  type: dm
  message_label: hint_request    # messages label — text must match exactly
  zone_label: start_zone         # optional — restrict to senders inside this zone
  # OR
  zone_group: game_zones         # optional — restrict to senders inside any zone in the group
```

| Field | Required | Description |
|---|---|---|
| `message_label` | yes | A `messages` label. The incoming DM text is compared to `message.text` after stripping whitespace. |
| `zone_label` | no | A `zones` label. Sender must be inside this zone. Mutually exclusive with `zone_group`. |
| `zone_group` | no | A `groups` label of kind `zone`. Sender must be inside any member zone. Mutually exclusive with `zone_label`. |

**Important:** `variable_threshold` triggers also evaluate at DM receipt time
(when a `dm` trigger event is processed, all `variable_threshold` events for
node-scoped variables are also checked). This means you can silently fire
side-effects (like `request_location`) on any DM from a node whose variable
value meets a threshold, without adding logic to the DM event itself.

#### `channel` — node sends a matching message on a monitored channel

Fires when any node broadcasts a message on a specific channel whose text
matches a defined message. If `zone_label` or `zone_group` is set, the sender
must also be inside that zone (or any zone in the group).

```yaml
trigger:
  type: channel
  message_label: activation_code
  zone_label: clue_zone          # optional — restrict to senders inside this zone
  channel_label: main            # channels label — message must arrive on this channel
```

| Field | Required | Description |
|---|---|---|
| `message_label` | yes | A `messages` label |
| `zone_label` | no | A `zones` label — if set, sender must be inside this zone. Mutually exclusive with `zone_group`. |
| `zone_group` | no | A `groups` label of kind `zone` — sender must be inside any member zone. Mutually exclusive with `zone_label`. |
| `channel_label` | yes | A `channels` label — message must arrive on this channel |

#### `variable_threshold` — a variable crosses a threshold

Fires when a variable's current value satisfies the operator comparison against
the threshold value. Evaluation timing depends on variable type:

- **Node-scoped mutable variables**: evaluated when the node sends a DM or position update.
- **Node-scoped computed variables** (e.g. `distance_change_to_waypoint`): evaluated on every position update from that node.
- **Global mutable variables** and **global/unscoped computed variables**: evaluated on the periodic tick (every ~60 seconds).

```yaml
trigger:
  type: variable_threshold
  variable: hint_count     # mutable_variables or variables label
  operator: gte            # lt | lte | eq | neq | gte | gt
  value: 10
```

| Field | Required | Description |
|---|---|---|
| `variable` | yes | A `variables` or `mutable_variables` label |
| `operator` | yes | One of `lt`, `lte`, `eq`, `neq`, `gte`, `gt` |
| `value` | yes | The threshold to compare against. Must be numeric for numeric operators. |

**Notes:**
- String-typed mutable variables only support `eq` and `neq`.
- Computed variables that return `[unknown]` (e.g. no prior position for
  `distance_change_to_waypoint`) will not satisfy numeric operators — the
  trigger silently skips rather than erroring.
- Use `trigger_per_node: true` so the threshold fires independently per node.
- Use `reset_mins` to prevent repeated firing once the threshold is met:
  ```yaml
  - label: refresh_stale_location
    trigger:
      type: variable_threshold
      variable: seconds_since_update
      operator: gte
      value: 300
    trigger_per_node: true
    reset_mins: 5
    responses:
      - type: request_location
        to_triggering_node: true
  ```

#### `flag_expired` — a flag's expiry timer fires

Fires when a flag with `expiry_mins` set reaches its expiry time and is removed
from a node, zone, waypoint, or dynamic waypoint.

```yaml
trigger:
  type: flag_expired
  flag_label: armed           # flags label — must have expiry_mins set
  target_kind: dynamic_waypoint   # node | zone | waypoint | dynamic_waypoint
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label. The flag must have `expiry_mins` defined. |
| `target_kind` | yes | The entity type the flag expired on: `node`, `zone`, `waypoint`, or `dynamic_waypoint`. |

**Notes:**
- When `target_kind: dynamic_waypoint`, responses have access to waypoint
  context (`to_all_near_triggering_waypoint`, `add_waypoint_flag`, etc.).
- When `target_kind: node`, responses have access to node context
  (`to_triggering_node`).
- For other `target_kind` values there is no triggering node, so
  `to_triggering_node` is not valid.

#### `waypoint_expired` — a dynamic waypoint's expiry timer fires

Fires when a dynamic waypoint created with `expiry_mins` reaches its expiry and
is destroyed. Optional `had_flag` restricts the trigger to waypoints that
carried a specific flag at the time of expiry.

```yaml
trigger:
  type: waypoint_expired
  had_flag: laser_target    # optional — only fire for waypoints that had this flag
```

| Field | Required | Description |
|---|---|---|
| `had_flag` | no | A `flags` label. If set, only fires for expired waypoints that carried this flag. Omit to fire for any expired dynamic waypoint. |

---

### Responses

Responses are executed in order when an event fires. Multiple responses in the
same event share the same context (same triggering node, same time).

Every response uses a **target** to specify who or what it acts on. The target
is expressed as a single key on the response object. The available target keys
are documented in the [Targets](#targets) section below.

#### `send_message` — send a text message

```yaml
- type: send_message
  message_label: welcome         # messages label
  to_triggering_node: true       # target (see Targets)
```

| Field | Required | Description |
|---|---|---|
| `message_label` | yes | A `messages` label. The `text` of that message is sent. |
| target key | yes | One target key (see Targets). Use `to_channel` for a channel broadcast; all other targets send a DM to each resolved node individually. |

#### `add_flag` — apply a flag to a target

```yaml
- type: add_flag
  flag_label: has_clue           # flags label
  to_triggering_node: true       # target
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label. The expiry from the flag definition is used. |
| target key | yes | One target key (see Targets). When targeting a zone or waypoint, the flag is set on that geographic object, not on individual nodes. |

#### `remove_flag` — remove a flag from a target

```yaml
- type: remove_flag
  flag_label: temporary_access
  to_all_in_zone: restricted_area
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label |
| target key | yes | One target key (see Targets) |

#### `request_location` — ask target node(s) to broadcast their GPS

Sends a best-effort position request to the target node(s). The node may or may
not respond depending on firmware version and settings.

```yaml
- type: request_location
  to_triggering_node: true
```

| Field | Required | Description |
|---|---|---|
| target key | yes | One target key (see Targets). Only node-resolving targets are meaningful here. |

#### `set_variable` — assign a value to a mutable variable

Sets a mutable variable to a specific value. Values are clamped to `[min, max]`
if those are defined on the variable.

```yaml
- type: set_variable
  variable_label: score      # mutable_variables label
  value: 0
  # no target required for global variables
```

For node-scoped variables a target is required:
```yaml
- type: set_variable
  variable_label: hint_count
  value: 0
  to_triggering_node: true   # target — required for scope: node
```

| Field | Required | Description |
|---|---|---|
| `variable_label` | yes | A `mutable_variables` label |
| `value` | yes | The value to assign. Coerced to the variable's `type`. |
| target key | conditional | Required when the variable's `scope` is `node`. Must not be present for `scope: global`. |

#### `increment_variable` — add an amount to a mutable variable

Adds `amount` to the current value of a numeric mutable variable. The result is
clamped to `[min, max]` if those are defined. Not valid for `type: string`.

```yaml
- type: increment_variable
  variable_label: hint_count
  amount: 1
  to_triggering_node: true   # required for scope: node
```

| Field | Required | Description |
|---|---|---|
| `variable_label` | yes | A `mutable_variables` label with `type: integer` or `float` |
| `amount` | yes | Amount to add (positive or negative) |
| target key | conditional | Required when `scope: node`. Must not be present for `scope: global`. |

#### `disable_event` — disable an event at runtime

Prevents an event from firing until re-enabled. Equivalent to the event having
`disabled: true` in config, but applied dynamically. The disabled state is
persisted across restarts.

```yaml
- type: disable_event
  event_label: near_cache_hint   # events label
```

| Field | Required | Description |
|---|---|---|
| `event_label` | yes | An `events` label |

#### `enable_event` — re-enable a disabled event

Clears the disabled state on an event, allowing its trigger to be evaluated
again. Has no effect if the event is already enabled.

```yaml
- type: enable_event
  event_label: phase_two_unlock
```

| Field | Required | Description |
|---|---|---|
| `event_label` | yes | An `events` label |

#### `set_event_triggers` — manually set an event's trigger count

Resets or advances the `times_triggered` counter on any event. Set to `0` to
re-enable a max-trigger-limited event; set to a high number to permanently
disable one.

```yaml
- type: set_event_triggers
  event_label: game_start        # events label
  value: 0                       # new integer value for times_triggered
```

| Field | Required | Description |
|---|---|---|
| `event_label` | yes | An `events` label |
| `value` | yes | Integer. The `times_triggered` counter is set to exactly this value. |

#### `add_to_group` / `remove_from_group` — manage group membership

Adds or removes a node (or zone/waypoint, depending on group `kind`) from a group.

```yaml
- type: add_to_group
  group_label: red_team
  to_triggering_node: true

- type: remove_from_group
  group_label: red_team
  to_all_with_flag: eliminated
```

| Field | Required | Description |
|---|---|---|
| `group_label` | yes | A `groups` label |
| target key | yes | One target key. The resolved entities must match the group's `kind`. |

#### `random_options` — select one of several weighted outcome branches at random

Picks one branch at random (weighted) and executes its responses. All other
branches are ignored. The selection is made once per event firing — all responses
within the chosen branch share the same context as the parent event.

```yaml
- type: random_options
  options:
    - weight: 3                       # chosen ~60% of the time (3 out of 3+1+1)
      responses:
        - type: send_message
          message_label: common_result
          to_triggering_node: true

    - weight: 1                       # chosen ~20% of the time
      responses:
        - type: send_message
          message_label: rare_result
          to_triggering_node: true
        - type: add_flag
          flag_label: rare_winner
          to_triggering_node: true

    - weight: 1                       # chosen ~20% of the time
      responses:
        - type: send_message
          message_label: other_result
          to_triggering_node: true
```

| Field | Required | Description |
|---|---|---|
| `options` | yes | List of branch objects. Must have at least 2 entries. |
| `options[].weight` | yes | Relative weight for this branch. Must be > 0. Probability = weight / sum of all weights. |
| `options[].responses` | yes | List of responses to execute if this branch is chosen. At least one response required. |

**Notes:**
- Weights are relative — `[3, 1, 1]` gives 60%/20%/20%; `[1, 1]` gives 50%/50%.
- `random_options` can be nested: a branch's `responses` list may itself contain
  another `random_options` entry.

#### `with_node` — execute responses in the context of a selected node

Resolves a target to one or more node IDs and re-executes a set of inner
responses with each selected node as the triggering node. The primary use is
selecting a random node from a pool and then acting on it (e.g. creating a
dynamic waypoint at their location).

```yaml
- type: with_node
  to_all_with_flag: valid_target
  random_n: 1              # optional — pick N at random from the resolved set
  responses:
    - type: create_waypoint
      expiry_mins: 60
      initial_flags:
        - laser_target
    - type: send_message
      message_label: you_are_targeted
      to_triggering_node: true
```

| Field | Required | Description |
|---|---|---|
| target key | yes | Any node-resolving target (not `to_channel`). The inner responses fire once per resolved node. |
| `responses` | yes | List of inner responses. Each runs with the selected node as context. |

**Restrictions inside `with_node`:**
- `destroy_waypoint`, `add_waypoint_flag`, and `remove_waypoint_flag` are not
  valid inside `with_node` (no triggering waypoint context).
- `to_all_near_triggering_waypoint` is not valid inside `with_node`.

#### `create_waypoint` — place a dynamic waypoint at the triggering node's location

Creates a temporary waypoint at the current position of the triggering node.
The waypoint can carry flags and has an optional expiry timer.

```yaml
- type: create_waypoint
  expiry_mins: 60        # optional — waypoint self-destructs after this many minutes
  initial_flags:
    - laser_target        # flags applied to the new waypoint (must be defined in flags:)
```

| Field | Required | Description |
|---|---|---|
| `expiry_mins` | no | Minutes until the waypoint is automatically destroyed. Omit for a permanent waypoint. |
| `initial_flags` | no | List of flag labels to apply to the new waypoint at creation. |

**Restriction:** `create_waypoint` requires a trigger that provides node context
(`enters_zone`, `leaves_zone`, `near_waypoint`, `near_node`, `dm`, `channel`,
`flag_expired` with `target_kind: node`, or inside `with_node`). It cannot
appear directly in `time_window` or `in_zone_on_start` events.

#### `add_waypoint_flag` / `remove_waypoint_flag` — modify a dynamic waypoint's flags

Add or remove a flag on the *triggering dynamic waypoint* — the waypoint that
caused the current event to fire. Only valid in `near_waypoint + target_flag`
events and `flag_expired + target_kind: dynamic_waypoint` events.

```yaml
- type: add_waypoint_flag
  flag_label: detonated

- type: remove_waypoint_flag
  flag_label: armed
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label |

#### `destroy_waypoint` — delete the triggering dynamic waypoint

Immediately removes the triggering dynamic waypoint. Only valid in the same
contexts as `add_waypoint_flag`.

```yaml
- type: destroy_waypoint
```

---

### Targets

Every response (except `set_event_triggers`, `disable_event`, `enable_event`,
`add_waypoint_flag`, `remove_waypoint_flag`, and `destroy_waypoint`) requires
exactly one target key. The key determines which node(s), zone, or waypoint the
response acts on.

| Target key | Value type | Resolves to | Notes |
|---|---|---|---|
| `to_triggering_node: true` | boolean | The single node whose packet caused the event to fire | Not available in `time_window`, `in_zone_on_start`, `waypoint_expired`, or `flag_expired` with non-node `target_kind` |
| `to_node: <label>` | node label | The single hard-coded node with that label | |
| `to_channel: <label>` | channel label | Broadcasts the message on that channel | `send_message` only |
| `to_zone: <label>` | zone label | The zone object itself | `add_flag` / `remove_flag` only — sets the flag on the zone, not on individual nodes |
| `to_flag: <label>` | flag label | All nodes that currently carry that flag | |
| `to_waypoint_radius: {waypoint: <label>, meters: <n>}` | object | All nodes within `meters` of the waypoint | |
| `to_all_in_zone: <label>` | zone label | All nodes with a known location currently inside the zone | Supports `random_n` |
| `to_all_with_flag: <label>` | flag label | All nodes that currently carry that flag | Supports `random_n` |
| `to_all_near_waypoint: {waypoint: <label>, meters: <n>}` | object | All nodes within `meters` of the waypoint | Supports `random_n` |
| `to_all_near_node: {node: <label>, meters: <n>}` | object | All nodes within `meters` of the named hard-coded node (excluding the target node itself) | Both nodes must have known locations; supports `random_n` |
| `to_all_near_triggering_waypoint: {meters: <n>}` | object | All nodes within `meters` of the triggering dynamic waypoint | Only in `near_waypoint + target_flag` or `flag_expired + dynamic_waypoint` events; supports `random_n` |
| `to_group: <label>` | group label | All current members of the named group | Supports `random_n` |

**`random_n`:** Any target marked "supports `random_n`" accepts an optional
`random_n: <integer>` field on the response. If the resolved set is larger than
`random_n`, a random subset of exactly that size is used.

```yaml
- type: send_message
  message_label: targeted
  to_all_with_flag: valid_target
  random_n: 1           # DM only one random node from all valid targets
```

---

### Exceptions

Exceptions are skip conditions checked before any response is executed. If any
exception matches, the entire event is skipped (no responses fire, and
`times_triggered` is not incremented).

```yaml
exceptions:
  - kind: node_has_flag
    flag: winner                 # flags label

  - kind: zone_lacks_flag
    flag: game_active
    target: start_zone           # zones label
```

| Field | Required | Description |
|---|---|---|
| `kind` | yes | One of the exception kinds listed below |
| `flag` | conditional | A `flags` label. Required for all flag-check kinds. |
| `target` | conditional | Required for `zone_*` and `waypoint_*` kinds, and for zone/waypoint group kinds. |
| `chance` | conditional | Float 0.0–1.0. Required for `random_skip`. |
| `group` | conditional | A `groups` label. Required for `*_in_group` / `*_not_in_group` kinds. |

| Kind | Fields | Meaning |
|---|---|---|
| `node_has_flag` | `flag` | Skip if the triggering node has this flag |
| `node_lacks_flag` | `flag` | Skip if the triggering node does not have this flag |
| `zone_has_flag` | `flag`, `target` (zone) | Skip if the named zone has this flag |
| `zone_lacks_flag` | `flag`, `target` (zone) | Skip if the named zone does not have this flag |
| `waypoint_has_flag` | `flag`, optional `target` (waypoint) | Skip if the named (or triggering dynamic) waypoint has this flag |
| `waypoint_lacks_flag` | `flag`, optional `target` (waypoint) | Skip if the named (or triggering dynamic) waypoint does not have this flag |
| `node_in_group` | `group` | Skip if the triggering node is a member of this group |
| `node_not_in_group` | `group` | Skip if the triggering node is not a member of this group |
| `zone_in_group` | `group`, `target` (zone) | Skip if the named zone is a member of this group |
| `zone_not_in_group` | `group`, `target` (zone) | Skip if the named zone is not a member of this group |
| `waypoint_in_group` | `group`, `target` (waypoint) | Skip if the named waypoint is a member of this group |
| `waypoint_not_in_group` | `group`, `target` (waypoint) | Skip if the named waypoint is not a member of this group |
| `random_skip` | `chance` | Skip with probability `chance` (e.g. `0.3` = 30% chance of skipping) |

**Evaluation order:** All flag-check and group-check exceptions are evaluated
first. `random_skip` is rolled only if every deterministic exception passes. This
ensures a deterministic exception (e.g. "player already has the winner flag")
always takes precedence over randomness.

**Note:** For `time_window` and `in_zone_on_start` triggers there is no
triggering node, so `node_*` exceptions will never match and will not cause a skip.

```yaml
exceptions:
  - kind: node_has_flag
    flag: winner

  - kind: random_skip
    chance: 0.25          # 25% of the time, skip firing the event
```

---

## Full event example

```yaml
events:
  - label: find_treasure
    trigger:
      type: near_waypoint
      target: hidden_cache
      meters: 5
    responses:
      - type: send_message
        message_label: winner_message
        to_triggering_node: true
      - type: add_flag
        flag_label: winner
        to_triggering_node: true
      - type: remove_flag
        flag_label: has_clue
        to_triggering_node: true
      - type: request_location
        to_triggering_node: true
      - type: set_event_triggers
        event_label: near_cache_hint
        value: 99              # disable the "you're getting closer" hint
    exceptions:
      - kind: node_has_flag
        flag: winner           # don't re-award to someone who already won
      - kind: node_lacks_flag
        flag: has_clue         # must have collected the clue first
      - kind: zone_lacks_flag
        flag: game_active
        target: start_zone
    max_triggers: null         # unlimited — every player can win
    reset_mins: null           # no cooldown needed (max_triggers already gates repeats)
```

---

## Validation rules

The bot validates the config on startup and refuses to run if any of these
conditions are violated:

- Every label referenced in a trigger, response, or exception must be defined in
  the corresponding top-level section.
- `near_waypoint`, `near_zone`, and `near_node` triggers require `meters` to be set. `in_zone` and `in_zone_on_start` do not use `meters`.
- `near_waypoint` requires exactly one of `target` (static waypoint) or `target_flag` (dynamic waypoint), not both.
- `channel` triggers require `channel_label`.
- `zone_has_flag` / `zone_lacks_flag` exceptions require `target`.
- `waypoint_has_flag` / `waypoint_lacks_flag` without `target` are only valid in dynamic waypoint event contexts.
- `random_skip` exceptions require `chance` (float 0.0–1.0). `flag` and `target` are not used.
- `random_options` responses require at least 2 options, each with `weight > 0` and at least one response. All labels inside nested branches are validated the same way as top-level responses.
- Each `nodes` entry's `initial_flags` must all reference defined flags.
- `mutable_variables` labels must not duplicate any `variables` label.
- `mutable_variables` `type` must be `integer`, `float`, or `string`.
- `mutable_variables` `scope` must be `global` or `node`.
- `mutable_variables` `initial` must match the declared `type`.
- `mutable_variables` `min`/`max` are not valid for `type: string`.
- `mutable_variables` `initial` must be within `[min, max]` if both are set.
- `set_variable` / `increment_variable` on a `scope: node` variable require a target; on `scope: global` must not have a target.
- `increment_variable` is not valid for `type: string` variables.
- `create_waypoint` requires a trigger that provides node context.
- `destroy_waypoint`, `add_waypoint_flag`, `remove_waypoint_flag` require a dynamic waypoint context (`near_waypoint + target_flag` or `flag_expired + target_kind: dynamic_waypoint`).
- `to_all_near_triggering_waypoint` requires a dynamic waypoint context.
- `with_node` target cannot be `to_channel`.
- `with_node` must have at least one inner response.
- `destroy_waypoint`, `add_waypoint_flag`, `remove_waypoint_flag`, and `to_all_near_triggering_waypoint` are not valid inside `with_node`.
- `random_n` must be a positive integer when present.
- `groups` `kind` must be `node`, `zone`, or `waypoint`. `initial_members` must reference defined labels of the matching kind.
- Group exceptions (`*_in_group`, `*_not_in_group`) require `group`, which must reference a group of the matching kind.
- `variable_threshold` `operator` must be one of `lt`, `lte`, `eq`, `neq`, `gte`, `gt`.
- String-type mutable variables in `variable_threshold` only support `eq` and `neq`.
- `flag_expired` `target_kind` must be `node`, `zone`, `waypoint`, or `dynamic_waypoint`.
- All `{token}` references in message text must be defined variable labels or the built-in tokens `node_id` and `zone`.

Errors are reported with the event label and field that caused the problem, for
example:

```
ConfigError: Event 'find_treasure' trigger: label 'hiden_cache' not defined
```
