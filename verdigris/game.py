"""
game.py -- Main loop, character creation and the command interface.

THE TURN STRUCTURE
    One player action = one world turn. On each turn, tick_world() runs:

        1. Status effects tick (damage, expiry, stim crash)
        2. Trace decays; trace consequences may fire
        3. District heat decays everywhere the player isn't
        4. Quest manager re-evaluates every locked node's preconditions
        5. Random encounter roll, weighted by district and player state

    This ordering matters: statuses resolve before encounters, so you can
    bleed out before the next fight starts, and quest triggers evaluate
    before encounters so a story beat takes precedence over random content.
"""

from __future__ import annotations

import os
import sys
import glob
import textwrap

from . import actions, combat, content, netrun, quests, ui, worldgen
from .db import Database, jload
from .dice import Dice
from .rules import (Character, adjust_heat, adjust_rep, all_rep, get_heat,
                    rep_report, rep_tier)

WIDTH = ui.WIDTH
RULE = "-" * WIDTH


class QuitSignal(Exception):
    """Raised from ask() on Ctrl+C / EOF so any nested screen unwinds to the
    game menu instead of getting stuck. Combat state isn't persisted, so
    bailing out mid-fight is safe; the world itself is already saved.

    hard=True means the input stream is closed (EOF / piped input exhausted),
    so there's no point opening an interactive menu -- just save and exit."""

    def __init__(self, hard: bool = False):
        super().__init__()
        self.hard = hard


# ==========================================================================
# OUTPUT HELPERS
# ==========================================================================
def wrap(text: str, indent: str = "") -> str:
    out = []
    for para in str(text).split("\n"):
        if not para.strip():
            out.append("")
            continue
        out.append(textwrap.fill(
            para, width=WIDTH, initial_indent=indent, subsequent_indent=indent
        ))
    return "\n".join(out)


def say(text: str = "", indent: str = "") -> None:
    print(wrap(text, indent))


def sayc(text: str, name: str = "ink", indent: str = "  ") -> None:
    """Wrap plain text, then colour each line (keeps ANSI off the wrapper)."""
    for line in wrap(text, indent).split("\n"):
        print(ui.color(line, name) if line.strip() else line)


def header(text: str, kind: str | None = None) -> None:
    """Section banner. Pass a scene `kind` for a themed frame."""
    if kind:
        print(ui.scene_frame(kind, text))
    else:
        print(ui.banner(text))


def ask(prompt: str = "> ") -> str:
    try:
        styled = ui.color(ui.g("chev") + ui.g("chev"), "cyan", bold=True) + " " \
            + ui.color(prompt.rstrip(": ").strip() or "", "grey") \
            + ui.color(" " + ui.g("arrow") + " ", "cyan")
        return input(styled).strip()
    except KeyboardInterrupt:
        print()
        raise QuitSignal(hard=False)
    except EOFError:
        print()
        raise QuitSignal(hard=True)


def menu(options: list[str], prompt: str = "Choose") -> int:
    """Numbered menu. Returns a 0-based index, or -1 to back out."""
    for i, opt in enumerate(options, 1):
        num = ui.color("{:>2}".format(i), "amber", bold=True)
        mark = ui.color(ui.g("dot"), "cyan")
        print("  " + num + " " + mark + " " + opt)
    hint = ui.dim("[1-{}, b=back]".format(len(options)))
    while True:
        raw = ask("{} {}".format(prompt, hint))
        low = raw.lower()
        if low in ("b", "back", "", "quit", "q", "exit"):
            return -1
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(ui.color("  Not an option.", "red"))


# ==========================================================================
# CHARACTER CREATION
# ==========================================================================
def create_character(db: Database, dice: Dice, difficulty: str = "normal",
                     name: str | None = None, handle: str | None = None) -> Character:
    diff = content.DIFFICULTIES.get(difficulty, content.DIFFICULTIES["normal"])
    header(f"{content.CITY}")
    say(content.CITY_PREMISE)
    print()
    print(ui.color("  Difficulty: ", "grey")
          + ui.color(diff["name"], "amber", bold=True))

    if not name:
        name = ask("Your name") or f"{dice.pick(content.FIRST_NAMES)} {dice.pick(content.LAST_NAMES)}"
    if not handle:
        handle = ask("Street handle") or dice.pick(content.STREET_NAMES)

    header("choose a role")
    keys = list(content.ROLES)
    for i, key in enumerate(keys, 1):
        spec = content.ROLES[key]
        icon = ui.ROLE_ICON.get(key, ui.g("diamond"))
        num = ui.color("{}".format(i), "amber", bold=True)
        title = ui.color(f"{icon} {key.upper()}", "cyan", bold=True)
        attrs = spec["attrs"]
        top3 = sorted(attrs.items(), key=lambda kv: -kv[1])[:3]
        stat_line = "  ".join(
            ui.color(k, "grey") + " " + ui.color(str(v), "green", bold=True)
            for k, v in top3
        )
        print(f"\n  {num}  {title}    {stat_line}")
        say(spec["blurb"], indent="      ")
        print("      " + ui.color("Passive: ", "amber") + spec["passive_desc"])
    print()

    idx = -1
    while idx < 0:
        raw = ask(f"Role [1-{len(keys)}]")
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            idx = int(raw) - 1
    role_key = keys[idx]
    spec = content.ROLES[role_key]

    # Apply the difficulty attribute modifier (clamped to the human 1..10 band).
    mod = diff["attr_mod"]
    attrs = {k: max(1, min(10, v + mod)) for k, v in spec["attrs"].items()}
    hp_max = 10 + attrs["BOD"] * 3

    db.run(
        "INSERT INTO player(id,name,handle,role,district,credits,hp,hp_max,"
        "coherence,trace,heat,xp,level,ref,bod,intl,nrv,pre,tec,wir) "
        "VALUES(1,?,?,?,'sable_row',?,?,?,100,0,0,0,1,?,?,?,?,?,?,?)",
        (name, handle, role_key, diff["credits"], hp_max, hp_max,
         attrs["REF"], attrs["BOD"], attrs["INT"], attrs["NRV"],
         attrs["PRE"], attrs["TEC"], attrs["WIR"]),
    )

    for skill, rank in spec["skills"].items():
        db.run("INSERT OR REPLACE INTO skills(skill,rank) VALUES(?,?)", (skill, rank))

    char = Character(db, dice)

    for item_key in spec["kit"]:
        char.give_item(item_key)
    for item_key in diff["extra_kit"]:      # difficulty-granted extras
        char.give_item(item_key)
    for cyber_key in spec["cyber"]:
        char.install_cyberware(cyber_key)

    # Starting ammo for whatever they were issued, scaled by difficulty.
    boxes = diff["ammo_boxes"]
    for item in char.items(category="weapon"):
        tmpl = content.ITEMS[item["template"]]
        if tmpl.get("ammo"):
            if boxes > 0:
                char.give_ammo(tmpl["ammo"],
                               content.AMMO_TYPES[tmpl["ammo"]]["box"] * boxes)
            db.run("UPDATE items SET loaded=? WHERE id=?",
                   (tmpl["mag"], item["id"]))

    # Auto-equip the best of each category.
    for cat in ("weapon", "armor", "deck"):
        items = char.items(category=cat)
        if items:
            char.equip(items[0]["id"])

    # Fixer's leverage passive: a contact in every district.
    if spec["passive"] == "leverage":
        for did in content.DISTRICTS:
            nid = worldgen.generate_npc(db, dice, did, persistent=True)
            db.run("UPDATE npcs SET met=1, trust=35 WHERE id=?", (nid,))

    db.set_meta("turn", 0)
    db.set_meta("difficulty", difficulty)
    db.log(f"{name} \"{handle}\", {role_key}, arrived in {content.CITY} "
           f"[{diff['name']}].", "start")
    return char


