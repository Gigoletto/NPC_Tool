"""Shadowrun 5 Spielleitertool - Hauptoberflaeche und Navigation."""

from __future__ import annotations

import html
import json
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st

from src import data_loader
from src import npc_engine as engine
from src import pool_calculator as pools

# Umlaute als Escape, damit diese Datei reines ASCII bleibt.
EINTRAEGE = "Eintr\u00e4ge"  # Eintraege
KRAEFTE = "Kr\u00e4fte"  # Kraefte
LOESCHEN = "L\u00f6schen"  # Loeschen
RUESTUNG = "R\u00fcstung"  # Ruestung
AUSRUESTUNG = "Ausr\u00fcstung"  # Ausruestung

APP_TITLE = "\u26a1 Shadowrun 5 - Spielleitertool"

ARCHETYPE_ICONS: dict[str, str] = {
    engine.ARCHETYPE_MUNDANE: "\U0001f464 Mundan",
    engine.ARCHETYPE_MAGICIAN: "\u2728 Zauberer",
    engine.ARCHETYPE_SPIRIT: "\U0001f47b Geist",
    engine.ARCHETYPE_CRITTER: "\U0001f43e Critter",
}

SECTION_ATTACK = "\u2694\ufe0f Angriff"
SECTION_DEFENSE = "\U0001f6e1\ufe0f Verteidigung & Schadenswiderstand"
SECTION_SKILLS = "\U0001f3b2 Proben & Fertigkeiten"
SECTION_EQUIPMENT = "\U0001f392 Ausr\u00fcstung"
SECTION_SPELLS = "\U0001f4dc Zauber & Entzug"

EXPORT_FORMAT = "shadowrun5-gm-dashboard"
EXPORT_VERSION = 1

KEINE_WAFFE = "Keine"
KEINE_PANZERUNG = "Keine (Wert aus CSV)"

ATTRIBUTE_SHORT = {
    "Konstitution": "KON",
    "Geschick": "GES",
    "Reaktion": "REA",
    engine.STAERKE: "STR",
    "Willenskraft": "WIL",
    "Logik": "LOG",
    "Intuition": "INT",
    "Charisma": "CHA",
}

# So viele Proben stehen direkt auf der Karte, der Rest liegt im Expander.
VISIBLE_POOLS = 6

# 'Herbeirufen' ist der Name der Beschwoerungsfertigkeit in Fertigkeiten.csv.
MAGIC_SKILL_LABELS = {"Herbeirufen": "Herbeirufen (Beschw\u00f6ren)"}


def archetype_label(archetype: str) -> str:
    """Anzeigename mit Icon - intern bleibt der Archetyp unveraendert."""
    return ARCHETYPE_ICONS.get(archetype, archetype)


def split_dashboard_pools(
    npc_pools: list[pools.DicePool],
) -> tuple[list[pools.DicePool], list[pools.DicePool], list[pools.DicePool]]:
    """Teilt Pools in Angriff, Verteidigung und Proben/Fertigkeiten."""
    attacks: list[pools.DicePool] = []
    defenses: list[pools.DicePool] = []
    skills: list[pools.DicePool] = []
    for pool in npc_pools:
        if pool.label.startswith("Angriff"):
            attacks.append(pool)
        elif pool.label in ("Verteidigung", "Schadenswiderstand"):
            defenses.append(pool)
        else:
            skills.append(pool)
    return attacks, defenses, skills


def render_dashboard_pools(npc_pools: list[pools.DicePool]) -> None:
    """Zeigt Wuerfelpools auf der Karte in thematischen Abschnitten."""
    attacks, defenses, skill_pools = split_dashboard_pools(npc_pools)
    shown = 0

    if attacks:
        st.markdown(f"**{SECTION_ATTACK}**")
        for pool in attacks:
            st.write(f"**{pool.label}:** {pool.dashboard_text}")
            shown += 1

    if defenses:
        st.markdown(f"**{SECTION_DEFENSE}**")
        for pool in defenses:
            st.write(f"**{pool.label}:** {pool.dashboard_text}")
            shown += 1

    if not skill_pools:
        return

    st.markdown(f"**{SECTION_SKILLS}**")
    visible_count = max(0, VISIBLE_POOLS - shown)
    for pool in skill_pools[:visible_count]:
        st.write(f"**{pool.label}:** {pool.dashboard_text}")

    overflow = skill_pools[visible_count:]
    if overflow:
        with st.expander(f"{SECTION_SKILLS} (weitere)"):
            st.dataframe(
                pools.pool_table(overflow),
                width="stretch",
                hide_index=True,
            )


def html_attr(text: object) -> str:
    """Maskiert Text fuer HTML-Attribute (title=), damit Anfuehrungszeichen nicht brechen."""
    value = engine.to_text(text, "")
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def spell_description(spell_db: pd.DataFrame, name: str) -> str:
    try:
        row = engine.get_row(spell_db, name)
    except KeyError:
        return "Keine Beschreibung hinterlegt."
    return engine.to_text(row.get(engine.ERLAEUTERUNGEN), "Keine Beschreibung hinterlegt.")


