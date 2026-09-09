"""Shadowrun 5 Spielleitertool - Hauptoberflaeche und Navigation."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import random
import re
import uuid
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

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

APP_TITLE = "Shadowrun 5 - Spielleitertool"
BANNER_PATH = Path(__file__).resolve().parent / "Banner_Spielleitertool.jpg"
ICON_DIR = Path(__file__).resolve().parent / "Icon"
ICON_DISPLAY_PX = 22

SECTION_ATTACK = "Angriff"
SECTION_DEFENSE = "Verteidigung & Schadenswiderstand"
SECTION_SKILLS = "Proben & Fertigkeiten"
SECTION_EQUIPMENT = "Ausr\u00fcstung"
SECTION_SPELLS = "Zauber & Entzug"

EXPORT_FORMAT = "shadowrun5-gm-dashboard"
EXPORT_VERSION = 2
_SAVE_NAME_SAFE = re.compile(r"[^A-Za-z0-9_\-]+")
MAX_IMPORT_BYTES = 512_000
MAX_IMPORT_NPCS = 80
MAX_IMPORT_INITIATIVE = 80
MAX_IMPORT_SPELLS = 40
MAX_IMPORT_WEAPONS = 4
MAX_IMPORT_SKILLS = 80
MAX_NAME_LEN = 80

INITIATIVE_PLAYER = "Spieler"
INITIATIVE_NPC = "NPC"
INITIATIVE_SHORT = 5
INITIATIVE_PASS = 10
INITIATIVE_STATE_KEY = "initiative_list"
INI_SELECTED_KEY = "ini_npc_multiselect"
CARDS_PER_ROW_KEY = "dashboard_cards_per_row"
GENERATOR_ARCHETYPE_KEY = "generator_archetype"
GENERATOR_ARCHETYPE_RADIO_KEY = "generator_archetype_radio"
GENERATOR_METATYPE_KEY = "generator_metatype"
GENERATOR_NAME_KEY = "generator_name"
MAIN_TAB_KEY = "main_tab"
TAB_DASHBOARD = "dashboard"
TAB_GENERATOR = "generator"
TAB_DATA = "data"

KEINE_WAFFE = "Keine"
KEINE_PANZERUNG = "Keine (Wert aus CSV)"

_NUMERIC_AP = re.compile(r"^[+-]?\d+$")
_BLANK_AP = {"", "-", "\u2013", "\u2014"}

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

THEME_PRIMARY = "#00E5FF"
THEME_PRIMARY_HOVER = "#00B8D4"
THEME_ON_PRIMARY = "#0E1117"


def _fold_icon_name(name: str) -> str:
    """Vergleicht Icon-Dateinamen ohne Umlaute und Satzzeichen."""
    swapped = (
        name.replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00c4", "ae")
        .replace("\u00d6", "oe")
        .replace("\u00dc", "ue")
        .replace("\u00df", "ss")
    )
    return "".join(char for char in swapped.casefold() if char.isalnum())


def _skill_sort_key(name: str) -> str:
    """Deutsche Alphabet-Sortierung: Umlaute wie Grundbuchstaben."""
    table = str.maketrans(
        {
            "\u00e4": "a",
            "\u00f6": "o",
            "\u00fc": "u",
            "\u00c4": "a",
            "\u00d6": "o",
            "\u00dc": "u",
            "\u00df": "ss",
        }
    )
    return str(name).translate(table).casefold()


def _icon_file(name: str) -> Path | None:
    if not ICON_DIR.is_dir():
        return None
    wanted = _fold_icon_name(name)
    fallback: Path | None = None
    for path in ICON_DIR.glob("*.png"):
        folded = _fold_icon_name(path.stem)
        if folded == wanted:
            return path
        if wanted.startswith("ausr") and folded.startswith("ausr"):
            fallback = path
    return fallback


def _icon_data_uri(path: Path, size: int = ICON_DISPLAY_PX) -> str:
    """Skaliert das PNG auf eine einheitliche Icon-Groesse."""
    image = Image.open(path).convert("RGBA")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(
        image,
        ((size - image.width) // 2, (size - image.height) // 2),
        image,
    )
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


@lru_cache(maxsize=64)
def _icon_markdown_cached(name: str, resolved: str, mtime: float) -> str:
    """Cache-Schluessel enthaelt mtime, damit geaenderte PNGs ohne Neustart gelten."""
    return f"![{name}]({_icon_data_uri(Path(resolved))})"


def icon_markdown(name: str) -> str:
    """PNG aus dem Ordner Icon als kleines Markdown-Bild, sonst leer."""
    match = _icon_file(name)
    if match is None:
        return ""
    try:
        mtime = match.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _icon_markdown_cached(name, str(match.resolve()), mtime)


def with_icon(icon_name: str, text: str = "") -> str:
    """Haengt das PNG-Icon vor den Text. Fehlt die Datei, bleibt der Text."""
    mark = icon_markdown(icon_name)
    if mark and text:
        return f"{mark} {text}"
    return mark or text


def archetype_label(archetype: str) -> str:
    """Anzeigename mit PNG-Icon - intern bleibt der Archetyp unveraendert."""
    return with_icon(archetype, archetype)


def preload_lazy_widgets() -> None:
    """Laedt Slider-JS beim ersten Seitenaufbau.

    Streamlit holt Slider.*.js erst, wenn das erste Slider-Widget erscheint.
    Beim Archetyp-Wechsel bricht dieser Nachlade-Import oft ab; der Browser
    merkt sich den Fehlschlag und zeigt danach nur noch den TypeError.
    Ein unsichtbarer Slider auf jeder Seite verhindert das.
    """
    st.markdown(
        """
        <style>
        div[class*="st-key-_preload_box"] {
            display: none !important;
            height: 0 !important;
            overflow: hidden !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="_preload_box"):
        st.slider(
            "preload",
            min_value=1,
            max_value=engine.MAX_FORCE,
            value=4,
            key="_preload_slider",
            label_visibility="collapsed",
        )


def render_main_nav(npc_count: int) -> str:
    """Nur der aktive Bereich wird gezeichnet - st.tabs laeuft immer komplett durch."""
    if st.session_state.get(MAIN_TAB_KEY) not in (
        TAB_DASHBOARD,
        TAB_GENERATOR,
        TAB_DATA,
    ):
        st.session_state[MAIN_TAB_KEY] = TAB_DASHBOARD

    current = st.session_state[MAIN_TAB_KEY]
    options = (
        (TAB_DASHBOARD, f"Dashboard ({npc_count})"),
        (TAB_GENERATOR, "NPC-Generator"),
        (TAB_DATA, "Datenbanken"),
    )
    columns = st.columns(len(options))
    for column, (tab_id, label) in zip(columns, options):
        if column.button(
            label,
            key=f"main_nav_{tab_id}",
            type="primary" if tab_id == current else "secondary",
            width="stretch",
        ):
            st.session_state[MAIN_TAB_KEY] = tab_id
            st.rerun()
    return st.session_state[MAIN_TAB_KEY]


DEFENSE_POOL_LABELS = ("Verteidigung", "Schadenswiderstand", "Entzug widerstehen")


def split_dashboard_pools(
    npc_pools: list[pools.DicePool],
    npc: engine.BaseNPC | None = None,
) -> tuple[list[pools.DicePool], list[pools.DicePool], list[pools.DicePool]]:
    """Teilt Pools in Angriff, Verteidigung und Proben/Fertigkeiten."""
    attacks: list[pools.DicePool] = []
    defenses: list[pools.DicePool] = []
    skills: list[pools.DicePool] = []
    for pool in npc_pools:
        if pool.label.startswith("Angriff"):
            attacks.append(pool)
        elif (
            isinstance(npc, engine.MagicianNPC)
            and pool.label in pools.MAGIC_ATTACK_SKILLS
        ):
            attacks.append(pool)
        elif (
            isinstance(npc, engine.Critter)
            and pool.label == "Waffenloser Kampf"
        ):
            attacks.append(pool)
        elif pool.label in DEFENSE_POOL_LABELS:
            defenses.append(pool)
        else:
            skills.append(pool)
    skills.sort(key=lambda pool: pool.label.casefold())
    return attacks, defenses, skills


def render_dashboard_pools(
    npc_pools: list[pools.DicePool],
    npc: engine.BaseNPC | None = None,
    detailed: bool = False,
) -> None:
    """Zeigt Wuerfelpools auf der Karte in thematischen Abschnitten."""
    attacks, defenses, skill_pools = split_dashboard_pools(npc_pools, npc)

    def _line(pool: pools.DicePool) -> str:
        return pool.text if detailed else pool.dashboard_text

    if defenses:
        st.markdown(f"**{with_icon('Verteidigung', SECTION_DEFENSE)}**")
        for pool in defenses:
            st.write(f"**{pool.label}:** {_line(pool)}")

    if attacks:
        st.markdown(f"**{with_icon('Angriff', SECTION_ATTACK)}**")
        for pool in attacks:
            line = _line(pool)
            if not detailed and pool.note:
                line += f" \u00b7 {pool.note}"
            st.write(f"**{pool.label}:** {line}")

    if not skill_pools:
        return

    if detailed:
        st.markdown(f"**{with_icon('Proben', SECTION_SKILLS)}**")
        for pool in skill_pools:
            st.write(f"**{pool.label}:** {_line(pool)}")
        return

    with st.expander(with_icon("Proben", SECTION_SKILLS)):
        for pool in skill_pools:
            st.write(f"**{pool.label}:** {_line(pool)}")


def format_limits_line(npc: engine.BaseNPC) -> str:
    """Kompakte Limitzeile fuer Karte und Generator."""
    return (
        f"**Limits:** k\u00f6rperlich **{npc.physical_limit()}** \u00b7 "
        f"geistig **{npc.mental_limit()}** \u00b7 "
        f"sozial **{npc.social_limit()}**"
    )


def render_dashboard_edge(
    npc: engine.BaseNPC, config: dict, frames: dict[str, pd.DataFrame]
) -> None:
    """Edge direkt unter den Limits, manuell aenderbar."""
    baseline = instantiate_npc(config, frames)
    natural_edge = int(baseline.edge) if baseline is not None else int(npc.edge)
    edge_key = f"edge_card_{config['uid']}"
    _seed_widget(edge_key, int(npc.edge))
    edge = int(
        st.number_input(
            "Edge",
            min_value=0,
            max_value=12,
            step=1,
            key=edge_key,
        )
    )
    config["edge"] = edge if edge != natural_edge else None
    engine.apply_overrides(npc, edge=edge)


def npc_magic_force(npc: engine.BaseNPC, config: dict | None) -> int | None:
    """Aktuelle Kraftstufe fuer das Limit von Spruchzauberei."""
    if not isinstance(npc, engine.MagicianNPC):
        return None
    if config is not None and npc.spells and config.get("spell_force"):
        return int(config["spell_force"])
    return int(npc.magic) if npc.magic else None


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
    layout="wide",
)


def inject_layout_css() -> None:
    """Kartenraster per st.html, nicht per Markdown.

    Markdown zerlegt CSS-Selektoren mit '>' und '*'. st.html mit nur
    <style> landet im Event-Container und bleibt nach Reruns erhalten.
    """
    rules: list[str] = []
    for columns in range(1, 7):
        rules.append(
            f".st-key-npc-grid-{columns}{{"
            "display:grid!important;"
            f"grid-template-columns:repeat({columns},minmax(0,1fr))!important;"
            "gap:0.6rem!important;"
            "align-items:start!important;"
            "}"
            f".st-key-npc-grid-{columns}>:only-child:not([class*='st-key-npc-card']){{"
            "display:contents!important;"
            "}"
            f".st-key-npc-grid-{columns}>*,"
            f".st-key-npc-grid-{columns} [class*='st-key-npc-card']{{"
            "min-width:0!important;"
            "max-width:100%!important;"
            "}"
        )
    rules.append(
        ".stCaption img,.stMarkdown img,[data-testid='stExpander'] img,"
        "[data-testid='stRadio'] img{"
        "height:1.15em!important;"
        "width:1.15em!important;"
        "max-height:1.15em!important;"
        "max-width:1.15em!important;"
        "object-fit:contain!important;"
        "vertical-align:-0.15em!important;"
        "}"
    )
    rules.append(_theme_override_css())
    rules.append(
        "div[class*='st-key-_theme_inject']{"
        "display:none!important;height:0!important;overflow:hidden!important;"
        "}"
    )
    st.html(f"<style>{''.join(rules)}</style>")
    _inject_theme_into_parent()