# ==========================================================================
# STATUS DISPLAY
# ==========================================================================
def show_status(db: Database, char: Character) -> None:
    print(ui.hud(db, char, compact=False))


def show_inventory(db: Database, char: Character) -> None:
    header("inventory")
    weapon = char.equipped_weapon()
    if weapon:
        tmpl = content.ITEMS[weapon["template"]]
        mag = f" [{weapon['loaded']}/{tmpl['mag']}]" if tmpl.get("mag") else ""
        print("  " + ui.color(ui.g("target"), "red") + " Weapon: "
              + ui.color(weapon["name"], "white", bold=True)
              + ui.color(mag, "amber") + ui.dim(f" ({weapon['condition']}%)"))
    deck = char.equipped_deck()
    if deck:
        print("  " + ui.color(ui.g("node"), "cyan") + " Deck:   "
              + ui.color(deck["name"], "white", bold=True)
              + ui.dim(f" ({deck['condition']}%)"))

    by_cat: dict[str, list] = {}
    for item in char.items():
        by_cat.setdefault(item["category"], []).append(item)

    for cat, items in sorted(by_cat.items()):
        print("\n  " + ui.color(f"[{cat}]", "cyan", bold=True))
        for it in items:
            eq = ui.color("  " + ui.g("check") + "equipped", "green") if it["equipped"] else ""
            qty = ui.color(f" x{it['qty']}", "amber") if it["qty"] > 1 else ""
            cond = ""
            if it["category"] in ("weapon", "armor", "deck", "cyberware"):
                cond = ui.dim(f" ({it['condition']}%)")
            idlabel = ui.color(f"[{it['id']:>3}]", "grey")
            print(f"    {idlabel} {it['name']}{qty}{cond}{eq}")

    cw = char.cyberware()
    if cw:
        print("\n  " + ui.color("[installed cyberware]", "magenta", bold=True))
        for c in cw:
            state = "" if c["online"] else ui.color("  OFFLINE", "red", bold=True)
            integ_c = "green" if c["integrity"] >= 50 else ("amber" if c["integrity"] >= 25 else "red")
            idlabel = ui.color(f"[{c['id']:>3}]", "grey")
            print(f"    {idlabel} {c['name']} {ui.dim('--')} {c['slot']}, "
                  f"integrity {ui.color(str(c['integrity']) + '%', integ_c)}, "
                  f"strain {c['strain']}{state}")


def show_reputation(db: Database) -> None:
    header("standing")
    for name, value, tier in rep_report(db):
        frac = (value + 100) / 200
        if value >= 45:
            cname = "green"
        elif value >= 15:
            cname = "cyan"
        elif value >= -30:
            cname = "grey"
        else:
            cname = "red"
        bar = ui.gauge(value + 100, 200, 28, cname)
        val = ui.color(f"{value:>+4}", cname, bold=True)
        print(f"  {name:<28} {bar} {val}  {ui.color(tier, cname)}")


def show_journal(db: Database) -> None:
    header("journal")
    for row in reversed(db.recent_journal(20)):
        tag = ui.color(f"T{row['turn']:>3}", "grey")
        kind_c = {"coherence": "magenta", "cyber": "cyan", "progress": "green",
                  "start": "amber"}.get(row["kind"], "ink")
        wrapped = wrap(row["text"], indent="       ")
        wrapped = wrapped.strip()
        print("  " + tag + "  " + ui.color(wrapped, kind_c))


