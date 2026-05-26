"""
Collecte automatique des données économiques et financières.
Sources : BEA, BLS, Eurostat, ECB, Fed, Yahoo Finance, FRED, Banque Mondiale
Toutes les données non disponibles ici sont collectées par Claude web_search.
"""
import requests
import datetime
import json

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HEXADashboard/1.0)"}

def get(url, timeout=30):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  Tentative {attempt+1}/2 echouee: {e}")
            if attempt == 1: return None

def get_json(url, **kw):
    r = get(url, **kw)
    if r is None: return {}
    try: return r.json()
    except: return {}

def fetch_gdp_usa():
    try:
        url = ("https://apps.bea.gov/api/data?UserID=GUEST"
               "&method=GetData&DataSetName=NIPA"
               "&TableName=T10101&Frequency=Q&Year=X&ResultFormat=JSON")
        data = get_json(url)
        rows = [r for r in data["BEAAPI"]["Results"]["Data"] if r.get("SeriesCode")=="A191RL"]
        if not rows: raise Exception("pas de donnees")
        rows.sort(key=lambda x: x.get("TimePeriod",""))
        def fmt(r):
            p=r["TimePeriod"]; y,q=p[:4],p[4:]
            return f"T{q} {y} (ann.)", float(r["DataValue"].replace(",",""))
        lp,lv=fmt(rows[-1]); pp,pv=fmt(rows[-2])
        np_,nv=fmt(rows[-5] if len(rows)>=5 else rows[0])
        return {"val":f"{lv:+.1f}%","period":lp,"prev":f"{pv:+.1f}%","prev_period":pp,
                "n1":f"{nv:+.1f}%","n1_period":np_,"source":"BEA (apps.bea.gov)"}
    except Exception as e:
        print(f"  BEA echoue: {e}")
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"BEA (indisponible)"}

def fetch_gdp_eurostat(geo="EA20"):
    try:
        url = (f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
               f"namq_10_gdp?format=JSON&lang=fr&freq=Q&unit=PCH_PRE"
               f"&na_item=B1GQ&s_adj=SCA&geo={geo}")
        data = get_json(url)
        if not data or "value" not in data: raise Exception("pas de donnees")
        vals  = data["value"]
        times = list(data["dimension"]["time"]["category"]["label"].values())
        entries = [(times[int(k)], float(v))
                   for k,v in vals.items()
                   if v is not None and int(k) < len(times)]
        if len(entries) < 2: raise Exception("pas assez")
        entries.sort(key=lambda x: x[0])
        return {"val":f"{entries[-1][1]:+.1f}%","period":entries[-1][0],
                "prev":f"{entries[-2][1]:+.1f}%","prev_period":entries[-2][0],
                "n1":f"{entries[-5][1]:+.1f}%" if len(entries)>=5 else "N/D",
                "n1_period":entries[-5][0] if len(entries)>=5 else "N/D",
                "source":"Eurostat"}
    except Exception as e:
        fallbacks = {
            "FR":   {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                     "n1":"N/D","n1_period":"N/D","source":"INSEE (indisponible)"},
            "EA20": {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                     "n1":"N/D","n1_period":"N/D","source":"Eurostat (indisponible)"}
        }
        return fallbacks.get(geo, {"val":"N/D","period":"N/D","prev":"N/D",
                "prev_period":"N/D","n1":"N/D","n1_period":"N/D",
                "source":"Eurostat (erreur)"})

def fetch_cpi_usa():
    try:
        today = datetime.date.today()
        payload = json.dumps({"seriesid":["CUUR0000SA0"],
                              "startyear":str(today.year-2),
                              "endyear":str(today.year)})
        r = requests.post(
            "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0",
            data=payload, headers={"Content-type":"application/json"}, timeout=30)
        series = r.json()["Results"]["series"][0]["data"]
        series.sort(key=lambda x: (x["year"], x["period"]))
        def yoy(i):
            return (float(series[i]["value"]) - float(series[i-12]["value"])) \
                   / float(series[i-12]["value"]) * 100
        return {
            "val":  f"{yoy(-1):.1f}%",
            "period": f"{series[-1]['year']}-{series[-1]['period'].replace('M','')}",
            "prev": f"{yoy(-2):.1f}%",
            "prev_period": f"{series[-2]['year']}-{series[-2]['period'].replace('M','')}",
            "n1":   f"{yoy(-13):.1f}%" if len(series)>=13 else "N/D",
            "n1_period": f"{series[-13]['year']}-{series[-13]['period'].replace('M','')}"
                         if len(series)>=13 else "N/D",
            "source": "BLS API (api.bls.gov)"}
    except Exception as e:
        print(f"  BLS CPI echoue: {e}")
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"BLS (indisponible)"}

