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

**Common patterns to apply correctly:**

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

**Variable interpolation in messages:**
```yaml
messages:
  - label: status
    text: "Active: {survivor_count} | Destroyed: {destroyed_count}"
```
Use `{label}` to interpolate any defined variable (computed or mutable).
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
- [ ] Every `zone_has_flag`/`waypoint_has_flag` exception has `target`
- [ ] `create_waypoint` only appears inside `with_node` or in events with node context
  (`enters_zone`, `leaves_zone`, `near_waypoint`, `near_node`, `dm`, `channel`, `flag_expired` with `target_kind: node`)
- [ ] `add_waypoint_flag`, `remove_waypoint_flag`, `destroy_waypoint` only appear
  in `near_waypoint` + `target_flag` or `flag_expired` + `dynamic_waypoint` events
- [ ] `to_triggering_node` is not used in `time_window`, `in_zone_on_start`,
  `waypoint_expired`, or `flag_expired` with non-node `target_kind`
- [ ] `random_options` has at least 2 options
- [ ] All `initial_flags` on `nodes:` entries are defined in `flags:`
- [ ] `mutable_variables` used in `increment_variable` are type `integer` or `float`
- [ ] `variable_threshold` `operator` is one of: `lt`, `lte`, `eq`, `neq`, `gte`, `gt`

## Reference examples

Four complete example configs are in `references/examples/`. Read them for
patterns and idioms before generating complex configs:

- `security_system.yaml` — simple zone monitoring, flags, channel broadcasts
- `ghost_walk.yaml` — self-guided tour, sequential flag gating, no staff required
- `castle_defense.yaml` — multi-zone escalating alerts, leave/enter events, status reports
- `orbital_cannon_survival.yaml` — full-featured: `with_node`, `create_waypoint`,
  `flag_expired`, dynamic waypoints, `random_skip`, `random_options`, mutable variables,
  `variable_threshold` win conditions, open enrollment

Read the relevant example(s) before generating. The orbital cannon example is the
most complete showcase of advanced features.
