"""Wuerfelpool-Rechner.

Dieses Modul berechnet ausschliesslich, WIE VIELE Wuerfel geworfen werden
muessen. Es wuerfelt bewusst nicht: gewuerfelt wird am Spieltisch.
Deshalb enthaelt dieses Modul keinerlei Zufallsfunktionen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import npc_engine as engine

# Umlaute als Escape, damit dieses Modul reines ASCII bleibt.
UNGEUEBT = "unge\u00fcbt"  # ungeuebt

# Attributskuerzel aus Fertigkeiten.csv -> Attributsname im Tool.
ATTRIBUTE_BY_CODE: dict[str, str] = {
    "BOD": "Konstitution",
    "AGI": "Geschick",
    "REA": "Reaktion",
    "STR": engine.STAERKE,
    "WIL": "Willenskraft",
    "LOG": "Logik",
    "INT": "Intuition",
    "CHA": "Charisma",
    "MAG": "Magie",
    "RES": "Resonanz",
}

# Reserve, falls Fertigkeiten.csv fehlt: die Fertigkeiten aus NPC_Grunddaten.
FALLBACK_SKILL_ATTRIBUTES: dict[str, str] = {
    "Akrobatik": "Geschick",
    "Antimagie": "Magie",
    "Gewehre": "Geschick",
    "Klingenwaffen": "Geschick",
    "Kn\u00fcppel": "Geschick",  # Knueppel
    "Pistolen": "Geschick",
    "Projektilwaffen": "Geschick",
    "Schleichen": "Geschick",
    "Schnellfeuerwaffen": "Geschick",
    "Schwere Waffen": "Geschick",
    "Schwimmen": engine.STAERKE,
    "Spruchzauberei": "Magie",
    "Herbeirufen": "Magie",
    "Waffenloser Kampf": "Geschick",
    "Wahrnehmung": "Intuition",
    "Wurfwaffen": "Geschick",
    "Exotische Nahkampfwaffe": "Geschick",
    "Exotische Fernkampfwaffe": "Geschick",
}

# Abzug fuer Proben auf eine Fertigkeit, die der NPC nicht besitzt.
DEFAULTING_PENALTY = -1

# Jeder volle dritte Schadenspunkt kostet einen Wuerfel.
BOXES_PER_WOUND = 3

# Ableitung der Kampffertigkeit aus der Spalte 'Typ' der Waffen-Datenbank.
# Die Reihenfolge entscheidet: 'Maschinenpistole' muss vor 'Pistole' stehen.
WEAPON_SKILL_RULES: tuple[tuple[str, str], ...] = (
    ("maschinengewehr", "Schwere Waffen"),
    ("sturmkanone", "Schwere Waffen"),
    ("raketenwerfer", "Schwere Waffen"),
    ("granat", "Schwere Waffen"),
    ("torpedo", "Schwere Waffen"),
    ("maschinenpistole", "Schnellfeuerwaffen"),
    ("sturmgewehr", "Schnellfeuerwaffen"),
    ("scharfsch", "Gewehre"),
    ("sportgewehr", "Gewehre"),
    ("schrotflinte", "Gewehre"),
    ("pistole", "Pistolen"),
    ("taser", "Pistolen"),
    ("projektilwaffen", "Projektilwaffen"),
    ("wurfwaffen", "Wurfwaffen"),
    ("klingenwaffen", "Klingenwaffen"),
    ("kn\u00fcppel", "Kn\u00fcppel"),  # Knueppel
    ("nahkampf", "Exotische Nahkampfwaffe"),
    ("laserwaffen", "Exotische Fernkampfwaffe"),
    ("flammenwerfer", "Exotische Fernkampfwaffe"),
    ("spezielle waffen", "Exotische Fernkampfwaffe"),
    ("exot", "Exotische Fernkampfwaffe"),
)

FALLBACK_WEAPON_SKILL = "Waffenloser Kampf"


@dataclass(frozen=True)
class DicePool:
    """Ein fertiger Wuerfelpool samt Herleitung - ohne Wurf."""

    label: str
    components: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    modifier: int = 0
    wounds: int = 0
    note: str = ""
    limit: str | None = None

    @property
    def base(self) -> int:
        return sum(value for _, value in self.components)

    @property
    def total(self) -> int:
        return max(0, self.base + self.modifier + self.wounds)

    @property
    def formula(self) -> str:
        parts = " + ".join(f"{label} {value}" for label, value in self.components)
        if self.wounds:
            parts += f" {self.wounds:+d} (Wundabzug)"
        if self.modifier:
            parts += f" {self.modifier:+d} (Situation)"
        return parts

    @property
    def text(self) -> str:
        """Zeile fuer die Anzeige, z. B. '9 W6 (Intuition 4 + Wahrnehmung 5)'."""
        line = f"{self.total} W6 ({self.formula})"
        if self.note:
            line += f" - {self.note}"
        return line

    @property
    def dashboard_text(self) -> str:
        """Kompakte Dashboard-Zeile: Wuerfel, optional Limit und aktive Abzuege."""
        line = f"{self.total} W6"
        if self.limit is not None:
            line += f" [{self.limit}]"
        if self.wounds:
            line += f" ({self.wounds} Wunden)"
        if self.modifier:
            line += f" ({self.modifier:+d} Situation)"
        if self.note:
            line += f" - {self.note}"
        return line

    def with_modifier(self, modifier: int) -> "DicePool":
        return DicePool(
            self.label, self.components, modifier, self.wounds, self.note, self.limit
        )

    def with_wounds(self, wounds: int) -> "DicePool":
        return DicePool(
            self.label, self.components, self.modifier, wounds, self.note, self.limit
        )


def wound_modifier(damage: int) -> int:
    """Wundabzug: -1 Wuerfel je drei erlittenen Schadensboxen (3-5 = -1, 6-8 = -2)."""
    return -(max(0, int(damage)) // BOXES_PER_WOUND)


def build_skill_attribute_map(skill_db: pd.DataFrame | None = None) -> dict[str, str]:
    """Ordnet jeder Fertigkeit ihr Attribut zu, bevorzugt aus Fertigkeiten.csv."""
    mapping = dict(FALLBACK_SKILL_ATTRIBUTES)
    if skill_db is None or "attribute" not in skill_db.columns:
        return mapping

    for name, code in skill_db["attribute"].items():
        attribute = ATTRIBUTE_BY_CODE.get(str(code).strip().upper())
        if attribute:
            mapping[str(name)] = attribute
    return mapping


def attribute_value(npc: engine.BaseNPC, attribute: str) -> int:
    """Liest ein Attribut; Magie und Resonanz liegen ausserhalb der acht Grundwerte."""
    if attribute in npc.attributes:
        return npc.attributes[attribute]
    if attribute == "Magie":
        return engine.to_int(getattr(npc, "magic", None) or npc.row.get("Magie"))
    if attribute == "Resonanz":
        return engine.to_int(npc.row.get("Resonanz"))
    return 0


def skill_pool(
    npc: engine.BaseNPC,
    skill: str,
    skill_map: dict[str, str] | None = None,
    modifier: int = 0,
) -> DicePool:
    """Attribut + Fertigkeit. Fehlt die Fertigkeit, gilt der Abzug fuer Ungeuebte."""
    skill_map = skill_map or FALLBACK_SKILL_ATTRIBUTES
    attribute = skill_map.get(skill, "Intuition")
    rating = engine.to_int(getattr(npc, "skills", {}).get(skill))

    components = ((attribute, attribute_value(npc, attribute)),)
    if rating > 0:
        return DicePool(skill, components + ((skill, rating),), modifier)

    return DicePool(
        skill, components + ((UNGEUEBT, DEFAULTING_PENALTY),), modifier
    )


def weapon_skill(weapon_type: str) -> str:
    """Leitet die Kampffertigkeit aus dem Waffentyp ab."""
    text = str(weapon_type).lower()
    for keyword, skill in WEAPON_SKILL_RULES:
        if keyword in text:
            return skill
    return FALLBACK_WEAPON_SKILL


def attack_pool(
    npc: engine.BaseNPC,
    weapon: engine.Weapon,
    skill_map: dict[str, str] | None = None,
    modifier: int = 0,
) -> DicePool:
    """Angriffspool einer konkreten Waffe, z. B. 'Geschick 5 + Klingenwaffen 6'."""
    skill = weapon_skill(weapon.weapon_type)
    if isinstance(npc, engine.Spirit):
        attribute = (skill_map or FALLBACK_SKILL_ATTRIBUTES).get(skill, "Geschick")
        pool = spirit_skill_pool(npc, skill, attribute, modifier)
    else:
        pool = skill_pool(npc, skill, skill_map, modifier)
    limit = weapon.accuracy if weapon.accuracy != "-" else None
    return DicePool(f"Angriff mit {weapon.name}", pool.components, modifier, limit=limit)


def defense_pool(npc: engine.BaseNPC, modifier: int = 0) -> DicePool:
    """Ausweichen gegen Nahkampf- und Fernkampfangriffe."""
    return DicePool(
        "Verteidigung",
        (
            ("Reaktion", npc.attributes["Reaktion"]),
            ("Intuition", npc.attributes["Intuition"]),
        ),
        modifier,
    )


def damage_resistance_pool(npc: engine.BaseNPC, modifier: int = 0) -> DicePool:
    """Schadenswiderstand: Konstitution + Panzerung."""
    armor = engine.to_int(getattr(npc, "armor", 0))
    return DicePool(
        "Schadenswiderstand",
        (
            ("Konstitution", npc.attributes["Konstitution"]),
            ("Panzerung", armor),
        ),
        modifier,
    )


def composure_pool(npc: engine.BaseNPC, modifier: int = 0) -> DicePool:
    """Selbstbeherrschung: Willenskraft + Charisma."""
    return DicePool(
        "Selbstbeherrschung",
        (
            ("Willenskraft", npc.attributes["Willenskraft"]),
            ("Charisma", npc.attributes["Charisma"]),
        ),
        modifier,
    )


def drain_pool(npc: engine.BaseNPC, modifier: int = 0) -> DicePool:
    """Entzug widerstehen: Willenskraft + Logik (Magier)."""
    return DicePool(
        "Entzug widerstehen",
        (
            ("Willenskraft", npc.attributes["Willenskraft"]),
            ("Logik", npc.attributes["Logik"]),
        ),
        modifier,
    )


def spirit_skill_pool(
    npc: engine.Spirit, label: str, attribute: str, modifier: int = 0
) -> DicePool:
    """Geister beherrschen ihre Fertigkeiten in Hoehe der Kraftstufe."""
    return DicePool(
        label,
        ((attribute, attribute_value(npc, attribute)), ("Kraftstufe", npc.force)),
        modifier,
    )


def _mundane_pools(
    npc: engine.MundaneNPC, skill_map: dict[str, str] | None, modifier: int
) -> list[DicePool]:
    pools = [
        defense_pool(npc, modifier),
        damage_resistance_pool(npc, modifier),
        composure_pool(npc, modifier),
    ]
    trained = sorted(
        (skill for skill, rating in npc.skills.items() if rating > 0),
        key=lambda skill: npc.skills[skill],
        reverse=True,
    )
    pools.extend(skill_pool(npc, skill, skill_map, modifier) for skill in trained)
    return pools


def _magician_pools(
    npc: engine.MagicianNPC, skill_map: dict[str, str] | None, modifier: int
) -> list[DicePool]:
    pools = _mundane_pools(npc, skill_map, modifier)
    # Die magischen Proben stehen immer vorn, auch bei Stufe 0.
    magic_pools = [
        skill_pool(npc, skill, skill_map, modifier) for skill in engine.MAGIC_SKILLS
    ]
    magic_labels = {pool.label for pool in magic_pools}
    rest = [pool for pool in pools[2:] if pool.label not in magic_labels]
    return pools[:2] + [drain_pool(npc, modifier)] + magic_pools + rest


def _spirit_pools(npc: engine.Spirit, modifier: int) -> list[DicePool]:
    armor = 2 * npc.force
    return [
        defense_pool(npc, modifier),
        DicePool(
            "Schadenswiderstand",
            (
                ("Konstitution", npc.attributes["Konstitution"]),
                ("Panzerung", armor),
            ),
            modifier,
            note=f"Immunitaet gegen normale Waffen (2 x F = {armor})",
        ),
        spirit_skill_pool(npc, "Waffenloser Kampf", "Geschick", modifier),
        spirit_skill_pool(npc, "Wahrnehmung", "Intuition", modifier),
        spirit_skill_pool(npc, "Astralkampf", "Willenskraft", modifier),
        spirit_skill_pool(npc, "Schleichen", "Geschick", modifier),
        composure_pool(npc, modifier),
    ]


def _critter_pools(npc: engine.Critter, modifier: int) -> list[DicePool]:
    # Die Critter-Datenbank enthaelt keine Fertigkeiten, daher Proben ungeuebt.
    pools = [defense_pool(npc, modifier), damage_resistance_pool(npc, modifier)]
    for label, attribute in (
        ("Wahrnehmung", "Intuition"),
        ("Waffenloser Kampf", "Geschick"),
        ("Schleichen", "Geschick"),
    ):
        pools.append(
            DicePool(
                label,
                (
                    (attribute, attribute_value(npc, attribute)),
                    (UNGEUEBT, DEFAULTING_PENALTY),
                ),
                modifier,
            )
        )
    pools.append(composure_pool(npc, modifier))
    return pools


def standard_pools(
    npc: engine.BaseNPC,
    skill_map: dict[str, str] | None = None,
    modifier: int = 0,
    wounds: int = 0,
) -> list[DicePool]:
    """Die wichtigsten Pools des jeweiligen Archetyps, bereits fertig gerechnet."""
    if isinstance(npc, engine.Spirit):
        pools = _spirit_pools(npc, modifier)
    elif isinstance(npc, engine.Critter):
        pools = _critter_pools(npc, modifier)
    elif isinstance(npc, engine.MagicianNPC):
        pools = _magician_pools(npc, skill_map, modifier)
    elif isinstance(npc, engine.MundaneNPC):
        pools = _mundane_pools(npc, skill_map, modifier)
    else:
        pools = [defense_pool(npc, modifier)]

    # Angriffe mit ausgeruesteten Waffen stehen ganz oben.
    attacks = [
        attack_pool(npc, weapon, skill_map, modifier) for weapon in npc.weapons
    ]
    pools = attacks + pools

    if wounds:
        pools = [pool.with_wounds(wounds) for pool in pools]
    return pools


def initiative_line(npc: engine.BaseNPC, modifier: int = 0, wounds: int = 0) -> str:
    """Initiative als reiner Text - die Wuerfel wirft der Spielleiter selbst."""
    base = max(0, npc.initiative_base + modifier + wounds)
    line = f"{base} + {npc.initiative_dice}W6"

    notes = []
    if wounds:
        notes.append(f"{wounds:+d} Wundabzug")
    if modifier:
        notes.append(f"{modifier:+d} Situation")
    if notes:
        line += " (inkl. " + ", ".join(notes) + ")"
    return line


def pool_table(pools: list[DicePool]) -> pd.DataFrame:
    """Pools als Tabelle fuer die kompakte Anzeige."""
    return pd.DataFrame(
        {
            "Probe": [pool.label for pool in pools],
            "W6": [pool.total for pool in pools],
            "Herleitung": [pool.formula for pool in pools],
        }
    )