def fetch_cpi_eurostat(geo="EA"):
    try:
        url = (f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
               f"prc_hicp_manr?format=JSON&lang=fr&freq=M&unit=RCH_A&coicop=CP00&geo={geo}")
        data = get_json(url)
        if not data or "value" not in data: raise Exception("pas de donnees")
        vals  = data["value"]
        times = list(data["dimension"]["time"]["category"]["label"].values())
        entries = [(times[int(k)], float(v))
                   for k,v in vals.items()
                   if v is not None and int(k) < len(times)]
        if len(entries) < 2: raise Exception("pas assez")
        entries.sort(key=lambda x: x[0])
        return {"val":f"{entries[-1][1]:.1f}%","period":entries[-1][0],
                "prev":f"{entries[-2][1]:.1f}%","prev_period":entries[-2][0],
                "n1":f"{entries[-13][1]:.1f}%" if len(entries)>=13 else "N/D",
                "n1_period":entries[-13][0] if len(entries)>=13 else "N/D",
                "source":"Eurostat HICP"}
    except:
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"Eurostat (indisponible)"}

def fetch_ecb_rate():
    try:
        url = ("https://data-api.ecb.europa.eu/service/data/"
               "FM/B.U2.EUR.4F.KR.DFR.LEV"
               "?format=csvdata&startPeriod=2024-01-01&detail=dataonly")
        r = get(url)
        if r is None: raise Exception("timeout")
        lines = [l for l in r.text.strip().split("\n")
                 if l and not l.startswith("KEY") and not l.startswith("DATAFLOW")]
        valid = [l for l in lines if l.split(",")[-1].strip() not in ("",".",)]
        if not valid: raise Exception("pas de donnees")
        last, prev = valid[-1].split(","), valid[-2].split(",")
        return {"val":f"{float(last[-1]):.2f}%","detail":"Taux de depot BCE",
                "prev":f"{float(prev[-1]):.2f}%","prev_period":prev[0],
                "source":"ECB SDW"}
    except Exception as e:
        print(f"  ECB SDW echoue: {e}")
        return {"val":"N/D","detail":"Taux de depot BCE","prev":"N/D",
                "prev_period":"N/D","source":"ECB SDW (indisponible)"}

def fetch_fed_rate():
    try:
        url = "https://www.federalreserve.gov/releases/h15/current/h15.xml"
        r = get(url)
        if r is None: raise Exception("timeout")
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        obs = []
        for s in root.iter():
            if "Obs" in s.tag:
                d = s.get("TIME_PERIOD",""); v = s.get("OBS_VALUE","")
                if d and v and v != "ND":
                    try: obs.append((d, float(v)))
                    except: pass
        if len(obs) < 2: raise Exception("pas de donnees")
        obs.sort(key=lambda x: x[0])
        return {"val":f"{obs[-1][1]:.2f}%","period":obs[-1][0][:7],
                "prev":f"{obs[-2][1]:.2f}%","prev_period":obs[-2][0][:7],
                "n1":f"{obs[-13][1]:.2f}%" if len(obs)>=13 else "N/D",
                "n1_period":obs[-13][0][:7] if len(obs)>=13 else "N/D",
                "source":"Fed H.15 (federalreserve.gov)"}
    except Exception as e:
        print(f"  Fed H.15 echoue: {e}")
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"Fed (indisponible)"}

