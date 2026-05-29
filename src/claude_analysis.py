"""
HEXA Patrimoine - Analyse Claude v7.0
======================================
UN SEUL appel Claude qui :
1. Recupere via web_search les donnees SANS API :
   - PMI Composite 6 zones (France, ZE, USA, Chine, Bresil, Inde)
   - Taux directeurs : PBoC, BCB Selic, RBI Repo
   - Argos Mid-Market multiple
   - France Invest stats (levees, invest, cessions, nb entreprises)
   - Dry Powder mondial et rendement PE
   - Taux immo 20 ans + Bureaux IDF + Surfaces commerciales prime
   - Prix immo m2 dans 8 villes
   - Top 10 SCPI par collecte + analyse marche

2. Produit l'analyse macro complete :
   - Commentaire general
   - Cycle economique 6 zones (regimes Goldilocks/Surchauffe/Obligations/Stagflation)
   - Points de vigilance + Opportunites
   - Allocation par classe d'actif (7 classes)
   - Syntheses immo, PE, SCPI

Architecture v7.0 :
  - 1 SEUL appel Claude avec web_search
  - Prompt cible et raisonnable (~30K tokens initiaux)
  - max_tokens=8000 pour absorber la reponse longue
  - Garde-fou contexte 720K chars pour eviter le crash 200K tokens
"""
import os
import json
import re
import sys
import time
from typing import Dict, Any, Optional

import anthropic


MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
# v7.0 : un seul appel, donc on peut etre genereux sur les iterations
MAX_SEARCH_ITERATIONS = int(os.environ.get("CLAUDE_MAX_ITER", "15"))
# Garde-fou contexte (~180K tokens)
MAX_CONTEXT_CHARS = int(os.environ.get("CLAUDE_MAX_CONTEXT_CHARS", "720000"))


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _ensure_pct(s: Any) -> str:
    """Ajoute '%' si absent sur une valeur numerique nue, idempotent."""
    if s is None or s == "":
        return "N/D"
    s = str(s).strip()
    if not s or s.upper() == "N/D":
        return "N/D"
    # Si la chaine se termine deja par % ou bps ou pb, on garde
    if s.endswith("%") or s.lower().endswith(("bps", "pb")):
        return s
    # Si c'est un nombre nu, ajouter %
    try:
        float(s.replace(",", ".").replace("+", "").rstrip("xX"))
        return s + "%" if not s.endswith("%") else s
    except ValueError:
        return s


def extract_json(text: str) -> dict:
    """Extrait le premier bloc JSON valide d'une reponse Claude."""
    if not text or not text.strip():
        raise ValueError("reponse vide")
    text = text.strip()
    # Cas ```json ... ```
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
    # Cas brut : trouver le premier {
    if not text.startswith("{"):
        first = text.find("{")
        if first >= 0:
            text = text[first:]
    # Tentative directe
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tentative de reparation : tronquer au dernier } valide
        for i in range(len(text), 0, -1):
            try:
                return json.loads(text[:i])
            except json.JSONDecodeError:
                continue
        raise ValueError(f"JSON irreparable. Debut : {text[:200]}")


def _concat_text(response) -> str:
    """Concatene tous les blocs texte d'une reponse (le JSON peut etre
    fragmente sur plusieurs blocs quand des recherches sont intercalees)."""
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text" and getattr(block, "text", ""):
            parts.append(block.text)
    return "".join(parts)


def call_with_search(client, prompt: str, max_tokens: int = 8000) -> str:
    """Un seul appel a l'API. web_search est un outil SERVER-SIDE : l'API
    execute elle-meme les recherches et reinjecte les resultats sans qu'on
    ait a gerer la boucle tool_use/tool_result cote client.

    max_uses borne le nombre de recherches (contexte + cout).
    """
    tools = [{
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": MAX_SEARCH_ITERATIONS,
    }]
    messages = [{"role": "user", "content": prompt}]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            tools=tools,
            messages=messages,
        )
    except anthropic.BadRequestError as e:
        print(f"  [WARN] BadRequestError : {e}", flush=True)
        return ""

    text = _concat_text(response)

    if response.stop_reason == "max_tokens":
        print(f"  [WARN] max_tokens atteint. Texte recupere : {len(text)} chars.", flush=True)
    elif response.stop_reason not in ("end_turn", "max_tokens"):
        print(f"  [WARN] stop_reason inattendu : {response.stop_reason}. "
              f"Texte recupere : {len(text)} chars.", flush=True)

    return text


