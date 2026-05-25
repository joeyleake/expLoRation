---
name: yaml-builder
description: >
  Generates expLoRation YAML configuration files from natural language descriptions.
  Use this skill when the user explicitly asks to create, write, or build an
  expLoRation YAML file or scenario — for example "create a yaml for a capture
  the flag game", "write an expLoRation config for a guided nature walk", or
  "build a scenario where nodes earn points for entering zones". Do NOT trigger
  for questions about how expLoRation works, requests to explain the schema, or
  edits to an existing YAML the user has pasted — only trigger when the user
  wants a new YAML file generated from scratch.
---

# expLoRation YAML Builder

You are generating a YAML configuration file for expLoRation, a YAML-defined
event engine for Meshtastic mesh networks that turns GPS-tracked nodes into
triggers for real-world interactive experiences.

## Required reading

Before generating any YAML, read the full schema reference:

```
references/CONFIG.md
```

This is mandatory — do not rely on memory for field names, trigger types,
response types, or validation rules. The schema has evolved significantly and
your training data may be outdated.

## Process

### Step 1 — Ask clarifying questions

Before writing any YAML, ask the user the questions below that are relevant
to their scenario. Not all questions apply to every scenario — use judgment.
Ask them all in a single message, not one at a time.

**Always ask:**
- What is the play area? (approximate real-world location, or fictional/placeholder coords OK)
- What should happen and when? (the core game loop in plain English)
- What Meshtastic channel should the bot broadcast on?

**Ask if relevant:**
- Are there teams or factions? How do nodes join them?
- Is there a win condition? How does the game end?
- Should new nodes be able to join mid-game, or is enrollment locked at start?
- How long should the game run / how often should events recur?
- Should there be a status broadcast? How often?
- Are there any random/chance elements?

Do not proceed to generation until you have answers to at least the always-ask
questions.

### Step 2 — Generate a draft

Generate a complete, runnable YAML file. Follow these rules:

**Structure**
- Include all required sections: `channels`, `flags`, `messages`, `events`
- Include `zones`, `waypoints`, `nodes`, `variables`, `mutable_variables`,
  `groups` only as needed
- Use placeholder coordinates (SF area: 37.77°N, 122.41°W) if the user hasn't
  provided real ones — add a comment saying `# CONFIGURE: replace with real coordinates`
- Use `AQ==` as the default PSK unless the user specifies otherwise
- Never use real coordinates or real node IDs in generated output — use the SF
  placeholder area and generic node IDs like `!aabbccdd`, `!11223344`

**Labels**
- Labels must be unique within their type
- Use snake_case, descriptive, lowercase: `player_enters_zone` not `event1`
- Message labels describe content: `target_locked` not `msg3`

**Events**
- Every event needs at least one trigger and one response
- Add exception guards defensively: if a node can only win once, add
  `node_has_flag: winner` exception; if game can end, add `zone_has_flag: game_over` exceptions
- Use `reset_mins` to prevent event spam
- Use `trigger_per_node: true` for events that should fire once per node
  rather than once globally

**Flags**
- Define all flags in the `flags:` section before using them
- Use `expiry_mins` for transient state (stun, blast radius, targeting lock)
- Permanent flags (eliminated, winner, destroyed) omit `expiry_mins`

**Messages**
- Write real, evocative message text — not placeholders like "You have entered the zone"
- For game announcements, use emoji sparingly for visual scanning
- Multi-line messages use YAML `|` block scalar
- Messages longer than ~180 chars will be split by the engine — design accordingly
- Use `{node_id}` for the raw hex ID, `{node_shortname}` for the 4-char callsign, or `{node_longname}` for the full display name when naming the triggering node in announcements; prefer shortname/longname for player-facing messages
- Use `{zone}` to name the zone in messages where it adds context

**Templated commands (variable capture):**

Place exactly one `{mutable_variable_label}` token in a `dm` or `channel` message
text to turn it into a capture command. Everything before the token is the fixed
prefix; everything after is the fixed suffix. The captured text is stored in the
named variable for the triggering node before responses fire.

```yaml
- label: player_name
  type: string
  scope: node      # must be scope: node
  initial: "unknown"
  max_length: 32   # apply max_length on string vars used in broadcasts

messages:
  - label: setname_cmd
    text: "!setname {player_name}"
```

**Alerts (`send_alert`):**