def _theme_override_css() -> str:
    """Cyan im Ruhezustand, nicht nur beim Hover."""
    primary = THEME_PRIMARY
    hover = THEME_PRIMARY_HOVER
    ink = THEME_ON_PRIMARY
    buttons = (
        ".stButton button,"
        ".stDownloadButton button,"
        ".stFormSubmitButton button,"
        "[data-testid='stBaseButton-primary'],"
        "[data-testid='stBaseButton-primaryFormSubmit'],"
        "[data-testid='stBaseButton-primaryNoPadding'],"
        "[data-testid='stBaseButton-secondary'],"
        "[data-testid='stBaseButton-tertiary'],"
        "button[kind='primary'],"
        "button[kind='secondary'],"
        "button[kind='tertiary']"
    )
    return (
        f":root,.stApp,[data-testid='stAppViewContainer'],[data-testid='stHeader']{{"
        f"--primary-color:{primary}!important;"
        f"--st-primary-color:{primary}!important;"
        f"--primary:{primary}!important;"
        "}"
        f"{buttons}{{"
        f"border-color:{primary}!important;"
        f"outline-color:{primary}!important;"
        "}"
        "[data-testid='stBaseButton-primary'],"
        "[data-testid='stBaseButton-primaryFormSubmit'],"
        "[data-testid='stBaseButton-primaryNoPadding'],"
        "button[kind='primary'],"
        ".stDownloadButton button,"
        ".stFormSubmitButton button{"
        f"background-color:{primary}!important;"
        f"background-image:none!important;"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stBaseButton-primary'] *,"
        "[data-testid='stBaseButton-primaryFormSubmit'] *,"
        "[data-testid='stBaseButton-primaryNoPadding'] *,"
        "button[kind='primary'] *,"
        ".stDownloadButton button *,"
        ".stFormSubmitButton button *{"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stBaseButton-secondary'],"
        "[data-testid='stBaseButton-tertiary'],"
        "button[kind='secondary'],"
        "button[kind='tertiary']{"
        f"color:{primary}!important;"
        f"background-color:transparent!important;"
        f"background-image:none!important;"
        "}"
        "[data-testid='stBaseButton-secondary'] *,"
        "[data-testid='stBaseButton-tertiary'] *,"
        "button[kind='secondary'] *,"
        "button[kind='tertiary'] *{"
        f"color:{primary}!important;"
        "}"
        f"{buttons}:hover{{"
        f"border-color:{hover}!important;"
        "}"
        "[data-testid='stBaseButton-secondary']:hover,"
        "[data-testid='stBaseButton-tertiary']:hover,"
        "button[kind='secondary']:hover,"
        "button[kind='tertiary']:hover,"
        "[data-testid='stBaseButton-secondary']:hover *,"
        "[data-testid='stBaseButton-tertiary']:hover *,"
        "button[kind='secondary']:hover *,"
        "button[kind='tertiary']:hover *{"
        f"color:{hover}!important;"
        "}"
        "[data-testid='stBaseButton-primary']:hover,"
        "[data-testid='stBaseButton-primaryFormSubmit']:hover,"
        "button[kind='primary']:hover,"
        ".stDownloadButton button:hover,"
        ".stFormSubmitButton button:hover{"
        f"background-color:{hover}!important;"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stBaseButton-primary']:hover *,"
        "[data-testid='stBaseButton-primaryFormSubmit']:hover *,"
        "button[kind='primary']:hover *,"
        ".stDownloadButton button:hover *,"
        ".stFormSubmitButton button:hover *{"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stSlider'] [role='slider'],"
        "[data-testid='stSlider'] [class*='e23vpic3'],"
        "[data-testid='stSliderThumb'],"
        "[data-testid='stSliderTickBarFilled']{"
        f"background:{primary}!important;"
        f"background-color:{primary}!important;"
        f"background-image:none!important;"
        f"border-color:{primary}!important;"
        "}"
        "[data-testid='stSlider'] *:has(> [data-testid='stSliderThumbValue']){"
        f"background:{primary}!important;"
        f"background-color:{primary}!important;"
        f"background-image:none!important;"
        f"border-color:{primary}!important;"
        "filter:none!important;"
        "}"
        "[data-testid='stSliderThumbValue'],"
        "[data-testid='stSliderThumbValue'] *,"
        "[data-testid='stSlider'] [class*='e23vpic4'],"
        "[data-testid='stThumbValue'],"
        "[data-testid='stThumbValue'] *{"
        f"color:{primary}!important;"
        "background:transparent!important;"
        "background-color:transparent!important;"
        "}"
        "[data-testid='stSlider'] [class*='e23vpic5']{"
        "filter:none!important;"
        "isolation:isolate!important;"
        "}"
        "[data-testid='stSlider'] [class*='e23vpic5']::after{"
        "content:'';"
        "position:absolute;"
        "inset:0;"
        f"background:{primary};"
        "mix-blend-mode:hue;"
        "pointer-events:none;"
        "}"
        "[data-testid='stSlider'] .react-aria-SliderTrack > :first-child{"
        "filter:none!important;"
        "isolation:isolate!important;"
        "}"
        "[data-testid='stSlider'] .react-aria-SliderTrack > :first-child::after{"
        "content:'';"
        "position:absolute;"
        "inset:0;"
        f"background:{primary};"
        "mix-blend-mode:hue;"
        "pointer-events:none;"
        "}"
        "[data-testid='stProgress'] [role='progressbar']>div,"
        "[data-testid='stProgressBar']>div{"
        f"background-color:{primary}!important;"
        "}"
        "[data-testid='stCheckbox'] input,"
        "[data-testid='stRadio'] input,"
        ".stCheckbox input,"
        ".stRadio input{"
        f"accent-color:{primary}!important;"
        "}"
        "[data-testid='stRadioOption'][data-selected] [class*='etak9234'],"
        "[data-testid='stRadio'] [data-selected] [class*='etak9234'],"
        "[data-testid='stRadioOption'][data-selected]>div>div>div:first-child,"
        "[class*='etak9231'][data-selected] [class*='etak9234']{"
        f"background:{primary}!important;"
        f"background-color:{primary}!important;"
        f"border-color:{primary}!important;"
        "}"
        "[data-testid='stCheckbox'] [data-selected] [class*='ew2p8o3'],"
        "[data-testid='stCheckbox'] label[data-selected]>div:first-of-type,"
        "[class*='ew2p8o2'][data-selected] [class*='ew2p8o3']{"
        f"background:{primary}!important;"
        f"background-color:{primary}!important;"
        f"border-color:{primary}!important;"
        "}"
        "div[class*='st-key-rename-btn'] [data-testid='stPopoverButton'],"
        "div[class*='st-key-rename-btn'] button{"
        "background:transparent!important;"
        "background-color:transparent!important;"
        "background-image:none!important;"
        "border:none!important;"
        "box-shadow:none!important;"
        "outline:none!important;"
        "min-height:2rem!important;"
        "padding:0.15rem!important;"
        "}"
        "div[class*='st-key-rename-btn'] [data-testid='stPopoverButton'] img,"
        "div[class*='st-key-rename-btn'] button img{"
        "height:22px!important;"
        "width:22px!important;"
        "max-height:22px!important;"
        "max-width:22px!important;"
        "object-fit:contain!important;"
        "}"
        "div[class*='st-key-rename-btn'] [data-testid='stPopoverButton'] svg,"
        "div[class*='st-key-rename-btn'] button svg{"
        "display:none!important;"
        "}"
        "[data-baseweb='slider'] [role='progressbar'],"
        "div[data-baseweb='slider']>div>div{"
        f"background-color:{primary}!important;"
        "}"
        "a,a:visited{"
        f"color:{primary}!important;"
        "}"
        "[data-testid='stButtonGroup'],"
        "[data-testid='stButtonGroup'] *:has(button),"
        "[data-testid='stButtonGroup'] [role='group'],"
        "[data-testid='stButtonGroup'] [role='radiogroup'],"
        "[data-testid='stButtonGroup'] [role='toolbar'],"
        "[data-variant='segmented_control']{"
        "border-color:#3D3D4A!important;"
        "outline:none!important;"
        "box-shadow:none!important;"
        "}"
        "[data-testid='stButtonGroup'] button,"
        "button[kind='segmented_control'],"
        "button[kind='segmented_controlActive']{"
        "border-color:#3D3D4A!important;"
        "outline:none!important;"
        "box-shadow:none!important;"
        "}"
        "[data-testid='stButtonGroup'] button[data-selected],"
        "[data-testid='stButtonGroup'] button[aria-checked='true'],"
        "[data-testid='stButtonGroup'] button[aria-pressed='true'],"
        "button[kind='segmented_controlActive']{"
        f"background-color:{primary}!important;"
        f"border-color:{primary}!important;"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stButtonGroup'] button[data-selected] *,"
        "[data-testid='stButtonGroup'] button[aria-checked='true'] *,"
        "[data-testid='stButtonGroup'] button[aria-pressed='true'] *,"
        "button[kind='segmented_controlActive'] *{"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stButtonGroup'] button[data-selected]:hover,"
        "[data-testid='stButtonGroup'] button[aria-checked='true']:hover,"
        "[data-testid='stButtonGroup'] button[aria-pressed='true']:hover{"
        f"background-color:{hover}!important;"
        f"border-color:{hover}!important;"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stButtonGroup'] button[data-selected]:hover *,"
        "[data-testid='stButtonGroup'] button[aria-checked='true']:hover *,"
        "[data-testid='stButtonGroup'] button[aria-pressed='true']:hover *{"
        f"color:{ink}!important;"
        "}"
        "[data-testid='stMultiSelect'] [data-tag],"
        "[data-testid='stMultiSelect'] [data-tag-index],"
        "[data-baseweb='tag']{"
        f"background:{primary}!important;"
        f"background-color:{primary}!important;"
        f"background-image:none!important;"
        f"border-color:{primary}!important;"
        f"color:{ink}!important;"
        "filter:none!important;"
        "}"
        "[data-testid='stMultiSelect'] [data-tag] *,"
        "[data-testid='stMultiSelect'] [data-tag] svg,"
        "[data-baseweb='tag'] *,"
        "[data-baseweb='tag'] svg{"
        f"color:{ink}!important;"
        f"fill:{ink}!important;"
        "}"
    )


