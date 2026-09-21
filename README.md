<p align="center"><img src="assets/icon-256.png" width="160" alt="Verdigris Bay icon"></p>

<h1 align="center">Verdigris Bay</h1>

A procedurally generated cyberpunk survival RPG that runs entirely in your terminal, written in pure Python with no dependencies.

Verdigris Bay is a text RPG set in a sinking coastal city. You pick a role, take jobs, dive the net, and manage a humanity meter as you install chrome, trying to reach one of five endings before the city kills you. Game state lives in SQLite, the world is generated procedurally, and everything renders as a coloured terminal HUD built from raw ANSI.

```
python3 play.py
```

That is the whole install step. No `pip install`, no virtualenv, no build. Prefer a double-clickable program? Grab a prebuilt executable from [Releases](../../releases).

---

## Features

- **Pure standard library.** Python 3.10 or newer, and nothing else. It runs anywhere CPython runs, musl included.
- **Six playable roles.** Runner, Enforcer, Fixer, Techie, Medic and Scavver, each with its own stats, starting kit and a passive ability.
- **A generated world.** Six districts, six factions, plus NPCs, sites and loot rolled at runtime. `--seed` makes generation reproducible.
- **Tabletop-style resolution.** A d10 plus attribute plus skill against a difficulty value, with exploding and imploding tens.
- **Tactical combat.** Random hit locations, armour as damage reduction that ablates, aimed called shots, wound penalties, and mid-fight switching between ranged and melee weapons.
- **Netrunning.** A trace meter that persists between runs and decays over time, with ICE and network floors.
- **Coherence.** Installing cyberware costs humanity. Let it run out and you lose the character in a specific way.
- **A narrative engine.** A node graph with a precondition DSL drives an arc with five reachable endings gated on how you played.
- **Four difficulty levels.** Easy through Brutal, each changing your starting stats, loadout, ammo, and how often the city ambushes you.
- **Six UI themes.** Neon Noir, Vaporwave, Matrix, Amber CRT, Ice, and a colour-off Mono mode. Saved per character.
- **A save browser.** Every character is listed at launch with its status. One file per character, with continuous autosave.

---

## Download

Prebuilt executables are attached to each [Release](../../releases). They bundle their own Python, so nothing needs to be installed.

| Platform | File | How to run |
|---|---|---|
| Windows 10/11 (x64) | `verdigris-bay-windows-x64.zip` | Unzip and double-click `verdigris-bay.exe` |
| Linux (x64) | `verdigris-bay-linux-x64.tar.gz` | Extract, then `./verdigris-bay`, or run `./install-linux.sh` for a menu entry with icon |
| macOS (Apple Silicon) | `verdigris-bay-macos-arm64.tar.gz` | Extract, then double-click `verdigris-bay` (opens in Terminal) |
| macOS (Intel) | `verdigris-bay-macos-x64.tar.gz` | Same as above |

Known rough edges with the binaries:

- **They are unsigned.** Windows SmartScreen will warn on first launch (More info, then Run anyway). macOS Gatekeeper will block it; clear the quarantine flag with `xattr -d com.apple.quarantine verdigris-bay`, or right-click and choose Open.
- **The Linux build is made on Ubuntu 24.04** and needs glibc 2.39 or newer. Rolling distros (openSUSE Tumbleweed, Arch, Fedora 40+) are fine. On older systems such as openSUSE Leap 15 or Debian 12, run from source instead; it is one command.
- **Icons:** the Windows `.exe` carries the icon directly. A bare Linux or macOS binary cannot hold an icon; on Linux the installer adds it to your app menu, and on macOS the binary shows the generic Terminal icon.
- **Startup takes a second or two.** Single-file executables unpack themselves to a temp directory on each launch.

## Running from source

Python 3.10 or newer. There are no other dependencies.

```sh
python3 --version
```

---

## Quick start

```sh
git clone <your-repo-url>
cd verdigris-bay
python3 play.py
```

Launch options:

```sh
python3 play.py                        # character browser: load a save or start new
python3 play.py mysave.save            # load or create a specific save file
python3 play.py mysave.save --seed 42  # reproducible world generation
python3 tests/smoke.py                 # run the test suite
```

Running with no arguments opens a browser listing every saved character (name, handle, role, level, district, turn, difficulty, and whether they are alive). Pick one to load, or start a new character. The game autosaves as you play, one file per character.

