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
- Use `{node_id}` to name the triggering node in announcements
- Use `{zone}` to name the zone in messages where it adds context

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
`{node_id}` and `{zone}` are always available as built-in tokens.
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
- [ ] No real-world coordinates, node IDs, or personally-identifying information

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
