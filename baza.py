"""Baza danych linii produkcyjnej (SQLite).

3 stanowiska: Cięcie laserowe, Gięcie, Spawanie
1 wyrób z drzewem komponentów, parametrami i kartami technologicznymi.

Uruchomienie:  python baza.py   ->  tworzy plik produkcja.db z danymi przykładowymi
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("produkcja.db")

SCHEMA = """
-- Stanowiska pracy + flaga zajętości (0 = wolne, 1 = zajęte)
CREATE TABLE IF NOT EXISTS stanowiska (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa   TEXT NOT NULL UNIQUE,
    opis    TEXT,
    zajete  INTEGER NOT NULL DEFAULT 0 CHECK (zajete IN (0, 1))
);

-- Maszyny przypisane do stanowisk (relacja 1:N)
CREATE TABLE IF NOT EXISTS maszyny (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stanowisko_id  INTEGER NOT NULL REFERENCES stanowiska(id) ON DELETE RESTRICT,
    nazwa          TEXT NOT NULL,
    typ            TEXT,
    producent      TEXT,
    model          TEXT,
    sprawna        INTEGER NOT NULL DEFAULT 1 CHECK (sprawna IN (0, 1))
);

-- Wyrób
CREATE TABLE IF NOT EXISTS produkty (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    kod    TEXT NOT NULL UNIQUE,
    nazwa  TEXT NOT NULL,
    opis   TEXT
);

-- Komponenty wyrobu; nadrzedny_id tworzy drzewo (rozgałęzienie)
CREATE TABLE IF NOT EXISTS komponenty (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt_id    INTEGER NOT NULL REFERENCES produkty(id) ON DELETE CASCADE,
    nadrzedny_id  INTEGER REFERENCES komponenty(id) ON DELETE CASCADE,
    kod           TEXT NOT NULL,
    nazwa         TEXT NOT NULL,
    material      TEXT,
    ilosc         INTEGER NOT NULL DEFAULT 1 CHECK (ilosc > 0),
    UNIQUE (produkt_id, kod)
);

-- Parametry: dotyczą wyrobu ALBO komponentu (dokładnie jednego z nich)
CREATE TABLE IF NOT EXISTS parametry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt_id    INTEGER REFERENCES produkty(id) ON DELETE CASCADE,
    komponent_id  INTEGER REFERENCES komponenty(id) ON DELETE CASCADE,
    nazwa         TEXT NOT NULL,
    wartosc       TEXT NOT NULL,
    jednostka     TEXT,
    CHECK ((produkt_id IS NOT NULL) + (komponent_id IS NOT NULL) = 1)
);

-- Karty technologiczne; komponent_id NULL = karta całego wyrobu (np. montaż)
CREATE TABLE IF NOT EXISTS karty_technologiczne (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt_id    INTEGER NOT NULL REFERENCES produkty(id) ON DELETE CASCADE,
    komponent_id  INTEGER REFERENCES komponenty(id) ON DELETE CASCADE,
    numer         TEXT NOT NULL UNIQUE,
    wersja        TEXT NOT NULL DEFAULT '1.0',
    opis          TEXT
);

-- Operacje na karcie: kolejność, stanowisko, maszyna, czasy [min]
CREATE TABLE IF NOT EXISTS operacje (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    karta_id       INTEGER NOT NULL REFERENCES karty_technologiczne(id) ON DELETE CASCADE,
    nr_operacji    INTEGER NOT NULL,
    stanowisko_id  INTEGER NOT NULL REFERENCES stanowiska(id),
    maszyna_id     INTEGER REFERENCES maszyny(id),
    nazwa          TEXT NOT NULL,
    opis           TEXT,
    tpz_min        REAL NOT NULL DEFAULT 0 CHECK (tpz_min >= 0),  -- czas przygotowawczo-zakończeniowy
    tj_min         REAL NOT NULL CHECK (tj_min > 0),              -- czas jednostkowy
    UNIQUE (karta_id, nr_operacji)
);

-- Maszyna użyta w operacji musi stać na stanowisku tej operacji
CREATE TRIGGER IF NOT EXISTS trg_operacje_maszyna_ins
BEFORE INSERT ON operacje
WHEN NEW.maszyna_id IS NOT NULL AND
     (SELECT stanowisko_id FROM maszyny WHERE id = NEW.maszyna_id) <> NEW.stanowisko_id
