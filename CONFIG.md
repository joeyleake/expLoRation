# expLoRation Configuration Reference

The game is defined entirely by a single YAML file (default: `game.yaml`). Every
object — zones, messages, events — is referenced by a short string called a
**label**. Labels must be unique within their type. The bot validates all
cross-references on startup and exits with a descriptive error if any label is
missing or misused.

---

## Top-level structure

```yaml
channels:            [ ... ]
zones:               [ ... ]
waypoints:           [ ... ]
messages:            [ ... ]
flags:               [ ... ]
nodes:               [ ... ]
groups:              [ ... ]
variables:           [ ... ]
mutable_variables:   [ ... ]
events:              [ ... ]
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
- For `CommandTrigger`, the incoming message text is compared against `text`
  after stripping leading/trailing whitespace. Comparison is exact (case-sensitive).

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

Groups are named, typed collections of nodes, zones, or waypoints whose membership
is stored in SQLite and managed at runtime via `add_to_group` / `remove_from_group`
responses. They complement flags: flags track *state* ("has this node won?"), groups
track *membership* ("which team does this node belong to?").

```yaml
groups:
  - label: red_team
    kind: node                # "node" | "zone" | "waypoint"
    initial_members:          # optional — members seeded at startup
      - node_alpha
      - node_beta

  - label: active_zones
    kind: zone

  - label: required_checkpoints
    kind: waypoint
    initial_members:
      - checkpoint_1
      - checkpoint_2
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used in responses, targets, and exceptions |
| `kind` | string | yes | `node`, `zone`, or `waypoint` — the type of members this group holds |
| `initial_members` | list of labels | no | Members of the appropriate kind seeded when the bot starts |

**Notes:**
- `initial_members` entries must be valid labels for the group's `kind` (node labels for
  `kind: node`, zone labels for `kind: zone`, waypoint labels for `kind: waypoint`).
- Startup seeding is additive and non-destructive: restarting the bot re-adds `initial_members`
  but does **not** remove members that were added dynamically at runtime. Group membership is
  persistent across restarts — it is not reset like expiring flags.
- Groups with no `initial_members` start empty and are populated entirely by `add_to_group`
  responses at runtime.

---

## Variables

Variables compute live values from engine state and are interpolated into
message text at send time using `{variable_label}` tokens. All values are
read-only — computed on demand, stored nowhere.

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

**Message interpolation:**

Place `{variable_label}` anywhere in a message `text` field. Tokens are replaced
at send time with the resolved value. If resolution fails (missing context, no
known location, etc.) the token is replaced with a fallback string:

- `[unknown]` — label undefined or required data unavailable
- `[no node context]` — `scope: node` variable used in an event with no triggering node
- `[no nodes]` — no eligible nodes for `nearest_node_*`

All variable labels referenced in message text are validated at startup.

```yaml
messages:
  - label: status
    text: "There are {hunters_in_zone} hunters in the area. You are {dist_to_cache}m from the cache."
```

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

Returns the count of current members in the target group. Works for groups of any kind.

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

Mutable variables are writable, typed, persisted values that event responses can modify at
runtime. They complement the read-only computed `variables:` (which track counts, distances,
and other derived state) — mutable variables hold values that the game logic actively changes,
like HP, score counters, or a phase string.

All mutable variable state lives in SQLite and survives bot restarts. On startup the bot
inserts an initial row for each variable using `INSERT OR IGNORE`, so restarting mid-game
does **not** reset values to their initial defaults.

```yaml
mutable_variables:
  - label: hp
    type: integer
    scope: node
    initial: 100
    min: 0
    max: 100

  - label: score
    type: integer
    scope: global
    initial: 0
    min: 0

  - label: game_phase
    type: string
    scope: global
    initial: waiting
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | yes | Unique name used in responses, triggers, and message interpolation. Must not duplicate any label in `variables:` |
| `type` | string | yes | `integer`, `float`, or `string` |
| `scope` | string | yes | `global` (one value shared across all nodes) or `node` (separate value per node) |
| `initial` | any | yes | Starting value. Must be type-compatible (int for integer, numeric for float, string for string) |
| `min` | number | no | Lower bound, enforced on every write. Numeric types only |
| `max` | number | no | Upper bound, enforced on every write. Numeric types only |

**Notes:**
- `min`/`max` are enforced via clamping on every write — a value can never go outside the
  declared bounds regardless of the increment amount.
- Labels must be unique across both `variables:` and `mutable_variables:` since they share
  the `{label}` interpolation namespace in messages.
- For `scope: node`, per-node rows are created on first write. Reading before the first write
  returns the `initial` value.

### Modifying mutable variables: response types

#### `set_variable`

Sets a mutable variable to a static value.

```yaml
responses:
  - type: set_variable
    variable_label: game_phase
    value: active            # global-scoped: no target

  - type: set_variable
    variable_label: hp
    value: 100
    to_triggering_node: true  # node-scoped: target required
