# Verdigris Bay

A procedurally generated, text-based cyberpunk RPG in Python with a coloured
terminal HUD. SQLite-backed game state, a composable world generator, and a
node-graph narrative engine with five reachable endings.

**Pure standard library.** No pip install, no virtualenv, no compiled
extensions, no glibc-specific calls. `sqlite3`, `random`, `dataclasses`,
`textwrap`, `json`, plus `os`/`re`/`sys`/`shutil` for the terminal UI. It runs
anywhere CPython 3.10+ runs, musl included.

```sh
python3 play.py                      # character browser: load a save or start new
python3 play.py mysave.db            # load/create a specific save file
python3 play.py mysave.db --seed 42  # reproducible world generation
python3 tests/smoke.py               # ~110 integration checks
```

Run with no arguments and you get a **character browser** listing every saved
run (name, handle, role, level, district, turn, difficulty, alive/dead); pick
one to load or start a new character. New saves go under `saves/`, one file per
character. Pick a **difficulty** (easy / normal / hard / brutal) and a UI
**theme** (six, including a no-colour Mono) at creation; both are stored with
the save. The game autosaves; type `menu` or hit `Ctrl+C` anywhere to save and
exit.

---

## On the source material

This engine ships with **entirely original content**. The city, the six
factions, every weapon, implant, program and the whole narrative arc are
written for this project.

