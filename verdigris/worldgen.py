"""
worldgen.py -- Procedural generation engine.

GENERATION PHILOSOPHY
    Generators are *composers*, not randomisers. A location is built by
    layering: district context -> structural kind -> descriptor -> feature ->
    occupant -> security rating -> loot tier. Each layer reads the layers
    above it, so results are coherent: a Terraces server farm gets corporate
    security and tier-4 loot; a Drowned Quarter flooded lobby gets scavvers,
    tidal hazards and tier-1 scrap.

    Every generator takes a Dice instance. Pass a seeded child (dice.spawn)
    to make generation reproducible for a given location id.

PROBABILITY MODEL
    All tables are {option: weight} dicts consumed by Dice.weighted().
    Weights are modified at runtime by context -- district security, player
    heat, reputation standing -- rather than being static. The modifier
    functions are the interesting part; the base tables live in content.py.
"""

from __future__ import annotations

import sqlite3

from . import content
from .db import Database, jdump, jload
from .dice import Dice


# ==========================================================================
# WORLD SEEDING -- run once at new game
# ==========================================================================
def seed_world(db: Database, dice: Dice) -> None:
    """Populate the static registries: factions, districts, and starting NPCs."""
    for fid, spec in content.FACTIONS.items():
        db.run(
            "INSERT OR REPLACE INTO factions(id,name,short,type,blurb) "
            "VALUES(?,?,?,?,?)",
            (fid, spec["name"], spec["short"], spec["type"], spec["blurb"]),
        )
        db.run(
            "INSERT OR IGNORE INTO reputation(faction_id,value) VALUES(?,0)",
            (fid,),
        )

    for did, spec in content.DISTRICTS.items():
        db.run(
            "INSERT OR REPLACE INTO districts"
            "(id,name,blurb,security,wealth,flooding,control,heat,tags,visited) "
            "VALUES(?,?,?,?,?,?,?,0,?,0)",
            (did, spec["name"], spec["blurb"], spec["security"], spec["wealth"],
             spec["flooding"], spec["control"], jdump(spec["tags"])),
        )

    # A handful of persistent, named NPCs per district so the world has
    # anchors the quest system can reference by id.
    for did in content.DISTRICTS:
        for _ in range(dice.between(2, 4)):
            generate_npc(db, dice, did, persistent=True)


