"""
combat.py -- Tactical resolution.

STRUCTURE OF A ROUND
    1. Initiative -- rolled once at encounter start, held for the fight
    2. On the player's turn: one action (attack / item / reload / move / flee)
    3. Enemies act in initiative order
    4. End of round: status effects tick, ammo and armour state persist

HIT LOCATIONS
    A d10 location roll modifies damage. Head hits multiply; limb hits are
    reduced but can cripple. This is a common tabletop structure implemented
    here with original values.

        1     head        x2 damage, cyberware shock
        2-3   torso       x1
        4-5   torso       x1
        6-7   arm         x0.7, may disarm
        8-10  leg         x0.7, may cripple (REF penalty)

DAMAGE PIPELINE
    weapon dice + attribute bonus (melee only) + margin bonus
      -> location multiplier
      -> armour SP reduced by weapon AP
      -> HP

    The margin bonus is what makes skill matter beyond hit/miss: every 4
    points of margin over the DV adds +1 damage, so a good shooter is not
    merely more likely to connect but lands harder when they do.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import content
from .db import Database, jdump, jload
from .dice import Dice
from .rules import Character, adjust_heat, adjust_rep

HIT_LOCATIONS = {
    1:  ("head",  2.0),
    2:  ("torso", 1.0), 3: ("torso", 1.0),
    4:  ("torso", 1.0), 5: ("torso", 1.0),
    6:  ("arm",   0.7), 7: ("arm",   0.7),
    8:  ("leg",   0.7), 9: ("leg",   0.7), 10: ("leg", 0.7),
}


@dataclass
class Combatant:
    """Runtime wrapper for an NPC in a fight."""
    npc_id: int
    name: str
    hp: int
    hp_max: int
    threat: int
    faction: str | None
    initiative: int = 0
    armor: int = 0
    statuses: dict[str, int] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def attack_pool(self) -> tuple[int, int]:
        """(attribute, skill) scaled from threat rating."""
        return 3 + self.threat, self.threat

    def damage_dice(self) -> tuple[int, int]:
        return (1 + self.threat // 2, 6)


class Combat:
    """
    One encounter. Instantiate, then drive with player_action() until
    resolved() returns True.
    """

    def __init__(self, db: Database, dice: Dice, char: Character,
                 npc_ids: list[int], context: str = ""):
        self.db = db
        self.dice = dice
        self.char = char
        self.context = context
        self.round = 1
        self.log: list[str] = []
        self.fled = False

        self.enemies: list[Combatant] = []
        diff_tmod = None
        for nid in npc_ids:
            row = db.one("SELECT * FROM npcs WHERE id=? AND alive=1", (nid,))
            if not row:
                continue
            if diff_tmod is None:
                d = content.DIFFICULTIES.get(
                    db.get_meta("difficulty", "normal"),
                    content.DIFFICULTIES["normal"])
                diff_tmod = d["enemy_threat"]
            threat = max(1, row["threat"] + diff_tmod)
            c = Combatant(
                npc_id=row["id"],
                name=(f"{row['name']} \"{row['handle']}\"" if row["handle"] else row["name"]),
                hp=row["hp"], hp_max=row["hp"],
                threat=threat, faction=row["faction_id"],
                # TUNING: enemy armour was threat-1, which meant a threat-3
                # opponent carried SP 2 -- enough to nearly zero out any 1d6
                # weapon. Halving it keeps armour-piercing meaningful without
                # hard-walling low-calibre and holdout weapons entirely.
                armor=threat // 2,
            )
            c.initiative = 3 + c.threat + dice.d10()
            self.enemies.append(c)

        self.player_init = char.initiative()
        self.enemies.sort(key=lambda e: -e.initiative)

    # -- state -------------------------------------------------------------
    def living(self) -> list[Combatant]:
        return [e for e in self.enemies if e.alive]

    def resolved(self) -> bool:
        return self.fled or not self.living() or self.char.is_dead()

    def outcome(self) -> str:
        if self.fled:
            return "fled"
        if self.char.is_dead():
            return "defeat"
        return "victory"

    def emit(self, text: str) -> None:
        self.log.append(text)

    def drain_log(self) -> list[str]:
        out = self.log[:]
        self.log = []
        return out

    # ------------------------------------------------------------------
    # PLAYER ACTIONS
    # ------------------------------------------------------------------
    def player_attack(self, target_index: int = 0, aimed: bool = False) -> None:
        """
        Attack the target. aimed=True is a deliberate head shot: a single
        precise round at a steep to-hit penalty for the head location's x2
        multiplier -- the Cyberpunk aimed-shot tradeoff.
        """
        targets = self.living()
        if not targets:
            return
        target = targets[min(target_index, len(targets) - 1)]

        weapon = self.char.equipped_weapon()
        if weapon is None:
            self._unarmed(target)
            self._enemy_phase()
            return

        tmpl = content.ITEMS[weapon["template"]]
        skill_name = tmpl.get("skill", "firearms")
        is_ranged = skill_name == "firearms"

        # --- ammunition -------------------------------------------------
        if is_ranged and tmpl.get("mag"):
            if weapon["loaded"] <= 0:
                # Fall back to unarmed rather than forfeiting the action.
                # Forfeiting created an unwinnable loop: a player out of both
                # magazine and reserve ammo, with no melee weapon, could only
                # stand there taking free hits until they died or fled.
                reserve = self.char.ammo_count(tmpl["ammo"])
                if reserve > 0:
                    self.emit(f"{tmpl['name']} is empty -- reload.")
                    self._enemy_phase()
                    return
                self.emit(f"{tmpl['name']} is empty and so is your kit. "
                          f"You close the distance.")
                self._unarmed(target)
                self._enemy_phase()
                return
            # An aimed shot spends one round; a normal attack spends its ROF.
            shots = 1 if aimed else min(tmpl.get("rof", 1), weapon["loaded"])
            self.db.run(
                "UPDATE items SET loaded=loaded-? WHERE id=?", (shots, weapon["id"])
            )
        else:
            shots = 1 if aimed else tmpl.get("rof", 1)

        # --- degraded weapons jam ---------------------------------------
        if weapon["condition"] < 40 and self.dice.chance((40 - weapon["condition"]) * 0.01):
            self.emit(f"{tmpl['name']} JAMS. Clearing it costs you the round.")
            self._enemy_phase()
            return

        # --- resolve each shot ------------------------------------------
        mods = {}
        if target.statuses.get("suppressed"):
            mods["target_pinned"] = 2
        if self.char.has_status("suppressed"):
            mods["pinned"] = -2
        if aimed:
            mods["aimed"] = -6          # steep penalty for the called shot
        # Higher-threat enemies are harder to hit.
        difficulty = 11 + target.threat

        hits = 0
        total_damage = 0
        for _ in range(shots):
            chk = self.char.check(skill_name, difficulty=difficulty, **mods)
            if not chk.success:
                continue
            hits += 1

            if aimed:
                loc_name, loc_mult = "head", 2.0
            else:
                loc_roll = self.dice.d10()
                loc_name, loc_mult = HIT_LOCATIONS[loc_roll]

            count, sides = tmpl["damage"]
            dmg = self.dice.d(sides, count)
            if tmpl.get("bonus_dmg_attr"):
                dmg += self.char.attr(tmpl["bonus_dmg_attr"]) // 2
            dmg += chk.margin // 4          # skill converts to damage
            dmg = int(dmg * loc_mult)
            dmg = max(1, dmg - max(0, target.armor - tmpl.get("ap", 0)))

            target.hp -= dmg
            total_damage += dmg
            crit = " CRITICAL." if chk.critical else ""
            self.emit(f"Hit -- {loc_name} -- {dmg} damage.{crit}")

            if tmpl.get("on_hit"):
                target.statuses[tmpl["on_hit"]] = 2
                self.emit(f"{target.name} is {tmpl['on_hit']}.")
            if loc_name == "head" and self.dice.chance(0.6 if aimed else 0.3):
                target.statuses["stunned"] = 1
                self.emit(f"{target.name} is stunned.")

        if hits == 0:
            self.emit(f"You miss {target.name}.")
        else:
            self.emit(f"{target.name}: {max(0, target.hp)}/{target.hp_max} HP.")

        # --- weapon wear -------------------------------------------------
        if self.dice.chance(0.2):
            self.db.run(
                "UPDATE items SET condition=MAX(0,condition-1) WHERE id=?",
                (weapon["id"],),
            )

        if not target.alive:
            self._kill(target)

        self._enemy_phase()

    def _unarmed(self, target: Combatant) -> None:
        chk = self.char.check("melee", difficulty=11 + target.threat)
        if chk.success:
            dmg = max(1, self.dice.d6() + self.char.attr("BOD") // 3 - target.armor)
            target.hp -= dmg
            self.emit(f"You hit {target.name} bare-handed for {dmg}.")
            if not target.alive:
                self._kill(target)
        else:
            self.emit("You swing and connect with nothing.")

    def player_reload(self) -> None:
        weapon = self.char.equipped_weapon()
        if not weapon:
            self.emit("Nothing to reload.")
            self._enemy_phase()
            return
        tmpl = content.ITEMS[weapon["template"]]
        mag = tmpl.get("mag")
        if not mag:
            self.emit(f"{tmpl['name']} doesn't take a magazine.")
            self._enemy_phase()
            return
        need = mag - weapon["loaded"]
        ammo_type = tmpl["ammo"]
        have = self.char.ammo_count(ammo_type)
        if have <= 0:
            self.emit(f"No {content.AMMO_TYPES[ammo_type]['name'].lower()} left.")
            self._enemy_phase()
            return
        loaded = min(need, have)
        self.char.consume_ammo(ammo_type, loaded)
        self.db.run(
            "UPDATE items SET loaded=loaded+? WHERE id=?", (loaded, weapon["id"])
        )
        self.emit(f"Reloaded -- {weapon['loaded'] + loaded}/{mag}.")
        self._enemy_phase()

    def player_use_item(self, item_id: int) -> None:
        from .actions import use_consumable   # local import avoids a cycle
        msg = use_consumable(self.db, self.dice, self.char, item_id, in_combat=True)
        self.emit(msg)
        self._enemy_phase()

    def player_flee(self) -> None:
        """
        Fleeing is an opposed athletics check against the fastest enemy.
        Failure costs a free attack from everyone.
        """
        fastest = max(self.living(), key=lambda e: e.threat)
        won, margin = self.dice.opposed(
            self.char.attr("REF"), self.char.skill("athletics"),
            3 + fastest.threat, fastest.threat,
            encumbrance=self.char.armor_penalty(),
        )
        if won:
            self.fled = True
            self.emit("You break contact and go.")
            adjust_heat(self.db, self.char.row["district"], 3)
        else:
            self.emit("They cut you off. Everyone gets a shot.")
            for e in self.living():
                self._enemy_attack(e, free=True)

    # ------------------------------------------------------------------
    # ENEMY PHASE
    # ------------------------------------------------------------------
    def _enemy_phase(self) -> None:
        if self.resolved():
            return
        for e in self.living():
            if e.statuses.get("stunned"):
                e.statuses["stunned"] -= 1
                if e.statuses["stunned"] <= 0:
                    del e.statuses["stunned"]
                self.emit(f"{e.name} is stunned and loses the round.")
                continue
            self._enemy_attack(e)
            if self.char.is_dead():
                return

        for msg in self.char.tick_statuses():
            self.emit(msg)
        self.round += 1

    def _enemy_attack(self, e: Combatant, free: bool = False) -> None:
        attr, skill = e.attack_pool()
        # Player dodge raises the effective difficulty.
        #
        # TUNING: this used dodge//2, which gave non-combat roles almost no
        # defensive floor -- a Runner (REF 5, no dodge rank) sat at DV 12
        # against a threat-3 attacker averaging 14.5, so they were hit ~70% of
        # the time and died in two rounds. Using the full dodge value gives
        # every role a survivable baseline while still rewarding investment:
        # an Enforcer with REF 7 and dodge 3 sits at DV 20 instead of 15.
        dodge = self.char.attr("REF") + self.char.skill("dodge")
        chk = self.dice.check(attribute=attr, skill=skill, difficulty=10 + dodge)
        if not chk.success:
            self.emit(f"{e.name} fires and misses.")
            return

        count, sides = e.damage_dice()
        raw = self.dice.d(sides, count) + chk.margin // 4
        loc_name, loc_mult = HIT_LOCATIONS[self.dice.d10()]
        raw = int(raw * loc_mult)

        taken, notices = self.char.damage(raw, ap=max(0, e.threat - 1), source=e.name)
        tag = " (free attack)" if free else ""
        self.emit(f"{e.name} hits you in the {loc_name} for {taken}.{tag}")
        for n in notices:
            self.emit(n)

    # ------------------------------------------------------------------
    # RESOLUTION
    # ------------------------------------------------------------------
    def _kill(self, target: Combatant) -> None:
        self.db.run("UPDATE npcs SET alive=0, hp=0 WHERE id=?", (target.npc_id,))
        self.emit(f"{target.name} is down.")

        # Killing generates heat and costs standing with their faction.
        district = self.char.row["district"]
        adjust_heat(self.db, district, 6)
        if target.faction:
            adjust_rep(self.db, target.faction, -6)

    def finish(self) -> list[str]:
        """
        Award XP and salvage. Called once by the caller after resolved().
        """
        out = []
        if self.outcome() != "victory":
            return out

        xp = sum(12 + e.threat * 8 for e in self.enemies if not e.alive)
        out += self.char.award_xp(xp)
        out.append(f"+{xp} XP.")

        # Scavver passive: strip the bodies.
        if self.char.passive() == "scrounger":
            for e in self.enemies:
                if e.alive:
                    continue
                if self.dice.chance(0.6):
                    creds = self.dice.between(40, 90) * max(1, e.threat)
                    self.char.credits(creds)
                    out.append(f"Salvaged {creds}cr off {e.name}.")
                if self.dice.chance(0.3):
                    key = self.dice.weighted(content.LOOT_TIERS[min(3, e.threat)])
                    if key in content.ITEMS:
                        self.char.give_item(key, condition=self.dice.between(30, 70))
                        out.append(f"Took their {content.ITEMS[key]['name']}.")
        return out