def fetch_euribor():
    try:
        url = ("https://data-api.ecb.europa.eu/service/data/"
               "FM/B.U2.EUR.RT0.MM.EURIBOR3MD_.HSTA"
               "?format=csvdata&startPeriod=2024-01-01&detail=dataonly")
        r = get(url)
        if r is None: raise Exception("timeout")
        lines = [l for l in r.text.strip().split("\n")
                 if l and not l.startswith("KEY") and not l.startswith("DATAFLOW")]
        valid = [l for l in lines if l.split(",")[-1].strip() not in ("",".",)]
        if not valid: raise Exception("pas de donnees")
        last = valid[-1].split(",")
        prev = valid[-2].split(",") if len(valid) >= 2 else last
        n1   = valid[-252].split(",") if len(valid) >= 252 else valid[0].split(",")
        return {"val":f"{float(last[-1]):.3f}%","date":last[0],
                "prev":f"{float(prev[-1]):.3f}%","prev_date":prev[0],
                "n1":f"{float(n1[-1]):.3f}%","n1_date":n1[0],
                "source":"ECB SDW (Euribor 3M)"}
    except Exception as e:
        print(f"  Euribor echoue: {e}")
        return {"val":"N/D","date":"N/D","prev":"N/D","prev_date":"N/D",
                "n1":"N/D","n1_date":"N/D","source":"ECB SDW (indisponible)"}

def fetch_vix():
    try:
        data = get_json(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "%5EVIX?interval=1d&range=2mo")
        if not data: raise Exception("pas de donnees")
        result  = data["chart"]["result"][0]
        closes  = result["indicators"]["quote"][0]["close"]
        times   = result["timestamp"]
        valid   = [(t,c) for t,c in zip(times, closes) if c is not None]
        if len(valid) < 2: raise Exception("pas assez")
        data2   = get_json(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "%5EVIX?interval=1d&range=14mo")
        n1_v    = [c for c in data2["chart"]["result"][0]
                   ["indicators"]["quote"][0]["close"] if c is not None]
        n1_val  = n1_v[-22] if len(n1_v) >= 22 else n1_v[0]
        import datetime as dt
        return {
            "val":  f"{valid[-1][1]:.2f}",
            "date": dt.datetime.fromtimestamp(valid[-1][0]).strftime("%Y-%m-%d"),
            "prev": f"{valid[-2][1]:.2f}",
            "prev_date": dt.datetime.fromtimestamp(valid[-2][0]).strftime("%Y-%m-%d"),
            "n1":   f"{n1_val:.2f}","n1_date":"N/D",
            "source":"CBOE via Yahoo Finance"}
    except Exception as e:
        print(f"  VIX echoue: {e}")
        return {"val":"N/D","date":"N/D","prev":"N/D","prev_date":"N/D",
                "n1":"N/D","n1_date":"N/D","source":"CBOE (indisponible)"}

def fetch_nfp():
    try:
        today   = datetime.date.today()
        payload = json.dumps({"seriesid":["CES0000000001"],
                              "startyear":str(today.year-2),
                              "endyear":str(today.year)})
        r = requests.post(
            "https://api.bls.gov/publicAPI/v1/timeseries/data/CES0000000001",
            data=payload, headers={"Content-type":"application/json"}, timeout=30)
        series = r.json()["Results"]["series"][0]["data"]
        series.sort(key=lambda x: (x["year"], x["period"]))
        def delta(i):
            return (float(series[i]["value"]) - float(series[i-1]["value"])) * 1000
        def period(i):
            return f"{series[i]['year']}-{series[i]['period'].replace('M','')}"
        return {"val":f"{delta(-1):+,.0f}","period":period(-1),
                "prev":f"{delta(-2):+,.0f}","prev_period":period(-2),
                "n1":f"{delta(-13):+,.0f}" if len(series)>=13 else "N/D",
                "n1_period":period(-13) if len(series)>=13 else "N/D",
                "source":"BLS API (api.bls.gov)"}
    except Exception as e:
        print(f"  BLS NFP echoue: {e}")
        return {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                "n1":"N/D","n1_period":"N/D","source":"BLS (indisponible)"}

def fetch_unemployment_usa():
    try:
        today   = datetime.date.today()
        payload = json.dumps({"seriesid":["LNS14000000"],
                              "startyear":str(today.year-1),
                              "endyear":str(today.year)})
        r = requests.post(
            "https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000",
            data=payload, headers={"Content-type":"application/json"}, timeout=30)
        series = r.json()["Results"]["series"][0]["data"]
        series.sort(key=lambda x: (x["year"], x["period"]))
        last = series[-1]
        return {"val":f"{float(last['value']):.1f}%",
                "period":f"{last['year']}-{last['period'].replace('M','')}"}
    except:
        return {"val":"N/D","period":"N/D"}

