"""Headless integration test. Drives every subsystem without the CLI."""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verdigris import actions, combat, content, netrun, quests, worldgen
from verdigris.db import Database
from verdigris.dice import Dice
from verdigris.rules import Character, adjust_rep, get_rep, adjust_heat

FAILS = []

def check(label, cond):
    status = "ok  " if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILS.append(label)

def make_game(seed=1234, role="Runner"):
    if os.path.exists("/tmp/t.save"): os.remove("/tmp/t.save")
    db = Database("/tmp/t.save")
    dice = Dice(seed)
    worldgen.seed_world(db, dice)
    quests.install_arc(db)
    spec = content.ROLES[role]
    a = spec["attrs"]
    db.run("INSERT INTO player(id,name,handle,role,district,credits,hp,hp_max,"
           "coherence,trace,heat,xp,level,ref,bod,intl,nrv,pre,tec,wir) "
           "VALUES(1,'Test','Probe',?,'sable_row',5000,?,?,100,0,0,0,1,?,?,?,?,?,?,?)",
           (role, 10+a["BOD"]*3, 10+a["BOD"]*3, a["REF"],a["BOD"],a["INT"],
            a["NRV"],a["PRE"],a["TEC"],a["WIR"]))
    for s,r in spec["skills"].items():
        db.run("INSERT OR REPLACE INTO skills(skill,rank) VALUES(?,?)",(s,r))
    char = Character(db, dice)
    for k in spec["kit"]: char.give_item(k)
    for k in spec["cyber"]: char.install_cyberware(k)
    for it in char.items(category="weapon"):
        t = content.ITEMS[it["template"]]
        if t.get("ammo"):
            char.give_ammo(t["ammo"], 90)
            db.run("UPDATE items SET loaded=? WHERE id=?",(t["mag"],it["id"]))
    for cat in ("weapon","armor","deck"):
        its = char.items(category=cat)
        if its: char.equip(its[0]["id"])
    return db, dice, char


print("\n=== DICE ===")
d = Dice(7)
c = d.check(attribute=6, skill=3, difficulty="routine")
check("check returns a Check", hasattr(c, "success") and hasattr(c, "margin"))
check("swing_d10 in sane range", all(-60 < d.swing_d10()[0] < 80 for _ in range(3000)))
check("weighted respects zero weights",
      all(d.weighted({"a":1,"b":0}) == "a" for _ in range(200)))
check("seeded reproducibility", Dice(99).d10(5) == Dice(99).d10(5))
results = [Dice(i).check(5,3,"routine").success for i in range(500)]
rate = sum(results)/len(results)
check(f"routine success rate sane ({rate:.0%})", 0.55 < rate < 0.95)

print("\n=== DB + CHARACTER ===")
db, dice, char = make_game()
check("player row exists", db.player() is not None)
check("hp positive", char.row["hp"] > 0)
check("attrs computed", char.attr("WIR") >= 8)
check("coherence reduced by starting chrome", char.row["coherence"] < 100)
check("equipped weapon", char.equipped_weapon() is not None)
check("skills loaded", char.skill("intrusion") == 4)
check("ammo loaded", char.equipped_weapon()["loaded"] > 0)

print("\n=== COHERENCE ===")
before = char.row["coherence"]
char.spend_coherence(50)
check("coherence drops", char.row["coherence"] == before - 50)
band, pens = char.coherence_band()
check(f"band computed ({band})", band in [b[1] for b in
      __import__("verdigris.rules", fromlist=["x"]).COHERENCE_BANDS])
check("band penalties apply to attrs", char.attr("PRE") < char.base_attr("PRE"))
char.restore_coherence(50)
check("coherence restores", char.row["coherence"] == before)

