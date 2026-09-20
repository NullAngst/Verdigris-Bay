"""
db.py -- SQLite persistence layer.

The database IS the game state. Nothing authoritative lives only in Python
objects; every subsystem reads and writes through here, so a save is just the
file on disk and there is no separate serialisation step to get out of sync.

SCHEMA OVERVIEW
    meta              key/value: seed, turn, version, player_id
    player            one row -- stats, vitals, credits, location
    skills            player skill ranks
    factions          static faction registry (seeded from content.py)
    reputation        player standing per faction, with history counter
    districts         the six city districts and their live state (heat)
    locations         procedurally generated sites, persisted once visited
    npcs              generated people, with per-NPC relationship columns
    items             everything ownable; polymorphic owner (player/location/npc)
    cyberware         installed implants with integrity tracking
    status_effects    timed conditions on any target
    net_hosts         discovered network hosts and their crack state
    quest_nodes       the node graph -- see quests.py
    flags             arbitrary narrative booleans/counters
    journal           append-only event log shown to the player

DESIGN NOTE ON `items`
    A single polymorphic table rather than separate player_inventory /
    loot_container tables. Moving an item from a crate into a backpack is
    then one UPDATE, and there is exactly one place where item state
    (condition, ammo loaded, quantity) can live.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable

SCHEMA_VERSION = 3


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    name          TEXT NOT NULL,
    handle        TEXT NOT NULL,
    role          TEXT NOT NULL,
    district      TEXT NOT NULL,
    location_id   INTEGER,
    credits       INTEGER NOT NULL DEFAULT 0,
    hp            INTEGER NOT NULL,
    hp_max        INTEGER NOT NULL,
    coherence     INTEGER NOT NULL DEFAULT 100,
    trace         INTEGER NOT NULL DEFAULT 0,
    heat          INTEGER NOT NULL DEFAULT 0,
    xp            INTEGER NOT NULL DEFAULT 0,
    level         INTEGER NOT NULL DEFAULT 1,
    ref INTEGER NOT NULL, bod INTEGER NOT NULL, intl INTEGER NOT NULL,
    nrv INTEGER NOT NULL, pre INTEGER NOT NULL, tec INTEGER NOT NULL,
    wir INTEGER NOT NULL,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS skills (
    skill TEXT PRIMARY KEY,
    rank  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS factions (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    short  TEXT NOT NULL,
    type   TEXT NOT NULL,
    blurb  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reputation (
    faction_id TEXT PRIMARY KEY,
    value      INTEGER NOT NULL DEFAULT 0
                 CHECK (value BETWEEN -100 AND 100),
    changes    INTEGER NOT NULL DEFAULT 0,
    last_turn  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (faction_id) REFERENCES factions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS districts (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    blurb     TEXT NOT NULL,
    security  INTEGER NOT NULL,
    wealth    INTEGER NOT NULL,
    flooding  INTEGER NOT NULL DEFAULT 0,
    control   TEXT,
    heat      INTEGER NOT NULL DEFAULT 0,
    tags      TEXT NOT NULL DEFAULT '[]',
    visited   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (control) REFERENCES factions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    district_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    descriptor  TEXT,
    feature     TEXT,
    occupant    TEXT,
    security    INTEGER NOT NULL DEFAULT 0,
    loot_tier   INTEGER NOT NULL DEFAULT 1,
    seed        INTEGER NOT NULL,
    discovered  INTEGER NOT NULL DEFAULT 0,
    cleared     INTEGER NOT NULL DEFAULT 0,
    looted      INTEGER NOT NULL DEFAULT 0,
    persistent  INTEGER NOT NULL DEFAULT 0,
    props       TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (district_id) REFERENCES districts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_loc_district ON locations(district_id);

CREATE TABLE IF NOT EXISTS npcs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    handle      TEXT,
    role        TEXT NOT NULL,
    faction_id  TEXT,
    district_id TEXT,
    location_id INTEGER,
    alive       INTEGER NOT NULL DEFAULT 1,
    met         INTEGER NOT NULL DEFAULT 0,
    -- relationship axes, each -100..100
    trust       INTEGER NOT NULL DEFAULT 0,
    fear        INTEGER NOT NULL DEFAULT 0,
    debt        INTEGER NOT NULL DEFAULT 0,
    hp          INTEGER NOT NULL DEFAULT 20,
    threat      INTEGER NOT NULL DEFAULT 1,
    notes       TEXT NOT NULL DEFAULT '',
    props       TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (faction_id)  REFERENCES factions(id)  ON DELETE SET NULL,
    FOREIGN KEY (district_id) REFERENCES districts(id) ON DELETE SET NULL,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_npc_district ON npcs(district_id);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    template    TEXT NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    owner_type  TEXT NOT NULL CHECK (owner_type IN ('player','location','npc','vendor')),
    owner_id    INTEGER NOT NULL,
    qty         INTEGER NOT NULL DEFAULT 1,
    condition   INTEGER NOT NULL DEFAULT 100,
    equipped    INTEGER NOT NULL DEFAULT 0,
    loaded      INTEGER NOT NULL DEFAULT 0,
    props       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_item_owner ON items(owner_type, owner_id);

CREATE TABLE IF NOT EXISTS cyberware (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    template    TEXT NOT NULL,
    name        TEXT NOT NULL,
    slot        TEXT NOT NULL,
    strain      INTEGER NOT NULL,
    integrity   INTEGER NOT NULL DEFAULT 100,
    online      INTEGER NOT NULL DEFAULT 1,
    installed_turn INTEGER NOT NULL DEFAULT 0,
    props       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS status_effects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL CHECK (target_type IN ('player','npc')),
    target_id   INTEGER NOT NULL,
    effect      TEXT NOT NULL,
    magnitude   INTEGER NOT NULL DEFAULT 1,
    turns       INTEGER NOT NULL DEFAULT 1,
    source      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_status_target ON status_effects(target_type, target_id);

CREATE TABLE IF NOT EXISTS net_hosts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    district_id TEXT,
    owner       TEXT,
    tier        INTEGER NOT NULL DEFAULT 1,
    depth       INTEGER NOT NULL DEFAULT 3,
    cracked     INTEGER NOT NULL DEFAULT 0,
    discovered  INTEGER NOT NULL DEFAULT 1,
    seed        INTEGER NOT NULL DEFAULT 0,
    props       TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (district_id) REFERENCES districts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS quest_nodes (
    id            TEXT PRIMARY KEY,
    arc           TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'locked'
                    CHECK (status IN ('locked','available','active','done','failed','missed')),
    preconditions TEXT NOT NULL DEFAULT '{}',
    effects       TEXT NOT NULL DEFAULT '{}',
    choices       TEXT NOT NULL DEFAULT '[]',
    terminal      INTEGER NOT NULL DEFAULT 0,
    fired_turn    INTEGER
);

CREATE TABLE IF NOT EXISTS flags (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    turn  INTEGER NOT NULL,
    kind  TEXT NOT NULL DEFAULT 'event',
    text  TEXT NOT NULL
);
"""