Use `send_alert` instead of `send_message` when the message represents a genuine
safety or urgency situation — for example, notifying a player who has entered a
restricted or dangerous area. Alerts are sent as `TEXT_MESSAGE_APP` with
`Priority.ALERT`, so they appear as normal text in all clients but receive
preferential routing through the mesh. On nodes with the External Notification
module configured, they may also trigger hardware buzzers or vibration.

```yaml
- type: send_alert
  message_label: danger_msg
  to_triggering_node: true
```

**Node hardware and telemetry variables:**

Nine node-scoped `tracks` values expose live data from the bot's nodedb:

| `tracks` value | Returns |
|---|---|
| `node_battery_level` | Battery % (integer) |
| `node_voltage` | Supply voltage (e.g. `3.85`) |
| `node_channel_utilization` | Channel utilization % |
| `node_air_util_tx` | TX air utilization % |
| `node_uptime_seconds` | Seconds since last boot |
| `node_snr` | SNR of last received packet |
| `node_hops_away` | Hop count from bot's radio |
| `node_hw_model` | Hardware model string (e.g. `TBEAM`) |
| `node_role` | Node role (e.g. `CLIENT`, `ROUTER`) |

All require `scope: node`. Telemetry values are only as fresh as the last
telemetry broadcast — use `request_telemetry` to prompt a fresh update. Use
`request_telemetry` in the same event as a `variable_threshold` or DM command
to keep values current.

**Security considerations for captured values:**
- Captured values come from untrusted radio nodes — treat them like user input.
- Captured values are stored as **literals** and are never re-interpolated. A player
  who sends `!setname {node_id}` stores the text `{node_id}`, not their real ID.
- Apply `max_length` on any string variable used in broadcast messages to prevent
  a malicious player from flooding the channel with long text.
- Prefer `type: integer` or `type: float` with `min`/`max` bounds for numeric inputs:
  type mismatch blocks the trigger automatically, no extra validation needed.

**Common patterns to apply correctly:**

*Warmer/colder direction tracking:*

`distance_change_to_waypoint` returns negative when the node moved closer and
positive when it moved farther. Since exception logic only supports flag checks,
direction is tracked by setting flags on position update and routing hint
commands via those flags.

```yaml
variables:
  - label: hint_delta
    scope: node
    tracks: distance_change_to_waypoint
    target: hidden_cache

flags:
  - label: dir_closer
  - label: dir_farther

events:
  - label: mark_dir_closer
    trigger:
      type: variable_threshold
      variable: hint_delta
      operator: lt
      value: -1            # moved more than 1m closer
    trigger_per_node: true
    responses:
      - type: add_flag
        flag_label: dir_closer
        to_triggering_node: true
      - type: remove_flag
        flag_label: dir_farther
        to_triggering_node: true

  - label: hint_warmer
    trigger:
      type: dm
      message_label: hint_cmd
    trigger_per_node: true
    exceptions:
      - kind: node_lacks_flag
        flag: dir_closer    # skip if node has NOT moved closer
    responses:
      - type: send_message
        message_label: hint_warmer_msg
        to_triggering_node: true
```

The `hint_same` variant fires when NEITHER flag is present (both `node_has_flag`
exceptions skip it). The `hint_colder` variant fires when `dir_farther` is set
AND `dir_closer` is NOT set (add a `node_has_flag: dir_closer` exception).

*Stale location refresh:*

`seconds_since_last_update` returns seconds since the node's last GPS packet.
Use with `variable_threshold` to silently request fresh positions when a node
DMs the bot but hasn't updated recently. The trigger evaluates at DM receipt
time — no changes to the DM event are needed.

```yaml
variables:
  - label: seconds_since_update
    scope: node
    tracks: seconds_since_last_update

events:
  - label: refresh_stale_location
    trigger:
      type: variable_threshold
      variable: seconds_since_update
      operator: gte
      value: 300           # 5 minutes
    trigger_per_node: true
    reset_mins: 5          # at most once per node per 5 minutes
    responses:
      - type: request_location
        to_triggering_node: true
```

*Previous distance and movement delta:*

`prev_distance_to_waypoint` is the distance from the node's *previous* recorded position
to the waypoint (metres, integer). Pair it with `distance_to_waypoint` when you need to
show both "was" and "now" distances in the same message.

`distance_change_to_waypoint` subtracts prev from current: negative = closer, positive =
farther (one decimal place). Use it as the `variable_threshold` trigger for direction
flags rather than comparing the two distance variables yourself.