# ──────────────────────────────────────────────────────────────────────────
# Construction du prompt unique
# ──────────────────────────────────────────────────────────────────────────

def _summary_apis(data: Dict[str, Any]) -> str:
    """Resume textuel des donnees deja recuperees via APIs, injecte dans le prompt
    pour eviter que Claude re-cherche ce qu'on a deja."""
    def gv(d, k="val"):
        return d.get(k, "N/D") if isinstance(d, dict) else "N/D"

    lignes = [
        "DONNEES DEJA RECUPEREES VIA APIs (ne pas chercher) :",
        "",
        "PIB (croissance a/a) :",
        f"  - France     : {gv(data.get('gdp_fr'))} ({gv(data.get('gdp_fr'), 'period')})",
        f"  - Zone Euro  : {gv(data.get('gdp_ez'))} ({gv(data.get('gdp_ez'), 'period')})",
        f"  - Etats-Unis : {gv(data.get('gdp_usa'))} ({gv(data.get('gdp_usa'), 'period')})",
        f"  - Chine      : {gv(data.get('gdp_chine'))} ({gv(data.get('gdp_chine'), 'period')})",
        f"  - Bresil     : {gv(data.get('gdp_bresil'))} ({gv(data.get('gdp_bresil'), 'period')})",
        f"  - Inde       : {gv(data.get('gdp_inde'))} ({gv(data.get('gdp_inde'), 'period')})",
        "",
        "Inflation (CPI a/a) :",
        f"  - France     : {gv(data.get('cpi_fr'))} ({gv(data.get('cpi_fr'), 'period')})",
        f"  - Zone Euro  : {gv(data.get('cpi_ez'))} ({gv(data.get('cpi_ez'), 'period')})",
        f"  - Etats-Unis : {gv(data.get('cpi_usa'))} ({gv(data.get('cpi_usa'), 'period')})",
        f"  - Chine      : {gv(data.get('cpi_chine'))} ({gv(data.get('cpi_chine'), 'period')})",
        f"  - Bresil     : {gv(data.get('cpi_bresil'))} ({gv(data.get('cpi_bresil'), 'period')})",
        f"  - Inde       : {gv(data.get('cpi_inde'))} ({gv(data.get('cpi_inde'), 'period')})",
        "",
        "Taux directeurs :",
        f"  - BCE        : {gv(data.get('ecb_rate'))}",
        f"  - Fed        : {gv(data.get('fed_rate'))}",
        "",
        "Marche :",
        f"  - VIX        : {gv(data.get('vix'))}",
        f"  - Fear&Greed : {gv(data.get('fg'))} ({gv(data.get('fg'), 'label')})",
        f"  - Spread OAT/Bund : {data.get('spread', {}).get('spread', 'N/D')} bps",
        f"  - IG spread  : {data.get('credit_spreads', {}).get('ig_spread', 'N/D')} bps",
        f"  - HY spread  : {data.get('credit_spreads', {}).get('hy_spread', 'N/D')} bps",
        f"  - NFP        : {gv(data.get('nfp'))}",
        f"  - Chomage US : {gv(data.get('unemployment_usa'))}",
    ]
    return "\n".join(lignes)


