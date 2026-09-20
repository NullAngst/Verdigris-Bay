"""
content.py -- The setting: Verdigris Bay.

ORIGINALITY NOTE
----------------
Every faction, district, person, weapon, implant and program in this file is
original to this project. The genre conventions it works within (megacorps,
street gangs, implants that cost you something, a network you dive into) are
common property of the cyberpunk genre. No named content from any published
tabletop product appears here.

STRUCTURE
---------
Everything is plain data -- dicts and tuples -- so the procedural generator,
the database seeder and the quest engine can all consume it without importing
game logic. Add content here, not in the engines.
"""

from __future__ import annotations

# ==========================================================================
# THE CITY
# ==========================================================================
CITY = "Verdigris Bay"

CITY_PREMISE = """\
Verdigris Bay was built on reclaimed land and it has been trying to sink back
into the water ever since. Forty years ago the seawalls failed during a
storm surge and the city's founding families discovered it was cheaper to
build upward on the high ground than to pump out the low. So they did. The
Terraces went up, the Drowned Quarter went under, and nobody with the money
to leave has looked down since.

You live down here. The tide comes in twice a day through streets nobody
bothered to condemn.\
"""


# ==========================================================================
# ATTRIBUTES
# ==========================================================================
# Seven attributes, range 1-10 for humans. Used by every check in the game.
ATTRIBUTES = {
    "REF": "Reflex -- speed, coordination, trigger discipline",
    "BOD": "Body -- mass, stamina, how much you can absorb",
    "INT": "Intellect -- analysis, recall, planning",
    "NRV": "Nerve -- composure under pressure, resistance to fear and pain",
    "PRE": "Presence -- read people, be believed, be remembered",
    "TEC": "Tech -- build it, breach it, keep it running",
    "WIR": "Wire -- neural bandwidth; how well your brain talks to machines",
}

SKILLS = {
    # combat
    "firearms":     "REF",
    "melee":        "REF",
    "dodge":        "REF",
    "heavy_weapons": "BOD",
    # physical
    "athletics":    "BOD",
    "stealth":      "REF",
    "endurance":    "BOD",
    # mental / technical
    "electronics":  "TEC",
    "demolitions":  "TEC",
    "medicine":     "TEC",
    "security":     "TEC",
    "streetwise":   "INT",
    "investigate":  "INT",
    # social
    "persuade":     "PRE",
    "intimidate":   "PRE",
    "deceive":      "PRE",
    "composure":    "NRV",
    # net
    "intrusion":    "WIR",
    "evasion":      "WIR",
    "signal":       "WIR",
}


# ==========================================================================
# ROLES -- starting archetypes
# ==========================================================================
# Each role sets attribute priorities, starting skills, starting kit and a
# unique passive. Roles are deliberately overlapping; none is a hard class.
ROLES = {
    "Runner": {
        "blurb": "You go into the network and come back out with things that "
                 "weren't yours. Mostly you come back out.",
        "attrs": {"WIR": 8, "INT": 7, "TEC": 6, "REF": 5, "NRV": 5, "PRE": 4, "BOD": 4},
        "skills": {"intrusion": 4, "evasion": 3, "electronics": 3, "signal": 2,
                   "stealth": 2, "investigate": 2, "firearms": 1},
        "kit": ["service_pistol", "armor_liner_coat", "deck_lowgrade",
                "prog_hammer", "prog_veil", "stim_patch"],
        "cyber": ["neural_port"],
        "passive": "trace_shed",
        "passive_desc": "Trace decays 3 points faster per turn out of the net.",
    },
    "Enforcer": {
        "blurb": "Somebody has to stand in the doorway. You are expensive, "
                 "and you are worth it.",
        "attrs": {"BOD": 8, "REF": 7, "NRV": 7, "TEC": 4, "INT": 4, "PRE": 5, "WIR": 3},
        "skills": {"firearms": 4, "melee": 3, "dodge": 3, "endurance": 3,
                   "intimidate": 3, "heavy_weapons": 2, "composure": 2},
        "kit": ["service_pistol", "armor_plate_vest", "combat_knife", "trauma_kit"],
        "cyber": ["subdermal_weave"],
        "passive": "pain_gate",
        "passive_desc": "Ignore the first 3 damage from every incoming hit.",
    },
    "Fixer": {
        "blurb": "You don't do the job. You know who does, what they charge, "
                 "and what they owe.",
        "attrs": {"PRE": 8, "INT": 7, "NRV": 6, "REF": 5, "TEC": 4, "BOD": 4, "WIR": 5},
        "skills": {"persuade": 4, "streetwise": 4, "deceive": 3, "investigate": 3,
                   "composure": 2, "firearms": 2, "security": 1},
        "kit": ["service_pistol", "armor_liner_coat", "burner_deck", "cred_chip_small"],
        "cyber": ["voice_modulator"],
        "passive": "leverage",
        "passive_desc": "Start with a contact in every district and +1 to all "
                        "reputation gains.",
    },
    "Techie": {
        "blurb": "Everything in this city is held together with solder and "
                 "somebody's patience. Usually yours.",
        "attrs": {"TEC": 8, "INT": 7, "REF": 5, "WIR": 6, "BOD": 5, "NRV": 5, "PRE": 4},
        "skills": {"electronics": 4, "security": 4, "medicine": 3, "demolitions": 2,
                   "investigate": 2, "firearms": 2, "intrusion": 2},
        "kit": ["service_pistol", "toolkit_field", "armor_liner_coat", "emp_charge"],
        "cyber": ["optic_suite"],
        "passive": "field_repair",
        "passive_desc": "Can restore cyberware integrity and repair gear "
                        "without a clinic.",
    },
    "Medic": {
        "blurb": "Street doc. Half your patients can't go to a hospital and "
                 "the other half can't be seen going anywhere.",
        "attrs": {"TEC": 7, "INT": 7, "PRE": 6, "NRV": 6, "REF": 5, "BOD": 5, "WIR": 4},
        "skills": {"medicine": 5, "electronics": 3, "persuade": 3, "composure": 3,
                   "investigate": 2, "streetwise": 2, "firearms": 1},
        "kit": ["service_pistol", "trauma_kit", "trauma_kit", "armor_liner_coat",
                "stim_patch", "stim_patch"],
        "cyber": ["diagnostic_hand"],
        "passive": "triage",
        "passive_desc": "Healing items restore 50% more and can be used in combat.",
    },
    "Scavver": {
        "blurb": "The Drowned Quarter is full of things people left behind "
                 "when the water came. You have a boat.",
        "attrs": {"BOD": 6, "REF": 7, "INT": 6, "TEC": 6, "NRV": 6, "PRE": 4, "WIR": 4},
        "skills": {"athletics": 4, "stealth": 3, "investigate": 3, "streetwise": 3,
                   "electronics": 2, "melee": 2, "endurance": 3},
        "kit": ["scattergun", "armor_plate_vest", "toolkit_field", "rebreather"],
        "cyber": ["lung_filter"],
        "passive": "scrounger",
        "passive_desc": "+2 loot rolls per container and can salvage from "
                        "defeated enemies.",
    },
}