BEGIN
    SELECT RAISE(ABORT, 'Maszyna nie należy do wskazanego stanowiska');
END;

-- Widok pomocniczy: status stanowisk i lista maszyn
CREATE VIEW IF NOT EXISTS v_stanowiska AS
SELECT s.id,
       s.nazwa,
       CASE s.zajete WHEN 1 THEN 'zajęte' ELSE 'wolne' END AS status,
       GROUP_CONCAT(m.nazwa, ', ') AS maszyny
FROM stanowiska s
LEFT JOIN maszyny m ON m.stanowisko_id = s.id
GROUP BY s.id;
"""


def get_conn(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite domyślnie NIE pilnuje kluczy obcych
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path=DB_PATH, seed=True):
    conn = get_conn(path)
    conn.executescript(SCHEMA)
    if seed and conn.execute("SELECT COUNT(*) FROM stanowiska").fetchone()[0] == 0:
        seed_data(conn)
    conn.commit()
    return conn


def seed_data(conn):
    """Dane PRZYKŁADOWE - podmień na rzeczywiste."""
    cur = conn.cursor()

    # Stanowiska
    cur.executemany(
        "INSERT INTO stanowiska (nazwa, opis) VALUES (?, ?)",
        [("Cięcie laserowe", "Wycinanie elementów z blach"),
         ("Gięcie", "Gięcie elementów blaszanych"),
         ("Spawanie", "Spawanie zespołów")],
    )
    st = {r["nazwa"]: r["id"] for r in cur.execute("SELECT id, nazwa FROM stanowiska")}

    # Maszyny
    cur.executemany(
        "INSERT INTO maszyny (stanowisko_id, nazwa, typ, producent, model) VALUES (?, ?, ?, ?, ?)",
        [(st["Cięcie laserowe"], "Wycinarka laserowa", "laser światłowodowy", "Przykładowy", "L-3015"),
         (st["Gięcie"], "Prasa krawędziowa", "prasa hydrauliczna", "Przykładowy", "PK-100"),
         (st["Spawanie"], "Spawarka MIG/MAG", "spawarka", "Przykładowy", "MIG-350"),
         (st["Spawanie"], "Stół spawalniczy", "oprzyrządowanie", "Przykładowy", "SS-2")],
    )
    ma = {r["nazwa"]: r["id"] for r in cur.execute("SELECT id, nazwa FROM maszyny")}

    # Wyrób
    cur.execute("INSERT INTO produkty (kod, nazwa, opis) VALUES (?, ?, ?)",
                ("WYR-001", "Wspornik konstrukcyjny", "Wyrób spawany z elementów blaszanych"))
    pid = cur.lastrowid
    cur.executemany(
        "INSERT INTO parametry (produkt_id, nazwa, wartosc, jednostka) VALUES (?, ?, ?, ?)",
        [(pid, "Masa całkowita", "2.4", "kg"),
         (pid, "Gatunek stali", "S235JR", None)],
    )

    # Drzewo komponentów: wyrób -> zespół -> elementy
    def komp(kod, nazwa, material, ilosc, nadrzedny=None):
        cur.execute(
            "INSERT INTO komponenty (produkt_id, nadrzedny_id, kod, nazwa, material, ilosc) "
            "VALUES (?, ?, ?, ?, ?, ?)", (pid, nadrzedny, kod, nazwa, material, ilosc))
        return cur.lastrowid

    zesp = komp("ZESP-01", "Zespół spawany wspornika", None, 1)
    plyta = komp("KOMP-01", "Płyta podstawy", "S235JR", 1, zesp)
    sciana = komp("KOMP-02", "Ściana boczna", "S235JR", 2, zesp)
    zebro = komp("KOMP-03", "Żebro usztywniające", "S235JR", 2, zesp)

    # Parametry komponentów
    cur.executemany(
        "INSERT INTO parametry (komponent_id, nazwa, wartosc, jednostka) VALUES (?, ?, ?, ?)",
        [(plyta, "Grubość blachy", "5", "mm"), (plyta, "Wymiary", "200x100", "mm"),
         (sciana, "Grubość blachy", "3", "mm"), (sciana, "Kąt gięcia", "90", "°"),
         (zebro, "Grubość blachy", "3", "mm")],
    )

    # Karty technologiczne + operacje
    def karta(numer, komponent, opis, operacje):
        cur.execute(
            "INSERT INTO karty_technologiczne (produkt_id, komponent_id, numer, opis) VALUES (?, ?, ?, ?)",
            (pid, komponent, numer, opis))
        kid = cur.lastrowid
        cur.executemany(
            "INSERT INTO operacje (karta_id, nr_operacji, stanowisko_id, maszyna_id, nazwa, tpz_min, tj_min) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(kid, *op) for op in operacje])

    laser, giecie, spaw = st["Cięcie laserowe"], st["Gięcie"], st["Spawanie"]
    karta("KT-001", plyta, "Płyta podstawy",
          [(10, laser, ma["Wycinarka laserowa"], "Cięcie laserowe", 5, 2.0)])
    karta("KT-002", sciana, "Ściana boczna",
          [(10, laser, ma["Wycinarka laserowa"], "Cięcie laserowe", 5, 1.5),
           (20, giecie, ma["Prasa krawędziowa"], "Gięcie", 10, 1.0)])
    karta("KT-003", zebro, "Żebro usztywniające",
          [(10, laser, ma["Wycinarka laserowa"], "Cięcie laserowe", 5, 0.8)])
    karta("KT-004", None, "Montaż spawany wyrobu",
          [(10, spaw, ma["Spawarka MIG/MAG"], "Spawanie zespołu", 8, 6.5)])


# ---------- Funkcje pomocnicze (do użycia w Streamlit) ----------

def ustaw_zajetosc(conn, stanowisko_id, zajete: bool):
    conn.execute("UPDATE stanowiska SET zajete = ? WHERE id = ?", (int(zajete), stanowisko_id))
    conn.commit()


def drzewo_komponentow(conn, produkt_id):
    """Zwraca komponenty wyrobu z poziomem zagnieżdżenia (rekurencyjne CTE)."""
    return conn.execute("""
        WITH RECURSIVE drzewo(id, nadrzedny_id, kod, nazwa, material, ilosc, poziom) AS (
            SELECT id, nadrzedny_id, kod, nazwa, material, ilosc, 0
            FROM komponenty WHERE produkt_id = ? AND nadrzedny_id IS NULL
            UNION ALL
            SELECT k.id, k.nadrzedny_id, k.kod, k.nazwa, k.material, k.ilosc, d.poziom + 1
            FROM komponenty k JOIN drzewo d ON k.nadrzedny_id = d.id
        )
        SELECT * FROM drzewo ORDER BY poziom, kod
    """, (produkt_id,)).fetchall()


def operacje_karty(conn, numer_karty):
    return conn.execute("""
        SELECT o.nr_operacji, o.nazwa, s.nazwa AS stanowisko, m.nazwa AS maszyna,
               o.tpz_min, o.tj_min
        FROM operacje o
        JOIN karty_technologiczne k ON k.id = o.karta_id
        JOIN stanowiska s ON s.id = o.stanowisko_id
        LEFT JOIN maszyny m ON m.id = o.maszyna_id
        WHERE k.numer = ?
        ORDER BY o.nr_operacji
    """, (numer_karty,)).fetchall()


if __name__ == "__main__":
    conn = init_db()
    print("Stanowiska:")
    for r in conn.execute("SELECT * FROM v_stanowiska"):
        print(f"  {r['nazwa']:<16} {r['status']:<7} maszyny: {r['maszyny']}")
    print("\nDrzewo komponentów wyrobu WYR-001:")
    pid = conn.execute("SELECT id FROM produkty WHERE kod = 'WYR-001'").fetchone()["id"]
    for r in drzewo_komponentow(conn, pid):
        print("  " + "    " * r["poziom"] + f"{r['kod']} {r['nazwa']} (x{r['ilosc']})")
    print("\nKarta KT-002:")
    for r in operacje_karty(conn, "KT-002"):
        print(f"  {r['nr_operacji']}: {r['nazwa']} @ {r['stanowisko']} / {r['maszyna']}")
    conn.close()