```

| Field | Required | Description |
|---|---|---|
| `variable_label` | yes | Label of a `mutable_variables:` entry |
| `value` | yes | Value to set. Must be compatible with the variable's `type` |
| target | node-scoped only | Any node-resolving target (`to_triggering_node`, `to_node`, `to_all_in_zone`, etc.). Must be omitted for `scope: global` |

#### `increment_variable`

Adds an amount to a numeric mutable variable (use a negative amount to decrement). The result
is clamped to `[min, max]` if bounds are defined. Not valid for `type: string`.

```yaml
responses:
  - type: increment_variable
    variable_label: score
    amount: 10              # global-scoped: no target

  - type: increment_variable
    variable_label: hp
    amount: -25
    to_triggering_node: true  # node-scoped: target required
```

| Field | Required | Description |
|---|---|---|
| `variable_label` | yes | Label of a numeric (`integer` or `float`) `mutable_variables:` entry |
| `amount` | yes | Number to add (positive or negative) |
| target | node-scoped only | Any node-resolving target. Must be omitted for `scope: global` |

### Triggering on a value: `variable_threshold`

Fires when a mutable variable satisfies a comparison against a threshold value. This trigger
is **level-triggered**: it fires whenever the condition is true on each evaluation cycle, not
only when the value first crosses the threshold. Use `reset_mins` to prevent repeat firing.

- **Global-scoped** variables: evaluated on every periodic tick (`--periodic` interval).
- **Node-scoped** variables: evaluated on every position update for that node.

```yaml
events:
  - label: elimination
    trigger:
      type: variable_threshold
      variable: hp           # label of the mutable variable (key is "variable:", not "variable_label:")
      operator: lte
      value: 0
    responses:
      - type: add_flag
        flag_label: eliminated
        to_triggering_node: true
    exceptions:
      - kind: node_has_flag
        flag: eliminated
    reset_mins: 1
```

| Field | Required | Description |
|---|---|---|
| `variable` | yes | Label of a `mutable_variables:` **or** `variables:` (computed) entry |
| `operator` | yes | Comparison operator (see table below) |
| `value` | yes | Threshold to compare against. Must be type-compatible with the variable |

Computed variables resolve their current value at evaluation time (e.g. `flag_count` returns the live count). String mutable variables only support `eq` / `neq`; numeric mutable and computed variables support all operators.

**Operators:**

| Operator | Meaning |
|---|---|
| `lt` | less than |
| `lte` | less than or equal |
| `eq` | equal |
| `neq` | not equal |
| `gte` | greater than or equal |
| `gt` | greater than |

`lt`, `lte`, `gte`, `gt` are only valid for numeric types (`integer`, `float`). String variables
support only `eq` and `neq`.

### Interpolating mutable variables in messages

Mutable variable labels can be used in message text with the same `{label}` syntax as computed
variables:

```yaml
messages:
  - label: status
    text: "HP: {hp} | Score: {score} | Phase: {game_phase}"
```

For `scope: node` variables, the value interpolated is the triggering node's value.

### Built-in interpolation tokens

Two tokens are always available in message text without being declared as variables:

| Token | Resolves to |
|---|---|
| `{node_id}` | The triggering node's ID (e.g. `!6984ec24`). Useful in `enters_zone`, `flag_expired + target_kind: node`, and any node-context event. Resolves to `[unknown]` if there is no node context. |
| `{zone}` | A zone the triggering node is currently in. In `enters_zone` events this is the entered zone. In other node-context events (including `with_node` inner responses) it falls back to the node's last known zone. Resolves to `[unknown]` if the node has no known zone. |

### Worked example: HP system

```yaml
mutable_variables:
  - label: hp
    type: integer
    scope: node
    initial: 100
    min: 0
    max: 100