# ==========================================================================
# FACTIONS
# ==========================================================================
# reputation runs -100 (blood feud) to +100 (made). `friction` maps how
# gaining standing with this faction costs you standing elsewhere -- the
# core of the political system.
FACTIONS = {
    "halcyon": {
        "name": "Halcyon Vertex",
        "short": "Halcyon",
        "type": "corporate",
        "blurb": "Biotech and pharmaceutical combine. Owns the Terraces, the "
                 "water rights, and the coroner's office. Publishes a lovely "
                 "annual report.",
        "friction": {"lowline": -0.8, "ossuary": -0.5, "ironvein": -0.3},
        "tier_titles": ["Flagged", "Cleared", "Contracted", "Preferred Asset"],
    },
    "ossuary": {
        "name": "The Ossuary",
        "short": "Ossuary",
        "type": "cult",
        "blurb": "They believe the body is a draft, not a final copy. Best "
                 "chrome in the Bay, installed in a basement by someone who "
                 "considers it a sacrament.",
        "friction": {"halcyon": -0.6, "authority": -0.7},
        "tier_titles": ["Meat", "Initiate", "Revised", "Testament"],
    },
    "meridian": {
        "name": "Grey Meridian",
        "short": "Meridian",
        "type": "network",
        "blurb": "A netrunner collective that behaves like a library and "
                 "prices like a cartel. If it happened on the wire, they have "
                 "a copy.",
        "friction": {"authority": -0.6, "halcyon": -0.4},
        "tier_titles": ["Noise", "Reader", "Contributor", "Archivist"],
    },
    "ironvein": {
        "name": "Ironvein Syndicate",
        "short": "Ironvein",
        "type": "criminal",
        "blurb": "Guns, cargo, and the Gantry docks. Old money that never "
                 "bothered to launder itself because nobody ever made them.",
        "friction": {"authority": -0.9, "lowline": -0.3},
        "tier_titles": ["Outsider", "Known", "Associate", "Made"],
    },
    "authority": {
        "name": "Civic Reclamation Authority",
        "short": "the CRA",
        "type": "state",
        "blurb": "Municipal police, if municipal police had armored vehicles "
                 "and a mandate to 'reclaim' whichever districts are behind "
                 "on assessments.",
        "friction": {"ironvein": -0.9, "ossuary": -0.7, "meridian": -0.6, "lowline": -0.4},
        "tier_titles": ["Suspect", "Compliant", "Informant", "Deputised"],
    },
    "lowline": {
        "name": "The Lowline",
        "short": "the Lowline",
        "type": "community",
        "blurb": "Mutual aid, tidal farming and scavenging rights in the "
                 "flooded districts. Not a gang. Will absolutely act like one "
                 "if you touch their pumps.",
        "friction": {"halcyon": -0.9, "authority": -0.4},
        "tier_titles": ["Stranger", "Neighbour", "Kin", "Anchor"],
    },
}

