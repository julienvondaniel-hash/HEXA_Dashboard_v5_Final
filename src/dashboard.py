"""
HEXA Patrimoine - Dashboard v7.0
================================
Fetch des donnees economiques via APIs structurees uniquement.
Aucun appel Claude dans ce module - tout est fait via APIs officielles
avec fallbacks robustes en cascade.

Architecture v7.0 :
  Couche 1 (ici)        : APIs gratuites pour donnees chiffrees
  Couche 2 (analysis)   : 1 seul appel Claude pour PMI/SCPI/Immo + analyse
  Couche 3 (generate)   : PDF + email
"""
import os
import time
import datetime
from typing import Optional, Dict, Any

import requests

# ── Config ────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "HEXA-Dashboard/7.0 (patrimoine reporting; contact: dashboard@hexa-patrimoine.fr)",
    "Accept": "application/json, text/csv, */*",
}
TIMEOUT = 60   # secondes : large pour latence US <-> EU
RETRIES = 3    # 3 tentatives avec backoff exponentiel


def _get(url: str, timeout: int = TIMEOUT, retries: int = RETRIES,
         headers: Optional[Dict[str, str]] = None) -> Optional[requests.Response]:
    """GET HTTP avec retry exponentiel et User-Agent explicite.
    Renvoie la reponse ou None apres epuisement des retries."""
    h = {**HEADERS, **(headers or {})}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last_err = e
            wait = 2 ** attempt  # 1s, 2s, 4s
            print(f"    Tentative {attempt+1}/{retries} echec ({type(e).__name__}). Retry {wait}s.", flush=True)
            if attempt < retries - 1:
                time.sleep(wait)
    print(f"    Echec definitif : {last_err}", flush=True)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 : ECONOMIE (PIB / CPI)
# ═══════════════════════════════════════════════════════════════════════════

def fetch_eurostat_gdp(country_code: str) -> Optional[Dict[str, Any]]:
    """PIB trimestriel a/a via Eurostat.
    country_code : 'FR', 'EA20' (Zone Euro), 'DE', etc.
    """
    # GDP volume index, growth rate over same quarter previous year
    url = (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        f"namq_10_gdp?format=JSON&geo={country_code}&unit=CLV_PCH_PRE_HAB&s_adj=SCA&na_item=B1GQ&lang=FR"
    )
    # Note: l'endpoint above n'est pas robuste, on essaie une variante simple
    url = (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        f"namq_10_gdp?geo={country_code}&unit=CLV_PCH_SM&s_adj=SCA&na_item=B1GQ&format=JSON&lang=EN"
    )
    r = _get(url, timeout=45)
    if not r:
        return None
    try:
        data = r.json()
        values = data.get("value", {})
        dims = data.get("dimension", {}).get("time", {}).get("category", {}).get("index", {})
        if not values or not dims:
            return None
        # Trouver les 2 dernieres periodes
        # dims est un dict {period: index} ex {"2025-Q4": 100, "2026-Q1": 101}
        sorted_periods = sorted(dims.keys(), key=lambda k: dims[k], reverse=True)
        if len(sorted_periods) < 1:
            return None

        def fmt_period(p):
            # "2026-Q1" -> "T1 2026"
            if "-Q" in p:
                yr, q = p.split("-Q")
                return f"T{q} {yr}"
            return p

        latest = sorted_periods[0]
        prev = sorted_periods[1] if len(sorted_periods) > 1 else None
        # n1 : meme trimestre il y a 1 an
        n1 = None
        if "-Q" in latest:
            yr, q = latest.split("-Q")
            target = f"{int(yr)-1}-Q{q}"
            if target in dims:
                n1 = target

        def get_val(period):
            if period is None:
                return None
            idx = dims.get(period)
            if idx is None:
                return None
            return values.get(str(idx))

        v_latest = get_val(latest)
        v_prev = get_val(prev)
        v_n1 = get_val(n1)
        if v_latest is None:
            return None
        return {
            "val": f"{v_latest:.1f}%",
            "period": fmt_period(latest),
            "prev": f"{v_prev:.1f}%" if v_prev is not None else "N/D",
            "prev_period": fmt_period(prev) if prev else "N/D",
            "n1": f"{v_n1:.1f}%" if v_n1 is not None else "N/D",
            "n1_period": fmt_period(n1) if n1 else "N/D",
            "source": "Eurostat",
        }
    except Exception as e:
        print(f"    Parsing Eurostat echec : {e}", flush=True)
        return None


