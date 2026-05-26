"""
Appel API Claude avec web_search pour collecter toutes les données dynamiques
et produire l'analyse mensuelle complète.
"""
import os
import json
import datetime
import anthropic


def build_search_prompt(mois: str, annee: int) -> str:
    return f"""Tu es un assistant de recherche financière et économique.
Nous sommes en {mois} {annee}. Utilise l'outil web_search pour rechercher
chaque donnée ci-dessous. Fais autant de recherches que nécessaire.

DONNEES A RECHERCHER :

1. PMI COMPOSITES (S&P Global / HCOB) — dernier mois {annee} :
   France, Zone Euro, États-Unis, Chine (Caixin)
   → valeur actuelle, mois, valeur mois précédent

2. CHINE — source : Reuters, AFP, Les Echos :
   - PIB dernier trimestre (croissance a/a %)
   - CPI dernier mois (inflation a/a %)
   - Taux LPR 1 an PBoC en vigueur

3. INFLATION FLASH Eurostat/INSEE :
   - CPI France avril {annee} (estimation flash INSEE)
   - CPI Zone Euro avril {annee} (estimation flash Eurostat)

4. TAUX IMMOBILIER FRANCE {mois} {annee} :
   - Taux crédit immobilier 20 ans moyen (CAFPI, Meilleurtaux)
   - Variation vs mois précédent et A-1

5. MARCHE BUREAUX ET COMMERCES :
   - Surface bureaux vacants Île-de-France (CBRE, JLL)
   - Surface commerciale disponible France

6. PRIX IMMOBILIER AU m2 — source : DVF, MeilleursAgents, notaires :
   Paris, Lyon, Tassin-la-Demi-Lune, Saint-Foy-les-Lyon,
   Maisons-Laffitte, Le Vesinet, Chatou, Saint-Germain-en-Laye

7. INDICE ARGOS MID-MARKET — dernier trimestre {annee} :
   Multiple médian EV/EBITDA actuel et précédent

8. FRANCE INVEST — dernières données {annee} :
   Levées de fonds, investissements, cessions, nb entreprises, rendement net

9. DRY POWDER PE MONDIAL — dernière estimation :
   Montant en milliards $

10. SPREAD OAT/BUND 10 ANS — aujourd'hui :
    Taux OAT 10 ans, Bund 10 ans, spread en pb

11. SPREADS CREDIT IG/HY — dernières valeurs :
    - Investment Grade (IG OAS spread en %)
    - High Yield (HY OAS spread en %)
    Si FRED indisponible, chercher dans la presse financière.

12. SPREAD COURBE US 2ans/10ans — aujourd'hui :
    Taux US 2 ans et 10 ans, spread en points de pourcentage

13. SCPI — marché France {annee} :
    - Taux de distribution moyen du marché
    - Collecte nette trimestrielle dernière période
    - Décote marché secondaire moyenne
    - Taux d'occupation financier moyen
    - Tendances par secteur (bureaux, commerce, santé, logistique, résidentiel, hôtellerie)
    - 5 SCPI de référence avec : nom, gestionnaire, secteur, TD, TOF, prix de part, variation prix
    Source : ASPIM, MeilleuresSCPI.com, France SCPI, L'AGEFI, Les Echos

Réponds UNIQUEMENT avec ce JSON (sans texte avant ou après) :
{{
  "pmi": {{
    "france": {{"val": "", "period": "", "prev": "", "source": ""}},
    "usa":    {{"val": "", "period": "", "prev": "", "source": ""}},
    "ez":     {{"val": "", "period": "", "prev": "", "source": ""}},
    "chine":  {{"val": "", "period": "", "prev": "", "source": ""}}
  }},
  "chine": {{
    "pib_val": "", "pib_period": "", "pib_prev": "", "pib_prev_period": "",
    "cpi_val": "", "cpi_period": "", "cpi_prev": "", "cpi_prev_period": "",
    "pboc_val": "", "pboc_prev": "", "pboc_detail": ""
  }},
  "cpi_flash": {{
    "france_val": "", "france_period": "", "france_prev": "", "france_source": "",
    "ez_val": "",     "ez_period": "",     "ez_prev": "",     "ez_source": ""
  }},
  "immo_taux": {{
    "taux_20ans": "", "taux_20ans_prev": "", "taux_20ans_n1": "", "taux_20ans_commentaire": "",
    "bureaux_val": "", "bureaux_prev": "", "bureaux_n1": "", "bureaux_commentaire": "",
    "commerces_val": "", "commerces_prev": "", "commerces_n1": "", "commerces_commentaire": ""
  }},
  "immo_prix": {{
    "Paris":                 {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Lyon":                  {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Tassin-la-Demi-Lune":   {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Saint-Foy-les-Lyon":    {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Maisons-Laffitte":      {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Le Vesinet":            {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Chatou":                {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}},
    "Saint-Germain-en-Laye": {{"val": 0, "var_1an": 0.0, "var_5ans": 0.0, "periode": "", "source": ""}}
  }},
  "argos": {{"val": "", "prev": "", "prev_period": "", "n1": "", "n1_period": "", "source": ""}},
  "france_invest": {{
    "levees":   {{"val": "", "var": "", "periode": ""}},
    "invest":   {{"val": "", "var": "", "periode": ""}},
    "cessions": {{"val": "", "var": "", "periode": ""}},
    "nb_ent":   {{"val": "", "var": "", "periode": ""}},
    "rdt":      {{"val": "", "var": "", "periode": ""}}
  }},
  "dry_powder": {{"val": "", "var": "", "periode": "", "source": ""}},
  "spread_oat_bund": {{"oat": "", "bund": "", "spread": "", "spread_prev": "", "source": ""}},
  "credit_spreads": {{
    "ig_spread": "", "ig_spread_prev": "", "ig_spread_n1": "",
    "hy_spread": "", "hy_spread_prev": "", "hy_spread_n1": "",
    "source": ""
  }},
  "spread_us_curve": {{
    "us_2y": "", "us_10y": "", "spread": "", "spread_prev": "", "signal": "", "source": ""
  }},
  "scpi": {{
    "marche": {{
      "td_moyen": "", "td_moyen_prev": "", "td_moyen_n1": "",
      "collecte_nette": "", "collecte_prev": "", "collecte_periode": "",
      "decote_secondaire": "", "decote_prev": "",
      "tof_moyen": "", "source": ""
    }},
    "par_secteur": [
      {{"secteur": "", "poids": "", "td": "", "tendance": "▲|▶|▼", "commentaire": ""}}
    ],
    "scpi_phares": [
      {{"nom": "", "gestionnaire": "", "secteur": "", "td": "", "tof": "",
        "prix_part": "", "var_prix": "", "note": ""}}
    ],
    "analyse": "",
    "points_vigilance": ["", "", ""],
    "opportunites": ["", "", ""]
  }}
}}"""