def fetch_fear_greed():
    try:
        r = get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
        if r is None: raise Exception("timeout")
        fg = r.json()["fear_and_greed"]
        return {"val":str(int(fg["score"])),
                "label":fg["rating"].replace("_"," ").title(),
                "prev":str(int(fg["previous_close"])),
                "n1":str(int(fg["previous_1_year"])),
                "source":"CNN Business"}
    except Exception as e:
        return {"val":"N/D","label":"N/D","prev":"N/D","n1":"N/D",
                "source":f"CNN (erreur: {e})"}

def fetch_oat_bund_spread():
    # Tentative 1 : Yahoo Finance
    try:
        def get_yield(ticker):
            data = get_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{ticker}?interval=1d&range=2mo")
            if not data: return None, None
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            valid  = [c for c in closes if c is not None]
            return (valid[-1], valid[-2]) if len(valid) >= 2 else (None, None)
        fr, fr_p = get_yield("FR10YT=RR")
        de, de_p = get_yield("DE10YT=RR")
        if fr and de:
            return {"spread":f"{(fr-de)*100:.0f}",
                    "spread_prev":f"{(fr_p-de_p)*100:.0f}" if fr_p and de_p else "N/D",
                    "oat":f"{fr:.2f}%","bund":f"{de:.2f}%",
                    "source":"Yahoo Finance (taux 10 ans)"}
        raise Exception("tickers non disponibles")
    except Exception as e1:
        print(f"  Yahoo spread echoue: {e1}")
    # Tentative 2 : ECB SDW
    try:
        def get_ecb(country):
            url = (f"https://data-api.ecb.europa.eu/service/data/"
                   f"IRS/M.{country}.L.L40.CI.0.EUR.N.Z"
                   f"?format=csvdata&startPeriod=2024-01-01&detail=dataonly")
            r = get(url)
            if r is None: return None, None
            lines = [l for l in r.text.strip().split("\n")
                     if l and not l.startswith("KEY") and not l.startswith("DATAFLOW")]
            valid = [l for l in lines if l.split(",")[-1].strip() not in ("",".",)]
            if not valid: return None, None
            return (float(valid[-1].split(",")[-1]),
                    float(valid[-2].split(",")[-1]) if len(valid)>=2 else None)
        fr, fr_p = get_ecb("FR")
        de, de_p = get_ecb("DE")
        if fr and de:
            return {"spread":f"{(fr-de)*100:.0f}",
                    "spread_prev":f"{(fr_p-de_p)*100:.0f}" if fr_p and de_p else "N/D",
                    "oat":f"{fr:.2f}%","bund":f"{de:.2f}%",
                    "source":"ECB SDW (taux mensuels)"}
        raise Exception("ECB SDW indisponible")
    except Exception as e2:
        print(f"  ECB SDW spread echoue: {e2}")
    # Fallback : N/D, complété par Claude web_search
    return {"spread":"N/D","spread_prev":"N/D","oat":"N/D","bund":"N/D",
            "source":"web_search"}

def fetch_us_yield_curve():
    """Spread 2ans/10ans US — signal inversion courbe"""
    try:
        def get_yield(ticker):
            data = get_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/"
                f"{ticker}?interval=1d&range=5d")
            if not data: return None
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            valid  = [c for c in closes if c is not None]
            return valid[-1] if valid else None
        y10 = get_yield("%5ETNX")
        y2  = get_yield("%5EIRX")
        if y10 and y2:
            spread = round(y10 - y2, 2)
            signal = ("Inversion" if spread < 0
                      else "Aplatissement" if spread < 0.5
                      else "Normal")
            return {"us_2y":f"{y2:.2f}%","us_10y":f"{y10:.2f}%",
                    "spread":f"{spread:+.2f}","spread_prev":"N/D",
                    "signal":signal,"source":"Yahoo Finance (^IRX / ^TNX)"}
        raise Exception("yields indisponibles")
    except Exception as e:
        print(f"  Courbe taux US echouee: {e}")
        return {"us_2y":"N/D","us_10y":"N/D","spread":"N/D","spread_prev":"N/D",
                "signal":"N/D","source":"Yahoo Finance (indisponible)"}

