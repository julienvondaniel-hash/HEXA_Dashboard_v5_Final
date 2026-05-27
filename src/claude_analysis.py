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
MAX_SEARCH_ITERATIONS = int(os.environ.get("CLAUDE_MAX_ITER", "20"))


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
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # En cas de JSON tronque (max_tokens), on tente une reparation simple :
        # on cherche la derniere virgule/accolade valide et on ferme proprement.
        print(f"  [WARN] JSON invalide : {e}")
        snippet_start = text[:120].replace("\n", " ")
        snippet_end = text[-120:].replace("\n", " ")
        print(f"  [WARN] Debut: {snippet_start!r}")
        print(f"  [WARN] Fin  : {snippet_end!r}")
        # Tentative de reparation : couper avant la derniere structure incomplete
        repaired = _attempt_json_repair(text)
        if repaired is not None:
            try:
                result = json.loads(repaired)
                print(f"  [OK] JSON repare avec {len(result)} cles de premier niveau.")
                return result
            except json.JSONDecodeError:
                pass
        raise


def _attempt_json_repair(text: str):
    """Tentative simple de reparation d'un JSON tronque par max_tokens.
    On equilibre les accolades / crochets en coupant a la derniere paire complete."""
    if not text or text[0] != "{":
        return None
    depth_curl = 0
    depth_brack = 0
    in_str = False
    escape = False
    last_safe = -1  # Position apres la derniere paire (clef: valeur) complete au niveau racine
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth_curl += 1
        elif c == "}":
            depth_curl -= 1
            if depth_curl == 0:
                # Cas trivial : JSON complet, pas besoin de reparer
                return text[:i+1]
        elif c == "[":
            depth_brack += 1
        elif c == "]":
            depth_brack -= 1
        elif c == "," and depth_curl == 1 and depth_brack == 0:
            # Une virgule au niveau racine = fin propre d'une cle de premier niveau
            last_safe = i
    if last_safe < 0:
        return None
    # On coupe a la derniere virgule racine et on ferme l'accolade
    return text[:last_safe] + "}"


def call_with_search(client, prompt: str, max_tokens: int = 2000) -> str:
    """
    Boucle d'echange avec l'API jusqu'a end_turn ou plafond d'iterations.
    Le plafond evite un loop couteux si Claude reste bloque sur tool_use.

    Renvoie le dernier bloc texte trouve, meme en cas de truncation (max_tokens).
    Cela evite de perdre une reponse partielle exploitable.
    """
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    messages = [{"role": "user", "content": prompt}]
    last_text = ""
    tool_use_count = 0
    for it in range(MAX_SEARCH_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )
        # On capture tout texte present dans la reponse, quelle que soit le stop_reason
        for block in response.content:
            if hasattr(block, "text") and block.text:
                last_text = block.text

        if response.stop_reason == "end_turn":
            return last_text
        if response.stop_reason == "tool_use":
            tool_use_count += sum(1 for b in response.content if b.type == "tool_use")
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": "ok"}
                for b in response.content if b.type == "tool_use"
            ]
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            continue
        if response.stop_reason == "max_tokens":
            print(f"  [WARN] max_tokens atteint a l'iteration {it+1} (budget {max_tokens}). "
                  f"Texte recupere : {len(last_text)} chars.")
            return last_text
        # Autre stop_reason inattendu : on log et on sort avec ce qu'on a
        print(f"  [WARN] stop_reason inattendu : {response.stop_reason}. "
              f"Texte recupere : {len(last_text)} chars.")
        break
    # Sortie par limite d'iterations sans end_turn
    print(f"  [WARN] Limite MAX_SEARCH_ITERATIONS={MAX_SEARCH_ITERATIONS} atteinte "
          f"({tool_use_count} tool_use total). Texte recupere : {len(last_text)} chars.")
    return last_text


