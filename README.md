# Verdigris Bay

A procedurally generated cyberpunk survival RPG that runs entirely in your terminal, written in pure Python with no dependencies.

Verdigris Bay is a text RPG set in a sinking coastal city. You pick a role, take jobs, dive the net, and manage a humanity meter as you install chrome, trying to reach one of five endings before the city kills you. Game state lives in SQLite, the world is generated procedurally, and everything renders as a colored terminal HUD built from raw ANSI.

```
python3 play.py
```

That is the whole install step. No `pip install`, no virtualenv, no build.

---

## Features

- **Pure standard library.** Python 3.10 or newer, and nothing else. It runs anywhere CPython runs, musl included.
- **Six playable roles.** Runner, Enforcer, Fixer, Techie, Medic and Scavver, each with its own stats, starting kit and a passive ability.
- **A generated world.** Six districts, six factions, plus NPCs, sites and loot rolled at runtime. `--seed` makes generation reproducible.
- **Tabletop-style resolution.** A d10 plus attribute plus skill against a difficulty value, with exploding and imploding tens.
- **Tactical combat.** Random hit locations, armor as damage reduction that ablates, aimed called shots, wound penalties, and mid-fight switching between ranged and melee weapons.
- **Netrunning.** A trace meter that persists between runs and decays over time, with ICE and network floors.
- **Coherence.** Installing cyberware costs humanity. Let it run out and you lose the character in a specific way.
- **A narrative engine.** A node graph with a precondition DSL drives an arc with five reachable endings gated on how you played.
- **Four difficulty levels.** Easy through Brutal, each changing your starting stats, loadout, ammo, and how often the city ambushes you.
- **Six UI themes.** Neon Noir, Vaporwave, Matrix, Amber CRT, Ice, and a color-off Mono mode. Saved per character.
- **A save browser.** Every character is listed at launch with its status. One file per character, with continuous autosave.

---

## Requirements

Python 3.10 or newer. There are no other dependencies.

Check your version:

```sh
python3 --version
```

---

## Quick start

```sh
git clone https://github.com/NullAngst/Verdigris-Bay
cd Verdigris-Bay
python3 play.py
```

Launch options:

```sh
python3 play.py                        # character browser: load a save or start new
python3 play.py mysave.save            # load or create a specific save file
python3 play.py mysave.save --seed 42  # reproducible world generation
python3 tests/smoke.py                 # run the test suite
```

Running with no arguments opens a browser listing every saved character (name, handle, role, level, district, turn, difficulty, and whether they are alive). Pick one to load, or start a new character. New saves are written to a `saves/` folder, one file each. The game autosaves as you play.

To leave at any point, type `menu` or press `Ctrl+C`. Both open a menu with Resume, Change theme, Save now, and Save and quit. The world is always saved. The only thing you lose by bailing out mid-fight is that one fight.

---

## Controls

At the main prompt:

| Command | Action | Advances the world |
|---|---|---|
| `look` / `l` | Describe where you are | no |
| `status` / `s` | Your full character sheet | no |
| `inv` / `i` | Inventory and cyberware | no |
| `rep` / `r` | Faction standing | no |
| `journal` / `j` | Recent event log | no |
| `explore` / `e` | Find and search sites | yes |
| `travel` / `t` | Change district | yes |
| `net` / `n` | Dive the local network | yes |
| `market` / `m` | Buy and sell | yes |
| `clinic` / `c` | Healing and cyberware | yes |
| `story` | Open narrative threads | yes |
| `train` | Spend skill points | no |
| `equip <id>` | Equip an item by id | no |
| `use <id>` | Use a consumable by id | yes |
| `wait` / `w` | Pass a turn | yes |
| `theme` | Change the UI theme | no |
| `menu` | Save, change theme, or quit (same as `Ctrl+C`) | no |
| `save` | Write to disk | no |
| `quit` / `q` | Save and exit | no |

In a fight you choose from Attack, Aimed shot (a called head shot at a to-hit penalty), Switch weapon (free, does not cost the round), Reload, Use item, and Flee.

---

## Difficulty

Chosen at character creation and stored with the save. It shapes your starting stats, your loadout, and how often you get ambushed. Nothing is locked to a role.

| Level | Stats | Credits | Starting kit | Ambush rate |
|---|---|---|---|---|
| Easy | +1 all | 2,800 | Extra pistol, blade, spare vest, 3 trauma kits, 2 stims, lots of ammo | low |
| Normal | base | 1,200 | Role kit plus a backup blade, a trauma kit and a stim | medium |
| Hard | -1 all | 500 | Role kit only, little ammo | high |
| Brutal | -2 all | 200 | Role kit only, no spare ammo, enemies hit harder | very high |

---

## Themes

Change the look from the browser, the `menu`, or the `theme` command. Your choice is saved with the character.

| Theme | Look |
|---|---|
| Neon Noir | The default: cyan, magenta and amber on black |
| Vaporwave | 80s pastel: hot pink, lavender and teal |
| Matrix | Green phosphor |
| Amber CRT | A warm monochrome terminal glow |
| Ice | Cold blues and white |
| Mono | No colour at all, plain text |

Color and glyphs are also auto-detected and degrade on their own. You can force behavior with environment variables: `NO_COLOR=1` turns off all color, `VERDIGRIS_ASCII=1` uses a plain ASCII glyph set, and `VERDIGRIS_FORCE_COLOR=1` forces color even when output is piped.

---

## Project layout

```
verdigris-bay/
  play.py              # launcher
  verdigris/
    content.py         # all game data (roles, items, districts, factions, difficulty)
    dice.py            # seeded RNG and dice
    db.py              # SQLite wrapper, game state
    rules.py           # character sheet, checks, skills, cyberware
    worldgen.py        # procedural world, NPCs, encounters, loot
    combat.py          # turn-based combat resolution
    netrun.py          # netrunning and the trace meter
    quests.py          # node-graph narrative engine and endings
    actions.py         # consumables and shared actions
    ui.py              # ANSI HUD, themes, framed screens (presentation only)
    game.py            # command loop, menus, save browser, glue
  tests/
    smoke.py           # integration tests
  HOW_TO_PLAY.html     # player-facing manual
  README.md
```

Dependencies flow one way. `content`, `dice` and `db` depend on nothing, everything else depends on those, and `game` sits on top. `ui` is presentation only and holds no game logic, so rendering can change without touching a rule. The database is the single source of truth: the `Character` object is a live view over the `player` row rather than a cached copy, so a save is just the file on disk with no separate serialization step.

---

## Testing

```sh
python3 tests/smoke.py
```

The suite runs about 110 assertions across the dice, rules, world generation, combat, netrunning and narrative systems, plus a soak test that plays 500 turns as each of the six roles and checks that nothing throws.

---

## Source material

This project ships with entirely original content. The city, the factions, every weapon, implant and program, and the whole narrative arc are written for it.

The genre's shared mechanical vocabulary (attribute plus skill plus die against a difficulty number, hit locations, armor as damage reduction, augmentation carrying a psychological cost, a trace clock during intrusion) is common to many cyberpunk tabletop systems. No copyrighted setting, lore or stat block from any commercial rulebook is reproduced here.