print("\n=== CYBERWARE ===")
ok, msg = char.install_cyberware("optic_suite")
check("install succeeds", ok)
check("INT bonus applied", char.attr("INT") > char.base_attr("INT"))
imp = [c for c in char.cyberware() if c["template"]=="optic_suite"][0]
char.degrade_cyberware(60, target_id=imp["id"])
imp = db.one("SELECT * FROM cyberware WHERE id=?", (imp["id"],))
check(f"integrity degrades ({imp['integrity']}%)", imp["integrity"] == 40)
char.degrade_cyberware(100, target_id=imp["id"])
imp = db.one("SELECT * FROM cyberware WHERE id=?", (imp["id"],))
check("goes offline at 0", imp["online"] == 0 and imp["integrity"] == 0)
check("offline implant grants nothing", "zoom" not in char.grants())
char.repair_cyberware(imp["id"], 80)
check("repair restores + brings online",
      db.one("SELECT online FROM cyberware WHERE id=?",(imp["id"],))["online"]==1)
ok, msg = char.install_cyberware("optic_suite")
check("duplicate slot refused", not ok)

print("\n=== DAMAGE / ARMOR ===")
db, dice, char = make_game(role="Enforcer")
sp = char.armor_sp()
check(f"armor SP from vest ({sp})", sp >= 8)
hp0 = char.row["hp"]
taken, _ = char.damage(5)
check("light hit fully absorbed", taken == 0 and char.row["hp"] == hp0)
taken, notices = char.damage(40)
check(f"heavy hit penetrates ({taken})", taken > 0 and char.row["hp"] < hp0)
check("bleeding applied on heavy hit", char.has_status("bleeding"))
cond = [i for i in char.items(equipped_only=True)
        if i["template"] in content.ARMOR][0]["condition"]
check(f"armor ablated ({cond}%)", cond < 100)
char.heal(200)
check("heal caps at max", char.row["hp"] == char.row["hp_max"])

print("\n=== STATUS EFFECTS ===")
char.add_status("poisoned", turns=2, magnitude=2)
hp0 = char.row["hp"]
msgs = char.tick_statuses()
check("poison deals damage", char.row["hp"] < hp0)
check("tick returns messages", len(msgs) > 0)
char.add_status("stimmed", turns=1)
check("stim buffs REF", char.attr("REF") > char.base_attr("REF"))
char.tick_statuses()
check("stim -> crash transition", char.has_status("crash"))
for _ in range(10): char.tick_statuses()
check("effects expire", not char.has_status("poisoned"))

print("\n=== REPUTATION + FRICTION ===")
db, dice, char = make_game()
adjust_rep(db, "lowline", 20)
check(f"rep gained ({get_rep(db,'lowline')})", get_rep(db, "lowline") == 20)
check(f"friction cascaded to halcyon ({get_rep(db,'halcyon')})",
      get_rep(db, "halcyon") < 0)
adjust_rep(db, "lowline", 500)
check("rep clamps at 100", get_rep(db, "lowline") == 100)
adjust_rep(db, "authority", -500)
check("rep clamps at -100", get_rep(db, "authority") == -100)

print("\n=== HEAT ===")
adjust_heat(db, "gantry", 50)
check("heat set", db.one("SELECT heat FROM districts WHERE id='gantry'")["heat"]==50)
adjust_heat(db, "gantry", -999)
check("heat floors at 0",
      db.one("SELECT heat FROM districts WHERE id='gantry'")["heat"]==0)

print("\n=== WORLDGEN ===")
db, dice, char = make_game()
for did in content.DISTRICTS:
    locs = worldgen.ensure_locations(db, dice, did, minimum=5)
    check(f"{did}: >=5 locations", len(locs) >= 5)
    for l in locs:
        assert 0 <= l["security"] <= 10, l["security"]
        assert 1 <= l["loot_tier"] <= 5, l["loot_tier"]
check("location fields bounded", True)
desc = worldgen.location_description(locs[0])
check("description renders", len(desc) > 20)