`current_position` and `prev_position` return `"lat, lon"` to five decimal places for the
node's current and previous fixes respectively. Useful for debug messages or recording
where a player was when an event fired.

All four require `scope: node`. `prev_*` variants return `[unknown]` until the node has sent
at least two position updates.

*Mutable variable counter with upgrade gate:*

```yaml
mutable_variables:
  - label: hint_count
    type: integer
    scope: node
    initial: 0

flags:
  - label: hint_veteran    # permanent — unlocks enhanced hints after 10 uses

events:
  - label: count_hint
    trigger:
      type: dm
      message_label: hint_cmd
    trigger_per_node: true
    responses:
      - type: increment_variable
        variable_label: hint_count
        amount: 1
        to_triggering_node: true

  - label: grant_hint_veteran
    trigger:
      type: variable_threshold
      variable: hint_count
      operator: gte
      value: 10
    trigger_per_node: true
    max_triggers: 1
    responses:
      - type: add_flag
        flag_label: hint_veteran
        to_triggering_node: true
```

*Timed selection of a random node (e.g. orbital cannon targeting):*
```yaml
- type: with_node
  to_all_with_flag: valid_target
  random_n: 1
  responses:
    - type: create_waypoint
      expiry_mins: 60
      initial_flags:
        - laser_target
```
`create_waypoint` requires node context — it CANNOT appear directly in a
`time_window` or `in_zone_on_start` event. Always wrap it in `with_node`.

*Blast radius / area effect:*
```yaml
- type: add_flag
  flag_label: in_blast_zone
  to_all_near_triggering_waypoint:
    meters: 1609
```
Only valid in `flag_expired` + `dynamic_waypoint` or `near_waypoint` +
`target_flag` events where `triggering_waypoint_id` is in context.

*Detonation timer via flag expiry:*
```yaml
flags:
  - label: armed
    expiry_mins: 30   # expiry fires the blast event

events:
  - label: detonate
    trigger:
      type: flag_expired
      flag_label: armed
      target_kind: dynamic_waypoint
    responses:
      - type: add_flag
        flag_label: in_blast_zone
        to_all_near_triggering_waypoint:
          meters: 500
```

*Open enrollment (any node entering a zone becomes a valid target):*
```yaml
- label: enter_play_area
  trigger:
    type: enters_zone
    target: play_zone_a
  trigger_per_node: true
  exceptions:
    - kind: node_has_flag
      flag: valid_target
    - kind: node_has_flag
      flag: eliminated
  responses:
    - type: add_flag
      flag_label: valid_target
      to_triggering_node: true
```

*Multi-polygon areas via zone groups:*

When a play area can't fit in one triangle, split it into adjacent triangles and add
them all to a zone group. Use `enters_zone_group` / `leaves_zone_group` / `in_zone_group`
against the group instead of duplicating event blocks per triangle.

```yaml
zones:
  - label: arena_a
    points: [[37.76, -122.42], [37.77, -122.42], [37.77, -122.41]]
  - label: arena_b
    points: [[37.76, -122.42], [37.77, -122.41], [37.76, -122.41]]

groups:
  - label: arena_zones
    kind: zone
    members: [arena_a, arena_b]

events:
  - label: enter_arena
    trigger:
      type: enters_zone_group
      zone_group: arena_zones   # fires when node enters any member zone
    trigger_per_node: true
    responses:
      - type: add_flag
        flag_label: in_arena
        to_triggering_node: true
```

`{zone}` in message templates resolves to the specific zone that triggered the event,
so a single event block can report which triangle the node crossed into.

`in_zone_group_on_start` is the periodic equivalent — fires during each periodic check
if any located node is currently inside any member zone. Use it in place of
`in_zone_on_start` when the area spans multiple triangles.

*Win condition via computed variable:*
```yaml
variables:
  - label: survivor_count
    scope: global
    tracks: flag_count
    target: valid_target

events:
  - label: last_survivor
    trigger:
      type: variable_threshold
      variable: survivor_count
      operator: eq
      value: 1
    max_triggers: 1
```
`variable_threshold` works with both computed (`variables:`) and mutable
(`mutable_variables:`) variables.

*Misfire / random skip:*
```yaml
exceptions:
  - kind: random_skip
    chance: 0.05   # 5% chance to skip
```

*Random outcome selection:*
```yaml
- type: random_options
  options:
    - weight: 3
      responses:
        - type: send_message
          message_label: common_outcome
          to_channel: main
    - weight: 1
      responses:
        - type: send_message
          message_label: rare_outcome
          to_channel: main
```