flags:
  - label: eliminated

messages:
  - label: damage_notice
    text: "You took a hit! HP remaining: {hp}"
  - label: eliminated_notice
    text: "You have been eliminated."

zones:
  - label: danger_zone
    points:
      - [37.77, -122.42]
      - [37.78, -122.42]
      - [37.77, -122.41]

events:
  # Deal 25 damage on zone entry (once per minute)
  - label: take_damage
    trigger:
      type: enters_zone
      target: danger_zone
    responses:
      - type: increment_variable
        variable_label: hp
        amount: -25
        to_triggering_node: true
      - type: send_message
        message_label: damage_notice
        to_triggering_node: true
    exceptions:
      - kind: node_has_flag
        flag: eliminated
    reset_mins: 1

  # Eliminate when HP reaches zero (checked on every position update)
  - label: elimination
    trigger:
      type: variable_threshold
      variable: hp
      operator: lte
      value: 0
    responses:
      - type: add_flag
        flag_label: eliminated
        to_triggering_node: true
      - type: send_message
        message_label: eliminated_notice
        to_triggering_node: true
    exceptions:
      - kind: node_has_flag
        flag: eliminated
```

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
within `meters` of a waypoint. The waypoint can be a **static** waypoint defined
in config (`target`) or any **dynamic** waypoint carrying a specified flag (`target_flag`).

**Static waypoint (config-defined):**

```yaml
trigger:
  type: near_waypoint
  target: hidden_cache     # waypoint label
  meters: 20               # radius in metres
```

**Dynamic waypoint (runtime-created, matched by flag):**

```yaml
trigger:
  type: near_waypoint
  target_flag: gravestone  # fires against any live dynamic waypoint with this flag
  meters: 20
```

| Field | Required | Description |
|---|---|---|
| `target` | one of `target`/`target_flag` | A `waypoints` label (static config waypoint) |
| `target_flag` | one of `target`/`target_flag` | A `flags` label. Fires against any live dynamic waypoint carrying this flag. |
| `meters` | yes | Radius in metres. The trigger fires if the node is within this distance. |

**Dynamic waypoint matching:**
- When `target_flag` is used, all non-expired dynamic waypoints carrying that flag are checked.
- If multiple qualifying waypoints are within range, the nearest one wins.
- The matched waypoint's ID is stored in event context as `triggering_waypoint_id` and is available to
  companion response types (`add_waypoint_flag`, `remove_waypoint_flag`, `destroy_waypoint`) and to
  targetless `waypoint_has_flag` / `waypoint_lacks_flag` exceptions.
- Exactly one of `target` or `target_flag` must be specified — using both or neither is a config error.

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
defined message. If `zone_label` is set, the sender must also be inside that zone.

```yaml
trigger:
  type: dm
  message_label: hint_request    # messages label — text must match exactly
  zone_label: start_zone         # optional — restrict to senders inside this zone
```

| Field | Required | Description |
|---|---|---|
| `message_label` | yes | A `messages` label. The incoming DM text is compared to `message.text` after stripping whitespace. |
| `zone_label` | no | A `zones` label. If set, the sender must have a known location inside this zone. If omitted, any sender can trigger the event regardless of location. |

**Note:** When `zone_label` is omitted, a sender with no known GPS fix can still trigger the event. If you need to gate on location, include `zone_label`.

#### `flag_expired` — a flag's timer ran out

Fires when a flag with an `expiry_mins` setting reaches its expiry time and is deleted. Fires
once per expired (entity, flag) pair — if three nodes' `stunned` flag expires in the same tick,
the event fires three times, each with the appropriate entity as context.

```yaml
trigger:
  type: flag_expired
  flag_label: stunned          # flags label — must have expiry_mins set to ever fire
  target_kind: node            # "node" | "zone" | "waypoint" | "dynamic_waypoint"
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label |
| `target_kind` | yes | The kind of entity that lost the flag: `node`, `zone`, `waypoint`, or `dynamic_waypoint` |

**Context by `target_kind`:**