def build_prompt(data: Dict[str, Any]) -> str:
    """Construit l'unique prompt v7.0.
    Objectif : prompt initial ~25-35K tokens, bien sous les 200K."""
    mois = data.get("date", "ce mois")
    annee = 2026
    try:
        annee = int(data["collected_at"][:4])
    except Exception:
        pass

    apis_summary = _summary_apis(data)

    # On demande UNIQUEMENT ce qui n'est pas dans les APIs
    return f"""Tu es analyste senior chez HEXA Patrimoine, cabinet de gestion patrimoniale.
Date du rapport : {mois}.

{apis_summary}

TA MISSION
==========
Recupere via web_search les donnees manquantes, puis produis une analyse macroeconomique
complete. Tout doit etre dans UN SEUL bloc JSON en sortie.

DONNEES A RECUPERER VIA WEB_SEARCH
==================================
0. PIB et inflation des pays emergents (donnees OFFICIELLES les plus recentes), car
   les APIs structurees sont trop retardees pour ces pays :
   - Chine : croissance PIB a/a (dernier trimestre, NBS) + CPI a/a (dernier mois, NBS).
   - Bresil : croissance PIB a/a (dernier trimestre, IBGE) + IPCA a/a (dernier mois, IBGE).
   - Inde : croissance PIB a/a (dernier trimestre, MoSPI) + CPI a/a (dernier mois, MoSPI).
   Format : pourcentage avec signe pour le PIB (ex "+5.4%"), avec periode (ex "T1 2026"
   pour le PIB, "Avr 2026" pour le CPI). Ces valeurs DOIVENT etre coherentes avec celles
   que tu reutiliseras dans claude_cycle (section 14).

1. PMI Composite {mois} pour 6 zones (S&P Global / HCOB / Caixin) :
   France, Zone Euro, Etats-Unis, Chine, Bresil, Inde.
   Format : nombre seul (ex "48.9"), periode = mois (ex "Mai 2026").
   IMPORTANT : ne JAMAIS laisser un PMI vide. Si tu ne trouves pas le mois exact,
   prends le mois disponible le plus recent et indique-le dans "period".

2. Taux directeurs des banques centrales emergentes (decision la plus recente) :
   - PBoC (Chine) : LPR 1 an. Source : PBoC.
   - BCB Selic (Bresil) : decision COPOM la plus recente. Source : Banco Central do Brasil.
   - RBI Repo (Inde) : decision MPC la plus recente. Source : Reserve Bank of India.

3. Argos Mid-Market Index (multiple EV/EBITDA T1 {annee}). Source : Argos Wityu.

4. France Invest statistiques annuelles {annee-1} :
   - Levees de fonds (Md€, variation % vs annee precedente)
   - Montants investis (Md€)
   - Cessions / desinvestissements (Md€)
   - Nombre d'entreprises en portefeuille
   Source : France Invest activite annuelle.

5. Dry Powder PE mondial (Bain Global PE Report ou Preqin).

6. Rendement net annuel PE France 10 ans (France Invest).

7. Taux credit immobilier 20 ans en France {mois}. Source : CAFPI/Empruntis.

8. Taux de vacance des bureaux en Ile-de-France (JLL/CBRE dernier trimestre).

9. Taux prime des surfaces commerciales France (JLL/CBRE).

10. Prix median m2 dans ces 8 villes (DVF/MeilleursAgents) :
    Paris, Lyon, Tassin-la-Demi-Lune, Saint-Foy-les-Lyon,
    Maisons-Laffitte, Le Vesinet, Chatou, Saint-Germain-en-Laye.
    Pour chaque : prix actuel €/m2, variation 1 an %, variation 5 ans %.
    IMPORTANT : remplis ces 8 villes meme avec une estimation MeilleursAgents/SeLoger
    recente ; ne laisse PAS cette section vide. Si une ville precise manque, utilise
    la donnee de prix au m2 la plus recente disponible pour cette commune.

11. SCPI marche France {annee} :
    - TD moyen marche (% annuel)
    - Collecte nette {annee} (Md€)
    - Decote secondaire (% ex: "-20% a -30%", PAS le montant des parts en attente)
    - TOF moyen (%)
    - Par secteur (Bureaux/Commerce/Sante/Logistique/Diversifie) : poids %, TD %, tendance (haut/bas/stable), 1 commentaire court
    - Source : ASPIM/IEIF.

12. Top 10 SCPI par collecte nette {annee} (ASPIM classement) :
    nom, gestionnaire, secteur, collecte (M€), TD (%), TOF (%), prix part (€), variation prix (%), 1 note courte.

ANALYSE MACRO A PRODUIRE
========================
13. Commentaire general (2-3 phrases) sur la conjoncture {mois}.

14. Cycle economique pour les 6 zones (France, Etats-Unis, Zone Euro, Chine, Bresil, Inde) :
    Pour chaque zone, choisir un regime parmi :
      - Goldilocks (croissance haute + inflation basse) -> Actions
      - Surchauffe (croissance haute + inflation haute) -> Mat. premieres, immo, value
      - Obligations d'Etat (croissance basse + inflation basse) -> Duration, souveraines
      - Stagflation (croissance basse + inflation haute) -> Or, OATi, cash
    Seuils indicatifs : croissance haute >1.5%, inflation haute >2.5%.
    Inclure : regime, commentaire (1-2 phrases), pib_estime (avec %), cpi_estime (avec %).

15. Points de vigilance (3 bullets, ~15 mots chacun) sur les risques actuels.

16. Opportunites identifiees (3 bullets) sur les opportunites d'investissement.

17. Allocation recommandee par classe d'actif (1 phrase par classe) :
    actions, obligations, matieres_premieres, immobilier, cash_monetaire, private_equity, scpi.

18. Synthese immobilier (2 phrases sur le marche immo francais).
19. Synthese private equity (2 phrases sur le PE).
20. Synthese SCPI (analyse marche SCPI, 2-3 phrases, sera aussi mise dans scpi.analyse).

FORMAT DE SORTIE
================
Reponds UNIQUEMENT avec ce JSON unique (pas de texte avant ou apres) :

{{
  "emergents": {{
    "gdp_chine":  {{"val":"","period":"","source":"NBS"}},
    "gdp_bresil": {{"val":"","period":"","source":"IBGE"}},
    "gdp_inde":   {{"val":"","period":"","source":"MoSPI"}},
    "cpi_chine":  {{"val":"","period":"","source":"NBS"}},
    "cpi_bresil": {{"val":"","period":"","source":"IBGE"}},
    "cpi_inde":   {{"val":"","period":"","source":"MoSPI"}}
  }},
  "pmi": {{
    "france": {{"val":"","period":"","prev":"","source":""}},
    "ez":     {{"val":"","period":"","prev":"","source":""}},
    "usa":    {{"val":"","period":"","prev":"","source":""}},
    "chine":  {{"val":"","period":"","prev":"","source":""}},
    "bresil": {{"val":"","period":"","prev":"","source":""}},
    "inde":   {{"val":"","period":"","prev":"","source":""}}
  }},
  "pboc":      {{"val":"","prev":"","detail":"LPR 1 an","source":"PBoC"}},
  "bcb_selic": {{"val":"","prev":"","detail":"Taux Selic, decision COPOM ...","source":"BCB"}},
  "rbi_repo":  {{"val":"","prev":"","detail":"Repo Rate, decision MPC ...","source":"RBI"}},
  "argos": {{"val":"","prev":"","prev_periode":"","n1":"","n1_periode":""}},
  "france_invest": {{
    "levees":   {{"val":"","var":"+/-X%","periode":""}},
    "invest":   {{"val":"","var":"","periode":""}},
    "cessions": {{"val":"","var":"","periode":""}},
    "nb_ent":   {{"val":""}}
  }},
  "dry_powder": {{"val":"","var":"","commentaire":""}},
  "rdt_pe":     {{"val":"","commentaire":""}},
  "taux_immo":  {{"val":"","prev":"","n1":"","commentaire":""}},
  "bureaux_idf": {{"val":"","prev":"","n1":"","commentaire":""}},
  "commerces":  {{"val":"","prev":"","n1":"","commentaire":""}},
  "immo_prix": {{
    "Paris":                  {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Lyon":                   {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Tassin-la-Demi-Lune":    {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Saint-Foy-les-Lyon":     {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Maisons-Laffitte":       {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Le Vesinet":             {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Chatou":                 {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}},
    "Saint-Germain-en-Laye":  {{"val":0,"var_1an":0,"var_5ans":0,"periode":"","source":"DVF/MeilleursAgents"}}
  }},
  "scpi": {{
    "marche": {{
      "td_moyen":"","td_moyen_prev":"","td_moyen_n1":"",
      "collecte_nette":"","collecte_prev":"","collecte_periode":"",
      "decote_secondaire":"-X% a -Y%","decote_prev":"",
      "tof_moyen":"","source":"ASPIM/IEIF"
    }},
    "par_secteur": [
      {{"secteur":"Bureaux","poids":"","td":"","tendance":"haut|bas|stable","commentaire":""}},
      {{"secteur":"Commerce","poids":"","td":"","tendance":"","commentaire":""}},
      {{"secteur":"Sante","poids":"","td":"","tendance":"","commentaire":""}},
      {{"secteur":"Logistique","poids":"","td":"","tendance":"","commentaire":""}},
      {{"secteur":"Diversifie","poids":"","td":"","tendance":"","commentaire":""}}
    ],
    "scpi_top10": [
      {{"nom":"","gestionnaire":"","secteur":"","collecte":"","td":"","tof":"","prix_part":"","var_prix":"","note":""}}
    ],
    "analyse":"",
    "points_vigilance":["","",""],
    "opportunites":["","",""]
  }},
  "commentaire_general":"",
  "claude_cycle": {{
    "France":      {{"regime":"","commentaire":"","pib_estime":"X%","cpi_estime":"X%"}},
    "Etats-Unis":  {{"regime":"","commentaire":"","pib_estime":"","cpi_estime":""}},
    "Zone Euro":   {{"regime":"","commentaire":"","pib_estime":"","cpi_estime":""}},
    "Chine":       {{"regime":"","commentaire":"","pib_estime":"","cpi_estime":""}},
    "Bresil":      {{"regime":"","commentaire":"","pib_estime":"","cpi_estime":""}},
    "Inde":        {{"regime":"","commentaire":"","pib_estime":"","cpi_estime":""}}
  }},
  "claude_vigilance": ["","",""],
  "claude_opportunites": ["","",""],
  "claude_allocation": {{
    "actions":"","obligations":"","matieres_premieres":"","immobilier":"",
    "cash_monetaire":"","private_equity":"","scpi":""
  }},
  "claude_synthese_immo":"",
  "claude_synthese_pe":"",
  "claude_synthese_scpi":""
}}

REGLES DE FORMAT
================
- PIB, CPI, TD, taux : TOUJOURS avec le symbole "%" (ex: "0.3%", "+5.0%").
- PMI : nombre seul SANS %.
- Spreads : nombre seul SANS bps (juste "69").
- Decote secondaire : EN POURCENTAGE (ex: "-20% a -30%").
- scpi_top10 : exactement 10 SCPI, classees par collecte decroissante.
- COHERENCE OBLIGATOIRE : dans claude_cycle, "pib_estime" et "cpi_estime" de chaque zone
  DOIVENT reprendre exactement les valeurs PIB/CPI affichees ailleurs dans le rapport :
  France/Zone Euro/USA depuis les donnees API fournies en haut de ce prompt ;
  Chine/Bresil/Inde depuis le bloc "emergents" que tu viens de remplir.
  N'invente JAMAIS un chiffre d'inflation ou de croissance different dans les commentaires.
- Le "regime" de chaque zone doit etre coherent avec ces deux chiffres et les seuils donnes.
- Si une donnee est INTROUVABLE apres recherche, mets val="" (vide). Le PDF affichera N/D.
- AUCUNE valeur inventee : si tu ne trouves pas, vide. EXCEPTION : PMI et prix immo,
  pour lesquels tu prends la donnee recente la plus proche plutot que de laisser vide.
- Reponds en francais.
"""