# ==========================================================================
# WORLD TICK
# ==========================================================================
def tick_world(db: Database, dice: Dice, char: Character,
               qm: quests.QuestManager) -> None:
    """One world turn. See module docstring for ordering rationale."""
    db.advance_turn()

    for msg in char.tick_statuses():
        say(f"  {msg}")

    netrun.decay_trace(db, char)

    # Heat decays everywhere the player isn't standing.
    here = char.row["district"]
    for row in db.q("SELECT id, heat FROM districts WHERE heat > 0"):
        rate = 1 if row["id"] == here else 3
        adjust_heat(db, row["id"], -rate)

    # Quest triggers.
    for node in qm.check_triggers():
        print()
        say(f"*** {node['title']} -- new thread available ('story') ***")

    # Trace consequences.
    consequence = netrun.trace_consequence(db, dice, char)
    if consequence == "strike_team":
        print()
        say("A vehicle stops outside and four doors open at once.")
        ids = [
            worldgen.generate_npc(db, dice, here, faction_id="authority", threat=5)
            for _ in range(3)
        ]
        run_combat(db, dice, char, ids, "strike team")
        return

    # Ambient encounter.
    # Ambient encounter. Frequency is set by difficulty (stored in meta), so
    # a low-difficulty run isn't ambushed every few steps.
    diff = content.DIFFICULTIES.get(db.get_meta("difficulty", "normal"),
                                    content.DIFFICULTIES["normal"])
    if dice.chance(diff["encounter"]):
        enc = worldgen.roll_encounter(db, dice, here)
        if enc:
            handle_encounter(db, dice, char, enc)


# ==========================================================================
# ENCOUNTERS
# ==========================================================================
def handle_encounter(db: Database, dice: Dice, char: Character, enc: dict) -> None:
    header(enc["name"])
    say(enc["text"])
    print()

    if enc["type"] == "combat":
        ids = enc.get("npc_ids", [])
        if ids:
            run_combat(db, dice, char, ids, enc["name"])
        return

    if enc["type"] == "social_combat":
        opts = ["Fight.", "Talk your way out.", "Intimidate them.", "Walk away."]
        choice = menu(opts, "Response")
        ids = enc.get("npc_ids", [])
        if choice == 0 and ids:
            run_combat(db, dice, char, ids, enc["name"])
        elif choice == 1:
            chk = char.check("persuade", difficulty=13 + enc["threat"] * 2)
            if chk.success:
                say("  You give them a reason to be somewhere else. It works.")
                char.award_xp(20)
                if enc.get("faction"):
                    adjust_rep(db, enc["faction"], 2)
            else:
                say("  They aren't interested in talking.")
                if ids:
                    run_combat(db, dice, char, ids, enc["name"])
        elif choice == 2:
            chk = char.check("intimidate", difficulty=13 + enc["threat"] * 2)
            if chk.success:
                say("  They reassess. Then they leave.")
                char.award_xp(20)
                if enc.get("faction"):
                    adjust_rep(db, enc["faction"], -3)
                adjust_heat(db, char.row["district"], 2)
            else:
                say("  That was the wrong read.")
                if ids:
                    run_combat(db, dice, char, ids, enc["name"])
        else:
            chk = char.check("athletics", difficulty="routine")
            say("  You go." if chk.success else
                "  You go, and they take something off you on the way past.")
            if not chk.success:
                char.credits(-min(char.credits(), dice.between(100, 400)))
        return

    if enc["type"] == "discovery":
        tier = dice.between(2, 4)
        key = dice.weighted(content.LOOT_TIERS[tier])
        if key in content.LOOT_ALIASES:
            kind, arg, base = content.LOOT_ALIASES[key]
            if kind == "credits":
                char.credits(base)
                say(f"  {base}cr.")
            elif kind == "ammo":
                char.give_ammo(arg, base)
                say(f"  {content.AMMO_TYPES[arg]['name']} x{base}.")
            else:
                char.credits(base)
                say(f"  Salvage worth {base}cr.")
        elif key in content.ITEMS:
            char.give_item(key)
            say(f"  {content.ITEMS[key]['name']}.")
        char.award_xp(15)
        return

    if enc["type"] == "hazard":
        chk = char.check("athletics", difficulty="tricky")
        if chk.success:
            say("  You get to high ground in time.")
            char.award_xp(15)
        else:
            dmg, notices = char.damage(dice.d6(2), bypass_armor=True, source="hazard")
            say(f"  It catches you. {dmg} damage.")
            for n in notices:
                say(f"  {n}")
        return

    # Plain social encounter.
    if enc["type"] == "social":
        opts = ["Engage.", "Keep walking."]
        if menu(opts, "Response") == 0:
            chk = char.check("persuade", difficulty="routine")
            if chk.success:
                say("  It goes well. You come away with something useful.")
                char.award_xp(25)
                if enc.get("faction"):
                    adjust_rep(db, enc["faction"], 4)
                if dice.chance(0.4):
                    db.bump_flag("intel_fragments", 1)
                    say("  You pick up an intel fragment.")
            else:
                say("  Nothing comes of it.")