*Group-based routing:*
```yaml
groups:
  - label: red_team
    kind: node

events:
  - label: join_red_team
    trigger:
      type: dm
      message_label: join_red_cmd
    trigger_per_node: true
    responses:
      - type: add_to_group
        group_label: red_team
        to_triggering_node: true

  - label: red_team_alert
    trigger:
      type: enters_zone
      target: red_base
    trigger_per_node: true
    exceptions:
      - kind: node_not_in_group
        group: red_team
    responses:
      - type: send_message
        message_label: intruder_alert
        to_group: red_team
```

**Variable interpolation in messages:**
```yaml
messages:
  - label: status
    text: "Active: {survivor_count} | Destroyed: {destroyed_count}"
  - label: found
    text: "🎉 {node_id} found the cache!"
```
Use `{label}` to interpolate any defined variable (computed or mutable).
`{node_id}`, `{node_shortname}`, `{node_longname}`, and `{zone}` are always available as built-in tokens.
Node-scoped variables resolve to the triggering node's value.

**Game state anchor:**
Use a flag on a zone object as a global game state flag rather than on nodes:
```yaml
- type: add_flag
  flag_label: game_over
  to_zone: play_zone_a   # sets flag on the zone object, not nodes in it

# Gate other events:
exceptions:
  - kind: zone_has_flag
    flag: game_over
    target: play_zone_a
```

**Mesh waypoint broadcast (orbital cannon pattern):**
Use `create_waypoint` with `mesh_*` fields to simultaneously create an internal dynamic
waypoint and push a visible waypoint to players' Meshtastic maps. Link them so the mesh
waypoint is deleted automatically when the dynamic waypoint expires:

```yaml
events:
  - label: cannon_selector
    trigger:
      type: time_window
      start: "2020-01-01T00:00:00"
      end:   "2099-01-01T00:00:00"
    auto_recur: true
    recur_mins: 60
    responses:
      - type: with_node
        to_all_with_flag: valid_target
        random_n: 1
        responses:
          - type: create_waypoint
            expiry_mins: 60
            initial_flags:
              - laser_target
            mesh_name: "🛰️ TARGET LOCK"          # max 30 chars
            mesh_description: "Evac in 60 min."  # max 100 chars
            mesh_channel: game_channel            # broadcasts to channel

  - label: blast_cleanup
    trigger:
      type: flag_expired
      flag_label: laser_target
      target_kind: dynamic_waypoint
    responses:
      - type: delete_mesh_waypoint
        use_triggering_waypoint: true             # resolves via linked dynamic waypoint
```

`use_triggering_waypoint: true` only works when the dynamic waypoint was created with
`mesh_*` fields — the mesh_waypoint_id is stored on the dynamic waypoint row at creation.

For a mesh-only waypoint with no internal tracking (static marker, hint drop):
```yaml
- type: broadcast_waypoint
  name: "🏁 Finish Line"
  description: "Cross here to win."
  lat: 37.7749          # explicit coords required when no node location is available
  lon: -122.4194
  expiry_mins: 480
  label: finish_line    # required if you plan to delete_mesh_waypoint later
  to_channel: game_channel
```

**`waypoint_received` trigger** — fires when the bot receives a `WAYPOINT_APP` packet:
```yaml
trigger:
  type: waypoint_received
  from_flag: scout          # optional: only from nodes with this flag
  name_contains: "supply"   # optional: case-insensitive name filter
```
Available tokens in responses: `{waypoint_name}`, `{waypoint_description}`,
`{waypoint_lat}`, `{waypoint_lon}`, `{node_id}`.

**Triangular zones:**
Zones must have exactly 3 points. Cover rectangular areas with two triangles:
```yaml
- label: area_a
  points:
    - [37.10, -122.20]   # NW
    - [37.00, -122.20]   # SW
    - [37.00, -122.10]   # SE

- label: area_b
  points:
    - [37.10, -122.20]   # NW
    - [37.10, -122.10]   # NE
    - [37.00, -122.10]   # SE
```

### Step 3 — Present and solicit feedback

After generating the YAML:
1. Briefly summarize what the config does (3-5 sentences covering the game loop)
2. Call out any assumptions you made that the user should verify
3. Flag any `# CONFIGURE` comments that need real values
4. Ask: "Does this match what you had in mind? Anything you'd like to change?"

## Validation mental checklist

Before outputting any YAML, mentally verify:

- [ ] Every label referenced in a trigger, response, or exception is defined in its section
- [ ] Every `near_waypoint`, `near_zone`, `near_node` trigger has `meters`
- [ ] Every `*_zone_group` / `in_zone_group` / `in_zone_group_on_start` trigger has `zone_group` (not `target`), and the referenced group has `kind: zone`
- [ ] Every `channel` trigger has `channel_label`
- [ ] Every `zone_has_flag`/`waypoint_has_flag` exception has `target` (or is in a dynamic waypoint context)
- [ ] Every `*_in_group`/`*_not_in_group` exception has `group`; zone/waypoint group exceptions also have `target`
- [ ] `create_waypoint` only appears inside `with_node` or in events with node context
  (`enters_zone`, `leaves_zone`, `near_waypoint`, `near_node`, `dm`, `channel`, `flag_expired` with `target_kind: node`)
- [ ] `add_waypoint_flag`, `remove_waypoint_flag`, `destroy_waypoint` only appear
  in `near_waypoint` + `target_flag` or `flag_expired` + `dynamic_waypoint` events
- [ ] `to_triggering_node` is not used in `time_window`, `in_zone_on_start`,
  `waypoint_expired`, or `flag_expired` with non-node `target_kind`
- [ ] `to_all_near_triggering_waypoint` only used in dynamic waypoint context
- [ ] `random_options` has at least 2 options
- [ ] All `initial_flags` on `nodes:` entries are defined in `flags:`
- [ ] All `initial_members` on `groups:` entries are defined and match the group's `kind`
- [ ] `mutable_variables` used in `increment_variable` are type `integer` or `float`
- [ ] `set_variable`/`increment_variable` on `scope: node` variables have a target; `scope: global` have no target
- [ ] `variable_threshold` `operator` is one of: `lt`, `lte`, `eq`, `neq`, `gte`, `gt`
- [ ] `flag_expired` has `target_kind`; `waypoint_expired` does not require it
- [ ] Capture templates (`{mutable_var}` in command messages): at most one capture token per message; variable must be `scope: node`; `max_length` set on string vars that appear in broadcast messages
- [ ] `send_alert` used only for genuine safety/urgency situations, not ordinary confirmations
- [ ] `node_*` tracks variables are `scope: node`; pair with `request_telemetry` if fresh values are needed
- [ ] No real-world coordinates, node IDs, or personally-identifying information
- [ ] `create_waypoint` with `mesh_*` fields: `mesh_name` ≤30 chars, `mesh_description` ≤100 chars;
  exactly one of `mesh_channel` or `mesh_to_triggering_node` is set; trigger provides node context
- [ ] `broadcast_waypoint`: `name` ≤30 chars, `description` ≤100 chars; `lat`/`lon` both set or
  both omitted; explicit coords required when trigger is `time_window` or `in_zone_on_start`
  (no node location available); `label` set if `delete_mesh_waypoint` will reference it
- [ ] `delete_mesh_waypoint`: exactly one of `label` or `use_triggering_waypoint` is set;
  `use_triggering_waypoint: true` only valid when the triggering dynamic waypoint was created
  with `mesh_*` fields

## Reference examples

Five complete example configs are in `references/examples/`. Read them for
patterns and idioms before generating complex configs:

- `ghost_walk.yaml` — self-guided tour, sequential flag gating, `flag_count` variable,
  staff exclusion via initial flags
- `castle_defense.yaml` — multi-zone escalating alerts, `leaves_zone` / `enters_zone`,
  `auto_recur` status reports, `to_node` DMs, `request_location`
- `trail_race.yaml` — dual-channel (one broadcast-only), `{node_id}` in public
  announcements, `near_waypoint` checkpoint timing, staff exclusion
- `warmer_colder_geocache.yaml` — **primary reference for:** `distance_change_to_waypoint`,
  direction-flag routing, `mutable_variables` + `increment_variable`, `variable_threshold`
  upgrade gate, `expiry_mins` rate limiter, stale location refresh
- `orbital_cannon_survival.yaml` — full-featured: `with_node`, `create_waypoint`,
  `flag_expired`, dynamic waypoints, `random_skip`, `random_options`, mutable variables,
  `variable_threshold` win conditions, open enrollment

Read the relevant example(s) before generating. For scenarios involving movement
tracking, hint systems, or mutable counters, start with `warmer_colder_geocache.yaml`.
For advanced dynamic waypoint mechanics, start with `orbital_cannon_survival.yaml`.