def fetch_eurostat_cpi(country_code: str) -> Optional[Dict[str, Any]]:
    """CPI a/a mensuel via Eurostat (HICP).
    country_code : 'FR', 'EA20', 'DE', etc.
    """
    url = (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        f"prc_hicp_manr?geo={country_code}&coicop=CP00&format=JSON&lang=EN"
    )
    r = _get(url, timeout=45)
    if not r:
        return None
    try:
        data = r.json()
        values = data.get("value", {})
        dims = data.get("dimension", {}).get("time", {}).get("category", {}).get("index", {})
        if not values or not dims:
            return None
        sorted_periods = sorted(dims.keys(), reverse=True)
        latest = sorted_periods[0]
        prev = sorted_periods[1] if len(sorted_periods) > 1 else None

        def fmt(p):
            if "-" in p and len(p.split("-")) == 2:
                yr, m = p.split("-")
                mois = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun",
                        "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
                try:
                    return f"{mois[int(m)-1]} {yr}"
                except (ValueError, IndexError):
                    return p
            return p

        # n1 : meme mois il y a 12 mois
        n1 = None
        if "-" in latest:
            yr, m = latest.split("-")
            target = f"{int(yr)-1}-{m}"
            if target in dims:
                n1 = target

        def get_val(period):
            if period is None:
                return None
            idx = dims.get(period)
            if idx is None:
                return None
            return values.get(str(idx))

        v = get_val(latest)
        vp = get_val(prev)
        v1 = get_val(n1)
        if v is None:
            return None
        return {
            "val": f"{v:.1f}%",
            "period": fmt(latest),
            "prev": f"{vp:.1f}%" if vp is not None else "N/D",
            "prev_period": fmt(prev) if prev else "N/D",
            "n1": f"{v1:.1f}%" if v1 is not None else "N/D",
            "n1_period": fmt(n1) if n1 else "N/D",
            "source": "Eurostat HICP",
        }
    except Exception as e:
        print(f"    Parsing Eurostat CPI echec : {e}", flush=True)
        return None


def fetch_bls_cpi() -> Optional[Dict[str, Any]]:
    """CPI USA via BLS API publique (no key requise pour usage limite).
    Serie CUUR0000SA0 = CPI All Urban Consumers, all items, NSA.
    On calcule l'a/a a partir des index mensuels."""
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0"
    payload = {"seriesid": ["CUUR0000SA0"], "startyear": str(datetime.datetime.now().year - 2),
               "endyear": str(datetime.datetime.now().year)}
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        series = d.get("Results", {}).get("series", [])
        if not series or not series[0].get("data"):
            return None
        data_pts = series[0]["data"]  # plus recent en premier
        # Index par (year, periodMM)
        idx = {(p["year"], p["period"][1:]): float(p["value"]) for p in data_pts
               if p.get("period", "").startswith("M") and p.get("value")}
        if not idx:
            return None
        # Trouver les periodes les plus recentes
        sorted_keys = sorted(idx.keys(), key=lambda k: (int(k[0]), int(k[1])), reverse=True)
        latest = sorted_keys[0]
        prev = sorted_keys[1] if len(sorted_keys) > 1 else None
        a1 = (str(int(latest[0]) - 1), latest[1])
        a1_prev = (str(int(prev[0]) - 1), prev[1]) if prev else None

        def yoy(now_key, year_ago_key):
            now_v = idx.get(now_key)
            past_v = idx.get(year_ago_key)
            if now_v is None or past_v is None:
                return None
            return (now_v / past_v - 1) * 100

        v = yoy(latest, a1)
        vp = yoy(prev, a1_prev) if prev else None
        # n1 : valeur a/a il y a 12 mois
        a1_a2 = (str(int(latest[0]) - 2), latest[1])
        v1 = yoy(a1, a1_a2)

        def fmt(k):
            mois = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
            return f"{mois[int(k[1])-1]} {k[0]}"

        if v is None:
            return None
        return {
            "val": f"{v:.1f}%",
            "period": fmt(latest),
            "prev": f"{vp:.1f}%" if vp is not None else "N/D",
            "prev_period": fmt(prev) if prev else "N/D",
            "n1": f"{v1:.1f}%" if v1 is not None else "N/D",
            "n1_period": fmt(a1) if a1 else "N/D",
            "source": "BLS CPI-U",
        }
    except Exception as e:
        print(f"    BLS CPI echec : {e}", flush=True)
        return None


def fetch_bea_gdp() -> Optional[Dict[str, Any]]:
    """PIB USA via FRED A191RL1Q225SBEA (Real GDP, Percent Change from Year Ago).
    Plus stable que BEA API qui necessite une cle."""
    return fetch_fred("A191RL1Q225SBEA", as_quarterly_gdp=True, source_label="FRED (BEA)")


