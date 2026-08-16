"""NPC-Engine: Archetypen, Attributsberechnung und Aufloesung von Textformeln."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import pandas as pd

# Umlaute als Escape, damit dieses Modul reines ASCII bleibt.
STAERKE = "St\u00e4rke"  # Staerke
INITIATIVWUERFEL = "Initiativw\u00fcrfel"  # Initiativwuerfel
INIT_AENDERUNG = "\u00c4nderung Initiative"  # Aenderung Initiative
ERLAEUTERUNGEN = "Erl\u00e4uterungen"  # Erlaeuterungen
RUESTUNG = "R\u00fcstung"  # Ruestung
PRAEZISION = "Pr\u00e4zision"  # Praezision
MODUS = "Reichw./Modus"

ATTRIBUTES: tuple[str, ...] = (
    "Konstitution",
    "Geschick",
    "Reaktion",
    STAERKE,
    "Willenskraft",
    "Logik",
    "Intuition",
    "Charisma",
)

# Spalten der NPC-Tabelle, die keine Fertigkeit sind.
NPC_META_COLUMNS = ("Edge", "Essenz", "Magie", "Panzerung", INITIATIVWUERFEL)

# Variablen, die in Textformeln fuer die Kraftstufe stehen.
FORMULA_VARIABLES = ("KS", "F")

# Spalten, in denen Critter Kraftstufen-Formeln enthalten koennen.
CRITTER_FORCE_COLUMNS: tuple[str, ...] = ATTRIBUTES + ("Initiative", "Edge", "Magie")

_FORCE_REF_PATTERN = re.compile(r"(?<![A-Z])F(?![A-Z])|(?<![A-Z])KS(?![A-Z])", re.IGNORECASE)
_FORMULA_SAFE_PATTERN = re.compile(r"^[\d+\-*/().]+$")

MIN_SPIRIT_ATTRIBUTE = 1
MIN_DRAIN = 2
MAX_FORCE = 12

# Fertigkeiten, die jeder Zauberer besitzt - unabhaengig vom Wert in der CSV.
# 'Herbeirufen' ist in Fertigkeiten.csv der Name der Beschwoerungsfertigkeit.
MAGIC_SKILLS = ("Spruchzauberei", "Antimagie", "Herbeirufen")

DEFAULT_MAGIC = 6
DEFAULT_MAGIC_SKILL = 4

ARCHETYPE_MUNDANE = "Mundan"
ARCHETYPE_MAGICIAN = "Zauberer"
ARCHETYPE_SPIRIT = "Geist"
ARCHETYPE_CRITTER = "Critter"

ARCHETYPES = (ARCHETYPE_MUNDANE, ARCHETYPE_MAGICIAN, ARCHETYPE_SPIRIT, ARCHETYPE_CRITTER)

# Aus welcher Datenbank speist sich welcher Archetyp.
ARCHETYPE_DATABASE = {
    ARCHETYPE_MUNDANE: "NPC_Grunddaten",
    ARCHETYPE_MAGICIAN: "NPC_Grunddaten",
    ARCHETYPE_SPIRIT: "Geister",
    ARCHETYPE_CRITTER: "Critter",
}

_MISSING_VALUES = {"", "-", "--", "?", "n/a", "na", "nan", "none", "\u2013", "\u2014"}

_NUMBER_PATTERN = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_DICE_PATTERN = re.compile(r"(\d+)\s*[WD]\s*6", re.IGNORECASE)
# Trennt Aufzaehlungen, ignoriert dabei Kommata innerhalb von Klammern.
_LIST_PATTERN = re.compile(r",(?![^(]*\))")


def _is_missing(value: object) -> bool:
    try:
        if pd.isna(value):  # faengt None, NaN und pd.NA ab
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _MISSING_VALUES


def to_int(value: object, default: int = 0) -> int:
    """Wandelt CSV-Text robust in einen Integer; leere Werte und '-' ergeben 0."""
    if _is_missing(value):
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)

    match = _NUMBER_PATTERN.search(str(value))
    if match is None:
        return default
    return int(float(match.group().replace(",", ".")))


def to_float(value: object, default: float = 0.0) -> float:
    """Wie to_int, behaelt aber Nachkommastellen (z. B. Essenz 5,5)."""
    if _is_missing(value):
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)

    match = _NUMBER_PATTERN.search(str(value))
    if match is None:
        return default
    return float(match.group().replace(",", "."))


def to_text(value: object, default: str = "") -> str:
    """Gibt CSV-Text bereinigt zurueck; leere Werte werden zum Standardtext."""
    if _is_missing(value):
        return default
    return str(value).strip()


def contains_force_reference(value: object) -> bool:
    """Prueft, ob ein CSV-Wert die Kraftstufen-Variable F oder KS enthaelt."""
    if _is_missing(value):
        return False
    return bool(_FORCE_REF_PATTERN.search(str(value)))


def critter_uses_force(row: pd.Series) -> bool:
    """True, wenn dieser Critter Attribute oder Initiative aus F ableitet."""
    return any(
        contains_force_reference(row.get(column))
        for column in CRITTER_FORCE_COLUMNS
        if column in row.index
    )


def evaluate_formula(formula_str: object, force: int) -> int:
    """Loest Formeln wie 'F+3', '(F*2)+2' oder 'F/2' mit der Kraftstufe auf.

    Reine Zahlen werden unveraendert uebernommen, leere Werte ergeben 0.
    """
    if _is_missing(formula_str):
        return 0

    text = str(formula_str).strip().upper().replace(" ", "")
    if not text:
        return 0

    force = int(force)

    if not contains_force_reference(text):
        return to_int(text, default=0)

    for variable in FORMULA_VARIABLES:
        text = re.sub(rf"(?<![A-Z]){variable}(?![A-Z])", str(force), text)

    # Kurzschreibweisen wie Fx2 oder F×2 in echte Multiplikation uebersetzen.
    text = re.sub(r"F([X\u00d7*])(\d+)", rf"{force}*\2", text)

    if not _FORMULA_SAFE_PATTERN.match(text):
        return to_int(formula_str, default=0)

    try:
        return int(eval(text, {"__builtins__": {}}, {}))
    except (SyntaxError, TypeError, ZeroDivisionError, NameError, ValueError):
        return to_int(formula_str, default=0)


def calculate_formula(formula_str: object, force: int) -> int:
    """Kompatibilitaets-Wrapper fuer Geister, Zauberentzug und Critter."""
    return evaluate_formula(formula_str, force)


def calculate_drain(formula_str: object, force: int) -> int:
    """Entzug eines Zaubers; laut Regelwerk immer mindestens 2."""
    return max(MIN_DRAIN, calculate_formula(formula_str, force))


def parse_initiative_dice(value: object, default: int = 1) -> int:
    """Liest die Wuerfelzahl aus Angaben wie '+2W6'."""
    match = _DICE_PATTERN.search(str(value))
    return int(match.group(1)) if match else default


def split_list(value: object) -> list[str]:
    """Zerlegt Aufzaehlungen wie 'Bewegung, Verschlingen (Erde)' in Einzelteile."""
    if _is_missing(value):
        return []
    return [part.strip() for part in _LIST_PATTERN.split(str(value)) if part.strip()]


def get_row(df: pd.DataFrame, name: str) -> pd.Series:
    """Holt genau eine Zeile; bei doppelten Namen immer die erste Fundstelle."""
    if name not in df.index:
        raise KeyError(f"'{name}' ist in dieser Datenbank nicht enthalten.")

    entry = df.loc[name]
    if isinstance(entry, pd.DataFrame):
        entry = entry.iloc[0]
    return entry


@dataclass(frozen=True)
class Weapon:
    """Eine Waffe aus der Waffen-Datenbank."""

    name: str
    weapon_type: str
    damage: str
    ap: str
    mode: str
    accuracy: str
    recoil: str
    ammo: str
    source: str

    @classmethod
    def from_row(cls, name: str, row: pd.Series) -> "Weapon":
        return cls(
            name=name,
            weapon_type=to_text(row.get("Typ"), "-"),
            damage=to_text(row.get("Schaden"), "-"),
            ap=to_text(row.get("DK"), "-"),
            mode=to_text(row.get(MODUS), "-"),
            accuracy=to_text(row.get(PRAEZISION), "-"),
            recoil=to_text(row.get("RK"), "-"),
            ammo=to_text(row.get("Munition"), "-"),
            source=to_text(row.get("Fundstelle"), "-"),
        )

    def summary(self) -> dict[str, str]:
        return {
            "Schaden": self.damage,
            "DK": self.ap,
            "Modus": self.mode,
            f"{PRAEZISION}": self.accuracy,
            "RK": self.recoil,
            "Munition": self.ammo,
        }


@dataclass(frozen=True)
class Armor:
    """Ein Eintrag aus der Ruestungs-Datenbank."""

    name: str
    rating: int
    rating_text: str
    category: str
    source: str

    @classmethod
    def from_row(cls, name: str, row: pd.Series) -> "Armor":
        rating_text = to_text(row.get(RUESTUNG), "0")
        return cls(
            name=name,
            rating=to_int(rating_text),
            rating_text=rating_text,
            category=to_text(row.get("Kategorie"), "-"),
            source=f"{to_text(row.get('Quelle'), '-')} S. {to_text(row.get('Seite'), '-')}",
        )

    @property
    def is_accessory(self) -> bool:
        """Werte wie '+2' (Helm, Schild) ergaenzen eine getragene Panzerung."""
        return self.rating_text.startswith("+")


def load_weapon(df: pd.DataFrame, name: str) -> Weapon:
    return Weapon.from_row(name, get_row(df, name))


def load_armor(df: pd.DataFrame, name: str) -> Armor:
    return Armor.from_row(name, get_row(df, name))


class BaseNPC:
    """Gemeinsame Basis aller Archetypen."""

    ARCHETYPE = "NPC"

    def __init__(self, name: str, row: pd.Series) -> None:
        self.name = name
        self.row = row
        self.attributes = self._read_attributes(row)
        self.formulas: dict[str, str] = {}
        self.initiative_dice = 1
        self.armor = 0
        self.edge = 0
        self.initiative_override: int | None = None
        self.weapons: list[Weapon] = []
        self.armor_item: Armor | None = None

    def _read_attributes(self, row: pd.Series) -> dict[str, int]:
        return {attribute: to_int(row.get(attribute)) for attribute in ATTRIBUTES}

    @classmethod
    def from_database(cls, df: pd.DataFrame, name: str, **kwargs) -> "BaseNPC":
        return cls(name, get_row(df, name), **kwargs)

    @property
    def initiative_base(self) -> int:
        if self.initiative_override is not None:
            return self.initiative_override
        return self.natural_initiative_base()

    def natural_initiative_base(self) -> int:
        """Initiative-Basis aus den Attributen, ohne manuelle Anpassung."""
        return self.attributes["Reaktion"] + self.attributes["Intuition"]

    @property
    def initiative_text(self) -> str:
        return f"{self.initiative_base} + {self.initiative_dice}W6"

    @property
    def physical_monitor(self) -> int:
        return 8 + math.ceil(self.attributes["Konstitution"] / 2)

    @property
    def stun_monitor(self) -> int:
        return 8 + math.ceil(self.attributes["Willenskraft"] / 2)

    @property
    def damage_capacity(self) -> int:
        """Hausregel: ein gemeinsamer Monitor in Hoehe des groesseren Wertes."""
        return max(self.physical_monitor, self.stun_monitor)

    def details(self) -> dict[str, str]:
        """Kurze Zusatzwerte fuer die Anzeige."""
        return {
            "Initiative": self.initiative_text,
            "Zustandsmonitor (koerperlich)": str(self.physical_monitor),
            "Zustandsmonitor (geistig)": str(self.stun_monitor),
        }

    def long_texts(self) -> dict[str, str]:
        """Lange Textfelder, die in einem Expander landen."""
        return {}


class MundaneNPC(BaseNPC):
    """Nichtmagischer NPC aus NPC_Grunddaten."""

    ARCHETYPE = ARCHETYPE_MUNDANE

    def __init__(self, name: str, row: pd.Series) -> None:
        super().__init__(name, row)
        self.initiative_dice = parse_initiative_dice(row.get(INITIATIVWUERFEL))
        self.armor = to_int(row.get("Panzerung"))
        self.edge = to_int(row.get("Edge"))
        self.essence = to_float(row.get("Essenz"))
        self.skills = {
            column: to_int(row[column])
            for column in row.index
            if column not in ATTRIBUTES and column not in NPC_META_COLUMNS
        }

    def details(self) -> dict[str, str]:
        values = super().details()
        values["Edge"] = str(self.edge)
        values["Panzerung"] = str(self.armor)
        values["Essenz"] = f"{self.essence:g}"
        return values

    def skill_table(self, only_trained: bool = True) -> pd.DataFrame:
        skills = {
            name: value
            for name, value in self.skills.items()
            if value > 0 or not only_trained
        }
        table = pd.DataFrame(
            {"Fertigkeit": list(skills), "Stufe": list(skills.values())}
        )
        return table.sort_values("Stufe", ascending=False, ignore_index=True)


class MagicianNPC(MundaneNPC):
    """Magisch begabter NPC: Grundwerte wie mundan, dazu Magie und Zauber.

    Die Basis-Metatypen fuehren in der CSV ueberall eine 0 bei Magie und den
    magischen Fertigkeiten. Diese Nullen werden hier bewusst uebersteuert.
    """

    ARCHETYPE = ARCHETYPE_MAGICIAN

    def __init__(
        self,
        name: str,
        row: pd.Series,
        magic: int | None = None,
        spells: list[str] | None = None,
        skill_ratings: dict[str, int] | None = None,
    ) -> None:
        super().__init__(name, row)
        self.magic_from_csv = to_int(row.get("Magie"))
        self.magic = int(magic) if magic is not None else (
            self.magic_from_csv or DEFAULT_MAGIC
        )
        self.spells = list(spells or [])

        # Magische Fertigkeiten gehoeren immer dazu, auch wenn die CSV sie
        # nicht kennt oder auf 0 setzt.
        for skill in MAGIC_SKILLS:
            self.skills.setdefault(skill, 0)
            if self.skills[skill] <= 0:
                self.skills[skill] = DEFAULT_MAGIC_SKILL

        for skill, rating in (skill_ratings or {}).items():
            self.skills[skill] = to_int(rating)

    @property
    def magic_skills(self) -> dict[str, int]:
        return {skill: self.skills.get(skill, 0) for skill in MAGIC_SKILLS}

    def details(self) -> dict[str, str]:
        values = super().details()
        values["Magie"] = str(self.magic)
        values["Zauber"] = str(len(self.spells))
        return values

    def spell_table(self, spell_db: pd.DataFrame, force: int) -> pd.DataFrame:
        """Zauberliste mit Entzug, berechnet fuer die gewaehlte Kraftstufe."""
        rows = []
        for spell in self.spells:
            try:
                data = get_row(spell_db, spell)
            except KeyError:
                continue
            rows.append(
                {
                    "Zauber": spell,
                    "Kategorie": to_text(data.get("KATEGORIE"), "-"),
                    "Art": to_text(data.get("ART"), "-"),
                    "Reichweite": to_text(data.get("REICHWEITE"), "-"),
                    "Schaden": to_text(data.get("SCHADEN"), "-"),
                    "Dauer": to_text(data.get("DAUER"), "-"),
                    "Entzugsformel": to_text(data.get("ENTZUG"), "-"),
                    "Entzug": calculate_drain(data.get("ENTZUG"), force),
                }
            )
        return pd.DataFrame(rows)


class Spirit(BaseNPC):
    """Geist: alle Attribute ergeben sich aus der Kraftstufe."""

    ARCHETYPE = ARCHETYPE_SPIRIT

    def __init__(self, name: str, row: pd.Series, force: int = 4) -> None:
        self.force = max(1, min(int(force), MAX_FORCE))
        super().__init__(name, row)
        self.formulas = {
            attribute: to_text(row.get(attribute), "-") for attribute in ATTRIBUTES
        }
        self.initiative_dice = parse_initiative_dice(row.get(INITIATIVWUERFEL), default=2)
        self.initiative_modifier = to_int(row.get(INIT_AENDERUNG))
        self.unarmed_damage = to_text(row.get("Waffenlos"), "-")
        self.source = to_text(row.get("Fundstelle"), "-")
        self.powers = split_list(row.get("Standardkraft"))
        self.optional_powers = split_list(row.get("Optionale Kraft"))

    def _read_attributes(self, row: pd.Series) -> dict[str, int]:
        return {
            attribute: max(
                MIN_SPIRIT_ATTRIBUTE, calculate_formula(row.get(attribute), self.force)
            )
            for attribute in ATTRIBUTES
        }

    def details(self) -> dict[str, str]:
        values = super().details()
        values["Kraftstufe (F)"] = str(self.force)
        values["Waffenloser Schaden"] = f"{self.unarmed_damage}K"
        values["Fundstelle"] = self.source
        return values

    def long_texts(self) -> dict[str, str]:
        return {
            "Standardkraefte": ", ".join(self.powers) or "-",
            "Optionale Kraefte": ", ".join(self.optional_powers) or "-",
        }


class Critter(BaseNPC):
    """Critter aus der Critter-Datenbank (gleiche Attributsspalten wie NPC/Geister)."""

    ARCHETYPE = ARCHETYPE_CRITTER

    def __init__(
        self,
        name: str,
        row: pd.Series,
        force: int = 4,
        uses_force: bool | None = None,
    ) -> None:
        self.uses_force = uses_force if uses_force is not None else critter_uses_force(row)
        self.force = max(1, min(int(force), MAX_FORCE)) if self.uses_force else 0
        super().__init__(name, row)
        self.category = to_text(row.get("Kategorie"), "-")
        self.armor = to_int(row.get(RUESTUNG))
        self.source = f"{to_text(row.get('Quelle'), '-')} S. {to_text(row.get('Seite'), '-')}"

        force_value = self.force if self.uses_force else 0
        self.edge = (
            evaluate_formula(row.get("Edge"), force_value)
            if self.uses_force
            else to_int(row.get("Edge"))
        )
        self.magic = (
            evaluate_formula(row.get("Magie"), force_value)
            if self.uses_force
            else to_int(row.get("Magie"))
        )
        self._initiative_base = self._resolve_initiative(row)
        self.initiative_dice = 1

        if self.uses_force:
            self.formulas = {
                attribute: to_text(row.get(attribute), "-") for attribute in ATTRIBUTES
            }
        else:
            self.formulas = {}

    def _resolve_initiative(self, row: pd.Series) -> int:
        raw = row.get("Initiative")
        if self.uses_force:
            return evaluate_formula(raw, self.force)
        return to_int(raw)

    def _read_attributes(self, row: pd.Series) -> dict[str, int]:
        if self.uses_force:
            return {
                attribute: max(
                    MIN_SPIRIT_ATTRIBUTE,
                    evaluate_formula(row.get(attribute), self.force),
                )
                for attribute in ATTRIBUTES
            }
        return {attribute: to_int(row.get(attribute)) for attribute in ATTRIBUTES}

    def natural_initiative_base(self) -> int:
        if self._initiative_base:
            return self._initiative_base
        return super().natural_initiative_base()

    def details(self) -> dict[str, str]:
        values = super().details()
        values["Kategorie"] = self.category
        values["Edge"] = str(self.edge)
        values["Panzerung"] = str(self.armor)
        if self.magic:
            values["Magie"] = str(self.magic)
        if self.uses_force:
            values["Kraftstufe (F)"] = str(self.force)
        values["Fundstelle"] = self.source
        return values


def apply_overrides(
    npc: BaseNPC,
    attributes: dict[str, int] | None = None,
    armor: int | None = None,
    edge: int | None = None,
    initiative_base: int | None = None,
    initiative_dice: int | None = None,
) -> BaseNPC:
    """Uebernimmt am Spieltisch angepasste Werte in den NPC."""
    for attribute, value in (attributes or {}).items():
        if attribute in npc.attributes:
            npc.attributes[attribute] = to_int(value)

    if armor is not None:
        npc.armor = to_int(armor)
    if edge is not None:
        npc.edge = to_int(edge)
    if initiative_base is not None:
        npc.initiative_override = to_int(initiative_base)
    if initiative_dice is not None:
        npc.initiative_dice = to_int(initiative_dice)

    return npc


def equip(
    npc: BaseNPC,
    weapons: list[Weapon] | None = None,
    armor: Armor | None = None,
) -> BaseNPC:
    """Ruestet den NPC aus. Die Panzerung ersetzt den Wert aus der CSV."""
    npc.weapons = [weapon for weapon in (weapons or []) if weapon is not None]

    if armor is not None:
        npc.armor_item = armor
        # Zubehoer wie Helm ('+2') ergaenzt, alles andere ersetzt den Grundwert.
        npc.armor = npc.armor + armor.rating if armor.is_accessory else armor.rating

    return npc


def create_npc(
    archetype: str,
    name: str,
    df: pd.DataFrame,
    force: int = 4,
    magic: int | None = None,
    spells: list[str] | None = None,
    skill_ratings: dict[str, int] | None = None,
) -> BaseNPC:
    """Erzeugt den passenden Archetyp aus der jeweiligen Datenbank."""
    if archetype == ARCHETYPE_MUNDANE:
        return MundaneNPC.from_database(df, name)
    if archetype == ARCHETYPE_MAGICIAN:
        return MagicianNPC.from_database(
            df, name, magic=magic, spells=spells, skill_ratings=skill_ratings
        )
    if archetype == ARCHETYPE_SPIRIT:
        return Spirit.from_database(df, name, force=force)
    if archetype == ARCHETYPE_CRITTER:
        row = get_row(df, name)
        return Critter.from_database(
            df,
            name,
            force=force,
            uses_force=critter_uses_force(row),
        )

    raise ValueError(f"Unbekannter Archetyp '{archetype}'.")