# ==========================================================================
# NPC GENERATION
# ==========================================================================
def generate_npc(db: Database, dice: Dice, district_id: str,
                 faction_id: str | None = None, persistent: bool = False,
                 threat: int | None = None) -> int:
    """
    Generate a person.

    Faction affiliation defaults to weighted-by-district-control: the
    controlling faction is three times as likely as any other, which makes
    territory legible without being absolute.
    """
    dist = content.DISTRICTS[district_id]

    if faction_id is None:
        weights = {f: 1.0 for f in content.FACTIONS}
        weights[dist["control"]] = 3.0
        weights["unaffiliated"] = 2.0
        pick = dice.weighted(weights)
        faction_id = None if pick == "unaffiliated" else pick

    name = f"{dice.pick(content.FIRST_NAMES)} {dice.pick(content.LAST_NAMES)}"
    handle = dice.pick(content.STREET_NAMES) if dice.chance(0.55) else None
    role = dice.pick(content.NPC_ROLES)

    if threat is None:
        # Threat tracks district security with variance.
        threat = max(1, min(6, dist["security"] // 2 + dice.between(-1, 2)))

    # Threat 1-6 maps to roughly 15-45 HP. Kept shallow so low-damage
    # roles (Fixer, Medic) can still finish a fight they commit to.
    hp = 12 + threat * 5 + dice.between(0, 6)

    # Starting disposition is nudged by the player's standing with the NPC's
    # faction, so reputation is felt immediately on first contact.
    trust = 0
    if faction_id:
        rep_row = db.one("SELECT value FROM reputation WHERE faction_id=?", (faction_id,))
        if rep_row:
            trust = int(rep_row["value"] * 0.4) + dice.between(-10, 10)

    cur = db.run(
        "INSERT INTO npcs(name,handle,role,faction_id,district_id,alive,met,"
        "trust,fear,debt,hp,threat,props) VALUES(?,?,?,?,?,1,0,?,0,0,?,?,?)",
        (name, handle, role, faction_id, district_id,
         max(-100, min(100, trust)), hp, threat,
         jdump({"persistent": persistent})),
    )
    return cur.lastrowid


def npc_display(npc: sqlite3.Row) -> str:
    if npc["handle"]:
        return f"{npc['name']} \"{npc['handle']}\""
    return npc["name"]


def adjust_npc(db: Database, npc_id: int, trust: int = 0,
               fear: int = 0, debt: int = 0) -> None:
    """Move one person's relationship axes, clamped to [-100, 100]."""
    row = db.one("SELECT * FROM npcs WHERE id=?", (npc_id,))
    if not row:
        return
    clamp = lambda v: max(-100, min(100, v))
    db.run(
        "UPDATE npcs SET trust=?, fear=?, debt=? WHERE id=?",
        (clamp(row["trust"] + trust), clamp(row["fear"] + fear),
         clamp(row["debt"] + debt), npc_id),
    )


# ==========================================================================
# LOCATION GENERATION
# ==========================================================================
def generate_location(db: Database, dice: Dice, district_id: str,
                      persistent: bool = False) -> int:
    """
    Compose a location from the district's structural vocabulary.

    SECURITY DERIVATION
        base district security, +2 if the structural kind is inherently
        guarded (server farm, bonded warehouse, laboratory), -2 if abandoned
        or flooded, +1 per 25 points of district heat.

    LOOT TIER DERIVATION
        tier = clamp(1..5) of round((wealth + security) / 4) with a d10 swing
        on the top end -- so a poor district *can* hide something good, which
        is what keeps the Drowned Quarter worth searching.
    """
    dist = content.DISTRICTS[district_id]
    loc_seed = dice.between(1, 2**31 - 1)
    ld = Dice(loc_seed)  # local deterministic stream for this location

    kind = ld.weighted(content.LOCATION_KINDS[district_id])
    descriptor = ld.pick(content.DESCRIPTORS)
    feature = ld.pick(content.FEATURES)

    # Occupancy weights shift with district heat -- a hot district has more
    # patrols and fewer empty rooms.
    heat_row = db.one("SELECT heat FROM districts WHERE id=?", (district_id,))
    heat = heat_row["heat"] if heat_row else 0
    occ_weights = dict(content.OCCUPANTS)
    occ_weights["empty"] = max(1.0, occ_weights["empty"] - heat / 20)
    occ_weights["cra_patrol"] += heat / 15
    occ_weights["corp_security"] += heat / 25
    occupant = ld.weighted(occ_weights)

    security = dist["security"]
    if kind in ("server_farm", "laboratory", "bonded_warehouse",
                "customs_shed", "pump_station", "chem_store"):
        security += 2
    if descriptor in ("abandoned mid-shift", "condemned", "rusted through",
                      "flooded", "waterlogged"):
        security -= 2
    security += heat // 25
    security = max(0, min(10, security))

    tier = round((dist["wealth"] + security) / 4)
    if ld.chance(0.10):
        tier += 1  # the jackpot roll
    if ld.chance(0.15):
        tier -= 1
    tier = max(1, min(5, tier))

    name = _location_name(ld, kind, district_id)

    cur = db.run(
        "INSERT INTO locations(district_id,name,kind,descriptor,feature,"
        "occupant,security,loot_tier,seed,discovered,persistent,props) "
        "VALUES(?,?,?,?,?,?,?,?,?,1,?,?)",
        (district_id, name, kind, descriptor, feature, occupant,
         security, tier, loc_seed, 1 if persistent else 0, jdump({})),
    )
    loc_id = cur.lastrowid

    # Populate with loot and, if occupied, hostiles.
    populate_loot(db, ld, loc_id, tier)
    if occupant in ("gang_crew", "corp_security", "cra_patrol",
                    "ossuary_cell", "scavvers", "drones"):
        count = ld.between(1, 3)
        faction = {
            "gang_crew": "ironvein", "corp_security": "halcyon",
            "cra_patrol": "authority", "ossuary_cell": "ossuary",
            "scavvers": "lowline", "drones": "halcyon",
        }[occupant]
        for _ in range(count):
            npc_id = generate_npc(db, ld, district_id, faction_id=faction)
            db.run("UPDATE npcs SET location_id=? WHERE id=?", (loc_id, npc_id))

    return loc_id


_NAME_PARTS = {
    "prefix": ["Old", "Lower", "New", "East", "West", "Upper", "Back",
               "Saint", "Second", "North"],
    "noun": ["Ferry", "Harrow", "Cordite", "Marrow", "Pilgrim", "Tallow",
             "Vessel", "Quay", "Fathom", "Cinder", "Argent", "Bellow",
             "Crossing", "Salvage", "Halyard", "Kestrel"],
}

_KIND_LABELS = {
    "atrium": "Atrium", "office_floor": "Offices", "clinic": "Clinic",
    "server_farm": "Server Farm", "residence": "Residences",
    "transit_hub": "Transit Hub", "laboratory": "Lab",
    "bar": "Bar", "ripperdoc": "Clinic", "fight_pit": "Pit",
    "noodle_stall": "Stall", "pawn_shop": "Pawn", "flophouse": "Flophouse",
    "arcade": "Arcade", "foundry": "Foundry", "fab_shop": "Fab Shop",
    "warehouse": "Warehouse", "boiler_room": "Boiler Room",
    "chem_store": "Chem Store", "loading_dock": "Loading Dock",
    "container_stack": "Stacks", "bonded_warehouse": "Bonded Store",
    "crane_gantry": "Crane", "customs_shed": "Customs Shed",
    "wet_dock": "Wet Dock", "barge": "Barge",
    "flooded_lobby": "Lobby", "rooftop_camp": "Rooftop Camp",
    "submerged_vault": "Vault", "pump_station": "Pump Station",
    "tidal_farm": "Tidal Farm", "collapsed_span": "Collapsed Span",
    "squat_block": "Squats", "antenna_base": "Antenna Base",
    "scrap_yard": "Scrapyard", "chapel": "Chapel",
    "signal_shack": "Signal Shack", "buried_bunker": "Bunker",
}


def _location_name(dice: Dice, kind: str, district_id: str) -> str:
    label = _KIND_LABELS.get(kind, kind.replace("_", " ").title())
    if dice.chance(0.45):
        return f"{dice.pick(_NAME_PARTS['prefix'])} {dice.pick(_NAME_PARTS['noun'])} {label}"
    if dice.chance(0.5):
        return f"{dice.pick(_NAME_PARTS['noun'])} {label}"
    return f"{label} {dice.between(2, 88)}"


def location_description(loc: sqlite3.Row) -> str:
    occ = {
        "empty": "Nobody here. Not recently, either.",
        "squatters": "A dozen people living here who would rather you left.",
        "gang_crew": "Ironvein crew, and they have seen you.",
        "corp_security": "Halcyon contractors, in matched armour.",
        "cra_patrol": "A CRA patrol working the room.",
        "scavvers": "Lowline salvagers, already halfway through stripping it.",
        "ossuary_cell": "An Ossuary cell, mid-ceremony. Or mid-surgery.",
        "drones": "Two security drones, quartering the space.",
        "lone_fixer": "One person at the back, waiting for somebody. Maybe you.",
        "wounded_stranger": "Someone bleeding out against the far wall.",
    }.get(loc["occupant"], "")
    return (
        f"{loc['name']} -- {loc['descriptor']}. There's {loc['feature']}.\n"
        f"{occ}"
    ).strip()


# ==========================================================================
# LOOT GENERATION
# ==========================================================================
def populate_loot(db: Database, dice: Dice, location_id: int, tier: int) -> None:
    """
    Fill a location with items drawn from its loot tier.

    Count is 0-4, weighted downward, so most rooms are disappointing and the
    occasional one is not. Tier 5 always yields at least one item.
    """
    count_table = {0: 3.0, 1: 5.0, 2: 3.0, 3: 1.5, 4: 0.5}
    if tier >= 4:
        count_table[0] = 0.5
    count = dice.weighted(count_table)
    if tier == 5:
        count = max(1, count)

    table = content.LOOT_TIERS[tier]
    for key in dice.weighted_many(table, count):
        _place_loot_item(db, dice, location_id, key)


def _place_loot_item(db: Database, dice: Dice, location_id: int, key: str) -> None:
    """Resolve a loot key -- which may be an alias -- into a concrete row."""
    if key in content.LOOT_ALIASES:
        kind, arg, base = content.LOOT_ALIASES[key]
        if kind == "credits":
            amount = int(base * dice.rng.uniform(0.5, 1.6))
            db.run(
                "INSERT INTO items(template,name,category,owner_type,owner_id,"
                "qty,props) VALUES('credits','Credits','credits','location',?,?,?)",
                (location_id, amount, jdump({})),
            )
        elif kind == "ammo":
            qty = int(base * dice.rng.uniform(0.4, 1.2))
            db.run(
                "INSERT INTO items(template,name,category,owner_type,owner_id,qty)"
                " VALUES(?,?,'ammo','location',?,?)",
                (f"ammo_{arg}", content.AMMO_TYPES[arg]["name"], location_id, qty),
            )
        elif kind == "junk":
            db.run(
                "INSERT INTO items(template,name,category,owner_type,owner_id,"
                "qty,props) VALUES('scrap',?,'junk','location',?,?,?)",
                (arg, location_id, dice.between(1, 4), jdump({"value": base})),
            )
        return

    if key in content.CYBERWARE:
        tmpl = content.CYBERWARE[key]
        db.run(
            "INSERT INTO items(template,name,category,owner_type,owner_id,"
            "qty,condition,props) VALUES(?,?,'cyberware','location',?,1,?,?)",
            (key, tmpl["name"], location_id, dice.between(55, 100),
             jdump({"strain": tmpl["strain"]})),
        )
        return

    tmpl = content.ITEMS.get(key)
    if not tmpl:
        return
    condition = dice.between(45, 100)
    db.run(
        "INSERT INTO items(template,name,category,owner_type,owner_id,qty,"
        "condition,loaded) VALUES(?,?,?,'location',?,1,?,?)",
        (key, tmpl["name"], tmpl.get("cat", "misc"), location_id,
         condition, tmpl.get("mag") or 0),
    )


def location_loot(db: Database, location_id: int) -> list[sqlite3.Row]:
    return db.q(
        "SELECT * FROM items WHERE owner_type='location' AND owner_id=?",
        (location_id,),
    )


# ==========================================================================
# ENCOUNTER GENERATION
# ==========================================================================
def encounter_table(db: Database, district_id: str) -> dict[str, float]:
    """
    Build a context-weighted encounter table.

    MODIFIERS APPLIED
        * district heat        -> CRA and corporate responses climb steeply
        * player reputation    -> hostile factions seek you out; allied
                                  factions offer contact encounters instead
        * district flooding    -> tidal hazards become possible at all
        * district control     -> the controlling faction appears more often

    This is the function that makes the world feel like it is reacting to the
    player rather than rolling on a static chart.
    """
    dist = content.DISTRICTS[district_id]
    heat = db.one("SELECT heat FROM districts WHERE id=?", (district_id,))["heat"]
    reps = {
        r["faction_id"]: r["value"]
        for r in db.q("SELECT faction_id, value FROM reputation")
    }

    weights: dict[str, float] = {}
    for key, spec in content.ENCOUNTER_TEMPLATES.items():
        w = 1.0
        fac = spec.get("faction")

        # Controlling faction is more present on its own turf.
        if fac and fac == dist["control"]:
            w *= 2.0

        # Standing skews which faction finds you, and how.
        if fac:
            rep = reps.get(fac, 0)
            if rep <= -30:
                # They're hunting you.
                w *= 2.2 if spec["type"] in ("combat", "social_combat") else 0.4
            elif rep >= 45:
                # They're friendly -- more contacts, fewer confrontations.
                w *= 0.3 if spec["type"] in ("combat", "social_combat") else 1.8

        # Heat drives state response specifically.
        if fac == "authority":
            w *= 1.0 + heat / 30
        if key == "drone_sweep":
            w *= 1.0 + heat / 45
        if key == "ambush":
            w *= 1.0 + heat / 50

        # Environment gates.
        if key == "tide_warning":
            w = w * dist["flooding"] if dist["flooding"] else 0.0
        if key == "cargo_spill" and "cargo" not in dist["tags"]:
            w *= 0.25
        if key == "dead_drop" and "surveilled" in dist["tags"]:
            w *= 0.4

        if w > 0:
            weights[key] = w

    weights["nothing"] = max(2.0, 9.0 - dist["security"] * 0.5 - heat / 12)
    return weights


def roll_encounter(db: Database, dice: Dice, district_id: str) -> dict | None:
    """Roll one encounter. Returns None for 'nothing happens'."""
    key = dice.weighted(encounter_table(db, district_id))
    if key == "nothing":
        return None
    spec = dict(content.ENCOUNTER_TEMPLATES[key])
    spec["key"] = key

    # Populate the cast for anything that can turn violent.
    if spec["type"] in ("combat", "social_combat"):
        count = max(1, min(4, spec["threat"] // 2 + dice.between(1, 2)))
        ids = []
        for _ in range(count):
            ids.append(generate_npc(
                db, dice, district_id,
                faction_id=spec.get("faction"),
                threat=max(1, spec["threat"]),
            ))
        spec["npc_ids"] = ids
    return spec


# ==========================================================================
# NET HOST GENERATION
# ==========================================================================
def generate_net_host(db: Database, dice: Dice, district_id: str,
                      tier: int | None = None) -> int:
    """
    Generate a network host: a stack of nodes, each possibly defended by ICE.

    Host tier drives node depth, ICE tier distribution and payload value.
    The layout is generated once and stored, so a host you retreat from is
    the same host when you come back -- including which nodes you cracked.
    """
    dist = content.DISTRICTS[district_id]
    if tier is None:
        tier = max(1, min(5, dist["security"] // 2 + dice.between(0, 1)))

    seed = dice.between(1, 2**31 - 1)
    hd = Dice(seed)
    depth = 2 + tier
    owner = dist["control"]

    prefixes = ["ARC", "NODE", "SUBNET", "RELAY", "VAULT", "INDEX", "GRID"]
    name = f"{hd.pick(prefixes)}-{hd.between(100, 999)} [{content.FACTIONS[owner]['short']}]"

    # Build the node stack. Deeper nodes get better ICE and better payload.
    nodes = []
    for i in range(depth):
        depth_frac = (i + 1) / depth
        ice_pool = {
            k: (1.0 if v["tier"] <= tier else 0.15)
            for k, v in content.ICE.items()
            if v["tier"] <= tier + 1
        }
        # Weight toward higher-tier ICE deeper in.
        for k, v in list(ice_pool.items()):
            ice_pool[k] = v * (1 + depth_frac * content.ICE[k]["tier"] * 0.6)

        has_ice = hd.chance(0.45 + depth_frac * 0.45)
        node = {
            "index": i,
            "label": hd.pick([
                "auth gateway", "file store", "process bus", "log archive",
                "payroll spool", "sensor feed", "credential vault",
                "mail relay", "R&D partition", "physical security control",
            ]),
            "ice": hd.weighted(ice_pool) if has_ice else None,
            "cracked": False,
            "payload": _net_payload(hd, tier, depth_frac),
        }
        nodes.append(node)

    cur = db.run(
        "INSERT INTO net_hosts(name,district_id,owner,tier,depth,seed,props) "
        "VALUES(?,?,?,?,?,?,?)",
        (name, district_id, owner, tier, depth, seed, jdump({"nodes": nodes})),
    )
    return cur.lastrowid


def _net_payload(dice: Dice, tier: int, depth_frac: float) -> dict:
    """What's actually in a node when you crack it."""
    kind = dice.weighted({
        "credits": 3.0,
        "data": 3.0,
        "program": 1.2 * tier * depth_frac,
        "intel": 1.5,
        "control": 0.8 * depth_frac,
        "nothing": 2.0 - depth_frac,
    })
    if kind == "credits":
        return {"kind": "credits", "amount": int(200 * tier * (0.5 + depth_frac * 1.5))}
    if kind == "program":
        return {"kind": "program", "key": dice.pick(list(content.PROGRAMS))}
    if kind == "data":
        return {"kind": "data", "value": int(150 * tier * (0.5 + depth_frac))}
    if kind == "intel":
        return {"kind": "intel"}
    if kind == "control":
        return {"kind": "control"}
    return {"kind": "nothing"}


def get_or_make_hosts(db: Database, dice: Dice, district_id: str) -> list[sqlite3.Row]:
    """Lazily ensure a district has network hosts to dive."""
    hosts = db.q("SELECT * FROM net_hosts WHERE district_id=?", (district_id,))
    if len(hosts) < 2:
        for _ in range(2 - len(hosts)):
            generate_net_host(db, dice, district_id)
        hosts = db.q("SELECT * FROM net_hosts WHERE district_id=?", (district_id,))
    return hosts


# ==========================================================================
# DISTRICT REFRESH
# ==========================================================================
def ensure_locations(db: Database, dice: Dice, district_id: str,
                     minimum: int = 4) -> list[sqlite3.Row]:
    """
    Guarantee a district has explorable sites.

    Non-persistent, fully-looted locations are recycled rather than
    accumulating forever -- the city churns.
    """
    db.run(
        "DELETE FROM locations WHERE district_id=? AND persistent=0 "
        "AND looted=1 AND cleared=1", (district_id,),
    )
    rows = db.q("SELECT * FROM locations WHERE district_id=?", (district_id,))
    while len(rows) < minimum:
        generate_location(db, dice, district_id)
        rows = db.q("SELECT * FROM locations WHERE district_id=?", (district_id,))
    return rows