| `target_kind` | Triggering context | `to_triggering_node` valid? | Waypoint responses valid? |
|---|---|---|---|
| `node` | The node whose flag expired | yes | no |
| `zone` | None (like `time_window`) | no | no |
| `waypoint` | None | no | no |
| `dynamic_waypoint` | The dynamic waypoint whose flag expired | no | `add_waypoint_flag`, `remove_waypoint_flag` only |

**Notes:**
- `flag_expired` does NOT fire when a flag is removed via a `remove_flag` response — only when a timer naturally expires.
- `flag_expired` does NOT fire for flags cascade-deleted when a dynamic waypoint itself expires. Use `waypoint_expired` for that.
- `destroy_waypoint` is not valid in `flag_expired` events; the waypoint is still alive when a flag on it expires.
- For `target_kind: dynamic_waypoint`, targetless `waypoint_has_flag` / `waypoint_lacks_flag` exceptions check the triggering dynamic waypoint (same as `near_waypoint + target_flag` events).

#### `waypoint_expired` — a dynamic waypoint's timer ran out

Fires when a dynamic waypoint created by `create_waypoint` reaches its `expiry_mins` limit and
is deleted. Fires once per expired waypoint. The waypoint and all its flags are already deleted
by the time the event fires; this is the opportunity to react to the disappearance.

```yaml
trigger:
  type: waypoint_expired
  had_flag: gravestone        # optional — only fire for waypoints that had this flag
```

| Field | Required | Description |
|---|---|---|
| `had_flag` | no | A `flags` label. If set, only fires for waypoints that carried this flag at the time they expired. Omit to fire for all expired dynamic waypoints. |

**Notes:**
- No triggering node or live waypoint context. `to_triggering_node`, `add_waypoint_flag`, `remove_waypoint_flag`, and `destroy_waypoint` are all invalid in responses.
- Useful for: channel broadcasts, flag operations on nodes, event enable/disable.
- Each dynamic waypoint can carry multiple flags; `had_flag` checks membership in the set of flags the waypoint held at expiry, not whether the flag itself expired first.

#### `channel` — node sends a matching message on a monitored channel

Fires when any node broadcasts a message on a specific channel whose text
matches a defined message. If `zone_label` is set, the sender must also be inside that zone.

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
| `zone_label` | no | A `zones` label — if set, sender must be inside this zone |
| `channel_label` | yes | A `channels` label — message must arrive on this channel |

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

#### `add_to_group` — add member(s) to a group

Adds one or more members to a group. For `kind: node` groups the target is any
node-resolving key. For `kind: zone` groups use `to_zone`. For `kind: waypoint`
groups use `to_waypoint_radius` (the waypoint label is extracted; the radius is
ignored for membership purposes).

```yaml
- type: add_to_group
  group_label: red_team
  to_triggering_node: true    # node group — target is node-resolving

- type: add_to_group
  group_label: active_zones
  to_zone: north_sector       # zone group — target must be a zone
```

| Field | Required | Description |
|---|---|---|
| `group_label` | yes | A `groups` label |
| target key | yes | Must match the group's `kind` |

#### `remove_from_group` — remove member(s) from a group

Removes one or more members from a group. Same target rules as `add_to_group`.

```yaml
- type: remove_from_group
  group_label: red_team
  to_triggering_node: true
```

| Field | Required | Description |
|---|---|---|
| `group_label` | yes | A `groups` label |
| target key | yes | Must match the group's `kind` |

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

#### `create_waypoint` — stamp a dynamic waypoint at the triggering node's location

Creates a new dynamic waypoint at the triggering node's current GPS position. The waypoint
exists only in the runtime database — it does not require any config declaration. Other events
can match against it using `near_waypoint` with `target_flag`.

```yaml
- type: create_waypoint
  expiry_mins: 60           # optional — waypoint is deleted after this many minutes
  initial_flags:            # optional — flags applied to the waypoint on creation
    - gravestone
```

| Field | Required | Description |
|---|---|---|
| `expiry_mins` | no | Minutes until the waypoint and all its flags are automatically deleted. Omit for a permanent waypoint. |
| `initial_flags` | no | List of `flags` labels to attach to the waypoint at creation time. Each flag's own `expiry_mins` (from its definition) applies independently. |

