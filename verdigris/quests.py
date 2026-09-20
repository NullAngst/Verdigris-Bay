"""
quests.py -- Node-based dynamic narrative system.

ARCHITECTURE
    The story is a directed graph of nodes stored in the `quest_nodes` table.
    Each node carries:

        preconditions : JSON predicate evaluated against live game state
        effects       : JSON state mutations applied when the node fires
        choices       : branches the player selects between, each with its own
                        requirements and effects
        terminal      : marks an ending node

    Every world turn, check_triggers() evaluates the preconditions of every
    'locked' node. Nodes whose conditions are met become 'available' and are
    surfaced to the player. This means the story is *pulled* by world state
    rather than *pushed* by a linear script: the same playthrough reaches
    different nodes depending on where you went, who you angered, how much
    chrome you took and how hot you ran.

PRECONDITION DSL
    Keys are ANDed together. Any key may be omitted.

        turn_min        int    -- world turn at least this
        level_min       int    -- player level at least this
        district        str|[] -- player must be in this district / one of
        rep             {faction: int}   -- standing >= value (negative = <=)
        flag            {key: value}     -- flag equals value
        not_flag        [keys]           -- none of these flags are truthy
        nodes_done      [node_ids]       -- all listed nodes completed
        nodes_not_done  [node_ids]       -- none of them completed
        item            str    -- player holds this item template
        credits_min     int
        coherence_min   int
        coherence_max   int    -- gates the "you're still yourself" endings
        trace_min       int
        heat_min        int
        chance          float  -- rolled each evaluation; the random trigger
        manual          True   -- never auto-triggers; unlock-only (endings)

EFFECTS DSL
        set_flag   {key: value}
        bump_flag  {key: int}
        rep        {faction: int}
        credits    int
        xp         int
        items      [template_keys]
        heat       int
        trace      int
        coherence  int
        unlock     [node_ids]      -- force nodes from locked to available
        complete   [node_ids]
        fail       [node_ids]
        journal    str
"""

from __future__ import annotations

import sqlite3

from . import content
from .db import Database, jdump, jload
from .dice import Dice
from .rules import Character, adjust_rep, get_rep


# ==========================================================================
# PRECONDITION EVALUATION
# ==========================================================================
def evaluate(db: Database, dice: Dice, char: Character, cond: dict) -> bool:
    """Return True if every clause in `cond` holds against current state."""
    if not cond:
        return True

    # `manual` marks a node that must never auto-trigger from world state --
    # it is reachable ONLY through another node's `unlock` effect. Without
    # this, ending nodes (which carry no preconditions of their own, since
    # their gating lives in the choices that unlock them) evaluated as
    # trivially true and every ending became available on turn one.
    if cond.get("manual"):
        return False

    player = db.player()
    if player is None:
        return False

    if "turn_min" in cond and db.turn < cond["turn_min"]:
        return False

    if "level_min" in cond and player["level"] < cond["level_min"]:
        return False

    if "district" in cond:
        want = cond["district"]
        want = [want] if isinstance(want, str) else want
        if player["district"] not in want:
            return False

    for fid, threshold in cond.get("rep", {}).items():
        value = get_rep(db, fid)
        # Negative thresholds express "at most" -- rep must be <= threshold.
        if threshold >= 0 and value < threshold:
            return False
        if threshold < 0 and value > threshold:
            return False

    for key, want in cond.get("flag", {}).items():
        have = db.flag(key)
        if isinstance(want, int) and not isinstance(want, bool):
            try:
                if int(have or 0) < want:
                    return False
            except (TypeError, ValueError):
                return False
        elif have != want:
            return False

    for key in cond.get("not_flag", []):
        if db.flag(key):
            return False

    for nid in cond.get("nodes_done", []):
        row = db.one("SELECT status FROM quest_nodes WHERE id=?", (nid,))
        if not row or row["status"] != "done":
            return False

    for nid in cond.get("nodes_not_done", []):
        row = db.one("SELECT status FROM quest_nodes WHERE id=?", (nid,))
        if row and row["status"] == "done":
            return False

    if "item" in cond:
        row = db.one(
            "SELECT 1 FROM items WHERE owner_type='player' AND owner_id=1 "
            "AND template=?", (cond["item"],),
        )
        if not row:
            return False

    if "credits_min" in cond and player["credits"] < cond["credits_min"]:
        return False
    if "coherence_min" in cond and player["coherence"] < cond["coherence_min"]:
        return False
    if "coherence_max" in cond and player["coherence"] > cond["coherence_max"]:
        return False
    if "trace_min" in cond and player["trace"] < cond["trace_min"]:
        return False

    if "heat_min" in cond:
        row = db.one("SELECT heat FROM districts WHERE id=?", (player["district"],))
        if not row or row["heat"] < cond["heat_min"]:
            return False

    if "chance" in cond and not dice.chance(cond["chance"]):
        return False

    return True


