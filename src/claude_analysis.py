"""
Appel API Claude avec web_search — 3 passes courtes + analyse.
Modele : configurable via ANTHROPIC_MODEL (defaut : claude-opus-4-5).

Cette version 6.1 corrige les trous identifies dans la version precedente :
- Fallback web_search ajoute pour PIB France/USA/Zone Euro et Fed rate
  (les APIs officielles tombent souvent en N/D suivant le calendrier de publication).
- Plafond de tokens cumules sur call_with_search pour eviter une boucle couteuse.
- Pause configurable entre passes (defaut 3s, suffisant pour Tier 1 500K tok/min).
"""
import os
import json
import time
import datetime
import anthropic


MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-5")
PAUSE = int(os.environ.get("CLAUDE_PAUSE_SECONDS", "3"))
MAX_SEARCH_ITERATIONS = int(os.environ.get("CLAUDE_MAX_ITER", "12"))


def extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise Exception("reponse vide")
    text = text.strip()
    # Cas balise ```json ... ```
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                text = p
                break
    # Decoupe sur les accolades extremes
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


def call_with_search(client, prompt: str, max_tokens: int = 2000) -> str:
    """
    Boucle d'echange avec l'API jusqu'a end_turn ou plafond d'iterations.
    Le plafond evite un loop couteux si Claude reste bloque sur tool_use.
    """
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    messages = [{"role": "user", "content": prompt}]
    for _ in range(MAX_SEARCH_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    return block.text
            return ""
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": "ok"}
                for b in response.content if b.type == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
        else:
            break
    return ""


def call_simple(client, prompt: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _need_gdp_fallback(data: dict) -> dict:
    """Identifie les zones PIB dont la collecte API a echoue."""
    need = {}
    for zone, key in [("France", "gdp_fr"), ("USA", "gdp_usa"), ("Zone Euro", "gdp_ez")]:
        v = data.get(key, {}).get("val", "N/D")
        if not v or v == "N/D":
            need[zone] = key
    return need


def _need_fed_fallback(data: dict) -> bool:
    v = data.get("fed_rate", {}).get("val", "N/D")
    return not v or v == "N/D"


def fetch_all_dynamic_data(client, mois: str, annee: int, data: dict) -> dict:
    """
    Recherche web en 3 passes.
    Le parametre `data` permet a la Passe 1 de cibler uniquement les indicateurs
    reellement manquants (PIB FR/US/ZE, Fed rate) plutot que de tout demander.
    """
    result = {}

    # ── Passe 1 : PMI + Chine + CPI flash + fallback PIB/Fed si APIs HS ──────
    gdp_need = _need_gdp_fallback(data)
    fed_need = _need_fed_fallback(data)
    fallback_block = ""
    fallback_keys = ""
    if gdp_need or fed_need:
        gdp_zones = ", ".join(gdp_need.keys()) if gdp_need else "aucune"
        extra = []
        if gdp_need:
            extra.append(f'"gdp_fallback":{{' +
                         ",".join([f'"{z.lower().replace(" ","_")}":{{"val":"","period":"","prev":"","prev_period":""}}'
                                   for z in gdp_need.keys()]) + "}")
        if fed_need:
            extra.append('"fed_fallback":{"val":"","prev":"","prev_period":"","source":""}')
        fallback_block = "," + ",".join(extra)
        fallback_keys = (
            f" + Fallback : PIB trimestriel le plus recent pour {gdp_zones}"
            + (" + Fed funds rate (upper bound) actuel" if fed_need else "")
        )

    prompt1 = (
        f'Recherche pour {mois} {annee}. Reponds UNIQUEMENT avec ce JSON :\n'
        '{"pmi":{"france":{"val":"","period":"","prev":"","source":""},'
        '"usa":{"val":"","period":"","prev":"","source":""},'
        '"ez":{"val":"","period":"","prev":"","source":""},'
        '"chine":{"val":"","period":"","prev":"","source":""}},'
        '"chine":{"pib_val":"","pib_period":"","pib_prev":"","pib_prev_period":"",'
        '"cpi_val":"","cpi_period":"","cpi_prev":"","cpi_prev_period":"",'
        '"pboc_val":"","pboc_prev":"","pboc_detail":""},'
        '"cpi_flash":{"france_val":"","france_period":"","france_prev":"","france_source":"",'
        '"ez_val":"","ez_period":"","ez_prev":"","ez_source":""}'
        + fallback_block + '}\n'
        f'Recherche : 1) PMI S&P Global/HCOB/Caixin {mois} {annee} '
        f'2) PIB CPI Chine {annee} '
        f'3) CPI flash France Zone Euro {mois} {annee}'
        + fallback_keys
    )

    try:
        print("  Passe 1 (PMI/Chine/CPI" + (" + fallback PIB/Fed" if (gdp_need or fed_need) else "") + ")...")
        text1 = call_with_search(client, prompt1, max_tokens=2500)
        if text1:
            result.update(extract_json(text1))
            print("  Passe 1 OK")
    except Exception as e:
        print(f"  Passe 1 echouee: {e}")

    print(f"  Pause {PAUSE}s...")
    time.sleep(PAUSE)

    # ── Passe 2 : Spreads + PE ────────────────────────────────────────────────
    prompt2 = (
        f'Recherche pour {mois} {annee}. Reponds UNIQUEMENT avec ce JSON :\n'
        '{"spread_oat_bund":{"oat":"","bund":"","spread":"","spread_prev":"","source":""},'
        '"spread_us_curve":{"us_2y":"","us_10y":"","spread":"","spread_prev":"","signal":"","source":""},'
        '"credit_spreads":{"ig_spread":"","ig_spread_prev":"","ig_spread_n1":"",'
        '"hy_spread":"","hy_spread_prev":"","hy_spread_n1":"","source":""},'
        '"argos":{"val":"","prev":"","prev_period":"","n1":"","n1_period":"","source":""},'
        '"dry_powder":{"val":"","var":"","periode":"","source":""},'
        '"france_invest":{"levees":{"val":"","var":"","periode":""},'
        '"invest":{"val":"","var":"","periode":""},'
        '"cessions":{"val":"","var":"","periode":""},'
        '"nb_ent":{"val":"","var":"","periode":""},'
        '"rdt":{"val":"","var":"","periode":""}}}\n'
        "Recherche : 1) Spread OAT/Bund 10 ans aujourd'hui (Banque de France/Bundesbank) "
        "2) Courbe US 2 ans / 10 ans aujourd'hui "
        "3) Spreads credit Investment Grade et High Yield (FRED BAMLC0A0CM / BAMLH0A0HYM2) "
        f"4) Indice Argos Mid-Market dernier trimestre {annee} "
        f"5) France Invest activite {annee} (levees, investissements, cessions, entreprises) "
        f"6) Dry Powder Private Equity mondial {annee} (Bain/Preqin)"
    )

    try:
        print("  Passe 2 (spreads/PE)...")
        text2 = call_with_search(client, prompt2, max_tokens=2500)
        if text2:
            result.update(extract_json(text2))
            print("  Passe 2 OK")
    except Exception as e:
        print(f"  Passe 2 echouee: {e}")

    print(f"  Pause {PAUSE}s...")
    time.sleep(PAUSE)

    # ── Passe 3 : Immo + SCPI ─────────────────────────────────────────────────
    prompt3 = (
        f'Recherche pour {mois} {annee}. Reponds UNIQUEMENT avec ce JSON :\n'
        '{"immo_taux":{"taux_20ans":"","taux_20ans_prev":"","taux_20ans_n1":"",'
        '"taux_20ans_commentaire":"","bureaux_val":"","bureaux_prev":"","bureaux_n1":"",'
        '"bureaux_commentaire":"","commerces_val":"","commerces_prev":"","commerces_n1":"",'
        '"commerces_commentaire":""},'
        '"immo_prix":{"Paris":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Lyon":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Tassin-la-Demi-Lune":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Saint-Foy-les-Lyon":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Maisons-Laffitte":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Le Vesinet":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Chatou":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""},'
        '"Saint-Germain-en-Laye":{"val":0,"var_1an":0.0,"var_5ans":0.0,"periode":"","source":""}},'
        '"scpi":{"marche":{"td_moyen":"","td_moyen_prev":"","td_moyen_n1":"",'
        '"collecte_nette":"","collecte_prev":"","collecte_periode":"",'
        '"decote_secondaire":"","decote_prev":"","tof_moyen":"","source":""},'
        '"par_secteur":[{"secteur":"Bureaux","poids":"","td":"","tendance":"","commentaire":""},'
        '{"secteur":"Commerce","poids":"","td":"","tendance":"","commentaire":""},'
        '{"secteur":"Sante","poids":"","td":"","tendance":"","commentaire":""},'
        '{"secteur":"Logistique","poids":"","td":"","tendance":"","commentaire":""},'
        '{"secteur":"Diversifie","poids":"","td":"","tendance":"","commentaire":""}],'
        '"scpi_phares":[{"nom":"","gestionnaire":"","secteur":"","td":"","tof":"","prix_part":"","var_prix":"","note":""},'
        '{"nom":"","gestionnaire":"","secteur":"","td":"","tof":"","prix_part":"","var_prix":"","note":""},'
        '{"nom":"","gestionnaire":"","secteur":"","td":"","tof":"","prix_part":"","var_prix":"","note":""}],'
        '"analyse":"","points_vigilance":["","",""],"opportunites":["","",""]}}\n'
        f"Tendance par secteur SCPI : utilise EXACTEMENT l'un de ces symboles : haut, bas, stable.\n"
        f"Recherche : 1) Taux credit immo 20 ans France {mois} {annee} CAFPI "
        "2) Bureaux vacants IDF CBRE JLL dernier trimestre "
        "3) Prix m2 Paris Lyon Tassin-la-Demi-Lune Saint-Foy-les-Lyon Maisons-Laffitte Le Vesinet Chatou Saint-Germain-en-Laye "
        f"4) SCPI marche France {annee} : TD moyen, collecte nette, decote secondaire, TOF, perfs par secteur "
        "5) 3 SCPI phares (Iroko Zen, Corum Origin, Transitions Europe)"
    )

    try:
        print("  Passe 3 (immo/SCPI)...")
        text3 = call_with_search(client, prompt3, max_tokens=3500)
        if text3:
            parsed = extract_json(text3)
            # Normalisation tendance SCPI : "haut"/"bas"/"stable" -> triangle
            tend_map = {"haut": "▲", "bas": "▼", "stable": "▶",
                        "▲": "▲", "▼": "▼", "▶": "▶"}
            for s in parsed.get("scpi", {}).get("par_secteur", []):
                s["tendance"] = tend_map.get(s.get("tendance", "").strip().lower(), "▶")
            result.update(parsed)
            print("  Passe 3 OK")
    except Exception as e:
        print(f"  Passe 3 echouee: {e}")

    return result


def build_analysis_prompt(data: dict, mois: str) -> str:
    def v(path, default="N/D"):
        try:
            keys = path.split(".")
            d = data
            for k in keys:
                d = d[k]
            return str(d) if d else default
        except Exception:
            return default

    cac_p = sp_p = 0
    try:
        cac = data.get("indices", {}).get("CAC 40", {})
        if cac.get("prev_y"):
            cac_p = (cac["val"] - cac["prev_y"]) / cac["prev_y"] * 100
        sp = data.get("indices", {}).get("S&P 500", {})
        if sp.get("prev_y"):
            sp_p = (sp["val"] - sp["prev_y"]) / sp["prev_y"] * 100
    except Exception:
        pass

    sc = data.get("spread_us_curve", {})
    cs = data.get("credit_spreads", {})

    return f"""Tu es conseiller en gestion de patrimoine senior chez HEXA Patrimoine.
Analyse les donnees economiques de {mois} et produis une analyse professionnelle.

DONNEES MACRO :
PIB : France {v("gdp_fr.val")} | Zone Euro {v("gdp_ez.val")} | USA {v("gdp_usa.val")} | Chine {v("gdp_chine.val")}
PMI : France {v("pmi.france.val")} | Zone Euro {v("pmi.ez.val")} | USA {v("pmi.usa.val")} | Chine {v("pmi.chine.val")}
NFP {v("nfp.val")} | Chomage US {v("unemployment_usa.val")}
Inflation : France {v("cpi_fr.val")} | ZE {v("cpi_ez.val")} | USA {v("cpi_usa.val")} | Chine {v("cpi_chine.val")}
Taux : BCE {v("ecb_rate.val")} | Fed {v("fed_rate.val")} | Euribor {v("euribor.val")}
VIX {v("vix.val")} | F&G {v("fg.val")}/100 | OAT/Bund {v("spread.spread")} bps
Courbe US 2/10 ans : {sc.get("spread","N/D")} (signal : {sc.get("signal","N/D")})
Credit : IG {cs.get("ig_spread","N/D")} | HY {cs.get("hy_spread","N/D")}
CAC 40 {cac_p:+.1f}%/an | S&P 500 {sp_p:+.1f}%/an

REGLES IMPORTANTES :
- Pour chaque zone, classe-la dans UN regime parmi : Goldilocks, Surchauffe, Obligations, Stagflation.
  Goldilocks : croissance positive (>0%) ET inflation maitrisee (<3%).
  Surchauffe : croissance robuste (>1.5%) ET inflation elevee (>3%).
  Obligations : croissance faible/nulle (<0.5%) ET inflation maitrisee (<2.5%).
  Stagflation : croissance faible/nulle (<0.5%) ET inflation elevee (>2.5%).
- Si une donnee est N/D, raisonne a partir du PMI et de l'inflation seuls.
- Pour Amerique latine et Asie ex-Chine, utilise les estimations FMI WEO les plus recentes.

Reponds UNIQUEMENT avec ce JSON :
{{
  "commentaire_general": "2-3 phrases contexte macro HEXA.",
  "analyse_cycle": {{
    "France":          {{"regime": "Goldilocks|Surchauffe|Obligations|Stagflation", "commentaire": "1 phrase", "pib_estime": "valeur en %", "cpi_estime": "valeur en %"}},
    "Etats-Unis":      {{"regime": "...", "commentaire": "...", "pib_estime": "...", "cpi_estime": "..."}},
    "Zone Euro":       {{"regime": "...", "commentaire": "...", "pib_estime": "...", "cpi_estime": "..."}},
    "Chine":           {{"regime": "...", "commentaire": "...", "pib_estime": "...", "cpi_estime": "..."}},
    "Amerique latine": {{"regime": "...", "commentaire": "...", "pib_estime": "...", "cpi_estime": "..."}},
    "Asie ex-Chine":   {{"regime": "...", "commentaire": "...", "pib_estime": "...", "cpi_estime": "..."}}
  }},
  "points_vigilance": ["risque 1", "risque 2", "risque 3"],
  "opportunites":     ["opp 1", "opp 2", "opp 3"],
  "allocation_recommandee": {{
    "actions":"1 phrase","obligations":"1 phrase",
    "matieres_premieres":"1 phrase","immobilier":"1 phrase",
    "cash_monetaire":"1 phrase","private_equity":"1 phrase","scpi":"1 phrase"
  }},
  "synthese_immobilier":"2 phrases.",
  "synthese_pe":"2 phrases.",
  "synthese_scpi":"2 phrases.",
  "analyse_courbe_taux":"1 phrase.",
  "analyse_credit":"1 phrase."
}}"""


def _inject_dynamic(data: dict, dynamic: dict):
    if not dynamic:
        return

    # PMI
    if "pmi" in dynamic:
        for zone in ["france", "usa", "ez", "chine"]:
            if zone in dynamic["pmi"] and dynamic["pmi"][zone].get("val"):
                data["pmi"][zone].update(dynamic["pmi"][zone])

    # CPI flash France / Zone Euro
    if "cpi_flash" in dynamic:
        cf = dynamic["cpi_flash"]
        if cf.get("france_val"):
            data["cpi_fr"].update({
                "val": cf["france_val"],
                "period": cf.get("france_period", "N/D"),
                "prev": cf.get("france_prev", "N/D"),
                "source": cf.get("france_source", "INSEE flash"),
            })
        if cf.get("ez_val"):
            data["cpi_ez"].update({
                "val": cf["ez_val"],
                "period": cf.get("ez_period", "N/D"),
                "prev": cf.get("ez_prev", "N/D"),
                "source": cf.get("ez_source", "Eurostat flash"),
            })

    # Chine
    if "chine" in dynamic:
        c = dynamic["chine"]
        if c.get("pib_val"):
            data["gdp_chine"] = {
                "val": c.get("pib_val", "N/D"), "period": c.get("pib_period", "N/D"),
                "prev": c.get("pib_prev", "N/D"), "prev_period": c.get("pib_prev_period", "N/D"),
                "n1": "N/D", "n1_period": "N/D", "source": "NBS via web_search",
            }
        if c.get("cpi_val"):
            data["cpi_chine"] = {
                "val": c.get("cpi_val", "N/D"), "period": c.get("cpi_period", "N/D"),
                "prev": c.get("cpi_prev", "N/D"), "prev_period": c.get("cpi_prev_period", "N/D"),
                "n1": "N/D", "n1_period": "N/D", "source": "NBS via web_search",
            }
        if c.get("pboc_val"):
            data["pboc"] = {
                "val": c.get("pboc_val", "N/D"), "prev": c.get("pboc_prev", "N/D"),
                "detail": c.get("pboc_detail", "LPR 1 an"), "source": "PBoC via web_search",
            }

    # Fallback PIB France/USA/Zone Euro (si APIs officielles ont echoue)
    gdp_fb = dynamic.get("gdp_fallback", {})
    gdp_map = {"france": "gdp_fr", "usa": "gdp_usa", "zone_euro": "gdp_ez"}
    for src_key, target_key in gdp_map.items():
        entry = gdp_fb.get(src_key, {})
        if entry.get("val") and data.get(target_key, {}).get("val", "N/D") == "N/D":
            data[target_key] = {
                "val": entry["val"], "period": entry.get("period", "N/D"),
                "prev": entry.get("prev", "N/D"), "prev_period": entry.get("prev_period", "N/D"),
                "n1": "N/D", "n1_period": "N/D",
                "source": f"{'Eurostat' if src_key!='usa' else 'BEA'} via web_search",
            }

    # Fallback Fed rate
    fed_fb = dynamic.get("fed_fallback", {})
    if fed_fb.get("val") and data.get("fed_rate", {}).get("val", "N/D") == "N/D":
        data["fed_rate"] = {
            "val": fed_fb["val"], "period": "courant",
            "prev": fed_fb.get("prev", "N/D"), "prev_period": fed_fb.get("prev_period", "N/D"),
            "n1": "N/D", "n1_period": "N/D",
            "source": fed_fb.get("source") or "Fed via web_search",
        }

    # Immo taux
    if "immo_taux" in dynamic and dynamic["immo_taux"].get("taux_20ans"):
        it = dynamic["immo_taux"]
        data["immobilier_taux"].update({k: v for k, v in it.items() if v})

    # Prix immo par ville
    if "immo_prix" in dynamic:
        valid = {k: v for k, v in dynamic["immo_prix"].items() if v.get("val", 0) > 0}
        if valid:
            data["immo_prix"] = valid

    # Private Equity
    pe = data.get("private_equity", {})
    if "argos" in dynamic and dynamic["argos"].get("val"):
        a = dynamic["argos"]
        pe["argos"] = (a.get("val", "N/D"), a.get("prev", "N/D"), a.get("prev_period", "N/D"),
                       a.get("n1", "N/D"), a.get("n1_period", "N/D"))
    if "france_invest" in dynamic:
        fi = dynamic["france_invest"]
        for key in ["levees", "invest", "cessions", "nb_ent", "rdt"]:
            if key in fi and fi[key].get("val"):
                d = fi[key]
                pe[key] = (d.get("val", "N/D"), d.get("var", ""), d.get("periode", ""))
    if "dry_powder" in dynamic and dynamic["dry_powder"].get("val"):
        dp = dynamic["dry_powder"]
        pe["dp"] = (dp.get("val", "N/D"), dp.get("var", ""), dp.get("periode", ""))

    # Spread OAT/Bund
    if "spread_oat_bund" in dynamic and dynamic["spread_oat_bund"].get("oat"):
        sp = dynamic["spread_oat_bund"]
        data["spread"] = {
            "spread": sp.get("spread", "N/D"), "spread_prev": sp.get("spread_prev", "N/D"),
            "oat": sp.get("oat", "N/D"), "bund": sp.get("bund", "N/D"),
            "source": sp.get("source", "web_search"),
        }

    # Credit spreads (uniquement si FRED a echoue)
    if "credit_spreads" in dynamic and dynamic["credit_spreads"].get("ig_spread"):
        cs = dynamic["credit_spreads"]
        if data.get("credit_spreads", {}).get("ig_spread", "N/D") == "N/D":
            data["credit_spreads"].update(cs)

    # Courbe US 2/10 ans (uniquement si Yahoo a echoue)
    if "spread_us_curve" in dynamic and dynamic["spread_us_curve"].get("spread"):
        uc = dynamic["spread_us_curve"]
        if data.get("spread_us_curve", {}).get("spread", "N/D") == "N/D":
            data["spread_us_curve"].update(uc)

    # SCPI
    if "scpi" in dynamic and dynamic["scpi"].get("marche", {}).get("td_moyen"):
        data["scpi"].update(dynamic["scpi"])


def get_claude_analysis(data: dict) -> tuple:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    today = datetime.date.today()
    mois_fr = ["janvier", "fevrier", "mars", "avril", "mai", "juin",
               "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]
    mois = f"{mois_fr[today.month-1].capitalize()} {today.year}"
    annee = today.year

    if not api_key:
        print("  ANTHROPIC_API_KEY non definie")
        return _fallback_analysis(data), {}

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # 3 passes de recherche (avec connaissance des trous a combler)
        dynamic = fetch_all_dynamic_data(client, mois, annee, data)
        _inject_dynamic(data, dynamic)

        # Pause avant analyse
        print(f"  Pause {PAUSE}s avant analyse...")
        time.sleep(PAUSE)

        # Analyse
        print("  Analyse Claude...")
        text = call_simple(client, build_analysis_prompt(data, mois))
        analysis = extract_json(text)
        print("  Analyse OK")
        return analysis, dynamic

    except Exception as e:
        print(f"  Erreur Claude: {e}")
        return _fallback_analysis(data), {}


def _fallback_analysis(data: dict) -> dict:
    mois = data.get("date", "ce mois")
    return {
        "commentaire_general": f"Analyse automatique indisponible pour {mois}.",
        "analyse_cycle": {z: {"regime": "N/D", "commentaire": "Analyse indisponible.",
                              "pib_estime": "N/D", "cpi_estime": "N/D"}
                          for z in ["France", "Etats-Unis", "Zone Euro", "Chine",
                                    "Amerique latine", "Asie ex-Chine"]},
        "points_vigilance": ["API Claude indisponible."],
        "opportunites": ["API Claude indisponible."],
        "allocation_recommandee": {k: "N/D" for k in
            ["actions", "obligations", "matieres_premieres", "immobilier",
             "cash_monetaire", "private_equity", "scpi"]},
        "synthese_immobilier": "Analyse indisponible.",
        "synthese_pe": "Analyse indisponible.",
        "synthese_scpi": "Analyse indisponible.",
        "analyse_courbe_taux": "Analyse indisponible.",
        "analyse_credit": "Analyse indisponible.",
    }