**Notes:**
- Requires a triggering node with a known GPS fix. If the node has no location, the response is skipped with a warning.
- Not valid in `time_window` or `in_zone_on_start` events, which have no triggering node.
- Waypoint expiry is cascade-deleted: when the waypoint expires, all of its flags are also deleted in the same transaction.
- The created waypoint has an auto-increment integer ID (not a label) and is accessed by other events exclusively through `target_flag` matching.

#### `add_waypoint_flag` — add a flag to the triggering dynamic waypoint

Adds a flag to the dynamic waypoint that triggered the current event. Only valid in
events whose trigger is `near_waypoint` with `target_flag`.

```yaml
- type: add_waypoint_flag
  flag_label: looted        # flags label
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label. The flag's own `expiry_mins` applies. |

#### `remove_waypoint_flag` — remove a flag from the triggering dynamic waypoint

Removes a flag from the dynamic waypoint that triggered the current event. Only valid in
events whose trigger is `near_waypoint` with `target_flag`.

```yaml
- type: remove_waypoint_flag
  flag_label: looted
```

| Field | Required | Description |
|---|---|---|
| `flag_label` | yes | A `flags` label |

#### `destroy_waypoint` — delete the triggering dynamic waypoint

Permanently deletes the dynamic waypoint that triggered the current event, along with
all of its flags. Only valid in events whose trigger is `near_waypoint` with `target_flag`.

```yaml
- type: destroy_waypoint
```

No additional fields — the waypoint to destroy is always the one that triggered the event.

---

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
- Each nested branch is validated at startup just like top-level responses —
  all label references must resolve.
- `times_triggered` is incremented once per event firing regardless of which
  branch was chosen.

#### `with_node` — execute responses in the context of a selected node

Resolves a target to one or more nodes and executes the inner `responses` list as if each selected
node had triggered the event. Provides a full `NodeContext` to inner responses — including
`to_triggering_node` (which refers to the selected node) and `create_waypoint` (which stamps a
waypoint at that node's GPS position).

This is the primary way to use `create_waypoint` from `time_window`, `in_zone_on_start`, or any
other periodic trigger that has no triggering node.

```yaml
- type: with_node
  to_all_with_flag: valid_target    # any node-resolving target; supports random_n
  random_n: 1                       # optional — select 1 node at random from the resolved list
  responses:
    - type: create_waypoint
      expiry_mins: 60
      initial_flags:
        - laser_target
    - type: send_message
      message_label: target_locked
      to_channel: comms
```

| Field | Required | Description |
|---|---|---|
| target key | yes | Any node-resolving target key (all targets except `to_channel`). Supports `random_n`. |
| `responses` | yes | List of responses to execute per selected node. Same syntax as top-level responses. |

**Notes:**
- If the selected node has no known location, it is skipped with a log warning and the next node
  (if any) is tried. This matters for `create_waypoint`, which requires coordinates.
- `to_triggering_node` inside `with_node` refers to the currently selected node.
- `with_node` may be nested inside `random_options` branches or inside another `with_node`. Nesting multiplies the node pool: `random_n: 5` outer × `random_n: 5` inner = up to 25 inner executions. Deep nesting with large unsampled pools can be expensive — use `random_n` to bound execution.
- `destroy_waypoint`, `add_waypoint_flag`, and `remove_waypoint_flag` are not valid inside
  `with_node` responses (no triggering waypoint context is provided).
- If the resolved node list is empty (no nodes carry the target flag, or `random_n` sampling
  results in an empty draw), the response is skipped with a log warning.

**Example — orbital cannon targeting a random registered pilot:**

```yaml
# Every hour, pick one random pilot node and stamp a waypoint at their location.
# The waypoint's 30-min expiry triggers the blast event.
- label: cannon_selector
  trigger:
    type: time_window
    start: "2020-01-01T00:00:00"
    end:   "2099-01-01T00:00:00"
  auto_recur: true
  recur_mins: 60
  responses:
    - type: with_node
      to_all_with_flag: player
      random_n: 1
      responses:
        - type: create_waypoint
          expiry_mins: 30
          initial_flags:
            - laser_target
        - type: send_message
          message_label: target_locked
          to_channel: comms
