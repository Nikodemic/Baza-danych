"""Aplikacja Streamlit - linia produkcyjna (3 stanowiska, 1 wyrób).

Uruchomienie:  streamlit run app.py
Pliki baza.py, dane.py i app.py muszą leżeć w jednym folderze.
"""
import streamlit as st

import baza
import dane

st.set_page_config(page_title="Linia produkcyjna", page_icon="🏭", layout="wide")


@st.cache_resource
def start():
    """Tworzy bazę z danymi przykładowymi, jeśli plik produkcja.db jeszcze nie istnieje."""
    baza.init_db().close()
    return True


start()

st.title("🏭 Linia produkcyjna")
tab_stan, tab_wyrob, tab_karty, tab_obc = st.tabs(
    ["Stanowiska", "Wyrób", "Karty technologiczne", "Obciążenie"])


# ---------- 1. Stanowiska ----------
def zmien_zajetosc(sid):
    dane.ustaw_zajetosc(sid, st.session_state[f"zajete_{sid}"])


with tab_stan:
    stan = dane.stanowiska()
    kolumny = st.columns(len(stan))
    for kol, r in zip(kolumny, stan.itertuples()):
        with kol, st.container(border=True):
            st.subheader(r.nazwa)
            st.caption(r.opis or " ")
            if r.zajete:
                st.error("● ZAJĘTE")
            else:
                st.success("● WOLNE")
            st.toggle("Stanowisko zajęte", value=bool(r.zajete), key=f"zajete_{r.id}",
                      on_change=zmien_zajetosc, args=(r.id,))
            st.markdown("**Maszyny**")
            st.dataframe(dane.maszyny(r.id), hide_index=True)


# ---------- 2. Wyrób ----------
with tab_wyrob:
    prod = dane.produkty()
    if prod.empty:
        st.info("Brak wyrobów w bazie.")
    else:
        idx = st.selectbox("Wyrób", list(range(len(prod))),
                           format_func=lambda i: f"{prod.kod[i]} – {prod.nazwa[i]}")
        pid = int(prod.id[idx])
        st.write(prod.opis[idx])

        komp = dane.komponenty(pid)
        lewa, prawa = st.columns([3, 2])
        with lewa:
            st.markdown("**Struktura wyrobu**")
            if komp.empty:
                st.info("Wyrób nie ma jeszcze komponentów.")
            else:
                st.graphviz_chart(dane.dot_drzewo(prod.nazwa[idx], komp))
        with prawa:
            st.markdown("**Parametry wyrobu**")
            st.dataframe(dane.parametry_wyrobu(pid), hide_index=True)

        if not komp.empty:
            st.markdown("**Komponenty**")
            widok = komp.assign(struktura=komp.poziom.map(lambda p: "— " * p) + komp.nazwa)
            st.dataframe(widok[["kod", "struktura", "material", "ilosc"]], hide_index=True)

            etykiety = dict(zip(komp.id.tolist(), (komp.kod + " – " + komp.nazwa).tolist()))
            wybrany = st.selectbox("Parametry komponentu", komp.id.tolist(),
                                   format_func=lambda i: etykiety[i])
            par = dane.parametry_komponentu(wybrany)
            if par.empty:
                st.caption("Ten komponent nie ma zdefiniowanych parametrów.")
            else:
                st.dataframe(par, hide_index=True)


# ---------- 3. Karty technologiczne ----------
with tab_karty:
    karty = dane.karty()
    if karty.empty:
        st.info("Brak kart technologicznych.")
    else:
        opisy = dict(zip(karty.numer, karty.numer + " – " + karty.opis))
        numer = st.selectbox("Karta technologiczna", karty.numer.tolist(),
                             format_func=lambda n: opisy[n])
        info = karty[karty.numer == numer].iloc[0]
        st.caption(f"Dotyczy: {info.komponent} · wersja {info.wersja}")

        oper = dane.operacje_karty(numer)
        if oper.empty:
            st.info("Karta nie ma jeszcze operacji.")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Liczba operacji", len(oper))
            m2.metric("Suma tpz [min]", round(oper.tpz_min.sum(), 2))
            m3.metric("Suma tj [min]", round(oper.tj_min.sum(), 2))
            st.graphviz_chart(dane.dot_operacje(oper))
            st.dataframe(oper, hide_index=True)


# ---------- 4. Obciążenie ----------
with tab_obc:
    obc = dane.obciazenie()
    st.markdown("**Czas jednostkowy na stanowisku (na jeden wyrób)**")
    st.caption("tj z kart technologicznych × liczba sztuk komponentu w wyrobie.")
    if obc.czas_na_wyrob_min.sum() == 0:
        st.info("Brak operacji do zsumowania.")
    else:
        st.bar_chart(obc.set_index("stanowisko")["czas_na_wyrob_min"])
        waskie = obc.loc[obc.czas_na_wyrob_min.idxmax()]
        st.metric("Najbardziej obciążone stanowisko",
                  f"{waskie.stanowisko} ({waskie.czas_na_wyrob_min:.1f} min)")
    st.dataframe(obc, hide_index=True)