def spell_tooltip_html(
    spell_db: pd.DataFrame,
    name: str,
    *,
    force: int | None = None,
) -> str:
    """HTML-Zeile mit Browser-Tooltip gemaess Vorgabe (title-Attribut)."""
    title = html_attr(spell_description(spell_db, name))
    label = html.escape(name)
    suffix = ""
    if force is not None:
        try:
            row = engine.get_row(spell_db, name)
            formula = engine.to_text(row.get("ENTZUG"), "-")
            drain = engine.calculate_drain(row.get("ENTZUG"), force)
            suffix = f" (Entzug: {html.escape(formula)} &#8594; {drain})"
        except KeyError:
            pass
    return f'<span title="{title}">\u2728 {label}{suffix}</span>'


def render_spell_tooltip_list(
    spell_db: pd.DataFrame,
    spells: list[str],
    force: int | None = None,
) -> None:
    """Listet Zauber mit Mouseover-Tooltip und optional Entzug bei Kraftstufe."""
    if not spells:
        return
    lines = [
        f"&bull; {spell_tooltip_html(spell_db, spell, force=force)}"
        for spell in sorted(spells)
    ]
    st.markdown("<br>".join(lines), unsafe_allow_html=True)

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="\u26a1",
    layout="wide",
)


def load_databases() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Laedt alle Datenbanken und sammelt Fehler statt sie durchzureichen."""
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}

    for name in data_loader.DATASETS:
        try:
            frames[name] = data_loader.load_database(name)
        except Exception as error:  # Fehlende oder defekte CSV soll die App nicht stoppen.
            errors[name] = str(error)

    return frames, errors


def render_database_status(frames: dict[str, pd.DataFrame], errors: dict[str, str]) -> None:
    """Ladezustand aller CSV-Dateien - nur im Tab 'Datenbanken' sichtbar."""
    status, detail = st.columns([1, 3])
    status.metric(
        f"Geladen ({EINTRAEGE} gesamt)",
        f"{len(frames)}/{len(data_loader.DATASETS)}",
        delta=f"{sum(len(df) for df in frames.values())} {EINTRAEGE}",
        delta_color="off",
    )

    with detail:
        for name, message in errors.items():
            st.error(f"**{name}** - {message}", icon="\u26a0\ufe0f")

        lines = []
        for name, df in frames.items():
            line = f"**{name}** - {len(df)} {EINTRAEGE}"
            duplicates = int(df.index.duplicated().sum())
            if duplicates:
                line += f" :orange[({duplicates}x doppelter Name)]"
            lines.append(line)
        st.write(" \u00b7 ".join(lines))


def build_npc(config: dict, frames: dict[str, pd.DataFrame]) -> engine.BaseNPC | None:
    """Erzeugt den NPC neu aus seiner gespeicherten Konfiguration."""
    df = frames.get(engine.ARCHETYPE_DATABASE[config["archetype"]])
    if df is None:
        return None
    try:
        npc = engine.create_npc(
            config["archetype"],
            config["name"],
            df,
            force=config.get("force", 4),
            magic=config.get("magic"),
            spells=config.get("spells", []),
            skill_ratings=config.get("skill_ratings", {}),
        )
    except KeyError:
        return None

    engine.apply_overrides(
        npc,
        attributes=config.get("attributes"),
        edge=config.get("edge"),
        initiative_base=config.get("initiative"),
        initiative_dice=config.get("initiative_dice"),
    )
    equip_from_config(npc, config, frames)
    return npc


def equip_from_config(
    npc: engine.BaseNPC, config: dict, frames: dict[str, pd.DataFrame]
) -> None:
    """Waffen und Panzerung aus der Konfiguration an den NPC haengen."""
    weapon_db = frames.get("Waffen")
    weapons = []
    if weapon_db is not None:
        weapons = [
            engine.load_weapon(weapon_db, name)
            for name in config.get("weapons", [])
            if name and name in weapon_db.index
        ]

    armor_db = frames.get(RUESTUNG)
    armor_name = config.get("armor")
    armor = None
    if armor_db is not None and armor_name and armor_name in armor_db.index:
        armor = engine.load_armor(armor_db, armor_name)

    engine.equip(npc, weapons, armor)


def select_npc_config(frames: dict[str, pd.DataFrame]) -> dict | None:
    """Auswahl von Archetyp und Name - im Hauptbereich, damit keine Sidebar noetig ist."""
    st.markdown("**NPC erstellen**")

    archetype = st.radio(
        "Archetyp",
        engine.ARCHETYPES,
        horizontal=True,
        format_func=archetype_label,
    )
    database = engine.ARCHETYPE_DATABASE[archetype]
    df = frames.get(database)
    if df is None:
        st.error(f"Datenbank '{database}' ist nicht geladen.")
        return None

    fields = st.columns(3)
    slot = 0

    # Critter sind zahlreich - erst nach Kategorie filtern.
    if archetype == engine.ARCHETYPE_CRITTER and "Kategorie" in df.columns:
        categories = ["Alle"] + sorted(df["Kategorie"].dropna().unique())
        category = fields[slot].selectbox("Kategorie", categories)
        slot += 1
        if category != "Alle":
            df = df[df["Kategorie"] == category]

    names = sorted(dict.fromkeys(df.index))
    if not names:
        st.warning("Keine Auswahl vorhanden.")
        return None

    name = fields[slot].selectbox("Name", names)
    slot += 1

    config = {
        "uid": "",
        "archetype": archetype,
        "name": name,
        "force": 4,
        "uses_force": False,
        "magic": None,
        "skill_ratings": {},
        "spells": [],
        "spell_force": 4,
        "modifier": 0,
        "damage": 0,
        "attributes": {},
        "edge": None,
        "initiative": None,
        "initiative_dice": None,
        "weapons": [],
        "armor": None,
    }

    if archetype == engine.ARCHETYPE_SPIRIT:
        config["force"] = fields[slot].slider("Kraftstufe (F)", 1, engine.MAX_FORCE, 4)
    elif archetype == engine.ARCHETYPE_CRITTER:
        row = engine.get_row(df, name)
        config["uses_force"] = engine.critter_uses_force(row)
        if config["uses_force"]:
            config["force"] = fields[slot].slider("Kraftstufe (F)", 1, engine.MAX_FORCE, 4)
    elif archetype == engine.ARCHETYPE_MAGICIAN:
        row = engine.get_row(df, name)
        config["magic"] = int(
            fields[slot].slider(
                "Magie-Attribut",
                1,
                engine.MAX_FORCE,
                engine.to_int(row.get("Magie")) or engine.DEFAULT_MAGIC,
                help="Unabhaengig vom Wert in der CSV frei waehlbar.",
            )
        )
        config["skill_ratings"] = select_magic_skills(row)
        config["spells"] = select_spells(frames.get("Zauber"), f"{archetype}|{name}")
        config["spell_force"] = config["magic"]

    return config


def select_magic_skills(row: pd.Series) -> dict[str, int]:
    """Magische Fertigkeiten frei einstellbar - die CSV fuehrt hier nur Nullen."""
    ratings: dict[str, int] = {}
    columns = st.columns(len(engine.MAGIC_SKILLS))

    for column, skill in zip(columns, engine.MAGIC_SKILLS):
        preset = engine.to_int(row.get(skill)) or engine.DEFAULT_MAGIC_SKILL
        ratings[skill] = int(
            column.slider(MAGIC_SKILL_LABELS.get(skill, skill), 0, 12, preset)
        )

    return ratings


def select_spells(spell_db: pd.DataFrame | None, selection_key: str) -> list[str]:
    """Zauber kategorieuebergreifend waehlen - ohne Multiselect-Reset bei Filterwechsel."""
    if spell_db is None:
        st.error("Datenbank 'Zauber' ist nicht geladen.")
        return []

    state_key = f"selected_spells_{selection_key}"
    st.session_state.setdefault(state_key, [])

    valid = set(spell_db.index)
    selected: list[str] = [
        spell for spell in st.session_state[state_key] if spell in valid
    ]
    st.session_state[state_key] = selected

    with st.expander("Zauber auswaehlen", expanded=True):
        options = spell_db
        if "KATEGORIE" in spell_db.columns:
            categories = ["Alle"] + sorted(spell_db["KATEGORIE"].dropna().unique())
            category = st.selectbox(
                "Zauberkategorie (Filter)",
                categories,
                key=f"spell_cat_{selection_key}",
            )
            if category != "Alle":
                options = spell_db[spell_db["KATEGORIE"] == category]

        available = sorted(
            spell for spell in dict.fromkeys(options.index) if spell not in selected
        )

        pick_row, add_row = st.columns([4, 1])
        spell_choice: str | None = None
        if available:
            spell_choice = pick_row.selectbox(
                "Einzelszauber aus dieser Kategorie",
                available,
                key=f"spell_one_{selection_key}_{category}",
            )
        else:
            pick_row.caption("Keine weiteren Zauber in dieser Kategorie verfuegbar.")

        if add_row.button(
            "Zauber hinzufuegen",
            key=f"spell_add_{selection_key}",
            width="stretch",
            disabled=not available,
        ):
            if spell_choice and spell_choice not in selected:
                selected.append(spell_choice)
                st.session_state[state_key] = selected
                st.rerun()

        if spell_choice:
            st.caption(spell_description(spell_db, spell_choice))

        st.markdown(f"**Gewaehlte Zauber ({len(selected)})**")
        if not selected:
            st.caption("Noch keine Zauber gewaehlt.")
        else:
            for index, spell in enumerate(sorted(selected)):
                row, remove = st.columns([11, 1])
                row.markdown(
                    spell_tooltip_html(spell_db, spell),
                    unsafe_allow_html=True,
                )
                if remove.button(
                    "\u274c",
                    key=f"spell_rm_{selection_key}_{index}",
                    help="Zauber entfernen",
                ):
                    selected.remove(spell)
                    st.session_state[state_key] = selected
                    st.rerun()

    return list(st.session_state[state_key])


def render_attributes(npc: engine.BaseNPC) -> None:
    """Die acht Grundattribute als Metrik-Karten, bei Geistern samt Formel."""
    items = list(npc.attributes.items())
    for start in range(0, len(items), 4):
        columns = st.columns(4)
        for column, (label, value) in zip(columns, items[start : start + 4]):
            formula = npc.formulas.get(label)
            column.metric(label, value, delta=formula, delta_color="off")


def render_attribute_editor(npc: engine.BaseNPC, config: dict, state_key: str) -> None:
    """Attribute, Edge und Initiative direkt anpassbar - alle Pools rechnen live nach."""
    st.markdown("**Attribute** - mit den Pfeilen anpassen")

    # Ausgangswerte aus CSV bzw. Formel. Gespeichert werden spaeter nur
    # Abweichungen, damit z. B. die Kraftstufe eines Geistes weiter wirkt.
    natural_attributes = dict(npc.attributes)
    natural_edge = int(npc.edge)
    natural_dice = int(npc.initiative_dice)

    values: dict[str, int] = {}
    items = list(npc.attributes.items())
    for start in range(0, len(items), 4):
        columns = st.columns(4)
        for column, (label, value) in zip(columns, items[start : start + 4]):
            values[label] = int(
                column.number_input(
                    label,
                    min_value=0,
                    max_value=30,
                    value=int(value),
                    step=1,
                    key=f"attr_{state_key}_{label}",
                    help=npc.formulas.get(label),
                )
            )

    config["attributes"] = {
        label: value
        for label, value in values.items()
        if value != natural_attributes[label]
    }
    engine.apply_overrides(npc, attributes=values)

    columns = st.columns(4)
    edge = int(
        columns[0].number_input(
            "Edge", 0, 12, int(npc.edge), step=1, key=f"edge_{state_key}"
        )
    )
    # Der Schluessel enthaelt den natuerlichen Wert: aendern sich Reaktion oder
    # Intuition, startet das Feld wieder beim neu berechneten Basiswert.
    natural = npc.natural_initiative_base()
    initiative = int(
        columns[1].number_input(
            "Initiative-Basis",
            0,
            60,
            natural,
            step=1,
            key=f"ini_{state_key}_{natural}",
            help="Standard: Reaktion + Intuition",
        )
    )
    dice = int(
        columns[2].number_input(
            "Initiativw\u00fcrfel (W6)",
            1,
            5,
            int(npc.initiative_dice),
            step=1,
            key=f"dice_{state_key}",
        )
    )

    config["edge"] = edge if edge != natural_edge else None
    config["initiative"] = initiative if initiative != natural else None
    config["initiative_dice"] = dice if dice != natural_dice else None
    engine.apply_overrides(
        npc,
        edge=edge,
        initiative_base=config["initiative"],
        initiative_dice=dice,
    )


def render_equipment(
    npc: engine.BaseNPC,
    config: dict,
    frames: dict[str, pd.DataFrame],
    skill_map: dict[str, str],
    state_key: str,
) -> None:
    """Waffen und Panzerung waehlen; die Panzerung ersetzt den CSV-Grundwert."""
    st.markdown(f"**{AUSRUESTUNG}**")

    weapon_db = frames.get("Waffen")
    armor_db = frames.get(RUESTUNG)

    weapon_names = [KEINE_WAFFE]
    if weapon_db is not None:
        weapon_names += sorted(dict.fromkeys(weapon_db.index))
    armor_names = [KEINE_PANZERUNG]
    if armor_db is not None:
        armor_names += sorted(dict.fromkeys(armor_db.index))

    columns = st.columns(3)
    first = columns[0].selectbox("Waffe 1", weapon_names, key=f"w1_{state_key}")
    second = columns[1].selectbox("Waffe 2", weapon_names, key=f"w2_{state_key}")
    armor_name = columns[2].selectbox(
        "Getragene Panzerung", armor_names, key=f"armor_{state_key}"
    )

    config["weapons"] = [name for name in (first, second) if name != KEINE_WAFFE]
    config["armor"] = None if armor_name == KEINE_PANZERUNG else armor_name
    equip_from_config(npc, config, frames)

    if npc.armor_item is not None:
        item = npc.armor_item
        hint = "ergaenzt den Grundwert" if item.is_accessory else "ersetzt den Grundwert"
        st.caption(
            f"{item.name}: Panzerung {item.rating_text} ({hint}) \u2192 "
            f"Panzerung des NPC jetzt **{npc.armor}** \u00b7 {item.source}"
        )

    for weapon in npc.weapons:
        render_weapon(npc, weapon, skill_map)


def render_weapon(
    npc: engine.BaseNPC, weapon: engine.Weapon, skill_map: dict[str, str]
) -> None:
    with st.container(border=True):
        st.markdown(f"**{weapon.name}** \u00b7 {weapon.weapon_type}")

        columns = st.columns(3)
        columns[0].metric("Schaden", weapon.damage)
        columns[1].metric("DK", weapon.ap)
        columns[2].metric("Modus", weapon.mode)

        pool = pools.attack_pool(npc, weapon, skill_map)
        st.success(f"**{pool.label}:** {pool.text}")

        st.caption(
            f"{engine.PRAEZISION} {weapon.accuracy} \u00b7 RK {weapon.recoil} \u00b7 "
            f"Munition {weapon.ammo} \u00b7 {weapon.source}"
        )


def render_details(npc: engine.BaseNPC) -> None:
    details = npc.details()
    columns = st.columns(min(4, len(details)) or 1)
    for index, (label, value) in enumerate(details.items()):
        columns[index % len(columns)].metric(label, value)


def render_spirit_powers(
    npc: engine.Spirit, power_db: pd.DataFrame | None, key: str
) -> None:
    st.write("**Standard:** " + (", ".join(npc.powers) or "-"))
    st.write("**Optional:** " + (", ".join(npc.optional_powers) or "-"))

    if power_db is None:
        return

    choices = [
        power
        for power in npc.powers + npc.optional_powers
        if power.split(" (")[0] in power_db.index
    ]
    if not choices:
        return

    selected = st.selectbox("Kraft nachschlagen", choices, key=f"power_{key}")
    entry = engine.get_row(power_db, selected.split(" (")[0])
    st.caption(
        f"Art: {engine.to_text(entry.get('ART'), '-')} | "
        f"Handlung: {engine.to_text(entry.get('HANDLUNG'), '-')} | "
        f"Reichweite: {engine.to_text(entry.get('REICHWEITE'), '-')} | "
        f"Dauer: {engine.to_text(entry.get('DAUER'), '-')} | "
        f"{engine.to_text(entry.get('SEITE'), '-')}"
    )
    st.write(engine.to_text(entry.get(engine.ERLAEUTERUNGEN), "Keine Beschreibung hinterlegt."))


def render_generator(
    frames: dict[str, pd.DataFrame], skill_map: dict[str, str]
) -> None:
    with st.container(border=True):
        config = select_npc_config(frames)

    if config is None:
        st.info("Bitte einen Archetyp und einen Namen waehlen.")
        return

    npc = build_npc(config, frames)
    if npc is None:
        st.error("Dieser NPC konnte nicht erzeugt werden.")
        return

    header, button = st.columns([4, 1])
    header.subheader(f"{npc.name}  \u00b7  {archetype_label(npc.ARCHETYPE)}")
    # Der Klick wird erst am Ende ausgewertet, wenn Attribute und Ausruestung
    # in der Konfiguration stehen.
    add_clicked = button.button(
        "Zum Dashboard hinzufuegen", type="primary", width="stretch"
    )

    # Der Schluessel bindet die Eingabefelder an genau diesen NPC. Waehlst du
    # einen anderen Namen oder eine andere Kraftstufe, starten sie wieder
    # bei den Werten aus der Datenbank.
    state_key = (
        f"{config['archetype']}|{config['name']}|"
        f"{config.get('force')}|{config.get('magic')}|{config.get('uses_force')}"
    )

    render_attribute_editor(npc, config, state_key)
    st.divider()
    render_details(npc)
    st.divider()
    render_equipment(npc, config, frames, skill_map, state_key)

    st.divider()
    st.markdown("**Wuerfelpools**")
    for pool in pools.standard_pools(npc, skill_map)[:VISIBLE_POOLS]:
        st.write(f"**{pool.label}:** {pool.text}")
    st.caption("Gewuerfelt wird am Tisch - das Tool zaehlt nur die Wuerfel.")

    if isinstance(npc, engine.Spirit):
        with st.expander(f"{KRAEFTE} des Geistes", expanded=True):
            render_spirit_powers(npc, frames.get(KRAEFTE), key="generator")

    if isinstance(npc, engine.MagicianNPC) and npc.spells:
        with st.expander("Zauber", expanded=True):
            force = st.slider(
                "Kraftstufe der Zauber (KS)",
                1,
                engine.MAX_FORCE,
                min(npc.magic, engine.MAX_FORCE),
            )
            config["spell_force"] = force
            render_spell_tooltip_list(frames["Zauber"], npc.spells, force=force)
            st.caption("Entzugswert ist immer mindestens 2. Maus ueber Zauber fuer Wirkung.")

    if isinstance(npc, engine.MundaneNPC):
        with st.expander("Fertigkeiten"):
            only_trained = st.checkbox("Nur Fertigkeiten mit Stufe > 0", value=True)
            st.dataframe(npc.skill_table(only_trained), width="stretch", hide_index=True)

    with st.expander("Rohdaten aus der CSV"):
        st.dataframe(npc.row.to_frame("Wert"), width="stretch")

    if add_clicked:
        add_to_dashboard(config)


def copy_config(config: dict) -> dict:
    """Eigenstaendige Kopie, damit Karten sich nicht gegenseitig veraendern."""
    entry = dict(config)
    entry["spells"] = list(config.get("spells", []))
    entry["skill_ratings"] = dict(config.get("skill_ratings", {}))
    entry["attributes"] = dict(config.get("attributes", {}))
    entry["weapons"] = list(config.get("weapons", []))
    entry["uses_force"] = bool(config.get("uses_force"))
    return entry


def config_to_export(entry: dict) -> dict:
    """Bereitet einen Dashboard-Eintrag fuer JSON-Export vor."""
    copied = copy_config(entry)
    return {
        "archetype": copied["archetype"],
        "name": copied["name"],
        "label": copied.get("label", copied["name"]),
        "force": int(copied.get("force", 4)),
        "uses_force": bool(copied.get("uses_force")),
        "magic": copied.get("magic"),
        "skill_ratings": copied.get("skill_ratings", {}),
        "spells": copied.get("spells", []),
        "spell_force": int(copied.get("spell_force", 4)),
        "modifier": int(copied.get("modifier", 0)),
        "damage": int(copied.get("damage", 0)),
        "attributes": copied.get("attributes", {}),
        "edge": copied.get("edge"),
        "initiative": copied.get("initiative"),
        "initiative_dice": copied.get("initiative_dice"),
        "weapons": copied.get("weapons", []),
        "armor": copied.get("armor"),
    }


def build_export_payload(active: list[dict]) -> str:
    """Serialisiert alle Dashboard-NPCs in kompaktes JSON."""
    payload = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "npcs": [config_to_export(entry) for entry in active],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def export_filename() -> str:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return f"shadowrun-dashboard-{stamp}.json"


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def import_npc(raw: object) -> dict:
    """Wandelt einen JSON-Eintrag in einen gueltigen Dashboard-Eintrag um."""
    if not isinstance(raw, dict):
        raise ValueError("Jeder NPC muss ein JSON-Objekt sein.")

    archetype = raw.get("archetype")
    name = raw.get("name")
    if archetype not in engine.ARCHETYPES:
        raise ValueError(f"Unbekannter Archetyp '{archetype}'.")
    if not name:
        raise ValueError("Mindestens ein NPC hat keinen Namen.")

    magic = _optional_int(raw.get("magic"))
    return {
        "uid": uuid.uuid4().hex[:8],
        "archetype": archetype,
        "name": str(name),
        "label": str(raw.get("label") or name),
        "force": int(raw.get("force", 4)),
        "uses_force": bool(raw.get("uses_force", False)),
        "magic": magic,
        "skill_ratings": dict(raw.get("skill_ratings") or {}),
        "spells": list(raw.get("spells") or []),
        "spell_force": int(raw.get("spell_force", magic or 4)),
        "modifier": int(raw.get("modifier", 0)),
        "damage": int(raw.get("damage", 0)),
        "attributes": dict(raw.get("attributes") or {}),
        "edge": _optional_int(raw.get("edge")),
        "initiative": _optional_int(raw.get("initiative")),
        "initiative_dice": _optional_int(raw.get("initiative_dice")),
        "weapons": [str(weapon) for weapon in (raw.get("weapons") or [])],
        "armor": raw.get("armor"),
    }


def parse_import_file(content: bytes) -> list[dict]:
    """Liest eine exportierte Dashboard-JSON-Datei ein."""
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Keine gueltige JSON-Datei: {error}") from error

    if isinstance(data, list):
        npcs_raw = data
    elif isinstance(data, dict):
        if data.get("format") not in (None, EXPORT_FORMAT):
            raise ValueError("Unbekanntes Dateiformat.")
        npcs_raw = data.get("npcs", data.get("active_npcs"))
        if npcs_raw is None:
            raise ValueError("Keine NPC-Liste in der Datei gefunden.")
    else:
        raise ValueError("Ungueltiges Dateiformat.")

    if not isinstance(npcs_raw, list):
        raise ValueError("Die NPC-Liste muss ein Array sein.")
    if not npcs_raw:
        raise ValueError("Die Datei enthaelt keine NPCs.")

    return [import_npc(item) for item in npcs_raw]


def render_persistence_panel(active: list[dict]) -> None:
    """Export und Import der Dashboard-NPCs als JSON-Datei."""
    with st.expander("Speichern / Laden", expanded=not active):
        export_col, import_col = st.columns(2)

        with export_col:
            st.markdown("**Export**")
            st.caption(
                "Speichert alle NPCs inklusive Schaden, Modifikatoren, "
                "Zauber, Ausruestung und manueller Anpassungen."
            )
            st.download_button(
                "Dashboard-NPCs als Datei speichern",
                data=build_export_payload(active),
                file_name=export_filename(),
                mime="application/json",
                disabled=not active,
                width="stretch",
            )

        with import_col:
            st.markdown("**Import**")
            uploaded = st.file_uploader(
                "JSON-Datei laden",
                type=["json"],
                key="dashboard_import",
                help="Ersetzt das aktuelle Dashboard durch die NPCs aus der Datei.",
            )
            if uploaded is not None:
                file_id = f"{uploaded.name}:{uploaded.size}"
                if st.session_state.get("last_import_id") != file_id:
                    try:
                        entries = parse_import_file(uploaded.getvalue())
                    except ValueError as error:
                        st.error(str(error))
                        st.session_state["last_import_id"] = file_id
                    else:
                        st.session_state["active_npcs"] = entries
                        st.session_state["last_import_id"] = file_id
                        st.toast(f"{len(entries)} NPC(s) geladen.")
                        st.rerun()


def add_to_dashboard(config: dict) -> None:
    entry = copy_config(config)
    entry["uid"] = uuid.uuid4().hex[:8]
    entry["label"] = config["name"]
    st.session_state["active_npcs"].append(entry)
    st.toast(f"{config['name']} steht jetzt im Dashboard.")
    # Das Dashboard wird vor dem Generator gezeichnet, daher neu durchlaufen.
    st.rerun()


def render_damage_monitor(npc: engine.BaseNPC, config: dict) -> int:
    """Schadensmonitor der Karte. Gibt den Wundabzug als negative Zahl zurueck."""
    uid = config["uid"]
    key = f"dmg_{uid}"
    capacity = npc.damage_capacity

    # Sinkt die Kapazitaet (z. B. bei niedrigerer Konstitution), darf der
    # eingetragene Schaden nicht ueber dem neuen Maximum liegen.
    previous = st.session_state.get(key, config.get("damage", 0))
    st.session_state[key] = min(int(previous), capacity)

    damage = int(
        st.number_input(
            "Erlittener Schaden",
            min_value=0,
            max_value=capacity,
            step=1,
            key=key,
            help=f"Gemeinsamer Monitor: {capacity} Boxen "
            f"(hoeherer Wert aus {npc.physical_monitor} / {npc.stun_monitor}).",
        )
    )
    config["damage"] = damage

    wounds = pools.wound_modifier(damage)
    st.progress(damage / capacity if capacity else 0.0)

    status = f"Schaden: **{damage} / {capacity}** Boxen \u00b7 Wundabzug: **{wounds} W6**"
    if wounds:
        st.warning(status)
    else:
        st.caption(status)

    return wounds


def render_rename_control(config: dict, current_name: str) -> None:
    """Anzeigename auf der Dashboard-Karte aendern - nur label, nicht die CSV-Referenz."""
    uid = config["uid"]
    with st.popover("\u270f\ufe0f", help="Namen bearbeiten"):
        with st.form(key=f"rename_{uid}", clear_on_submit=False):
            new_name = st.text_input("Anzeigename", value=current_name, max_chars=80)
            submitted = st.form_submit_button("Speichern")
        if submitted:
            cleaned = new_name.strip()
            if not cleaned:
                st.warning("Der Name darf nicht leer sein.")
            elif cleaned != current_name:
                config["label"] = cleaned
                st.rerun()


def render_card(
    config: dict, frames: dict[str, pd.DataFrame], skill_map: dict[str, str]
) -> str | None:
    """Eine NPC-Karte im Dashboard. Gibt eine angeforderte Aktion zurueck."""
    uid = config["uid"]
    # Kraftstufe ist beim Beschwoeren fest - nur aus der Konfiguration, kein Regler.
    if config.get("archetype") == engine.ARCHETYPE_SPIRIT:
        config["force"] = int(config.get("force", 4))
    elif (
        config.get("archetype") == engine.ARCHETYPE_CRITTER
        and config.get("uses_force")
    ):
        config["force"] = int(config.get("force", 4))

    npc = build_npc(config, frames)
    if npc is None:
        st.error(f"'{config['name']}' kann nicht mehr geladen werden.")
        return None

    with st.container(border=True):
        display_name = config.get("label", npc.name)
        suffix = ""
        if isinstance(npc, engine.Spirit):
            suffix = f" (Kraftstufe {npc.force})"
        elif isinstance(npc, engine.Critter) and npc.uses_force:
            suffix = f" (Kraftstufe {npc.force})"

        title_col, edit_col = st.columns([0.93, 0.07], vertical_alignment="center")
        with title_col:
            st.markdown(f"### {display_name}{suffix}")
        with edit_col:
            render_rename_control(config, display_name)

        st.caption(archetype_label(config.get("archetype", npc.ARCHETYPE)))

        st.write(
            " \u00b7 ".join(
                f"{ATTRIBUTE_SHORT[label]} **{value}**"
                for label, value in npc.attributes.items()
            )
        )

        wounds = render_damage_monitor(npc, config)

        st.write(
            f"**Initiative:** {pools.initiative_line(npc, wounds=wounds)} \u00b7 "
            f"**Monitor:** {npc.physical_monitor} / {npc.stun_monitor}"
        )

        config["modifier"] = int(
            st.number_input(
                "Situative Modifikatoren (z. B. Deckung/Sicht)",
                min_value=-20,
                max_value=20,
                value=config.get("modifier", 0),
                step=1,
                key=f"mod_{uid}",
            )
        )

        npc_pools = pools.standard_pools(npc, skill_map, config["modifier"], wounds)
        render_dashboard_pools(npc_pools)

        render_card_details(npc, config, frames)

        duplicate, delete = st.columns(2)
        if duplicate.button("Duplizieren", key=f"dup_{uid}", width="stretch"):
            return "duplicate"
        if delete.button(LOESCHEN, key=f"del_{uid}", width="stretch"):
            return "delete"

    return None


def render_card_details(
    npc: engine.BaseNPC, config: dict, frames: dict[str, pd.DataFrame]
) -> None:
    """Lange Freitexte bleiben eingeklappt, damit das Dashboard ruhig bleibt."""
    uid = config["uid"]

    if isinstance(npc, engine.Spirit):
        with st.expander(KRAEFTE):
            render_spirit_powers(npc, frames.get(KRAEFTE), key=uid)

    if isinstance(npc, engine.MagicianNPC) and npc.spells:
        with st.expander(SECTION_SPELLS):
            config["spell_force"] = st.slider(
                "Kraftstufe (KS)",
                1,
                engine.MAX_FORCE,
                config.get("spell_force", npc.magic),
                key=f"ks_{uid}",
            )
            render_spell_tooltip_list(
                frames["Zauber"], npc.spells, force=config["spell_force"]
            )
            st.caption("Entzugswert ist immer mindestens 2. Maus ueber Zauber fuer Wirkung.")

    if isinstance(npc, engine.MundaneNPC):
        with st.expander(f"{SECTION_SKILLS} (Tabelle)"):
            st.dataframe(npc.skill_table(), width="stretch", hide_index=True)

    if npc.weapons or npc.armor_item is not None:
        with st.expander(SECTION_EQUIPMENT):
            for weapon in npc.weapons:
                st.write(
                    f"**{weapon.name}** \u00b7 Schaden {weapon.damage} \u00b7 "
                    f"DK {weapon.ap} \u00b7 Modus {weapon.mode}"
                )
            if npc.armor_item is not None:
                st.write(
                    f"**{npc.armor_item.name}** \u00b7 Panzerung "
                    f"{npc.armor_item.rating_text} \u2192 {npc.armor}"
                )


def render_dashboard(frames: dict[str, pd.DataFrame], skill_map: dict[str, str]) -> None:
    active = st.session_state["active_npcs"]

    render_persistence_panel(active)

    header, layout, clear = st.columns([5, 1, 1], vertical_alignment="bottom")
    header.caption(
        f"{len(active)} aktive NPCs. Die Wuerfel wirft der Spielleiter - "
        "das Tool nennt nur die Anzahl."
    )
    if active and clear.button("Alle entfernen", width="stretch"):
        st.session_state["active_npcs"] = []
        st.rerun()

    if not active:
        st.info(
            "Noch keine NPCs im Dashboard. Im Tab 'NPC-Generator' "
            "auf 'Zum Dashboard hinzufuegen' klicken."
        )
        return

    per_row = int(
        layout.selectbox(
            "Karten pro Seite", (1, 2, 3, 4, 5, 6), index=1, key="cards_per_page"
        )
    )

    for start in range(0, len(active), per_row):
        for column, config in zip(st.columns(per_row), active[start : start + per_row]):
            with column:
                action = render_card(config, frames, skill_map)
                if action == "delete":
                    active.remove(config)
                    st.rerun()
                if action == "duplicate":
                    copy = copy_config(config)
                    copy["uid"] = uuid.uuid4().hex[:8]
                    copy["label"] = f"{config.get('label', config['name'])} (Kopie)"
                    active.insert(active.index(config) + 1, copy)
                    st.rerun()


def render_database_browser(frames: dict[str, pd.DataFrame]) -> None:
    name = st.selectbox("Datenbank", list(frames))
    df = frames[name]
    st.write(f"{len(df)} {EINTRAEGE}, {len(df.columns)} Spalten (Index: '{df.index.name}')")
    st.dataframe(df, width="stretch")


def main() -> None:
    st.session_state.setdefault("active_npcs", [])

    frames, errors = load_databases()

    st.title(APP_TITLE)

    if not frames:
        st.error("Keine Datenbank konnte geladen werden.")
        return

    # Ladefehler sind zu wichtig, um sie in einem Tab zu verstecken.
    if errors:
        st.error(
            f"{len(errors)} Datenbank(en) konnten nicht geladen werden - "
            "Details im Tab 'Datenbanken'.",
            icon="\u26a0\ufe0f",
        )

    skill_map = pools.build_skill_attribute_map(frames.get("Fertigkeiten"))

    dashboard_tab, generator_tab, data_tab = st.tabs(
        [
            f"Dashboard ({len(st.session_state['active_npcs'])})",
            "NPC-Generator",
            "Datenbanken",
        ]
    )

    with dashboard_tab:
        render_dashboard(frames, skill_map)

    with generator_tab:
        render_generator(frames, skill_map)

    with data_tab:
        render_database_status(frames, errors)
        st.divider()
        render_database_browser(frames)


if __name__ == "__main__":
    main()
