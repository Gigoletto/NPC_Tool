from src import data_loader
from src import npc_engine as engine
from src import pool_calculator as pools

grund = data_loader.load_database("NPC_Grunddaten")
skills_db = data_loader.load_database("Fertigkeiten")
row = grund.iloc[0]
npc_skills = engine.skill_names_from_row(row)
csv_skills = [str(name) for name in skills_db.index]
mapping = pools.build_skill_attribute_map(skills_db)

print("=== NPC ohne Eintrag in Fertigkeiten.csv ===")
for name in npc_skills:
    if name not in skills_db.index:
        attr = mapping.get(name, "FEHLT->" + mapping.get(name, "Intuition-Default"))
        print(f"  {name!r} -> {mapping.get(name, 'DEFAULT Intuition')}")

print("=== Fertigkeiten.csv ohne Spalte in NPC_Grunddaten ===")
npc_set = set(npc_skills)
for name in csv_skills:
    if name not in npc_set:
        print(f"  {name!r} ({skills_db.loc[name, 'attribute']})")

print("=== Alle NPC-Fertigkeiten mit Attribut ===")
for name in npc_skills:
    code = ""
    if name in skills_db.index:
        code = str(skills_db.loc[name, "attribute"])
    print(f"  {name}: {mapping.get(name, 'MISSING')} (csv={code or '-'})")