def run_combat(db: Database, dice: Dice, char: Character,
               npc_ids: list[int], context: str) -> None:
    fight = combat.Combat(db, dice, char, npc_ids, context)
    if not fight.living():
        return

    print(ui.scene_frame("combat", f"combat {ui.g('sep')} {context}"))
    while not fight.resolved():
        enemies = fight.living()
        hp_c = ui._threshold_color(char.row["hp"] / max(1, char.row["hp_max"]))
        wl, wc = ui.wound_label(char.row["hp"], char.row["hp_max"])
        wtag = "  " + ui.color(ui.g("warn") + " " + wl, wc, bold=True) if wl else ""
        print("\n  " + ui.color(f"ROUND {fight.round}", "magenta", bold=True)
              + "   " + ui.color(ui.g("hp"), hp_c) + " "
              + ui.color(f"{char.row['hp']}/{char.row['hp_max']} HP", hp_c, bold=True)
              + wtag)
        for i, e in enumerate(enemies, 1):
            ec = ui._threshold_color(max(0, e.hp) / max(1, e.hp_max))
            bar = ui.gauge(max(0, e.hp), e.hp_max, 12, ec)
            num = ui.color(f"{i})", "grey")
            print(f"    {num} {ui.color(e.name, 'white')}  {bar} "
                  f"{ui.color(f'{max(0, e.hp)}/{e.hp_max}', ec)} "
                  f"{ui.dim(f'threat {e.threat}')}")

        weapon = char.equipped_weapon()
        wlabel = "Attack"
        can_aim = False
        wname = "unarmed"
        if weapon:
            tmpl = content.ITEMS[weapon["template"]]
            wname = weapon["name"]
            if tmpl.get("mag"):
                wlabel = f"Attack ({weapon['loaded']}/{tmpl['mag']})"
                wname += f" [{weapon['loaded']}/{tmpl['mag']}]"
            can_aim = True

        all_weapons = char.items(category="weapon")
        print("    " + ui.dim("weapon: ") + ui.color(wname, "amber"))

        # Ordered (key, label) actions so dispatch never depends on colour.
        actions_list = [("attack", wlabel)]
        if can_aim:
            actions_list.append(
                ("aim", ui.color("Aimed shot", "amber") + ui.dim(" (head, x2 dmg, harder)")))
        if len(all_weapons) > 1:
            actions_list.append(("switch", "Switch weapon"))
        actions_list += [("reload", "Reload"), ("item", "Use item"), ("flee", "Flee")]

        choice = menu([lbl for _, lbl in actions_list], "Action")
        if choice < 0:
            continue          # redraw; Ctrl+C is the way out to the menu
        action = actions_list[choice][0]

        def pick_target() -> int:
            if len(enemies) <= 1:
                return 0
            t = menu([e.name for e in enemies], "Target")
            return max(0, t)

        if action == "attack":
            fight.player_attack(pick_target())
        elif action == "aim":
            fight.player_attack(pick_target(), aimed=True)
        elif action == "switch":
            labels = []
            for w in all_weapons:
                wt = content.ITEMS[w["template"]]
                tag = f" [{w['loaded']}/{wt['mag']}]" if wt.get("mag") else " (melee)"
                eqm = "  " + ui.g("check") if w["equipped"] else ""
                labels.append(f"{w['name']}{tag}{eqm}")
            wi = menu(labels, "Equip")
            ui.clear_screen()
            print(ui.scene_frame("combat", f"combat {ui.g('sep')} {context}"))
            if wi >= 0:
                ok, msg = char.equip(all_weapons[wi]["id"])
                print("  " + ui.color(msg, "cyan"))
            continue          # free swap: does not spend the round
        elif action == "reload":
            fight.player_reload()
        elif action == "item":
            usable = [i for i in char.items()
                      if i["category"] in ("consumable", "tool")]
            if not usable:
                say("  Nothing usable.")
                continue
            idx = menu([f"{i['name']} x{i['qty']}" for i in usable], "Use")
            if idx >= 0:
                fight.player_use_item(usable[idx]["id"])
        elif action == "flee":
            fight.player_flee()
        else:
            continue

        # Fresh screen per round: frame, what just happened, then the next
        # round's status and menu below it.
        ui.clear_screen()
        print(ui.scene_frame("combat", f"combat {ui.g('sep')} {context}"))
        for line in fight.drain_log():
            print("  " + ui.color(line, "ink"))

    print()
    result = fight.outcome()
    if result == "victory":
        print("  " + ui.color(ui.g("check") + " Clear.", "green", bold=True))
        for line in fight.finish():
            print("  " + ui.color(line, "green"))
    elif result == "fled":
        print("  " + ui.color("You're out.", "amber"))
    else:
        print("  " + ui.color(ui.g("skull") + " You go down.", "red", bold=True))


# ==========================================================================
# NETRUN INTERFACE
# ==========================================================================
def run_netrun(db: Database, dice: Dice, char: Character) -> None:
    if "netrun" not in char.grants():
        say("You need a neural interface port to dive. Buy one, then have a "
            "clinic install it.")
        return
    if not char.equipped_deck():
        say("You need a deck equipped.")
        return

    district = char.row["district"]
    hosts = worldgen.get_or_make_hosts(db, dice, district)
    header("available hosts")
    labels = [
        f"{h['name']} -- tier {h['tier']}, {h['depth']} nodes"
        + ("  [CRACKED]" if h["cracked"] else "")
        for h in hosts
    ]
    idx = menu(labels, "Dive")
    if idx < 0:
        return

    run = netrun.NetRun(db, dice, char, hosts[idx]["id"])
    print(ui.scene_frame("netrun", f"dive {ui.g('sep')} {run.host['name']}"))

    while not run.finished():
        n = run.node
        if n is None:
            break
        print("\n" + ui.net_ladder(run.nodes, run.position))
        node_label = ui.color(f"Node {run.position + 1}/{len(run.nodes)}", "cyan", bold=True)
        print("  " + node_label + "  " + ui.color(n["label"], "white"))

        buf_c = ui._threshold_color(run.buffer / max(1, run.buffer_max))
        trace_c = ui._threshold_color(char.row["trace"] / 100, invert=True)
        hp_c = ui._threshold_color(char.row["hp"] / max(1, char.row["hp_max"]))
        print("  " + ui.color("BUFFER", "grey") + " "
              + ui.gauge(run.buffer, run.buffer_max, 10, buf_c) + " "
              + ui.color(f"{run.buffer}/{run.buffer_max}", buf_c)
              + "   " + ui.color("TRACE", "grey") + " "
              + ui.color(f"{char.row['trace']}", trace_c)
              + " " + ui.color(f"[{netrun.trace_band(char.row['trace'])}]", "grey")
              + "   " + ui.color("HP", "grey") + " "
              + ui.color(f"{char.row['hp']}/{char.row['hp_max']}", hp_c))
        if n.get("ice") and not n.get("ice_down"):
            spec = content.ICE[n["ice"]]
            hp = n.get("ice_hp", spec["hp"])
            lethal = ui.color("  " + ui.g("skull") + " LETHAL", "red", bold=True) if spec["lethal"] else ""
            print("  " + ui.color(ui.g("warn") + " ICE: " + spec["name"], "red", bold=True)
                  + " " + ui.color(f"{hp}/{spec['hp']}", "red") + lethal)

        opts = ["Probe", "Crack", "Stealth past", "Attack ICE",
                "Pull payload", "Descend", "Jack out"]
        if run._has_program("prog_cauterise") and not run.cauterise_used:
            opts.insert(6, "Cauterise (dump trace)")

        choice = menu(opts, "Action")
        label = opts[choice] if choice >= 0 else ""

        if label == "Probe":
            run.probe()
        elif label == "Crack":
            run.crack()
        elif label == "Stealth past":
            run.stealth_past()
        elif label == "Attack ICE":
            progs = run.attack_programs()
            if not progs:
                say("  No attack programs loaded.")
            else:
                pi = menu([p["name"] for p in progs], "Program")
                if pi >= 0:
                    run.attack_ice(progs[pi]["template"])
        elif label == "Pull payload":
            run.pull()
        elif label == "Descend":
            run.descend()
        elif label.startswith("Cauterise"):
            run.cauterise()
        elif label == "Jack out" or choice < 0:
            run.jack_out()

        ui.clear_screen()
        print(ui.scene_frame("netrun", f"dive {ui.g('sep')} {run.host['name']}"))
        for line in run.drain_log():
            print("  " + ui.color(line, "cyan"))

        if char.is_dead():
            break

    print()
    for line in run.finish():
        print("  " + ui.color(line, "cyan"))


