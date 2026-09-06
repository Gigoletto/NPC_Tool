"""CSV-Import und Caching der Shadowrun-5-Datenbanken."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent

ENCODINGS = ("cp1252", "latin1")

INDEX_COLUMN = "Name"

# Dateinamen mit Umlaut als Escape, damit dieses Modul reines ASCII bleibt.
RUESTUNG = "R\u00fcstung"  # Ruestung
KRAEFTE = "Kr\u00e4fte"  # Kraefte

DATASETS: dict[str, str] = {
    "NPC_Grunddaten": "NPC_Grunddaten.csv",
    "Geister": "Geister.csv",
    "Critter": "Critter.csv",
    "Waffen": "Waffen.csv",
    "Zauber": "Zauber.csv",
    "Fertigkeiten": "Fertigkeiten.csv",
    "Cyberware": "Cyberware.csv",
    RUESTUNG: f"{RUESTUNG}.csv",
    KRAEFTE: f"{KRAEFTE}.csv",
    "Metamagie": "Metamagie.csv",
}


def _read_csv(path: Path) -> pd.DataFrame:
    # Alle Werte bleiben Text, damit Formeln ('F+2', 'KS - 3') und Zahlen
    # exakt so erhalten bleiben, wie sie in der CSV stehen.
    for encoding in ENCODINGS[:-1]:
        try:
            return pd.read_csv(path, sep=";", encoding=encoding, dtype=str)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, sep=";", encoding=ENCODINGS[-1], dtype=str)


def _clean(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df.columns = [str(column).strip() for column in df.columns]
    df = df.loc[:, [not column.startswith("Unnamed") and column != "" for column in df.columns]]

    if INDEX_COLUMN not in df.columns:
        raise KeyError(f"{source}: Spalte '{INDEX_COLUMN}' fehlt.")

    df[INDEX_COLUMN] = df[INDEX_COLUMN].astype("string").str.strip()
    df = df[df[INDEX_COLUMN].notna() & (df[INDEX_COLUMN] != "")]

    return _uniquify_index(df.set_index(INDEX_COLUMN))


_DISAMBIGUATION_COLUMNS = (
    "Kategorie",
    "Typ",
    "Quelle",
    "Fundstelle",
    "KATEGORIE",
)


def _cell_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"-", "--", "nan", "none"}:
        return ""
    return text


def _disambiguation_suffix(row: pd.Series, column: str = "") -> str:
    """Kategorie, Waffentyp oder Quelle, damit doppelte Namen unterscheidbar sind."""
    columns = (column,) if column else _DISAMBIGUATION_COLUMNS
    for name in columns:
        if name not in row.index:
            continue
        text = _cell_text(row[name])
        if text:
            return text
    return ""


def _best_disambiguation_column(group: pd.DataFrame) -> str:
    """Nimmt die erste Spalte, in der sich die Doppelungen wirklich unterscheiden."""
    for column in _DISAMBIGUATION_COLUMNS:
        if column not in group.columns:
            continue
        values = {_cell_text(value) for value in group[column]}
        values.discard("")
        if len(values) > 1:
            return column
    return ""


def _uniquify_index(df: pd.DataFrame) -> pd.DataFrame:
    """Haengt bei doppelten Namen eine Klammer an, z. B. Krime Whammy (Schrotflinten)."""
    if df.empty or not df.index.has_duplicates:
        return df

    duplicated = set(df.index[df.index.duplicated(keep=False)])
    group_column = {}
    for name in duplicated:
        group = df.loc[name]
        if isinstance(group, pd.DataFrame):
            group_column[name] = _best_disambiguation_column(group)

    used: dict[str, int] = {}
    labels: list[str] = []
    for name, row in df.iterrows():
        label = str(name)
        if name in duplicated:
            suffix = _disambiguation_suffix(row, group_column.get(name, ""))
            if suffix:
                label = f"{name} ({suffix})"
        if label in used:
            used[label] += 1
            label = f"{label} #{used[label]}"
        else:
            used[label] = 1
        labels.append(label)

    df = df.copy()
    df.index = pd.Index(labels, name=INDEX_COLUMN)
    return df


# Steigt mit, wenn sich die Aufbereitung aendert (z. B. eindeutige Namen).
_CACHE_VERSION = 3


@st.cache_data(show_spinner=False)
def _load_cached(filename: str, mtime: float, version: int) -> pd.DataFrame:
    # 'mtime' und 'version' gehoeren zum Cache-Schluessel.
    del version
    return _clean(_read_csv(DATA_DIR / filename), filename)


def load_database(name: str) -> pd.DataFrame:
    """Liest eine Datenbank aus DATASETS und indiziert sie per Spalte 'Name'."""
    try:
        filename = DATASETS[name]
    except KeyError:
        raise KeyError(f"Unbekannte Datenbank '{name}'.") from None

    path = DATA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")

    return _load_cached(filename, path.stat().st_mtime, _CACHE_VERSION)


def load_npc_grunddaten() -> pd.DataFrame:
    return load_database("NPC_Grunddaten")


def load_geister() -> pd.DataFrame:
    return load_database("Geister")


def load_critter() -> pd.DataFrame:
    return load_database("Critter")


def load_waffen() -> pd.DataFrame:
    return load_database("Waffen")


def load_zauber() -> pd.DataFrame:
    return load_database("Zauber")


def load_fertigkeiten() -> pd.DataFrame:
    return load_database("Fertigkeiten")


def load_cyberware() -> pd.DataFrame:
    return load_database("Cyberware")


def load_ruestung() -> pd.DataFrame:
    return load_database(RUESTUNG)


def load_kraefte() -> pd.DataFrame:
    return load_database(KRAEFTE)


def load_metamagie() -> pd.DataFrame:
    return load_database("Metamagie")


def load_all() -> dict[str, pd.DataFrame]:
    """Liest alle in DATASETS eingetragenen Datenbanken."""
    return {name: load_database(name) for name in DATASETS}