# ==========================================================================
# EFFECT APPLICATION
# ==========================================================================
def apply_effects(db: Database, dice: Dice, char: Character,
                  effects: dict) -> list[str]:
    """Mutate game state. Returns player-facing messages."""
    out: list[str] = []
    if not effects:
        return out

    for key, value in effects.get("set_flag", {}).items():
        db.set_flag(key, value)

    for key, amount in effects.get("bump_flag", {}).items():
        db.bump_flag(key, amount)

    for fid, delta in effects.get("rep", {}).items():
        leverage = char.passive() == "leverage"
        changed = adjust_rep(db, fid, delta, leverage=leverage)
        for cid, newval in changed.items():
            sign = "+" if newval >= 0 else ""
            out.append(f"  {content.FACTIONS[cid]['name']}: {sign}{newval}")

    if "credits" in effects:
        char.credits(effects["credits"])
        out.append(f"  Credits {effects['credits']:+d}.")

    if "xp" in effects:
        out += ["  " + m for m in char.award_xp(effects["xp"])]
        out.append(f"  +{effects['xp']} XP.")

    for key in effects.get("items", []):
        if key in content.CYBERWARE:
            ok, msg = char.install_cyberware(key)
            out.append("  " + msg)
        elif char.give_item(key):
            out.append(f"  Received {content.ITEMS[key]['name']}.")

    if "heat" in effects:
        from .rules import adjust_heat
        adjust_heat(db, db.player()["district"], effects["heat"])

    if "trace" in effects:
        db.adjust_player("trace", effects["trace"], lo=0, hi=100)

    if "coherence" in effects:
        delta = effects["coherence"]
        if delta < 0:
            char.spend_coherence(-delta, reason="(the things you've seen)")
        else:
            char.restore_coherence(delta)
        out.append(f"  Coherence {delta:+d}.")

    for nid in effects.get("unlock", []):
        db.run(
            "UPDATE quest_nodes SET status='available' WHERE id=? AND status='locked'",
            (nid,),
        )

    for nid in effects.get("complete", []):
        db.run(
            "UPDATE quest_nodes SET status='done', fired_turn=? WHERE id=?",
            (db.turn, nid),
        )

    for nid in effects.get("fail", []):
        db.run("UPDATE quest_nodes SET status='failed' WHERE id=?", (nid,))

    if "journal" in effects:
        db.log(effects["journal"], "quest")

    return out


# ==========================================================================
# MANAGER
# ==========================================================================
class QuestManager:
    def __init__(self, db: Database, dice: Dice, char: Character):
        self.db = db
        self.dice = dice
        self.char = char

    def check_triggers(self) -> list[sqlite3.Row]:
        """
        Promote any locked node whose preconditions now hold.
        Called once per world turn from the main loop.
        """
        newly: list[sqlite3.Row] = []
        for node in self.db.q("SELECT * FROM quest_nodes WHERE status='locked'"):
            cond = jload(node["preconditions"], {})
            if evaluate(self.db, self.dice, self.char, cond):
                self.db.run(
                    "UPDATE quest_nodes SET status='available' WHERE id=?",
                    (node["id"],),
                )
                newly.append(node)
        return newly

    def available(self) -> list[sqlite3.Row]:
        return self.db.q(
            "SELECT * FROM quest_nodes WHERE status IN ('available','active') "
            "ORDER BY arc, id"
        )

    def get(self, node_id: str) -> sqlite3.Row | None:
        return self.db.one("SELECT * FROM quest_nodes WHERE id=?", (node_id,))

    def open_node(self, node_id: str) -> tuple[sqlite3.Row | None, list[dict]]:
        """
        Enter a node. Returns (node, valid_choices) where valid_choices are
        those whose own `requires` predicate currently holds.
        """
        node = self.get(node_id)
        if not node or node["status"] not in ("available", "active"):
            return None, []
        self.db.run("UPDATE quest_nodes SET status='active' WHERE id=?", (node_id,))

        choices = jload(node["choices"], [])
        valid = [
            c for c in choices
            if evaluate(self.db, self.dice, self.char, c.get("requires", {}))
        ]
        return node, valid

    def resolve_choice(self, node_id: str, choice: dict) -> list[str]:
        """Apply a choice's effects and close out the node."""
        out = []
        node = self.get(node_id)
        if not node:
            return ["That thread has gone cold."]

        if choice.get("text_result"):
            out.append(choice["text_result"])

        # Node-level effects fire first, then the choice's own.
        out += apply_effects(self.db, self.dice, self.char, jload(node["effects"], {}))
        out += apply_effects(self.db, self.dice, self.char, choice.get("effects", {}))

        self.db.run(
            "UPDATE quest_nodes SET status='done', fired_turn=? WHERE id=?",
            (self.db.turn, node_id),
        )
        self.db.log(f"[{node['arc']}] {node['title']}", "quest")

        if node["terminal"]:
            self.db.set_flag("ending", node_id)
        return out

    def ending(self) -> str | None:
        return self.db.flag("ending")


# ==========================================================================
# THE MAIN ARC -- "THE LEDGER"
# ==========================================================================
# An original storyline built to exercise every trigger type in the DSL:
# location, reputation threshold, database flag, item possession, coherence
# band, trace level, and random chance.
#
# PREMISE
#   Forty years ago the seawall failed and twelve blocks went under. The
#   official finding was storm surge beyond design tolerance. An internal
#   Halcyon audit ledger says otherwise: the reinforcement was costed,
#   scheduled, and cancelled, and the cancellation was signed. That ledger is
#   still in a Halcyon system, and someone has just died trying to move it.
#
# NON-LINEARITY
#   Act 2 has three entry points (Gantry / Terraces / Drowned), any ONE of
#   which advances the arc. Act 3 can be completed by netrun OR by physical
#   infiltration OR by buying it outright. There are five endings, gated on
#   reputation, coherence and the choices logged along the way.

ARC = "The Ledger"

