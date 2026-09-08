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
    "Astralkampf": "Willenskraft",
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
    engine.BESCHWOEREN: "Magie",
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

ASTRAL_COMBAT_SKILL = "Astralkampf"

MAGIC_ATTACK_SKILLS = ("Spruchzauberei", engine.BESCHWOEREN, ASTRAL_COMBAT_SKILL)

CRITTER_SKILL_NOTE = (
    "Hausregel: Critter ohne Fertigkeitswerte, Probe = Attribut x 2"
)

# Kuerzel der natuerlichen Limits auf den Karten.
LIMIT_PHYSICAL = "K"
LIMIT_MENTAL = "G"
LIMIT_SOCIAL = "S"
LIMIT_SPELL_FORCE = "KS"
LIMIT_SPIRIT_FORCE = "KS"

# Pools ohne Limit (kein Erfolgslimit nach SR5).
NO_LIMIT_LABELS = {"Verteidigung", "Schadenswiderstand", "Entzug widerstehen"}

# Fertigkeiten, deren Limit nicht aus der CSV-Kategorie folgt.
SKILL_LIMIT_OVERRIDES: dict[str, str] = {
    "Wahrnehmung": LIMIT_MENTAL,
    "Spruchzauberei": LIMIT_SPELL_FORCE,
    "Ritualzauberei": LIMIT_SPELL_FORCE,
    engine.BESCHWOEREN: LIMIT_SPIRIT_FORCE,
    "Astralkampf": LIMIT_MENTAL,
}

FALLBACK_SKILL_LIMITS: dict[str, str] = {
    "Akrobatik": LIMIT_PHYSICAL,
    "Antimagie": LIMIT_MENTAL,
    "Gewehre": LIMIT_PHYSICAL,
    "Klingenwaffen": LIMIT_PHYSICAL,
    "Kn\u00fcppel": LIMIT_PHYSICAL,
    "Pistolen": LIMIT_PHYSICAL,
    "Projektilwaffen": LIMIT_PHYSICAL,
    "Schleichen": LIMIT_PHYSICAL,
    "Schnellfeuerwaffen": LIMIT_PHYSICAL,
    "Schwere Waffen": LIMIT_PHYSICAL,
    "Schwimmen": LIMIT_PHYSICAL,
    "Spruchzauberei": LIMIT_SPELL_FORCE,
    engine.BESCHWOEREN: LIMIT_SPIRIT_FORCE,
    "Waffenloser Kampf": LIMIT_PHYSICAL,
    "Wahrnehmung": LIMIT_MENTAL,
    "Wurfwaffen": LIMIT_PHYSICAL,
    "Exotische Nahkampfwaffe": LIMIT_PHYSICAL,
    "Exotische Fernkampfwaffe": LIMIT_PHYSICAL,
    ASTRAL_COMBAT_SKILL: LIMIT_MENTAL,
    "Selbstbeherrschung": LIMIT_SOCIAL,
}


@dataclass(frozen=True)
class DicePool:
    """Ein fertiger Wuerfelpool samt Herleitung - ohne Wurf."""

    label: str
    components: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    modifier: int = 0
    wounds: int = 0
    note: str = ""
    limit: str | None = None
    ignore_wounds: bool = False
    ignore_situation: bool = False

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
        if self.limit is not None:
            line += f" [{self.limit}]"
        if self.note:
            line += f" - {self.note}"
        return line

    @property
    def dashboard_text(self) -> str:
        """Kompakte Kartenzeile: nur der finale Pool, optional das Limit."""
        line = f"{self.total} W6"
        if self.limit is not None:
            line += f" [{self.limit}]"
        return line

    def with_modifier(self, modifier: int) -> "DicePool":
        if self.ignore_situation:
            return self
        return DicePool(
            self.label,
            self.components,
            modifier,
            self.wounds,
            self.note,
            self.limit,
            self.ignore_wounds,
            self.ignore_situation,
        )

    def with_wounds(self, wounds: int) -> "DicePool":
        if self.ignore_wounds:
            return self
        return DicePool(
            self.label,
            self.components,
            self.modifier,
            wounds,
            self.note,
            self.limit,
            self.ignore_wounds,
            self.ignore_situation,
        )

    def with_limit(self, limit: str | None) -> "DicePool":
        return DicePool(
            self.label,
            self.components,
            self.modifier,
            self.wounds,
            self.note,
            limit,
            self.ignore_wounds,
            self.ignore_situation,
        )