The uploaded PDFs are commercial rulebooks (R. Talsorian's *Cyberpunk 2013 /
2020 / RED / Night City*, Steve Jackson Games' *GURPS Cyberpunk*). Their
settings, lore, gear lists and stat tables are copyrighted expression and are
not reproduced here in any form.

What *is* shared with those books is the genre's common mechanical vocabulary
— attribute + skill + die versus a difficulty number, hit locations, armour as
damage reduction, augmentation carrying a psychological cost, a trace clock
during intrusion. Game systems are not copyrightable, and these particular
implementations, numbers and band names are original.

If you want to build on the licensed setting specifically, R. Talsorian
publishes a **Cyberpunk RED Homebrew Content license**; read it directly, as
it governs what you may distribute.

---

## Architecture

```
verdigris/
  dice.py      Seedable RNG, the resolution check, weighted tables
  db.py        SQLite schema + access layer (13 tables)
  content.py   All setting data: factions, districts, gear, procgen vocabulary
  rules.py     Character model, Coherence, cyberware, reputation, damage
  worldgen.py  Procedural locations, NPCs, encounters, loot, net hosts
  combat.py    Turn-based tactical resolution
  netrun.py    Network intrusion, ICE, the trace meter
  quests.py    Node-graph narrative engine + "The Ledger" arc
  actions.py   Travel, search, vendors, clinics, consumables
  ui.py        Terminal presentation: colour, HUD, gauges, ASCII art
  game.py      Main loop, character creation, CLI
```

Dependencies flow one way: `content` depends on nothing, `dice`/`db` depend on
nothing, everything else depends on those, and `game` sits on top. `ui` is
presentation-only — it reads `content` for labels but holds no game logic, so
rendering can change without touching a rule. Adding content means editing
`content.py`, not the engines.

### Interface

A terminal HUD, not a wall of text. Before every prompt the game prints a
persistent status bar — colour-graded gauges for HP, Coherence, Trace and Heat,
plus level, credits, wound state and unspent skill points. Combat and
netrunning draw framed screens with enemy/node health bars, and there's a
title-screen logo and per-screen banners.

All of it is raw ANSI and Unicode box-drawing from `ui.py`, no `curses` or
third-party library, and it degrades in three independent steps:

- **Colour depth:** truecolor → 256 → 16 → none.
- **Glyphs:** Unicode → ASCII (auto when the output stream isn't UTF-8).
- **Colour at all:** off when `NO_COLOR` is set, output isn't a TTY, or
  `TERM=dumb`.

Overrides: `NO_COLOR=1`, `VERDIGRIS_ASCII=1`, `VERDIGRIS_FORCE_COLOR=1`. Piped
to a file it renders as clean monochrome text.

**Themes.** `ui.py` holds six named palettes (Neon Noir, Vaporwave, Matrix,
Amber CRT, Ice, and a colour-off Mono) keyed on semantic colour names, so a
theme swap re-tints the entire HUD, combat and netrun screens without touching
any rendering call site. The active theme is stored in the save's `meta` table
and reapplied on load; change it from the browser, the `menu`, or the `theme`
command.

**Difficulty.** `content.DIFFICULTIES` (easy / normal / hard / brutal) sets a
starting-attribute modifier, starting credits, extra kit, ammo, the ambient
encounter rate, and a flat enemy-threat modifier. It's chosen at creation and
stored in `meta`; the world tick reads it for the encounter roll and combat
reads it when building enemies.

### The database is the game state

Nothing authoritative lives only in a Python object. `Character` is a live
*view* over the `player` row, not a cached copy — so a save is just the file
on disk, and there is no serialisation step to drift out of sync.

Items use a single polymorphic table with `(owner_type, owner_id)`. Moving
loot from a crate into a backpack is one `UPDATE`, and item condition, ammo
loaded and quantity have exactly one home.

---

## Mechanics

### Resolution

```
d10 + attribute + skill + modifiers  vs  Difficulty Value
```

A natural 10 rolls again and adds; a natural 1 rolls again and subtracts. The
long tail means a desperate character occasionally beats a wall and a
competent one occasionally faceplants.

Degree of success is used everywhere — `Check.margin` drives bonus damage,
how much a netrun extraction yields, and how much integrity a repair restores.

Difficulty bands are calibrated so an unspecialised character (attribute 5,
skill 3) clears `routine` about 70% of the time:

| trivial | easy | routine | tricky | hard | severe | nightmare |
|---|---|---|---|---|---|---|
| 7 | 9 | 12 | 15 | 18 | 22 | 26 |

### Seven attributes

REF (reflex), BOD (body), INT (intellect), NRV (nerve), PRE (presence),
TEC (tech), WIR (wire — neural bandwidth). Twenty skills, each governed by one.

### Coherence — the cost of chrome

Starts at 100. Every implant permanently subtracts its `strain`. Extraction
returns only half. This is the game's central resource tension: chrome is the
most direct route to power and the most dangerous thing you can spend.

| Band | Range | Effect |
|---|---|---|
| Integrated | 90–100 | — |
| Drifting | 70–89 | −1 PRE |
| Fraying | 50–69 | −1 PRE, −1 NRV |
| Dissociating | 30–49 | −2 PRE, −2 NRV |
| Fugue | 10–29 | −3 PRE, −3 NRV |
| Flatline | 0–9 | run ends |

Crossing a band fires a story trigger and applies a status effect. A low-chrome
and a high-chrome playthrough reach different endings.

### Cyberware integrity

Separate from Coherence — this is maintenance, not psychology. Integrity drops
from damage taken, EMP and net diving. Below 50 the implant's bonus halves;
below 25 it can misfire; at 0 it goes offline until repaired.

### Combat

Initiative rolled once and held. Hit locations on a d10 (head ×2 damage, torso
×1, limbs ×0.7). Damage pipeline:

```
weapon dice + attribute (melee) + margin//4
  -> location multiplier
  -> armour SP reduced by weapon AP
  -> HP
```

Armour ablates as it absorbs. Weapons degrade and jam below 40% condition.
Magazines and reserve ammo are tracked separately. An empty weapon with no
reserve falls back to unarmed rather than forfeiting the round.

**Aimed shot.** Besides the standard attack, you can spend the action on a
single called shot to the head at −6 to hit. It lands the head location's ×2
multiplier and a raised stun chance — the deliberate risk/reward called shot.

**Weapon switching.** If you carry more than one weapon, combat offers a Switch
action that re-equips any ranged or melee weapon you own. The swap is free (it
doesn't consume the round), so you can drop from an empty pistol to a blade and
still act the same turn.

**Wound states.** Below half HP you're *Wounded* (−1 to your own actions);
below a quarter, *Mortal* (−2). The penalty applies only to the actions you
roll, never to the defensive DV enemies roll against, so being hurt is a real
setback without becoming an unrecoverable defence spiral.

Measured win rates (200 fights each, current build with wound penalties on),
two enemies, attack-only, no items or fleeing, **normal difficulty**:

| role | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|
| Enforcer | 100% | 100% | 100% | 93% | 60% |
| Scavver | 100% | 97% | 57% | 0% | 0% |
| Techie | 100% | 63% | 6% | 0% | 0% |
| Fixer | 99% | 58% | 3% | 0% | 0% |
| Medic | 100% | 47% | 2% | 0% | 0% |
| Runner | 100% | 41% | 1% | 0% | 0% |

Difficulty shifts this: easy gives you higher stats, more gear and −1 enemy
threat, while hard and brutal add enemy threat on top of a thinner loadout.
Non-combat roles are meant to talk, flee, use items, or never be there. Real
play is more forgiving than this table, which uses none of those options. The
wound-state penalty pulls the mid-tier numbers down a few points versus a
naive attrition slugfest — being hurt is supposed to cost you.

### Netrunning and the trace meter

Trace is 0–100 and **persists between runs**. It does not reset when you jack
out; it decays slowly over world turns. Every dive raises a clock that follows
you back into meatspace.

| Clean | Flagged | Tracked | Pinned | Burned |
|---|---|---|---|---|
| 0–24 | 25–49 | 50–74 | 75–94 | 95–100 |

At Flagged, CRA encounter weight rises. At Pinned, trace converts into district
heat. At Burned, a strike team may arrive mid-turn.

Hosts are persistent node stacks: a host you retreat from is the same host
when you return, including which nodes you cracked. ICE damage depletes the
deck buffer first; once the buffer is gone, half the overflow carries through
the neural port as real HP damage, and lethal ICE degrades cyberware on hit.

Per-tier, full-clear dive (20 runs each):

| tier | avg trace at exit | deaths |
|---|---|---|
| 1 | 26 | 0/20 |
| 2 | 68 | 0/20 |
| 3 | 85 | 0/20 |
| 4 | 99 | 3/20 |
| 5 | 100 | 4/20 |

Trace, not death, is the limiting resource — which is the intended shape.

### Reputation and faction friction

Six factions, standing −100 to +100. Gaining with one *costs* you elsewhere,
via a friction coefficient matrix in `content.FACTIONS`:

```python
"lowline": {"friction": {"halcyon": -0.9, "authority": -0.4}}
```

Gaining +10 with the Lowline applies −9 to Halcyon. Losses cascade at half
rate — the city notices you helping an enemy faster than it forgives you
hurting one.

You cannot max every faction, and three of the five endings are gated behind a
reputation threshold of 40. The political layer is a real choice, not five
independent progress bars.

---

## Procedural generation

Generators **compose** rather than randomise. A location layers:

```
district context -> structural kind -> descriptor -> feature
                 -> occupant -> security -> loot tier
```

Each layer reads the ones above it, so results stay coherent: a Terraces
server farm gets corporate security and tier-4 loot; a Drowned Quarter flooded
lobby gets scavvers, tidal hazards and tier-1 scrap.

Security is derived, not rolled:

```
base district security
  +2  inherently guarded kind (server farm, vault, chem store)
  -2  abandoned/flooded/condemned descriptor
  +1  per 25 points of district heat
```

Loot tier is `round((wealth + security) / 4)` with a 10% upward swing — so a
poor district *can* hide something good, which is what keeps the Drowned
Quarter worth searching.

### Encounter tables react to state

`worldgen.encounter_table()` builds weights at call time rather than reading a
static chart:

- The controlling faction appears twice as often on its own turf
- Standing ≤ −30 with a faction: their **combat** encounters ×2.2, contacts ×0.4
- Standing ≥ +45: combat ×0.3, contacts ×1.8
- District heat scales CRA, drone sweep and ambush weights
- Environment gates: tidal hazards only exist where `flooding > 0`

Every `Dice` instance is seedable and `dice.spawn(salt)` derives deterministic
children, so regenerating one location's loot doesn't desync the global stream.

---

## The narrative engine

The story is a directed graph in the `quest_nodes` table. Each turn,
`check_triggers()` evaluates every locked node's preconditions against live
state and promotes those that pass. The story is **pulled** by world state
rather than pushed by a script.

### Precondition DSL

Keys are ANDed. All are optional.

| key | meaning |
|---|---|
| `turn_min`, `level_min` | thresholds |
| `district` | str or list — player must be here |
| `rep` | `{faction: n}` — standing ≥ n, or ≤ n if n is negative |
| `flag` | `{key: value}` — equality, or ≥ for ints |
| `not_flag` | list — none of these are truthy |
| `nodes_done` / `nodes_not_done` | node id lists |
| `item` | player holds this template |
| `credits_min`, `coherence_min`, `coherence_max`, `trace_min`, `heat_min` | thresholds |
| `chance` | float, rolled per evaluation — the random trigger |
| `manual` | never auto-triggers; reachable only via another node's `unlock` |

Effects: `set_flag`, `bump_flag`, `rep`, `credits`, `xp`, `items`, `heat`,
`trace`, `coherence`, `unlock`, `complete`, `fail`, `journal`.

Choices carry their own `requires` predicate, so a branch simply doesn't appear
unless you've earned it.

### "The Ledger"

Forty years ago the seawall failed and twelve blocks went under. The official
finding was storm surge beyond design tolerance. An internal Halcyon audit
ledger says the reinforcement was costed, scheduled, and cancelled — and the
cancellation was signed.

Non-linear by construction: Act 2 has three parallel entry points (Gantry,
Terraces, Drowned Quarter), any one of which advances the arc. Act 3 resolves
by netrun, physical infiltration, or bribery. Five main endings gated on
reputation and choices, plus two early-exit endings for selling out.

The arc deliberately exercises every trigger type in the DSL — location,
reputation threshold, flag, item possession, coherence band, trace level and
random chance — so it doubles as a worked reference for authoring your own.

---

## Extending it

**New gear:** add to `WEAPONS` / `ARMOR` / `CONSUMABLES` / `CYBERWARE` in
`content.py`, then reference the key from a `LOOT_TIERS` entry. Nothing else
needs to change — vendors, loot and procgen all read those dicts.

**New district:** add to `DISTRICTS` and give it a matching `LOCATION_KINDS`
vocabulary. `seed_world()` picks it up on the next new game.

**New quest arc:** append node dicts to `quests.NODES` with a different `arc`
string. `install_arc()` is idempotent, so existing saves gain new nodes on
next load.

**New status effect:** add to `STATUS_EFFECTS`. The tick loop, attribute
modifier resolution and cyberware suppression all read that dict.

---

## Testing

`tests/smoke.py` runs ~110 assertions across every subsystem — dice
distributions, Coherence bands, cyberware degradation and repair, armour
ablation, status expiry, reputation clamping and friction cascade, procgen
bounds, encounter reweighting, combat termination, netrun persistence, the
full precondition DSL, every ending path, save/load round-tripping, and a
500-turn soak on all six roles.

Three real bugs surfaced during development and are fixed in the code:

1. **Swapped SQL parameters** in `generate_location` — `SET location_id=npc_id
   WHERE id=loc_id`, which tripped a foreign-key constraint on every occupied
   location.
2. **An empty weapon forfeited the combat round**, trapping a player with no
   ammo and no melee option in an unwinnable loop of free enemy attacks.
3. **Every ending auto-unlocked on turn one**, because an empty precondition
   dict evaluates as trivially true. Fixed with the `manual` DSL key.