# ==========================================================================
# STORY INTERFACE
# ==========================================================================
def run_story(db: Database, dice: Dice, char: Character,
              qm: quests.QuestManager) -> None:
    nodes = qm.available()
    if not nodes:
        say("Nothing is pulling at you right now. Keep moving.")
        return

    header("open threads", kind="story")
    idx = menu([f"[{n['arc']}] {n['title']}" for n in nodes], "Open")
    if idx < 0:
        return

    node_id = nodes[idx]["id"]
    node, choices = qm.open_node(node_id)
    if not node:
        say("That thread has gone cold.")
        return

    header(node["title"], kind="story")
    sayc(node["body"], "ink")
    print()

    if not choices:
        say("There's nothing you can do about this yet.")
        return

    ci = menu([c["text"] for c in choices], "Do")
    if ci < 0:
        return

    print()
    for line in qm.resolve_choice(node_id, choices[ci]):
        say(line)

    if node["terminal"]:
        print()
        print(ui.scene_frame("ending", "the run is over"))
        print("  " + ui.color("Ending reached: " + node["title"], "magenta", bold=True))
        show_reputation(db)
        db.set_flag("game_over", True)


# ==========================================================================
# LOCATION / MARKET / CLINIC MENUS
# ==========================================================================
def run_explore(db: Database, dice: Dice, char: Character) -> None:
    district = char.row["district"]
    locs = worldgen.ensure_locations(db, dice, district)
    header(f"{content.DISTRICTS[district]['name']} {ui.g('sep')} sites", kind="explore")

    labels = []
    for loc in locs:
        tags = []
        if loc["looted"]:
            tags.append("stripped")
        if loc["cleared"]:
            tags.append("cleared")
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        labels.append(f"{loc['name']} (sec {loc['security']}, "
                      f"tier {loc['loot_tier']}){suffix}")
    labels.append("Generate a new lead")

    idx = menu(labels, "Go to")
    if idx < 0:
        return
    if idx == len(labels) - 1:
        new_id = worldgen.generate_location(db, dice, district)
        loc = db.one("SELECT * FROM locations WHERE id=?", (new_id,))
        say(f"  Word comes back about {loc['name']}.")
        return

    loc = locs[idx]
    db.update_player(location_id=loc["id"])
    header(loc["name"])
    say(worldgen.location_description(loc))
    print()

    hostiles = db.q(
        "SELECT id FROM npcs WHERE location_id=? AND alive=1", (loc["id"],)
    )
    if hostiles and not loc["cleared"]:
        opts = ["Move in.", "Back out."]
        if menu(opts, "Action") != 0:
            return
        run_combat(db, dice, char, [h["id"] for h in hostiles], loc["name"])
        if char.is_dead():
            return
        db.run("UPDATE locations SET cleared=1 WHERE id=?", (loc["id"],))
        print()

    if loc["looted"]:
        say("  Nothing left here.")
        return

    for line in actions.search_location(db, dice, char, loc["id"]):
        say(line)


def run_market(db: Database, dice: Dice, char: Character) -> None:
    district = char.row["district"]
    header(f"{content.DISTRICTS[district]['name']} {ui.g('sep')} market", kind="market")
    while True:
        print(f"\n  Credits: {char.credits()}cr")
        mode = menu(["Buy", "Sell", "Leave"], "Market")
        if mode != 0 and mode != 1:
            return

        if mode == 0:
            stock = actions.vendor_stock(db, dice, district)
            labels = []
            for key, price in stock:
                if key.startswith("ammo_"):
                    at = key.replace("ammo_", "")
                    labels.append(f"{content.AMMO_TYPES[at]['name']} "
                                  f"x{content.AMMO_TYPES[at]['box']} -- {price}cr")
                else:
                    tmpl = content.ITEMS.get(key) or content.CYBERWARE.get(key, {})
                    labels.append(f"{tmpl.get('name', key)} -- {price}cr")
            i = menu(labels, "Buy")
            if i >= 0:
                say("  " + actions.buy(db, dice, char, stock[i][0], stock[i][1]))
        else:
            sellable = [i for i in char.items() if not i["equipped"]]
            if not sellable:
                say("  Nothing to sell.")
                continue
            labels = [f"{i['name']} x{i['qty']} ({i['condition']}%)" for i in sellable]
            i = menu(labels, "Sell")
            if i >= 0:
                say("  " + actions.sell(db, dice, char, sellable[i]["id"]))