```

---

### Targets

Every response (except `set_event_triggers`) requires exactly one target key.
The key determines which node(s), zone, or waypoint the response acts on.

| Target key | Value type | Resolves to | Notes |
|---|---|---|---|
| `to_triggering_node: true` | boolean | The single node whose packet caused the event to fire | Not available in `time_window` or `in_zone_on_start` events, which have no triggering node |
| `to_node: <label>` | node label | The single hard-coded node with that label | |
| `to_channel: <label>` | channel label | Broadcasts the message on that channel | `send_message` only |
| `to_zone: <label>` | zone label | The zone object itself | `add_flag` / `remove_flag` only — sets the flag on the zone, not on individual nodes |
| `to_flag: <label>` | flag label | All nodes that currently carry that flag | Supports `random_n` |
| `to_waypoint_radius: {waypoint: <label>, meters: <n>}` | object | All nodes within `meters` of the waypoint | Supports `random_n` |
| `to_all_in_zone: <label>` | zone label | All nodes with a known location currently inside the zone | Supports `random_n` |
| `to_all_with_flag: <label>` | flag label | All nodes that currently carry that flag | Supports `random_n` |
| `to_all_near_waypoint: {waypoint: <label>, meters: <n>}` | object | All nodes within `meters` of the waypoint | Supports `random_n` |
| `to_all_near_node: {node: <label>, meters: <n>}` | object | All nodes within `meters` of the named hard-coded node (excluding the target node itself) | Both nodes must have known locations. Supports `random_n` |
| `to_all_near_triggering_waypoint: {meters: <n>}` | object | All nodes within `meters` of the dynamic waypoint that triggered the current event | Only valid in `near_waypoint + target_flag` and `flag_expired + target_kind: dynamic_waypoint` events. Supports `random_n`. Not valid inside `with_node`. |
| `to_group: <label>` | group label | For `kind: node` groups: all member nodes (send_message, request_location, add/remove_flag, add/remove_from_group). For `kind: zone` or `kind: waypoint` groups: all member zones/waypoints (add/remove_flag only). | Supports `random_n` for `kind: node` groups |

**`random_n` — random sampling from multi-node targets**

Any target marked "Supports `random_n`" above accepts an optional `random_n` field. When set,
the resolved node list is randomly sampled down to at most `random_n` nodes before the response
is applied. If fewer nodes are resolved than `random_n`, all of them are used.

```yaml
- type: send_message
  message_label: chosen
  to_all_in_zone: play_area
  random_n: 3              # pick 3 random nodes from the zone
```

```yaml
- type: add_flag
  flag_label: targeted
  to_all_with_flag: active_player
  random_n: 1              # tag one random active player
