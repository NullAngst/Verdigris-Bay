"""
actions.py -- Player verbs that aren't combat or netrunning.

Each function here is a single world action: it mutates state, returns
player-facing text, and does NOT advance the turn (the main loop owns turn
advancement, so it can tick the world exactly once per player action).
"""

from __future__ import annotations

import sqlite3

from . import content, worldgen
from .db import Database, jdump, jload
from .dice import Dice
from .rules import Character, adjust_heat, adjust_rep, get_rep, rep_tier


# ==========================================================================
# CONSUMABLES
# ==========================================================================
def use_consumable(db: Database, dice: Dice, char: Character,
                   item_id: int, in_combat: bool = False) -> str:
    """Apply a consumable's effect and decrement the stack."""
    item = db.one(
        "SELECT * FROM items WHERE id=? AND owner_type='player' AND owner_id=1",
        (item_id,),
    )
    if not item:
        return "You don't have that."

    tmpl = content.ITEMS.get(item["template"])
    if not tmpl or tmpl.get("cat") not in ("consumable", "tool"):
        return f"{item['name']} isn't something you use like that."

    use = tmpl.get("use")
    power = tmpl.get("power", 0)
    msg = ""

    if use == "heal":
        if in_combat and char.passive() != "triage":
            return "No time to patch yourself up mid-fight."
        healed = char.heal(power)
        char.clear_status("bleeding")
        msg = f"Patched up. HP {healed}/{char.row['hp_max']}. Bleeding stopped."

    elif use == "stim":
        char.add_status("stimmed", turns=tmpl.get("turns", 4), magnitude=1, source="stim")
        msg = f"Stim hits. +{power} REF for {tmpl.get('turns', 4)} rounds."

    elif use == "trace_purge":
        new = db.adjust_player("trace", -power, lo=0)
        msg = f"Trace dumped to {new}."

    elif use == "emp":
        char.add_status("emp_locked", turns=3, source="emp")
        notices = char.degrade_cyberware(dice.between(8, 20))
        msg = "EMP detonates. Everything electronic within reach goes dark, "
        msg += "including yours.\n" + "\n".join(notices)

    elif use == "breathe":
        char.clear_status("drowning")
        msg = "Rebreather sealed. Ten minutes of air."

    elif use == "credits":
        char.credits(power)
        msg = f"Cashed the chip. +{power}cr."

    elif use == "repair":
        # Tools are not consumed -- handled by repair_menu.
        return "Use 'repair' to work on gear with this."

    else:
        return f"{item['name']} does nothing useful right now."

    char.drop_item(item_id, 1)
    return msg


def repair_with_toolkit(db: Database, dice: Dice, char: Character,
                        cyber_id: int) -> str:
    """
    Field repair. Requires a toolkit; Techies get a bonus and can't fail
    badly. The check's margin determines how much integrity comes back.
    """
    kit = db.one(
        "SELECT * FROM items WHERE owner_type='player' AND owner_id=1 "
        "AND template='toolkit_field'"
    )
    if not kit:
        return "You need a Field Toolkit."

    chk = char.check("electronics", difficulty="tricky",
                     toolkit=3, specialist=2 if char.passive() == "field_repair" else 0)
    if not chk.success:
        # Degrade the toolkit on failure rather than the implant -- failing a
        # repair should cost resources, not punish with a death spiral.
        db.run("UPDATE items SET condition=MAX(0,condition-15) WHERE id=?", (kit["id"],))
        if kit["condition"] <= 15:
            db.run("DELETE FROM items WHERE id=?", (kit["id"],))
            return "The repair fails and the toolkit is finished."
        return f"Repair fails. Toolkit worn down. ({chk.describe()})"

    amount = 20 + chk.margin * 2
    msg = char.repair_cyberware(cyber_id, amount)
    db.run("UPDATE items SET condition=MAX(0,condition-5) WHERE id=?", (kit["id"],))
    return msg