def fetch_credit_spreads():
    """Spreads IG/HY via FRED"""
    try:
        def get_fred(series_id):
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            r   = get(url)
            if r is None: return None, None, None
            lines = [l for l in r.text.strip().split("\n")
                     if l and not l.startswith("DATE")]
            valid = [l for l in lines if l.split(",")[1].strip() not in ("",".",)]
            if not valid: return None, None, None
            last = valid[-1].split(",")
            prev = valid[-2].split(",")
            n1   = valid[-22].split(",") if len(valid) >= 22 else valid[0].split(",")
            return float(last[1]), float(prev[1]), float(n1[1])
        ig_v, ig_p, ig_n = get_fred("BAMLC0A0CM")
        hy_v, hy_p, hy_n = get_fred("BAMLH0A0HYM2")
        if ig_v and hy_v:
            return {
                "ig_spread":      f"{ig_v:.2f}%",
                "ig_spread_prev": f"{ig_p:.2f}%" if ig_p else "N/D",
                "ig_spread_n1":   f"{ig_n:.2f}%" if ig_n else "N/D",
                "hy_spread":      f"{hy_v:.2f}%",
                "hy_spread_prev": f"{hy_p:.2f}%" if hy_p else "N/D",
                "hy_spread_n1":   f"{hy_n:.2f}%" if hy_n else "N/D",
                "source":"FRED (BAMLC0A0CM / BAMLH0A0HYM2)"}
        raise Exception("FRED indisponible")
    except Exception as e:
        print(f"  Credit spreads echoues: {e}")
        return {"ig_spread":"N/D","ig_spread_prev":"N/D","ig_spread_n1":"N/D",
                "hy_spread":"N/D","hy_spread_prev":"N/D","hy_spread_n1":"N/D",
                "source":"FRED (indisponible)"}

def fetch_commodity(ticker):
    try:
        data = get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{ticker}?interval=1d&range=14mo")
        if not data or "chart" not in data: return None
        result = data["chart"].get("result")
        if not result: return None
        closes = result[0]["indicators"]["quote"][0]["close"]
        valid  = [c for c in closes if c is not None]
        if len(valid) < 22: return None
        return {"val":valid[-1],"prev_m":valid[-22],
                "n1":valid[-252] if len(valid)>=252 else valid[0]}
    except: return None

def fetch_forex(ticker):
    return fetch_commodity(ticker)

def fetch_index(ticker):
    try:
        data = get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{ticker}?interval=1d&range=14mo")
        if not data or "chart" not in data: return None
        result = data["chart"].get("result")
        if not result: return None
        closes = result[0]["indicators"]["quote"][0]["close"]
        valid  = [c for c in closes if c is not None]
        if len(valid) < 22: return None
        return {"val":valid[-1],"prev_m":valid[-22],
                "prev_y":valid[-252] if len(valid)>=252 else valid[0]}
    except: return None

def fetch_eurusd():
    try:
        data = get_json(
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "EURUSD=X?interval=1d&range=5d")
        if not data: return 1.088
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        valid  = [c for c in closes if c is not None]
        return valid[-1] if valid else 1.088
    except: return 1.088

def fetch_worldbank(indicator, country_code):
    """API Banque Mondiale — avec gestion robuste des réponses vides"""
    try:
        url = (f"https://api.worldbank.org/v2/country/{country_code}/"
               f"indicator/{indicator}?format=json&mrv=4&per_page=4")
        data = get_json(url)
        # Vérifications robustes
        if not data: raise Exception("reponse vide")
        if not isinstance(data, list): raise Exception("format inattendu")
        if len(data) < 2: raise Exception("pas de metadata")
        if not data[1]: raise Exception("liste donnees vide")
        if not isinstance(data[1], list): raise Exception("donnees non-liste")
        entries = [(e["date"], e["value"])
                   for e in data[1]
                   if isinstance(e, dict) and e.get("value") is not None]
        if len(entries) < 2: raise Exception(f"pas assez ({len(entries)})")
        entries.sort(key=lambda x: x[0], reverse=True)
        return {
            "val":         f"{entries[0][1]:+.1f}%",
            "period":      entries[0][0],
            "prev":        f"{entries[1][1]:+.1f}%",
            "prev_period": entries[1][0],
            "n1":          f"{entries[2][1]:+.1f}%" if len(entries)>=3 else "N/D",
            "n1_period":   entries[2][0] if len(entries)>=3 else "N/D"
        }
    except Exception as e:
        print(f"  Banque Mondiale {country_code}/{indicator} echoue: {e}")
        return None