REP_TIERS = [(-100, "hostile"), (-30, "wary"), (15, "neutral"), (45, "trusted"), (75, "inner")]


# ==========================================================================
# DIFFICULTY
# ==========================================================================
# Chosen at character creation, stored in meta, read at creation and by the
# world tick. Difficulty shapes three things: your starting stats, your
# starting loadout, and how often the city comes for you.
#
#   attr_mod      -- added to every starting attribute (clamped 1..10)
#   credits       -- starting money
#   extra_kit     -- items granted ON TOP of the role's kit
#   ammo_boxes    -- boxes of ammo per equipped firearm (each box = AMMO 'box')
#   encounter     -- ambient encounter chance per world turn
#   enemy_threat  -- flat modifier to generated ambush enemy threat
DIFFICULTIES = {
    "easy": {
        "name": "Easy",
        "blurb": "You came prepared. Better stats, a full kit, guns and meds "
                 "to spare, and the street mostly leaves you alone.",
        "attr_mod": 1,
        "credits": 2800,
        "extra_kit": ["service_pistol", "combat_knife", "armor_plate_vest",
                      "trauma_kit", "trauma_kit", "trauma_kit",
                      "stim_patch", "stim_patch"],
        "ammo_boxes": 3,
        "encounter": 0.12,
        "enemy_threat": -1,
    },
    "normal": {
        "name": "Normal",
        "blurb": "The intended experience. A working kit, a backup blade, "
                 "and a city that notices you now and then.",
        "attr_mod": 0,
        "credits": 1200,
        "extra_kit": ["combat_knife", "trauma_kit", "stim_patch"],
        "ammo_boxes": 2,
        "encounter": 0.18,
        "enemy_threat": 0,
    },
    "hard": {
        "name": "Hard",
        "blurb": "You start with next to nothing and the Bay wants you dead. "
                 "Lower stats, thin kit, little ammo, frequent trouble.",
        "attr_mod": -1,
        "credits": 500,
        "extra_kit": [],
        "ammo_boxes": 1,
        "encounter": 0.30,
        "enemy_threat": 1,
    },
    "brutal": {
        "name": "Brutal",
        "blurb": "A knife, a prayer, and a target on your back. For people "
                 "who have already beaten this game and resent it.",
        "attr_mod": -2,
        "credits": 200,
        "extra_kit": [],
        "ammo_boxes": 0,
        "encounter": 0.38,
        "enemy_threat": 2,
    },
}
DIFFICULTY_ORDER = ["easy", "normal", "hard", "brutal"]


# ==========================================================================
# DISTRICTS
# ==========================================================================
# security  1-10: how hard the local response is
# wealth    1-10: drives loot quality and price multipliers
# flooding  0-3 : Drowned Quarter mechanics; affects movement and hazards
DISTRICTS = {
    "terraces": {
        "name": "The Terraces",
        "blurb": "Stacked arcology decks on the high ground. Filtered air, "
                 "real trees, and a checkpoint on every ramp.",
        "security": 9, "wealth": 9, "flooding": 0,
        "control": "halcyon",
        "tags": ["corporate", "surveilled", "vertical", "clean"],
        "hazards": ["drone_patrol", "id_checkpoint", "gas_lock"],
    },
    "sable_row": {
        "name": "Sable Row",
        "blurb": "Nine blocks of bars, clinics, ring fights and vending. The "
                 "only place in the Bay where all six factions drink.",
        "security": 5, "wealth": 6, "flooding": 0,
        "control": "ironvein",
        "tags": ["nightlife", "neutral_ground", "crowded", "market"],
        "hazards": ["crowd_crush", "pickpocket", "bad_dose"],
    },
    "kiln": {
        "name": "The Kiln",
        "blurb": "Foundries and fab shops running three shifts. Everything is "
                 "hot, loud, and owned by somebody who isn't here.",
        "security": 6, "wealth": 5, "flooding": 0,
        "control": "halcyon",
        "tags": ["industrial", "loud", "machinery", "toxic"],
        "hazards": ["thermal_vent", "machine_press", "chem_spill"],
    },
    "gantry": {
        "name": "The Gantry",
        "blurb": "Container cranes, bonded warehouses and a customs office "
                 "that has never once opened a red-tagged crate.",
        "security": 7, "wealth": 7, "flooding": 1,
        "control": "ironvein",
        "tags": ["docks", "smuggling", "cargo", "open_sightlines"],
        "hazards": ["crane_swing", "dock_dogs", "customs_sweep"],
    },
    "drowned": {
        "name": "The Drowned Quarter",
        "blurb": "Twelve blocks the seawall gave up on. Second storeys are "
                 "ground floor now. Everything below the tideline belongs to "
                 "whoever can hold their breath longest.",
        "security": 2, "wealth": 3, "flooding": 3,
        "control": "lowline",
        "tags": ["flooded", "abandoned", "salvage", "lightless"],
        "hazards": ["rising_tide", "structural_collapse", "bad_water"],
    },
    "static_fields": {
        "name": "The Static Fields",
        "blurb": "The old broadcast array and the squats that grew up under "
                 "it. Nothing wireless works right. Some people like that.",
        "security": 3, "wealth": 2, "flooding": 1,
        "control": "ossuary",
        "tags": ["squats", "interference", "lawless", "antenna"],
        "hazards": ["signal_burn", "feral_dogs", "collapse_pit"],
    },
}


