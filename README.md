# Tableau de Bord HEXA Patrimoine — Automatisation mensuelle v5

## Architecture complète

```
GitHub Actions (le 2 du mois à 7h00)
    │
    ├── src/dashboard.py        → APIs officielles (BEA, BLS, Eurostat, ECB, Fed, Yahoo Finance, FRED, Banque Mondiale)
    ├── src/claude_analysis.py  → Claude web_search (PMI, Chine, CPI flash, immo, PE, SCPI, spreads)
    ├── src/generate_pdf.py     → PDF charte HEXA (15 sections)
    └── main.py                 → Orchestration + email Gmail
```

## 15 sections du PDF

1. Activité & Croissance (PIB + PMI + NFP)
2. Inflation (CPI avec données flash)
3. Taux Directeurs (BCE, Fed, PBoC)
4. Stress Financier (VIX, Fear&Greed, Spread OAT/Bund, Courbe US 2/10ans, IG/HY)
5. Indices Boursiers Mondiaux
6. Taux de Change EUR
7. Cycle Économique (6 zones, analyse contextuelle Claude)
8. Allocation Recommandée (Claude)
9. Matières Premières
10. Prix Immobilier au m² (8 villes)
11. Taux de Référence (Euribor, OAT, taux immo, PE, IG, HY)
12. Private Equity (Argos, France Invest, Dry Powder)
13. SCPI (marché, secteurs, SCPI phares, analyse Claude)
14. Immobilier France (marché locatif & taux)

## Secrets GitHub requis

Settings → Secrets → Actions → New repository secret

| Secret | Description |
|--------|-------------|
| GMAIL_USER | votre@gmail.com |
| GMAIL_APP_PASS | Mot de passe application Gmail (16 caractères) |
| RECIPIENTS | email1@domain.com,email2@domain.com |
| ANTHROPIC_API_KEY | Clé API Claude (console.anthropic.com) |

## Fichiers à uploader à la racine GitHub

- `Logo_Hexa.png` — logo HEXA Patrimoine

## Sources de données

### Automatiques via APIs gratuites
- PIB USA → BEA | PIB France/ZE → Eurostat | CPI USA → BLS | CPI France/ZE → Eurostat HICP
- BCE → ECB SDW | Fed → Fed H.15 XML | Euribor → ECB SDW | VIX → Yahoo Finance
- NFP/Chômage → BLS | Fear&Greed → CNN | Spread OAT/Bund → Yahoo Finance/ECB SDW
- Courbe US 2/10ans → Yahoo Finance | IG/HY spreads → FRED
- Indices → Yahoo Finance | Forex → Yahoo Finance | Matières premières → Yahoo Finance
- PIB émergents → Banque Mondiale

### Via Claude web_search (automatique chaque mois)
- PMI (4 zones) → S&P Global / presse
- PIB/CPI/PBoC Chine → NBS via presse internationale
- CPI flash France/Zone Euro → INSEE/Eurostat
- Taux immo 20 ans → CAFPI
- Bureaux/commerces → CBRE/JLL
- Prix immo 8 villes → DVF/MeilleursAgents
- Argos Mid-Market → argos-wityu.com
- France Invest → france-invest.fr
- Dry Powder PE → Bain/Preqin
- SCPI marché → ASPIM/MeilleuresSCPI
- Spreads crédit si FRED indisponible → presse financière

## Coût mensuel estimé
- GitHub Actions : Gratuit
- Gmail : Gratuit
- API Claude : ~0,05€/mois (2 appels : recherche web + analyse)