def fetch_emerging_zones():
    zones = {}
    print("    Amerique latine...")
    gdp_lac = fetch_worldbank("NY.GDP.MKTP.KD.ZG", "4E")
    cpi_lac = fetch_worldbank("FP.CPI.TOTL.ZG",    "4E")
    zones["am_latine"] = {
        "gdp": {**(gdp_lac or {"val":"N/D","period":"N/D","prev":"N/D",
                               "prev_period":"N/D","n1":"N/D","n1_period":"N/D"}),
                "source": "Banque Mondiale" if gdp_lac else "indisponible"},
        "cpi": {**(cpi_lac or {"val":"N/D","period":"N/D","prev":"N/D",
                               "prev_period":"N/D","n1":"N/D","n1_period":"N/D"}),
                "source": "Banque Mondiale" if cpi_lac else "indisponible"},
    }
    print("    Asie ex-Chine...")
    gdp_asie = fetch_worldbank("NY.GDP.MKTP.KD.ZG", "Z4")
    cpi_asie = fetch_worldbank("FP.CPI.TOTL.ZG",    "Z4")
    zones["asie_ex_chine"] = {
        "gdp": {**(gdp_asie or {"val":"N/D","period":"N/D","prev":"N/D",
                                "prev_period":"N/D","n1":"N/D","n1_period":"N/D"}),
                "source": "Banque Mondiale" if gdp_asie else "indisponible"},
        "cpi": {**(cpi_asie or {"val":"N/D","period":"N/D","prev":"N/D",
                                "prev_period":"N/D","n1":"N/D","n1_period":"N/D"}),
                "source": "Banque Mondiale" if cpi_asie else "indisponible"},
    }
    return zones