# ──────────────────────────────────────────────────────────────────────────
# Injection des donnees Claude dans la structure data
# ──────────────────────────────────────────────────────────────────────────

def _inject_into_data(data: Dict[str, Any], parsed: Dict[str, Any]) -> None:
    """Injecte le JSON produit par Claude dans la structure data attendue par le PDF."""

    # PIB / CPI pays emergents : web_search (recent) prioritaire sur l'API (retardee).
    # On ne remplace que si Claude a fourni une valeur ET que l'API est vide/retardee.
    if "emergents" in parsed:
        em = parsed["emergents"]
        _mapping = {
            "gdp_chine": "gdp_chine", "gdp_bresil": "gdp_bresil", "gdp_inde": "gdp_inde",
            "cpi_chine": "cpi_chine", "cpi_bresil": "cpi_bresil", "cpi_inde": "cpi_inde",
        }
        for src_key, data_key in _mapping.items():
            block = em.get(src_key, {})
            val = (block.get("val") or "").strip()
            if not val:
                continue
            api_block = data.get(data_key, {}) or {}
            api_src = str(api_block.get("source", ""))
            api_period = str(api_block.get("period", ""))
            api_val = str(api_block.get("val", ""))
            # On prefere web_search si l'API a echoue (N/D), vient de la Banque Mondiale
            # (annuelle/retardee), ou n'a pas de periode trimestrielle/mensuelle 2026.
            api_is_stale = (
                api_val in ("", "N/D")
                or "Banque Mondiale" in api_src
                or "2024" in api_period or "2025" in api_period
            )
            if api_is_stale:
                data[data_key] = {
                    "val": _ensure_pct(val),
                    "period": block.get("period", "N/D"),
                    "prev": api_block.get("prev", "N/D"),
                    "prev_period": api_block.get("prev_period", "N/D"),
                    "n1": api_block.get("n1", "N/D"),
                    "n1_period": api_block.get("n1_period", "N/D"),
                    "source": block.get("source", "Source nationale (web)"),
                }

    # PMI
    if "pmi" in parsed:
        for zone in ("france", "ez", "usa", "chine", "bresil", "inde"):
            if zone in parsed["pmi"]:
                p = parsed["pmi"][zone]
                if p.get("val"):
                    data["pmi"][zone] = {
                        "val": p.get("val", "N/D"),
                        "period": p.get("period", "N/D"),
                        "prev": p.get("prev", "N/D"),
                        "source": p.get("source", "S&P Global PMI"),
                    }

    # Taux directeurs emergents
    for tk in ("pboc", "bcb_selic", "rbi_repo"):
        if tk in parsed and parsed[tk].get("val"):
            d = parsed[tk]
            data[tk] = {
                "val": _ensure_pct(d.get("val", "N/D")),
                "prev": _ensure_pct(d.get("prev", "N/D")),
                "detail": d.get("detail", data.get(tk, {}).get("detail", "")),
                "source": d.get("source", data.get(tk, {}).get("source", "")),
            }

    # Argos Mid-Market
    if "argos" in parsed and parsed["argos"].get("val"):
        a = parsed["argos"]
        data["private_equity"]["argos"] = (
            a.get("val", "N/D"),
            a.get("prev", "N/D"),
            a.get("prev_periode", "N/D"),
            a.get("n1", "N/D"),
            a.get("n1_periode", "N/D"),
        )

    # France Invest
    if "france_invest" in parsed:
        fi = parsed["france_invest"]
        if fi.get("levees", {}).get("val"):
            data["private_equity"]["levees"] = (
                fi["levees"].get("val", "N/D"),
                fi["levees"].get("var", ""),
                fi["levees"].get("periode", ""),
            )
        if fi.get("invest", {}).get("val"):
            data["private_equity"]["invest"] = (
                fi["invest"].get("val", "N/D"),
                fi["invest"].get("var", ""),
                fi["invest"].get("periode", ""),
            )
        if fi.get("cessions", {}).get("val"):
            data["private_equity"]["cessions"] = (
                fi["cessions"].get("val", "N/D"),
                fi["cessions"].get("var", ""),
                fi["cessions"].get("periode", ""),
            )
        if fi.get("nb_ent", {}).get("val"):
            data["private_equity"]["nb_ent"] = (
                fi["nb_ent"].get("val", "N/D"), "", "",
            )

    # Dry Powder + Rendement PE
    if "dry_powder" in parsed and parsed["dry_powder"].get("val"):
        dp = parsed["dry_powder"]
        data["private_equity"]["dp"] = (
            dp.get("val", "N/D"),
            dp.get("var", ""),
            dp.get("commentaire", ""),
        )
    if "rdt_pe" in parsed and parsed["rdt_pe"].get("val"):
        r = parsed["rdt_pe"]
        data["private_equity"]["rdt"] = (
            _ensure_pct(r.get("val", "N/D")),
            r.get("commentaire", ""),
            "",
        )

    # Taux immo / Bureaux / Commerces
    immo = data["immobilier_taux"]
    if "taux_immo" in parsed and parsed["taux_immo"].get("val"):
        t = parsed["taux_immo"]
        immo["taux_20ans"] = _ensure_pct(t.get("val", "N/D"))
        immo["taux_20ans_prev"] = _ensure_pct(t.get("prev", "N/D"))
        immo["taux_20ans_n1"] = _ensure_pct(t.get("n1", "N/D"))
        immo["taux_20ans_commentaire"] = t.get("commentaire", "")
    if "bureaux_idf" in parsed and parsed["bureaux_idf"].get("val"):
        b = parsed["bureaux_idf"]
        immo["bureaux_val"] = _ensure_pct(b.get("val", "N/D"))
        immo["bureaux_prev"] = _ensure_pct(b.get("prev", "N/D"))
        immo["bureaux_n1"] = _ensure_pct(b.get("n1", "N/D"))
        immo["bureaux_commentaire"] = b.get("commentaire", "")
    if "commerces" in parsed and parsed["commerces"].get("val"):
        c = parsed["commerces"]
        immo["commerces_val"] = _ensure_pct(c.get("val", "N/D"))
        immo["commerces_prev"] = _ensure_pct(c.get("prev", "N/D"))
        immo["commerces_n1"] = _ensure_pct(c.get("n1", "N/D"))
        immo["commerces_commentaire"] = c.get("commentaire", "")

    # Prix immo
    if "immo_prix" in parsed:
        for ville, infos in parsed["immo_prix"].items():
            if isinstance(infos, dict) and infos.get("val"):
                data["immo_prix"][ville] = infos

    # SCPI
    if "scpi" in parsed:
        sc = parsed["scpi"]
        if sc.get("marche"):
            data["scpi"]["marche"].update(sc["marche"])
        if sc.get("par_secteur"):
            data["scpi"]["par_secteur"] = sc["par_secteur"]
        if sc.get("scpi_top10"):
            data["scpi"]["scpi_top10"] = sc["scpi_top10"]
        data["scpi"]["analyse"] = sc.get("analyse", "")
        data["scpi"]["points_vigilance"] = sc.get("points_vigilance", [])
        data["scpi"]["opportunites"] = sc.get("opportunites", [])

    # Analyse macro
    data["commentaire_general"] = parsed.get("commentaire_general", "")
    data["claude_cycle"] = parsed.get("claude_cycle", {})
    data["claude_vigilance"] = parsed.get("claude_vigilance", [])
    data["claude_opportunites"] = parsed.get("claude_opportunites", [])
    data["claude_allocation"] = parsed.get("claude_allocation", {})
    data["claude_synthese_immo"] = parsed.get("claude_synthese_immo", "")
    data["claude_synthese_pe"] = parsed.get("claude_synthese_pe", "")
    data["claude_synthese_scpi"] = parsed.get("claude_synthese_scpi", "")