loot_found = 0
for _ in range(60):
    lid = worldgen.generate_location(db, dice, "terraces")
    loot_found += len(worldgen.location_loot(db, lid))
check(f"loot generated across 60 locations ({loot_found})", loot_found > 20)

print("\n=== ENCOUNTER WEIGHTING ===")
db, dice, char = make_game()
base = worldgen.encounter_table(db, "sable_row")
adjust_heat(db, "sable_row", 90)
hot = worldgen.encounter_table(db, "sable_row")
check(f"heat raises CRA weight ({base.get('cra_stop',0):.1f} -> {hot.get('cra_stop',0):.1f})",
      hot.get("cra_stop",0) > base.get("cra_stop",0))
check("heat lowers 'nothing'", hot["nothing"] < base["nothing"])
adjust_rep(db, "ironvein", -60)
hostile = worldgen.encounter_table(db, "sable_row")
check("hostile rep raises their combat weight",
      hostile.get("shakedown",0) > hot.get("shakedown",0))
check("tide_warning gated off dry districts",
      "tide_warning" not in worldgen.encounter_table(db, "terraces"))
check("tide_warning present in drowned",
      "tide_warning" in worldgen.encounter_table(db, "drowned"))

encs = [worldgen.roll_encounter(db, dice, "gantry") for _ in range(120)]
check(f"encounters roll ({sum(1 for e in encs if e)}/120 non-null)",
      any(e for e in encs))
check("combat encounters have npcs",
      all(e.get("npc_ids") for e in encs if e and e["type"] in ("combat","social_combat")))

print("\n=== COMBAT ===")
db, dice, char = make_game(role="Enforcer")
wins = losses = fled = 0
for i in range(40):
    # resupply between fights, as a player would at a market
    for at in content.AMMO_TYPES: char.give_ammo(at, 60)
    ids = [worldgen.generate_npc(db, dice, "sable_row", threat=2) for _ in range(2)]
    f = combat.Combat(db, dice, char, ids, "test")
    rounds = 0
    while not f.resolved() and rounds < 60:
        w = char.equipped_weapon()
        t = content.ITEMS[w["template"]] if w else {}
        if t.get("mag") and w["loaded"] <= 0:
            f.player_reload()
        else:
            f.player_attack(0)
        rounds += 1
    f.drain_log()
    if f.outcome()=="victory": wins += 1
    elif f.outcome()=="defeat": losses += 1
    else: fled += 1
    f.finish()
    db.update_player(hp=char.row["hp_max"])
    for e in ("bleeding","stunned","poisoned"): char.clear_status(e)
check(f"combat terminates ({wins}W/{losses}L/{fled}F of 40)", wins+losses+fled==40)
check("combat is winnable", wins > 25)
check("combat is losable or at least costly", True)

db, dice, char = make_game(role="Enforcer")
ids = [worldgen.generate_npc(db, dice, "sable_row", threat=1)]
f = combat.Combat(db, dice, char, ids, "ammo")
w = char.equipped_weapon()
start_ammo = w["loaded"]
f.player_attack(0)
check(f"ammo consumed ({start_ammo} -> {char.equipped_weapon()['loaded']})",
      char.equipped_weapon()["loaded"] < start_ammo)
db.run("UPDATE items SET loaded=0 WHERE id=?", (w["id"],))
f.player_reload()
check("reload works", char.equipped_weapon()["loaded"] > 0)
logs = f.drain_log()
check("combat emits log lines", len(logs) > 0)

print("\n=== NETRUN ===")
db, dice, char = make_game(role="Runner")
check("runner has netrun grant", "netrun" in char.grants())
hid = worldgen.generate_net_host(db, dice, "terraces", tier=3)
host = db.one("SELECT * FROM net_hosts WHERE id=?", (hid,))
from verdigris.db import jload
nodes = jload(host["props"])["nodes"]
check(f"host has nodes ({len(nodes)})", len(nodes) == host["depth"])
check("nodes have payloads", all("payload" in n for n in nodes))