# ==========================================================================
# MOVEMENT AND EXPLORATION
# ==========================================================================
def travel(db: Database, dice: Dice, char: Character, district_id: str) -> list[str]:
    """
    Move between districts.

    Travelling through a hostile district can be intercepted -- CRA
    checkpoints scale with your heat and your standing with the Authority.
    """
    if district_id not in content.DISTRICTS:
        return ["No such district."]
    if district_id == char.row["district"]:
        return ["You're already there."]

    out = []
    dist = content.DISTRICTS[district_id]

    # Checkpoint risk on entry.
    heat = db.one("SELECT heat FROM districts WHERE id=?", (district_id,))["heat"]
    auth_rep = get_rep(db, "authority")
    risk = (dist["security"] * 0.03) + (heat / 300) - (auth_rep / 500)
    if dice.chance(max(0.0, risk)):
        chk = char.check("deceive", difficulty=12 + dist["security"])
        if chk.success:
            out.append("Checkpoint on the ramp. You talk your way through it.")
        else:
            fine = min(char.credits(), 200 + dist["security"] * 60)
            char.credits(-fine)
            adjust_heat(db, district_id, 5)
            out.append(f"Checkpoint on the ramp. Scanned, searched, "
                       f"fined {fine}cr, waved on.")

    db.update_player(district=district_id, location_id=None)
    db.run("UPDATE districts SET visited=1 WHERE id=?", (district_id,))
    worldgen.ensure_locations(db, dice, district_id)

    out.append(f"\n=== {dist['name']} ===\n{dist['blurb']}")
    if dist["flooding"] >= 2 and not char.has_status("drowning"):
        out.append("The water is up to your knees within a block.")
    return out


def search_location(db: Database, dice: Dice, char: Character,
                    location_id: int) -> list[str]:
    """
    Search a location for loot. Search quality is an investigate check;
    the Scavver passive adds extra draws.
    """
    loc = db.one("SELECT * FROM locations WHERE id=?", (location_id,))
    if not loc:
        return ["Nothing there."]

    out = []
    loot = worldgen.location_loot(db, location_id)

    chk = char.check("investigate", difficulty=10 + loc["security"])
    if not chk.success and not loot:
        db.run("UPDATE locations SET looted=1 WHERE id=?", (location_id,))
        return ["You turn the place over and find nothing worth carrying."]

    # A critical search regenerates one extra item -- the hidden cache.
    if chk.critical:
        worldgen._place_loot_item(
            db, dice, location_id,
            dice.weighted(content.LOOT_TIERS[min(5, loc["loot_tier"] + 1)]),
        )
        out.append("You find a cache somebody thought was well hidden.")
        loot = worldgen.location_loot(db, location_id)

    if char.passive() == "scrounger" and dice.chance(0.5):
        worldgen._place_loot_item(
            db, dice, location_id,
            dice.weighted(content.LOOT_TIERS[loc["loot_tier"]]),
        )
        loot = worldgen.location_loot(db, location_id)

    if not loot:
        db.run("UPDATE locations SET looted=1 WHERE id=?", (location_id,))
        return ["Stripped. Somebody beat you here."]

    for item in loot:
        if item["category"] == "credits":
            char.credits(item["qty"])
            out.append(f"  {item['qty']}cr")
        elif item["category"] == "ammo":
            ammo_type = item["template"].replace("ammo_", "")
            char.give_ammo(ammo_type, item["qty"])
            out.append(f"  {item['name']} x{item['qty']}")
        elif item["category"] == "junk":
            value = jload(item["props"], {}).get("value", 20) * item["qty"]
            char.credits(value)
            out.append(f"  {item['name']} x{item['qty']} (sold for {value}cr)")
        elif item["category"] == "cyberware":
            # Loose cyberware goes into inventory; install at a clinic.
            db.run(
                "UPDATE items SET owner_type='player', owner_id=1 WHERE id=?",
                (item["id"],),
            )
            out.append(f"  {item['name']} (uninstalled, "
                       f"{item['condition']}% integrity)")
        else:
            db.run(
                "UPDATE items SET owner_type='player', owner_id=1 WHERE id=?",
                (item["id"],),
            )
            out.append(f"  {item['name']} ({item['condition']}%)")

    db.run("DELETE FROM items WHERE owner_type='location' AND owner_id=?",
           (location_id,))
    db.run("UPDATE locations SET looted=1 WHERE id=?", (location_id,))
    char.award_xp(10 + loc["loot_tier"] * 5)

    return ["You find:"] + out if out else ["Nothing."]


# ==========================================================================
# VENDORS
# ==========================================================================
def vendor_stock(db: Database, dice: Dice, district_id: str) -> list[tuple[str, int]]:
    """
    Generate a district's market inventory.

    Price is base value scaled by district wealth: poor districts sell
    cheaper but stock worse. Stock is regenerated per visit from a seed
    derived from the district and the current turn block, so it rotates
    every few turns rather than every single turn.
    """
    dist = content.DISTRICTS[district_id]
    block = db.turn // 5
    vd = Dice(hash((district_id, block)) & 0xFFFFFFFF)

    tier = max(1, min(5, round(dist["wealth"] / 2)))
    pool: dict[str, float] = {}
    for t in range(1, tier + 1):
        for key, weight in content.LOOT_TIERS[t].items():
            if key in content.ITEMS or key in content.CYBERWARE:
                pool[key] = pool.get(key, 0) + weight * (t / tier)

    picks = list(dict.fromkeys(vd.weighted_many(pool, 12)))[:8]
    multiplier = 0.75 + dist["wealth"] * 0.06

    stock = []
    for key in picks:
        base = (content.ITEMS.get(key) or content.CYBERWARE.get(key, {})).get("value", 100)
        stock.append((key, int(base * multiplier)))

    # Ammo is always available.
    for ammo_key, spec in content.AMMO_TYPES.items():
        stock.append((f"ammo_{ammo_key}", int(spec["value"] * spec["box"] * multiplier)))

    return stock