def _inject_theme_into_parent() -> None:
    """Schreibt Cyan in das echte Browserfenster (Streamlit-Cloud-Iframe)."""
    css = json.dumps(_theme_override_css())
    script = (
        "<script>(function(){"
        "var doc;"
        "try{doc=window.parent.document;}catch(e){doc=document;}"
        f"var css={css};"
        "var id='sr5-cyan-theme';"
        "var tag=doc.getElementById(id);"
        "if(!tag){tag=doc.createElement('style');tag.id=id;}"
        "tag.textContent=css;"
        "doc.head.appendChild(tag);"
        "function isRed(c){"
        "var s=String(c||'').toLowerCase();"
        "if(!s||s==='transparent'||s==='none'||s==='rgba(0, 0, 0, 0)')return false;"
        "if(/#ff4b4b|#f63366|#ff2b2b|#e74c3c|#ff6b6b/.test(s))return true;"
        "var m=s.match(/rgba?\\(\\s*(\\d+(?:\\.\\d+)?)[\\s,\\/]+(\\d+(?:\\.\\d+)?)[\\s,\\/]+(\\d+(?:\\.\\d+)?)/);"
        "if(m){var r=+m[1],g=+m[2],b=+m[3];"
        "if(r<=1&&g<=1&&b<=1){r*=255;g*=255;b*=255;}"
        "return r>=180&&g<=150&&b<=150&&r>g+50&&r>b+50;}"
        "var o=s.match(/oklch\\(\\s*[\\d.]+\\s+[\\d.]+\\s+(\\d+(?:\\.\\d+)?)/);"
        "if(o){var h=+o[1];return h>=8&&h<=50;}"
        "return false;"
        "}"
        "function swapRed(t){"
        "return String(t||'').replace(/#ff4b4b|#f63366|#ff2b2b/gi,'#00E5FF')"
        ".replace(/rgb\\(\\s*255\\s*,\\s*75\\s*,\\s*75\\s*\\)/gi,'rgb(0, 229, 255)')"
        ".replace(/rgb\\(\\s*255\\s+75\\s+75(?:\\s*\\/\\s*[\\d.]+)?\\s*\\)/gi,'rgb(0, 229, 255)');"
        "}"
        "function recolorSheets(){"
        "try{"
        "doc.querySelectorAll('style').forEach(function(el){"
        "if(el.id===id)return;"
        "var t=el.textContent||'';"
        "if(!/#ff4b4b|#f63366|#ff2b2b|255\\s*,\\s*75\\s*,\\s*75|255\\s+75\\s+75/i.test(t))return;"
        "el.textContent=swapRed(t);"
        "});"
        "var sheets=[].slice.call(doc.styleSheets||[]);"
        "if(doc.adoptedStyleSheets)sheets=sheets.concat([].slice.call(doc.adoptedStyleSheets));"
        "sheets.forEach(function(sheet){"
        "try{"
        "var rules=sheet.cssRules||sheet.rules;if(!rules)return;"
        "for(var i=0;i<rules.length;i++){"
        "var rule=rules[i];"
        "if(!rule.style)continue;"
        "['backgroundColor','background','borderColor','accentColor','fill','color','outlineColor'].forEach(function(prop){"
        "var v=rule.style[prop];"
        "if(v&&isRed(v))rule.style.setProperty(prop.replace(/[A-Z]/g,function(ch){return '-'+ch.toLowerCase();}),'#00E5FF','important');"
        "});"
        "}"
        "}catch(e){}"
        "});"
        "}catch(e){}"
        "}"
        "function paintTracks(){"
        "try{"
        "doc.querySelectorAll('[data-testid=stSlider]').forEach(function(root){"
        "var value=root.querySelector('[data-testid=stSliderThumbValue]');"
        "if(!value||!value.parentElement||!value.parentElement.parentElement)return;"
        "var bar=value.parentElement.parentElement.children[0];"
        "if(!bar||bar.contains(value))return;"
        "var thumb=value.parentElement;"
        "var track=thumb.parentElement;"
        "var tr=track.getBoundingClientRect();"
        "var th=thumb.getBoundingClientRect();"
        "if(!tr.width)return;"
        "var pct=Math.max(0,Math.min(100,((th.left+th.width/2)-tr.left)/tr.width*100));"
        "bar.style.setProperty('background-image',"
        "'linear-gradient(to right,#00E5FF 0%,#00E5FF '+pct+'%,#3D3D4A '+pct+'%,#3D3D4A 100%)',"
        "'important');"
        "bar.style.setProperty('filter','none','important');"
        "});"
        "}catch(e){}"
        "}"
        "function paintChips(){"
        "try{"
        "doc.querySelectorAll('[data-testid=stMultiSelect] [data-tag],[data-baseweb=tag]').forEach(function(el){"
        "el.style.setProperty('background','#00E5FF','important');"
        "el.style.setProperty('background-color','#00E5FF','important');"
        "el.style.setProperty('background-image','none','important');"
        "el.style.setProperty('border-color','#00E5FF','important');"
        "el.style.setProperty('color','#0E1117','important');"
        "el.style.setProperty('filter','none','important');"
        "el.querySelectorAll('*').forEach(function(child){"
        "child.style.setProperty('color','#0E1117','important');"
        "child.style.setProperty('fill','#0E1117','important');"
        "});"
        "});"
        "}catch(e){}"
        "}"
        "function paintToggles(){"
        "try{"
        "doc.querySelectorAll("
        +"'[data-testid=stRadioOption][data-selected],"
        +"'[data-testid=stRadio] [data-selected],"
        +"'[data-testid=stCheckbox] [data-selected]'"
        +").forEach(function(item){"
        "item.querySelectorAll("
        +"'[class*=etak9234],[class*=ew2p8o3]'"
        +").forEach(function(el){"
        "el.style.setProperty('background','#00E5FF','important');"
        "el.style.setProperty('background-color','#00E5FF','important');"
        "el.style.setProperty('border-color','#00E5FF','important');"
        "});"
        "});"
        "doc.querySelectorAll('[data-testid=stRadio] input,[data-testid=stCheckbox] input').forEach(function(el){"
        "el.style.setProperty('accent-color','#00E5FF','important');"
        "});"
        "}catch(e){}"
        "}"
        "function paint(){"
        "recolorSheets();"
        "try{"
        "doc.querySelectorAll('[data-testid=stCheckbox],[data-testid=stRadio],.stCheckbox,.stRadio,[data-testid=stSlider],[data-testid=stButtonGroup],[data-testid=stMultiSelect]').forEach(function(root){"
        "root.querySelectorAll('div,span,button,p').forEach(function(el){"
        "if(el.closest('[data-testid=stWidgetLabel],[data-testid=stMarkdown],[data-testid=stCaption]'))return;"
        "var view=doc.defaultView;if(!view)return;"
        "var cs=view.getComputedStyle(el);"
        "var onGroup=root.getAttribute('data-testid')==='stButtonGroup';"
        "var selected=el.getAttribute('data-selected')!=null||el.getAttribute('aria-checked')==='true'"
        "||el.getAttribute('aria-pressed')==='true';"
        "if(isRed(cs.backgroundColor)&&!onGroup)"
        "el.style.setProperty('background-color','#00E5FF','important');"
        "if(isRed(cs.color)&&root.getAttribute('data-testid')==='stSlider')"
        "el.style.setProperty('color','#00E5FF','important');"
        "if(isRed(cs.borderColor)||isRed(cs.borderTopColor)||isRed(cs.outlineColor)){"
        "var tone=(onGroup&&!selected)?'#3D3D4A':'#00E5FF';"
        "el.style.setProperty('border-color',tone,'important');"
        "if(onGroup){"
        "el.style.setProperty('outline','none','important');"
        "el.style.setProperty('box-shadow','none','important');"
        "}"
        "}"
        "});"
        "});"
        "}catch(e){}"
        "paintTracks();"
        "paintChips();"
        "paintToggles();"
        "}"
        "var scheduled=false;"
        "function requestPaint(){"
        "if(scheduled)return;"
        "scheduled=true;"
        "requestAnimationFrame(function(){scheduled=false;paint();});"
        "}"
        "paint();"
        "if(!doc.documentElement.__sr5ThemeWatch5){"
        "doc.documentElement.__sr5ThemeWatch5=true;"
        "new MutationObserver(requestPaint).observe(doc.documentElement,"
        "{subtree:true,childList:true,attributes:true,"
        "attributeFilter:['style','class','aria-checked','data-selected']});"
        "doc.addEventListener('pointermove',requestPaint,true);"
        "}"
        "})();</script>"
    )
    with st.container(key="_theme_inject"):
        st.iframe(script, height=1)


def render_cards_per_row_control() -> int:
    """Spaltenzahl in Session-State, nicht als Radio-Widget.

    st.radio mit Zahlen 1-6 setzt den Wert nach einem Rerun oft auf den
    Default (2) zurueck. Buttons schreiben nur in einen eigenen Key.
    """
    current = int(st.session_state.get(CARDS_PER_ROW_KEY, 2))
    label, *buttons = st.columns([2.2, *([1] * 6)], vertical_alignment="center")
    label.caption("Karten pro Zeile")
    for column, count in zip(buttons, range(1, 7)):
        if column.button(
            str(count),
            key=f"cards_per_row_btn_{count}",
            type="primary" if count == current else "secondary",
            width="stretch",
        ):
            st.session_state[CARDS_PER_ROW_KEY] = count
            st.rerun()
    return int(st.session_state.get(CARDS_PER_ROW_KEY, 2))


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


def instantiate_npc(
    config: dict, frames: dict[str, pd.DataFrame]
) -> engine.BaseNPC | None:
    """NPC aus CSV/Formel, ohne manuelle Overrides und ohne Ausruestung."""
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
            tradition=config.get("tradition"),
        )
    except KeyError:
        return None
    npc = apply_metatype_from_frames(npc, config, frames)
    if isinstance(npc, engine.Critter) and not npc.uses_force:
        catalog = engine.catalog_skill_names(
            frames.get(engine.ARCHETYPE_DATABASE[engine.ARCHETYPE_MUNDANE])
        )
        npc.skills = {name: 0 for name in catalog}
    return npc


def apply_metatype_from_frames(
    npc: engine.BaseNPC, config: dict, frames: dict[str, pd.DataFrame]
) -> engine.BaseNPC:
    """Rechnet den gewaehlten Metatyp auf Mundan- und Zauberer-Vorlagen."""
    if not engine.uses_metatype(config.get("archetype", "")):
        return npc
    name = config.get("metatype")
    table = frames.get(engine.METATYPE_DATABASE)
    if not name or table is None:
        return npc
    try:
        return engine.apply_metatype(npc, engine.get_row(table, name))
    except KeyError:
        return npc


def npc_baselines(npc: engine.BaseNPC) -> dict:
    """Ausgangswerte zum Vergleich, bevor Overrides den NPC veraendern."""
    return {
        "attributes": dict(npc.attributes),
        "edge": int(npc.edge),
        "initiative_dice": int(npc.initiative_dice),
        "initiative": npc.natural_initiative_base(),
        "armor": engine.natural_armor_value(npc),
    }


def build_npc(config: dict, frames: dict[str, pd.DataFrame]) -> engine.BaseNPC | None:
    """Erzeugt den NPC neu aus seiner gespeicherten Konfiguration."""
    npc = instantiate_npc(config, frames)
    if npc is None:
        return None

    engine.apply_overrides(
        npc,
        attributes=config.get("attributes"),
        edge=config.get("edge"),
        initiative_base=config.get("initiative"),
        initiative_dice=config.get("initiative_dice"),
        skills=config.get("skill_ratings"),
    )
    equip_from_config(npc, config, frames)
    return npc


def catalog_key(df: pd.DataFrame, name: object) -> object | None:
    """Findet einen CSV-Indexeintrag robust, auch bei geklammerten Doppelungen."""
    if df is None or name is None:
        return None
    text = str(name).strip()
    if not text or text == KEINE_WAFFE:
        return None
    try:
        return engine.resolve_row_name(df, text)
    except KeyError:
        return None


def equip_from_config(
    npc: engine.BaseNPC, config: dict, frames: dict[str, pd.DataFrame]
) -> None:
    """Waffen und Panzerung aus der Konfiguration an den NPC haengen."""
    weapon_db = frames.get("Waffen")
    weapons = []
    if weapon_db is not None:
        overrides = list(config.get("weapon_ap") or [])
        slot = 0
        for name in config.get("weapons", []):
            key = catalog_key(weapon_db, name)
            if key is None:
                continue
            weapon = engine.load_weapon(weapon_db, key)
            if slot < len(overrides) and overrides[slot] not in (None, ""):
                weapon = weapon.with_ap(str(overrides[slot]))
            weapons.append(weapon)
            slot += 1

    armor_db = frames.get(RUESTUNG)
    armor_name = config.get("armor")
    armor = None
    if armor_db is not None:
        armor_key = catalog_key(armor_db, armor_name)
        if armor_key is not None:
            armor = engine.load_armor(armor_db, armor_key)

    engine.equip(npc, weapons, armor, armor_rating=config.get("armor_rating"))


def select_npc_config(frames: dict[str, pd.DataFrame]) -> dict | None:
    """Auswahl von Archetyp und Name - im Hauptbereich, damit keine Sidebar noetig ist."""
    st.markdown("**NPC erstellen**")

    saved = st.session_state.get(GENERATOR_ARCHETYPE_KEY, engine.ARCHETYPE_MUNDANE)
    if saved not in engine.ARCHETYPES:
        saved = engine.ARCHETYPE_MUNDANE
    # Eigenen Speicher, den Streamlit beim Tabwechsel nicht loescht. Fehlt
    # der Radio-Key (Tab war nicht sichtbar), wird er hier wiederhergestellt.
    if GENERATOR_ARCHETYPE_RADIO_KEY not in st.session_state:
        st.session_state[GENERATOR_ARCHETYPE_RADIO_KEY] = saved

    archetype = st.radio(
        "Archetyp",
        engine.ARCHETYPES,
        horizontal=True,
        format_func=archetype_label,
        key=GENERATOR_ARCHETYPE_RADIO_KEY,
    )
    st.session_state[GENERATOR_ARCHETYPE_KEY] = archetype
    database = engine.ARCHETYPE_DATABASE[archetype]
    df = frames.get(database)
    if df is None:
        st.error(f"Datenbank '{database}' ist nicht geladen.")
        return None

    metatype: str | None = None
    if engine.uses_metatype(archetype):
        meta_df = frames.get(engine.METATYPE_DATABASE)
        if meta_df is None:
            st.error(
                f"Datenbank '{engine.METATYPE_DATABASE}' ist nicht geladen."
            )
            return None
        metatypes = [str(name) for name in dict.fromkeys(meta_df.index)]
        if not metatypes:
            st.warning("Keine Metatypen vorhanden.")
            return None
        _ensure_choice(GENERATOR_METATYPE_KEY, metatypes)
        metatype = st.selectbox("Metatyp", metatypes, key=GENERATOR_METATYPE_KEY)

    if engine.uses_metatype(archetype):
        names = engine.template_names(df, archetype)
    else:
        names = sorted(dict.fromkeys(df.index))
    if not names:
        st.warning("Keine Auswahl vorhanden.")
        return None

    _ensure_choice(GENERATOR_NAME_KEY, names)

    if engine.uses_metatype(archetype):
        if archetype == engine.ARCHETYPE_MAGICIAN:
            name_col, skill_col, magic_col, trad_col = st.columns(
                (1.15, 1.55, 0.95, 1.15)
            )
        else:
            name_col, skill_col = st.columns((1.2, 2.8))
            magic_col = trad_col = None
        name = name_col.selectbox(
            "Name",
            names,
            key=GENERATOR_NAME_KEY,
            format_func=template_display_name,
        )
    elif archetype == engine.ARCHETYPE_CRITTER:
        extra_col = None
        if "Kategorie" in df.columns:
            kat_col, name_col, extra_col = st.columns((1.0, 1.15, 1.85))
            categories = ["Alle"] + sorted(df["Kategorie"].dropna().unique())
            category = kat_col.selectbox("Kategorie", categories)
            if category != "Alle":
                df = df[df["Kategorie"] == category]
        else:
            name_col, extra_col = st.columns((1.2, 2.8))
        usable = df.apply(engine.critter_row_is_complete, axis=1)
        hidden = int((~usable).sum())
        df = df[usable]
        if hidden:
            st.caption(
                f"{hidden} Critter ohne Attributswerte ausgeblendet (z. B. Bugul)."
            )
        names = sorted(dict.fromkeys(df.index))
        if not names:
            st.warning("Keine Auswahl vorhanden.")
            return None
        _ensure_choice(GENERATOR_NAME_KEY, names)
        name = name_col.selectbox(
            "Name",
            names,
            key=GENERATOR_NAME_KEY,
            format_func=template_display_name,
        )
    else:
        fields = st.columns(3)
        slot = 0
        name = fields[slot].selectbox(
            "Name",
            names,
            key=GENERATOR_NAME_KEY,
            format_func=template_display_name,
        )
        slot += 1

    config = {
        "uid": "",
        "archetype": archetype,
        "name": name,
        "metatype": metatype,
        "force": 4,
        "uses_force": False,
        "magic": None,
        "skill_ratings": {},
        "selected_skills": [],
        "spells": [],
        "spell_force": 4,
        "tradition": engine.TRADITION_HERMETIC,
        "modifier": 0,
        "damage": 0,
        "attributes": {},
        "edge": None,
        "initiative": None,
        "initiative_dice": None,
        "armor_rating": None,
        "weapons": [],
        "weapon_ap": [],
        "armor": None,
    }

    if engine.uses_metatype(archetype):
        _render_skill_catalog_picker(skill_col, config, frames)

    if archetype == engine.ARCHETYPE_SPIRIT:
        config["force"] = int(
            fields[slot].slider("Kraftstufe (F)", 1, engine.MAX_FORCE, 4)
        )
    elif archetype == engine.ARCHETYPE_CRITTER:
        row = engine.get_row(df, name)
        config["uses_force"] = engine.critter_uses_force(row)
        if config["uses_force"]:
            config["force"] = int(
                extra_col.slider("Kraftstufe (F)", 1, engine.MAX_FORCE, 4)
            )
        else:
            _render_skill_catalog_picker(extra_col, config, frames)
    elif archetype == engine.ARCHETYPE_MAGICIAN:
        row = engine.get_row(df, name)
        magic_key = f"generator_magic_{name}"
        magic_preset = min(
            engine.MAX_FORCE,
            max(1, engine.to_int(row.get("Magie"))),
        )
        _seed_widget(magic_key, magic_preset)
        config["magic"] = int(
            magic_col.slider(
                "Magie-Attribut",
                1,
                engine.MAX_FORCE,
                key=magic_key,
                help="Unabhaengig vom Wert in der CSV frei waehlbar.",
            )
        )
        _render_tradition_control(
            config,
            f"generator_tradition_{name}",
            container=trad_col,
        )
        config["spells"] = select_spells(frames.get("Zauber"), f"{archetype}|{name}")
        config["spell_force"] = config["magic"]

    return config


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