def build_analysis_prompt(data: dict, mois: str) -> str:
    def v(path, default="N/D"):
        try:
            keys = path.split(".")
            d = data
            for k in keys: d = d[k]
            return str(d) if d else default
        except: return default

    cac_p = sp_p = 0
    try:
        cac = data.get("indices",{}).get("CAC 40",{})
        if cac.get("prev_y"): cac_p = (cac["val"]-cac["prev_y"])/cac["prev_y"]*100
        sp  = data.get("indices",{}).get("S&P 500",{})
        if sp.get("prev_y"):  sp_p  = (sp["val"] -sp["prev_y"] )/sp["prev_y"] *100
    except: pass

    spread_curve = data.get("spread_us_curve",{})
    cs = data.get("credit_spreads",{})

    return f"""Tu es conseiller en gestion de patrimoine senior chez HEXA Patrimoine.
Analyse les données économiques de {mois} et produis une analyse professionnelle complète.

DONNEES DU MOIS :
PIB : France {v("gdp_fr.val")} | Zone Euro {v("gdp_ez.val")} | USA {v("gdp_usa.val")} | Chine {v("gdp_chine.val")} | Am. latine {v("emerging_zones.am_latine.gdp.val")} | Asie ex-CN {v("emerging_zones.asie_ex_chine.gdp.val")}
PMI : France {v("pmi.france.val")} | Zone Euro {v("pmi.ez.val")} | USA {v("pmi.usa.val")} | Chine {v("pmi.chine.val")}
EMPLOI USA : NFP {v("nfp.val")} | Chomage {v("unemployment_usa.val")}
INFLATION : France {v("cpi_fr.val")} | Zone Euro {v("cpi_ez.val")} | USA {v("cpi_usa.val")} | Chine {v("cpi_chine.val")}
TAUX : BCE {v("ecb_rate.val")} | Fed {v("fed_rate.val")} | Euribor 3M {v("euribor.val")}
STRESS : VIX {v("vix.val")} | Fear&Greed {v("fg.val")}/100 | Spread OAT/Bund {v("spread.spread")}pb | OAT {v("spread.oat")}
COURBE US : Spread 2ans/10ans {spread_curve.get("spread","N/D")} ({spread_curve.get("signal","N/D")})
CREDIT : IG spread {cs.get("ig_spread","N/D")} | HY spread {cs.get("hy_spread","N/D")}
MARCHES : CAC 40 ({cac_p:+.1f}% 1an) | S&P 500 ({sp_p:+.1f}% 1an)
MATIERES 1ERES : Or {v("commodities.Or.val")}$/oz | Brent {v("commodities.Brent.val")}$/b
PE : Multiple Argos {v("private_equity.argos")[1] if isinstance(data.get("private_equity",{}).get("argos"),tuple) else "N/D"}
SCPI : TD moyen {v("scpi.marche.td_moyen")} | Collecte {v("scpi.marche.collecte_nette")} | Decote secondaire {v("scpi.marche.decote_secondaire")}

Reponds UNIQUEMENT avec ce JSON :
{{
  "commentaire_general": "2-3 phrases contexte macro professionnel HEXA.",
  "analyse_cycle": {{
    "France":          {{"regime": "Goldilocks|Surchauffe|Obligations|Stagflation", "commentaire": "1 phrase"}},
    "Etats-Unis":      {{"regime": "...", "commentaire": "..."}},
    "Zone Euro":       {{"regime": "...", "commentaire": "..."}},
    "Chine":           {{"regime": "...", "commentaire": "..."}},
    "Amerique latine": {{"regime": "...", "commentaire": "..."}},
    "Asie ex-Chine":   {{"regime": "...", "commentaire": "..."}}
  }},
  "points_vigilance": ["risque 1", "risque 2", "risque 3"],
  "opportunites":     ["opportunite 1", "opportunite 2", "opportunite 3"],
  "allocation_recommandee": {{
    "actions": "1 phrase", "obligations": "1 phrase",
    "matieres_premieres": "1 phrase", "immobilier": "1 phrase",
    "cash_monetaire": "1 phrase", "private_equity": "1 phrase",
    "scpi": "1 phrase sur les SCPI"
  }},
  "synthese_immobilier": "2 phrases contexte immo France.",
  "synthese_pe":         "2 phrases contexte PE.",
  "synthese_scpi":       "2 phrases contexte SCPI marche.",
  "analyse_courbe_taux": "1 phrase sur l'inversion courbe US et implications.",
  "analyse_credit":      "1 phrase sur les spreads IG/HY et implications pour obligations datees."
}}"""