def fetch_wb(indicator: str, country: str, label_source: str = None) -> Optional[Dict[str, Any]]:
    """Banque Mondiale World Development Indicators (annuel)."""
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&per_page=10&date=2020:2026"
    r = _get(url, timeout=45)
    if not r:
        return None
    try:
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return None
        rows = [x for x in data[1] if x.get("value") is not None]
        if not rows:
            return None
        rows.sort(key=lambda x: x["date"], reverse=True)
        latest, prev, n1 = rows[0], (rows[1] if len(rows) > 1 else None), (rows[2] if len(rows) > 2 else None)

        def fmt_val(v):
            return f"{v:+.1f}%" if v is not None else "N/D"

        return {
            "val": fmt_val(latest["value"]),
            "period": latest["date"],
            "prev": fmt_val(prev["value"]) if prev else "N/D",
            "prev_period": prev["date"] if prev else "N/D",
            "n1": fmt_val(n1["value"]) if n1 else "N/D",
            "n1_period": n1["date"] if n1 else "N/D",
            "source": label_source or f"Banque Mondiale ({country})",
        }
    except Exception as e:
        print(f"    World Bank {country} echec : {e}", flush=True)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 : TAUX DIRECTEURS
# ═══════════════════════════════════════════════════════════════════════════

def fetch_fred(series: str, as_quarterly_gdp: bool = False,
               source_label: str = None) -> Optional[Dict[str, Any]]:
    """Recuperation generique d'une serie FRED via l'API publique (sans cle pour CSV).
    Endpoint CSV qui ne necessite pas de cle API et est tres stable."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    r = _get(url, timeout=TIMEOUT)
    if not r:
        return None
    try:
        lines = [l.strip() for l in r.text.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            return None
        # CSV : "observation_date,SERIES"
        data_pts = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < 2:
                continue
            date, val = parts[0], parts[1]
            if val in ("", ".", "NaN"):
                continue
            try:
                data_pts.append((date, float(val)))
            except ValueError:
                continue
        if not data_pts:
            return None
        data_pts.sort(key=lambda x: x[0], reverse=True)
        latest = data_pts[0]
        prev = data_pts[1] if len(data_pts) > 1 else None

        # Pour A-1 : trouver une obs ~12 mois avant
        latest_yr = int(latest[0][:4])
        latest_mo = int(latest[0][5:7])
        n1 = None
        for d, v in data_pts:
            yr, mo = int(d[:4]), int(d[5:7])
            if yr == latest_yr - 1 and mo == latest_mo:
                n1 = (d, v)
                break

        def fmt_pct(v):
            return f"{v:.2f}%" if v is not None else "N/D"

        def fmt_quarter(date_str):
            # date format YYYY-MM-DD, quarter inferred from month
            yr, mo = int(date_str[:4]), int(date_str[5:7])
            q = (mo - 1) // 3 + 1
            return f"T{q} {yr}"

        def fmt_month(date_str):
            yr, mo = int(date_str[:4]), int(date_str[5:7])
            mois = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
            return f"{mois[mo-1]} {yr}"

        fmt = fmt_quarter if as_quarterly_gdp else fmt_month
        fmt_v = (lambda x: f"{x:+.1f}%") if as_quarterly_gdp else fmt_pct

        return {
            "val": fmt_v(latest[1]),
            "period": fmt(latest[0]),
            "prev": fmt_v(prev[1]) if prev else "N/D",
            "prev_period": fmt(prev[0]) if prev else "N/D",
            "n1": fmt_v(n1[1]) if n1 else "N/D",
            "n1_period": fmt(n1[0]) if n1 else "N/D",
            "source": source_label or f"FRED ({series})",
        }
    except Exception as e:
        print(f"    FRED {series} echec : {e}", flush=True)
        return None


def fetch_ecb_rate() -> Optional[Dict[str, Any]]:
    """Taux de depot BCE via FRED (ECBDFR) - plus stable que l'API SDW directe."""
    return fetch_fred("ECBDFR", source_label="ECB (via FRED)")


def fetch_fed_rate() -> Optional[Dict[str, Any]]:
    """Fed Funds rate via FRED DFEDTARU (upper bound). Daily series."""
    return fetch_fred("DFEDTARU", source_label="Federal Reserve")


