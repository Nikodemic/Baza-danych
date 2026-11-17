"""Warstwa danych: zapytania do bazy produkcja.db (bez Streamlit)."""
import sqlite3

import pandas as pd

import baza

KOLORY = ["#CDE7FF", "#D5F5D0", "#FFE0B2", "#F3D9FA", "#FFD6D6"]


def _polacz():
    conn = sqlite3.connect(baza.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def pobierz(sql, params=()):
    """SELECT -> DataFrame."""
    conn = _polacz()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def wykonaj(sql, params=()):
    """INSERT / UPDATE / DELETE."""
    conn = _polacz()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ---------- Stanowiska i maszyny ----------

def stanowiska():
    return pobierz("SELECT id, nazwa, opis, zajete FROM stanowiska ORDER BY id")


def maszyny(stanowisko_id):
    return pobierz(
        """SELECT nazwa AS maszyna, COALESCE(typ, '') AS typ,
                  COALESCE(producent, '') AS producent, COALESCE(model, '') AS model,
                  CASE sprawna WHEN 1 THEN 'tak' ELSE 'nie' END AS sprawna
           FROM maszyny WHERE stanowisko_id = ? ORDER BY id""",
        (int(stanowisko_id),))


def ustaw_zajetosc(stanowisko_id, zajete):
    wykonaj("UPDATE stanowiska SET zajete = ? WHERE id = ?",
            (int(bool(zajete)), int(stanowisko_id)))


# ---------- Wyrób ----------

def produkty():
    return pobierz("SELECT id, kod, nazwa, COALESCE(opis, '') AS opis FROM produkty ORDER BY id")


def komponenty(produkt_id):
    """Drzewo komponentów w kolejności 'w głąb' (rekurencyjne CTE)."""
    return pobierz(
        """WITH RECURSIVE drzewo(id, nadrzedny_id, kod, nazwa, material, ilosc, poziom, sciezka) AS (
               SELECT id, nadrzedny_id, kod, nazwa, material, ilosc, 0, kod
               FROM komponenty WHERE produkt_id = ? AND nadrzedny_id IS NULL
               UNION ALL
               SELECT k.id, k.nadrzedny_id, k.kod, k.nazwa, k.material, k.ilosc,
                      d.poziom + 1, d.sciezka || '/' || k.kod
               FROM komponenty k JOIN drzewo d ON k.nadrzedny_id = d.id
           )
           SELECT id, nadrzedny_id, kod, nazwa, COALESCE(material, '') AS material, ilosc, poziom
           FROM drzewo ORDER BY sciezka""",
        (int(produkt_id),))


def parametry_wyrobu(produkt_id):
    return pobierz(
        "SELECT nazwa AS parametr, wartosc, COALESCE(jednostka, '') AS jednostka "
        "FROM parametry WHERE produkt_id = ? ORDER BY id", (int(produkt_id),))


def parametry_komponentu(komponent_id):
    return pobierz(
        "SELECT nazwa AS parametr, wartosc, COALESCE(jednostka, '') AS jednostka "
        "FROM parametry WHERE komponent_id = ? ORDER BY id", (int(komponent_id),))


# ---------- Karty technologiczne ----------

def karty():
    return pobierz(
        """SELECT kt.numer, COALESCE(kt.opis, '') AS opis, kt.wersja,
                  COALESCE(k.kod, 'cały wyrób') AS komponent
           FROM karty_technologiczne kt
           LEFT JOIN komponenty k ON k.id = kt.komponent_id
           ORDER BY kt.numer""")


def operacje_karty(numer):
    return pobierz(
        """SELECT o.nr_operacji, o.nazwa, s.nazwa AS stanowisko,
                  COALESCE(m.nazwa, '-') AS maszyna, o.tpz_min, o.tj_min
           FROM operacje o
           JOIN karty_technologiczne kt ON kt.id = o.karta_id
           JOIN stanowiska s ON s.id = o.stanowisko_id
           LEFT JOIN maszyny m ON m.id = o.maszyna_id
           WHERE kt.numer = ?
           ORDER BY o.nr_operacji""",
        (numer,))


# ---------- Obciążenie ----------

def obciazenie():
    """Suma czasu jednostkowego na stanowisku, z uwzględnieniem liczby sztuk komponentu."""
    return pobierz(
        """SELECT s.nazwa AS stanowisko,
                  COALESCE(SUM(o.tj_min * COALESCE(k.ilosc, 1)), 0) AS czas_na_wyrob_min
           FROM stanowiska s
           LEFT JOIN operacje o ON o.stanowisko_id = s.id
           LEFT JOIN karty_technologiczne kt ON kt.id = o.karta_id
           LEFT JOIN komponenty k ON k.id = kt.komponent_id
           GROUP BY s.id ORDER BY s.id""")


# ---------- Schematy (Graphviz DOT) ----------

def _txt(s):
    return str(s).replace('"', "'")


def dot_drzewo(nazwa_wyrobu, df):
    linie = [
        "digraph G {",
        "rankdir=TB;",
        'node [shape=box, style="rounded,filled", fillcolor="#E8F0FE", fontname="Helvetica"];',
        f'p [label="{_txt(nazwa_wyrobu)}", fillcolor="#FDE9B8"];',
    ]
    for r in df.itertuples():
        linie.append(f'k{r.id} [label="{_txt(r.kod)}\\n{_txt(r.nazwa)}\\nx{r.ilosc}"];')
        rodzic = "p" if pd.isna(r.nadrzedny_id) else f"k{int(r.nadrzedny_id)}"
        linie.append(f"{rodzic} -> k{r.id};")
    linie.append("}")
    return "\n".join(linie)


def dot_operacje(df):
    stany = list(dict.fromkeys(df["stanowisko"]))
    linie = [
        "digraph G {",
        "rankdir=LR;",
        'node [shape=box, style="rounded,filled", fontname="Helvetica"];',
    ]
    for i, r in enumerate(df.itertuples()):
        kolor = KOLORY[stany.index(r.stanowisko) % len(KOLORY)]
        etykieta = f"{r.nr_operacji}. {_txt(r.nazwa)}\\n{_txt(r.stanowisko)}\\ntj = {r.tj_min} min"
        linie.append(f'o{i} [label="{etykieta}", fillcolor="{kolor}"];')
        if i > 0:
            linie.append(f"o{i - 1} -> o{i};")
    linie.append("}")
    return "\n".join(linie)