def extract_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("json"): p = p[4:].strip()
            if p.startswith("{"): text = p; break
    start = text.find("{"); end = text.rfind("}") + 1
    if start >= 0 and end > start: text = text[start:end]
    return json.loads(text)


def call_with_search(client, prompt: str, max_tokens: int = 5000) -> str:
    tools    = [{"type": "web_search_20250305", "name": "web_search"}]
    messages = [{"role": "user", "content": prompt}]
    for _ in range(20):
        response = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=max_tokens,
            tools=tools, messages=messages)
        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block,"text"): return block.text
            return ""
        if response.stop_reason == "tool_use":
            messages.append({"role":"assistant","content":response.content})
            tool_results=[{"type":"tool_result","tool_use_id":b.id,"content":"ok"}
                          for b in response.content if b.type=="tool_use"]
            if tool_results: messages.append({"role":"user","content":tool_results})
        else: break
    return ""


def call_simple(client, prompt: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=2500,
        messages=[{"role":"user","content":prompt}])
    return response.content[0].text


def _inject_dynamic(data: dict, dynamic: dict):
    if not dynamic: return

    # PMI
    if "pmi" in dynamic:
        for zone in ["france","usa","ez","chine"]:
            if zone in dynamic["pmi"] and dynamic["pmi"][zone].get("val"):
                data["pmi"][zone].update(dynamic["pmi"][zone])

    # CPI flash (priorité sur les données Eurostat si disponibles)
    if "cpi_flash" in dynamic:
        cf = dynamic["cpi_flash"]
        if cf.get("france_val"):
            data["cpi_fr"].update({"val":cf["france_val"],"period":cf.get("france_period","N/D"),
                                    "prev":cf.get("france_prev","N/D"),"source":cf.get("france_source","INSEE flash")})
        if cf.get("ez_val"):
            data["cpi_ez"].update({"val":cf["ez_val"],"period":cf.get("ez_period","N/D"),
                                    "prev":cf.get("ez_prev","N/D"),"source":cf.get("ez_source","Eurostat flash")})

    # Chine
    if "chine" in dynamic:
        c = dynamic["chine"]
        if c.get("pib_val"):
            data["gdp_chine"]={"val":c.get("pib_val","N/D"),"period":c.get("pib_period","N/D"),
                               "prev":c.get("pib_prev","N/D"),"prev_period":c.get("pib_prev_period","N/D"),
                               "n1":"N/D","n1_period":"N/D","source":"NBS via web_search"}
        if c.get("cpi_val"):
            data["cpi_chine"]={"val":c.get("cpi_val","N/D"),"period":c.get("cpi_period","N/D"),
                               "prev":c.get("cpi_prev","N/D"),"prev_period":c.get("cpi_prev_period","N/D"),
                               "n1":"N/D","n1_period":"N/D","source":"NBS via web_search"}
        if c.get("pboc_val"):
            data["pboc"]={"val":c.get("pboc_val","N/D"),"prev":c.get("pboc_prev","N/D"),
                          "detail":c.get("pboc_detail","LPR 1 an"),"source":"PBoC via web_search"}

    # Immo taux
    if "immo_taux" in dynamic and dynamic["immo_taux"].get("taux_20ans"):
        it = dynamic["immo_taux"]
        data["immobilier_taux"].update({k:v for k,v in it.items() if v})

    # Prix immo
    if "immo_prix" in dynamic:
        valid={k:v for k,v in dynamic["immo_prix"].items() if v.get("val",0)>0}
        if valid: data["immo_prix"]=valid

    # PE
    pe = data.get("private_equity",{})
    if "argos" in dynamic and dynamic["argos"].get("val"):
        a=dynamic["argos"]
        pe["argos"]=(a.get("val","N/D"),a.get("prev","N/D"),a.get("prev_period","N/D"),
                     a.get("n1","N/D"),a.get("n1_period","N/D"))
    if "france_invest" in dynamic:
        fi=dynamic["france_invest"]
        for key in ["levees","invest","cessions","nb_ent","rdt"]:
            if key in fi and fi[key].get("val"):
                d=fi[key]; pe[key]=(d.get("val","N/D"),d.get("var",""),d.get("periode",""))
    if "dry_powder" in dynamic and dynamic["dry_powder"].get("val"):
        dp=dynamic["dry_powder"]
        pe["dp"]=(dp.get("val","N/D"),dp.get("var",""),dp.get("periode",""))

    # Spread OAT/Bund
    if "spread_oat_bund" in dynamic and dynamic["spread_oat_bund"].get("oat"):
        sp=dynamic["spread_oat_bund"]
        data["spread"]={"spread":sp.get("spread","N/D"),"spread_prev":sp.get("spread_prev","N/D"),
                        "oat":sp.get("oat","N/D"),"bund":sp.get("bund","N/D"),"source":sp.get("source","web_search")}

    # Credit spreads (si FRED a échoué)
    if "credit_spreads" in dynamic and dynamic["credit_spreads"].get("ig_spread"):
        cs=dynamic["credit_spreads"]
        if data.get("credit_spreads",{}).get("ig_spread","N/D")=="N/D":
            data["credit_spreads"].update(cs)

    # Courbe US (si Yahoo a échoué)
    if "spread_us_curve" in dynamic and dynamic["spread_us_curve"].get("spread"):
        uc=dynamic["spread_us_curve"]
        if data.get("spread_us_curve",{}).get("spread","N/D")=="N/D":
            data["spread_us_curve"].update(uc)

    # SCPI
    if "scpi" in dynamic and dynamic["scpi"].get("marche",{}).get("td_moyen"):
        data["scpi"].update(dynamic["scpi"])