def run_clinic(db: Database, dice: Dice, char: Character) -> None:
    header("clinic", kind="clinic")
    while True:
        p = char.row
        band, _ = char.coherence_band()
        print(f"\n  HP {p['hp']}/{p['hp_max']}   Coherence {p['coherence']} [{band}]"
              f"   Credits {p['credits']}cr")
        choice = menu(
            ["Treatment (heal)", "Install cyberware", "Remove cyberware",
             "Field-repair cyberware", "Leave"],
            "Clinic",
        )
        if choice == 0:
            say("  " + actions.clinic_heal(db, dice, char))
        elif choice == 1:
            carried = char.items(category="cyberware")
            if not carried:
                say("  You're not carrying any implants.")
                continue
            i = menu([f"{c['name']} ({c['condition']}%) -- "
                      f"strain {content.CYBERWARE[c['template']]['strain']}"
                      for c in carried], "Install")
            if i < 0:
                continue
            back = menu(["Proper clinic (full price)",
                         "Back-alley (cheap, costs more Coherence)"], "Where") == 1
            say("  " + actions.clinic_install(db, dice, char,
                                              carried[i]["id"], back_alley=back))
        elif choice == 2:
            cw = char.cyberware()
            if not cw:
                say("  Nothing installed.")
                continue
            i = menu([f"{c['name']} (strain {c['strain']})" for c in cw], "Remove")
            if i >= 0:
                ok, msg = char.remove_cyberware(cw[i]["id"])
                say("  " + msg)
        elif choice == 3:
            cw = [c for c in char.cyberware() if c["integrity"] < 100]
            if not cw:
                say("  Everything's at full integrity.")
                continue
            i = menu([f"{c['name']} ({c['integrity']}%)" for c in cw], "Repair")
            if i >= 0:
                say("  " + actions.repair_with_toolkit(db, dice, char, cw[i]["id"]))
        else:
            return


def run_train(db: Database, char: Character) -> None:
    pts = int(db.flag("skill_points", 0))
    if pts <= 0:
        say("No skill points. Level up first.")
        return
    header(f"training -- {pts} points")
    names = sorted(content.SKILLS)
    labels = [f"{s} ({char.skill(s)}) -- governed by {content.SKILLS[s]}"
              for s in names]
    i = menu(labels, "Raise")
    if i >= 0:
        ok, msg = char.spend_skill_point(names[i])
        say("  " + msg)


def run_travel(db: Database, dice: Dice, char: Character) -> None:
    header("travel", kind="travel")
    keys = list(content.DISTRICTS)
    labels = []
    for k in keys:
        d = content.DISTRICTS[k]
        heat = get_heat(db, k)
        here = "  <- you are here" if k == char.row["district"] else ""
        labels.append(f"{d['name']} (sec {d['security']}, heat {heat}){here}")
    i = menu(labels, "Go to")
    if i >= 0:
        for line in actions.travel(db, dice, char, keys[i]):
            say(line)


# ==========================================================================
# MAIN LOOP
# ==========================================================================


def print_commands() -> None:
    header("commands")
    rows = [
        ("look / l", "describe where you are", "story", "open narrative threads"),
        ("explore / e", "find and search sites", "travel / t", "change district"),
        ("net / n", "dive the local network", "market / m", "buy and sell"),
        ("clinic / c", "medical and cyberware", "train", "spend skill points"),
        ("status / s", "your sheet", "inv / i", "inventory"),
        ("rep / r", "faction standing", "journal / j", "event log"),
        ("equip <id>", "equip an item", "use <id>", "use a consumable"),
        ("wait / w", "pass a turn", "theme", "change UI theme"),
        ("menu", "save / theme / quit", "help", "this list"),
        ("save", "write to disk", "quit", "save and exit"),
    ]
    for a, ad, b, bd in rows:
        left = ui.color(f"  {a:<14}", "cyan", bold=True) + ui.dim(f"{ad:<26}")
        right = ui.color(f"{b:<12}", "cyan", bold=True) + ui.dim(bd)
        print(left + right)


def look(db: Database, char: Character) -> None:
    d = content.DISTRICTS[char.row["district"]]
    header(d["name"], kind="travel")
    sayc(d["blurb"], "ink")
    ctrl = content.FACTIONS[d["control"]]
    print()
    say(f"Controlled by {ctrl['name']}. Security {d['security']}/10. "
        f"Local heat {get_heat(db, char.row['district'])}/100.")


# ==========================================================================
# SAVES, THEME, DIFFICULTY, MENU
# ==========================================================================
def _default_save_dir() -> str:
    """Where saves live.

    From source: ./saves, next to play.py, as before.
    Frozen executable: the platform's per-user data directory, because the
    working directory of a double-clicked binary is unpredictable (home on
    macOS, possibly read-only on Windows).
    VERDIGRIS_SAVE_DIR overrides both."""
    env = os.environ.get("VERDIGRIS_SAVE_DIR")
    if env:
        return env
    if not getattr(sys, "frozen", False):
        return "saves"
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("APPDATA") or home
        return os.path.join(base, "VerdigrisBay", "saves")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support",
                            "VerdigrisBay", "saves")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "verdigris-bay", "saves")


SAVE_DIR = _default_save_dir()


def _slugify(text: str) -> str:
    keep = "".join(c.lower() if c.isalnum() else "-" for c in text)
    slug = "-".join(part for part in keep.split("-") if part)
    return slug or "runner"


def list_save_paths() -> list[str]:
    paths: list[str] = []
    if os.path.isdir(SAVE_DIR):
        paths += sorted(glob.glob(os.path.join(SAVE_DIR, "*.save")))
    if not getattr(sys, "frozen", False):
        for p in sorted(glob.glob("*.save")):    # legacy top-level saves
            if p not in paths:
                paths.append(p)
    return paths


def save_summary(path: str) -> dict | None:
    try:
        db = Database(path)
        p = db.player()
        if not p:
            db.close()
            return None
        s = {
            "path": path, "name": p["name"], "handle": p["handle"],
            "role": p["role"], "level": p["level"], "district": p["district"],
            "turn": db.turn, "hp": p["hp"], "hp_max": p["hp_max"],
            "coherence": p["coherence"],
            "difficulty": db.get_meta("difficulty", "normal"),
            "dead": bool(db.flag("game_over")) or p["hp"] <= 0 or p["coherence"] <= 0,
        }
        db.close()
        return s
    except Exception:
        return None


def new_save_path(name: str) -> str:
    os.makedirs(SAVE_DIR, exist_ok=True)
    base = _slugify(name)
    path = os.path.join(SAVE_DIR, f"{base}.save")
    n = 2
    while os.path.exists(path):
        path = os.path.join(SAVE_DIR, f"{base}-{n}.save")
        n += 1
    return path