def preview_selected_armor(
    frames: dict[str, pd.DataFrame], state_key: str
) -> engine.Armor | None:
    """Liest die bereits gewaehlte Generator-Panzerung aus dem Session State."""
    selected = st.session_state.get(f"armor_{state_key}")
    if not selected or selected == KEINE_PANZERUNG:
        return None
    armor_db = frames.get(RUESTUNG)
    if armor_db is None:
        return None
    armor_key = catalog_key(armor_db, selected)
    if armor_key is None:
        return None
    return engine.load_armor(armor_db, armor_key)


def _ensure_choice(key: str, options: list[str]) -> None:
    """Haelt einen Selectbox-Wert in der aktuellen Optionsliste."""
    if not options:
        return
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]


def template_display_name(name: str) -> str:
    """CSV-Unterstriche nur in der Anzeige durch Leerzeichen ersetzen."""
    return str(name).replace("_", " ")


def default_npc_label(config: dict) -> str:
    pretty = template_display_name(config["name"])
    metatype = config.get("metatype")
    if metatype:
        return f"{pretty} ({metatype})"
    return pretty


def npc_source_line(npc: engine.BaseNPC) -> str:
    """Fundstelle fuer die Kopfzeile; leer, wenn in der CSV nichts steht."""
    source = engine.to_text(getattr(npc, "source", ""))
    if source in {"", "-"}:
        return ""
    return source


def _seed_widget(key: str, value: object) -> None:
    """Setzt den Widget-Startwert nur beim ersten Erscheinen, nie zusammen mit value=."""
    if key not in st.session_state:
        st.session_state[key] = value