def _fallback_analysis(data: Dict[str, Any]) -> None:
    """Si Claude echoue completement, on injecte un minimum pour que le PDF se genere."""
    if not data.get("commentaire_general"):
        data["commentaire_general"] = (
            f"Analyse automatique indisponible pour {data.get('date', 'ce mois')}. "
            "Les donnees chiffrees ci-dessous proviennent uniquement des APIs officielles."
        )
    if not data.get("claude_cycle"):
        data["claude_cycle"] = {
            z: {"regime": "N/D", "commentaire": "Analyse indisponible.",
                "pib_estime": "N/D", "cpi_estime": "N/D"}
            for z in ["France", "Etats-Unis", "Zone Euro", "Chine", "Bresil", "Inde"]
        }
    data.setdefault("claude_vigilance", ["Analyse Claude indisponible."])
    data.setdefault("claude_opportunites", ["Analyse Claude indisponible."])
    data.setdefault("claude_allocation", {k: "N/D" for k in
        ["actions", "obligations", "matieres_premieres", "immobilier",
         "cash_monetaire", "private_equity", "scpi"]})
    data.setdefault("claude_synthese_immo", "Synthese indisponible.")
    data.setdefault("claude_synthese_pe", "Synthese indisponible.")
    data.setdefault("claude_synthese_scpi", "Synthese indisponible.")


