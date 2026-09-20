"""
rules.py -- Mechanics translation layer.

This is where abstract tabletop-style procedures become executable state
changes. Everything reads and writes the database; the Character class is a
live view over the `player` row, not a cached copy.

SYSTEMS IMPLEMENTED HERE
    1. Derived statistics (HP, initiative, armour, carry)
    2. Effective attributes -- base + cyberware + status effects
    3. COHERENCE -- the cost of chrome (original mechanic, see below)
    4. Cyberware integrity degradation and misfire
    5. Reputation with cross-faction friction
    6. Inventory, ammunition and equipment
    7. Heat -- how much attention you've drawn in a district
    8. Experience and advancement

THE COHERENCE MECHANIC
    Coherence starts at 100 and only ever goes down permanently. Each implant
    inflicts its `strain` value as a permanent reduction. Coherence is the
    integration between your nervous system and the hardware bolted into it.

        90-100  Integrated   -- no penalty
        70-89   Drifting     -- -1 PRE
        50-69   Fraying      -- -1 PRE, -1 NRV, occasional intrusive sensory noise
        30-49   Dissociating -- -2 PRE, -2 NRV, forced composure checks under stress
        10-29   Fugue        -- -3 PRE, -3 NRV, hostile misidentification possible
        0-9     Flatline     -- run ends

    The design intent is a real resource tension: chrome is the most direct
    route to power, and the game's most dangerous resource sink. A Coherence
    build and a chrome build are genuinely different playthroughs, and the
    ending you can reach depends partly on which you chose.

CYBERWARE INTEGRITY
    Separate from Coherence. Integrity is maintenance, not psychology. It
    drops when you take damage, when you use an implant's active grant, and
    when EMP hits you. Below 50 the implant's attribute bonus halves; below
    25 it can misfire on use; at 0 it goes offline until repaired.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import content
from .db import Database, jdump, jload
from .dice import Dice

# Map the content.py attribute keys onto database column names.
ATTR_COLUMN = {
    "REF": "ref", "BOD": "bod", "INT": "intl",
    "NRV": "nrv", "PRE": "pre", "TEC": "tec", "WIR": "wir",
}

COHERENCE_BANDS = [
    (90, "Integrated",   {}),
    (70, "Drifting",     {"PRE": -1}),
    (50, "Fraying",      {"PRE": -1, "NRV": -1}),
    (30, "Dissociating", {"PRE": -2, "NRV": -2}),
    (10, "Fugue",        {"PRE": -3, "NRV": -3}),
    (0,  "Flatline",     {"PRE": -5, "NRV": -5}),
]


# ==========================================================================
# CHARACTER
# ==========================================================================
class Character:
    """
    Live view over the player row plus their skills, cyberware, items and
    status effects. Constructed cheaply; do not cache across turns.
    """

    def __init__(self, db: Database, dice: Dice):
        self.db = db
        self.dice = dice

    # -- raw row -----------------------------------------------------------
    @property
    def row(self) -> sqlite3.Row:
        r = self.db.player()
        if r is None:
            raise RuntimeError("no character exists yet")
        return r

    def __getattr__(self, item):
        # Delegate unknown attributes to the DB row so char.credits works.
        if item in ("db", "dice"):
            raise AttributeError(item)
        row = self.db.player()
        if row is not None and item in row.keys():
            return row[item]
        raise AttributeError(item)

    # -- attributes --------------------------------------------------------
    def base_attr(self, key: str) -> int:
        return int(self.row[ATTR_COLUMN[key]])

    def attr(self, key: str) -> int:
        """
        Effective attribute: base + cyberware (scaled by integrity)
        + status effect modifiers + coherence band penalty.
        """
        value = self.base_attr(key)
        value += self.cyber_attr_bonus(key)
        value += self.status_attr_mod(key)
        value += self.coherence_penalties().get(key, 0)
        return max(1, value)

    def cyber_attr_bonus(self, key: str) -> int:
        """Sum implant bonuses. Integrity < 50 halves the bonus (round down)."""
        total = 0
        for imp in self.cyberware():
            if not imp["online"]:
                continue
            tmpl = content.CYBERWARE.get(imp["template"], {})
            bonus = tmpl.get("effects", {}).get(key, 0)
            if not bonus:
                continue
            if imp["integrity"] < 50:
                bonus = bonus // 2
            total += bonus
        return total

    def status_attr_mod(self, key: str) -> int:
        total = 0
        for eff in self.statuses():
            spec = content.STATUS_EFFECTS.get(eff["effect"], {})
            total += spec.get("attr_mod", {}).get(key, 0) * eff["magnitude"]
        return total

    def skill(self, name: str) -> int:
        row = self.db.one("SELECT rank FROM skills WHERE skill=?", (name,))
        return int(row["rank"]) if row else 0

    def skill_attr(self, name: str) -> int:
        """The governing attribute value for a skill."""
        return self.attr(content.SKILLS.get(name, "INT"))

    # -- the standard check ------------------------------------------------
    def check(self, skill_name: str, difficulty="routine", **mods):
        """
        The single entry point for every player task resolution.

        Automatically folds in: governing attribute, skill rank, armour
        encumbrance penalty (for physical skills) and any caller modifiers.
        """
        attr_val = self.skill_attr(skill_name)
        rank = self.skill(skill_name)

        if skill_name in ("stealth", "athletics", "dodge", "melee"):
            mods.setdefault("encumbrance", self.armor_penalty())

        # Wound states: being hurt makes everything harder. This penalty
        # applies to the player's own actions only -- the defensive DV that
        # enemies roll against is computed separately in combat.py, so a bad
        # wound never cascades into an unrecoverable defence spiral.
        frac = self.row["hp"] / max(1, self.row["hp_max"])
        if frac <= 0.25:
            mods.setdefault("wounded", -2)
        elif frac <= 0.50:
            mods.setdefault("wounded", -1)

        return self.dice.check(
            attribute=attr_val, skill=rank, difficulty=difficulty, **mods
        )

    # -- derived -----------------------------------------------------------
    def max_hp(self) -> int:
        return 10 + self.base_attr("BOD") * 3 + (self.row["level"] - 1) * 2

    def initiative(self) -> int:
        return self.attr("REF") + self.dice.d10()

    def armor_sp(self) -> int:
        """Stopping power from equipped armour plus subdermal implants."""
        sp = 0
        for it in self.items(equipped_only=True):
            tmpl = content.ARMOR.get(it["template"])
            if tmpl:
                # Condition scales effective SP -- shot-up armour stops less.
                sp += int(tmpl["sp"] * (it["condition"] / 100))
        for imp in self.cyberware():
            if imp["online"] and "armor_2" in content.CYBERWARE.get(
                imp["template"], {}
            ).get("grants", []):
                sp += 2
        return sp

    def armor_penalty(self) -> int:
        worst = 0
        for it in self.items(equipped_only=True):
            tmpl = content.ARMOR.get(it["template"])
            if tmpl:
                worst = min(worst, tmpl.get("penalty", 0))
        return worst

    def grants(self) -> set[str]:
        """All abilities granted by online cyberware."""
        out: set[str] = set()
        suppressed = any(
            content.STATUS_EFFECTS.get(e["effect"], {}).get("suppress_cyber")
            for e in self.statuses()
        )
        if suppressed:
            return out
        for imp in self.cyberware():
            if imp["online"]:
                out.update(content.CYBERWARE.get(imp["template"], {}).get("grants", []))
        return out

    def passive(self) -> str:
        return content.ROLES.get(self.row["role"], {}).get("passive", "")

    # ----------------------------------------------------------------------
    # COHERENCE
    # ----------------------------------------------------------------------
    def coherence_band(self) -> tuple[str, dict]:
        c = self.row["coherence"]
        for threshold, label, penalties in COHERENCE_BANDS:
            if c >= threshold:
                return label, penalties
        return "Flatline", {"PRE": -5, "NRV": -5}

    def coherence_penalties(self) -> dict:
        return self.coherence_band()[1]

    def spend_coherence(self, amount: int, reason: str = "") -> tuple[int, str]:
        """
        Permanently reduce Coherence. Returns (new_value, band_label).
        Logs a band transition when one occurs, because the player needs to
        feel this happening.
        """
        before_band = self.coherence_band()[0]
        new = self.db.adjust_player("coherence", -abs(amount), lo=0, hi=100)
        after_band = self.coherence_band()[0]

        if after_band != before_band:
            self.db.log(
                f"Coherence has fallen to {new}. You are {after_band}. {reason}".strip(),
                kind="coherence",
            )
            if after_band in ("Dissociating", "Fugue"):
                self.add_status("dissociated", turns=6, source="coherence")
        return new, after_band

    def restore_coherence(self, amount: int) -> int:
        """
        Coherence recovery is rare and expensive -- therapy, downtime, or
        removing chrome. Never a simple purchase.
        """
        return self.db.adjust_player("coherence", abs(amount), lo=0, hi=100)

    # ----------------------------------------------------------------------
    # CYBERWARE
    # ----------------------------------------------------------------------
    def cyberware(self) -> list[sqlite3.Row]:
        return self.db.q("SELECT * FROM cyberware ORDER BY id")

    def slots_used(self, slot: str) -> int:
        return len([c for c in self.cyberware() if c["slot"] == slot])

    def slot_capacity(self, slot: str) -> int:
        return 3 if slot == "body" else 1

    def install_cyberware(self, template_key: str, quality: int = 100) -> tuple[bool, str]:
        """
        Install an implant. Returns (success, message).

        quality < 100 represents back-alley work: the implant starts
        pre-degraded and costs extra Coherence.
        """
        tmpl = content.CYBERWARE.get(template_key)
        if not tmpl:
            return False, "No such implant."

        slot = tmpl["slot"]
        if self.slots_used(slot) >= self.slot_capacity(slot):
            return False, f"Your {slot} slot is already full."

        strain = tmpl["strain"]
        if quality < 100:
            # Cheap surgery bites: +1 strain per 10 points of missing quality.
            strain += (100 - quality) // 10

        if self.row["coherence"] - strain <= 0:
            return False, ("Your Coherence will not survive that installation. "
                           "The doc refuses -- or should.")

        self.db.run(
            "INSERT INTO cyberware(template,name,slot,strain,integrity,"
            "installed_turn,props) VALUES(?,?,?,?,?,?,?)",
            (template_key, tmpl["name"], slot, strain, quality,
             self.db.turn, jdump({})),
        )
        new_coh, band = self.spend_coherence(strain, reason=f"({tmpl['name']} installed)")
        self.db.log(f"Installed {tmpl['name']}. Coherence {new_coh} ({band}).", "cyber")
        return True, (f"{tmpl['name']} installed. Coherence {new_coh} -- {band}.")

    def remove_cyberware(self, cyber_id: int) -> tuple[bool, str]:
        """
        Extraction returns HALF the strain as recovered Coherence. Getting the
        chrome out helps, but never fully undoes it -- the scar tissue is both
        literal and not.
        """
        row = self.db.one("SELECT * FROM cyberware WHERE id=?", (cyber_id,))
        if not row:
            return False, "No such implant."
        recovered = row["strain"] // 2
        self.db.run("DELETE FROM cyberware WHERE id=?", (cyber_id,))
        self.restore_coherence(recovered)
        self.db.log(f"Extracted {row['name']}. Recovered {recovered} Coherence.", "cyber")
        return True, f"{row['name']} removed. +{recovered} Coherence."

    def degrade_cyberware(self, amount: int, target_id: int | None = None) -> list[str]:
        """
        Wear implants down. Called by: taking damage, using active grants,
        EMP effects, and diving the net.

        Returns human-readable notices for anything that crossed a threshold.
        """
        notices = []
        implants = self.cyberware()
        if not implants:
            return notices
        targets = (
            [r for r in implants if r["id"] == target_id]
            if target_id else [self.dice.pick(implants)]
        )

        for imp in targets:
            new_int = max(0, imp["integrity"] - amount)
            online = 1 if new_int > 0 else 0
            self.db.run(
                "UPDATE cyberware SET integrity=?, online=? WHERE id=?",
                (new_int, online, imp["id"]),
            )
            if imp["integrity"] >= 50 > new_int:
                notices.append(f"{imp['name']} is degrading -- output halved.")
            if imp["integrity"] >= 25 > new_int:
                notices.append(f"{imp['name']} is failing. It may misfire.")
            if new_int == 0 and imp["integrity"] > 0:
                notices.append(f"{imp['name']} has gone OFFLINE.")
                self.db.log(f"{imp['name']} failed.", "cyber")
        return notices

    def repair_cyberware(self, cyber_id: int, amount: int) -> str:
        row = self.db.one("SELECT * FROM cyberware WHERE id=?", (cyber_id,))
        if not row:
            return "No such implant."
        new_int = min(100, row["integrity"] + amount)
        self.db.run(
            "UPDATE cyberware SET integrity=?, online=1 WHERE id=?",
            (new_int, cyber_id),
        )
        return f"{row['name']} integrity restored to {new_int}%."

    def misfire_check(self, cyber_id: int) -> bool:
        """
        True if a degraded implant misfires this use.
        Below 25 integrity the chance is (25 - integrity) * 2 percent.
        """
        row = self.db.one("SELECT integrity FROM cyberware WHERE id=?", (cyber_id,))
        if not row or row["integrity"] >= 25:
            return False
        return self.dice.chance((25 - row["integrity"]) * 0.02)

    # ----------------------------------------------------------------------
    # STATUS EFFECTS
    # ----------------------------------------------------------------------
    def statuses(self) -> list[sqlite3.Row]:
        return self.db.q(
            "SELECT * FROM status_effects WHERE target_type='player' AND target_id=1"
        )

    def has_status(self, effect: str) -> bool:
        return any(e["effect"] == effect for e in self.statuses())

    def add_status(self, effect: str, turns: int = 3, magnitude: int = 1,
                   source: str = "") -> None:
        spec = content.STATUS_EFFECTS.get(effect, {})
        existing = self.db.one(
            "SELECT * FROM status_effects WHERE target_type='player' "
            "AND target_id=1 AND effect=?", (effect,),
        )
        if existing and not spec.get("stacks", False):
            # Refresh duration, keep the higher magnitude.
            self.db.run(
                "UPDATE status_effects SET turns=?, magnitude=? WHERE id=?",
                (max(turns, existing["turns"]),
                 max(magnitude, existing["magnitude"]), existing["id"]),
            )
            return
        self.db.run(
            "INSERT INTO status_effects(target_type,target_id,effect,magnitude,"
            "turns,source) VALUES('player',1,?,?,?,?)",
            (effect, magnitude, turns, source),
        )

    def clear_status(self, effect: str) -> None:
        self.db.run(
            "DELETE FROM status_effects WHERE target_type='player' "
            "AND target_id=1 AND effect=?", (effect,),
        )

    def tick_statuses(self) -> list[str]:
        """
        Advance all timed effects by one turn. Applies per-turn damage,
        expires finished effects, handles the stim->crash transition.
        """
        messages = []
        for eff in self.statuses():
            spec = content.STATUS_EFFECTS.get(eff["effect"], {})
            dmg = spec.get("per_turn_damage", 0) * eff["magnitude"]
            if dmg:
                self.damage(dmg, bypass_armor=True, source=eff["effect"])
                messages.append(f"{eff['effect'].title()}: {dmg} damage.")

            remaining = eff["turns"] - 1
            if remaining <= 0:
                self.db.run("DELETE FROM status_effects WHERE id=?", (eff["id"],))
                messages.append(f"{eff['effect'].title()} has worn off.")
                if eff["effect"] == "stimmed":
                    self.add_status("crash", turns=5, source="stim")
                    messages.append("The stim crash hits.")
            else:
                self.db.run(
                    "UPDATE status_effects SET turns=? WHERE id=?",
                    (remaining, eff["id"]),
                )
        return messages

    # ----------------------------------------------------------------------
    # DAMAGE AND HEALING
    # ----------------------------------------------------------------------
    def damage(self, amount: int, bypass_armor: bool = False,
               ap: int = 0, source: str = "") -> tuple[int, list[str]]:
        """
        Apply damage. Returns (damage_actually_taken, notices).

        ORDER OF OPERATIONS
            1. Role passive mitigation (Enforcer's pain gate)
            2. Armour SP, reduced by the attack's AP
            3. Armour ablation -- armour degrades as it absorbs
            4. HP reduction
            5. Cyberware shock -- heavy hits jar implants loose
            6. Bleeding on a heavy hit
        """
        notices: list[str] = []
        dmg = amount

        if not bypass_armor:
            if self.passive() == "pain_gate":
                dmg = max(0, dmg - 3)
            sp = max(0, self.armor_sp() - ap)
            absorbed = min(sp, dmg)
            dmg = max(0, dmg - sp)
            if absorbed > 0:
                self._ablate_armor(absorbed)

        if dmg <= 0:
            return 0, ["Armour stopped it cold."]

        self.db.adjust_player("hp", -dmg, lo=0)

        # Heavy trauma jars cyberware and opens wounds.
        if dmg >= 10:
            notices += self.degrade_cyberware(self.dice.between(3, 9))
        if dmg >= 8 and not self.has_status("bleeding"):
            self.add_status("bleeding", turns=4, source=source)
            notices.append("You're bleeding.")

        return dmg, notices

    def _ablate_armor(self, absorbed: int) -> None:
        """
        Armour loses condition proportional to what it soaked.

        Tuned at //8 so a vest degrades meaningfully over a long firefight
        without becoming worthless mid-encounter -- at //4 a plate carrier
        was stripped to zero SP inside a single extended fight, which turned
        every drawn-out engagement into a death spiral.
        """
        for it in self.items(equipped_only=True):
            if it["template"] in content.ARMOR:
                loss = max(1, absorbed // 8)
                new = max(0, it["condition"] - loss)
                self.db.run("UPDATE items SET condition=? WHERE id=?", (new, it["id"]))
                break

    def heal(self, amount: int) -> int:
        if self.passive() == "triage":
            amount = int(amount * 1.5)
        return self.db.adjust_player("hp", amount, lo=0, hi=self.row["hp_max"])

    def is_dead(self) -> bool:
        return self.row["hp"] <= 0 or self.row["coherence"] <= 0

    # ----------------------------------------------------------------------
    # INVENTORY
    # ----------------------------------------------------------------------
    def items(self, equipped_only: bool = False,
              category: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM items WHERE owner_type='player' AND owner_id=1"
        params: list = []
        if equipped_only:
            sql += " AND equipped=1"
        if category:
            sql += " AND category=?"
            params.append(category)
        return self.db.q(sql + " ORDER BY category, name", params)

    def give_item(self, template_key: str, qty: int = 1,
                  condition: int = 100) -> int | None:
        tmpl = content.ITEMS.get(template_key)
        if not tmpl:
            return None
        # Stack consumables and ammo rather than creating duplicate rows.
        if tmpl.get("cat") in ("consumable", "ammo"):
            existing = self.db.one(
                "SELECT * FROM items WHERE owner_type='player' AND owner_id=1 "
                "AND template=?", (template_key,),
            )
            if existing:
                self.db.run(
                    "UPDATE items SET qty=qty+? WHERE id=?", (qty, existing["id"])
                )
                return existing["id"]
        cur = self.db.run(
            "INSERT INTO items(template,name,category,owner_type,owner_id,"
            "qty,condition,loaded) VALUES(?,?,?,'player',1,?,?,?)",
            (template_key, tmpl["name"], tmpl.get("cat", "misc"), qty,
             condition, tmpl.get("mag") or 0),
        )
        return cur.lastrowid

    def give_ammo(self, ammo_type: str, qty: int) -> None:
        key = f"ammo_{ammo_type}"
        spec = content.AMMO_TYPES[ammo_type]
        existing = self.db.one(
            "SELECT * FROM items WHERE owner_type='player' AND owner_id=1 "
            "AND template=?", (key,),
        )
        if existing:
            self.db.run("UPDATE items SET qty=qty+? WHERE id=?", (qty, existing["id"]))
        else:
            self.db.run(
                "INSERT INTO items(template,name,category,owner_type,owner_id,qty)"
                " VALUES(?,?,'ammo','player',1,?)",
                (key, spec["name"], qty),
            )

    def ammo_count(self, ammo_type: str) -> int:
        row = self.db.one(
            "SELECT qty FROM items WHERE owner_type='player' AND owner_id=1 "
            "AND template=?", (f"ammo_{ammo_type}",),
        )
        return int(row["qty"]) if row else 0

    def consume_ammo(self, ammo_type: str, qty: int = 1) -> bool:
        have = self.ammo_count(ammo_type)
        if have < qty:
            return False
        self.db.run(
            "UPDATE items SET qty=qty-? WHERE owner_type='player' AND owner_id=1 "
            "AND template=?", (qty, f"ammo_{ammo_type}"),
        )
        self.db.run("DELETE FROM items WHERE qty<=0 AND category='ammo'")
        return True

    def drop_item(self, item_id: int, qty: int = 1) -> bool:
        row = self.db.one("SELECT * FROM items WHERE id=?", (item_id,))
        if not row:
            return False
        if row["qty"] > qty:
            self.db.run("UPDATE items SET qty=qty-? WHERE id=?", (qty, item_id))
        else:
            self.db.run("DELETE FROM items WHERE id=?", (item_id,))
        return True

    def equip(self, item_id: int) -> tuple[bool, str]:
        row = self.db.one("SELECT * FROM items WHERE id=?", (item_id,))
        if not row:
            return False, "You don't have that."
        cat = row["category"]
        if cat not in ("weapon", "armor", "deck"):
            return False, f"{row['name']} isn't something you equip."
        # One equipped item per category.
        self.db.run(
            "UPDATE items SET equipped=0 WHERE owner_type='player' "
            "AND owner_id=1 AND category=?", (cat,),
        )
        self.db.run("UPDATE items SET equipped=1 WHERE id=?", (item_id,))
        return True, f"Equipped {row['name']}."

    def equipped_weapon(self) -> sqlite3.Row | None:
        return self.db.one(
            "SELECT * FROM items WHERE owner_type='player' AND owner_id=1 "
            "AND category='weapon' AND equipped=1"
        )

    def equipped_deck(self) -> sqlite3.Row | None:
        return self.db.one(
            "SELECT * FROM items WHERE owner_type='player' AND owner_id=1 "
            "AND category='deck' AND equipped=1"
        )

    def programs(self) -> list[sqlite3.Row]:
        return self.items(category="program")

    def credits(self, delta: int = 0) -> int:
        if delta:
            return self.db.adjust_player("credits", delta, lo=0)
        return self.row["credits"]

    # ----------------------------------------------------------------------
    # PROGRESSION
    # ----------------------------------------------------------------------
    def award_xp(self, amount: int) -> list[str]:
        """
        XP thresholds scale quadratically. Levelling raises HP and grants
        skill points the player spends at a terminal.
        """
        msgs = []
        self.db.adjust_player("xp", amount)
        row = self.row
        needed = row["level"] * row["level"] * 100
        if row["xp"] >= needed:
            self.db.adjust_player("level", 1)
            self.db.adjust_player("xp", -needed)
            new_max = self.max_hp()
            self.db.update_player(hp_max=new_max)
            self.db.adjust_player("hp", 8, hi=new_max)
            self.db.bump_flag("skill_points", 3)
            msgs.append(
                f"LEVEL UP -- now level {row['level'] + 1}. "
                f"+3 skill points (spend with 'train')."
            )
            self.db.log(msgs[-1], "progress")
        return msgs

    def spend_skill_point(self, skill_name: str) -> tuple[bool, str]:
        pts = int(self.db.flag("skill_points", 0))
        if pts <= 0:
            return False, "No skill points available."
        if skill_name not in content.SKILLS:
            return False, f"No such skill: {skill_name}"
        current = self.skill(skill_name)
        if current >= 10:
            return False, f"{skill_name} is already maxed."
        self.db.run(
            "INSERT INTO skills(skill,rank) VALUES(?,1) "
            "ON CONFLICT(skill) DO UPDATE SET rank=rank+1", (skill_name,),
        )
        self.db.bump_flag("skill_points", -1)
        return True, f"{skill_name} raised to {current + 1}. {pts - 1} points left."


# ==========================================================================
# REPUTATION
# ==========================================================================
def rep_tier(value: int) -> str:
    label = "hostile"
    for threshold, name in content.REP_TIERS:
        if value >= threshold:
            label = name
    return label


def get_rep(db: Database, faction_id: str) -> int:
    row = db.one("SELECT value FROM reputation WHERE faction_id=?", (faction_id,))
    return int(row["value"]) if row else 0


def all_rep(db: Database) -> dict[str, int]:
    return {
        r["faction_id"]: r["value"]
        for r in db.q("SELECT faction_id, value FROM reputation")
    }


def adjust_rep(db: Database, faction_id: str, delta: int,
               cascade: bool = True, leverage: bool = False) -> dict[str, int]:
    """
    Change standing with a faction, cascading friction to rivals.

    THE FRICTION MODEL
        content.FACTIONS[f]['friction'] maps rival -> coefficient in [-1, 0].
        A gain of +10 with a faction whose friction with Halcyon is -0.8
        applies -8 to Halcyon. Losses cascade at HALF rate -- the city is
        quicker to notice you helping an enemy than to forgive you hurting one.

    This is what makes the political layer a real choice rather than a set of
    independent progress bars: you cannot max every faction, and the ending
    you can reach is gated on where you ended up.

    Returns a dict of every faction changed and its new value.
    """
    if faction_id not in content.FACTIONS:
        return {}

    if leverage and delta > 0:
        delta += 1  # Fixer passive

    changed: dict[str, int] = {}

    def _apply(fid: str, amount: int) -> None:
        current = get_rep(db, fid)
        new = max(-100, min(100, current + amount))
        db.run(
            "INSERT INTO reputation(faction_id,value,changes,last_turn) "
            "VALUES(?,?,1,?) ON CONFLICT(faction_id) DO UPDATE SET "
            "value=?, changes=changes+1, last_turn=?",
            (fid, new, db.turn, new, db.turn),
        )
        if new != current:
            changed[fid] = new

    _apply(faction_id, delta)

    if cascade:
        friction = content.FACTIONS[faction_id].get("friction", {})
        for rival, coeff in friction.items():
            rate = coeff if delta > 0 else coeff * 0.5
            spill = int(round(delta * rate))
            if spill:
                _apply(rival, spill)

    return changed


def rep_report(db: Database) -> list[tuple[str, int, str]]:
    out = []
    for fid, spec in content.FACTIONS.items():
        val = get_rep(db, fid)
        out.append((spec["name"], val, rep_tier(val)))
    return sorted(out, key=lambda r: -r[1])


# ==========================================================================
# HEAT -- local attention
# ==========================================================================
def adjust_heat(db: Database, district_id: str, delta: int) -> int:
    """
    Heat is per-district attention. High heat raises encounter frequency and
    the odds that the encounter is a CRA response. It decays on its own each
    turn you spend elsewhere -- see game.tick_world().
    """
    row = db.one("SELECT heat FROM districts WHERE id=?", (district_id,))
    if not row:
        return 0
    new = max(0, min(100, row["heat"] + delta))
    db.run("UPDATE districts SET heat=? WHERE id=?", (new, district_id))
    return new


def get_heat(db: Database, district_id: str) -> int:
    row = db.one("SELECT heat FROM districts WHERE id=?", (district_id,))
    return int(row["heat"]) if row else 0