def render_attribute_editor(
    npc: engine.BaseNPC,
    config: dict,
    state_key: str,
    frames: dict[str, pd.DataFrame] | None = None,
) -> None:
    """Attribute, Edge und Initiative direkt anpassbar - alle Pools rechnen live nach."""
    st.markdown("**Attribute** - mit den Pfeilen anpassen")

    # Ausgangswerte immer aus der unveraenderten CSV/Formel, nicht vom
    # bereits ueberschriebenen NPC. Sonst gehen Edge/INI/Attribute nach
    # einem Rerun verloren.
    baseline_npc = instantiate_npc(config, frames or {}) if frames else None
    if baseline_npc is None:
        baselines = npc_baselines(npc)
    else:
        baselines = npc_baselines(baseline_npc)
    natural_attributes = baselines["attributes"]
    natural_edge = baselines["edge"]
    natural_dice = baselines["initiative_dice"]
    natural_armor = baselines["armor"]
    selected_armor = preview_selected_armor(frames or {}, state_key)
    preview_armor = engine.worn_armor_total(natural_armor, selected_armor)

    values: dict[str, int] = {}
    items = list(npc.attributes.items())
    for start in range(0, len(items), 4):
        columns = st.columns(4)
        for column, (label, value) in zip(columns, items[start : start + 4]):
            attr_key = f"attr_{state_key}_{label}"
            _seed_widget(attr_key, int(value))
            values[label] = int(
                column.number_input(
                    label,
                    min_value=0,
                    max_value=30,
                    step=1,
                    key=attr_key,
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
    edge_key = f"edge_{state_key}"
    _seed_widget(edge_key, int(npc.edge))
    edge = int(columns[0].number_input("Edge", 0, 12, step=1, key=edge_key))
    # Der Schluessel enthaelt den natuerlichen Wert: aendern sich Reaktion oder
    # Intuition, startet das Feld wieder beim neu berechneten Basiswert.
    natural = npc.natural_initiative_base()
    ini_key = f"ini_{state_key}_{natural}"
    _seed_widget(ini_key, natural)
    initiative = int(
        columns[1].number_input(
            "Initiative-Basis",
            0,
            60,
            step=1,
            key=ini_key,
            help=(
                "Standard: (F x 2) + Aenderung Initiative"
                if isinstance(npc, engine.Spirit)
                else "Standard: Reaktion + Intuition"
            ),
        )
    )
    dice_key = f"dice_{state_key}"
    _seed_widget(dice_key, int(npc.initiative_dice))
    dice = int(
        columns[2].number_input(
            "Initiativw\u00fcrfel (W6)", 1, 5, step=1, key=dice_key
        )
    )
    armor_suffix = selected_armor.name if selected_armor is not None else "csv"
    armor_key = f"panzer_{state_key}_{armor_suffix}"
    _seed_widget(armor_key, preview_armor)
    armor_rating = int(
        columns[3].number_input(
            "Panzerung",
            0,
            engine.MAX_FORCE * 2,
            step=1,
            key=armor_key,
            help="Grundwert aus der CSV, bei Geistern Immunitaet 2 x F, frei anpassbar.",
        )
    )

    config["edge"] = edge if edge != natural_edge else None
    config["initiative"] = initiative if initiative != natural else None
    config["initiative_dice"] = dice if dice != natural_dice else None
    config["armor_rating"] = armor_rating if armor_rating != preview_armor else None
    engine.apply_overrides(
        npc,
        armor=armor_rating,
        edge=edge,
        initiative_base=config["initiative"],
        initiative_dice=dice,
    )


def render_spirit_skill_editor(
    npc: engine.Spirit | engine.Critter,
    config: dict,
    state_key: str,
    frames: dict[str, pd.DataFrame] | None = None,
) -> None:
    """Geist-Fertigkeiten: Standard = Kraftstufe, manuell anpassbar."""
    st.markdown("**Fertigkeiten** - mit den Pfeilen anpassen")

    baseline_npc = instantiate_npc(config, frames or {}) if frames else None
    source = (
        baseline_npc
        if isinstance(baseline_npc, (engine.Spirit, engine.Critter))
        else npc
    )
    natural_rating = int(getattr(source, "force", 0) or 0)
    items = [
        (skill, natural_rating)
        for skill in getattr(source, "skills", {}) or {}
    ]
    if not items:
        config["skill_ratings"] = {}
        return

    values: dict[str, int] = {}
    for start in range(0, len(items), 4):
        columns = st.columns(4)
        for column, (label, preset) in zip(columns, items[start : start + 4]):
            skill_key = f"skill_{state_key}_{label}"
            _seed_widget(skill_key, int(preset))
            values[label] = int(
                column.number_input(
                    label,
                    min_value=0,
                    max_value=engine.MAX_FORCE,
                    step=1,
                    key=skill_key,
                )
            )

    config["skill_ratings"] = {
        name: rating
        for name, rating in values.items()
        if rating != natural_rating
    }
    engine.apply_overrides(npc, skills=values)


def _render_skill_catalog_picker(
    container, config: dict, frames: dict[str, pd.DataFrame]
) -> None:
    """Alle Fertigkeiten waehlbar; Vorlage plus Metatyp sind vorbelegt."""
    npc = instantiate_npc(config, frames)
    skills = getattr(npc, "skills", None) or {}
    is_open_critter = isinstance(npc, engine.Critter) and not npc.uses_force
    if not isinstance(npc, engine.MundaneNPC) and not is_open_critter:
        config["selected_skills"] = []
        return
    options = sorted(skills.keys(), key=_skill_sort_key)
    if is_open_critter:
        preset: list[str] = []
        help_text = (
            "Keine Vorbelegung, weil Critter zu unterschiedlich sind. "
            "Abwahl gilt als ungeuebt. Wechsel des Namens setzt die Auswahl zurueck."
        )
    else:
        preset = sorted(
            (name for name, rating in skills.items() if int(rating) > 0),
            key=_skill_sort_key,
        )
        help_text = (
            "Vorbelegt mit den Fertigkeiten aus der Vorlage (Stufe > 0). "
            "Abwahl gilt als ungeuebt. Wechsel von Name oder Metatyp setzt "
            "auf die Grunddaten zurueck."
        )
    widget_key = (
        f"generator_selected_skills_{config['archetype']}_"
        f"{config.get('metatype')}_{config['name']}"
    )
    allowed = set(options)
    if widget_key not in st.session_state:
        st.session_state[widget_key] = list(preset)
    else:
        current = st.session_state.get(widget_key) or []
        filtered = [name for name in current if name in allowed]
        if filtered != list(current):
            st.session_state[widget_key] = filtered
    selected = container.multiselect(
        "Fertigkeiten",
        options,
        key=widget_key,
        help=help_text,
        placeholder="Fertigkeiten waehlen",
    )
    chosen = set(selected or [])
    config["selected_skills"] = [name for name in options if name in chosen]


def render_skill_editor(
    npc: engine.BaseNPC,
    config: dict,
    state_key: str,
    frames: dict[str, pd.DataFrame] | None = None,
) -> None:
    """Gewaehlte Fertigkeiten wie Attribute: Ueberschrift und Zahlenfelder."""
    st.markdown("**Fertigkeiten** - mit den Pfeilen anpassen")

    baseline_npc = instantiate_npc(config, frames or {}) if frames else None
    source = (
        baseline_npc
        if getattr(baseline_npc, "skills", None) is not None
        else npc
    )
    natural = {
        name: int(value) for name, value in getattr(source, "skills", {}).items()
    }
    trained = [name for name, value in natural.items() if value > 0]
    selected = config.get("selected_skills")
    if selected is None:
        selected = trained
    selected = sorted(
        (name for name in natural if name in set(selected)),
        key=_skill_sort_key,
    )
    items = [(name, natural[name]) for name in selected]
    if not items:
        st.caption("Keine Fertigkeiten gewaehlt.")
        applied = {name: 0 for name in natural}
        config["skill_ratings"] = {
            name: rating
            for name, rating in applied.items()
            if rating != natural[name]
        }
        engine.apply_overrides(npc, skills=applied)
        return

    values: dict[str, int] = {}
    for start in range(0, len(items), 4):
        columns = st.columns(4)
        for column, (label, preset) in zip(columns, items[start : start + 4]):
            skill_key = f"skill_{state_key}_{label}"
            _seed_widget(skill_key, int(preset))
            values[label] = int(
                column.number_input(
                    label,
                    min_value=0,
                    max_value=engine.MAX_FORCE,
                    step=1,
                    key=skill_key,
                )
            )

    applied = {
        name: int(values[name]) if name in values else 0 for name in natural
    }
    config["skill_ratings"] = {
        name: rating
        for name, rating in applied.items()
        if rating != natural[name]
    }
    engine.apply_overrides(npc, skills=applied)


def _render_tradition_control(
    config: dict,
    widget_key: str,
    npc: engine.MagicianNPC | None = None,
    container=None,
) -> None:
    target = container if container is not None else st
    control_kwargs: dict = {
        "options": engine.TRADITIONS,
        "key": widget_key,
        "help": "Hermetiker: WIL + LOG. Schamane: WIL + CHA.",
    }
    if widget_key not in st.session_state:
        control_kwargs["default"] = (
            config.get("tradition") or engine.TRADITION_HERMETIC
        )
    tradition = target.segmented_control("Tradition", **control_kwargs)
    if tradition not in engine.DRAIN_ATTRIBUTE:
        tradition = engine.TRADITION_HERMETIC
    config["tradition"] = tradition
    if npc is not None:
        npc.tradition = tradition


def render_equipment(
    npc: engine.BaseNPC,
    config: dict,
    frames: dict[str, pd.DataFrame],
    skill_map: dict[str, str],
    state_key: str,
) -> None:
    """Waffen und Panzerung waehlen; die Panzerung ersetzt den CSV-Grundwert."""
    st.markdown(f"**{with_icon('Ausruestung', AUSRUESTUNG)}**")

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

    config["weapons"] = [
        str(name).strip()
        for name in (first, second)
        if name and name != KEINE_WAFFE
    ]
    config["armor"] = None if armor_name == KEINE_PANZERUNG else armor_name
    # DK-Overrides erst nach den Eingabefeldern, damit der Katalogwert als
    # Ausgangswert in den Widgets steht.
    config["weapon_ap"] = []
    equip_from_config(npc, config, frames)

    if npc.armor_item is not None:
        item = npc.armor_item
        hint = "ergaenzt den Grundwert" if item.is_accessory else "ersetzt den Grundwert"
        st.caption(
            f"{item.name}: Panzerung {item.rating_text} ({hint}) \u2192 "
            f"Panzerung des NPC jetzt **{npc.armor}** \u00b7 {item.source}"
        )

    adjusted: list[engine.Weapon] = []
    ap_values: list[str] = []
    for slot, weapon in enumerate(npc.weapons):
        ap_text = render_weapon(npc, weapon, skill_map, slot, state_key)
        ap_values.append(ap_text)
        adjusted.append(weapon if ap_text == weapon.ap else weapon.with_ap(ap_text))
    config["weapon_ap"] = ap_values
    npc.weapons = adjusted


def _dk_is_numeric(value: object) -> bool:
    text = str(value).strip()
    return text in _BLANK_AP or bool(_NUMERIC_AP.fullmatch(text))


def render_weapon(
    npc: engine.BaseNPC,
    weapon: engine.Weapon,
    skill_map: dict[str, str],
    slot: int,
    state_key: str,
) -> str:
    with st.container(border=True):
        st.markdown(f"**{weapon.name}** \u00b7 {weapon.weapon_type}")

        columns = st.columns(3)
        columns[0].metric("Schaden", weapon.damage)
        widget_key = f"dk_{state_key}_{slot}_{weapon.name}"
        if _dk_is_numeric(weapon.ap):
            preset = 0 if str(weapon.ap).strip() in _BLANK_AP else int(str(weapon.ap).strip())
            _seed_widget(widget_key, preset)
            ap_text = str(
                int(
                    columns[1].number_input(
                        "DK",
                        min_value=-20,
                        max_value=20,
                        step=1,
                        key=widget_key,
                        help=f"Katalogwert: {weapon.ap}",
                    )
                )
            )
        else:
            _seed_widget(widget_key, weapon.ap)
            ap_text = str(
                columns[1].text_input(
                    "DK",
                    key=widget_key,
                    help=f"Katalogwert: {weapon.ap}",
                )
            ).strip() or weapon.ap
        columns[2].metric("Modus", weapon.mode)

        pool = pools.attack_pool(npc, weapon, skill_map)
        st.success(f"**{pool.label}:** {pool.text}")

        st.caption(
            f"{engine.PRAEZISION} {weapon.accuracy} \u00b7 RK {weapon.recoil} \u00b7 "
            f"Munition {weapon.ammo} \u00b7 {weapon.source}"
        )
    return ap_text


def render_details(
    npc: engine.BaseNPC,
    config: dict | None = None,
    state_key: str = "",
) -> None:
    details = npc.details()
    slots: list[tuple] = [("metric", label, value) for label, value in details.items()]
    if isinstance(npc, engine.MagicianNPC) and config is not None:
        inserted = False
        with_tradition: list[tuple] = []
        for slot in slots:
            with_tradition.append(slot)
            if slot[1] == "Magie":
                with_tradition.append(("tradition",))
                inserted = True
        if not inserted:
            with_tradition.append(("tradition",))
        slots = with_tradition

    columns = st.columns(min(4, len(slots)) or 1)
    for index, slot in enumerate(slots):
        column = columns[index % len(columns)]
        if slot[0] == "metric":
            column.metric(slot[1], slot[2])
            continue

        widget_key = f"tradition_{state_key}"
        control_kwargs: dict = {
            "options": engine.TRADITIONS,
            "key": widget_key,
            "help": "Hermetiker: WIL + LOG. Schamane: WIL + CHA.",
        }
        if widget_key not in st.session_state:
            control_kwargs["default"] = (
                config.get("tradition") or engine.TRADITION_HERMETIC
            )
        tradition = column.segmented_control("Tradition", **control_kwargs)
        if tradition not in engine.DRAIN_ATTRIBUTE:
            tradition = engine.TRADITION_HERMETIC
        config["tradition"] = tradition
        npc.tradition = tradition


def resolve_power_lookup(power_db: pd.DataFrame, power: str) -> object | None:
    """Vollstaendiger Kraftname zuerst, sonst der Teil vor der Klammer."""
    text = str(power).strip()
    if not text:
        return None
    try:
        return engine.resolve_row_name(power_db, text)
    except KeyError:
        pass
    short = text.split(" (")[0].strip()
    if short and short != text:
        try:
            return engine.resolve_row_name(power_db, short)
        except KeyError:
            return None
    return None


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
        if resolve_power_lookup(power_db, power) is not None
    ]
    if not choices:
        return

    selected = st.selectbox("Kraft nachschlagen", choices, key=f"power_{key}")
    matched = resolve_power_lookup(power_db, selected)
    if matched is None:
        return
    entry = engine.get_row(power_db, matched)
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
    title = (
        f"{template_display_name(npc.name)}"
        + (f"  \u00b7  {config['metatype']}" if config.get("metatype") else "")
        + f"  \u00b7  {archetype_label(npc.ARCHETYPE)}"
    )
    if isinstance(npc, (engine.Critter, engine.Spirit)):
        source = npc_source_line(npc)
        if source:
            title += f"  \u00b7  {source}"
    header.subheader(title)
    # Der Klick wird erst am Ende ausgewertet, wenn Attribute und Ausruestung
    # in der Konfiguration stehen.
    add_clicked = button.button(
        "Zum Dashboard hinzufuegen", type="primary", width="stretch"
    )

    # Der Schluessel bindet die Eingabefelder an genau diesen NPC. Waehlst du
    # einen anderen Namen oder eine andere Kraftstufe, starten sie wieder
    # bei den Werten aus der Datenbank.
    state_key = (
        f"{config['archetype']}|{config.get('metatype')}|{config['name']}|"
        f"{config.get('force')}|{config.get('magic')}|{config.get('uses_force')}"
    )

    render_attribute_editor(npc, config, state_key, frames)
    st.divider()
    if isinstance(npc, engine.MundaneNPC):
        render_skill_editor(npc, config, state_key, frames)
    elif isinstance(npc, engine.Spirit):
        render_spirit_skill_editor(npc, config, state_key, frames)
    elif isinstance(npc, engine.Critter) and npc.uses_force:
        render_spirit_skill_editor(npc, config, state_key, frames)
    elif isinstance(npc, engine.Critter):
        render_skill_editor(npc, config, state_key, frames)
    else:
        render_details(npc, config, state_key)
    st.divider()
    render_equipment(npc, config, frames, skill_map, state_key)

    if isinstance(npc, engine.Spirit):
        with st.expander(f"{KRAEFTE} des Geistes", expanded=True):
            render_spirit_powers(npc, frames.get(KRAEFTE), key="generator")

    if isinstance(npc, engine.MagicianNPC) and npc.spells:
        with st.expander("Zauber", expanded=True):
            force = int(
                st.slider(
                    "Kraftstufe der Zauber (KS)",
                    1,
                    engine.MAX_FORCE,
                    min(npc.magic, engine.MAX_FORCE),
                )
            )
            config["spell_force"] = force
            render_spell_tooltip_list(frames["Zauber"], npc.spells, force=force)
            st.caption("Entzugswert ist immer mindestens 2. Maus ueber Zauber fuer Wirkung.")

    st.divider()
    st.markdown("**Wuerfelpools**")
    st.write(format_limits_line(npc))
    skill_limits = pools.build_skill_limit_map(frames.get("Fertigkeiten"))
    npc_pools = pools.standard_pools(
        npc,
        skill_map,
        magic_force=npc_magic_force(npc, config),
        skill_limits=skill_limits,
    )
    render_dashboard_pools(npc_pools, npc, detailed=True)
    st.caption("Gewuerfelt wird am Tisch - das Tool zaehlt nur die Wuerfel.")

    with st.expander("Erl\u00e4uterungen & Berechnungen"):
        render_npc_calculations(npc, config, skill_map, skill_limits)

    with st.expander("Rohdaten aus der CSV"):
        st.dataframe(npc.row.to_frame("Wert"), width="stretch")

    if add_clicked:
        if npc.weapons:
            config["weapons"] = [weapon.name for weapon in npc.weapons]
            config["weapon_ap"] = [weapon.ap for weapon in npc.weapons]
        add_to_dashboard(config)


def copy_config(config: dict) -> dict:
    """Eigenstaendige Kopie, damit Karten sich nicht gegenseitig veraendern."""
    entry = dict(config)
    entry["spells"] = list(config.get("spells", []))
    entry["skill_ratings"] = dict(config.get("skill_ratings", {}))
    entry["selected_skills"] = [
        str(name) for name in config.get("selected_skills") or [] if name
    ]
    entry["attributes"] = dict(config.get("attributes", {}))
    entry["weapons"] = [str(name) for name in config.get("weapons", []) if name]
    entry["weapon_ap"] = list(config.get("weapon_ap") or [])
    entry["uses_force"] = bool(config.get("uses_force"))
    entry["tradition"] = (
        config.get("tradition")
        if config.get("tradition") in engine.DRAIN_ATTRIBUTE
        else engine.TRADITION_HERMETIC
    )
    return entry


def config_to_export(entry: dict) -> dict:
    """Bereitet einen Dashboard-Eintrag fuer JSON-Export vor."""
    copied = copy_config(entry)
    return {
        "uid": copied.get("uid") or "",
        "archetype": copied["archetype"],
        "name": copied["name"],
        "metatype": copied.get("metatype"),
        "label": copied.get("label", copied["name"]),
        "force": int(copied.get("force", 4)),
        "uses_force": bool(copied.get("uses_force")),
        "magic": copied.get("magic"),
        "skill_ratings": copied.get("skill_ratings", {}),
        "selected_skills": copied.get("selected_skills", []),
        "spells": copied.get("spells", []),
        "spell_force": int(copied.get("spell_force", 4)),
        "tradition": copied.get("tradition", engine.TRADITION_HERMETIC),
        "modifier": int(copied.get("modifier", 0)),
        "damage": int(copied.get("damage", 0)),
        "attributes": copied.get("attributes", {}),
        "edge": copied.get("edge"),
        "initiative": copied.get("initiative"),
        "initiative_dice": copied.get("initiative_dice"),
        "armor_rating": copied.get("armor_rating"),
        "weapons": copied.get("weapons", []),
        "weapon_ap": copied.get("weapon_ap") or [],
        "armor": copied.get("armor"),
    }


def snapshot_initiative_list() -> list[dict]:
    """Aktueller Tracker-Stand inklusive der Werte aus den Eingabefeldern."""
    snapshot: list[dict] = []
    for entry in st.session_state.get(INITIATIVE_STATE_KEY, []):
        copied = {
            "uid": entry.get("uid") or uuid.uuid4().hex[:8],
            "name": str(entry.get("name") or ""),
            "value": max(0, int(entry.get("value", 0))),
            "kind": entry.get("kind") or INITIATIVE_PLAYER,
            "npc_uid": entry.get("npc_uid") or None,
            "note": str(entry.get("note") or ""),
        }
        widget_key = _initiative_value_key(copied["uid"])
        if widget_key in st.session_state:
            copied["value"] = max(0, int(st.session_state[widget_key]))
        snapshot.append(copied)
    return snapshot


def snapshot_selected_npcs(active: list[dict]) -> list[str]:
    """Welche NPCs in den Initiative-Chips ausgewaehlt sind."""
    living = {config["uid"] for config in active}
    if INI_SELECTED_KEY in st.session_state:
        return [
            str(uid)
            for uid in st.session_state.get(INI_SELECTED_KEY, [])
            if uid in living
        ]
    return [
        str(entry["npc_uid"])
        for entry in st.session_state.get(INITIATIVE_STATE_KEY, [])
        if entry.get("npc_uid") in living
    ]


def build_export_payload(active: list[dict]) -> str:
    """Serialisiert NPCs und Initiative-Tracker als Spielstand."""
    payload = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "npcs": [config_to_export(entry) for entry in active],
        "initiative": snapshot_initiative_list(),
        "initiative_selected": snapshot_selected_npcs(active),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def safe_save_stem(name: str) -> str:
    stem = _SAVE_NAME_SAFE.sub("_", name.strip())
    return stem or "spielstand"


def export_filename(name: str | None = None) -> str:
    if name and name.strip():
        stem = safe_save_stem(name)
        if stem.lower().endswith(".json"):
            stem = stem[:-5]
        return f"{stem}.json"
    stamp = datetime.now().strftime("%Y-%m-%d")
    return f"shadowrun-dashboard-{stamp}.json"


def _clip_text(value: object, default: str = "", limit: int = MAX_NAME_LEN) -> str:
    text = str(value if value is not None else default).strip()
    return text[:limit]


def _bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _optional_int(value: object, low: int = 0, high: int = 100) -> int | None:
    if value is None or value == "":
        return None
    return _bounded_int(value, low, low, high)


def _string_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clip_text(item) for item in value[:limit] if _clip_text(item)]