# ==========================================================================
# GEAR
# ==========================================================================
# WEAPONS
#   damage      -- (count, sides) dice
#   ap          -- armour penetration; subtracted from target armour
#   rof         -- attacks per combat round
#   mag         -- magazine capacity (None = melee)
#   hands       -- affects concealment and some checks
#   conceal     -- difficulty band others must beat to spot it on you
WEAPONS = {
    "holdout_pistol": {
        "name": "Wexler .22 Holdout", "cat": "weapon", "skill": "firearms",
        "damage": (2, 6), "ap": 0, "rof": 2, "mag": 6, "ammo": "light",
        "hands": 1, "conceal": "hard", "value": 180,
        "desc": "Fits in a sock. Feels like it, too.",
    },
    "service_pistol": {
        "name": "Corriveau M9 Service", "cat": "weapon", "skill": "firearms",
        "damage": (2, 6), "ap": 1, "rof": 2, "mag": 15, "ammo": "medium",
        "hands": 1, "conceal": "routine", "value": 520,
        "desc": "Every third cop and every second bodyguard in the Bay.",
    },
    "machine_pistol": {
        "name": "Sligo Chatterbox", "cat": "weapon", "skill": "firearms",
        "damage": (2, 6), "ap": 0, "rof": 4, "mag": 32, "ammo": "medium",
        "hands": 1, "conceal": "tricky", "value": 900,
        "desc": "Empties itself with enthusiasm. Accuracy is aspirational.",
    },
    "scattergun": {
        "name": "Tidewater Breachgun", "cat": "weapon", "skill": "firearms",
        "damage": (4, 6), "ap": 0, "rof": 1, "mag": 5, "ammo": "shell",
        "hands": 2, "conceal": "nightmare", "value": 740,
        "desc": "Salvage-rig standard. Opens doors and arguments.",
    },
    "carbine": {
        "name": "Halcyon Pattern-7 Carbine", "cat": "weapon", "skill": "firearms",
        "damage": (3, 6), "ap": 2, "rof": 3, "mag": 30, "ammo": "rifle",
        "hands": 2, "conceal": "nightmare", "value": 1600,
        "desc": "Corporate security issue. Serial numbers are a formality.",
    },
    "railpistol": {
        "name": "Ossuary Votive Rail", "cat": "weapon", "skill": "firearms",
        "damage": (3, 6), "ap": 5, "rof": 1, "mag": 4, "ammo": "slug",
        "hands": 1, "conceal": "tricky", "value": 3400,
        "desc": "Hand-wound coils, hand-etched scripture. Punches through "
                "plate like it's owed money.",
    },
    "combat_knife": {
        "name": "Gutter Knife", "cat": "weapon", "skill": "melee",
        "damage": (1, 6), "ap": 1, "rof": 2, "mag": None, "ammo": None,
        "hands": 1, "conceal": "hard", "value": 60, "bonus_dmg_attr": "BOD",
        "desc": "Quiet, legal to carry, never jams.",
    },
    "shock_baton": {
        "name": "CRA Compliance Baton", "cat": "weapon", "skill": "melee",
        "damage": (2, 6), "ap": 0, "rof": 2, "mag": 20, "ammo": "cell",
        "hands": 1, "conceal": "tricky", "value": 340, "on_hit": "stunned",
        "desc": "Issued with a pamphlet about de-escalation.",
    },
    "mono_cleaver": {
        "name": "Monofilament Cleaver", "cat": "weapon", "skill": "melee",
        "damage": (3, 6), "ap": 4, "rof": 1, "mag": None, "ammo": None,
        "hands": 2, "conceal": "nightmare", "value": 2200, "bonus_dmg_attr": "BOD",
        "desc": "The edge is one molecule wide. Do not test it on yourself.",
    },
}

ARMOR = {
    "armor_liner_coat": {
        "name": "Lined Longcoat", "cat": "armor", "sp": 4, "penalty": 0,
        "value": 300, "desc": "Looks like a coat. Is mostly a coat.",
    },
    "armor_plate_vest": {
        "name": "Plate Carrier Vest", "cat": "armor", "sp": 8, "penalty": -1,
        "value": 850, "desc": "Standard on any crew that expects trouble.",
    },
    "armor_riot": {
        "name": "CRA Riot Shell", "cat": "armor", "sp": 13, "penalty": -3,
        "value": 2600, "desc": "You will survive. You will not be quick.",
    },
    "armor_weave_suit": {
        "name": "Halcyon Executive Weave", "cat": "armor", "sp": 10, "penalty": 0,
        "value": 5200, "desc": "A very good suit that happens to stop rifle rounds.",
    },
}