class Database:
    """Thin, explicit wrapper around sqlite3. No ORM, no magic."""

    def __init__(self, path: str = "verdigris.save"):
        self.path = path
        fresh = not os.path.exists(path) or path == ":memory:"
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.is_new = fresh

    # -- plumbing ----------------------------------------------------------
    def q(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def run(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cur

    def runmany(self, sql: str, seq: Iterable[Iterable]) -> None:
        self.conn.executemany(sql, [tuple(r) for r in seq])
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # -- meta --------------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.run(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    @property
    def turn(self) -> int:
        return int(self.get_meta("turn", 0))

    def advance_turn(self, n: int = 1) -> int:
        t = self.turn + n
        self.set_meta("turn", t)
        return t

    # -- flags -------------------------------------------------------------
    def set_flag(self, key: str, value: Any = True) -> None:
        self.run(
            "INSERT INTO flags(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def flag(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM flags WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def bump_flag(self, key: str, amount: int = 1) -> int:
        current = self.flag(key, 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        new = current + amount
        self.set_flag(key, new)
        return new

    # -- journal -----------------------------------------------------------
    def log(self, text: str, kind: str = "event") -> None:
        self.run(
            "INSERT INTO journal(turn,kind,text) VALUES(?,?,?)",
            (self.turn, kind, text),
        )

    def recent_journal(self, n: int = 15) -> list[sqlite3.Row]:
        return self.q(
            "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (n,)
        )

    # -- convenience -------------------------------------------------------
    def player(self) -> sqlite3.Row | None:
        return self.one("SELECT * FROM player WHERE id=1")

    def update_player(self, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.run(f"UPDATE player SET {cols} WHERE id=1", list(fields.values()))

    def adjust_player(self, field: str, delta: int,
                      lo: int | None = None, hi: int | None = None) -> int:
        """Additive update with optional clamping. Returns the new value."""
        row = self.player()
        if row is None:
            raise RuntimeError("no player row")
        new = row[field] + delta
        if lo is not None:
            new = max(lo, new)
        if hi is not None:
            new = min(hi, new)
        self.update_player(**{field: new})
        return new


def jload(value: str | None, default: Any = None) -> Any:
    """Tolerant JSON column reader."""
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def jdump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