NODES = [
    # ------------------------------------------------------------------
    # ACT ONE
    # ------------------------------------------------------------------
    {
        "id": "ledger_01_courier",
        "arc": ARC,
        "title": "The Courier",
        "body": (
            "The woman ahead of you in the queue goes down like a dropped coat.\n\n"
            "No shot, no sound -- her legs simply stop being load-bearing. By "
            "the time you reach her she is grey and her pupils are two "
            "different sizes. Neural spike, delivered remotely. Somebody "
            "reached into her skull from somewhere else and turned her off.\n\n"
            "Her hand is closed around a shard drive. It is still warm, and "
            "the indicator on the side is blinking, which means it is still "
            "writing. Whatever is on it, it isn't finished arriving.\n\n"
            "You have about nine seconds before the crowd notices."
        ),
        "preconditions": {"turn_min": 2},
        "effects": {"journal": "A courier died in front of you holding a shard drive."},
        "choices": [
            {
                "id": "take",
                "text": "Take the shard and walk.",
                "text_result": (
                    "You palm it and keep moving at exactly the speed you were "
                    "already moving. Nobody looks up."
                ),
                "effects": {
                    "set_flag": {"has_shard": True},
                    "xp": 30,
                    "unlock": ["ledger_02_decrypt"],
                    "journal": "You took the shard.",
                },
            },
            {
                "id": "leave",
                "text": "Leave it. This is somebody else's problem.",
                "text_result": (
                    "You keep walking. Four minutes later a van with no "
                    "markings takes the corner behind you, fast.\n\n"
                    "You will think about this again."
                ),
                "effects": {
                    "set_flag": {"refused_shard": True},
                    "unlock": ["ledger_01b_second_chance"],
                },
            },
            {
                "id": "help",
                "text": "Try to keep her alive.",
                "text_result": (
                    "You get two fingers to her carotid and find nothing worth "
                    "finding. But she is not quite gone, and her hand opens, "
                    "and she pushes the shard into your palm with the last "
                    "deliberate act of her life.\n\n"
                    "\"Vance,\" she says. Then she stops."
                ),
                "requires": {},
                "effects": {
                    "set_flag": {"has_shard": True, "knows_vance": True,
                                 "tried_to_help": True},
                    "xp": 50,
                    "coherence": -3,
                    "rep": {"lowline": 4},
                    "unlock": ["ledger_02_decrypt"],
                    "journal": "She gave you the shard and a name: Vance.",
                },
            },
        ],
    },
    {
        "id": "ledger_01b_second_chance",
        "arc": ARC,
        "title": "It Finds You Anyway",
        "body": (
            "A kid you don't know puts a shard drive on the bar next to your "
            "elbow and is gone before you turn around.\n\n"
            "It's the same shard. Someone got it out of the crowd before the "
            "van arrived, and someone has decided it is yours now. There is a "
            "strip of tape on it with one word written in marker: VANCE."
        ),
        "preconditions": {
            "flag": {"refused_shard": True},
            "turn_min": 6,
            "chance": 0.35,
        },
        "effects": {},
        "choices": [
            {
                "id": "accept",
                "text": "Fine. Pocket it.",
                "text_result": "You pocket it. The city has made its decision.",
                "effects": {
                    "set_flag": {"has_shard": True, "knows_vance": True},
                    "xp": 30,
                    "unlock": ["ledger_02_decrypt"],
                },
            },
            {
                "id": "destroy",
                "text": "Snap it in half and leave it on the bar.",
                "text_result": (
                    "It breaks with a sound like a knuckle cracking. You leave "
                    "the pieces where the bartender can see them, so whoever "
                    "comes asking gets an answer.\n\n"
                    "Nobody ever comes asking. That should reassure you."
                ),
                "effects": {
                    "set_flag": {"shard_destroyed": True},
                    "journal": "You destroyed the shard.",
                },
            },
        ],
    },
    {
        "id": "ledger_02_decrypt",
        "arc": ARC,
        "title": "What's On It",
        "body": (
            "The shard is Halcyon internal, and it is encrypted with something "
            "that was expensive when it was new and is merely difficult now.\n\n"
            "What you can read without cracking it is a header and a date "
            "range: forty-one years back, the eighteen months either side of "
            "the seawall failure. What you can't read is everything else.\n\n"
            "You need somebody who can open it, and everybody who can open it "
            "will want to know why."
        ),
        "preconditions": {"flag": {"has_shard": True}},
        "effects": {},
        "choices": [
            {
                "id": "meridian",
                "text": "Take it to Grey Meridian.",
                "requires": {"rep": {"meridian": 10}},
                "text_result": (
                    "The archivist doesn't touch it. She looks at it for a long "
                    "time on a screen that is not connected to anything, and "
                    "then she says:\n\n"
                    "\"This is a costing document. Someone priced the "
                    "reinforcement of the western seawall, scheduled it for "
                    "the following quarter, and then it was cancelled. The "
                    "cancellation has a signature block. The signature block "
                    "is redacted at source, which means somebody redacted it "
                    "*inside* Halcyon, which means the unredacted version is "
                    "in a Halcyon system right now.\"\n\n"
                    "She slides it back across the table.\n\n"
                    "\"The auditor who compiled it is named Imre Vance. He "
                    "retired eleven years ago. He is not dead, which is "
                    "interesting, because he should be.\""
                ),
                "effects": {
                    "set_flag": {"knows_vance": True, "shard_decrypted": True,
                                 "meridian_knows": True},
                    "xp": 80,
                    "rep": {"meridian": 8},
                    "unlock": ["ledger_03_find_vance"],
                    "journal": "Meridian cracked the shard. The auditor is Imre Vance.",
                },
            },
            {
                "id": "ossuary",
                "text": "Take it to the Ossuary -- they owe nobody and fear less.",
                "requires": {"rep": {"ossuary": 10}},
                "text_result": (
                    "The man who opens it has a port in each temple and does "
                    "it in four minutes on equipment that should not be "
                    "capable of it.\n\n"
                    "\"A ledger,\" he says, pleased. \"They costed the wall and "
                    "decided the wall was not worth the money, and then twelve "
                    "blocks became the Drowned Quarter, and then the Drowned "
                    "Quarter became us.\"\n\n"
                    "He does not give the shard back immediately.\n\n"
                    "\"The auditor is called Vance. Bring him to us and we will "
                    "make him honest.\""
                ),
                "effects": {
                    "set_flag": {"knows_vance": True, "shard_decrypted": True,
                                 "ossuary_knows": True},
                    "xp": 80,
                    "rep": {"ossuary": 8},
                    "unlock": ["ledger_03_find_vance"],
                    "journal": "The Ossuary cracked the shard and wants Vance.",
                },
            },
            {
                "id": "self",
                "text": "Crack it yourself.",
                "requires": {},
                "text_result": (
                    "Nine hours, most of a coolant shunt and an argument with "
                    "your own deck later, it opens.\n\n"
                    "A costing document. The western seawall reinforcement, "
                    "priced and scheduled and then cancelled, with the "
                    "cancellation signature redacted at source. And a compiler "
                    "field, because auditors sign their work:\n\n"
                    "    COMPILED: I. VANCE, INTERNAL AUDIT\n\n"
                    "Nobody else knows you have this. That is worth something "
                    "and it will cost you something."
                ),
                "effects": {
                    "set_flag": {"knows_vance": True, "shard_decrypted": True,
                                 "solo_decrypt": True},
                    "xp": 110,
                    "trace": 12,
                    "unlock": ["ledger_03_find_vance"],
                    "journal": "You cracked the shard alone. Nobody knows you have it.",
                },
            },
            {
                "id": "sell_now",
                "text": "Sell it unread to whoever's buying.",
                "text_result": (
                    "A fixer in Sable Row gives you eight thousand and does not "
                    "ask a single question, which is how you know you sold it "
                    "for a tenth of what it was worth.\n\n"
                    "Two weeks later a man named Imre Vance is found in the "
                    "Drowned Quarter with his neural port melted shut. The "
                    "story runs for one day."
                ),
                "effects": {
                    "credits": 8000,
                    "set_flag": {"sold_shard": True},
                    "coherence": -6,
                    "rep": {"halcyon": 5, "lowline": -10, "meridian": -8},
                    "journal": "You sold the shard unread. Vance died for it.",
                    "unlock": ["ledger_end_complicit"],
                },
            },
        ],
    },
    # ------------------------------------------------------------------
    # ACT TWO -- three parallel entry points, any one advances
    # ------------------------------------------------------------------
    {
        "id": "ledger_03_find_vance",
        "arc": ARC,
        "title": "Finding Imre Vance",
        "body": (
            "Eleven years retired and still breathing is a trick. You put out "
            "the question carefully and get three answers back, which means "
            "two of them are wrong, or all three are and he's somewhere else "
            "entirely.\n\n"
            "  * A manifest at the Gantry lists an I. VANCE on a container "
            "ship leaving in four days.\n"
            "  * A Terraces residence is still drawing his pension and "
            "filtering his air.\n"
            "  * The Lowline says an old man with corporate hands has been "
            "living above the waterline in the Drowned Quarter for a decade "
            "and does not talk to anybody."
        ),
        "preconditions": {"flag": {"knows_vance": True}},
        "effects": {"set_flag": {"hunting_vance": True}},
        "choices": [
            {
                "id": "gantry",
                "text": "The Gantry. Catch him before the ship leaves.",
                "requires": {"district": "gantry"},
                "text_result": (
                    "The manifest is real and the name is real and the man is "
                    "not Imre Vance. He is a longshoreman who was paid four "
                    "hundred credits to carry the name onto a ship and off "
                    "again at the other end.\n\n"
                    "\"He's not leaving,\" the man says. \"He wanted somebody to "
                    "*think* he left. Paid me the same day the girl died.\"\n\n"
                    "Which tells you Vance knew about the courier, and moved "
                    "the same day, and is still in the Bay."
                ),
                "effects": {
                    "set_flag": {"vance_decoy_found": True},
                    "xp": 70,
                    "rep": {"ironvein": 4},
                    "unlock": ["ledger_04_vance"],
                    "journal": "The Gantry manifest was a decoy. Vance never left.",
                },
            },
            {
                "id": "terraces",
                "text": "The Terraces. Walk into his apartment.",
                "requires": {"district": "terraces"},
                "text_result": (
                    "The apartment has been drawing power and filtering air for "
                    "eleven years for the benefit of nobody. The furniture is "
                    "under sheets. The pension is being collected by an "
                    "automatic transfer into an account that pays a Drowned "
                    "Quarter water levy.\n\n"
                    "He is paying for water. In a flooded district. Which means "
                    "he is paying somebody to bring him clean water, and the "
                    "only people who do that are the Lowline."
                ),
                "effects": {
                    "set_flag": {"vance_trace_found": True},
                    "xp": 70,
                    "heat": 12,
                    "unlock": ["ledger_04_vance"],
                    "journal": "Vance's pension pays a Drowned Quarter water levy.",
                },
            },
            {
                "id": "drowned",
                "text": "The Drowned Quarter. Ask the Lowline directly.",
                "requires": {"district": "drowned", "rep": {"lowline": 15}},
                "text_result": (
                    "They don't pretend not to know. That's not how the Lowline "
                    "works.\n\n"
                    "\"Third floor of the old assessor's office, above the "
                    "tideline,\" the pump tech says. \"He's been there ten "
                    "years. He pays his levy and he doesn't bother anybody and "
                    "when the wall alarm goes he comes down and helps like "
                    "everyone else.\"\n\n"
                    "She looks at you for a while.\n\n"
                    "\"He's ours now. Whatever you're bringing him, bring it "
                    "carefully.\""
                ),
                "effects": {
                    "set_flag": {"vance_located": True, "lowline_vouched": True},
                    "xp": 90,
                    "rep": {"lowline": 6},
                    "unlock": ["ledger_04_vance"],
                    "journal": "The Lowline gave you Vance's address, and a warning.",
                },
            },
        ],
    },
    {
        "id": "ledger_04_vance",
        "arc": ARC,
        "title": "The Auditor",
        "body": (
            "Third floor of the old assessor's office, above the tideline. The "
            "stairs below the second landing are underwater and have been for "
            "a decade.\n\n"
            "Imre Vance is eighty-one and has corporate hands -- good ones, "
            "eleven years out of date, the kind of chrome a company gives you "
            "so you can work faster and then never updates because you are no "
            "longer worth updating.\n\n"
            "He does not seem surprised. He puts the kettle on.\n\n"
            "\"You found the compiler field,\" he says. \"Everyone does, "
            "eventually. That's not the document. That's the receipt for the "
            "document.\"\n\n"
            "He sits down opposite you.\n\n"
            "\"The ledger itself is still inside. Vault partition, Terraces "
            "deck forty. I put it there. I have spent eleven years deciding "
            "whether to take it out, and the honest answer is that I have been "
            "waiting for somebody to make me.\""
        ),
        "preconditions": {"flag": {"hunting_vance": True},
                          "nodes_done": ["ledger_03_find_vance"]},
        "effects": {"set_flag": {"met_vance": True}},
        "choices": [
            {
                "id": "ally",
                "text": "\"Then let's go get it.\"",
                "text_result": (
                    "He is quiet for a moment. Then he gets up and takes an "
                    "access card out of a tin on the shelf, eleven years cold, "
                    "and puts it on the table between you.\n\n"
                    "\"It won't open the vault. It'll get you to deck forty "
                    "without a checkpoint stopping you, which is the part "
                    "people usually die at.\"\n\n"
                    "\"And the vault?\"\n\n"
                    "\"The vault is your problem. I only ever solved my half.\""
                ),
                "effects": {
                    "set_flag": {"vance_ally": True, "has_access_card": True},
                    "xp": 120,
                    "unlock": ["ledger_05_vault"],
                    "journal": "Vance gave you a Terraces access card for deck forty.",
                },
            },
            {
                "id": "coerce",
                "text": "Make it clear he doesn't have a choice.",
                "text_result": (
                    "He listens to you the way an auditor listens: waiting for "
                    "the number that doesn't reconcile.\n\n"
                    "\"You've decided I'm a coward,\" he says. \"That's "
                    "reasonable. I've had eleven years to decide the same "
                    "thing.\"\n\n"
                    "He gives you the card. He does not look at you while he "
                    "does it, and he does not tell you the part he was going "
                    "to tell you, and you will find out what that part was at "
                    "the worst possible moment."
                ),
                "effects": {
                    "set_flag": {"vance_coerced": True, "has_access_card": True},
                    "xp": 90,
                    "coherence": -5,
                    "rep": {"lowline": -8},
                    "unlock": ["ledger_05_vault"],
                    "journal": "You strong-armed Vance. He held something back.",
                },
            },
            {
                "id": "sell_vance",
                "text": "He's worth more to Halcyon than the ledger is.",
                "requires": {"rep": {"halcyon": 20}},
                "text_result": (
                    "The number Halcyon quotes you is thirty thousand and they "
                    "quote it in under a minute, which means they have had it "
                    "costed and waiting for eleven years.\n\n"
                    "They are very polite. They ask you to leave the building "
                    "before the retrieval team arrives, as a courtesy.\n\n"
                    "You take the stairs down past the tideline and the water "
                    "is exactly as cold as it always is."
                ),
                "effects": {
                    "credits": 30000,
                    "set_flag": {"sold_vance": True},
                    "coherence": -12,
                    "rep": {"halcyon": 25, "lowline": -30, "meridian": -20,
                            "ossuary": -15},
                    "journal": "You sold Imre Vance to Halcyon for thirty thousand.",
                    "unlock": ["ledger_end_asset"],
                },
            },
        ],
    },
    # ------------------------------------------------------------------
    # ACT THREE -- the vault, three solutions
    # ------------------------------------------------------------------
    {
        "id": "ledger_05_vault",
        "arc": ARC,
        "title": "Deck Forty",
        "body": (
            "Halcyon Vertex, Terraces, deck forty. Vault partition.\n\n"
            "The card gets you off the transit ramp and into a corridor that "
            "smells like nothing at all, which is the single most expensive "
            "thing about the Terraces.\n\n"
            "The vault itself is a partition on an isolated host, and there "
            "are three ways in that anybody has ever come back from."
        ),
        "preconditions": {"flag": {"has_access_card": True}},
        "effects": {},
        "choices": [
            {
                "id": "netrun",
                "text": "Dive it. Take the partition apart from inside.",
                "requires": {"flag": {"data_shards": 1}},
                "text_result": (
                    "The partition is old architecture defended like new "
                    "architecture: two layers of Verdict sitting on a stack "
                    "that was built before Verdict existed.\n\n"
                    "You go in through the seam between the two and the ledger "
                    "is sitting in a read-only store with eleven years of dust "
                    "on the access log. The last entry before yours is "
                    "I. VANCE.\n\n"
                    "You pull it and you are out in ninety seconds, and your "
                    "hands do not stop shaking for an hour."
                ),
                "effects": {
                    "set_flag": {"has_ledger": True, "took_ledger_net": True},
                    "xp": 250,
                    "trace": 35,
                    "rep": {"halcyon": -20, "meridian": 10},
                    "journal": "You pulled the ledger out of deck forty.",
                    "unlock": ["ledger_06_what_now"],
                },
            },
            {
                "id": "physical",
                "text": "Walk in. Take the physical backup out of the vault.",
                "requires": {"level_min": 3},
                "text_result": (
                    "Vaults have physical backups because auditors do not trust "
                    "systems, and Vance was an auditor.\n\n"
                    "It is behind two doors and four people, and you get "
                    "through all six, and the last one has time to look at you "
                    "properly before you get past him. He will remember your "
                    "face and he will be asked about it.\n\n"
                    "The backup is a physical shard in a sealed case with a "
                    "handwritten label. The handwriting is shaky and eleven "
                    "years old:\n\n"
                    "    IF SOMEBODY IS READING THIS, I WAS RIGHT TO KEEP IT."
                ),
                "effects": {
                    "set_flag": {"has_ledger": True, "took_ledger_physical": True},
                    "xp": 250,
                    "heat": 45,
                    "rep": {"halcyon": -30, "authority": -15},
                    "journal": "You took the physical backup out of the vault.",
                    "unlock": ["ledger_06_what_now"],
                },
            },
            {
                "id": "buy",
                "text": "Buy it. Everything in the Terraces has a price.",
                "requires": {"credits_min": 25000},
                "text_result": (
                    "A vault clerk on deck forty has three children in Kiln "
                    "schools and a Halcyon salary that does not cover them.\n\n"
                    "She does not negotiate and she does not look at the "
                    "money. She hands you the partition key and says one "
                    "thing:\n\n"
                    "\"I read it. Six years ago, I read it, and I've been "
                    "waiting for somebody to come and buy it ever since. Take "
                    "it somewhere it matters.\""
                ),
                "effects": {
                    "credits": -25000,
                    "set_flag": {"has_ledger": True, "bought_ledger": True,
                                 "clerk_ally": True},
                    "xp": 200,
                    "rep": {"halcyon": -10},
                    "journal": "You bought the ledger from a clerk on deck forty.",
                    "unlock": ["ledger_06_what_now"],
                },
            },
        ],
    },
    {
        "id": "ledger_06_what_now",
        "arc": ARC,
        "title": "What It's Worth",
        "body": (
            "You have it.\n\n"
            "The western seawall reinforcement, costed at nine million, "
            "scheduled for the following quarter, cancelled eleven weeks "
            "before the surge. And the cancellation signature, unredacted, "
            "belonging to a man who is now on the Halcyon board and has been "
            "for thirty-one years.\n\n"
            "Twelve blocks. The Drowned Quarter is not a disaster. It is a "
            "line item.\n\n"
            "Now you decide what that's worth, and to whom."
        ),
        "preconditions": {"flag": {"has_ledger": True}},
        "effects": {},
        "choices": [
            {
                "id": "publish",
                "text": "Give it to Grey Meridian. Publish it everywhere at once.",
                "requires": {"rep": {"meridian": 40}},
                "effects": {"unlock": ["ledger_end_publish"],
                            "set_flag": {"chose_publish": True}},
                "text_result": "You take it to the archivists.",
            },
            {
                "id": "lowline",
                "text": "Give it to the Lowline. It's their twelve blocks.",
                "requires": {"rep": {"lowline": 40}},
                "effects": {"unlock": ["ledger_end_lowline"],
                            "set_flag": {"chose_lowline": True}},
                "text_result": "You take it down past the tideline.",
            },
            {
                "id": "leverage",
                "text": "Ironvein. Turn it into permanent leverage.",
                "requires": {"rep": {"ironvein": 40}},
                "effects": {"unlock": ["ledger_end_leverage"],
                            "set_flag": {"chose_leverage": True}},
                "text_result": "You take it to the Gantry.",
            },
            {
                "id": "sell",
                "text": "Sell it back to Halcyon. Retire.",
                "requires": {"rep": {"halcyon": 30}},
                "effects": {"unlock": ["ledger_end_sold"],
                            "set_flag": {"chose_sell": True}},
                "text_result": "You make the call.",
            },
            {
                "id": "burn",
                "text": "Destroy it. Nobody gets to own this.",
                "effects": {"unlock": ["ledger_end_burn"],
                            "set_flag": {"chose_burn": True}},
                "text_result": "You take it somewhere quiet.",
            },
        ],
    },
    # ------------------------------------------------------------------
    # ENDINGS
    # ------------------------------------------------------------------
    {
        "id": "ledger_end_publish",
        "arc": ARC,
        "title": "ENDING -- Open Record",
        "terminal": 1,
        "body": (
            "Meridian does not publish it. Meridian publishes it *everywhere*, "
            "which is different -- eleven hundred mirrors in under four "
            "minutes, every one of them in a jurisdiction that will not "
            "cooperate with the next ten.\n\n"
            "Halcyon's share price takes eight percent and recovers six. The "
            "board member resigns to spend more time with his family and is "
            "not charged with anything, because there is no statute under "
            "which a costing decision from forty-one years ago is a crime.\n\n"
            "But the seawall reinforcement gets funded within the year, "
            "because it is now cheaper to build it than to be the company "
            "that didn't. And a generation of people who grew up being told "
            "the water was weather find out the water was a budget.\n\n"
            "You do not get paid. Meridian gives you an archivist's mark, "
            "which is worth nothing and which you will keep for the rest of "
            "your life.\n\n"
            "The tide still comes in twice a day. It just isn't a mystery "
            "anymore."
        ),
        "preconditions": {"manual": True},
        "effects": {"rep": {"meridian": 30, "halcyon": -40, "lowline": 20},
                    "xp": 500, "journal": "ENDING: the ledger went public."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    {
        "id": "ledger_end_lowline",
        "arc": ARC,
        "title": "ENDING -- Standing Claim",
        "terminal": 1,
        "body": (
            "The Lowline does not publish it either. The Lowline files it.\n\n"
            "It turns out that a documented, signed, pre-meditated decision to "
            "not build a seawall is not a scandal -- it is *evidence*, and "
            "evidence has a use. Forty-one years of water damage across twelve "
            "blocks, with a signature on the cause.\n\n"
            "The claim takes six years and it is still going. But in year two "
            "the court grants an interim order and Halcyon starts paying for "
            "the pumps, and in year three the Drowned Quarter gets a legal "
            "standing it never had, and people who were squatters become "
            "claimants, which is a different word with a different future "
            "attached.\n\n"
            "You get a share. Not much, and slowly. The pump tech who told you "
            "where Vance lived brings it to you herself, in cash, every "
            "quarter, because that is how the Lowline does things.\n\n"
            "You still live here. That was always going to be the point."
        ),
        "preconditions": {"manual": True},
        "effects": {"rep": {"lowline": 40, "halcyon": -35}, "credits": 6000,
                    "xp": 500, "journal": "ENDING: the Lowline filed the claim."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    {
        "id": "ledger_end_leverage",
        "arc": ARC,
        "title": "ENDING -- The Standing Arrangement",
        "terminal": 1,
        "body": (
            "Ironvein does not want Halcyon destroyed. Ironvein wants Halcyon "
            "*obliged*, which is a far more durable asset.\n\n"
            "The arrangement is never written down. The Gantry customs office "
            "becomes even more relaxed than it already was. Certain containers "
            "stop being inspected at all. A Halcyon logistics subsidiary "
            "discovers it has a preferred freight partner it does not recall "
            "selecting.\n\n"
            "You are given a percentage and a title nobody says out loud, and "
            "for the first time in your life you are not the person who gets "
            "searched.\n\n"
            "The seawall does not get built. The twelve blocks stay under. "
            "Every quarter you sign for money that exists because a document "
            "about drowned people is sitting in a safe with your name on the "
            "access list.\n\n"
            "It's a good arrangement. You made sure of that."
        ),
        "preconditions": {"manual": True},
        "effects": {"rep": {"ironvein": 40, "lowline": -30, "authority": -25},
                    "credits": 45000, "coherence": -10, "xp": 500,
                    "journal": "ENDING: the ledger became leverage."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    {
        "id": "ledger_end_sold",
        "arc": ARC,
        "title": "ENDING -- Preferred Asset",
        "terminal": 1,
        "body": (
            "Halcyon pays one hundred and forty thousand and does not haggle, "
            "which tells you what it was actually worth and makes the number "
            "feel smaller every year that passes.\n\n"
            "You are relocated to the Terraces. Filtered air, real trees, a "
            "checkpoint that waves you through. Your Coherence stops "
            "degrading because you can afford maintenance now, and your "
            "chrome stops failing because you can afford the good clinic.\n\n"
            "Imre Vance dies fourteen months later of causes that are "
            "genuinely natural, which is the only mercy in this. He is "
            "eighty-two. The obituary is four lines and does not mention "
            "audit.\n\n"
            "From deck fifty-one you can see the Drowned Quarter on a clear "
            "day. It's the dark part. You can see exactly where the water "
            "line is, and you know to the week when it was decided, and you "
            "are the only person up here who does.\n\n"
            "The tide comes in twice a day. Nobody up here has ever had to "
            "know that."
        ),
        "preconditions": {"manual": True},
        "effects": {"rep": {"halcyon": 45, "lowline": -50, "meridian": -35,
                            "ossuary": -25},
                    "credits": 140000, "coherence": -15, "xp": 500,
                    "journal": "ENDING: you sold the ledger back to Halcyon."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    {
        "id": "ledger_end_burn",
        "arc": ARC,
        "title": "ENDING -- No Copies",
        "terminal": 1,
        "body": (
            "You take it to the Kiln and you put it in a foundry crucible at "
            "fourteen hundred degrees, and you watch until there is nothing "
            "left that any recovery lab could argue with.\n\n"
            "Your reasoning is sound, and you will rehearse it for years: "
            "published, it changes nothing and gets people killed. Given to "
            "the Lowline, it becomes a six-year court case that Halcyon can "
            "outspend. Sold, it makes you the last link in the chain that "
            "started with a cancelled work order.\n\n"
            "Every one of those is true. None of them is why you did it.\n\n"
            "You did it because for eight days you were the only person alive "
            "who could decide what happened to twelve drowned blocks, and the "
            "weight of that was unbearable, and the crucible made it stop.\n\n"
            "Imre Vance finds out somehow. He does not contact you. He simply "
            "stops paying his water levy, and moves out of the assessor's "
            "office, and the Lowline never finds out where he went.\n\n"
            "The tide comes in twice a day. It is nobody's fault now. That's "
            "what you bought."
        ),
        "preconditions": {"manual": True},
        "effects": {"coherence": -20, "xp": 500,
                    "journal": "ENDING: you destroyed the ledger."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    {
        "id": "ledger_end_complicit",
        "arc": ARC,
        "title": "ENDING -- Unread",
        "terminal": 1,
        "body": (
            "You never find out what was on it.\n\n"
            "That is the entire ending. You sold a shard you did not read to a "
            "fixer whose name you did not ask, for eight thousand credits, and "
            "a man named Imre Vance died in the Drowned Quarter eleven days "
            "later with his neural port melted shut.\n\n"
            "You hear the seawall story sometimes, in bars, from people who "
            "are certain. The surge was worse than the design tolerance. The "
            "surge was always worse than the design tolerance.\n\n"
            "Eight thousand credits is about four months, the way you live.\n\n"
            "The tide comes in twice a day."
        ),
        "preconditions": {"manual": True},
        "effects": {"coherence": -10, "xp": 200,
                    "journal": "ENDING: you sold it unread."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    {
        "id": "ledger_end_asset",
        "arc": ARC,
        "title": "ENDING -- Retrieval",
        "terminal": 1,
        "body": (
            "The retrieval team is four people and they are extremely good and "
            "the whole thing takes nine minutes.\n\n"
            "Halcyon pays what it said it would pay, on time, in full, because "
            "Halcyon always does -- that is why people keep selling them "
            "things.\n\n"
            "Imre Vance is debriefed for six weeks. At the end of it, the "
            "unredacted signature block is confirmed destroyed, the vault "
            "partition on deck forty is wiped, and an eighty-one-year-old man "
            "with eleven-year-old corporate hands is released into a care "
            "facility in the Terraces where he receives excellent treatment "
            "and does not speak.\n\n"
            "You have thirty thousand credits and the permanent, specific "
            "knowledge of what you are willing to do.\n\n"
            "The tide comes in twice a day. Somebody decided that. You know "
            "who, now, and you sold the only proof."
        ),
        "preconditions": {"manual": True},
        "effects": {"coherence": -18, "xp": 250,
                    "journal": "ENDING: you sold Vance and the trail went cold."},
        "choices": [{"id": "end", "text": "[ End ]", "effects": {}}],
    },
    # ------------------------------------------------------------------
    # AMBIENT / SIDE NODES -- demonstrate the other trigger types
    # ------------------------------------------------------------------
    {
        "id": "side_coherence_warning",
        "arc": "Side",
        "title": "The Person In The Window",
        "body": (
            "You catch your reflection in a dead shopfront and it takes you "
            "just slightly too long to recognise it.\n\n"
            "Not a long time. A quarter second. But you have been having that "
            "quarter second more often, and it is getting longer, and you know "
            "exactly what it is because everybody knows what it is.\n\n"
            "There is a clinic in Sable Row that does Coherence work. It is "
            "expensive and it is slow and it does not give you back what the "
            "chrome took, only some of it."
        ),
        "preconditions": {"coherence_max": 55, "not_flag": ["coherence_warned"]},
        "effects": {"set_flag": {"coherence_warned": True}},
        "choices": [
            {
                "id": "clinic",
                "text": "Book the clinic. (8,000cr)",
                "requires": {"credits_min": 8000},
                "text_result": (
                    "Three days of neural remapping and a headache that "
                    "outlasts it. You come out feeling marginally more like "
                    "the person who went in."
                ),
                "effects": {"credits": -8000, "coherence": 18},
            },
            {
                "id": "ossuary_way",
                "text": "Ask the Ossuary instead. They have opinions about this.",
                "requires": {"rep": {"ossuary": 25}},
                "text_result": (
                    "\"You're mourning a draft,\" the woman tells you, not "
                    "unkindly. \"The person in the window isn't gone. He was "
                    "never finished.\"\n\n"
                    "It does not restore your Coherence. It does make the "
                    "quarter second stop mattering quite so much, which is "
                    "arguably the same thing and arguably the opposite of it."
                ),
                "effects": {"coherence": 8, "rep": {"ossuary": 10}},
            },
            {
                "id": "ignore",
                "text": "It's a quarter second. Keep walking.",
                "text_result": "You keep walking.",
                "effects": {"set_flag": {"ignored_coherence": True}},
            },
        ],
    },
    {
        "id": "side_trace_knock",
        "arc": "Side",
        "title": "Someone At The Door",
        "body": (
            "Three knocks, evenly spaced. Nobody you know knocks like that.\n\n"
            "Through the spyhole: a woman in a coat that costs more than your "
            "deck, holding nothing, standing far enough back that you can see "
            "all of her. That is a deliberate choice and she wants you to "
            "notice she made it.\n\n"
            "\"I'm not here to serve anything,\" she says, to the door. \"I'm "
            "here because your trace signature has been sitting at the top of "
            "a list for four days and in about a week somebody less polite "
            "gets assigned to it.\""
        ),
        "preconditions": {"trace_min": 70, "not_flag": ["trace_visitor"],
                          "chance": 0.5},
        "effects": {"set_flag": {"trace_visitor": True}},
        "choices": [
            {
                "id": "deal",
                "text": "Open the door. Hear the offer.",
                "text_result": (
                    "The offer is simple: a one-time scrub of your trace "
                    "signature, in exchange for a name. Not yours. Somebody "
                    "else's.\n\n"
                    "You give her one. She writes nothing down."
                ),
                "effects": {"trace": -60, "rep": {"authority": 10, "meridian": -15},
                            "set_flag": {"gave_a_name": True}},
            },
            {
                "id": "refuse",
                "text": "Say nothing. Wait for her to leave.",
                "text_result": (
                    "She waits four minutes, which is a long time to stand in "
                    "a corridor, and then she goes.\n\n"
                    "Nothing happens for eleven days."
                ),
                "effects": {"rep": {"meridian": 8}, "heat": 15},
            },
        ],
    },
]


def install_arc(db: Database) -> None:
    """Load the narrative graph into the database. Idempotent."""
    for node in NODES:
        db.run(
            "INSERT OR IGNORE INTO quest_nodes"
            "(id,arc,title,body,status,preconditions,effects,choices,terminal) "
            "VALUES(?,?,?,?,'locked',?,?,?,?)",
            (node["id"], node["arc"], node["title"], node["body"],
             jdump(node.get("preconditions", {})),
             jdump(node.get("effects", {})),
             jdump(node.get("choices", [])),
             node.get("terminal", 0)),
        )