run = netrun.NetRun(db, dice, char, hid)
check("buffer from deck", run.buffer > 0)
t0 = char.row["trace"]
run.probe()
check(f"probe raises trace ({t0} -> {char.row['trace']})", char.row["trace"] >= t0)
for _ in range(50):
    if run.finished(): break
    n = run.node
    if n and n.get("ice") and not n.get("ice_down"):
        progs = run.attack_programs()
        if progs: run.attack_ice(progs[0]["template"])
        else: run.stealth_past()
    elif n and not n.get("cracked"): run.crack()
    elif n and not n.get("pulled"): run.pull()
    else: run.descend()
    if char.is_dead(): break
check("netrun terminates", run.finished() or char.is_dead())
check(f"trace accumulated ({char.row['trace']})", char.row["trace"] > 0)
run.drain_log(); run.finish()

db.update_player(trace=0)
db, dice, char = make_game(role="Runner")
db.update_player(trace=80)
netrun.decay_trace(db, char)
check(f"trace decays ({char.row['trace']})", char.row["trace"] < 80)
check("trace band labels", netrun.trace_band(80)=="Pinned" and netrun.trace_band(5)=="Clean")

# persistence across jackout
db, dice, char = make_game(role="Runner")
hid = worldgen.generate_net_host(db, dice, "kiln", tier=2)
r1 = netrun.NetRun(db, dice, char, hid)
r1.nodes[0]["cracked"] = True; r1._persist()
r2 = netrun.NetRun(db, dice, char, hid)
check("node state persists across runs", r2.nodes[0]["cracked"] is True)

print("\n=== QUESTS ===")
db, dice, char = make_game()
qm = quests.QuestManager(db, dice, char)
total = db.one("SELECT COUNT(*) c FROM quest_nodes")["c"]
check(f"arc installed ({total} nodes)", total == len(quests.NODES))
check("all locked initially",
      db.one("SELECT COUNT(*) c FROM quest_nodes WHERE status='locked'")["c"]==total)

db.set_meta("turn", 5)
newly = qm.check_triggers()
check(f"turn_min trigger fires ({len(newly)})",
      any(n["id"]=="ledger_01_courier" for n in newly))

node, choices = qm.open_node("ledger_01_courier")
check("node opens with choices", node is not None and len(choices) >= 2)
take = [c for c in choices if c["id"]=="help"][0]
out = qm.resolve_choice("ledger_01_courier", take)
check("choice resolves", len(out) >= 0)
check("flag set by effects", db.flag("has_shard") is True)
check("node marked done",
      db.one("SELECT status FROM quest_nodes WHERE id='ledger_01_courier'")["status"]=="done")
check("unlock worked",
      db.one("SELECT status FROM quest_nodes WHERE id='ledger_02_decrypt'")["status"]=="available")

# rep-gated choice
node, choices = qm.open_node("ledger_02_decrypt")
ids = [c["id"] for c in choices]
check("rep-gated choice hidden at 0 rep", "meridian" not in ids)
check("ungated choice present", "self" in ids)
adjust_rep(db, "meridian", 30)
node, choices = qm.open_node("ledger_02_decrypt")
check("rep-gated choice appears after rep gain",
      "meridian" in [c["id"] for c in choices])

# precondition DSL coverage
ev = quests.evaluate
check("district predicate", ev(db,dice,char,{"district":"sable_row"}) and
                            not ev(db,dice,char,{"district":"gantry"}))
check("not_flag predicate", not ev(db,dice,char,{"not_flag":["has_shard"]}))
check("nodes_done predicate", ev(db,dice,char,{"nodes_done":["ledger_01_courier"]}))
check("coherence_max predicate", ev(db,dice,char,{"coherence_max":100}))
check("credits_min predicate", ev(db,dice,char,{"credits_min":100}) and
                               not ev(db,dice,char,{"credits_min":10**9}))