def buy(db: Database, dice: Dice, char: Character,
        key: str, price: int) -> str:
    if char.credits() < price:
        return f"You're short. Need {price}cr, have {char.credits()}cr."

    if key.startswith("ammo_"):
        ammo_type = key.replace("ammo_", "")
        qty = content.AMMO_TYPES[ammo_type]["box"]
        char.credits(-price)
        char.give_ammo(ammo_type, qty)
        return f"Bought {qty} x {content.AMMO_TYPES[ammo_type]['name']}."

    if key in content.CYBERWARE:
        char.credits(-price)
        db.run(
            "INSERT INTO items(template,name,category,owner_type,owner_id,qty,"
            "condition) VALUES(?,?,'cyberware','player',1,1,100)",
            (key, content.CYBERWARE[key]["name"]),
        )
        return (f"Bought {content.CYBERWARE[key]['name']}. "
                f"Take it to a clinic to have it installed.")

    if key not in content.ITEMS:
        return "Not for sale."
    char.credits(-price)
    char.give_item(key)
    return f"Bought {content.ITEMS[key]['name']} for {price}cr."


def sell(db: Database, dice: Dice, char: Character, item_id: int) -> str:
    """Sell at 40% of base, scaled by condition."""
    item = db.one(
        "SELECT * FROM items WHERE id=? AND owner_type='player' AND owner_id=1",
        (item_id,),
    )
    if not item:
        return "You don't have that."
    if item["equipped"]:
        return "Unequip it first."

    tmpl = content.ITEMS.get(item["template"]) or content.CYBERWARE.get(item["template"])
    base = tmpl.get("value", 50) if tmpl else 50
    price = int(base * 0.4 * (item["condition"] / 100)) * item["qty"]
    price = max(5, price)

    char.credits(price)
    char.drop_item(item_id, item["qty"])
    return f"Sold {item['name']} for {price}cr."


# ==========================================================================
# CLINIC -- cyberware installation and coherence work
# ==========================================================================
def clinic_install(db: Database, dice: Dice, char: Character,
                   item_id: int, back_alley: bool = False) -> str:
    """
    Install cyberware the player is carrying.

    back_alley costs a quarter as much but installs at reduced quality,
    which means more Coherence strain and an implant that starts degraded.
    Ossuary standing improves back-alley outcomes -- they are the best
    ripperdocs in the Bay and they charge in loyalty.
    """
    item = db.one(
        "SELECT * FROM items WHERE id=? AND owner_type='player' AND owner_id=1 "
        "AND category='cyberware'", (item_id,),
    )
    if not item:
        return "You're not carrying that implant."

    tmpl = content.CYBERWARE.get(item["template"])
    if not tmpl:
        return "Nobody knows how to install that."

    fee = int(tmpl["value"] * (0.15 if back_alley else 0.5))
    if char.credits() < fee:
        return f"The doc wants {fee}cr up front. You have {char.credits()}cr."

    quality = item["condition"]
    if back_alley:
        oss = get_rep(db, "ossuary")
        # Ossuary standing offsets the quality penalty, up to erasing it.
        penalty = max(0, 25 - oss // 4)
        quality = max(30, quality - penalty)

    char.credits(-fee)
    ok, msg = char.install_cyberware(item["template"], quality=quality)
    if ok:
        char.drop_item(item_id, 1)
        if back_alley:
            adjust_rep(db, "ossuary", 3)
    else:
        char.credits(fee)  # refund a refused surgery
    return msg


def clinic_heal(db: Database, dice: Dice, char: Character) -> str:
    missing = char.row["hp_max"] - char.row["hp"]
    if missing <= 0:
        return "Nothing wrong with you that a clinic can fix."
    fee = missing * 12
    if char.credits() < fee:
        return f"Full treatment is {fee}cr. You have {char.credits()}cr."
    char.credits(-fee)
    char.heal(missing)
    for eff in ("bleeding", "poisoned", "burning", "crash"):
        char.clear_status(eff)
    return f"Patched, flushed and discharged. {fee}cr. HP {char.row['hp']}/{char.row['hp_max']}."
