"""
Collecte automatique des données économiques et financières.
Sources : BEA, BLS, Eurostat, ECB, Fed, Yahoo Finance, FRED, Banque Mondiale
Toutes les données non disponibles ici sont collectées par Claude web_search.
"""
import requests
import datetime
import json

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HEXADashboard/1.0)"}

def get(url, timeout=30, retries=2):
    """GET avec 2 retries + backoff court.
    Quand FRED/ECB sont en panne, la 3eme tentative ne recupere jamais rien,
    donc on s'arrete plus tot pour reduire le temps total du run."""
    import time as _t
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  Tentative {attempt+1}/{retries} echouee: {e}", flush=True)
            if attempt < retries - 1:
                _t.sleep(1)  # 1s entre tentatives (au lieu de backoff exponentiel)
    return None

def get_json(url, **kw):
    r = get(url, **kw)
    if r is None: return {}
    try: return r.json()
    except: return {}


def fetch_fred_series(series_id, timeout=45):
    """
    Recupere une serie FRED via l'endpoint CSV stable.
    Retourne une liste de tuples (date_str, valeur_float) triee chronologiquement,
    ou liste vide en cas d'echec. Cette helper centralise tous les acces FRED.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = get(url, timeout=timeout)
    if r is None:
        return []
    lines = [l for l in r.text.strip().split("\n") if l and not l.startswith("DATE")]
    out = []
    for line in lines:
        cells = line.split(",")
        if len(cells) < 2:
            continue
        d = cells[0].strip()
        v = cells[1].strip()
        if v in ("", "."):
            continue
        try:
            out.append((d, float(v)))
        except ValueError:
            continue
    out.sort(key=lambda x: x[0])
    return out

def fetch_gdp_usa():
    try:
        url = ("https://apps.bea.gov/api/data?UserID=GUEST"
               "&method=GetData&DataSetName=NIPA"
               "&TableName=T10101&Frequency=Q&Year=X&ResultFormat=JSON")
        data = get_json(url)
        # Structure attendue : BEAAPI.Results.Data (anciennement)
        # ou BEAAPI.Results[0].Data (parfois liste). On gere les deux cas.
        try:
            results = data["BEAAPI"]["Results"]
        except (KeyError, TypeError):
            raise Exception("BEAAPI.Results manquant")
        if isinstance(results, list) and results:
            results = results[0]
        rows_raw = results.get("Data", [])
        if not rows_raw:
            raise Exception("Data absent ou vide")
        rows = [r for r in rows_raw if r.get("SeriesCode") == "A191RL"]
        if not rows:
            raise Exception("pas de serie A191RL")
        rows.sort(key=lambda x: x.get("TimePeriod", ""))
        def fmt(r):
            p = r["TimePeriod"]; y, q = p[:4], p[4:]
            return f"T{q} {y} (ann.)", float(r["DataValue"].replace(",", ""))
        lp, lv = fmt(rows[-1])
        pp, pv = fmt(rows[-2]) if len(rows) >= 2 else (lp, lv)
        np_, nv = fmt(rows[-5]) if len(rows) >= 5 else fmt(rows[0])
        return {"val": f"{lv:+.1f}%", "period": lp, "prev": f"{pv:+.1f}%", "prev_period": pp,
                "n1": f"{nv:+.1f}%", "n1_period": np_, "source": "BEA (apps.bea.gov)"}
    except Exception as e:
        print(f"  BEA echoue: {e}")
        return {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D",
                "n1": "N/D", "n1_period": "N/D", "source": "BEA (web_search en repli)"}

def fetch_gdp_eurostat(geo="EA20"):
    try:
        url = (f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
               f"namq_10_gdp?format=JSON&lang=fr&freq=Q&unit=PCH_PRE&na_item=B1GQ&s_adj=SCA&geo={geo}")
        data = get_json(url)
        if not data or "value" not in data: raise Exception("pas de donnees")
        vals=data["value"]; times=list(data["dimension"]["time"]["category"]["label"].values())
        entries=[(times[int(k)],float(v)) for k,v in vals.items() if v is not None and int(k)<len(times)]
        if len(entries)<2: raise Exception("pas assez")
        entries.sort(key=lambda x: x[0])
        return {"val":f"{entries[-1][1]:+.1f}%","period":entries[-1][0],
                "prev":f"{entries[-2][1]:+.1f}%","prev_period":entries[-2][0],
                "n1":f"{entries[-5][1]:+.1f}%" if len(entries)>=5 else "N/D",
                "n1_period":entries[-5][0] if len(entries)>=5 else "N/D","source":"Eurostat"}
    except Exception as e:
        fallbacks={"FR":{"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                         "n1":"N/D","n1_period":"N/D","source":"INSEE (indisponible)"},
                   "EA20":{"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                           "n1":"N/D","n1_period":"N/D","source":"Eurostat (indisponible)"}}
        return fallbacks.get(geo,{"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                                   "n1":"N/D","n1_period":"N/D","source":"Eurostat (erreur)"})

def fetch_cpi_usa():
    try:
        today=datetime.date.today()
        payload=json.dumps({"seriesid":["CUUR0000SA0"],"startyear":str(today.year-2),"endyear":str(today.year)})
        r=requests.post("https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0",
                        data=payload,headers={"Content-type":"application/json"},timeout=30)
        series=r.json()["Results"]["series"][0]["data"]
        series.sort(key=lambda x:(x["year"],x["period"]))
        def yoy(i): return (float(series[i]["value"])-float(series[i-12]["value"]))/float(series[i-12]["value"])*100
        return {"val":f"{yoy(-1):.1f}%","period":f"{series[-1]['year']}-{series[-1]['period'].replace('M','')}",
                "prev":f"{yoy(-2):.1f}%","prev_period":f"{series[-2]['year']}-{series[-2]['period'].replace('M','')}",
                "n1":f"{yoy(-13):.1f}%" if len(series)>=13 else "N/D",
                "n1_period":f"{series[-13]['year']}-{series[-13]['period'].replace('M','')}" if len(series)>=13 else "N/D",
                "source":"BLS API (api.bls.gov)"}
    except Exception as e:
        print(f"  BLS CPI echoue: {e}")
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"BLS (indisponible)"}

def fetch_cpi_eurostat(geo="EA"):
    try:
        url=(f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
             f"prc_hicp_manr?format=JSON&lang=fr&freq=M&unit=RCH_A&coicop=CP00&geo={geo}")
        data=get_json(url)
        if not data or "value" not in data: raise Exception("pas de donnees")
        vals=data["value"]; times=list(data["dimension"]["time"]["category"]["label"].values())
        entries=[(times[int(k)],float(v)) for k,v in vals.items() if v is not None and int(k)<len(times)]
        if len(entries)<2: raise Exception("pas assez")
        entries.sort(key=lambda x: x[0])
        return {"val":f"{entries[-1][1]:.1f}%","period":entries[-1][0],
                "prev":f"{entries[-2][1]:.1f}%","prev_period":entries[-2][0],
                "n1":f"{entries[-13][1]:.1f}%" if len(entries)>=13 else "N/D",
                "n1_period":entries[-13][0] if len(entries)>=13 else "N/D","source":"Eurostat HICP"}
    except:
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"Eurostat (indisponible)"}

def fetch_ecb_rate():
    # Tentative 1 : FRED ECBDFR (Deposit Facility Rate, mis a jour quotidiennement)
    try:
        rows = fetch_fred_series("ECBDFR")
        if not rows:
            raise Exception("FRED ECBDFR vide")
        last_d, last_v = rows[-1]
        prev_d, prev_v = rows[-2] if len(rows) >= 2 else rows[-1]
        # Pour la "precedente DIFFERENTE", on cherche le dernier changement
        prev_change_d, prev_change_v = last_d, last_v
        for d, v in reversed(rows[:-1]):
            if v != last_v:
                prev_change_d, prev_change_v = d, v
                break
        return {"val": f"{last_v:.2f}%", "detail": "Taux de depot BCE (DFR)",
                "prev": f"{prev_change_v:.2f}%", "prev_period": prev_change_d[:7],
                "source": "FRED (ECBDFR)"}
    except Exception as e1:
        print(f"  FRED ECBDFR echoue: {e1}")
    # Tentative 2 : ECB SDW (CSV avec header)
    try:
        url = ("https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.DFR.LEV"
               "?format=csvdata&startPeriod=2024-01-01&detail=dataonly")
        r = get(url)
        if r is None: raise Exception("timeout")
        raw_lines = [l for l in r.text.strip().split("\n") if l.strip()]
        if not raw_lines: raise Exception("CSV vide")
        header = [h.strip() for h in raw_lines[0].split(",")]
        try:
            date_idx = header.index("TIME_PERIOD")
            val_idx = header.index("OBS_VALUE")
        except ValueError:
            date_idx, val_idx = 0, -1
        rows = []
        for line in raw_lines[1:]:
            cells = line.split(",")
            if len(cells) <= max(date_idx, val_idx if val_idx >= 0 else 0):
                continue
            d = cells[date_idx].strip()
            v = cells[val_idx].strip()
            if v in ("", "."): continue
            try:
                rows.append((d, float(v)))
            except ValueError:
                continue
        if not rows: raise Exception("pas de donnees")
        rows.sort(key=lambda x: x[0])
        last_d, last_v = rows[-1]
        prev_d, prev_v = rows[-2] if len(rows) >= 2 else rows[-1]
        return {"val": f"{last_v:.2f}%", "detail": "Taux de depot BCE",
                "prev": f"{prev_v:.2f}%", "prev_period": prev_d[:7], "source": "ECB SDW"}
    except Exception as e2:
        print(f"  ECB SDW echoue: {e2}")
    return {"val": "N/D", "detail": "Taux de depot BCE", "prev": "N/D",
            "prev_period": "N/D", "source": "BCE (web_search en repli)"}

def fetch_fed_rate():
    # Tentative 1 : FRED DFEDTARU (Upper Target Rate, le plus stable)
    try:
        rows = fetch_fred_series("DFEDTARU")
        if not rows:
            raise Exception("FRED DFEDTARU vide")
        last_d, last_v = rows[-1]
        prev_d, prev_v = rows[-22] if len(rows) >= 22 else (rows[-2] if len(rows) >= 2 else rows[-1])
        n1_d, n1_v = rows[-252] if len(rows) >= 252 else rows[0]
        return {"val": f"{last_v:.2f}%", "period": last_d[:7],
                "prev": f"{prev_v:.2f}%", "prev_period": prev_d[:7],
                "n1": f"{n1_v:.2f}%", "n1_period": n1_d[:7],
                "source": "FRED (DFEDTARU - Upper Target Rate)"}
    except Exception as e1:
        print(f"  FRED DFEDTARU echoue: {e1}")
    # Tentative 2 : FRED DFF (Effective Federal Funds Rate, autre serie fiable)
    try:
        rows = fetch_fred_series("DFF")
        if not rows:
            raise Exception("FRED DFF vide")
        last_d, last_v = rows[-1]
        prev_d, prev_v = rows[-22] if len(rows) >= 22 else (rows[-2] if len(rows) >= 2 else rows[-1])
        n1_d, n1_v = rows[-252] if len(rows) >= 252 else rows[0]
        return {"val": f"{last_v:.2f}%", "period": last_d[:7],
                "prev": f"{prev_v:.2f}%", "prev_period": prev_d[:7],
                "n1": f"{n1_v:.2f}%", "n1_period": n1_d[:7],
                "source": "FRED (DFF - Effective Federal Funds Rate)"}
    except Exception as e2:
        print(f"  FRED DFF echoue: {e2}")
    return {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D",
            "n1": "N/D", "n1_period": "N/D", "source": "Fed (web_search en repli)"}

def fetch_euribor():
    # Tentative 1 : ECB SDW (mensuel, format CSV)
    try:
        url = ("https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.RT0.MM.EURIBOR3MD_.HSTA"
               "?format=csvdata&startPeriod=2024-01-01&detail=dataonly")
        r = get(url)
        if r is None: raise Exception("timeout")
        raw_lines = [l for l in r.text.strip().split("\n") if l.strip()]
        if not raw_lines: raise Exception("CSV vide")
        header = [h.strip() for h in raw_lines[0].split(",")]
        try:
            date_idx = header.index("TIME_PERIOD")
            val_idx = header.index("OBS_VALUE")
        except ValueError:
            date_idx, val_idx = 0, -1
        rows = []
        for line in raw_lines[1:]:
            cells = line.split(",")
            if len(cells) <= max(date_idx, val_idx if val_idx >= 0 else 0):
                continue
            d = cells[date_idx].strip()
            v = cells[val_idx].strip()
            if v in ("", "."): continue
            try:
                rows.append((d, float(v)))
            except ValueError:
                continue
        if not rows: raise Exception("pas de donnees")
        rows.sort(key=lambda x: x[0])
        last_d, last_v = rows[-1]
        prev_d, prev_v = rows[-2] if len(rows) >= 2 else rows[-1]
        n1_d, n1_v = rows[-12] if len(rows) >= 12 else rows[0]
        return {"val": f"{last_v:.3f}%", "date": last_d,
                "prev": f"{prev_v:.3f}%", "prev_date": prev_d,
                "n1": f"{n1_v:.3f}%", "n1_date": n1_d, "source": "ECB SDW (Euribor 3M)"}
    except Exception as e1:
        print(f"  ECB SDW Euribor echoue: {e1}")
    # Tentative 2 : FRED IR3TIB01EZM156N (interbancaire 3 mois zone euro, proxy Euribor)
    try:
        rows = fetch_fred_series("IR3TIB01EZM156N")
        if not rows:
            raise Exception("FRED IR3TIB01EZM156N vide")
        last_d, last_v = rows[-1]
        prev_d, prev_v = rows[-2] if len(rows) >= 2 else rows[-1]
        n1_d, n1_v = rows[-13] if len(rows) >= 13 else rows[0]
        return {"val": f"{last_v:.3f}%", "date": last_d,
                "prev": f"{prev_v:.3f}%", "prev_date": prev_d,
                "n1": f"{n1_v:.3f}%", "n1_date": n1_d,
                "source": "FRED (IR3TIB01EZM156N - proxy OECD)"}
    except Exception as e2:
        print(f"  FRED Euribor proxy echoue: {e2}")
    return {"val": "N/D", "date": "N/D", "prev": "N/D", "prev_date": "N/D",
            "n1": "N/D", "n1_date": "N/D", "source": "Euribor (web_search en repli)"}

def fetch_vix():
    try:
        data=get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=2mo")
        if not data: raise Exception("pas de donnees")
        result=data["chart"]["result"][0]
        closes=result["indicators"]["quote"][0]["close"]; times=result["timestamp"]
        valid=[(t,c) for t,c in zip(times,closes) if c is not None]
        if len(valid)<2: raise Exception("pas assez")
        data2=get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=14mo")
        n1_v=[c for c in data2["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        n1_val=n1_v[-22] if len(n1_v)>=22 else n1_v[0]
        import datetime as dt
        return {"val":f"{valid[-1][1]:.2f}","date":dt.datetime.fromtimestamp(valid[-1][0]).strftime("%Y-%m-%d"),
                "prev":f"{valid[-2][1]:.2f}","prev_date":dt.datetime.fromtimestamp(valid[-2][0]).strftime("%Y-%m-%d"),
                "n1":f"{n1_val:.2f}","n1_date":"N/D","source":"CBOE via Yahoo Finance"}
    except Exception as e:
        print(f"  VIX echoue: {e}")
        return {"val":"N/D","date":"N/D","prev":"N/D","prev_date":"N/D","n1":"N/D","n1_date":"N/D","source":"CBOE (indisponible)"}

def fetch_nfp():
    try:
        today=datetime.date.today()
        payload=json.dumps({"seriesid":["CES0000000001"],"startyear":str(today.year-2),"endyear":str(today.year)})
        r=requests.post("https://api.bls.gov/publicAPI/v1/timeseries/data/CES0000000001",
                        data=payload,headers={"Content-type":"application/json"},timeout=30)
        series=r.json()["Results"]["series"][0]["data"]
        series.sort(key=lambda x:(x["year"],x["period"]))
        def delta(i): return (float(series[i]["value"])-float(series[i-1]["value"]))*1000
        def period(i): return f"{series[i]['year']}-{series[i]['period'].replace('M','')}"
        return {"val":f"{delta(-1):+,.0f}","period":period(-1),
                "prev":f"{delta(-2):+,.0f}","prev_period":period(-2),
                "n1":f"{delta(-13):+,.0f}" if len(series)>=13 else "N/D",
                "n1_period":period(-13) if len(series)>=13 else "N/D","source":"BLS API (api.bls.gov)"}
    except Exception as e:
        print(f"  BLS NFP echoue: {e}")
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"BLS (indisponible)"}

def fetch_unemployment_usa():
    try:
        today=datetime.date.today()
        payload=json.dumps({"seriesid":["LNS14000000"],"startyear":str(today.year-1),"endyear":str(today.year)})
        r=requests.post("https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000",
                        data=payload,headers={"Content-type":"application/json"},timeout=30)
        series=r.json()["Results"]["series"][0]["data"]
        series.sort(key=lambda x:(x["year"],x["period"]))
        last=series[-1]
        return {"val":f"{float(last['value']):.1f}%","period":f"{last['year']}-{last['period'].replace('M','')}"}
    except: return {"val":"N/D","period":"N/D"}

def fetch_fear_greed():
    try:
        r=get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
        if r is None: raise Exception("timeout")
        fg=r.json()["fear_and_greed"]
        return {"val":str(int(fg["score"])),"label":fg["rating"].replace("_"," ").title(),
                "prev":str(int(fg["previous_close"])),"n1":str(int(fg["previous_1_year"])),"source":"CNN Business"}
    except Exception as e:
        return {"val":"N/D","label":"N/D","prev":"N/D","n1":"N/D","source":f"CNN (erreur: {e})"}

def fetch_oat_bund_spread():
    # Tentative 1 : FRED OECD series (mensuel, fiable)
    try:
        fr_rows = fetch_fred_series("IRLTLT01FRM156N")  # France 10 ans
        de_rows = fetch_fred_series("IRLTLT01DEM156N")  # Germany 10 ans
        if not fr_rows or not de_rows:
            raise Exception("FRED OECD vide")
        fr_last_d, fr = fr_rows[-1]
        de_last_d, de = de_rows[-1]
        fr_prev = fr_rows[-2][1] if len(fr_rows) >= 2 else fr
        de_prev = de_rows[-2][1] if len(de_rows) >= 2 else de
        return {"spread": f"{(fr - de) * 100:.0f}",
                "spread_prev": f"{(fr_prev - de_prev) * 100:.0f}",
                "oat": f"{fr:.2f}%", "bund": f"{de:.2f}%",
                "source": f"FRED OECD (mensuel, {fr_last_d[:7]})"}
    except Exception as e1:
        print(f"  FRED OECD spread echoue: {e1}")
    # Tentative 2 : Yahoo Finance (tickers volatiles, peuvent disparaitre)
    try:
        def get_yield(ticker):
            data = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2mo")
            if not data: return None, None
            try:
                closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            except (KeyError, IndexError, TypeError):
                return None, None
            valid = [c for c in closes if c is not None]
            return (valid[-1], valid[-2]) if len(valid) >= 2 else (None, None)
        fr, fr_p = get_yield("FR10YT=RR")
        de, de_p = get_yield("DE10YT=RR")
        if fr and de:
            return {"spread": f"{(fr - de) * 100:.0f}",
                    "spread_prev": f"{(fr_p - de_p) * 100:.0f}" if fr_p and de_p else "N/D",
                    "oat": f"{fr:.2f}%", "bund": f"{de:.2f}%",
                    "source": "Yahoo Finance (taux 10 ans)"}
        raise Exception("tickers Yahoo non disponibles")
    except Exception as e2:
        print(f"  Yahoo spread echoue: {e2}")
    return {"spread": "N/D", "spread_prev": "N/D", "oat": "N/D", "bund": "N/D",
            "source": "OAT/Bund (web_search en repli)"}

def fetch_us_yield_curve():
    """Spread 2ans/10ans US — signal inversion courbe"""
    try:
        def get_yield(ticker):
            data=get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d")
            if not data: return None
            closes=data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            valid=[c for c in closes if c is not None]
            return valid[-1] if valid else None
        y2 = get_yield("%5EIRX")   # 13-week proxy pour 2ans
        y10= get_yield("%5ETNX")   # 10 ans
        # Meilleur proxy 2 ans
        y2_real = get_yield("^FVX")  # 5 ans comme proxy
        if y10:
            us2  = get_yield("%5EIRX") or 0
            spread = round(y10 - us2, 2)
            signal = "Inversion" if spread < 0 else ("Aplatissement" if spread < 0.5 else "Normal")
            sig_c  = "rouge" if spread < 0 else ("orange" if spread < 0.5 else "vert")
            return {"us_2y": f"{us2:.2f}%","us_10y":f"{y10:.2f}%",
                    "spread":f"{spread:+.2f}","spread_prev":"N/D",
                    "signal":signal,"source":"Yahoo Finance (^IRX / ^TNX)"}
        raise Exception("yields indisponibles")
    except Exception as e:
        print(f"  Courbe taux US echouee: {e}")
        return {"us_2y":"N/D","us_10y":"N/D","spread":"N/D","spread_prev":"N/D",
                "signal":"N/D","source":"Yahoo Finance (indisponible)"}

def fetch_credit_spreads():
    """Spreads IG/HY via FRED. Les spreads sont en % chez FRED (OAS), on garde tel quel."""
    try:
        ig_rows = fetch_fred_series("BAMLC0A0CM")    # IG OAS spread
        hy_rows = fetch_fred_series("BAMLH0A0HYM2")  # HY OAS spread
        if not ig_rows or not hy_rows:
            raise Exception("FRED IG/HY vide")
        ig_v = ig_rows[-1][1]
        ig_p = ig_rows[-2][1] if len(ig_rows) >= 2 else ig_v
        ig_n = ig_rows[-22][1] if len(ig_rows) >= 22 else ig_rows[0][1]
        hy_v = hy_rows[-1][1]
        hy_p = hy_rows[-2][1] if len(hy_rows) >= 2 else hy_v
        hy_n = hy_rows[-22][1] if len(hy_rows) >= 22 else hy_rows[0][1]
        return {"ig_spread": f"{ig_v:.2f}%",
                "ig_spread_prev": f"{ig_p:.2f}%",
                "ig_spread_n1": f"{ig_n:.2f}%",
                "hy_spread": f"{hy_v:.2f}%",
                "hy_spread_prev": f"{hy_p:.2f}%",
                "hy_spread_n1": f"{hy_n:.2f}%",
                "source": "FRED (BAMLC0A0CM / BAMLH0A0HYM2)"}
    except Exception as e:
        print(f"  Credit spreads echoues: {e}")
        return {"ig_spread": "N/D", "ig_spread_prev": "N/D", "ig_spread_n1": "N/D",
                "hy_spread": "N/D", "hy_spread_prev": "N/D", "hy_spread_n1": "N/D",
                "source": "FRED (web_search en repli)"}

def fetch_commodity(ticker):
    try:
        data=get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=14mo")
        if not data or "chart" not in data: return None
        result=data["chart"].get("result")
        if not result: return None
        closes=result[0]["indicators"]["quote"][0]["close"]
        valid=[c for c in closes if c is not None]
        if len(valid)<22: return None
        return {"val":valid[-1],"prev_m":valid[-22],"n1":valid[-252] if len(valid)>=252 else valid[0]}
    except: return None

def fetch_forex(ticker):
    return fetch_commodity(ticker)

def fetch_index(ticker):
    try:
        data=get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=14mo")
        if not data or "chart" not in data: return None
        result=data["chart"].get("result")
        if not result: return None
        closes=result[0]["indicators"]["quote"][0]["close"]
        valid=[c for c in closes if c is not None]
        if len(valid)<22: return None
        return {"val":valid[-1],"prev_m":valid[-22],"prev_y":valid[-252] if len(valid)>=252 else valid[0]}
    except: return None

def fetch_eurusd():
    try:
        data=get_json("https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=5d")
        if not data: return 1.088
        closes=data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        valid=[c for c in closes if c is not None]
        return valid[-1] if valid else 1.088
    except: return 1.088

def fetch_worldbank(indicator, country_code):
    try:
        url = (f"https://api.worldbank.org/v2/country/{country_code}/"
               f"indicator/{indicator}?format=json&mrv=4&per_page=4")
        data = get_json(url)
        # data peut etre {} (echec), [{...meta}, None] (pas de donnees pour ce code),
        # ou [{...meta}, [entrees]] (cas normal). On verifie tout.
        if not data or not isinstance(data, list) or len(data) < 2:
            raise Exception("pas de donnees")
        entries_raw = data[1]
        if not entries_raw or not isinstance(entries_raw, list):
            raise Exception(f"liste vide pour {country_code}")
        entries = [(e["date"], e["value"]) for e in entries_raw
                   if isinstance(e, dict) and e.get("value") is not None]
        if len(entries) < 2:
            raise Exception("pas assez de points")
        entries.sort(key=lambda x: x[0], reverse=True)
        return {"val": f"{entries[0][1]:+.1f}%", "period": entries[0][0],
                "prev": f"{entries[1][1]:+.1f}%", "prev_period": entries[1][0],
                "n1": f"{entries[2][1]:+.1f}%" if len(entries) >= 3 else "N/D",
                "n1_period": entries[2][0] if len(entries) >= 3 else "N/D"}
    except Exception as e:
        print(f"  Banque Mondiale {country_code} echoue: {e}")
        return None

def fetch_emerging_zones():
    zones = {}
    # CORRECTION : codes WB valides
    # v6.5.6 : Bresil (BRA) et Inde (IND) au lieu des agregats regionaux LCN/EAS
    # Les codes pays Banque Mondiale ont des donnees plus completes et fraiches
    # que les agregats regionaux (qui renvoyaient souvent des listes vides).
    print("    Bresil (BRA)...")
    gdp_bra = fetch_worldbank("NY.GDP.MKTP.KD.ZG", "BRA")
    cpi_bra = fetch_worldbank("FP.CPI.TOTL.ZG", "BRA")
    zones["bresil"] = {
        "gdp": {**(gdp_bra or {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D", "n1": "N/D", "n1_period": "N/D"}),
                "source": "Banque Mondiale (BRA)" if gdp_bra else "IBGE (web_search en repli)"},
        "cpi": {**(cpi_bra or {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D", "n1": "N/D", "n1_period": "N/D"}),
                "source": "Banque Mondiale (BRA)" if cpi_bra else "IBGE (web_search en repli)"},
    }
    print("    Inde (IND)...")
    gdp_ind = fetch_worldbank("NY.GDP.MKTP.KD.ZG", "IND")
    cpi_ind = fetch_worldbank("FP.CPI.TOTL.ZG", "IND")
    zones["inde"] = {
        "gdp": {**(gdp_ind or {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D", "n1": "N/D", "n1_period": "N/D"}),
                "source": "Banque Mondiale (IND)" if gdp_ind else "MOSPI (web_search en repli)"},
        "cpi": {**(cpi_ind or {"val": "N/D", "period": "N/D", "prev": "N/D", "prev_period": "N/D", "n1": "N/D", "n1_period": "N/D"}),
                "source": "Banque Mondiale (IND)" if cpi_ind else "MOSPI (web_search en repli)"},
    }
    return zones

def collect_all():
    print("Collecte des donnees...")
    today=datetime.date.today()
    mois_fr=["janvier","fevrier","mars","avril","mai","juin",
             "juillet","aout","septembre","octobre","novembre","decembre"]
    date_str=f"{mois_fr[today.month-1].capitalize()} {today.year}"
    data={"date":date_str,"collected_at":str(today)}

    for name,fn in [
        ("gdp_usa",fetch_gdp_usa),("gdp_ez",lambda:fetch_gdp_eurostat("EA20")),
        ("gdp_fr",lambda:fetch_gdp_eurostat("FR")),("cpi_usa",fetch_cpi_usa),
        ("cpi_ez",lambda:fetch_cpi_eurostat("EA")),("cpi_fr",lambda:fetch_cpi_eurostat("FR")),
        ("ecb_rate",fetch_ecb_rate),("fed_rate",fetch_fed_rate),("euribor",fetch_euribor),
        ("nfp",fetch_nfp),("unemployment_usa",fetch_unemployment_usa),
        ("vix",fetch_vix),("spread",fetch_oat_bund_spread),("fg",fetch_fear_greed)]:
        print(f"  {name}..."); data[name]=fn()

    # Nouveaux indicateurs
    print("  courbe_us..."); data["spread_us_curve"] = fetch_us_yield_curve()
    print("  credit_spreads..."); data["credit_spreads"] = fetch_credit_spreads()
    data["eurusd"]=fetch_eurusd()

    # Données Chine/PMI/PE/SCPI/Immo → N/D, remplies par Claude web_search
    data["gdp_chine"]    ={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"NBS (web_search)"}
    data["gdp_emergents"]={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"FMI WEO (web_search)"}
    data["cpi_chine"]    ={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"NBS (web_search)"}
    data["pboc"]         ={"val":"N/D","prev":"N/D","detail":"LPR 1 an","source":"PBoC (web_search)"}
    # Nouvelles zones v6.5.6 : Bresil + Inde (donnees nationales mensuelles/trimestrielles)
    # Nouvelles zones v6.5.6 : Bresil + Inde (donnees nationales fiables et mensuelles)
    data["gdp_bresil"] ={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"IBGE (web_search)"}
    data["cpi_bresil"] ={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"IBGE (web_search)"}
    data["gdp_inde"]   ={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"MOSPI (web_search)"}
    data["cpi_inde"]   ={"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D","n1":"N/D","n1_period":"N/D","source":"MOSPI (web_search)"}
    # Taux directeurs emergents : Bresil (Selic) et Inde (RBI Repo)
    data["bcb_selic"] ={"val":"N/D","prev":"N/D","detail":"Taux Selic","source":"Banco Central do Brasil (web_search)"}
    data["rbi_repo"]  ={"val":"N/D","prev":"N/D","detail":"Repo Rate","source":"Reserve Bank of India (web_search)"}
    data["pmi"]={
        "france":       {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global / HCOB PMI"},
        "usa":          {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global PMI"},
        "ez":           {"val":"N/D","period":"N/D","prev":"N/D","source":"HCOB / S&P Global PMI"},
        "chine":        {"val":"N/D","period":"N/D","prev":"N/D","source":"Caixin / S&P Global PMI"},
        "bresil":       {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global PMI Bresil"},
        "inde":         {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global PMI Inde"},
    }
    data["immobilier_taux"]={
        "taux_20ans":"N/D","taux_20ans_prev":"N/D","taux_20ans_n1":"N/D",
        "taux_20ans_commentaire":"Source : CAFPI (web_search)",
        "bureaux_val":"N/D","bureaux_prev":"N/D","bureaux_n1":"N/D",
        "bureaux_commentaire":"Source : CBRE/JLL (web_search)",
        "commerces_val":"N/D","commerces_prev":"N/D","commerces_n1":"N/D",
        "commerces_commentaire":"Source : CBRE/JLL (web_search)",
    }
    data["private_equity"]={
        "argos":("N/D","N/D","N/D","N/D","N/D"),
        "dp":("N/D","",""),"rdt":("N/D","",""),
        "levees":("N/D","",""),"invest":("N/D","",""),
        "cessions":("N/D","",""),"nb_ent":("N/D","",""),
    }
    # SCPI initialisée à N/D, remplie par Claude web_search
    data["scpi"]={
        "marche":{"td_moyen":"N/D","td_moyen_prev":"N/D","td_moyen_n1":"N/D",
                  "collecte_nette":"N/D","collecte_prev":"N/D","collecte_periode":"N/D",
                  "decote_secondaire":"N/D","decote_prev":"N/D","tof_moyen":"N/D",
                  "source":"ASPIM / MeilleuresSCPI (web_search)"},
        "par_secteur":[],"scpi_top10":[],
        "analyse":"N/D","points_vigilance":[],"opportunites":[],
    }

    print("  Matieres premieres...")
    data["commodities"]={}
    for name,tickers in [("Or",["GC=F"]),("Argent",["SI=F"]),("Cuivre",["HG=F"]),
                          ("Gaz naturel",["NG=F"]),("Brent",["BZ=F","CL=F"])]:
        c=None
        for ticker in tickers:
            c=fetch_commodity(ticker)
            if c: print(f"    {name} OK ({ticker})"); break
        if c: data["commodities"][name]=c
        else: print(f"    {name} N/D")

    print("  Taux de change...")
    data["forex"]={}
    for name,ticker in [("EUR/USD","EURUSD=X"),("EUR/GBP","EURGBP=X"),
                         ("EUR/JPY","EURJPY=X"),("EUR/CHF","EURCHF=X"),("EUR/CNY","EURCNY=X")]:
        f=fetch_forex(ticker)
        if f: data["forex"][name]=f; print(f"    {name} OK")

    print("  Indices boursiers...")
    data["indices"]={}
    for name,ticker in [("CAC 40","^FCHI"),("Euro Stoxx 50","^STOXX50E"),("S&P 500","^GSPC"),
                         ("Nasdaq","^IXIC"),("Dow Jones","^DJI"),("FTSE 100","^FTSE"),
                         ("Nikkei 225","^N225"),("Shanghai","000001.SS"),("MSCI EM","EEM")]:
        idx=fetch_index(ticker)
        if idx: data["indices"][name]=idx; print(f"    {name} OK")

    print("  Zones emergentes...")
    ez = fetch_emerging_zones()
    data["emerging_zones"] = ez
    # v6.5.6 : cabler les resultats Banque Mondiale BRA/IND dans les cles utilisees par le PDF.
    # Si la Banque Mondiale a renvoye une vraie valeur, on la prend ; sinon Claude web_search
    # remplira via emerging_zones en Pass 1 (cascade IBGE/MOSPI/OCDE).
    for zkey, dprefix, src_inst in [("bresil", "bresil", "IBGE"), ("inde", "inde", "MOSPI")]:
        zgdp = ez.get(zkey, {}).get("gdp", {})
        zcpi = ez.get(zkey, {}).get("cpi", {})
        if zgdp.get("val", "N/D") not in ("N/D", "", None):
            data[f"gdp_{dprefix}"].update(zgdp)
        if zcpi.get("val", "N/D") not in ("N/D", "", None):
            data[f"cpi_{dprefix}"].update(zcpi)

    data["immo_prix"]={}  # Rempli par Claude web_search

    print("Collecte terminee.")
    return data

if __name__=="__main__":
    print(json.dumps(collect_all(),indent=2,ensure_ascii=False,default=str))