# ──────────────────────────────────────────────────────────────────────────
# Diagnostic post-injection
# ──────────────────────────────────────────────────────────────────────────

def _diagnostic_log(data: Dict[str, Any]) -> None:
    """Log un resume des donnees collectees pour faciliter le debug."""
    print("\n  --- Diagnostic post-injection ---", flush=True)
    checks = [
        ("PIB Chine",       data.get("gdp_chine", {}).get("val")),
        ("PIB Bresil",      data.get("gdp_bresil", {}).get("val")),
        ("PIB Inde",        data.get("gdp_inde", {}).get("val")),
        ("CPI Chine",       data.get("cpi_chine", {}).get("val")),
        ("CPI Bresil",      data.get("cpi_bresil", {}).get("val")),
        ("CPI Inde",        data.get("cpi_inde", {}).get("val")),
        ("PMI France",      data.get("pmi", {}).get("france", {}).get("val")),
        ("PMI USA",         data.get("pmi", {}).get("usa", {}).get("val")),
        ("PMI Zone Euro",   data.get("pmi", {}).get("ez", {}).get("val")),
        ("PMI Chine",       data.get("pmi", {}).get("chine", {}).get("val")),
        ("PMI Bresil",      data.get("pmi", {}).get("bresil", {}).get("val")),
        ("PMI Inde",        data.get("pmi", {}).get("inde", {}).get("val")),
        ("PBoC",            data.get("pboc", {}).get("val")),
        ("BCB Selic",       data.get("bcb_selic", {}).get("val")),
        ("RBI Repo",        data.get("rbi_repo", {}).get("val")),
        ("Argos",           data.get("private_equity", {}).get("argos", ("N/D",))[0]),
        ("Levees PE",       data.get("private_equity", {}).get("levees", ("N/D",))[0]),
        ("Taux 20 ans",     data.get("immobilier_taux", {}).get("taux_20ans")),
        ("Bureaux IDF",     data.get("immobilier_taux", {}).get("bureaux_val")),
        ("Prix immo",       f"{len(data.get('immo_prix', {}))} villes"),
        ("SCPI TD moyen",   data.get("scpi", {}).get("marche", {}).get("td_moyen")),
        ("SCPI top 10",     f"{len(data.get('scpi', {}).get('scpi_top10', []))} SCPI"),
    ]
    nd_count = 0
    for label, val in checks:
        v = val if val else "N/D"
        if not val or str(val) == "N/D":
            nd_count += 1
            print(f"    [N/D] {label}", flush=True)
        else:
            print(f"    [OK]  {label} : {v}", flush=True)
    print(f"  ({nd_count}/{len(checks)} indicateurs en N/D)", flush=True)
    print("  ---------------------------------\n", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# Point d'entree principal
# ──────────────────────────────────────────────────────────────────────────

def run_analysis(data: Dict[str, Any], client: Optional[anthropic.Anthropic] = None) -> Dict[str, Any]:
    """Lance l'analyse Claude unique sur les donnees deja collectees via APIs.
    Retourne le dict data enrichi des champs Claude."""
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("  [ERREUR] ANTHROPIC_API_KEY absent, analyse Claude impossible.", flush=True)
            _fallback_analysis(data)
            return data
        client = anthropic.Anthropic(api_key=api_key)

    print(f"\n  Analyse Claude unique (modele {MODEL})...", flush=True)
    prompt = build_prompt(data)
    print(f"  Prompt initial : {len(prompt):,} chars (~{len(prompt)//4:,} tokens)", flush=True)

    try:
        text = call_with_search(client, prompt, max_tokens=8000)
        if not text:
            print("  [WARN] Reponse Claude vide. Application du fallback.", flush=True)
            _fallback_analysis(data)
            return data

        try:
            parsed = extract_json(text)
            print(f"  JSON parse OK ({len(parsed)} cles de premier niveau).", flush=True)
        except Exception as e:
            print(f"  [WARN] JSON invalide : {e}", flush=True)
            print(f"  Debut reponse : {text[:200]}", flush=True)
            _fallback_analysis(data)
            return data

        _inject_into_data(data, parsed)
        _fallback_analysis(data)  # remplit ce qui n'a pas ete injecte
        _diagnostic_log(data)
        return data

    except Exception as e:
        print(f"  [ERREUR] Analyse Claude echec : {type(e).__name__}: {e}", flush=True)
        _fallback_analysis(data)
        return data


if __name__ == "__main__":
    # Test isole
    sample = {"date": "Mai 2026", "collected_at": "2026-05-28"}
    print(build_prompt(sample)[:2000])
