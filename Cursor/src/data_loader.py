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

    return df.set_index(INDEX_COLUMN)


@st.cache_data(show_spinner=False)
def _load_cached(filename: str, mtime: float) -> pd.DataFrame:
    # 'mtime' gehoert zum Cache-Schluessel: eine bearbeitete CSV wird dadurch
    # automatisch neu eingelesen, ohne die App neu zu starten.
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

    return _load_cached(filename, path.stat().st_mtime)


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