CONSUMABLES = {
    "trauma_kit": {
        "name": "Trauma Kit", "cat": "consumable", "use": "heal",
        "power": 14, "value": 220, "desc": "Sealant, clamps, and a very "
        "optimistic set of instructions.",
    },
    "stim_patch": {
        "name": "Stim Patch", "cat": "consumable", "use": "stim",
        "power": 2, "turns": 4, "value": 160,
        "desc": "+2 REF for four rounds. Then you pay for it.",
    },
    "coolant_shunt": {
        "name": "Coolant Shunt", "cat": "consumable", "use": "trace_purge",
        "power": 25, "value": 380, "desc": "Dumps trace heat. Smells like "
        "burnt sugar and regret.",
    },
    "emp_charge": {
        "name": "EMP Charge", "cat": "consumable", "use": "emp",
        "power": 3, "value": 500, "desc": "Disables cyberware and drones in a "
        "small radius. Including yours.",
    },
    "rebreather": {
        "name": "Rebreather", "cat": "consumable", "use": "breathe",
        "power": 10, "value": 260, "desc": "Ten minutes of air. The Drowned "
        "Quarter sells these at every landing.",
    },
    "cred_chip_small": {
        "name": "Anonymous Cred Chip", "cat": "consumable", "use": "credits",
        "power": 500, "value": 500, "desc": "Untraceable. Mostly.",
    },
    "toolkit_field": {
        "name": "Field Toolkit", "cat": "tool", "use": "repair",
        "power": 20, "value": 400, "desc": "Reusable. Restores cyberware "
        "integrity and repairs gear.",
    },
}

AMMO_TYPES = {
    "light":  {"name": "Light Rounds",  "value": 1, "box": 30},
    "medium": {"name": "Medium Rounds", "value": 2, "box": 30},
    "rifle":  {"name": "Rifle Rounds",  "value": 3, "box": 30},
    "shell":  {"name": "Shells",        "value": 4, "box": 20},
    "slug":   {"name": "Rail Slugs",    "value": 12, "box": 10},
    "cell":   {"name": "Power Cells",   "value": 3, "box": 20},
}


# ==========================================================================
# CYBERWARE
# ==========================================================================
# strain    -- permanent Coherence cost on install (see rules.py)
# integrity -- 0-100, degrades with use and damage; low integrity misfires
# slot      -- one item per slot, except 'body' which allows three
CYBERWARE = {
    "neural_port": {
        "name": "Neural Interface Port", "slot": "head", "strain": 6,
        "value": 1800, "effects": {"WIR": 1}, "grants": ["netrun"],
        "desc": "A socket at the base of the skull. Required to dive.",
    },
    "optic_suite": {
        "name": "Optic Suite", "slot": "eyes", "strain": 5,
        "value": 2400, "effects": {"INT": 1}, "grants": ["lowlight", "zoom"],
        "desc": "Low-light, magnification, and an overlay you cannot turn off.",
    },
    "reflex_governor": {
        "name": "Reflex Governor", "slot": "spine", "strain": 14,
        "value": 9000, "effects": {"REF": 2}, "grants": ["extra_action"],
        "desc": "Rewires the spinal reflex arc. Everyone else slows down.",
    },
    "subdermal_weave": {
        "name": "Subdermal Weave", "slot": "body", "strain": 8,
        "value": 3200, "effects": {}, "grants": ["armor_2"],
        "desc": "Ballistic mesh under the skin. Itches in cold weather.",
    },
    "muscle_lace": {
        "name": "Muscle Lace", "slot": "body", "strain": 9,
        "value": 4100, "effects": {"BOD": 2}, "grants": [],
        "desc": "Contractile filament woven through major groups.",
    },
    "voice_modulator": {
        "name": "Voice Modulator", "slot": "throat", "strain": 4,
        "value": 1500, "effects": {"PRE": 1}, "grants": ["mimic"],
        "desc": "Pitch, timbre, accent. Recorded samples optional.",
    },
    "diagnostic_hand": {
        "name": "Diagnostic Hand", "slot": "arm", "strain": 5,
        "value": 2100, "effects": {"TEC": 1}, "grants": ["field_surgery"],
        "desc": "Fingertip sensors and a retractable suture driver.",
    },
    "lung_filter": {
        "name": "Filtration Lung", "slot": "body", "strain": 6,
        "value": 2700, "effects": {"BOD": 1}, "grants": ["gas_immune", "hold_breath"],
        "desc": "Scrubs particulates and most nerve agents. Most.",
    },
    "adrenal_pump": {
        "name": "Adrenal Pump", "slot": "gland", "strain": 11,
        "value": 5600, "effects": {"NRV": 2}, "grants": ["second_wind"],
        "desc": "Floods your system when your heart rate spikes. Cannot be "
                "triggered manually, which is the problem.",
    },
    "cortex_stack": {
        "name": "Cortex Stack", "slot": "head", "strain": 16,
        "value": 12000, "effects": {"INT": 2, "WIR": 1}, "grants": ["ice_read"],
        "desc": "Co-processor bonded to the parietal lobe. You will have "
                "thoughts that are not entirely yours.",
    },
}