def call_simple(client, prompt: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _strip_unit(s, units=("bps", "pb", "%")):
    """Enleve les suffixes d'unite d'une valeur numerique pour eviter les doubles unites en sortie PDF.
    Garde la valeur brute (ex : '69 bps' -> '69', '0.91%' -> '0.91')."""
    if not s or not isinstance(s, str):
        return s
    out = s.strip()
    for u in units:
        if out.lower().endswith(u.lower()):
            out = out[: -len(u)].strip()
    return out


def _strip_unit_pct_only(s):
    """Comme _strip_unit, mais ne touche pas aux 'bps'. Pour les valeurs OAT/Bund qui gardent leur %."""
    if not s or not isinstance(s, str):
        return s
    return s.strip()


def _ensure_pct(s):
    """Garantit qu'une valeur a le symbole % si elle est purement numerique."""
    if not s or not isinstance(s, str):
        return s
    st = s.strip()
    if not st or st.upper() == "N/D":
        return st
    if "%" in st:
        return st
    try:
        float(st.replace(",", "."))
        return st + "%"
    except ValueError:
        return st


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


def _need_euribor_fallback(data: dict) -> bool:
    v = data.get("euribor", {}).get("val", "N/D")
    return not v or v == "N/D"


def _need_spread_fallback(data: dict) -> bool:
    v = data.get("spread", {}).get("spread", "N/D")
    return not v or v == "N/D"


def fetch_all_dynamic_data(client, mois: str, annee: int, data: dict) -> dict:
    """
    Recherche web en 3 passes.
    Le parametre `data` permet a la Passe 1 de cibler uniquement les indicateurs
    reellement manquants (PIB FR/US/ZE, Fed rate) plutot que de tout demander.
    """
    result = {}

    # ── Passe 1 : PMI + Chine + CPI flash + fallback PIB/Fed/Euribor si APIs HS ──
    gdp_need = _need_gdp_fallback(data)
    fed_need = _need_fed_fallback(data)
    eur_need = _need_euribor_fallback(data)
    fallback_block = ""
    fallback_keys = ""
    if gdp_need or fed_need or eur_need:
        gdp_zones = ", ".join(gdp_need.keys()) if gdp_need else "aucune"
        extra = []
        if gdp_need:
            extra.append(f'"gdp_fallback":{{' +
                         ",".join([f'"{z.lower().replace(" ","_")}":{{"val":"","period":"","prev":"","prev_period":""}}'
                                   for z in gdp_need.keys()]) + "}")
        if fed_need:
            extra.append('"fed_fallback":{"val":"","prev":"","prev_period":"","source":""}')
        if eur_need:
            extra.append('"euribor_fallback":{"val":"","date":"","prev":"","prev_date":"","n1":"","n1_date":""}')
        fallback_block = "," + ",".join(extra)
        parts = []
        if gdp_need: parts.append(f"PIB trimestriel le plus recent pour {gdp_zones}")
        if fed_need: parts.append("Fed funds rate (upper bound) actuel")
        if eur_need: parts.append("Euribor 3 mois actuel et historique")
        fallback_keys = " + Fallback : " + " + ".join(parts)

    prompt1 = (
        f'Recherche pour {mois} {annee}. Reponds UNIQUEMENT avec ce JSON :\n'
        '{"pmi":{"france":{"val":"","period":"","prev":"","source":""},'
        '"usa":{"val":"","period":"","prev":"","source":""},'
        '"ez":{"val":"","period":"","prev":"","source":""},'
        '"chine":{"val":"","period":"","prev":"","source":""},'
        '"latam":{"val":"","period":"","prev":"","source":""},'
        '"asie_ex_chine":{"val":"","period":"","prev":"","source":""}},'
        '"chine":{"pib_val":"","pib_period":"","pib_prev":"","pib_prev_period":"",'
        '"cpi_val":"","cpi_period":"","cpi_prev":"","cpi_prev_period":"",'
        '"pboc_val":"","pboc_prev":"","pboc_detail":""},'
        '"cpi_flash":{"france_val":"","france_period":"","france_prev":"","france_source":"",'
        '"ez_val":"","ez_period":"","ez_prev":"","ez_source":""},'
        # Nouvelles zones v6.5.2 : PIB + CPI + taux directeurs Latam (Bresil) et Asie ex-Chine (Inde)
        '"emerging_zones":{'
        '"latam":{"gdp_val":"","gdp_period":"","gdp_prev":"","gdp_prev_period":"",'
                  '"cpi_val":"","cpi_period":"","cpi_prev":"","cpi_prev_period":"","source":""},'
        '"asie_ex_chine":{"gdp_val":"","gdp_period":"","gdp_prev":"","gdp_prev_period":"",'
                         '"cpi_val":"","cpi_period":"","cpi_prev":"","cpi_prev_period":"","source":""},'
        '"bcb_selic":{"val":"","prev":"","detail":"","source":""},'
        '"rbi_repo":{"val":"","prev":"","detail":"","source":""}'
        '}'
        + fallback_block + '}\n'
        'REGLES DE FORMAT (importantes pour l\'affichage correct du PDF) :\n'
        '- PIB et CPI : TOUJOURS avec le symbole "%". Exemple : "0.3%", "2.2%", "+5.0%". '
        'JAMAIS sans % (ne pas ecrire juste "0.3" ou "2.2").\n'
        '- Taux directeurs (PBoC, Fed, BCB Selic, RBI Repo) : TOUJOURS avec "%". Exemple : "3.00%", "10.75%".\n'
        '- PMI : nombre seul SANS unite ni mention. Exemple : "48.9", PAS "48.9 (contraction)".\n'
        '- NFP : nombre brut avec signe. Exemple : "+115000" ou "+115,000".\n'
        '- Periode PMI : TOUJOURS un mois ("Mai 2026"), JAMAIS un trimestre ("Q2 2026" ou "T2 2026"). '
        'Les PMI Composite sont des indicateurs mensuels.\n'
        '- ZONES EMERGENTES (CRITIQUE) : pour "emerging_zones.latam" et "emerging_zones.asie_ex_chine", '
        'remplir IMPERATIVEMENT gdp_val et cpi_val avec les agregats regionaux FMI WEO (rapport WEO d\'avril ou octobre le plus recent). '
        'Exemple Latam : gdp_val="2.5%", gdp_period="2025", cpi_val="5.0%", cpi_period="2025". '
        'Exemple Asie ex-Chine : gdp_val="4.5%", gdp_period="2025", cpi_val="2.3%", cpi_period="2025". '
        'Ces valeurs sont obligatoires pour le rendu PDF.\n'
        f'Recherche : 1) PMI S&P Global/HCOB/Caixin {mois} {annee} (4 grandes zones, periode en MOIS) '
        f'2) PIB CPI Chine {annee} '
        f'3) CPI flash France Zone Euro {mois} {annee} '
        f'4) FMI WEO {annee} agregat Amerique latine et Caraibes : projection PIB et inflation annuelle '
        f'5) FMI WEO {annee} agregat emerging Asia excluding China : projection PIB et inflation annuelle '
        f'6) BCB Brasil Selic decision la plus recente + RBI India Repo Rate decision la plus recente'
        + fallback_keys
    )

    try:
        print("  Passe 1 (PMI/Chine/CPI" + (" + fallback PIB/Fed/Euribor" if (gdp_need or fed_need or eur_need) else "") + ")...")
        text1 = call_with_search(client, prompt1, max_tokens=4000)
        if text1:
            result.update(extract_json(text1))
            print("  Passe 1 OK")
        else:
            print("  Passe 1 : reponse vide de Claude")
    except Exception as e:
        snippet = (text1[:200] if 'text1' in dir() and text1 else "(vide)").replace("\n", " ")
        print(f"  Passe 1 echouee: {e}")
        print(f"  Passe 1 contenu (200 premiers chars) : {snippet!r}")

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
        'Format : oat/bund avec %, spreads en bps (juste le nombre), argos avec x, dp en T$, montants en Md€.\n'
        "Recherche : 1) Spread OAT/Bund 10 ans (Banque de France/Bundesbank) "
        "2) Courbe US 2 ans / 10 ans "
        "3) Spreads credit IG et HY (FRED BAMLC0A0CM / BAMLH0A0HYM2) "
        f"4) Argos Mid-Market T1 {annee} "
        f"5) France Invest {annee-1} (levees, invest, cessions, entreprises) "
        f"6) Dry Powder PE mondial {annee} (Bain/Preqin)"
    )

    try:
        print("  Passe 2 (spreads/PE)...")
        text2 = call_with_search(client, prompt2, max_tokens=5000)
        if text2:
            result.update(extract_json(text2))
            print("  Passe 2 OK")
        else:
            print("  Passe 2 : reponse vide de Claude (probable runaway tool_use)")
    except Exception as e:
        snippet = (text2[:200] if 'text2' in dir() and text2 else "(vide)").replace("\n", " ")
        print(f"  Passe 2 echouee: {e}")
        print(f"  Passe 2 contenu (200 premiers chars) : {snippet!r}")

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
        # v6.5.2 : top 10 SCPI par collecte (au lieu de 3 SCPI phares)
        '"scpi_top10":['
        + ",".join(['{"nom":"","gestionnaire":"","secteur":"","td":"","tof":"","prix_part":"","var_prix":"","collecte":"","note":""}'] * 10)
        + '],'
        '"analyse":"","points_vigilance":["","",""],"opportunites":["","",""]}}\n'
        f"Tendance par secteur SCPI : utilise EXACTEMENT 'haut', 'bas' ou 'stable'.\n"
        "Format : TD secteur ANNUEL (pas /trim), sans (annualise). Source prix immo : 'DVF/MeilleursAgents'.\n"
        "Pour scpi_top10 : RANG IMPORTANT, classees par collecte nette decroissante "
        f"(plus grosse collecte {annee} en position 1). "
        "Inclure le champ 'collecte' (ex : '450 M€', '320 M€'). "
        "Note doit etre courte (1 phrase max, ex : 'Sans frais d'entree, label ISR').\n"
        f"Recherche : 1) Taux credit immo 20 ans France {mois} {annee} CAFPI "
        "2) Bureaux vacants IDF CBRE JLL dernier trimestre "
        "3) Prix m2 Paris Lyon Tassin-la-Demi-Lune Saint-Foy-les-Lyon Maisons-Laffitte Le Vesinet Chatou Saint-Germain-en-Laye "
        f"4) SCPI marche France {annee} : TD moyen, collecte nette, decote secondaire, TOF, perfs par secteur "
        f"5) Top 10 SCPI par collecte nette {annee} (ASPIM / MeilleuresSCPI / Pierrepapier classement)"
    )

    try:
        print("  Passe 3 (immo/SCPI)...")
        text3 = call_with_search(client, prompt3, max_tokens=6000)
        if text3:
            parsed = extract_json(text3)
            # Normalisation tendance SCPI : "haut"/"bas"/"stable" -> triangle
            tend_map = {"haut": "▲", "bas": "▼", "stable": "▶",
                        "▲": "▲", "▼": "▼", "▶": "▶"}
            for s in parsed.get("scpi", {}).get("par_secteur", []):
                s["tendance"] = tend_map.get(s.get("tendance", "").strip().lower(), "▶")
                # Normalisation TD : enleve "/trim" et convertit en annuel si necessaire
                td = s.get("td", "").strip()
                if "/trim" in td.lower() or "trimestriel" in td.lower():
                    # Extraire valeur et la multiplier par 4
                    import re
                    m = re.search(r"([\d.,]+)", td)
                    if m:
                        try:
                            v = float(m.group(1).replace(",", "."))
                            s["td"] = f"{v*4:.1f}%"
                        except ValueError:
                            s["td"] = td.replace("/trim", "").replace("/trimestriel", "").strip()
                    else:
                        s["td"] = td.replace("/trim", "").replace("/trimestriel", "").strip()
                # S'assurer d'avoir le %
                if s.get("td") and "%" not in s["td"]:
                    s["td"] = s["td"] + "%"
            # Nettoyage TD marche / TOF / decote / SCPI top 10 : retirer "(annualise)"
            mkt = parsed.get("scpi", {}).get("marche", {})
            for k in ("td_moyen", "td_moyen_prev", "td_moyen_n1", "tof_moyen", "decote_secondaire", "decote_prev"):
                v = mkt.get(k, "")
                if isinstance(v, str):
                    mkt[k] = v.replace("(annualise)", "").replace("(annualisé)", "").strip()
            for sp in parsed.get("scpi", {}).get("scpi_top10", []):
                for k in ("td", "tof"):
                    v = sp.get(k, "")
                    if isinstance(v, str):
                        sp[k] = v.replace("(annualise)", "").replace("(annualisé)", "").strip()
            result.update(parsed)
            print("  Passe 3 OK")
        else:
            print("  Passe 3 : reponse vide de Claude (probable runaway tool_use)")
    except Exception as e:
        snippet = (text3[:200] if 'text3' in dir() and text3 else "(vide)").replace("\n", " ")
        print(f"  Passe 3 echouee: {e}")
        print(f"  Passe 3 contenu (200 premiers chars) : {snippet!r}")

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
  APPLIQUE LES SEUILS STRICTEMENT (ne pas surinterpreter) :
  Goldilocks   : croissance > 0.5% ET inflation < 2.5%.
  Surchauffe   : croissance > 1.5% ET inflation >= 2.5%.
  Obligations  : croissance <= 0.5% ET inflation < 2.5%.
  Stagflation  : croissance <= 0.5% ET inflation >= 2.5%.
  Exemples : France PIB 0.0% + CPI 2.2% -> Obligations (PAS Stagflation, car CPI<2.5%).
             USA PIB 2.0% + CPI 3.6% -> Surchauffe.
             Zone Euro PIB 0.1% + CPI 3.0% -> Stagflation.