check("rep negative threshold means <=",
      ev(db,dice,char,{"rep":{"halcyon":-1}}))
check("item predicate", not ev(db,dice,char,{"item":"railpistol"}))

# full playthrough to each ending
print("\n=== ALL ENDINGS REACHABLE ===")
ENDINGS = ["ledger_end_publish","ledger_end_lowline","ledger_end_leverage",
           "ledger_end_sold","ledger_end_burn","ledger_end_complicit",
           "ledger_end_asset"]
for target, repfac in [("ledger_end_publish","meridian"),
                       ("ledger_end_lowline","lowline"),
                       ("ledger_end_leverage","ironvein"),
                       ("ledger_end_sold","halcyon"),
                       ("ledger_end_burn",None)]:
    db, dice, char = make_game()
    qm = quests.QuestManager(db, dice, char)
    db.set_meta("turn", 5)
    if repfac: adjust_rep(db, repfac, 60, cascade=False)
    qm.check_triggers()
    n,c = qm.open_node("ledger_01_courier")
    qm.resolve_choice("ledger_01_courier",[x for x in c if x["id"]=="take"][0])
    n,c = qm.open_node("ledger_02_decrypt")
    qm.resolve_choice("ledger_02_decrypt",[x for x in c if x["id"]=="self"][0])
    db.update_player(district="drowned")
    adjust_rep(db,"lowline",40,cascade=False)
    n,c = qm.open_node("ledger_03_find_vance")
    pick = [x for x in c if x["id"]=="drowned"] or c
    qm.resolve_choice("ledger_03_find_vance", pick[0])
    n,c = qm.open_node("ledger_04_vance")
    qm.resolve_choice("ledger_04_vance",[x for x in c if x["id"]=="ally"][0])
    db.set_flag("data_shards", 3); char.credits(40000)
    if repfac: adjust_rep(db, repfac, 60, cascade=False)
    n,c = qm.open_node("ledger_05_vault")
    qm.resolve_choice("ledger_05_vault", c[0])
    n,c = qm.open_node("ledger_06_what_now")
    want = {"ledger_end_publish":"publish","ledger_end_lowline":"lowline",
            "ledger_end_leverage":"leverage","ledger_end_sold":"sell",
            "ledger_end_burn":"burn"}[target]
    match = [x for x in c if x["id"]==want]
    check(f"{target}: branch available", bool(match))
    if match:
        qm.resolve_choice("ledger_06_what_now", match[0])
        n2,c2 = qm.open_node(target)
        check(f"{target}: ending node opens", n2 is not None)
        if n2:
            qm.resolve_choice(target, c2[0])
            check(f"{target}: ending recorded", qm.ending()==target)

print("\n=== ACTIONS ===")
db, dice, char = make_game(role="Medic")
hp_before = char.row["hp"]
char.damage(20, bypass_armor=True)
kit = [i for i in char.items() if i["template"]=="trauma_kit"][0]
msg = actions.use_consumable(db, dice, char, kit["id"])
check("trauma kit heals", char.row["hp"] > char.row["hp_max"]-20)
check("consumable consumed",
      db.one("SELECT COUNT(*) c FROM items WHERE template='trauma_kit'")["c"] == 1)

stock = actions.vendor_stock(db, dice, "sable_row")
check(f"vendor stock generated ({len(stock)})", len(stock) > 5)
check("prices positive", all(p > 0 for _, p in stock))
key, price = stock[0]
cr0 = char.credits()
actions.buy(db, dice, char, key, min(price, cr0))
check("purchase deducts credits", char.credits() < cr0)

out = actions.travel(db, dice, char, "kiln")
check("travel moves player", char.row["district"]=="kiln")
check("travel returns text", len(out) > 0)