def choose_theme(db: Database | None = None) -> None:
    header("theme", kind="story")
    names = ui.theme_names()
    cur = ui.active_theme()
    labels = []
    for n in names:
        mark = ui.color("  " + ui.g("check") + " current", "green") if n == cur else ""
        labels.append(ui.color(ui.theme_label(n), "cyan", bold=True)
                      + ui.dim("  " + ui.theme_blurb(n)) + mark)
    i = menu(labels, "Theme")
    if i < 0:
        return
    ui.set_theme(names[i])
    if db is not None:
        db.set_meta("theme", names[i])
    # A little swatch so the choice is visible immediately.
    swatch = "  ".join(
        ui.color(ui.g("bar_full") * 2, c)
        for c in ("cyan", "magenta", "amber", "green", "red", "verd"))
    print("\n  " + ui.color("Theme set: ", "grey")
          + ui.color(ui.theme_label(names[i]), "magenta", bold=True))
    print("  " + swatch)


def choose_difficulty() -> str:
    header("difficulty", kind="story")
    order = content.DIFFICULTY_ORDER
    labels = []
    for k in order:
        d = content.DIFFICULTIES[k]
        labels.append(ui.color(d["name"], "amber", bold=True) + ui.dim("  " + d["blurb"]))
    i = menu(labels, "Difficulty")
    return order[i] if i >= 0 else "normal"


def game_menu(db: Database, char: Character, save_path: str) -> bool:
    """Returns True if the player chose to quit the program."""
    while True:
        print(ui.scene_frame("story", "menu"))
        opts = ["Resume", "Change theme", "Save now", "Save and quit"]
        try:
            c = menu(opts, "Menu")
        except QuitSignal as sig:
            if sig.hard:
                db.conn.commit()
                return True
            return False
        if c in (-1, 0):
            return False
        if c == 1:
            choose_theme(db)
        elif c == 2:
            db.conn.commit()
            print("  " + ui.color(ui.g("check") + " Saved to " + save_path, "green"))
        elif c == 3:
            db.conn.commit()
            print("  " + ui.color("Saved. Out.", "green", bold=True))
            return True


# ==========================================================================
# STARTUP BROWSER
# ==========================================================================
def startup_browser(seed: int | None) -> tuple[str, str] | None:
    """
    Show saved characters and let the player load one or start new.
    Returns (mode, path) where mode is 'load' or 'new', or None to quit.
    """
    ui.clear_screen()
    print(ui.title_screen())
    while True:
        summaries = [s for s in (save_summary(p) for p in list_save_paths()) if s]

        header("select a character", kind="travel")
        labels = []
        for s in summaries:
            state = (ui.color("  " + ui.g("skull") + " dead", "red")
                     if s["dead"] else ui.color(f"  {s['hp']}/{s['hp_max']} HP", "green"))
            dname = content.DISTRICTS.get(s["district"], {}).get("name", s["district"])
            diff = content.DIFFICULTIES.get(s["difficulty"], {}).get("name", s["difficulty"])
            labels.append(
                ui.color(s["name"], "white", bold=True) + " "
                + ui.color(f'"{s["handle"]}"', "magenta") + "  "
                + ui.color(s["role"], "cyan") + ui.dim(f" L{s['level']}")
                + ui.dim(f"  {dname} " + ui.g("sep") + f" T{s['turn']} " + ui.g("sep") + f" {diff}")
                + state)
        labels.append(ui.color("+ New character", "green", bold=True))
        labels.append(ui.color("Change theme", "cyan"))
        labels.append(ui.dim("Quit"))

        try:
            i = menu(labels, "Select")
        except QuitSignal:
            return None
        if i < 0:
            return None

        if i < len(summaries):
            return ("load", summaries[i]["path"])
        if i == len(summaries):                 # New character
            return ("new", "")
        if i == len(summaries) + 1:             # Change theme
            choose_theme(None)
            continue
        return None                             # Quit


def start_new_game(seed: int | None) -> tuple[Database, Dice, Character, str] | None:
    difficulty = choose_difficulty()
    dice = Dice(seed)
    name = ask("Your name") or f"{dice.pick(content.FIRST_NAMES)} {dice.pick(content.LAST_NAMES)}"
    handle = ask("Street handle") or dice.pick(content.STREET_NAMES)

    save_path = new_save_path(name)
    db = Database(save_path)
    db.set_meta("seed", dice.seed if dice.seed is not None else 0)
    db.set_meta("schema_version", 3)
    db.set_meta("theme", ui.active_theme())

    worldgen.seed_world(db, dice)
    quests.install_arc(db)
    char = create_character(db, dice, difficulty=difficulty, name=name, handle=handle)
    worldgen.ensure_locations(db, dice, "sable_row")

    ui.clear_screen()
    header("sable row", kind="travel")
    sayc(content.DISTRICTS["sable_row"]["blurb"], "ink")
    print("\n" + ui.dim("  Type ") + ui.color("help", "cyan", bold=True)
          + ui.dim(" for commands, ") + ui.color("menu", "cyan", bold=True)
          + ui.dim(" (or Ctrl+C) to save and exit."))
    return db, dice, char, save_path


def load_game(path: str, seed: int | None) -> tuple[Database, Dice, Character, str]:
    db = Database(path)
    dice = Dice(seed if seed is not None else db.get_meta("seed"))
    if db.get_meta("seed") is None:
        db.set_meta("seed", dice.seed if dice.seed is not None else 0)
    db.set_meta("schema_version", 3)
    ui.set_theme(db.get_meta("theme", ui.DEFAULT_THEME))

    char = Character(db, dice)
    quests.install_arc(db)
    ui.clear_screen()
    print(ui.title_screen())
    print("\n" + ui.color("  Welcome back, ", "ink")
          + ui.color(char.row["handle"], "magenta", bold=True)
          + ui.color(f".  Turn {db.turn}.", "ink"))
    print(ui.dim("  Type ") + ui.color("menu", "cyan", bold=True)
          + ui.dim(" (or Ctrl+C) at any time to save and exit."))
    return db, dice, char, path