def collect_all():
    print("Collecte des donnees...")
    today    = datetime.date.today()
    mois_fr  = ["janvier","fevrier","mars","avril","mai","juin",
                "juillet","aout","septembre","octobre","novembre","decembre"]
    date_str = f"{mois_fr[today.month-1].capitalize()} {today.year}"
    data     = {"date": date_str, "collected_at": str(today)}

    for name, fn in [
        ("gdp_usa",          fetch_gdp_usa),
        ("gdp_ez",           lambda: fetch_gdp_eurostat("EA20")),
        ("gdp_fr",           lambda: fetch_gdp_eurostat("FR")),
        ("cpi_usa",          fetch_cpi_usa),
        ("cpi_ez",           lambda: fetch_cpi_eurostat("EA")),
        ("cpi_fr",           lambda: fetch_cpi_eurostat("FR")),
        ("ecb_rate",         fetch_ecb_rate),
        ("fed_rate",         fetch_fed_rate),
        ("euribor",          fetch_euribor),
        ("nfp",              fetch_nfp),
        ("unemployment_usa", fetch_unemployment_usa),
        ("vix",              fetch_vix),
        ("spread",           fetch_oat_bund_spread),
        ("fg",               fetch_fear_greed),
    ]:
        print(f"  {name}...")
        data[name] = fn()

    # Nouveaux indicateurs
    print("  courbe_us...")
    data["spread_us_curve"] = fetch_us_yield_curve()
    print("  credit_spreads...")
    data["credit_spreads"]  = fetch_credit_spreads()
    data["eurusd"]          = fetch_eurusd()

    # Données initialisées à N/D — remplies par Claude web_search
    data["gdp_chine"]     = {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                             "n1":"N/D","n1_period":"N/D","source":"NBS (web_search)"}
    data["gdp_emergents"] = {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                             "n1":"N/D","n1_period":"N/D","source":"FMI WEO (web_search)"}
    data["cpi_chine"]     = {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                             "n1":"N/D","n1_period":"N/D","source":"NBS (web_search)"}
    data["pboc"]          = {"val":"N/D","prev":"N/D","detail":"LPR 1 an",
                             "source":"PBoC (web_search)"}
    data["pmi"] = {
        "france": {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global / HCOB PMI"},
        "usa":    {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global PMI"},
        "ez":     {"val":"N/D","period":"N/D","prev":"N/D","source":"HCOB / S&P Global PMI"},
        "chine":  {"val":"N/D","period":"N/D","prev":"N/D","source":"Caixin / S&P Global PMI"},
    }
    data["immobilier_taux"] = {
        "taux_20ans":"N/D","taux_20ans_prev":"N/D","taux_20ans_n1":"N/D",
        "taux_20ans_commentaire":"Source : CAFPI (web_search)",
        "bureaux_val":"N/D","bureaux_prev":"N/D","bureaux_n1":"N/D",
        "bureaux_commentaire":"Source : CBRE/JLL (web_search)",
        "commerces_val":"N/D","commerces_prev":"N/D","commerces_n1":"N/D",
        "commerces_commentaire":"Source : CBRE/JLL (web_search)",
    }
    data["private_equity"] = {
        "argos":   ("N/D","N/D","N/D","N/D","N/D"),
        "dp":      ("N/D","",""), "rdt":     ("N/D","",""),
        "levees":  ("N/D","",""), "invest":  ("N/D","",""),
        "cessions":("N/D","",""), "nb_ent":  ("N/D","",""),
    }
    data["scpi"] = {
        "marche": {
            "td_moyen":"N/D","td_moyen_prev":"N/D","td_moyen_n1":"N/D",
            "collecte_nette":"N/D","collecte_prev":"N/D","collecte_periode":"N/D",
            "decote_secondaire":"N/D","decote_prev":"N/D","tof_moyen":"N/D",
            "source":"ASPIM / MeilleuresSCPI (web_search)"},
        "par_secteur":[],"scpi_phares":[],
        "analyse":"N/D","points_vigilance":[],"opportunites":[],
    }

    print("  Matieres premieres...")
    data["commodities"] = {}
    for name, tickers in [
        ("Or",          ["GC=F"]),
        ("Argent",      ["SI=F"]),
        ("Cuivre",      ["HG=F"]),
        ("Gaz naturel", ["NG=F"]),
        ("Brent",       ["BZ=F","CL=F"])]:
        c = None
        for ticker in tickers:
            c = fetch_commodity(ticker)
            if c:
                print(f"    {name} OK ({ticker})")
                break
        if c: data["commodities"][name] = c
        else: print(f"    {name} N/D")

    print("  Taux de change...")
    data["forex"] = {}
    for name, ticker in [
        ("EUR/USD","EURUSD=X"), ("EUR/GBP","EURGBP=X"),
        ("EUR/JPY","EURJPY=X"), ("EUR/CHF","EURCHF=X"),
        ("EUR/CNY","EURCNY=X")]:
        f = fetch_forex(ticker)
        if f:
            data["forex"][name] = f
            print(f"    {name} OK")

    print("  Indices boursiers...")
    data["indices"] = {}
    for name, ticker in [
        ("CAC 40","^FCHI"),       ("Euro Stoxx 50","^STOXX50E"),
        ("S&P 500","^GSPC"),      ("Nasdaq","^IXIC"),
        ("Dow Jones","^DJI"),     ("FTSE 100","^FTSE"),
        ("Nikkei 225","^N225"),   ("Shanghai","000001.SS"),
        ("MSCI EM","EEM")]:
        idx = fetch_index(ticker)
        if idx:
            data["indices"][name] = idx
            print(f"    {name} OK")

    print("  Zones emergentes (Banque Mondiale)...")
    data["emerging_zones"] = fetch_emerging_zones()

    data["immo_prix"] = {}  # Rempli par Claude web_search

    print("Collecte terminee.")
    return data

if __name__ == "__main__":
    print(json.dumps(collect_all(), indent=2, ensure_ascii=False, default=str))