def wound_modifier(damage: int) -> int:
    """Wundabzug: -1 Wuerfel je drei erlittenen Schadensboxen (3-5 = -1, 6-8 = -2)."""
    return -(max(0, int(damage)) // BOXES_PER_WOUND)


def limit_kind_from_category(category: object) -> str:
    """Ordnet eine Fertigkeitskategorie dem natuerlichen Limit zu."""
    text = (
        str(category)
        .lower()
        .replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
    )
    if "sozial" in text:
        return LIMIT_SOCIAL
    if "kampf" in text or "koerperlich" in text or "fahrzeug" in text:
        return LIMIT_PHYSICAL
    return LIMIT_MENTAL


def build_skill_limit_map(skill_db: pd.DataFrame | None = None) -> dict[str, str]:
    """Limit-Art je Fertigkeit, inkl. Ausnahmen wie Wahrnehmung = geistig."""
    mapping = dict(FALLBACK_SKILL_LIMITS)
    if skill_db is None or "Kategorie" not in skill_db.columns:
        mapping.update(SKILL_LIMIT_OVERRIDES)
        return mapping

    for name, category in skill_db["Kategorie"].items():
        skill = str(name)
        mapping[skill] = SKILL_LIMIT_OVERRIDES.get(
            skill, limit_kind_from_category(category)
        )
    mapping.update(SKILL_LIMIT_OVERRIDES)
    return mapping


def inherent_limit_text(
    npc: engine.BaseNPC,
    kind: str,
    magic_force: int | None = None,
) -> str | None:
    """Text in eckigen Klammern: Zahl, bei Zauber und Beschwoeren nur KS."""
    del magic_force
    if kind == LIMIT_PHYSICAL:
        return str(npc.physical_limit())
    if kind == LIMIT_MENTAL:
        return str(npc.mental_limit())
    if kind == LIMIT_SOCIAL:
        return str(npc.social_limit())
    if kind == LIMIT_SPELL_FORCE:
        return LIMIT_SPELL_FORCE
    if kind == LIMIT_SPIRIT_FORCE:
        return LIMIT_SPIRIT_FORCE
    return None


def assign_pool_limit(
    pool: DicePool,
    npc: engine.BaseNPC,
    skill_limits: dict[str, str] | None = None,
    magic_force: int | None = None,
) -> DicePool:
    """Setzt das Limit, sofern die Probe eines hat und noch keins steht."""
    if pool.limit is not None or pool.label in NO_LIMIT_LABELS:
        return pool

    skill_limits = skill_limits or FALLBACK_SKILL_LIMITS
    kind = skill_limits.get(pool.label)
    if pool.label == "Angriff (waffenlos)":
        kind = LIMIT_PHYSICAL
    elif pool.label == "Selbstbeherrschung":
        kind = LIMIT_SOCIAL
    if kind is None:
        return pool

    text = inherent_limit_text(npc, kind, magic_force)
    return pool.with_limit(text) if text else pool


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
    note = f"Schaden {weapon.damage} \u00b7 DK {weapon.ap}"
    return DicePool(
        f"Angriff mit {weapon.name}",
        pool.components,
        modifier,
        note=note,
        limit=limit,
    )


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
        ignore_wounds=True,
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
    """Entzug widerstehen: WIL+LOG (Hermetiker) oder WIL+CHA (Schamane)."""
    del modifier  # Deckung/Sicht gehoert nicht auf den Entzug.
    second = "Logik"
    if isinstance(npc, engine.MagicianNPC):
        second = npc.drain_attribute
    return DicePool(
        "Entzug widerstehen",
        (
            ("Willenskraft", npc.attributes["Willenskraft"]),
            (second, npc.attributes[second]),
        ),
        note="Situation wirkt nicht auf Entzug",
        ignore_situation=True,
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


def spirit_unarmed_attack_pool(npc: engine.Spirit, modifier: int = 0) -> DicePool:
    """GES + Waffenloser Kampf (Kraftstufe), Schaden geistig."""
    return DicePool(
        "Angriff (waffenlos)",
        (
            ("Geschick", attribute_value(npc, "Geschick")),
            ("Waffenloser Kampf", npc.force),
        ),
        modifier,
        note=f"Schaden {npc.unarmed_damage}G",
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
    """Wie mundan, zusaetzlich Entzug zwischen Verteidigung und Fertigkeiten."""
    pools = _mundane_pools(npc, skill_map, modifier)
    return pools[:2] + [drain_pool(npc, modifier)] + pools[2:]


def critter_attribute_pool(
    npc: engine.Critter, label: str, attribute: str, modifier: int = 0
) -> DicePool:
    """Hausregel: Critter-Probe als Attribut + Attribut (Attribut x 2)."""
    value = attribute_value(npc, attribute)
    return DicePool(
        label,
        ((attribute, value), (label, value)),
        modifier,
    )


def spirit_damage_resistance_pool(
    npc: engine.Spirit, modifier: int = 0
) -> DicePool:
    """Schadenswiderstand: Immunitaet 2xF, hoehere getragene Panzerung gewinnt."""
    immunity = engine.spirit_hardened_armor(npc.force)
    armor = engine.to_int(getattr(npc, "armor", 0))
    if armor > immunity:
        note = f"getragene Panzerung {armor} (Immunitaet 2 x F = {immunity})"
    else:
        note = f"Immunitaet gegen normale Waffen (2 x F = {immunity})"
        armor = max(armor, immunity)
    return DicePool(
        "Schadenswiderstand",
        (
            ("Konstitution", npc.attributes["Konstitution"]),
            ("Panzerung", armor),
        ),
        modifier,
        note=note,
        ignore_wounds=True,
    )


def _spirit_pools(npc: engine.Spirit, modifier: int) -> list[DicePool]:
    return [
        defense_pool(npc, modifier),
        spirit_damage_resistance_pool(npc, modifier),
        spirit_skill_pool(npc, "Wahrnehmung", "Intuition", modifier),
        spirit_skill_pool(npc, "Astralkampf", "Willenskraft", modifier),
        spirit_skill_pool(npc, "Schleichen", "Geschick", modifier),
        composure_pool(npc, modifier),
    ]


def _critter_pools(npc: engine.Critter, modifier: int) -> list[DicePool]:
    # Keine Fertigkeitswerte in der CSV: Hausregel Attribut x 2.
    pools = [defense_pool(npc, modifier), damage_resistance_pool(npc, modifier)]
    for label, attribute in (
        ("Wahrnehmung", "Intuition"),
        ("Waffenloser Kampf", "Geschick"),
        ("Schleichen", "Geschick"),
    ):
        pools.append(critter_attribute_pool(npc, label, attribute, modifier))
    pools.append(composure_pool(npc, modifier))
    return pools


def standard_pools(
    npc: engine.BaseNPC,
    skill_map: dict[str, str] | None = None,
    modifier: int = 0,
    wounds: int = 0,
    magic_force: int | None = None,
    skill_limits: dict[str, str] | None = None,
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

    # Waffenangriffe und angeborene Angriffe stehen ganz oben.
    attacks = [
        attack_pool(npc, weapon, skill_map, modifier) for weapon in npc.weapons
    ]
    if isinstance(npc, engine.Spirit):
        attacks.append(spirit_unarmed_attack_pool(npc, modifier))
    pools = [
        assign_pool_limit(pool, npc, skill_limits, magic_force)
        for pool in attacks + pools
    ]

    if wounds:
        pools = [pool.with_wounds(wounds) for pool in pools]
    return pools


def initiative_total(npc: engine.BaseNPC, modifier: int = 0, wounds: int = 0) -> int:
    """Finale Initiative-Basis inklusive Situation und Wundabzug."""
    return max(0, npc.initiative_base + modifier + wounds)


def initiative_line(npc: engine.BaseNPC, modifier: int = 0, wounds: int = 0) -> str:
    """Initiative als reiner Text - die Wuerfel wirft der Spielleiter selbst."""
    return f"{initiative_total(npc, modifier, wounds)} + {npc.initiative_dice}W6"


def initiative_explanation(
    npc: engine.BaseNPC, modifier: int = 0, wounds: int = 0
) -> list[str]:
    """Rechenweg der Initiative inklusive aller Modifikatoren."""
    lines: list[str] = []
    if isinstance(npc, engine.Spirit):
        lines.append(
            f"(F x 2) + Aenderung Initiative = ({npc.force} x 2) + "
            f"{npc.initiative_modifier} = {npc.natural_initiative_base()}"
        )
    else:
        reaction = npc.attributes["Reaktion"]
        intuition = npc.attributes["Intuition"]
        natural = reaction + intuition
        lines.append(f"Reaktion {reaction} + Intuition {intuition} = {natural}")
        if npc.initiative_override is not None:
            lines.append(f"Manuell gesetzt: {npc.initiative_override}")
    lines.append(f"Initiativwuerfel: + {npc.initiative_dice}W6")
    extras = []
    if wounds:
        extras.append(f"{wounds:+d} Wundabzug")
    if modifier:
        extras.append(f"{modifier:+d} Situation")
    if extras:
        lines.append("Modifikatoren: " + ", ".join(extras))
    lines.append(f"Ergebnis: {initiative_line(npc, modifier, wounds)}")
    return lines


def pool_table(pools: list[DicePool]) -> pd.DataFrame:
    """Pools als Tabelle fuer die kompakte Anzeige."""
    return pd.DataFrame(
        {
            "Probe": [pool.label for pool in pools],
            "W6": [pool.total for pool in pools],
            "Herleitung": [pool.formula for pool in pools],
        }
    )