def fetch_euribor() -> Optional[Dict[str, Any]]:
    """Euribor 3 mois via FRED IR3TIB01EZM156N (OECD). Donnees mensuelles."""
    return fetch_fred("IR3TIB01EZM156N", source_label="Euribor 3M (OECD via FRED)")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 : OAT/BUND ET SPREADS CREDIT
# ═══════════════════════════════════════════════════════════════════════════

def fetch_spread_oat_bund() -> Optional[Dict[str, Any]]:
    """Calcule le spread OAT/Bund via FRED."""
    oat = fetch_fred("IRLTLT01FRM156N", source_label="FRED")
    bund = fetch_fred("IRLTLT01DEM156N", source_label="FRED")
    if not oat or not bund:
        return None
    try:
        oat_v = float(oat["val"].rstrip("%"))
        bund_v = float(bund["val"].rstrip("%"))
        spread = (oat_v - bund_v) * 100  # en bps
        # prev
        spread_prev = None
        if oat.get("prev", "N/D") != "N/D" and bund.get("prev", "N/D") != "N/D":
            spread_prev = (float(oat["prev"].rstrip("%")) - float(bund["prev"].rstrip("%"))) * 100
        return {
            "spread": f"{spread:.0f}",
            "spread_prev": f"{spread_prev:.0f}" if spread_prev is not None else "N/D",
            "oat": oat["val"],
            "bund": bund["val"],
            "source": "FRED (OECD long-term rates)",
        }
    except Exception as e:
        print(f"    Spread OAT/Bund calcul echec : {e}", flush=True)
        return None


def fetch_credit_spreads() -> Optional[Dict[str, Any]]:
    """Spreads IG et HY via FRED ICE BofA."""
    ig = fetch_fred("BAMLC0A0CM")
    hy = fetch_fred("BAMLH0A0HYM2")
    if not ig and not hy:
        return None
    try:
        out = {}
        if ig:
            # FRED renvoie en %, on convertit en bps
            ig_v = float(ig["val"].rstrip("%")) * 100
            ig_p = float(ig["prev"].rstrip("%")) * 100 if ig["prev"] != "N/D" else None
            ig_n = float(ig["n1"].rstrip("%")) * 100 if ig["n1"] != "N/D" else None
            out["ig_spread"] = f"{ig_v:.0f}"
            out["ig_spread_prev"] = f"{ig_p:.0f}" if ig_p is not None else "N/D"
            out["ig_spread_n1"] = f"{ig_n:.0f}" if ig_n is not None else "N/D"
        else:
            out.update({"ig_spread": "N/D", "ig_spread_prev": "N/D", "ig_spread_n1": "N/D"})
        if hy:
            hy_v = float(hy["val"].rstrip("%")) * 100
            hy_p = float(hy["prev"].rstrip("%")) * 100 if hy["prev"] != "N/D" else None
            hy_n = float(hy["n1"].rstrip("%")) * 100 if hy["n1"] != "N/D" else None
            out["hy_spread"] = f"{hy_v:.0f}"
            out["hy_spread_prev"] = f"{hy_p:.0f}" if hy_p is not None else "N/D"
            out["hy_spread_n1"] = f"{hy_n:.0f}" if hy_n is not None else "N/D"
        else:
            out.update({"hy_spread": "N/D", "hy_spread_prev": "N/D", "hy_spread_n1": "N/D"})
        out["source"] = "FRED ICE BofA"
        return out
    except Exception as e:
        print(f"    Credit spreads parse echec : {e}", flush=True)
        return None


def fetch_us_curve() -> Optional[Dict[str, Any]]:
    """Courbe US 2 ans / 10 ans via FRED."""
    t2 = fetch_fred("DGS2")  # 2-Year Treasury Constant Maturity
    t10 = fetch_fred("DGS10")  # 10-Year
    if not t2 or not t10:
        return None
    try:
        t2_v = float(t2["val"].rstrip("%"))
        t10_v = float(t10["val"].rstrip("%"))
        spread = t10_v - t2_v
        signal = "Normal" if spread > 0 else "Inverse"
        return {
            "us_2y": t2["val"],
            "us_10y": t10["val"],
            "spread": f"{spread:.2f}",
            "spread_prev": "N/D",
            "signal": signal,
            "source": "FRED (US Treasury)",
        }
    except Exception as e:
        print(f"    US curve echec : {e}", flush=True)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 : MARCHES (Yahoo Finance) ET FEAR & GREED
# ═══════════════════════════════════════════════════════════════════════════