# ==========================================================================
# NET -- programs and ICE
# ==========================================================================
DECKS = {
    "burner_deck": {
        "name": "Burner Deck", "cat": "deck", "buffer": 5, "shield": 1,
        "speed": 0, "value": 600, "desc": "Disposable. Barely a deck.",
    },
    "deck_lowgrade": {
        "name": "Meridian Casebook", "cat": "deck", "buffer": 8, "shield": 2,
        "speed": 1, "value": 2200, "desc": "Collective-issue. Reliable, "
        "unremarkable, traceable to a collective that will deny you.",
    },
    "deck_midgrade": {
        "name": "Silvert Nine", "cat": "deck", "buffer": 12, "shield": 4,
        "speed": 2, "value": 7500, "desc": "Custom shop build out of the Kiln.",
    },
    "deck_highgrade": {
        "name": "Tessellate Prime", "cat": "deck", "buffer": 18, "shield": 6,
        "speed": 3, "value": 21000, "desc": "Somebody died to get this out of "
        "a Halcyon lab. Possibly several somebodies.",
    },
}

PROGRAMS = {
    "prog_hammer": {
        "name": "Hammer", "cat": "program", "class": "attack",
        "power": 5, "trace": 8, "value": 700,
        "desc": "Brute-force ICE breaker. Loud.",
    },
    "prog_lancet": {
        "name": "Lancet", "cat": "program", "class": "attack",
        "power": 8, "trace": 5, "value": 2400,
        "desc": "Precision breaker. Finds the seam instead of the wall.",
    },
    "prog_veil": {
        "name": "Veil", "cat": "program", "class": "stealth",
        "power": 4, "trace": -6, "value": 900,
        "desc": "Masks your signature. Reduces trace accumulation.",
    },
    "prog_mirror": {
        "name": "Mirror", "cat": "program", "class": "defense",
        "power": 6, "trace": 3, "value": 1800,
        "desc": "Reflects a portion of ICE damage back at its host.",
    },
    "prog_siphon": {
        "name": "Siphon", "cat": "program", "class": "utility",
        "power": 5, "trace": 6, "value": 1500,
        "desc": "Pulls data and credits out of a cracked node faster.",
    },
    "prog_cauterise": {
        "name": "Cauterise", "cat": "program", "class": "utility",
        "power": 20, "trace": 0, "value": 3000,
        "desc": "Emergency trace purge. One use per run.",
    },
}

# ICE -- Intrusion Countermeasures. attack damages the runner's deck buffer;
# on buffer depletion, damage carries to the runner's HP (feedback).
ICE = {
    "watchdog": {
        "name": "Watchdog", "tier": 1, "hp": 8, "attack": 3, "defense": 2,
        "trace_rate": 5, "lethal": False,
        "desc": "Logs you and raises the alarm. Harmless on its own.",
    },
    "mastiff": {
        "name": "Mastiff", "tier": 2, "hp": 14, "attack": 6, "defense": 4,
        "trace_rate": 8, "lethal": False,
        "desc": "Bites the deck. Will not follow you out.",
    },
    "tallyman": {
        "name": "Tallyman", "tier": 2, "hp": 10, "attack": 4, "defense": 6,
        "trace_rate": 14, "lethal": False,
        "desc": "Doesn't fight. Just counts, accurately and fast.",
    },
    "verdict": {
        "name": "Verdict", "tier": 3, "hp": 22, "attack": 9, "defense": 7,
        "trace_rate": 10, "lethal": True,
        "desc": "Black ICE. Halcyon runs it on anything above Deck 40.",
    },
    "ossifier": {
        "name": "Ossifier", "tier": 4, "hp": 30, "attack": 12, "defense": 9,
        "trace_rate": 12, "lethal": True,
        "desc": "Induces a seizure through the neural port and holds it there.",
    },
}


# ==========================================================================
# STATUS EFFECTS
# ==========================================================================
STATUS_EFFECTS = {
    "bleeding":    {"desc": "Losing blood", "per_turn_damage": 2, "stacks": True},
    "stunned":     {"desc": "Can't act", "skip_turn": True, "stacks": False},
    "burning":     {"desc": "On fire", "per_turn_damage": 4, "stacks": False},
    "poisoned":    {"desc": "Toxin in the blood", "per_turn_damage": 1,
                    "attr_mod": {"BOD": -1}, "stacks": True},
    "stimmed":     {"desc": "Riding a stim", "attr_mod": {"REF": 2}, "stacks": False},
    "crash":       {"desc": "Stim crash", "attr_mod": {"REF": -2, "NRV": -1}, "stacks": False},
    "emp_locked":  {"desc": "Cyberware offline", "suppress_cyber": True, "stacks": False},
    "suppressed":  {"desc": "Pinned down", "attr_mod": {"REF": -2}, "stacks": False},
    "dissociated": {"desc": "Coherence failure", "attr_mod": {"PRE": -2, "NRV": -2},
                    "stacks": False},
    "drowning":    {"desc": "Out of air", "per_turn_damage": 5, "stacks": False},
}