```

`random_n` must be a positive integer. It is not valid on single-node targets (`to_triggering_node`, `to_node`) or non-node targets (`to_channel`, `to_zone`).

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
| `group` | conditional | A `groups` label. Required for all `*_in_group` kinds. |
| `target` | conditional | Required for `zone_*`, `zone_in_group`, and `waypoint_in_group` kinds, and for static-waypoint `waypoint_*` kinds. Omit for `node_*` kinds and for dynamic-waypoint `waypoint_*` checks (see below). |
| `chance` | conditional | Float 0.0–1.0. Required for `random_skip`. |

| Kind | Fields | Meaning |
|---|---|---|
| `node_has_flag` | `flag` | Skip if the triggering node has this flag |
| `node_lacks_flag` | `flag` | Skip if the triggering node does not have this flag |
| `zone_has_flag` | `flag`, `target` (zone) | Skip if the named zone has this flag |
| `zone_lacks_flag` | `flag`, `target` (zone) | Skip if the named zone does not have this flag |
| `waypoint_has_flag` | `flag`, `target` (waypoint, optional) | Skip if the named waypoint has this flag. If `target` is omitted, checks the **triggering dynamic waypoint** instead (only valid in `near_waypoint target_flag` events). |
| `waypoint_lacks_flag` | `flag`, `target` (waypoint, optional) | Skip if the named waypoint does not have this flag. If `target` is omitted, checks the **triggering dynamic waypoint** (only valid in `near_waypoint target_flag` events). |
| `node_in_group` | `group` | Skip if the triggering node is a member of this node-kind group |
| `node_not_in_group` | `group` | Skip if the triggering node is not a member of this node-kind group |
| `zone_in_group` | `group`, `target` (zone) | Skip if the named zone is a member of this zone-kind group |
| `zone_not_in_group` | `group`, `target` (zone) | Skip if the named zone is not a member of this zone-kind group |
| `waypoint_in_group` | `group`, `target` (waypoint) | Skip if the named waypoint is a member of this waypoint-kind group |
| `waypoint_not_in_group` | `group`, `target` (waypoint) | Skip if the named waypoint is not a member of this waypoint-kind group |
| `random_skip` | `chance` | Skip with probability `chance` (e.g. `0.3` = 30% chance of skipping) |

**Evaluation order:** All deterministic exceptions (flag checks, group checks) are evaluated first.
`random_skip` is rolled only if every deterministic exception passes. This ensures a deterministic
exception (e.g. "player already has the winner flag") always takes precedence over randomness.

**Note:** For `time_window` and `in_zone_on_start` triggers there is no
triggering node, so `node_has_flag`, `node_lacks_flag`, `node_in_group`, and
`node_not_in_group` exceptions will never match and will not cause a skip.

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
- `near_waypoint` requires exactly one of `target` (static waypoint label) or `target_flag` (flag label). Using both or neither is a config error.
- `target_flag` is only valid on `near_waypoint`. Using it on any other trigger kind is a config error.
- `channel` triggers require `channel_label`.
- `zone_has_flag` / `zone_lacks_flag` exceptions require `target`.
- `waypoint_has_flag` / `waypoint_lacks_flag` with `target` set require `target` to be a defined waypoint label. Without `target`, they check the triggering dynamic waypoint and are only valid in `near_waypoint target_flag` events.
- `random_skip` exceptions require `chance` (float 0.0–1.0). `flag` and `target` are not used.
- `random_options` responses require at least 2 options, each with `weight > 0` and at least one response. All labels inside nested branches are validated the same way as top-level responses.
- `with_node` responses require at least one inner response. `to_channel` is not valid as the `with_node` target. `destroy_waypoint`, `add_waypoint_flag`, `remove_waypoint_flag`, and `to_all_near_triggering_waypoint` are not valid inside `with_node` inner responses.
- `to_all_near_triggering_waypoint` is only valid in events with a dynamic waypoint context (`near_waypoint + target_flag` and `flag_expired + target_kind: dynamic_waypoint`). It is not valid in `with_node` inner responses.
- `random_n` must be a positive integer when set. It is not valid on single-node or non-node targets.
- `create_waypoint` responses are not valid in `time_window`, `in_zone_on_start`, `waypoint_expired`, or `flag_expired` events with `target_kind` other than `node` (no triggering node).
- `destroy_waypoint` is only valid in `near_waypoint + target_flag` events.
- `add_waypoint_flag` and `remove_waypoint_flag` are valid in `near_waypoint + target_flag` events and in `flag_expired` events with `target_kind: dynamic_waypoint`. They are not valid in `waypoint_expired` events (the waypoint is already gone).
- `to_triggering_node` is not valid in events with no node context: `time_window`, `in_zone_on_start`, `waypoint_expired`, and `flag_expired` with `target_kind` other than `node`.
- `flag_expired` triggers require `flag_label` (a defined flag) and `target_kind` (one of `node`, `zone`, `waypoint`, `dynamic_waypoint`).
- `waypoint_expired` trigger's `had_flag`, if set, must reference a defined flag.
- `waypoint_has_flag` / `waypoint_lacks_flag` exceptions without `target` are valid in `near_waypoint + target_flag` events and `flag_expired + target_kind: dynamic_waypoint` events.
- Each `nodes` entry's `initial_flags` must all reference defined flags.
- `groups` entries require `kind` to be `node`, `zone`, or `waypoint`.
- Each `groups` entry's `initial_members` must reference labels of the appropriate kind.
- `add_to_group` / `remove_from_group` responses require a valid `group_label`.
- `node_in_group` / `node_not_in_group` exceptions require `group` pointing to a `kind: node` group.
- `zone_in_group` / `zone_not_in_group` exceptions require `group` (a `kind: zone` group) and `target` (a zone label).
- `waypoint_in_group` / `waypoint_not_in_group` exceptions require `group` (a `kind: waypoint` group) and `target` (a waypoint label).
- `group_count` variables require `target` to be a defined group label.

Errors are reported with the event label and field that caused the problem, for
example:

```
ConfigError: Event 'find_treasure' trigger: label 'hiden_cache' not defined
```