- Si une donnee est N/D, raisonne a partir du PMI et de l'inflation seuls.
- Pour Amerique latine et Asie ex-Chine, utilise les estimations FMI WEO les plus recentes.
- pib_estime et cpi_estime : TOUJOURS avec le symbole "%". Exemple "2.0%", "+5.0%", PAS juste "2.0".

Reponds UNIQUEMENT avec ce JSON :
{{
  "commentaire_general": "2-3 phrases contexte macro HEXA.",
  "analyse_cycle": {{
    "France":          {{"regime": "Goldilocks|Surchauffe|Obligations|Stagflation", "commentaire": "1 phrase", "pib_estime": "X.X%", "cpi_estime": "X.X%"}},
    "Etats-Unis":      {{"regime": "...", "commentaire": "...", "pib_estime": "X.X%", "cpi_estime": "X.X%"}},
    "Zone Euro":       {{"regime": "...", "commentaire": "...", "pib_estime": "X.X%", "cpi_estime": "X.X%"}},
    "Chine":           {{"regime": "...", "commentaire": "...", "pib_estime": "X.X%", "cpi_estime": "X.X%"}},
    "Amerique latine": {{"regime": "...", "commentaire": "...", "pib_estime": "X.X%", "cpi_estime": "X.X%"}},
    "Asie ex-Chine":   {{"regime": "...", "commentaire": "...", "pib_estime": "X.X%", "cpi_estime": "X.X%"}}
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
    # On peut etre appele avec dynamic vide (toutes Passes plantees) :
    # dans ce cas on injecte uniquement des sources de repli explicites
    # pour eviter d'afficher des sources trompeuses.
    if dynamic is None:
        dynamic = {}

    # PMI (4 grandes zones + 2 nouvelles emergentes v6.5.2)
    if "pmi" in dynamic:
        for zone in ["france", "usa", "ez", "chine", "latam", "asie_ex_chine"]:
            if zone in dynamic["pmi"] and dynamic["pmi"][zone].get("val"):
                data["pmi"].setdefault(zone, {"val":"N/D","period":"N/D","prev":"N/D","source":"S&P Global (web_search)"})
                data["pmi"][zone].update(dynamic["pmi"][zone])

    # Zones emergentes v6.5.2 : PIB / CPI Latam et Asie ex-Chine + taux directeurs
    # Aucun fallback chiffre : si Claude n'a pas trouve, on garde N/D explicite
    if "emerging_zones" in dynamic:
        ez_data = dynamic["emerging_zones"]
        # Amerique latine
        latam = ez_data.get("latam", {})
        if latam.get("gdp_val"):
            data["gdp_latam"] = {
                "val":         _ensure_pct(latam["gdp_val"]),
                "period":      latam.get("gdp_period", "N/D"),
                "prev":        _ensure_pct(latam.get("gdp_prev", "N/D")),
                "prev_period": latam.get("gdp_prev_period", "N/D"),
                "n1":          "N/D", "n1_period": "N/D",
                "source":      latam.get("source", "FMI WEO (web_search)"),
            }
        if latam.get("cpi_val"):
            data["cpi_latam"] = {
                "val":         _ensure_pct(latam["cpi_val"]),
                "period":      latam.get("cpi_period", "N/D"),
                "prev":        _ensure_pct(latam.get("cpi_prev", "N/D")),
                "prev_period": latam.get("cpi_prev_period", "N/D"),
                "n1":          "N/D", "n1_period": "N/D",
                "source":      latam.get("source", "FMI WEO (web_search)"),
            }
        # Asie ex-Chine
        asie = ez_data.get("asie_ex_chine", {})
        if asie.get("gdp_val"):
            data["gdp_asie_ex_chine"] = {
                "val":         _ensure_pct(asie["gdp_val"]),
                "period":      asie.get("gdp_period", "N/D"),
                "prev":        _ensure_pct(asie.get("gdp_prev", "N/D")),
                "prev_period": asie.get("gdp_prev_period", "N/D"),
                "n1":          "N/D", "n1_period": "N/D",
                "source":      asie.get("source", "FMI WEO (web_search)"),
            }
        if asie.get("cpi_val"):
            data["cpi_asie_ex_chine"] = {
                "val":         _ensure_pct(asie["cpi_val"]),
                "period":      asie.get("cpi_period", "N/D"),
                "prev":        _ensure_pct(asie.get("cpi_prev", "N/D")),
                "prev_period": asie.get("cpi_prev_period", "N/D"),
                "n1":          "N/D", "n1_period": "N/D",
                "source":      asie.get("source", "FMI WEO (web_search)"),
            }
        # Taux directeurs emergents
        bcb = ez_data.get("bcb_selic", {})
        if bcb.get("val"):
            data["bcb_selic"] = {
                "val":    _ensure_pct(bcb["val"]),
                "prev":   _ensure_pct(bcb.get("prev", "N/D")),
                "detail": bcb.get("detail", "Taux Selic (Bresil)"),
                "source": bcb.get("source", "Banco Central do Brasil (web_search)"),
            }
        rbi = ez_data.get("rbi_repo", {})
        if rbi.get("val"):
            data["rbi_repo"] = {
                "val":    _ensure_pct(rbi["val"]),
                "prev":   _ensure_pct(rbi.get("prev", "N/D")),
                "detail": rbi.get("detail", "Repo Rate (Inde)"),
                "source": rbi.get("source", "RBI (web_search)"),
            }

    # CPI flash France / Zone Euro
    if "cpi_flash" in dynamic:
        cf = dynamic["cpi_flash"]
        if cf.get("france_val"):
            data["cpi_fr"].update({
                "val": _ensure_pct(cf["france_val"]),
                "period": cf.get("france_period", "N/D"),
                "prev": _ensure_pct(cf.get("france_prev", "N/D")),
                "source": cf.get("france_source", "INSEE flash"),
            })
        if cf.get("ez_val"):
            data["cpi_ez"].update({
                "val": _ensure_pct(cf["ez_val"]),
                "period": cf.get("ez_period", "N/D"),
                "prev": _ensure_pct(cf.get("ez_prev", "N/D")),
                "source": cf.get("ez_source", "Eurostat flash"),
            })

    # Chine - les PIB/CPI/taux PBoC s'affichent toujours avec %
    if "chine" in dynamic:
        c = dynamic["chine"]
        if c.get("pib_val"):
            data["gdp_chine"] = {
                "val": _ensure_pct(c.get("pib_val", "N/D")),
                "period": c.get("pib_period", "N/D"),
                "prev": _ensure_pct(c.get("pib_prev", "N/D")),
                "prev_period": c.get("pib_prev_period", "N/D"),
                "n1": "N/D", "n1_period": "N/D",
                "source": "NBS via web_search",
            }
        if c.get("cpi_val"):
            data["cpi_chine"] = {
                "val": _ensure_pct(c.get("cpi_val", "N/D")),
                "period": c.get("cpi_period", "N/D"),
                "prev": _ensure_pct(c.get("cpi_prev", "N/D")),
                "prev_period": c.get("cpi_prev_period", "N/D"),
                "n1": "N/D", "n1_period": "N/D",
                "source": "NBS via web_search",
            }
        if c.get("pboc_val"):
            data["pboc"] = {
                "val":    _ensure_pct(c.get("pboc_val", "N/D")),
                "prev":   _ensure_pct(c.get("pboc_prev", "N/D")),
                "detail": c.get("pboc_detail", "LPR 1 an"),
                "source": "PBoC via web_search",
            }

    # Fallback PIB France/USA/Zone Euro (si APIs officielles ont echoue)
    gdp_fb = dynamic.get("gdp_fallback", {})
    gdp_map = {"france": "gdp_fr", "usa": "gdp_usa", "zone_euro": "gdp_ez"}
    for src_key, target_key in gdp_map.items():
        entry = gdp_fb.get(src_key, {})
        if entry.get("val") and data.get(target_key, {}).get("val", "N/D") == "N/D":
            data[target_key] = {
                "val":  _ensure_pct(entry["val"]),
                "period": entry.get("period", "N/D"),
                "prev": _ensure_pct(entry.get("prev", "N/D")),
                "prev_period": entry.get("prev_period", "N/D"),
                "n1": "N/D", "n1_period": "N/D",
                "source": f"{'Eurostat' if src_key!='usa' else 'BEA'} via web_search",
            }

    # Fallback Fed rate
    fed_fb = dynamic.get("fed_fallback", {})
    if fed_fb.get("val") and data.get("fed_rate", {}).get("val", "N/D") == "N/D":
        data["fed_rate"] = {
            "val": _ensure_pct(fed_fb["val"]), "period": "courant",
            "prev": _ensure_pct(fed_fb.get("prev", "N/D")),
            "prev_period": fed_fb.get("prev_period", "N/D"),
            "n1": "N/D", "n1_period": "N/D",
            "source": fed_fb.get("source") or "Fed via web_search",
        }

    # Fallback Euribor
    eur_fb = dynamic.get("euribor_fallback", {})
    if eur_fb.get("val") and data.get("euribor", {}).get("val", "N/D") == "N/D":
        data["euribor"] = {
            "val":  _ensure_pct(eur_fb["val"]),         "date":      eur_fb.get("date", "N/D"),
            "prev": _ensure_pct(eur_fb.get("prev","N/D")),"prev_date": eur_fb.get("prev_date", "N/D"),
            "n1":   _ensure_pct(eur_fb.get("n1","N/D")), "n1_date":   eur_fb.get("n1_date", "N/D"),
            "source": "ECB SDW (Euribor 3M, web_search)",
        }

    # Immo taux
    if "immo_taux" in dynamic and dynamic["immo_taux"].get("taux_20ans"):
        it = dynamic["immo_taux"]
        data["immobilier_taux"].update({k: v for k, v in it.items() if v})
    # Pas de fallback chiffre : si Claude n'a rien renvoye, on garde N/D et on clarifie
    # juste la source pour que le lecteur comprenne pourquoi la donnee manque.
    it_data = data.get("immobilier_taux", {})
    if not it_data.get("taux_20ans") or it_data.get("taux_20ans") == "N/D":
        data["immobilier_taux"]["taux_20ans_commentaire"] = "CAFPI - donnee non collectee ce mois."
    if not it_data.get("bureaux_val") or it_data.get("bureaux_val") == "N/D":
        data["immobilier_taux"]["bureaux_commentaire"] = "JLL/CBRE - donnee trimestrielle non collectee."
    if not it_data.get("commerces_val") or it_data.get("commerces_val") == "N/D":
        data["immobilier_taux"]["commerces_commentaire"] = "JLL/CBRE - taux prime non publie ce mois."

    # Prix immo par ville
    if "immo_prix" in dynamic:
        valid = {k: v for k, v in dynamic["immo_prix"].items() if v.get("val", 0) > 0}
        if valid:
            data["immo_prix"] = valid

    # Fallback : si aucun prix immo n'a ete recolte, on injecte les dernieres valeurs
    # de reference (estimation MeilleursAgents) pour eviter une Section 10 vide.
    # Prix immo par ville : pas de fallback chiffre (eviter biais d'analyse).
    # Si Claude n'a rien collecte, immo_prix reste vide et le PDF affichera
    # uniquement l'entete de la Section 10.

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
                val = str(d.get("val", "N/D")).strip()
                # Pour rdt : si la valeur contient un "/", on garde le premier nombre uniquement
                # (ex: "5.4% (moy) / 6.0% (evergreen)" -> "5.4%" et detail dans var)
                if key == "rdt" and "/" in val:
                    import re
                    m = re.search(r"([\d.,]+%?)", val)
                    if m:
                        val = m.group(1) if m.group(1).endswith("%") else m.group(1) + "%"
                pe[key] = (val, d.get("var", ""), d.get("periode", ""))
    if "dry_powder" in dynamic and dynamic["dry_powder"].get("val"):
        dp = dynamic["dry_powder"]
        val = str(dp.get("val", "N/D")).strip()
        # Si la valeur contient "/", garder la premiere partie (ex: "3.7 T$ (PE) / 1.3 T$ (Buyout)")
        if "/" in val:
            val = val.split("/")[0].strip()
        # S'assurer du suffixe Md$/T$ implicite : si juste un nombre, ajouter "T$"
        if val and val[-1].isdigit():
            val = val + " T$"
        pe["dp"] = (val, dp.get("var", ""), dp.get("periode", ""))

    # Pas de fallback chiffre pour les indicateurs PE : si Claude n'a rien collecte,
    # les valeurs restent N/D (initialisees par dashboard.py). Cela evite tout biais
    # d'analyse base sur des estimations approximatives.

    # Spread OAT/Bund - on enleve toute unite parasite (Claude tend a renvoyer "69 bps")
    if "spread_oat_bund" in dynamic and dynamic["spread_oat_bund"].get("oat"):
        sp = dynamic["spread_oat_bund"]
        data["spread"] = {
            "spread":      _strip_unit(sp.get("spread", "N/D")),
            "spread_prev": _strip_unit(sp.get("spread_prev", "N/D")),
            "oat":         _ensure_pct(sp.get("oat", "N/D")),
            "bund":        _ensure_pct(sp.get("bund", "N/D")),
            "source":      sp.get("source", "web_search"),
        }

    # Credit spreads (uniquement si FRED a echoue) - meme normalisation
    if "credit_spreads" in dynamic and dynamic["credit_spreads"].get("ig_spread"):
        cs = dynamic["credit_spreads"]
        if data.get("credit_spreads", {}).get("ig_spread", "N/D") == "N/D":
            data["credit_spreads"].update({
                "ig_spread":      _strip_unit(cs.get("ig_spread", "N/D")),
                "ig_spread_prev": _strip_unit(cs.get("ig_spread_prev", "N/D")),
                "ig_spread_n1":   _strip_unit(cs.get("ig_spread_n1", "N/D")),
                "hy_spread":      _strip_unit(cs.get("hy_spread", "N/D")),
                "hy_spread_prev": _strip_unit(cs.get("hy_spread_prev", "N/D")),
                "hy_spread_n1":   _strip_unit(cs.get("hy_spread_n1", "N/D")),
                "source":         cs.get("source", "web_search"),
            })

    # Courbe US 2/10 ans (uniquement si Yahoo a echoue)
    if "spread_us_curve" in dynamic and dynamic["spread_us_curve"].get("spread"):
        uc = dynamic["spread_us_curve"]
        if data.get("spread_us_curve", {}).get("spread", "N/D") == "N/D":
            data["spread_us_curve"].update({
                "us_2y":       _ensure_pct(uc.get("us_2y", "N/D")),
                "us_10y":      _ensure_pct(uc.get("us_10y", "N/D")),
                "spread":      _strip_unit(uc.get("spread", "N/D")),
                "spread_prev": _strip_unit(uc.get("spread_prev", "N/D")),
                "signal":      uc.get("signal", "N/D"),
                "source":      uc.get("source", "web_search"),
            })

    # Pas de fallback chiffre sur les spreads OAT/Bund, IG, HY : si ni l'API FRED ni
    # web_search n'ont rien collecte, on garde N/D explicite plutot que d'introduire
    # un biais avec des estimations approximatives.
    if data.get("spread", {}).get("spread", "N/D") == "N/D":
        data["spread"]["source"] = "Banque de France / Bundesbank - donnee non collectee."
    if data.get("credit_spreads", {}).get("ig_spread", "N/D") == "N/D":
        data["credit_spreads"]["source"] = "FRED BAMLC0A0CM / BAMLH0A0HYM2 - donnee non collectee."

    # SCPI
    if "scpi" in dynamic and dynamic["scpi"].get("marche", {}).get("td_moyen"):
        data["scpi"].update(dynamic["scpi"])
    # Pas de fallback chiffre SCPI. Si la Passe 3 a echoue, Section 13 reste avec
    # uniquement les en-tetes et un message clair dans la source.
    scpi = data.get("scpi", {})
    if scpi.get("marche", {}).get("td_moyen", "N/D") == "N/D":
        scpi.setdefault("marche", {})["source"] = "ASPIM / MeilleuresSCPI - donnee non collectee."


def _diagnostic_log(data: dict):
    """
    Diagnostic post-injection : affiche les champs critiques pour reperer rapidement
    une passe web_search defaillante. Visible dans les logs GitHub Actions.
    """
    print("  --- Diagnostic post-injection ---")
    critical = {
        "PIB Latam (P1)":         data.get("gdp_latam", {}).get("val", "N/D"),
        "PIB Asie ex-Chine (P1)": data.get("gdp_asie_ex_chine", {}).get("val", "N/D"),
        "BCB Selic Bresil (P1)":  data.get("bcb_selic", {}).get("val", "N/D"),
        "RBI Repo Inde (P1)":     data.get("rbi_repo", {}).get("val", "N/D"),
        "Spread OAT/Bund (P2)":   data.get("spread", {}).get("spread", "N/D"),
        "Spread IG (P2)":         data.get("credit_spreads", {}).get("ig_spread", "N/D"),
        "Spread HY (P2)":         data.get("credit_spreads", {}).get("hy_spread", "N/D"),
        "Argos Mid-Market (P2)":  data.get("private_equity", {}).get("argos", ("N/D",))[0],
        "Dry Powder (P2)":        data.get("private_equity", {}).get("dp", ("N/D",))[0],
        "Levees PE (P2)":         data.get("private_equity", {}).get("levees", ("N/D",))[0],
        "Taux 20 ans (P3)":       data.get("immobilier_taux", {}).get("taux_20ans", "N/D"),
        "Bureaux IDF (P3)":       data.get("immobilier_taux", {}).get("bureaux_val", "N/D"),
        "Prix immo (P3)":         f"{len(data.get('immo_prix', {}))} villes",
        "SCPI TD moyen (P3)":     data.get("scpi", {}).get("marche", {}).get("td_moyen", "N/D"),
        "SCPI top 10 (P3)":       f"{len(data.get('scpi', {}).get('scpi_top10', []))} SCPI",
    }
    nd_count = 0
    for k, v in critical.items():
        marker = " [N/D]" if v in ("N/D", "0 villes", "0 SCPI") else ""
        if marker:
            nd_count += 1
        print(f"    {k}: {v}{marker}")
    if nd_count >= 5:
        print(f"  [WARN] {nd_count}/{len(critical)} indicateurs en N/D : verifier les passes web_search.")
    print("  ---------------------------------")


def _final_format_sweep(data: dict):
    """
    Filet de securite final avant generation PDF :
    garantit que tous les champs PIB / CPI / taux directeurs portent bien le symbole %.
    Couvre les cas ou une source (API ou web_search) renvoie un nombre nu comme "0.0".
    """
    # PIB : val, prev, n1 pour chaque zone (incluant zones emergentes v6.5.2)
    for key in ("gdp_fr", "gdp_usa", "gdp_ez", "gdp_chine", "gdp_emergents",
                "gdp_latam", "gdp_asie_ex_chine"):
        d = data.get(key)
        if isinstance(d, dict):
            for fld in ("val", "prev", "n1"):
                if fld in d:
                    d[fld] = _ensure_pct(d[fld])
    # CPI : val, prev, n1 pour chaque zone (incluant zones emergentes v6.5.2)
    for key in ("cpi_fr", "cpi_usa", "cpi_ez", "cpi_chine",
                "cpi_latam", "cpi_asie_ex_chine"):
        d = data.get(key)
        if isinstance(d, dict):
            for fld in ("val", "prev", "n1"):
                if fld in d:
                    d[fld] = _ensure_pct(d[fld])
    # Taux directeurs : ECB, Fed, PBoC, Euribor + BCB Selic, RBI Repo v6.5.2
    for key in ("ecb_rate", "fed_rate", "pboc", "euribor", "bcb_selic", "rbi_repo"):
        d = data.get(key)
        if isinstance(d, dict):
            for fld in ("val", "prev", "n1"):
                if fld in d:
                    d[fld] = _ensure_pct(d[fld])


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
        # Filet de securite : garantit que tous les % sont presents avant analyse
        _final_format_sweep(data)

        # Diagnostic : recap des donnees critiques apres injection
        _diagnostic_log(data)

        # Pause avant analyse
        print(f"  Pause {PAUSE}s avant analyse...")
        time.sleep(PAUSE)

        # Analyse
        print("  Analyse Claude...")
        text = call_simple(client, build_analysis_prompt(data, mois))
        analysis = extract_json(text)
        # Normalisation : pib_estime / cpi_estime doivent porter %
        for zone, info in analysis.get("analyse_cycle", {}).items():
            if isinstance(info, dict):
                if "pib_estime" in info:
                    info["pib_estime"] = _ensure_pct(info["pib_estime"])
                if "cpi_estime" in info:
                    info["cpi_estime"] = _ensure_pct(info["cpi_estime"])
        print("  Analyse OK")
        return analysis, dynamic

    except Exception as e:
        print(f"  Erreur Claude: {e}")
        _final_format_sweep(data)  # On normalise aussi en cas d'erreur Claude
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
