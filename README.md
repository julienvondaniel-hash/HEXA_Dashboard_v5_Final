# Tableau de Bord HEXA Patrimoine — Automatisation mensuelle v6.2

## Corrections v6.2 (par rapport a v6.1)

Apres analyse du rendu v6.1 (mai 2026), corrections additionnelles :

| # | Anomalie corrigee | Impact |
|---|---|---|
| 1 | `fetch_ecb_rate` retournait la cle serie SDW comme periode (ex "FM.B.U2.EUR.4F.KR.DFR.LEV") | Parse robuste du CSV ECB avec recherche par nom de colonne |
| 2 | `fetch_euribor` meme bug + pas de fallback | Parse robuste + fallback `web_search` ajoute (champ `euribor_fallback`) |
| 3 | "69 bps bps" en Section 4 quand Claude retournait "69 bps" au lieu de "69" | Helper `_strip_unit` cote claude_analysis + `fmt_bps` idempotent cote PDF |
| 4 | "Prec. : N/D% -" en Section 4 quand US curve `spread_prev` etait vide | Parsing conditionnel : pas de `%` si N/D |
| 5 | Section 14 IMMOBILIER : header en bleu sur fond bleu = invisible | `header_white_style` cree pour les Paragraphs sur fond fonce |
| 6 | Section 12 PE : "3.7 T$ (PE global) / 1.3 T$ (Buyout)" debordait en taille 20pt | `_kpi_font_size` adapte la police selon la longueur (24/20/16/13/11pt) |
| 7 | Section 12 PE : colonne "Var." trop etroite pour "+9% valeur / -6% volume" | Largeur colonnes ajustee 42/24/22/70 -> 40/24/32/62 |
| 8 | Section 13 SCPI : TD secteur en %/trim au lieu d'annuel | Regle ajoutee dans prompt Pass 3 + normalisation auto (×4 + ajout %) |
| 9 | Section 11 Euribor en N/D : "N/D (N/D)" inesthetique | Helper `_fmt_period` : affiche "N/D" simple si donnees absentes |
| 10 | Sources prix immo heterogenes (Qoridor, PAP, SeLoger, MeilleursAgents melanges) | Prompt Pass 3 force "DVF/MeilleursAgents" ou "Notaires de France" |
| 11 | Valeurs PE multi-segments ("5.4% (moy) / 6.0% (evergreen)") debordaient | `_strip_unit` cote claude_analysis : ne garde que la 1ere valeur, var en commentaire |
| 12 | Mention "(annualise)" parasite dans plusieurs valeurs SCPI | Nettoyage systematique a l'injection (`td_moyen`, `tof`, `decote`) |

## Corrections v6.1 (rappel)

| # | Anomalie corrigee |
|---|---|
| 1 | `REGIME_COLORS` non defini (NameError latent) |
| 2 | PIB France/USA/Zone Euro hardcodes en Section 7 |
| 3 | Pas de fallback `web_search` pour PIB FR/US/ZE ni Fed rate |
| 4 | `fetch_fed_rate` bascule sur FRED `DFEDTARU` (H.15 en fallback) |
| 5 | Section 8 (Allocation) : ligne SCPI omise |
| 6 | Spreads IG/HY en format mixte, prec./A-1 manquants |
| 7 | Spread OAT/Bund : "bps pb" doublon |
| 8 | Bandeaux "CORRECTION" et "CORRECTION v2" supprimes |
| 9 | Renumerotation continue : 12 → 13 → 14 |
| 10 | Section 14 SCPI : "(annualise)" mal coupe |
| 11 | Section 15 doublon Section 11 |
| 12 | `call_with_search` plafonne via `CLAUDE_MAX_ITER` |
| 13 | Pauses configurables via `CLAUDE_PAUSE_SECONDS` |
| 14 | Modele Anthropic configurable via `ANTHROPIC_MODEL` |
| 15 | `parse_pct` robuste pour eviter les TypeError sur N/D |

## Architecture