def fetch_yahoo_chart(ticker: str, range_param: str = "14mo") -> Optional[Dict[str, Any]]:
    """Cours actuel + il y a 1 mois + il y a 1 an via Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={range_param}"
    r = _get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    if not r:
        return None
    try:
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        chart = result[0]
        timestamps = chart.get("timestamp", [])
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        if not timestamps or not closes:
            return None
        # Filtrer les None
        pts = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
        if not pts:
            return None
        latest_t, latest_v = pts[-1]
        # Trouver la valeur il y a ~30 jours
        target_1m = latest_t - 30 * 86400
        target_1y = latest_t - 365 * 86400
        prev_m = min(pts, key=lambda x: abs(x[0] - target_1m))[1]
        prev_y = min(pts, key=lambda x: abs(x[0] - target_1y))[1]
        return {"val": latest_v, "prev_m": prev_m, "prev_y": prev_y}
    except Exception as e:
        print(f"    Yahoo {ticker} echec : {e}", flush=True)
        return None


def fetch_vix() -> Optional[Dict[str, Any]]:
    v = fetch_yahoo_chart("^VIX", range_param="14mo")
    if not v:
        return None
    return {
        "val": f"{v['val']:.2f}",
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "prev": f"{v['prev_m']:.2f}",
        "prev_date": (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d"),
        "n1": f"{v['prev_y']:.2f}",
        "n1_date": (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d"),
        "source": "CBOE via Yahoo Finance",
    }


def fetch_fear_greed() -> Optional[Dict[str, Any]]:
    """Index Fear & Greed via l'API CNN non documentee (lecture seule, publique)."""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    r = _get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    if not r:
        return None
    try:
        data = r.json()
        fg = data.get("fear_and_greed", {})
        val = int(round(fg.get("score", 0)))
        label = fg.get("rating", "Neutral").capitalize()
        prev_close = int(round(fg.get("previous_close", val)))
        prev_y = int(round(fg.get("previous_1_year", val)))
        return {
            "val": str(val),
            "label": label,
            "prev": str(prev_close),
            "n1": str(prev_y),
            "source": "CNN Business",
        }
    except Exception as e:
        print(f"    Fear & Greed echec : {e}", flush=True)
        return None