# ==========================================================================
# GAME LOOP
# ==========================================================================
def run_loop(db: Database, dice: Dice, char: Character, save_path: str) -> str:
    """Run one character's session. Returns 'quit' (exit program) or
    'end' (character finished; caller may return to the browser)."""
    qm = quests.QuestManager(db, dice, char)

    while True:
        if db.flag("game_over"):
            print("\n" + ui.dim("The run is over."))
            return "end"

        if char.is_dead():
            print(ui.scene_frame("ending", "flatline"))
            if char.row["coherence"] <= 0:
                sayc("Your Coherence hit zero. There is still a body walking "
                     "around Verdigris Bay wearing your face and your chrome. "
                     "It is not you, and it has not noticed.", "red")
            else:
                sayc("You bleed out somewhere in " +
                     content.DISTRICTS[char.row['district']]['name'] +
                     ". The city does not slow down for it.", "red")
            show_reputation(db)
            db.set_flag("game_over", True)
            return "end"

        print("\n" + ui.hud(db, char, compact=True))

        try:
            raw = ask(content.DISTRICTS[char.row['district']]['name'])
            parts = raw.split()
            cmd = parts[0].lower() if parts else ""
            arg = parts[1] if len(parts) > 1 else ""

            # New screen per command: the result of this action stays visible
            # until the next one is entered.
            if cmd:
                ui.clear_screen()

            ticks = False

            if cmd in ("quit", "q", "exit"):
                db.conn.commit()
                say("Saved. Out.")
                return "quit"
            elif cmd in ("menu", "esc", "pause"):
                if game_menu(db, char, save_path):
                    return "quit"
            elif cmd == "theme":
                choose_theme(db)
            elif cmd in ("help", "?"):
                print_commands()
            elif cmd in ("look", "l"):
                look(db, char)
            elif cmd in ("status", "s"):
                show_status(db, char)
            elif cmd in ("inv", "i", "inventory"):
                show_inventory(db, char)
            elif cmd in ("rep", "r"):
                show_reputation(db)
            elif cmd in ("journal", "j"):
                show_journal(db)
            elif cmd == "story":
                run_story(db, dice, char, qm)
                ticks = True
            elif cmd in ("explore", "e"):
                run_explore(db, dice, char)
                ticks = True
            elif cmd in ("travel", "t"):
                run_travel(db, dice, char)
                ticks = True
            elif cmd in ("net", "n"):
                run_netrun(db, dice, char)
                ticks = True
            elif cmd in ("market", "m"):
                run_market(db, dice, char)
                ticks = True
            elif cmd in ("clinic", "c"):
                run_clinic(db, dice, char)
                ticks = True
            elif cmd == "train":
                run_train(db, char)
            elif cmd == "equip":
                if arg.isdigit():
                    ok, msg = char.equip(int(arg))
                    say("  " + msg)
                else:
                    say("  Usage: equip <item id> (see 'inv')")
            elif cmd == "use":
                if arg.isdigit():
                    say("  " + actions.use_consumable(db, dice, char, int(arg)))
                    ticks = True
                else:
                    say("  Usage: use <item id> (see 'inv')")
            elif cmd in ("wait", "w"):
                say("  You wait.")
                ticks = True
            elif cmd == "save":
                db.conn.commit()
                say(f"  Saved to {save_path}.")
            elif cmd == "":
                continue
            else:
                say(f"  Unknown command: {cmd}. Type 'help'.")

            if ticks and not db.flag("game_over"):
                tick_world(db, dice, char, qm)

        except QuitSignal as sig:
            # Ctrl+C / EOF from anywhere unwinds here. EOF (closed stream)
            # just saves and exits; Ctrl+C opens the menu.
            if sig.hard:
                db.conn.commit()
                return "quit"
            if game_menu(db, char, save_path):
                return "quit"
            # otherwise: resume the loop


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    seed = None
    if "--seed" in argv:
        try:
            seed = int(argv[argv.index("--seed") + 1])
        except (ValueError, IndexError):
            seed = None

    explicit = [a for a in argv if not a.startswith("--")
                and a != (str(seed) if seed is not None else None)]
    explicit_path = explicit[0] if explicit else None

    # Direct-path launch keeps the old behaviour: load or create at that path.
    if explicit_path:
        db = Database(explicit_path)
        if db.player() is None:
            dice = Dice(seed)
            db.set_meta("seed", dice.seed if dice.seed is not None else 0)
            db.set_meta("schema_version", 3)
            db.set_meta("theme", ui.active_theme())
            worldgen.seed_world(db, dice)
            quests.install_arc(db)
            try:
                difficulty = choose_difficulty()
                char = create_character(db, dice, difficulty=difficulty)
            except QuitSignal:
                db.close()
                return 0
            worldgen.ensure_locations(db, dice, "sable_row")
            header("sable row", kind="travel")
            sayc(content.DISTRICTS["sable_row"]["blurb"], "ink")
            print("\n" + ui.dim("  Type ") + ui.color("help", "cyan", bold=True)
                  + ui.dim(" for commands."))
        else:
            db, dice, char, explicit_path = load_game(explicit_path, seed)
        run_loop(db, dice, char, explicit_path)
        db.close()
        return 0

    # Browser launch: pick, load or create, and return here on death.
    while True:
        try:
            choice = startup_browser(seed)
        except QuitSignal:
            return 0
        if choice is None:
            print("\n" + ui.dim("Out."))
            return 0

        mode, path = choice
        try:
            if mode == "new":
                started = start_new_game(seed)
                if started is None:
                    continue
                db, dice, char, save_path = started
            else:
                db, dice, char, save_path = load_game(path, seed)
        except QuitSignal:
            continue

        result = run_loop(db, dice, char, save_path)
        db.close()
        if result == "quit":
            return 0
        # 'end' -> back to the browser to pick another character.


if __name__ == "__main__":
    sys.exit(main())