# ==========================================================================
# PROCGEN VOCABULARY
# ==========================================================================
# The location generator composes: KIND + DESCRIPTOR + FEATURE + OCCUPANT.
LOCATION_KINDS = {
    "terraces": {
        "atrium": 3, "office_floor": 4, "clinic": 2, "server_farm": 2,
        "residence": 3, "transit_hub": 2, "laboratory": 2,
    },
    "sable_row": {
        "bar": 5, "ripperdoc": 3, "fight_pit": 2, "noodle_stall": 4,
        "pawn_shop": 3, "flophouse": 3, "arcade": 2,
    },
    "kiln": {
        "foundry": 4, "fab_shop": 4, "warehouse": 3, "boiler_room": 2,
        "chem_store": 2, "loading_dock": 3,
    },
    "gantry": {
        "container_stack": 5, "bonded_warehouse": 3, "crane_gantry": 2,
        "customs_shed": 2, "wet_dock": 3, "barge": 2,
    },
    "drowned": {
        "flooded_lobby": 5, "rooftop_camp": 3, "submerged_vault": 2,
        "pump_station": 2, "tidal_farm": 3, "collapsed_span": 3,
    },
    "static_fields": {
        "squat_block": 5, "antenna_base": 2, "scrap_yard": 4,
        "chapel": 2, "signal_shack": 3, "buried_bunker": 1,
    },
}

DESCRIPTORS = [
    "flooded", "half-demolished", "freshly repainted", "condemned",
    "smoke-stained", "overlit", "pitch-dark", "humming", "silent",
    "waterlogged", "barricaded", "wide open", "stripped to the studs",
    "crowded", "abandoned mid-shift", "recently swept", "rusted through",
]

FEATURES = [
    "a maintenance shaft nobody has bricked up",
    "a security desk with the monitors still live",
    "standing water up to the shins",
    "a cargo lift that only goes down",
    "scaffolding across the whole east wall",
    "an Ossuary shrine wedged into an alcove",
    "a Halcyon drone charging cradle, occupied",
    "three months of unread mail on the floor",
    "a wall of salvaged server racks, half of them warm",
    "a hole in the ceiling and daylight through it",
    "somebody's whole life in cardboard boxes",
    "a floor safe, welded shut from the outside",
    "a Lowline water filter serving forty families",
    "graffiti that keeps saying the same six words",
]

OCCUPANTS = {
    "empty": 6,
    "squatters": 4,
    "gang_crew": 3,
    "corp_security": 2,
    "cra_patrol": 2,
    "scavvers": 3,
    "ossuary_cell": 2,
    "drones": 2,
    "lone_fixer": 2,
    "wounded_stranger": 1,
}


# ==========================================================================
# NAME POOLS
# ==========================================================================
FIRST_NAMES = [
    "Ada", "Bex", "Corin", "Dae", "Esker", "Fen", "Grisel", "Hollis", "Imre",
    "Jun", "Kestrel", "Lem", "Mira", "Noor", "Oleg", "Pell", "Quill", "Rasa",
    "Sable", "Tibor", "Ulla", "Vance", "Wren", "Xia", "Yusuf", "Zeph",
    "Calder", "Mave", "Torrin", "Ilse", "Ovid", "Nyx", "Bram", "Sena",
]

LAST_NAMES = [
    "Achebe", "Baranov", "Calloway", "Duarte", "Esparza", "Ferreira",
    "Golubev", "Haddad", "Ito", "Jankovic", "Kowal", "Laurent", "Moreau",
    "Nakamura", "Okonjo", "Petrov", "Quesada", "Rasmussen", "Sarkis",
    "Tremaine", "Ustinov", "Vasquez", "Whitlock", "Xiang", "Yazdani", "Zoric",
]

STREET_NAMES = [
    "Ratchet", "Vespers", "Dimestore", "Nine-Fingers", "Cathode", "Pale Mary",
    "Tinwork", "Gospel", "Halfmast", "Brownout", "Saltwater", "The Auditor",
    "Kickdown", "Mothlight", "Sixty-Six", "Drydock", "Hush", "Ferryman",
]

NPC_ROLES = [
    "ripperdoc", "fixer", "courier", "dock foreman", "bartender",
    "netrunner", "enforcer", "smuggler", "pump technician", "archivist",
    "chem cook", "bounty hunter", "scrapper", "clinic nurse", "informant",
]