def import_npc(raw: object) -> dict:
    """Wandelt einen JSON-Eintrag in einen geprueften Dashboard-Eintrag um."""
    if not isinstance(raw, dict):
        raise ValueError("Jeder NPC muss ein JSON-Objekt sein.")

    archetype = raw.get("archetype")
    name = _clip_text(raw.get("name"))
    if archetype not in engine.ARCHETYPES:
        raise ValueError(f"Unbekannter Archetyp '{archetype}'.")
    if not name:
        raise ValueError("Mindestens ein NPC hat keinen Namen.")

    magic = _optional_int(raw.get("magic"), 1, engine.MAX_FORCE)
    selected_raw = raw.get("selected_skills") or []
    if not isinstance(selected_raw, list):
        selected_raw = []
    selected_skills = [
        engine.normalize_skill_name(_clip_text(skill))
        for skill in selected_raw[:MAX_IMPORT_SKILLS]
        if _clip_text(skill)
    ]
    ratings_raw = raw.get("skill_ratings") or {}
    if not isinstance(ratings_raw, dict):
        ratings_raw = {}
    skill_ratings = {
        engine.normalize_skill_name(_clip_text(skill)): _bounded_int(
            rating, 0, 0, engine.MAX_FORCE
        )
        for skill, rating in list(ratings_raw.items())[:MAX_IMPORT_SKILLS]
        if _clip_text(skill)
    }
    attributes_raw = raw.get("attributes") or {}
    if not isinstance(attributes_raw, dict):
        attributes_raw = {}
    attributes = {
        key: _bounded_int(attributes_raw.get(key), 0, 0, 30)
        for key in engine.ATTRIBUTES
        if key in attributes_raw
    }
    uid = _clip_text(raw.get("uid"), limit=16) or uuid.uuid4().hex[:8]
    armor = raw.get("armor")
    metatype = _clip_text(raw.get("metatype"))
    if engine.uses_metatype(archetype):
        metatype = metatype or engine.DEFAULT_METATYPE
    else:
        metatype = None
    return {
        "uid": uid,
        "archetype": archetype,
        "name": name,
        "metatype": metatype,
        "label": _clip_text(raw.get("label") or name),
        "force": _bounded_int(raw.get("force", 4), 4, 1, engine.MAX_FORCE),
        "uses_force": bool(raw.get("uses_force", False)),
        "magic": magic,
        "skill_ratings": skill_ratings,
        "selected_skills": selected_skills,
        "spells": _string_list(raw.get("spells"), MAX_IMPORT_SPELLS),
        "spell_force": _bounded_int(
            raw.get("spell_force", magic or 4), magic or 4, 1, engine.MAX_FORCE
        ),
        "tradition": (
            raw.get("tradition")
            if raw.get("tradition") in engine.DRAIN_ATTRIBUTE
            else engine.TRADITION_HERMETIC
        ),
        "modifier": _bounded_int(raw.get("modifier", 0), 0, -20, 20),
        "damage": _bounded_int(raw.get("damage", 0), 0, 0, 40),
        "attributes": attributes,
        "edge": _optional_int(raw.get("edge"), 0, 12),
        "initiative": _optional_int(raw.get("initiative"), 0, 100),
        "initiative_dice": _optional_int(raw.get("initiative_dice"), 1, 5),
        "armor_rating": _optional_int(raw.get("armor_rating"), 0, 50),
        "weapons": _string_list(raw.get("weapons"), MAX_IMPORT_WEAPONS),
        "weapon_ap": _string_list(raw.get("weapon_ap"), MAX_IMPORT_WEAPONS),
        "armor": _clip_text(armor) if armor not in (None, "") else None,
    }


def import_initiative_entry(raw: object) -> dict:
    """Stellt einen Tracker-Eintrag aus JSON wieder her."""
    if not isinstance(raw, dict):
        raise ValueError("Jeder Initiative-Eintrag muss ein JSON-Objekt sein.")
    kind = raw.get("kind") or INITIATIVE_PLAYER
    if kind not in (INITIATIVE_PLAYER, INITIATIVE_NPC):
        kind = INITIATIVE_PLAYER
    npc_uid = raw.get("npc_uid") or None
    return {
        "uid": _clip_text(raw.get("uid"), limit=16) or uuid.uuid4().hex[:8],
        "name": _clip_text(raw.get("name")) or "Unbenannt",
        "value": _bounded_int(raw.get("value", 0), 0, 0, 200),
        "kind": kind,
        "npc_uid": _clip_text(npc_uid, limit=16) if npc_uid else None,
        "note": _clip_text(raw.get("note"), limit=120),
    }