def fetch_bls_nfp() -> Optional[Dict[str, Any]]:
    """Non-Farm Payrolls via BLS PUBLIC API (CES0000000001 = Total nonfarm SA, thousands).
    On renvoie la variation mensuelle (change in NFP)."""
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001"
    payload = {"seriesid": ["CES0000000001"], "startyear": str(datetime.datetime.now().year - 2),
               "endyear": str(datetime.datetime.now().year)}
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        series = d.get("Results", {}).get("series", [])
        if not series or not series[0].get("data"):
            return None
        pts = series[0]["data"]
        pts = [(p["year"], p["period"], float(p["value"])) for p in pts
               if p.get("period", "").startswith("M") and p.get("value")]
        if len(pts) < 13:
            return None
        # Tri chrono : recent en premier
        pts.sort(key=lambda x: (int(x[0]), int(x[1][1:])), reverse=True)
        latest = pts[0]
        prev = pts[1]
        n12 = pts[12] if len(pts) > 12 else None
        n13 = pts[13] if len(pts) > 13 else None

        def change(now, before):
            # Niveaux en milliers, variation = (now - before) * 1000 emplois
            return (now[2] - before[2]) * 1000

        delta_latest = change(latest, prev)
        delta_n1 = change(n12, n13) if n12 and n13 else None

        def fmt_period(p):
            mois = ["Jan", "Fev", "Mar", "Avr", "Mai", "Jun", "Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]
            mo = int(p[1][1:])
            return f"{p[0]}-{p[1][1:]}"

        return {
            "val": f"+{delta_latest:+,.0f}".replace("++", "+"),
            "period": fmt_period(latest),
            "prev": f"+{change(prev, pts[2]):+,.0f}".replace("++", "+"),
            "prev_period": fmt_period(prev),
            "n1": f"+{delta_n1:+,.0f}".replace("++", "+") if delta_n1 is not None else "N/D",
            "n1_period": fmt_period(n12) if n12 else "N/D",
            "source": "BLS CES",
        }
    except Exception as e:
        print(f"    NFP echec : {e}", flush=True)
        return None


def fetch_bls_unemployment() -> Optional[Dict[str, Any]]:
    """Taux de chomage US via BLS LNS14000000."""
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/LNS14000000"
    payload = {"seriesid": ["LNS14000000"], "startyear": str(datetime.datetime.now().year),
               "endyear": str(datetime.datetime.now().year)}
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        series = d.get("Results", {}).get("series", [])
        if not series or not series[0].get("data"):
            return None
        pts = series[0]["data"]
        if not pts:
            return None
        latest = pts[0]
        return {
            "val": f"{float(latest['value']):.1f}%",
            "period": f"{latest['year']}-{latest['period'][1:]}",
        }
    except Exception as e:
        print(f"    Unemployment echec : {e}", flush=True)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 : INDICES / FOREX / MATIERES
# ═══════════════════════════════════════════════════════════════════════════

INDICES = {
    "CAC 40": "^FCHI", "Euro Stoxx 50": "^STOXX50E", "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC", "Dow Jones": "^DJI", "FTSE 100": "^FTSE",
    "Nikkei 225": "^N225", "Shanghai": "000001.SS", "MSCI EM": "EEM",
}

FOREX = [
    ("EUR/USD", "EURUSD=X"), ("EUR/GBP", "EURGBP=X"), ("EUR/JPY", "EURJPY=X"),
    ("EUR/CHF", "EURCHF=X"), ("EUR/CNY", "EURCNY=X"),
]

COMMODITIES = [
    ("Or", "GC=F"), ("Argent", "SI=F"), ("Cuivre", "HG=F"),
    ("Gaz naturel", "NG=F"), ("Brent", "BZ=F"),
]


def fetch_indices() -> Dict[str, Any]:
    out = {}
    for name, ticker in INDICES.items():
        v = fetch_yahoo_chart(ticker)
        if v:
            out[name] = v
            print(f"    {name} OK", flush=True)
        else:
            print(f"    {name} ECHEC", flush=True)
    return out


def fetch_forex() -> Dict[str, Any]:
    out = {}
    for pair, ticker in FOREX:
        v = fetch_yahoo_chart(ticker)
        if v:
            out[pair] = {"val": v["val"], "prev_m": v["prev_m"], "n1": v["prev_y"]}
            print(f"    {pair} OK", flush=True)
    return out


def fetch_commodities() -> Dict[str, Any]:
    out = {}
    for name, ticker in COMMODITIES:
        v = fetch_yahoo_chart(ticker)
        if v:
            out[name] = {"val": v["val"], "prev_m": v["prev_m"], "n1": v["prev_y"]}
            print(f"    {name} OK ({ticker})", flush=True)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def collect_all() -> Dict[str, Any]:
    """Lance toutes les fetchs en sequence et renvoie le dict complet de donnees."""
    print("=== Collecte v7.0 : APIs structurees uniquement ===", flush=True)
    today = datetime.datetime.now()
    mois_fr = ["Janvier", "Fevrier", "Mars", "Avril", "Mai", "Juin",
               "Juillet", "Aout", "Septembre", "Octobre", "Novembre", "Decembre"]
    data: Dict[str, Any] = {
        "date": f"{mois_fr[today.month-1]} {today.year}",
        "collected_at": today.strftime("%Y-%m-%d"),
    }

    # ─── PIB ──────────────────────────────────────────────────────────────
    print("\n[1/8] PIB...", flush=True)
    print("  PIB France (Eurostat)...", flush=True)
    data["gdp_fr"] = fetch_eurostat_gdp("FR") or _nd_gdp("Eurostat (indisponible)")
    print("  PIB Zone Euro (Eurostat)...", flush=True)
    data["gdp_ez"] = fetch_eurostat_gdp("EA20") or _nd_gdp("Eurostat (indisponible)")
    print("  PIB Etats-Unis (FRED A191RL1Q225SBEA)...", flush=True)
    data["gdp_usa"] = fetch_bea_gdp() or _nd_gdp("FRED BEA (indisponible)")
    print("  PIB Chine (Banque Mondiale)...", flush=True)
    data["gdp_chine"] = fetch_wb("NY.GDP.MKTP.KD.ZG", "CHN") or _nd_gdp("Banque Mondiale (indisponible)")
    print("  PIB Bresil (Banque Mondiale)...", flush=True)
    data["gdp_bresil"] = fetch_wb("NY.GDP.MKTP.KD.ZG", "BRA") or _nd_gdp("Banque Mondiale (indisponible)")
    print("  PIB Inde (Banque Mondiale)...", flush=True)
    data["gdp_inde"] = fetch_wb("NY.GDP.MKTP.KD.ZG", "IND") or _nd_gdp("Banque Mondiale (indisponible)")
    data["gdp_emergents"] = _nd_gdp("Non utilise depuis v6.5.6")

    # ─── CPI ──────────────────────────────────────────────────────────────
    print("\n[2/8] CPI...", flush=True)
    print("  CPI France (Eurostat HICP)...", flush=True)
    data["cpi_fr"] = fetch_eurostat_cpi("FR") or _nd_cpi("Eurostat (indisponible)")
    print("  CPI Zone Euro (Eurostat HICP)...", flush=True)
    data["cpi_ez"] = fetch_eurostat_cpi("EA20") or _nd_cpi("Eurostat (indisponible)")
    print("  CPI Etats-Unis (BLS)...", flush=True)
    data["cpi_usa"] = fetch_bls_cpi() or _nd_cpi("BLS (indisponible)")
    print("  CPI Chine (Banque Mondiale)...", flush=True)
    data["cpi_chine"] = fetch_wb("FP.CPI.TOTL.ZG", "CHN") or _nd_cpi("Banque Mondiale (indisponible)")
    print("  CPI Bresil (Banque Mondiale)...", flush=True)
    data["cpi_bresil"] = fetch_wb("FP.CPI.TOTL.ZG", "BRA") or _nd_cpi("Banque Mondiale (indisponible)")
    print("  CPI Inde (Banque Mondiale)...", flush=True)
    data["cpi_inde"] = fetch_wb("FP.CPI.TOTL.ZG", "IND") or _nd_cpi("Banque Mondiale (indisponible)")

    # ─── Taux directeurs ──────────────────────────────────────────────────
    print("\n[3/8] Taux directeurs...", flush=True)
    print("  BCE (FRED ECBDFR)...", flush=True)
    ecb = fetch_ecb_rate()
    if ecb:
        data["ecb_rate"] = {"val": ecb["val"], "detail": "Taux de depot BCE",
                            "prev": ecb["prev"], "prev_period": ecb["prev_period"],
                            "source": ecb["source"]}
    else:
        data["ecb_rate"] = {"val": "N/D", "detail": "Taux de depot BCE", "prev": "N/D",
                            "prev_period": "N/D", "source": "ECB (indisponible)"}
    print("  Fed (FRED DFEDTARU)...", flush=True)
    fed = fetch_fed_rate()
    if fed:
        data["fed_rate"] = {**fed, "detail": "Fed Funds upper bound"}
    else:
        data["fed_rate"] = {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D",
                            "n1": "N/D", "n1_period": "N/D", "source": "Fed (indisponible)",
                            "detail": "Fed Funds upper bound"}

    # PBoC / BCB / RBI : pas d'API officielle stable, on laisse N/D pour Claude analyse
    data["pboc"]      = {"val": "N/D", "prev": "N/D", "detail": "LPR 1 an", "source": "PBoC (web_search a faire)"}
    data["bcb_selic"] = {"val": "N/D", "prev": "N/D", "detail": "Taux Selic", "source": "BCB (web_search a faire)"}
    data["rbi_repo"]  = {"val": "N/D", "prev": "N/D", "detail": "Repo Rate", "source": "RBI (web_search a faire)"}

    # ─── Euribor ──────────────────────────────────────────────────────────
    print("\n[4/8] Euribor...", flush=True)
    print("  Euribor 3M (FRED OECD)...", flush=True)
    eur = fetch_euribor()
    if eur:
        data["euribor"] = {"val": eur["val"], "date": eur["period"],
                           "prev": eur["prev"], "prev_date": eur["prev_period"],
                           "n1": eur["n1"], "n1_date": eur["n1_period"],
                           "source": eur["source"]}
    else:
        data["euribor"] = {"val": "N/D", "date": "N/D", "prev": "N/D", "prev_date": "N/D",
                           "n1": "N/D", "n1_date": "N/D", "source": "Euribor (indisponible)"}

    # ─── Spreads / Courbe US ──────────────────────────────────────────────
    print("\n[5/8] Spreads et courbe...", flush=True)
    print("  Spread OAT/Bund (FRED OECD)...", flush=True)
    data["spread"] = fetch_spread_oat_bund() or {
        "spread": "N/D", "spread_prev": "N/D", "oat": "N/D", "bund": "N/D",
        "source": "FRED (indisponible)",
    }
    print("  Courbe US 2/10 ans (FRED)...", flush=True)
    data["spread_us_curve"] = fetch_us_curve() or {
        "us_2y": "N/D", "us_10y": "N/D", "spread": "N/D", "spread_prev": "N/D",
        "signal": "N/D", "source": "FRED (indisponible)",
    }
    print("  Spreads IG/HY (FRED ICE BofA)...", flush=True)
    data["credit_spreads"] = fetch_credit_spreads() or {
        "ig_spread": "N/D", "ig_spread_prev": "N/D", "ig_spread_n1": "N/D",
        "hy_spread": "N/D", "hy_spread_prev": "N/D", "hy_spread_n1": "N/D",
        "source": "FRED (indisponible)",
    }

    # ─── Marches : VIX, F&G, NFP, chomage ─────────────────────────────────
    print("\n[6/8] Indicateurs de marche...", flush=True)
    print("  VIX (Yahoo Finance)...", flush=True)
    data["vix"] = fetch_vix() or {"val": "N/D", "date": "N/D", "prev": "N/D",
                                   "prev_date": "N/D", "n1": "N/D", "n1_date": "N/D",
                                   "source": "Yahoo (indisponible)"}
    print("  Fear & Greed (CNN)...", flush=True)
    data["fg"] = fetch_fear_greed() or {"val": "N/D", "label": "N/D", "prev": "N/D",
                                         "n1": "N/D", "source": "CNN (indisponible)"}
    print("  NFP (BLS)...", flush=True)
    data["nfp"] = fetch_bls_nfp() or {"val": "N/D", "period": "N/D", "prev": "N/D",
                                       "prev_period": "N/D", "n1": "N/D", "n1_period": "N/D",
                                       "source": "BLS (indisponible)"}
    print("  Unemployment (BLS)...", flush=True)
    data["unemployment_usa"] = fetch_bls_unemployment() or {"val": "N/D", "period": "N/D"}

    # ─── Indices / Forex / Matieres ───────────────────────────────────────
    print("\n[7/8] Marches mondiaux...", flush=True)
    print("  Indices boursiers...", flush=True)
    data["indices"] = fetch_indices()
    print("  Taux de change...", flush=True)
    data["forex"] = fetch_forex()
    print("  Matieres premieres...", flush=True)
    data["commodities"] = fetch_commodities()

    # EUR/USD pour conversions matieres
    if "EUR/USD" in data["forex"]:
        data["eurusd"] = data["forex"]["EUR/USD"]["val"]
    else:
        data["eurusd"] = 1.10  # fallback raisonnable

    # ─── PMI / Immo / SCPI / PE : laisses vides pour Claude analyse ───────
    print("\n[8/8] Donnees a recuperer par Claude analyse...", flush=True)
    data["pmi"] = {z: {"val": "N/D", "period": "N/D", "prev": "N/D", "source": "S&P Global PMI"}
                   for z in ["france", "usa", "ez", "chine", "bresil", "inde"]}
    data["immo_prix"] = {}
    data["immobilier_taux"] = {
        "taux_20ans": "N/D", "taux_20ans_prev": "N/D", "taux_20ans_n1": "N/D",
        "taux_20ans_commentaire": "A recuperer (CAFPI/Empruntis)",
        "bureaux_val": "N/D", "bureaux_prev": "N/D", "bureaux_n1": "N/D",
        "bureaux_commentaire": "A recuperer (JLL/CBRE)",
        "commerces_val": "N/D", "commerces_prev": "N/D", "commerces_n1": "N/D",
        "commerces_commentaire": "A recuperer (JLL/CBRE)",
    }
    data["private_equity"] = {
        "argos": ("N/D", "N/D", "N/D", "N/D", "N/D"),
        "dp": ("N/D", "", ""), "rdt": ("N/D", "", ""),
        "levees": ("N/D", "", ""), "invest": ("N/D", "", ""),
        "cessions": ("N/D", "", ""), "nb_ent": ("N/D", "", ""),
    }
    data["scpi"] = {
        "marche": {"td_moyen": "N/D", "td_moyen_prev": "N/D", "td_moyen_n1": "N/D",
                   "collecte_nette": "N/D", "collecte_prev": "N/D", "collecte_periode": "N/D",
                   "decote_secondaire": "N/D", "decote_prev": "N/D", "tof_moyen": "N/D",
                   "source": "ASPIM/IEIF (a recuperer)"},
        "par_secteur": [], "scpi_top10": [], "analyse": "",
        "points_vigilance": [], "opportunites": [],
    }

    print("\n=== Collecte terminee ===", flush=True)
    return data


def _nd_gdp(source: str) -> Dict[str, Any]:
    return {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D",
            "n1": "N/D", "n1_period": "N/D", "source": source}


def _nd_cpi(source: str) -> Dict[str, Any]:
    return {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D",
            "n1": "N/D", "n1_period": "N/D", "source": source}


if __name__ == "__main__":
    import json
    d = collect_all()
    print("\n=== Resume ===")
    print(json.dumps({k: v for k, v in d.items() if k not in ("indices", "forex", "commodities")},
                     indent=2, ensure_ascii=False, default=str)[:3000])