# ==========================================================================
# ENCOUNTERS
# ==========================================================================
# Weights are modified at runtime by district security, player heat and
# reputation -- see worldgen.encounter_table().
ENCOUNTER_TEMPLATES = {
    "shakedown": {
        "name": "Shakedown",
        "type": "social_combat",
        "text": "Three of them peel off a doorway and fan out. The one in "
                "front doesn't bother with a weapon. That's the message.",
        "faction": "ironvein", "threat": 2,
    },
    "cra_stop": {
        "name": "CRA Stop-and-Scan",
        "type": "social",
        "text": "The van doors open before it fully stops. Scanner wand up, "
                "already pointed at your skull.",
        "faction": "authority", "threat": 3,
    },
    "drone_sweep": {
        "name": "Drone Sweep",
        "type": "combat",
        "text": "Rotor wash off the wall above you. Two of them, quartering "
                "the block in a pattern that will reach you in nine seconds.",
        "faction": "halcyon", "threat": 3,
    },
    "scavver_dispute": {
        "name": "Salvage Dispute",
        "type": "social_combat",
        "text": "Somebody was already here. They have a boat hook and the "
                "expression of a person who has used it.",
        "faction": "lowline", "threat": 1,
    },
    "ossuary_sermon": {
        "name": "Street Sermon",
        "type": "social",
        "text": "A woman with chrome to the elbow is preaching from a crate. "
                "The crowd is bigger than it should be.",
        "faction": "ossuary", "threat": 0,
    },
    "dead_drop": {
        "name": "Dead Drop",
        "type": "discovery",
        "text": "A magnetic case behind a downpipe, exactly where the chalk "
                "mark said it would be.",
        "faction": "meridian", "threat": 0,
    },
    "ambush": {
        "name": "Ambush",
        "type": "combat",
        "text": "They were waiting. That's the last clear thought you get "
                "before the muzzle flash.",
        "faction": None, "threat": 4,
    },
    "wounded_runner": {
        "name": "Wounded Runner",
        "type": "social",
        "text": "Someone is propped against the wall with a hand over their "
                "abdomen and a deck still jacked into their skull.",
        "faction": "meridian", "threat": 0,
    },
    "cargo_spill": {
        "name": "Spilled Cargo",
        "type": "discovery",
        "text": "A container seam has split. Whatever was inside is now "
                "partly outside, and nobody has arrived to care yet.",
        "faction": "ironvein", "threat": 1,
    },
    "tide_warning": {
        "name": "Tide Warning",
        "type": "hazard",
        "text": "The klaxon on the pump station goes off, three short. The "
                "water is coming up and it is coming up now.",
        "faction": "lowline", "threat": 2,
    },
}


# ==========================================================================
# LOOT TIERS
# ==========================================================================
# tier -> {item_key: weight}. worldgen picks tier from district wealth +
# location security, then draws from the tier.
LOOT_TIERS = {
    1: {
        "stim_patch": 5, "trauma_kit": 4, "ammo_light": 6, "ammo_medium": 5,
        "combat_knife": 3, "holdout_pistol": 2, "armor_liner_coat": 2,
        "scrap": 8, "cred_small": 5,
    },
    2: {
        "trauma_kit": 5, "stim_patch": 4, "ammo_medium": 6, "ammo_shell": 4,
        "service_pistol": 3, "scattergun": 2, "armor_plate_vest": 3,
        "toolkit_field": 2, "prog_veil": 2, "burner_deck": 2,
        "scrap": 5, "cred_small": 6, "coolant_shunt": 2,
    },
    3: {
        "ammo_rifle": 5, "machine_pistol": 3, "carbine": 2, "armor_plate_vest": 3,
        "prog_hammer": 3, "prog_mirror": 2, "deck_lowgrade": 2,
        "emp_charge": 3, "neural_port": 1, "optic_suite": 2,
        "cred_medium": 5, "toolkit_field": 2,
    },
    4: {
        "carbine": 3, "armor_weave_suit": 2, "armor_riot": 2, "railpistol": 1,
        "mono_cleaver": 1, "prog_lancet": 2, "prog_siphon": 2,
        "deck_midgrade": 2, "subdermal_weave": 2, "muscle_lace": 2,
        "adrenal_pump": 1, "cred_medium": 4, "cred_large": 2,
    },
    5: {
        "railpistol": 2, "mono_cleaver": 2, "armor_weave_suit": 3,
        "deck_highgrade": 1, "prog_cauterise": 2, "reflex_governor": 1,
        "cortex_stack": 1, "cred_large": 5, "ammo_slug": 4,
    },
}

# Abstract loot keys that resolve to concrete items at generation time.
LOOT_ALIASES = {
    "scrap":       ("junk", "Salvaged Components", 15),
    "cred_small":  ("credits", None, 150),
    "cred_medium": ("credits", None, 700),
    "cred_large":  ("credits", None, 2200),
    "ammo_light":  ("ammo", "light", 30),
    "ammo_medium": ("ammo", "medium", 30),
    "ammo_rifle":  ("ammo", "rifle", 30),
    "ammo_shell":  ("ammo", "shell", 20),
    "ammo_slug":   ("ammo", "slug", 10),
}


def all_items() -> dict:
    """Merged catalogue of every concrete item template."""
    catalogue = {}
    catalogue.update(WEAPONS)
    catalogue.update(ARMOR)
    catalogue.update(CONSUMABLES)
    catalogue.update(DECKS)
    catalogue.update(PROGRAMS)
    return catalogue


ITEMS = all_items()