Where saves go:

| Running as | Save location |
|---|---|
| Source (`python3 play.py`) | `saves/` next to `play.py` |
| Windows executable | `%APPDATA%\VerdigrisBay\saves` |
| macOS executable | `~/Library/Application Support/VerdigrisBay/saves` |
| Linux executable | `~/.local/share/verdigris-bay/saves` (respects `XDG_DATA_HOME`) |

Set `VERDIGRIS_SAVE_DIR` to override any of these.

The screen clears on every command, combat round and netrun action, so each screen shows the result of what you just did with the HUD underneath. Earlier turns are still in your terminal's scrollback. Set `VERDIGRIS_NO_CLEAR=1` to turn clearing off, and it switches off automatically when output is piped.

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

Colour and glyphs are also auto-detected and degrade on their own. You can force behaviour with environment variables: `NO_COLOR=1` turns off all colour, `VERDIGRIS_ASCII=1` uses a plain ASCII glyph set, and `VERDIGRIS_FORCE_COLOR=1` forces colour even when output is piped. On Windows the game switches the console into ANSI mode itself, so colour works in both Windows Terminal and the classic console.

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
  assets/
    icon.png           # 1024px master icon
    icon-256.png       # README / Linux menu icon
    icon.ico           # Windows executable icon
    icon.icns          # macOS icon
  packaging/
    make_icon.py       # regenerates everything in assets/ (needs Pillow)
    package.py         # bundles a built executable into a release archive
    install-linux.sh   # per-user install with menu entry and icon
    verdigris-bay.desktop
  .github/workflows/
    build.yml          # CI: test, build for 4 platforms, publish Release
  HOW_TO_PLAY.html     # player-facing manual
  DESIGN.md            # mechanics, architecture and balance notes
  README.md
```

Dependencies flow one way. `content`, `dice` and `db` depend on nothing, everything else depends on those, and `game` sits on top. `ui` is presentation only and holds no game logic, so rendering can change without touching a rule. The database is the single source of truth: the `Character` object is a live view over the `player` row rather than a cached copy, so a save is just the file on disk with no separate serialisation step.

---

## Testing

```sh
python3 tests/smoke.py
```

The suite runs about 110 assertions across the dice, rules, world generation, combat, netrunning and narrative systems, plus a soak test that plays 500 turns as each of the six roles and checks that nothing throws.

---

## Building executables

Builds are automated with GitHub Actions in `.github/workflows/build.yml`. The workflow runs the smoke tests, then builds a single-file executable with [PyInstaller](https://pyinstaller.org) on Windows, Linux, macOS Apple Silicon and macOS Intel, checks that each one launches and quits cleanly, and packages it with the docs.

To publish a release, push a version tag:

```sh
git tag v1.0.0
git push origin v1.0.0
```

The four archives are attached to a new GitHub Release with generated notes. To build without releasing, open the Actions tab, pick **Build executables**, and use **Run workflow**; the archives appear as downloadable artifacts on that run.

To build locally for your own platform:

```sh
python3 -m pip install pyinstaller
pyinstaller play.py --onefile --console --name verdigris-bay --clean --noconfirm
# add --icon assets/icon.ico on Windows
python3 packaging/package.py linux-x64    # optional: produce the release archive
```

PyInstaller does not cross-compile. Each platform's binary has to be built on that platform, which is why CI uses a runner per target.

The icon is generated, not hand-drawn. Edit `packaging/make_icon.py` and run it (it needs Pillow) to regenerate every size and format in `assets/`. Pillow is a build-time tool only; the game never imports it.

## Source material and license

This project ships with entirely original content. The city, the factions, every weapon, implant and program, and the whole narrative arc are written for it.

The genre's shared mechanical vocabulary (attribute plus skill plus die against a difficulty number, hit locations, armour as damage reduction, augmentation carrying a psychological cost, a trace clock during intrusion) is common to many cyberpunk tabletop systems. Game systems are not copyrightable, and these particular numbers, names and implementations are original. No copyrighted setting, lore or stat block from any commercial rulebook is reproduced here.

The code does not ship with a license file yet. Add one before publishing if you want to set terms for reuse. If you plan to build on a specific licensed setting, read that publisher's terms directly, since they govern what you may distribute.