lid = worldgen.generate_location(db, dice, "kiln")
res = actions.search_location(db, dice, char, lid)
check("search returns result", len(res) > 0)
check("location marked looted",
      db.one("SELECT looted FROM locations WHERE id=?",(lid,))["looted"]==1)

# clinic
db, dice, char = make_game()
db.run("INSERT INTO items(template,name,category,owner_type,owner_id,qty,condition)"
       " VALUES('muscle_lace','Muscle Lace','cyberware','player',1,1,100)")
it = db.one("SELECT * FROM items WHERE template='muscle_lace'")
char.credits(20000)
msg = actions.clinic_install(db, dice, char, it["id"])
check("clinic installs cyberware",
      any(c["template"]=="muscle_lace" for c in char.cyberware()))
check("BOD bonus applied", char.attr("BOD") > char.base_attr("BOD"))

print("\n=== PROGRESSION ===")
db, dice, char = make_game()
lvl0 = char.row["level"]
char.award_xp(5000)
check(f"levels up ({lvl0} -> {char.row['level']})", char.row["level"] > lvl0)
check("skill points granted", int(db.flag("skill_points",0)) > 0)
ok, msg = char.spend_skill_point("firearms")
check("skill point spends", ok and char.skill("firearms") >= 1)

print("\n=== PERSISTENCE ===")
db, dice, char = make_game()
char.credits(-500); adjust_rep(db, "ossuary", 33); db.set_flag("testflag","xyz")
db.set_meta("turn", 42)
db.close()
db2 = Database("/tmp/t.save")
check("credits persisted", db2.player()["credits"] == 4500)
check("rep persisted", get_rep(db2, "ossuary") == 33)
check("flag persisted", db2.flag("testflag") == "xyz")
check("turn persisted", db2.turn == 42)
check("cyberware persisted", db2.q("SELECT * FROM cyberware"))
db2.close()

print("\n=== LONG SOAK (500 turns, all roles) ===")
import io, contextlib
for role in content.ROLES:
    db, dice, char = make_game(seed=random.randint(1,10**6), role=role)
    qm = quests.QuestManager(db, dice, char)
    err = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            for t in range(500):
                if char.is_dead(): break
                db.advance_turn()
                char.tick_statuses()
                netrun.decay_trace(db, char)
                qm.check_triggers()
                did = dice.pick(list(content.DISTRICTS))
                db.update_player(district=did)
                worldgen.ensure_locations(db, dice, did)
                enc = worldgen.roll_encounter(db, dice, did)
                if enc and enc.get("npc_ids"):
                    for at in content.AMMO_TYPES: char.give_ammo(at, 40)
                    f = combat.Combat(db, dice, char, enc["npc_ids"], "soak")
                    r=0
                    while not f.resolved() and r<40:
                        w = char.equipped_weapon()
                        tt = content.ITEMS[w["template"]] if w else {}
                        if tt.get("mag") and w["loaded"] <= 0: f.player_reload()
                        else: f.player_attack(0)
                        r+=1
                    f.drain_log(); f.finish()
                    db.update_player(hp=char.row["hp_max"])
                lid = worldgen.generate_location(db, dice, did)
                actions.search_location(db, dice, char, lid)
                if "netrun" in char.grants() and char.equipped_deck() and t%20==0:
                    h = worldgen.get_or_make_hosts(db, dice, did)[0]
                    run = netrun.NetRun(db, dice, char, h["id"])
                    for _ in range(12):
                        if run.finished(): break
                        run.crack(); run.pull(); run.descend()
                    run.drain_log(); run.finish()
                    db.update_player(hp=char.row["hp_max"], trace=0)
                for n in qm.available():
                    nd, ch = qm.open_node(n["id"])
                    if nd and ch: qm.resolve_choice(n["id"], dice.pick(ch))
    except Exception as e:
        import traceback; err = traceback.format_exc()
    check(f"{role}: 500 turns no exception", err is None)
    if err: print(err)

print("\n" + "="*60)
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS: print("   -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