def get_claude_analysis(data: dict) -> tuple:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    today   = datetime.date.today()
    mois_fr = ["janvier","fevrier","mars","avril","mai","juin",
               "juillet","aout","septembre","octobre","novembre","decembre"]
    mois    = f"{mois_fr[today.month-1].capitalize()} {today.year}"
    annee   = today.year

    if not api_key:
        print("  ANTHROPIC_API_KEY non definie — fallbacks N/D")
        return _fallback_analysis(data), {}

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # 1. Recherche web de toutes les données dynamiques
        print("  Recherche web (PMI, Chine, flash CPI, immo, PE, SCPI, spreads)...")
        text    = call_with_search(client, build_search_prompt(mois, annee), max_tokens=5000)
        dynamic = extract_json(text) if text else {}
        print("  Donnees dynamiques OK")

        # 2. Injecter dans data
        _inject_dynamic(data, dynamic)

        # 3. Analyse
        print("  Analyse Claude...")
        text     = call_simple(client, build_analysis_prompt(data, mois))
        analysis = extract_json(text)
        print("  Analyse OK")
        return analysis, dynamic

    except Exception as e:
        print(f"  Erreur Claude: {e} — fallbacks N/D")
        return _fallback_analysis(data), {}


def _fallback_analysis(data: dict) -> dict:
    mois = data.get("date","ce mois")
    return {
        "commentaire_general": f"Analyse automatique indisponible pour {mois}.",
        "analyse_cycle": {z: {"regime":"N/D","commentaire":"Analyse indisponible."} for z in
            ["France","Etats-Unis","Zone Euro","Chine","Amerique latine","Asie ex-Chine"]},
        "points_vigilance":["API Claude indisponible."],
        "opportunites":    ["API Claude indisponible."],
        "allocation_recommandee":{k:"N/D" for k in
            ["actions","obligations","matieres_premieres","immobilier","cash_monetaire","private_equity","scpi"]},
        "synthese_immobilier":"Analyse indisponible.",
        "synthese_pe":"Analyse indisponible.",
        "synthese_scpi":"Analyse indisponible.",
        "analyse_courbe_taux":"Analyse indisponible.",
        "analyse_credit":"Analyse indisponible.",
    }