```
GitHub Actions (le 2 du mois a 7h00)
    │
    ├── src/dashboard.py        → APIs officielles (BEA, BLS, Eurostat, ECB, FRED, Yahoo Finance, Banque Mondiale)
    ├── src/claude_analysis.py  → Claude web_search (PMI, Chine, CPI flash, immo, PE, SCPI, spreads, fallback PIB/Fed/Euribor)
    ├── src/generate_pdf.py     → PDF charte HEXA (14 sections)
    └── main.py                 → Orchestration + email Gmail
```

## 14 sections du PDF

1. Activite & Croissance (PIB + PMI + NFP)
2. Inflation (CPI avec donnees flash)
3. Taux Directeurs (BCE, Fed, PBoC)
4. Stress Financier (VIX, Fear&Greed, Spread OAT/Bund, Courbe US 2/10ans, IG/HY)
5. Indices Boursiers Mondiaux
6. Taux de Change EUR
7. Cycle Economique (6 zones, analyse contextuelle Claude)
8. Allocation Recommandee (Claude, 7 classes d'actifs incluant SCPI)
9. Matieres Premieres
10. Prix Immobilier au m² (8 villes)
11. Taux de Reference (Euribor, OAT, taux immo, PE, IG, HY)
12. Private Equity (Argos, France Invest, Dry Powder)
13. SCPI (marche, secteurs, SCPI phares, analyse Claude)
14. Immobilier France (marche locatif : bureaux IDF + surfaces commerciales)

## Secrets GitHub requis

| Secret | Description | Obligatoire |
|--------|-------------|-------------|
| `GMAIL_USER` | votre@gmail.com | Oui |
| `GMAIL_APP_PASS` | Mot de passe application Gmail (16 caracteres) | Oui |
| `RECIPIENTS` | email1@domain.com,email2@domain.com | Oui |
| `ANTHROPIC_API_KEY` | Cle API Claude (console.anthropic.com) | Oui |

## Variables d'environnement optionnelles

| Variable | Defaut | Role |
|----------|--------|------|
| `ANTHROPIC_MODEL` | `claude-opus-4-5` | Modele Claude utilise pour web_search + analyse |
| `CLAUDE_PAUSE_SECONDS` | `3` | Pause entre les passes web_search |
| `CLAUDE_MAX_ITER` | `12` | Plafond d'iterations par appel `call_with_search` |

## Sources de donnees

### Automatiques via APIs gratuites
- PIB USA → BEA | PIB France/ZE → Eurostat | CPI USA → BLS | CPI France/ZE → Eurostat HICP
- BCE → ECB SDW (parse robuste v6.2) | Fed → FRED DFEDTARU (puis H.15 XML en fallback)
- Euribor → ECB SDW (parse robuste v6.2) | VIX → Yahoo Finance
- NFP/Chomage → BLS | Fear&Greed → CNN
- Spread OAT/Bund → Yahoo Finance/ECB SDW | Courbe US 2/10ans → Yahoo Finance
- IG/HY spreads → FRED | Indices → Yahoo Finance | Forex → Yahoo Finance
- Matieres premieres → Yahoo Finance | PIB emergents → Banque Mondiale

### Via Claude web_search (automatique chaque mois)
- PMI (4 zones) → S&P Global / Caixin / HCOB
- PIB/CPI/PBoC Chine → NBS via presse internationale
- CPI flash France/Zone Euro → INSEE/Eurostat
- Fallback PIB France/USA/Zone Euro si APIs officielles tombent
- Fallback Fed funds rate si FRED+H.15 tombent
- Fallback Euribor 3 mois si ECB SDW tombe (NOUVEAU v6.2)
- Taux immo 20 ans → CAFPI | Bureaux/commerces → CBRE/JLL
- Prix immo 8 villes → DVF/MeilleursAgents (sources homogenisees v6.2)
- Argos Mid-Market → argos-wityu.com | France Invest → france-invest.fr
- Dry Powder PE → Bain/Preqin (format strict v6.2 : 1 valeur principale)
- SCPI marche → ASPIM/MeilleuresSCPI (TD annuel impose v6.2)
- Spreads credit si FRED indisponible → presse financiere

## Cout mensuel estime
- GitHub Actions : Gratuit (≤ 2000 min/mois)
- Gmail : Gratuit
- API Claude : ~0,05-0,10 €/mois (3-4 appels : 3 passes recherche + 1 analyse)