def decode_import_payload(content: bytes | str) -> str:
    """Liest nur UTF-8 (inkl. BOM) und lehnt zu grosse Dateien ab."""
    if isinstance(content, str):
        raw = content
    else:
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("Die Datei ist zu gross (max. 512 KB).")
        try:
            raw = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError(f"Keine UTF-8-Datei: {error}") from error
    raw = raw.strip()
    if not raw:
        raise ValueError("Die Datei ist leer.")
    if len(raw.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Die Datei ist zu gross (max. 512 KB).")
    return raw


def parse_import_file(content: bytes | str) -> tuple[list[dict], list[dict], list[str]]:
    """Liest eine exportierte Spielstand-JSON-Datei ein."""
    try:
        data = json.loads(decode_import_payload(content))
    except json.JSONDecodeError as error:
        raise ValueError(f"Keine gueltige JSON-Datei: {error}") from error

    initiative_raw: list = []
    selected_raw: list = []
    if isinstance(data, list):
        npcs_raw = data
    elif isinstance(data, dict):
        if data.get("format") not in (None, EXPORT_FORMAT):
            raise ValueError("Unbekanntes Dateiformat.")
        npcs_raw = data.get("npcs", data.get("active_npcs"))
        if npcs_raw is None:
            npcs_raw = []
        initiative_raw = data.get("initiative") or data.get("initiative_list") or []
        selected_raw = data.get("initiative_selected") or []
    else:
        raise ValueError("Ungueltiges Dateiformat.")

    if not isinstance(npcs_raw, list):
        raise ValueError("Die NPC-Liste muss ein Array sein.")
    if initiative_raw is None:
        initiative_raw = []
    if not isinstance(initiative_raw, list):
        raise ValueError("Die Initiative-Liste muss ein Array sein.")
    if not isinstance(selected_raw, list):
        selected_raw = []
    if not npcs_raw and not initiative_raw:
        raise ValueError("Die Datei enthaelt keinen Spielstand.")
    if len(npcs_raw) > MAX_IMPORT_NPCS:
        raise ValueError(f"Zu viele NPCs (max. {MAX_IMPORT_NPCS}).")
    if len(initiative_raw) > MAX_IMPORT_INITIATIVE:
        raise ValueError(f"Zu viele Initiative-Eintraege (max. {MAX_IMPORT_INITIATIVE}).")

    npcs = [import_npc(item) for item in npcs_raw]
    initiative = [import_initiative_entry(item) for item in initiative_raw]
    living = {config["uid"] for config in npcs}
    selected = [str(uid) for uid in selected_raw if str(uid) in living]
    if not selected:
        selected = [
            entry["npc_uid"]
            for entry in initiative
            if entry.get("npc_uid") in living
        ]
    return npcs, initiative, selected


def clear_dashboard_widgets() -> None:
    """Entfernt Widget-Reste der bisherigen Karten und Tracker-Eintraege."""
    for config in st.session_state.get("active_npcs", []):
        uid = config.get("uid")
        if not uid:
            continue
        st.session_state.pop(f"dmg_{uid}", None)
        st.session_state.pop(f"mod_{uid}", None)
        st.session_state.pop(f"ks_{uid}", None)
    for entry in st.session_state.get(INITIATIVE_STATE_KEY, []):
        uid = entry.get("uid")
        if uid:
            st.session_state.pop(_initiative_value_key(uid), None)
    st.session_state.pop(INI_SELECTED_KEY, None)
    for key in list(st.session_state.keys()):
        if str(key).startswith("ini_npc_cb_"):
            st.session_state.pop(key, None)


def restore_loaded_widgets(
    npcs: list[dict], initiative: list[dict], selected: list[str]
) -> None:
    """Setzt Schadens-, Modifikator-, INI-Felder und NPC-Auswahl."""
    for config in npcs:
        uid = config["uid"]
        st.session_state[f"dmg_{uid}"] = int(config.get("damage", 0))
        st.session_state[f"mod_{uid}"] = int(config.get("modifier", 0))
        st.session_state[f"ks_{uid}"] = int(config.get("spell_force", 4) or 4)
    for entry in initiative:
        st.session_state[_initiative_value_key(entry["uid"])] = int(entry["value"])
    living = {config["uid"] for config in npcs}
    chosen = [uid for uid in selected if uid in living]
    st.session_state[INI_SELECTED_KEY] = chosen
    for uid in living:
        st.session_state[f"ini_npc_cb_{uid}"] = uid in chosen


def apply_pending_import() -> None:
    """Wendet einen gespeicherten JSON-Import an, ohne den Uploader per rerun zu stoeren."""
    payload = st.session_state.pop("pending_import", None)
    if payload is None:
        return
    try:
        npcs, initiative, selected = parse_import_file(payload)
    except ValueError as error:
        st.session_state["import_error"] = str(error)
        return
    clear_dashboard_widgets()
    st.session_state["active_npcs"] = npcs
    st.session_state[INITIATIVE_STATE_KEY] = initiative
    restore_loaded_widgets(npcs, initiative, selected)
    st.session_state["import_message"] = (
        f"{len(npcs)} NPC(s) und {len(initiative)} Initiative-Eintraege geladen."
    )


def queue_import(payload: bytes | str) -> None:
    """Eine Quelle (Datei oder Text) pruefen und ins Dashboard uebernehmen."""
    st.session_state["pending_import"] = payload
    apply_pending_import()


def _import_payload_id(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        digest = hashlib.sha256(payload).hexdigest()
    else:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:16]


def render_persistence_panel(active: list[dict]) -> None:
    """Export und Import nur im Browser - nichts wird auf den Server geschrieben."""
    message = st.session_state.pop("import_message", None)
    error = st.session_state.pop("import_error", None)
    if message:
        st.success(message)
    if error:
        st.error(error)

    has_state = bool(active or st.session_state.get(INITIATIVE_STATE_KEY))
    payload_text = build_export_payload(active)
    payload_bytes = payload_text.encode("utf-8")

    with st.expander("Speichern / Laden", expanded=not active):
        st.caption(
            "Die Datei bleibt auf deinem Rechner. "
            "Es wird nichts ins Projekt, nach GitHub oder auf den Server geschrieben."
        )
        st.markdown("**Speichern**")
        if "save_stem" not in st.session_state:
            st.session_state["save_stem"] = "spielstand"
        name_col, save_col = st.columns([3, 1], vertical_alignment="bottom")
        save_name = name_col.text_input("Dateiname", key="save_stem")
        save_col.download_button(
            "Speichern",
            data=payload_bytes,
            file_name=export_filename(save_name),
            mime="application/json",
            disabled=not has_state,
            width="stretch",
            help="Laedt die JSON-Datei in den Download-Ordner des Browsers.",
        )
        if has_state:
            with st.expander("JSON anzeigen und kopieren"):
                st.code(payload_text, language="json")
                st.caption("Falls der Download-Button fehlt: Text kopieren und als .json speichern.")

        st.markdown("**Laden**")
        st.caption("Ersetzt die aktuellen NPCs und die Initiative.")
        uploaded = st.file_uploader(
            "Spielstand-Datei",
            type=["json"],
            key="dashboard_import_file",
            accept_multiple_files=False,
            help="Nur eine JSON-Datei aus diesem Tool, hoechstens 1 MB.",
        )
        if st.button(
            "Spielstand aus Datei laden",
            width="stretch",
            disabled=uploaded is None,
        ):
            if uploaded is None:
                st.warning("Bitte zuerst eine JSON-Datei waehlen.")
            else:
                content = uploaded.getvalue()
                queue_import(content)
                st.session_state["last_import_id"] = _import_payload_id(content)
                st.session_state.pop("dashboard_import_file", None)
                st.rerun()

        pasted = st.text_area(
            "Oder JSON hier einfuegen",
            key="dashboard_import_paste",
            height=80,
            help="Reserve, falls der Datei-Dialog im Browser nicht oeffnet.",
        )
        if st.button("Eingefuegten Spielstand laden", width="stretch"):
            text = (pasted or "").strip()
            if not text:
                st.warning("Kein JSON zum Laden.")
            else:
                queue_import(text)
                st.session_state["last_import_id"] = _import_payload_id(text)
                if "import_error" not in st.session_state:
                    st.session_state["dashboard_import_paste"] = ""
                st.rerun()


def add_to_dashboard(config: dict) -> None:
    entry = copy_config(config)
    entry["uid"] = uuid.uuid4().hex[:8]
    entry["label"] = default_npc_label(config)
    st.session_state["active_npcs"].append(entry)
    st.toast(f"{entry['label']} steht jetzt im Dashboard.")
    # Das Dashboard wird vor dem Generator gezeichnet, daher neu durchlaufen.
    st.rerun()


def render_damage_monitor(npc: engine.BaseNPC, config: dict) -> int:
    """Schadensmonitor der Karte. Gibt den Wundabzug als negative Zahl zurueck."""
    uid = config["uid"]
    key = f"dmg_{uid}"
    capacity = npc.damage_capacity

    # Sinkt die Kapazitaet (z. B. bei niedrigerer Konstitution), darf der
    # eingetragene Schaden nicht ueber dem neuen Maximum liegen.
    previous = int(st.session_state.get(key, config.get("damage", 0)))
    st.session_state[key] = min(previous, capacity)

    damage = int(
        st.number_input(
            "Erlittener Schaden",
            min_value=0,
            max_value=capacity,
            step=1,
            key=key,
            help=f"Gemeinsamer Monitor: {capacity} Monitor "
            f"(hoeherer Wert aus {npc.physical_monitor} / {npc.stun_monitor}).",
        )
    )
    config["damage"] = damage

    wounds = pools.wound_modifier(damage)
    st.progress(damage / capacity if capacity else 0.0)

    status = (
        f"Schaden: **{damage} / {capacity}** Monitor "
        f"\u00b7 Wundabzug: **{wounds} W6**"
    )
    if wounds:
        st.warning(status)
    else:
        st.caption(status)

    return wounds


def render_rename_control(config: dict, current_name: str) -> None:
    """Anzeigename auf der Dashboard-Karte aendern - nur label, nicht die CSV-Referenz."""
    uid = config["uid"]
    label = icon_markdown("Stift") or "\u270f\ufe0f"
    with st.container(key=f"rename-btn-{uid}"):
        with st.popover(label, help="Namen bearbeiten", type="tertiary"):
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

        title_col, edit_col = st.columns([0.86, 0.14], vertical_alignment="center")
        with title_col:
            st.markdown(f"### {display_name}{suffix}")
        with edit_col:
            render_rename_control(config, display_name)

        caption = archetype_label(config.get("archetype", npc.ARCHETYPE))
        if config.get("metatype"):
            caption = f"{config['metatype']} \u00b7 {caption}"
        if isinstance(npc, engine.MagicianNPC):
            caption += f" \u00b7 {npc.tradition}"
        source = npc_source_line(npc)
        if source:
            caption += f" \u00b7 {source}"
        st.caption(caption)

        if (
            isinstance(npc, engine.Critter)
            and not npc.uses_force
            and all(value == 0 for value in npc.attributes.values())
        ):
            st.warning("Keine Attributswerte in der Datenbank.")

        st.write(
            " \u00b7 ".join(
                f"{ATTRIBUTE_SHORT[label]} **{value}**"
                for label, value in npc.attributes.items()
            )
        )
        st.write(format_limits_line(npc))
        render_dashboard_edge(npc, config, frames)

        wounds = render_damage_monitor(npc, config)
        mod_key = f"mod_{uid}"
        if mod_key not in st.session_state:
            st.session_state[mod_key] = int(config.get("modifier", 0))
        modifier = int(st.session_state[mod_key])

        st.write(
            f"**Initiative:** {pools.initiative_line(npc, modifier=modifier, wounds=wounds)}"
        )

        config["modifier"] = int(
            st.number_input(
                "Situative Modifikatoren (z. B. Deckung/Sicht)",
                min_value=-20,
                max_value=20,
                step=1,
                key=mod_key,
                help="Wirkt auf Angriff, Verteidigung, Initiative und Proben, nicht auf Entzug.",
            )
        )

        skill_limits = pools.build_skill_limit_map(frames.get("Fertigkeiten"))
        npc_pools = pools.standard_pools(
            npc,
            skill_map,
            config["modifier"],
            wounds,
            magic_force=npc_magic_force(npc, config),
            skill_limits=skill_limits,
        )
        render_dashboard_pools(npc_pools, npc)

        render_card_details(npc, config, frames)

        with st.expander("Erl\u00e4uterungen & Berechnungen"):
            render_npc_calculations(npc, config, skill_map, skill_limits)

        duplicate, delete = st.columns(2)
        if duplicate.button("Duplizieren", key=f"dup_{uid}", width="stretch"):
            return "duplicate"
        if delete.button(LOESCHEN, key=f"del_{uid}", width="stretch"):
            remove_npc_from_tracker(uid)
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
        with st.expander(with_icon("Entzug", SECTION_SPELLS)):
            ks_key = f"ks_{uid}"
            ks_kwargs: dict = {
                "min_value": 1,
                "max_value": engine.MAX_FORCE,
                "key": ks_key,
            }
            if ks_key not in st.session_state:
                ks_kwargs["value"] = int(
                    config.get("spell_force", npc.magic) or npc.magic
                )
            config["spell_force"] = int(st.slider("Kraftstufe (KS)", **ks_kwargs))
            render_spell_tooltip_list(
                frames["Zauber"], npc.spells, force=config["spell_force"]
            )
            st.caption("Entzugswert ist immer mindestens 2. Maus ueber Zauber fuer Wirkung.")

    if npc.weapons or npc.armor_item is not None or config.get("weapons"):
        with st.expander(with_icon("Ausruestung", SECTION_EQUIPMENT)):
            if npc.weapons:
                for weapon in npc.weapons:
                    st.write(
                        f"**{weapon.name}** \u00b7 Schaden {weapon.damage} \u00b7 "
                        f"DK {weapon.ap} \u00b7 Modus {weapon.mode}"
                    )
            elif config.get("weapons"):
                st.write(", ".join(str(name) for name in config["weapons"]))
            if npc.armor_item is not None:
                st.write(
                    f"**{npc.armor_item.name}** \u00b7 Panzerung "
                    f"{npc.armor_item.rating_text} \u2192 {npc.armor}"
                )


def _initiative_list() -> list[dict]:
    return st.session_state.setdefault(INITIATIVE_STATE_KEY, [])


def _initiative_value_key(uid: str) -> str:
    return f"ini_track_val_{uid}"


def make_initiative_entry(
    *,
    name: str,
    value: int,
    kind: str,
    npc_uid: str | None = None,
    note: str = "",
) -> dict:
    """Ein Tracker-Eintrag: Name, aktueller INI-Wert, Typ Spieler oder NPC."""
    return {
        "uid": uuid.uuid4().hex[:8],
        "name": name,
        "value": int(value),
        "kind": kind,
        "npc_uid": npc_uid,
        "note": note,
    }


def roll_initiative_dice(count: int) -> tuple[int, list[int]]:
    rolls = [random.randint(1, 6) for _ in range(max(0, int(count)))]
    return sum(rolls), rolls


def sort_initiative_entries(entries: list[dict]) -> list[dict]:
    """Hoechster INI-Wert zuerst, dann absteigend - wer dran ist steht oben."""
    return sorted(entries, key=lambda entry: entry["value"], reverse=True)


def _clear_initiative_widget(uid: str) -> None:
    st.session_state.pop(_initiative_value_key(uid), None)


def _set_initiative_widget(uid: str, value: int) -> None:
    st.session_state[_initiative_value_key(uid)] = int(value)


def remove_npc_from_tracker(npc_uid: str) -> None:
    remaining = []
    for entry in _initiative_list():
        if entry.get("npc_uid") == npc_uid:
            _clear_initiative_widget(entry["uid"])
            continue
        remaining.append(entry)
    st.session_state[INITIATIVE_STATE_KEY] = remaining


def prune_tracker_npcs(active: list[dict]) -> None:
    """Entfernt Tracker-NPCs, deren Dashboard-Karte nicht mehr existiert."""
    living = {config["uid"] for config in active}
    remaining = []
    for entry in _initiative_list():
        npc_uid = entry.get("npc_uid")
        if npc_uid and npc_uid not in living:
            _clear_initiative_widget(entry["uid"])
            continue
        remaining.append(entry)
    st.session_state[INITIATIVE_STATE_KEY] = remaining


def sync_tracker_npc_names(active: list[dict]) -> None:
    """Uebernimmt umbenannte Dashboard-NPCs in den Tracker."""
    labels = {
        config["uid"]: config.get("label") or config["name"] for config in active
    }
    for entry in _initiative_list():
        npc_uid = entry.get("npc_uid")
        if npc_uid and npc_uid in labels:
            entry["name"] = labels[npc_uid]


def _npc_choice_labels(active: list[dict]) -> dict[str, str]:
    """uid -> Chip-Text. Gleichnamige heissen z. B. 'Elf1 #2', ohne interne ID."""
    seen: dict[str, int] = {}
    labels: dict[str, str] = {}
    for config in active:
        base = str(config.get("label") or config["name"]).strip() or str(config["name"])
        count = seen.get(base, 0) + 1
        seen[base] = count
        labels[config["uid"]] = base if count == 1 else f"{base} #{count}"
    return labels


def add_player_to_tracker(name: str, value: int) -> None:
    entry = make_initiative_entry(
        name=name, value=value, kind=INITIATIVE_PLAYER
    )
    _set_initiative_widget(entry["uid"], value)
    _initiative_list().append(entry)


def npc_damage_value(config: dict) -> int:
    return int(st.session_state.get(f"dmg_{config['uid']}", config.get("damage", 0)))


def npc_situation_modifier(config: dict) -> int:
    return int(st.session_state.get(f"mod_{config['uid']}", config.get("modifier", 0)))


def current_npc_initiative_base(config: dict, npc: engine.BaseNPC) -> tuple[int, list[str]]:
    """INI-Basis inkl. Wundabzug und situativer Modifikatoren, wie auf der Karte."""
    raw = int(npc.initiative_base)
    wounds = pools.wound_modifier(npc_damage_value(config))
    situation = npc_situation_modifier(config)
    parts = [f"Basis {raw}"]
    if wounds:
        parts.append(f"{wounds} Wunden")
    if situation:
        parts.append(f"{situation:+d} Situation")
    return max(0, raw + wounds + situation), parts


def roll_selected_npcs(
    selected: list[dict], frames: dict[str, pd.DataFrame]
) -> list[str]:
    """Wuerfelt INI fuer gewaehlte Dashboard-NPCs und schreibt sie in die Liste."""
    messages: list[str] = []
    for config in selected:
        npc = build_npc(config, frames)
        if npc is None:
            messages.append(f"{config.get('label', config['name'])}: nicht ladbar.")
            continue

        base, base_parts = current_npc_initiative_base(config, npc)
        dice = int(npc.initiative_dice)
        rolled, faces = roll_initiative_dice(dice)
        total = base + rolled
        face_text = "+".join(str(face) for face in faces) or "0"
        base_text = " ".join(base_parts)
        note = f"{base_text} + {dice}W6 ({face_text}) = {total}"
        display_name = config.get("label") or npc.name

        remove_npc_from_tracker(config["uid"])
        entry = make_initiative_entry(
            name=display_name,
            value=total,
            kind=INITIATIVE_NPC,
            npc_uid=config["uid"],
            note=note,
        )
        _set_initiative_widget(entry["uid"], total)
        _initiative_list().append(entry)
        messages.append(f"{display_name}: {note}")
    return messages


def adjust_initiative(entry: dict, delta: int) -> None:
    entry["value"] = max(0, int(entry["value"]) + int(delta))
    _set_initiative_widget(entry["uid"], entry["value"])


def reset_combat_round() -> None:
    """NPCs raus, Spielernamen bleiben - Werte auf 0 fuer die neue Runde."""
    kept: list[dict] = []
    for entry in _initiative_list():
        if entry.get("kind") != INITIATIVE_PLAYER:
            _clear_initiative_widget(entry["uid"])
            continue
        entry["value"] = 0
        entry["note"] = ""
        _set_initiative_widget(entry["uid"], 0)
        kept.append(entry)
    st.session_state[INITIATIVE_STATE_KEY] = kept


def render_npc_initiative_picks(active: list[dict]) -> list[str]:
    """NPC-Auswahl per Checkbox - ohne Streamlit-Multiselect-Modul."""
    labels = _npc_choice_labels(active)
    if not labels:
        st.caption("Noch keine Dashboard-NPCs zum Auswaehlen.")
        return []

    st.markdown("**NPCs in der Initiative**")
    remembered = set(st.session_state.get(INI_SELECTED_KEY, []))
    columns = st.columns(min(3, len(labels)))
    selected: list[str] = []
    for index, (uid, label) in enumerate(labels.items()):
        box_key = f"ini_npc_cb_{uid}"
        if box_key not in st.session_state:
            st.session_state[box_key] = uid in remembered
        if columns[index % len(columns)].checkbox(label, key=box_key):
            selected.append(uid)
    st.session_state[INI_SELECTED_KEY] = selected
    return selected


def render_initiative_tracker(
    active: list[dict], frames: dict[str, pd.DataFrame]
) -> None:
    prune_tracker_npcs(active)
    sync_tracker_npc_names(active)

    if st.session_state.pop("ini_clear_player", False):
        st.session_state["ini_player_name"] = ""
        st.session_state["ini_player_value"] = 0

    for entry in _initiative_list():
        widget_key = _initiative_value_key(entry["uid"])
        if widget_key in st.session_state:
            clamped = max(0, int(st.session_state[widget_key]))
            st.session_state[widget_key] = clamped
            entry["value"] = clamped
        else:
            entry["value"] = max(0, int(entry["value"]))

    with st.expander("Initiative-Tracker", expanded=True):
        st.caption(
            "Hoechster INI-Wert handelt zuerst. "
            f"Pro Charakter {INITIATIVE_SHORT} oder {INITIATIVE_PASS} abziehen."
        )

        name_col, value_col, add_col = st.columns([3, 1, 1.4], vertical_alignment="bottom")
        player_name = name_col.text_input("Spielername", key="ini_player_name")
        player_value = int(
            value_col.number_input(
                "Gewuerfelte INI",
                min_value=0,
                max_value=80,
                step=1,
                key="ini_player_value",
            )
        )
        if add_col.button("Spieler hinzufuegen", width="stretch"):
            cleaned = player_name.strip()
            if not cleaned:
                st.warning("Bitte einen Spielernamen eingeben.")
            else:
                add_player_to_tracker(cleaned, player_value)
                st.session_state["ini_clear_player"] = True
                st.rerun()

        selected_uids = render_npc_initiative_picks(active)
        by_uid = {config["uid"]: config for config in active}
        roll_col, round_col = st.columns(2)
        if roll_col.button(
            "Ausgew\u00e4hlte NPCs w\u00fcrfeln",
            width="stretch",
            disabled=not active,
        ):
            if not selected_uids:
                st.warning("Bitte mindestens einen NPC auswaehlen.")
            else:
                selected = [by_uid[uid] for uid in selected_uids if uid in by_uid]
                messages = roll_selected_npcs(selected, frames)
                for line in messages:
                    st.toast(line)
                st.rerun()
        if round_col.button("Neue Kampfrunde (Reset)", width="stretch"):
            reset_combat_round()
            st.rerun()

        entries = sort_initiative_entries(_initiative_list())
        if not entries:
            st.info("Noch niemand in der Initiative. Spieler eintragen oder NPCs wuerfeln.")
            return

        acting_uid = next((item["uid"] for item in entries if item["value"] > 0), None)
        for entry in entries:
            widget_key = _initiative_value_key(entry["uid"])
            if widget_key not in st.session_state:
                _set_initiative_widget(entry["uid"], entry["value"])
            inactive = entry["value"] <= 0
            is_acting = entry["uid"] == acting_uid
            row = st.container(border=True)
            with row:
                name_col, minus5, minus10, kind_col, ini_col, del_col = st.columns(
                    [2.6, 0.7, 0.7, 1.0, 1.2, 0.5], vertical_alignment="center"
                )
                label = html.escape(entry["name"])
                if inactive:
                    name_col.markdown(
                        f'<span style="opacity:0.45">{label} \u00b7 keine Handlung</span>',
                        unsafe_allow_html=True,
                    )
                elif is_acting:
                    name_col.markdown(f"**\u25b6 {entry['name']}**")
                    if entry.get("note"):
                        name_col.caption(entry["note"])
                else:
                    name_col.markdown(f"**{entry['name']}**")
                    if entry.get("note"):
                        name_col.caption(entry["note"])
                if minus5.button(
                    f"-{INITIATIVE_SHORT}",
                    key=f"ini_m5_{entry['uid']}",
                    width="stretch",
                    disabled=inactive,
                ):
                    adjust_initiative(entry, -INITIATIVE_SHORT)
                    st.rerun()
                if minus10.button(
                    f"-{INITIATIVE_PASS}",
                    key=f"ini_m10_{entry['uid']}",
                    width="stretch",
                    disabled=inactive,
                ):
                    adjust_initiative(entry, -INITIATIVE_PASS)
                    st.rerun()
                kind_col.caption(entry["kind"])
                entry["value"] = int(
                    ini_col.number_input(
                        "INI",
                        min_value=0,
                        max_value=80,
                        step=1,
                        key=widget_key,
                        label_visibility="collapsed",
                    )
                )
                if del_col.button(
                    "\u274c",
                    key=f"ini_del_{entry['uid']}",
                    help="Aus der Initiative entfernen",
                ):
                    _clear_initiative_widget(entry["uid"])
                    st.session_state[INITIATIVE_STATE_KEY] = [
                        item
                        for item in _initiative_list()
                        if item["uid"] != entry["uid"]
                    ]
                    st.rerun()


EXPLAIN_HEADING_COLOR = THEME_PRIMARY


def _explain_heading(title: str) -> str:
    return (
        f'<span style="color:{EXPLAIN_HEADING_COLOR};font-weight:600">'
        f"{html.escape(title)}</span>"
    )


def explain_monitor(npc: engine.BaseNPC, damage: int, wounds: int) -> str:
    """Rechenweg des gemeinsamen Monitors und des Wundabzugs, eine Zeile."""
    constitution = npc.attributes["Konstitution"]
    willpower = npc.attributes["Willenskraft"]
    return (
        f"koerperlich 8 + aufrunden(KON {constitution} / 2) = {npc.physical_monitor} "
        f"\u00b7 geistig 8 + aufrunden(WIL {willpower} / 2) = {npc.stun_monitor} "
        f"\u00b7 gemeinsam {npc.damage_capacity} (Hausregel, hoeherer Wert) "
        f"\u00b7 aktuell {damage}/{npc.damage_capacity} "
        f"\u00b7 Wundabzug {wounds} W6 (je 3 Monitor -1)"
    )


def render_npc_calculations(
    npc: engine.BaseNPC,
    config: dict,
    skill_map: dict[str, str],
    skill_limits: dict[str, str] | None = None,
) -> None:
    """Kompakte Herleitungen untereinander, mit geringem Zeilenabstand."""
    modifier = int(config.get("modifier", 0))
    damage = int(config.get("damage", 0))
    wounds = pools.wound_modifier(damage)
    npc_pools = pools.standard_pools(
        npc,
        skill_map,
        modifier,
        wounds,
        magic_force=npc_magic_force(npc, config),
        skill_limits=skill_limits,
    )
    attacks, defenses, skill_pools = split_dashboard_pools(npc_pools, npc)

    lines = [
        f"{_explain_heading('Monitor:')} {html.escape(explain_monitor(npc, damage, wounds))}",
        _explain_heading("Limits:"),
        *(html.escape(line) for line in npc.limit_explanations()),
        _explain_heading("Initiative:"),
        *(html.escape(line) for line in pools.initiative_explanation(npc, modifier, wounds)),
    ]
    if defenses:
        lines.append(_explain_heading(f"{SECTION_DEFENSE}:"))
        lines.extend(
            html.escape(f"{pool.label}: {pool.text}") for pool in defenses
        )
    if attacks:
        lines.append(_explain_heading(f"{SECTION_ATTACK}:"))
        lines.extend(
            html.escape(f"{pool.label}: {pool.text}") for pool in attacks
        )
    if skill_pools:
        lines.append(_explain_heading(f"{SECTION_SKILLS}:"))
        lines.extend(
            html.escape(f"{pool.label}: {pool.text}") for pool in skill_pools
        )

    notes: list[str] = []
    if isinstance(npc, engine.MagicianNPC):
        notes.append(f"Entzug ({npc.tradition}): WIL + {npc.drain_attribute}")
        notes.append("Spruchzauberei: Limit = Kraftstufe des Zaubers (KS)")
        notes.append("Beschw\u00f6ren: Limit = Kraftstufe des herbeigerufenen Geistes (KS)")
    if isinstance(npc, engine.Spirit):
        notes.append(
            f"Waffenloser Schaden: STR {npc.attributes[engine.STAERKE]} + "
            f"Waffenlos {npc.unarmed_bonus} = {npc.unarmed_damage}G"
        )
        notes.append(
            "Schadenswiderstand: Immunitaet 2 x F, hoehere getragene Panzerung gewinnt"
        )
        notes.append(
            "Fertigkeiten: Standard = Kraftstufe, Magie des Geistes = Kraftstufe"
        )
    if isinstance(npc, engine.Critter) and npc.uses_force:
        notes.append("Fertigkeiten: Standard = Kraftstufe")
        notes.append(
            "Schadenswiderstand: Immunitaet 2 x F, hoehere getragene Panzerung gewinnt"
        )
        notes.append("Initiativwuerfel: +2W6")
    if notes:
        lines.append(_explain_heading("Hinweise:"))
        lines.extend(html.escape(note) for note in notes)

    st.markdown("<br>".join(lines), unsafe_allow_html=True)


def render_dashboard(frames: dict[str, pd.DataFrame], skill_map: dict[str, str]) -> None:
    apply_pending_import()
    render_persistence_panel(st.session_state["active_npcs"])
    active = st.session_state["active_npcs"]

    header, clear = st.columns([5, 1], vertical_alignment="bottom")
    header.caption(
        f"{len(active)} aktive NPCs. Die Wuerfel wirft der Spielleiter - "
        "das Tool nennt nur die Anzahl."
    )
    if active and clear.button("Alle entfernen", width="stretch"):
        for config in list(active):
            remove_npc_from_tracker(config["uid"])
        st.session_state["active_npcs"] = []
        st.rerun()

    if not active:
        st.info(
            "Noch keine NPCs im Dashboard. Im Tab 'NPC-Generator' "
            "auf 'Zum Dashboard hinzufuegen' klicken."
        )
        render_initiative_tracker(active, frames)
        return

    render_initiative_tracker(active, frames)
    per_row = render_cards_per_row_control()

    with st.container(key=f"npc-grid-{per_row}"):
        for config in list(active):
            with st.container(key=f"npc-card-{config['uid']}"):
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
    st.session_state.setdefault(INITIATIVE_STATE_KEY, [])
    if CARDS_PER_ROW_KEY not in st.session_state and "cards_per_row" in st.session_state:
        try:
            st.session_state[CARDS_PER_ROW_KEY] = int(st.session_state["cards_per_row"])
        except (TypeError, ValueError):
            pass
    st.session_state.setdefault(CARDS_PER_ROW_KEY, 2)

    frames, errors = load_databases()

    inject_layout_css()
    preload_lazy_widgets()
    if BANNER_PATH.is_file():
        st.image(BANNER_PATH, width="stretch")
    else:
        st.title(APP_TITLE)

    if not frames:
        st.error("Keine Datenbank konnte geladen werden.")
        return

    # Ladefehler sind zu wichtig, um sie in einem Tab zu verstecken.
    if errors:
        st.error(
            f"{len(errors)} Datenbank(en) konnten nicht geladen werden - "
            "Details unter 'Datenbanken'.",
            icon="\u26a0\ufe0f",
        )

    skill_map = pools.build_skill_attribute_map(frames.get("Fertigkeiten"))
    active_tab = render_main_nav(len(st.session_state["active_npcs"]))
    if active_tab == TAB_DASHBOARD:
        render_dashboard(frames, skill_map)
    elif active_tab == TAB_GENERATOR:
        render_generator(frames, skill_map)
    else:
        render_database_status(frames, errors)
        st.divider()
        render_database_browser(frames)


if __name__ == "__main__":
    main()
