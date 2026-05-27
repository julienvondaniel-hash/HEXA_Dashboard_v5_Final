"""
Generation du PDF tableau de bord HEXA Patrimoine.
Version 6.1 - corrections systematiques :
1. REGIME_COLORS desormais defini (NameError corrige).
2. Section 7 (cycle) : PIB / inflation lus dynamiquement depuis data, plus de hardcoding.
3. Section 8 (allocation) : ligne SCPI ajoutee, plus omise.
4. Section 4 (spreads IG/HY) : format unifie en points de base (pb) avec gestion N/D.
5. Section 4 (OAT/Bund) : "bps" sans doublon "pb".
6. Sections 2 et 7 : bandeaux "CORRECTION" supprimes (artefacts editoriaux).
7. Renumerotation : 12 PE -> 13 SCPI -> 14 Immobilier France (suppression du saut).
8. Section 13 (SCPI) : largeur TD moyen elargie pour eviter le saut de ligne.
9. Section 14 : ligne taux 20 ans dedupliquee de la Section 11.
10. parse_pct utilitaire robuste pour eviter les TypeError sur valeurs N/D.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, Spacer, Table, TableStyle,
                                HRFlowable, BaseDocTemplate,
                                PageTemplate, Frame)
from reportlab.lib.enums import TA_CENTER

# ── PALETTE ──────────────────────────────────────────────────────────────────
NAVY = colors.HexColor("#1B2B4B")
NAVY_LIGHT = colors.HexColor("#2A3F6F")
TURQUOISE = colors.HexColor("#4ABFBF")
LIGHT_BG = colors.HexColor("#F0F7F7")
DARK_ROW = colors.HexColor("#E3F2F2")
GREEN = colors.HexColor("#1A7F4B")
RED = colors.HexColor("#C0392B")
ORANGE = colors.HexColor("#D35400")
GREY_TEXT = colors.HexColor("#5D6D7E")
BLUE = colors.HexColor("#2471A3")
WHITE = colors.white

# Couleurs par regime (CORRECTION : etait reference mais jamais defini)
REGIME_COLORS = {
    "Goldilocks":   GREEN,
    "Surchauffe":   ORANGE,
    "Obligations":  BLUE,
    "Stagflation":  RED,
    "N/D":          GREY_TEXT,
}

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm


# ── STYLES ───────────────────────────────────────────────────────────────────
def S(name, **kw):
    return ParagraphStyle(name, **kw)


section_style = S("Sec", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE, leading=13)
label_style = S("Lbl", fontName="Helvetica-Bold", fontSize=7.5, textColor=NAVY)
# Style "header blanc" : utilise pour les premieres lignes de tableaux a fond fonce
# car la couleur d'un Paragraph s'impose sur le TEXTCOLOR du TableStyle.
header_white_style = S("HdrW", fontName="Helvetica-Bold", fontSize=7.5, textColor=WHITE)
value_style = S("Val", fontName="Helvetica-Bold", fontSize=9, textColor=NAVY)
small_style = S("Sm", fontName="Helvetica", fontSize=6.5, textColor=GREY_TEXT)
note_style = S("Nt", fontName="Helvetica-Oblique", fontSize=6, textColor=GREY_TEXT)


def h(c):
    return c.hexval()[2:]


# ── PARSERS ROBUSTES ─────────────────────────────────────────────────────────
def parse_pct(s):
    """Convertit une chaine type '+2,5%', '~3.6%', '80 bps', 'N/D' en float ou None."""
    if s is None:
        return None
    try:
        st = str(s).strip().replace('%', '').replace(',', '.').replace('+', '').replace('~', '').replace('bps', '').replace('pb', '').strip()
        if not st or st.upper() == "N/D":
            return None
        return float(st)
    except (ValueError, TypeError):
        return None


def arrow(v, p):
    """Fleche de variation entre v et p. Renvoie ('-', GREY_TEXT) si non comparable."""
    vf, pf = parse_pct(v), parse_pct(p)
    if vf is None or pf is None:
        return "-", GREY_TEXT
    if vf > pf:
        return "▲", GREEN
    if vf < pf:
        return "▼", RED
    return "▶", GREY_TEXT


def cpi_color(v):
    vf = parse_pct(v)
    if vf is None:
        return GREY_TEXT
    return RED if vf > 2.5 else (ORANGE if vf > 2.0 else GREEN)


def pmi_color(v):
    vf = parse_pct(v)
    if vf is None:
        return GREY_TEXT
    return GREEN if vf >= 50 else RED


def gdp_color(v):
    vf = parse_pct(v)
    if vf is None:
        return GREY_TEXT
    return GREEN if vf >= 0.3 else (ORANGE if vf >= 0 else RED)


def spread_color(v):
    vf = parse_pct(v)
    if vf is None:
        return GREY_TEXT
    return RED if vf < 0 else (ORANGE if vf < 0.3 else GREEN)


def credit_spread_color(v, asset_class="ig"):
    """v est exprime en points de base (ex: 80, 285)."""
    vf = parse_pct(v)
    if vf is None:
        return GREY_TEXT
    if asset_class == "ig":
        # IG : <120 vert, <180 orange, >=180 rouge (en bps)
        return GREEN if vf < 120 else (ORANGE if vf < 180 else RED)
    # HY : <400 vert, <600 orange, >=600 rouge (en bps)
    return GREEN if vf < 400 else (ORANGE if vf < 600 else RED)


def fmt_bps(v):
    """Formate une valeur de spread credit en 'XX bps' ou 'N/D'. Idempotent : '69 bps' -> '69 bps'."""
    if v is None:
        return "N/D"
    # parse_pct enleve deja les unites '%', 'bps', 'pb' avant de convertir
    vf = parse_pct(v)
    if vf is None:
        return "N/D"
    # Si la valeur originale etait en % (< 10), on convertit en bps (1% = 100 bps)
    # Sinon on garde tel quel
    if vf < 10:
        vf = vf * 100
    return f"{vf:.0f} bps"


# ── ENTETE / PIED DE PAGE ────────────────────────────────────────────────────
def page_bg(canvas_obj, doc):
    canvas_obj.saveState()
    w, h2 = A4
    canvas_obj.setFillColor(NAVY)
    canvas_obj.rect(0, h2 - 32 * mm, w, 32 * mm, fill=1, stroke=0)
    canvas_obj.setFillColor(TURQUOISE)
    canvas_obj.rect(0, h2 - 33.5 * mm, w, 1.5 * mm, fill=1, stroke=0)
    for lp in ["Logo_Hexa.png", "Logo Hexa.png"]:
        if os.path.exists(lp):
            try:
                canvas_obj.drawImage(lp, MARGIN, h2 - 30 * mm, width=30 * mm, height=22 * mm,
                                     preserveAspectRatio=True, mask='auto')
            except Exception:
                pass
            break
    canvas_obj.setFillColor(WHITE)
    canvas_obj.setFont("Helvetica-Bold", 14)
    canvas_obj.drawCentredString(w / 2 + 12 * mm, h2 - 13 * mm, "TABLEAU DE BORD ECONOMIQUE MENSUEL")
    canvas_obj.setFont("Helvetica-Bold", 11)
    canvas_obj.setFillColor(TURQUOISE)
    canvas_obj.drawCentredString(w / 2 + 12 * mm, h2 - 21 * mm, doc.dashboard_date)
    canvas_obj.setFont("Helvetica-Oblique", 6.5)
    canvas_obj.setFillColor(colors.HexColor("#AABCCC"))
    canvas_obj.drawCentredString(w / 2 + 12 * mm, h2 - 27 * mm,
        "Sources : INSEE - Eurostat - BEA - BLS - ECB - Fed - CBOE - CNN - S&P PMI - Yahoo Finance - FRED - DVF - France Invest - Banque Mondiale")
    canvas_obj.setFillColor(NAVY)
    canvas_obj.rect(0, 0, w, 9 * mm, fill=1, stroke=0)
    canvas_obj.setFillColor(TURQUOISE)
    canvas_obj.rect(0, 9 * mm, w, 0.8 * mm, fill=1, stroke=0)
    canvas_obj.setFillColor(colors.HexColor("#AABCCC"))
    canvas_obj.setFont("Helvetica", 6)
    canvas_obj.drawString(MARGIN, 4 * mm, "HEXA - Donnons du sens a votre patrimoine  |  Document a usage interne")
    canvas_obj.drawRightString(w - MARGIN, 4 * mm, f"{doc.dashboard_date}  |  Page {doc.page}")
    canvas_obj.restoreState()


def sec_hdr(title):
    t = Table([[Paragraph(f"  {title}", section_style)]], colWidths=[PAGE_W - 2 * MARGIN])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NAVY),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('LINEBEFORE', (0, 0), (0, -1), 4, TURQUOISE)]))
    return t


def std_table(header, rows, cw):
    t = Table([header] + rows, colWidths=cw)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY_LIGHT),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, DARK_ROW]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, 0), 1, TURQUOISE)]))
    return t


def note_box(text, color=NAVY):
    t = Table([[Paragraph(text, S("nb", fontName="Helvetica-Oblique", fontSize=7,
                                  textColor=color, leading=10))]],
              colWidths=[PAGE_W - 2 * MARGIN])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('LINEBEFORE', (0, 0), (0, -1), 3, TURQUOISE)]))
    return t


# ── GENERATEUR PRINCIPAL ─────────────────────────────────────────────────────
def generate_pdf(data, output_path):
    doc = BaseDocTemplate(output_path, pagesize=A4,
                          leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=36 * mm, bottomMargin=13 * mm)
    doc.dashboard_date = data["date"]
    frame = Frame(MARGIN, 13 * mm, PAGE_W - 2 * MARGIN, PAGE_H - 49 * mm, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=page_bg)])
    story = []
    col_w = PAGE_W - 2 * MARGIN

    # ── 1. ACTIVITE & CROISSANCE ─────────────────────────────────────────────
    story += [sec_hdr("1  |  ACTIVITE & CROISSANCE"), Spacer(1, 2 * mm)]
    pib_hdr = ["Zone", "PIB", "Periode", "Prec.", "A-1", "Source"]
    pib_cw = [30 * mm, 20 * mm, 24 * mm, 18 * mm, 22 * mm, 44 * mm]
    rows = []
    # Ordre v6.5.2 : France, Zone Euro, Etats-Unis, Chine, Amerique latine, Asie ex-Chine
    for zone, d in [("France", data["gdp_fr"]),
                    ("Zone Euro", data["gdp_ez"]),
                    ("Etats-Unis", data["gdp_usa"]),
                    ("Chine", data["gdp_chine"]),
                    ("Amerique latine", data.get("gdp_latam", {"val":"N/D","period":"N/D","prev":"N/D","n1":"N/D","n1_period":"N/D","source":"FMI WEO (web_search)"})),
                    ("Asie ex-Chine",  data.get("gdp_asie_ex_chine", {"val":"N/D","period":"N/D","prev":"N/D","n1":"N/D","n1_period":"N/D","source":"FMI WEO (web_search)"}))]:
        arw, ac = arrow(d["val"], d["prev"])
        gc = gdp_color(d["val"])
        rows.append([
            Paragraph(zone, label_style),
            Paragraph(f'<font color="#{h(gc)}"><b>{d["val"]}</b></font> <font color="#{h(ac)}">{arw}</font>', value_style),
            Paragraph(d["period"], small_style),
            Paragraph(d["prev"], small_style),
            Paragraph(f'{d["n1"]} ({d["n1_period"]})', small_style),
            Paragraph(d["source"], note_style)])
    story.append(std_table(pib_hdr, rows, pib_cw))
    story.append(Spacer(1, 3 * mm))

    # PMI
    pmi_hdr = ["Zone", "PMI Composite", "Mois", "Mois prec.", "Seuil", "Signal / Source"]
    pmi_cw = [30 * mm, 22 * mm, 18 * mm, 18 * mm, 14 * mm, 56 * mm]
    rows = []
    # Ordre v6.5.2 : France, Zone Euro, Etats-Unis, Chine, + Latam et Asie si dispos
    pmi_zones = [("France", "france"), ("Zone Euro", "ez"), ("Etats-Unis", "usa"), ("Chine", "chine")]
    if data["pmi"].get("latam", {}).get("val", "N/D") != "N/D":
        pmi_zones.append(("Amerique latine", "latam"))
    if data["pmi"].get("asie_ex_chine", {}).get("val", "N/D") != "N/D":
        pmi_zones.append(("Asie ex-Chine", "asie_ex_chine"))
    for zone, key in pmi_zones:
        pm = data["pmi"][key]
        val, prev = pm["val"], pm["prev"]
        arw, ac = arrow(val, prev)
        pc = pmi_color(val)
        vf = parse_pct(val)
        if vf is None:
            sig, sig_c = "N/D", GREY_TEXT
        elif vf >= 50:
            sig, sig_c = "Expansion", GREEN
        else:
            sig, sig_c = "Contraction", RED
        rows.append([
            Paragraph(zone, label_style),
            Paragraph(f'<font color="#{h(pc)}"><b>{val}</b></font> <font color="#{h(ac)}">{arw}</font>', value_style),
            Paragraph(pm["period"], small_style),
            Paragraph(prev, small_style),
            Paragraph("50,0", small_style),
            Paragraph(f'<font color="#{h(sig_c)}">{sig}</font> - {pm["source"]}', note_style)])
    story.append(std_table(pmi_hdr, rows, pmi_cw))
    story.append(Spacer(1, 3 * mm))

    # NFP + Chomage
    nfp = data["nfp"]
    unem = data["unemployment_usa"]
    arw_n, col_n = arrow(nfp["val"].replace(",", "").replace("+", ""),
                         nfp["prev"].replace(",", "").replace("+", ""))
    t_nfp = Table([
        [Paragraph("NFP Etats-Unis (BLS)", label_style),
         Paragraph(f'<b>{nfp["val"]}</b> emplois <font color="#{h(col_n)}">{arw_n}</font>', value_style),
         Paragraph(nfp["period"], small_style),
         Paragraph(f'Prec. : {nfp["prev"]} ({nfp["prev_period"]})', small_style),
         Paragraph(f'A-1 : {nfp["n1"]}', small_style),
         Paragraph(f'Chomage : {unem["val"]}', small_style)],
        [Paragraph(f'Source : {nfp["source"]}', note_style), '', '', '', '', '']],
        colWidths=[28 * mm, 26 * mm, 20 * mm, 36 * mm, 26 * mm, 22 * mm])
    t_nfp.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BACKGROUND', (0, 1), (-1, 1), WHITE),
        ('SPAN', (0, 1), (-1, 1)),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story += [t_nfp, Spacer(1, 4 * mm)]

    # ── 2. INFLATION ─────────────────────────────────────────────────────────
    story += [sec_hdr("2  |  INFLATION (IPC / CPI)"), Spacer(1, 2 * mm)]
    cpi_hdr = ["Zone", "IPC a/a", "Mois", "Mois prec.", "A-1", "Source"]
    cpi_cw = [30 * mm, 20 * mm, 22 * mm, 22 * mm, 22 * mm, 42 * mm]
    rows = []
    # Ordre v6.5.2 : France, Zone Euro, Etats-Unis, Chine, Amerique latine, Asie ex-Chine
    cpi_default = {"val":"N/D","period":"N/D","prev":"N/D","prev_period":"N/D",
                   "n1":"N/D","n1_period":"N/D","source":"FMI WEO (web_search)"}
    for zone, cd in [("France", data["cpi_fr"]),
                     ("Zone Euro", data["cpi_ez"]),
                     ("Etats-Unis", data["cpi_usa"]),
                     ("Chine", data["cpi_chine"]),
                     ("Amerique latine", data.get("cpi_latam", cpi_default)),
                     ("Asie ex-Chine",  data.get("cpi_asie_ex_chine", cpi_default))]:
        arw, ac = arrow(cd["val"], cd["prev"])
        cc = cpi_color(cd["val"])
        rows.append([
            Paragraph(zone, label_style),
            Paragraph(f'<font color="#{h(cc)}"><b>{cd["val"]}</b></font> <font color="#{h(ac)}">{arw}</font>', value_style),
            Paragraph(cd["period"], small_style),
            Paragraph(f'{cd["prev"]} ({cd["prev_period"]})', small_style),
            Paragraph(f'{cd["n1"]} ({cd["n1_period"]})', small_style),
            Paragraph(cd["source"], note_style)])
    story += [std_table(cpi_hdr, rows, cpi_cw), Spacer(1, 4 * mm)]

    # ── 3. TAUX DIRECTEURS ───────────────────────────────────────────────────
    story += [sec_hdr("3  |  POLITIQUES MONETAIRES - Taux Directeurs"), Spacer(1, 2 * mm)]
    ecb = data["ecb_rate"]
    fed = data["fed_rate"]
    pboc = data["pboc"]
    # Nouveaux taux directeurs v6.5.2 : BCB Selic (Bresil = proxy Amerique latine)
    # et RBI Repo Rate (Inde = proxy Asie ex-Chine). Defaults a N/D si non collecte.
    bcb = data.get("bcb_selic", {"val":"N/D","detail":"Taux Selic","prev":"N/D","source":"BCB (web_search)"})
    rbi = data.get("rbi_repo",  {"val":"N/D","detail":"Repo Rate","prev":"N/D","source":"RBI (web_search)"})
    rates_hdr = ["Banque Centrale", "Taux actuel", "Detail", "Taux prec.", "Source"]
    rates_cw = [40 * mm, 22 * mm, 36 * mm, 22 * mm, 38 * mm]
    arw_e, col_e = arrow(ecb["val"], ecb["prev"])
    arw_f, col_f = arrow(fed["val"], fed["prev"])
    arw_p, col_p = arrow(pboc["val"], pboc["prev"])
    arw_b, col_b = arrow(bcb["val"], bcb["prev"])
    arw_r, col_r = arrow(rbi["val"], rbi["prev"])
    # Ordre v6.5.2 : BCE (Zone Euro), Fed, PBoC, BCB (Latam), RBI (Asie)
    rows = [
        [Paragraph("BCE (Zone Euro)", label_style),
         Paragraph(f'<b>{ecb["val"]}</b> <font color="#{h(col_e)}">{arw_e}</font>', value_style),
         Paragraph(f'Prec. {ecb["prev"]} ({ecb["prev_period"]})', small_style),
         Paragraph(ecb["prev"], small_style),
         Paragraph(ecb["source"], note_style)],
        [Paragraph("Fed (Etats-Unis)", label_style),
         Paragraph(f'<b>{fed["val"]}</b> <font color="#{h(col_f)}">{arw_f}</font>', value_style),
         Paragraph(f'Prec. {fed["prev"]} ({fed["prev_period"]})', small_style),
         Paragraph(fed["prev"], small_style),
         Paragraph(fed["source"], note_style)],
        [Paragraph("PBoC (Chine)", label_style),
         Paragraph(f'<b>{pboc["val"]}</b> <font color="#{h(col_p)}">{arw_p}</font>', value_style),
         Paragraph(pboc["detail"], small_style),
         Paragraph(pboc["prev"], small_style),
         Paragraph(pboc["source"], note_style)],
        [Paragraph("BCB Selic (Bresil)", label_style),
         Paragraph(f'<b>{bcb["val"]}</b> <font color="#{h(col_b)}">{arw_b}</font>', value_style),
         Paragraph(bcb.get("detail", "Taux Selic (Amerique latine)"), small_style),
         Paragraph(bcb["prev"], small_style),
         Paragraph(bcb["source"], note_style)],
        [Paragraph("RBI Repo (Inde)", label_style),
         Paragraph(f'<b>{rbi["val"]}</b> <font color="#{h(col_r)}">{arw_r}</font>', value_style),
         Paragraph(rbi.get("detail", "Repo Rate (Asie ex-Chine)"), small_style),
         Paragraph(rbi["prev"], small_style),
         Paragraph(rbi["source"], note_style)]]
    story += [std_table(rates_hdr, rows, rates_cw), Spacer(1, 4 * mm)]

    # ── 4. STRESS FINANCIER ──────────────────────────────────────────────────
    story += [sec_hdr("4  |  INDICATEURS DE STRESS FINANCIER"), Spacer(1, 2 * mm)]
    fg = data["fg"]
    vix = data["vix"]
    sp = data["spread"]
    sw = col_w / 3
    fv = parse_pct(fg["val"])
    if fv is None:
        fc = GREY_TEXT
    elif fv <= 25 or fv > 75:
        fc = RED
    elif fv <= 45:
        fc = ORANGE
    elif fv <= 55:
        fc = GREY_TEXT
    else:
        fc = GREEN
    arw_fg, col_fg = arrow(fg["val"], fg["prev"])
    arw_vx, col_vx = arrow(vix["val"], vix["prev"])
    arw_sp, col_sp = arrow(sp["spread"], sp["spread_prev"])
    # Format unifie : le PDF n'ajoute jamais " bps" si la valeur le contient deja
    sp_val_str  = fmt_bps(sp["spread"])
    sp_prev_str = fmt_bps(sp["spread_prev"])
    t_stress = Table([
        [Paragraph("CNN Fear & Greed", label_style),
         Paragraph("VIX - Volatilite S&P 500", label_style),
         Paragraph("Spread OAT/Bund 10 ans", label_style)],
        [Paragraph(f'<font size="20" color="#{h(fc)}"><b>{fg["val"]}</b></font>/100<br/>'
                   f'<font color="#{h(fc)}"><b>{fg["label"]}</b></font>', value_style),
         Paragraph(f'<font size="20"><b>{vix["val"]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">CBOE</font>', value_style),
         Paragraph(f'<font size="20"><b>{sp_val_str}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">OAT {sp["oat"]} | Bund {sp["bund"]}</font>', value_style)],
        [Paragraph(f'Veille:{fg["prev"]} <font color="#{h(col_fg)}">{arw_fg}</font> | A-1:{fg["n1"]}', small_style),
         Paragraph(f'Veille:{vix["prev"]} ({vix["prev_date"]}) <font color="#{h(col_vx)}">{arw_vx}</font> | A-1:{vix["n1"]}', small_style),
         Paragraph(f'Prec.:{sp_prev_str} <font color="#{h(col_sp)}">{arw_sp}</font>', small_style)],
        [Paragraph(fg["source"], note_style),
         Paragraph(vix["source"], note_style),
         Paragraph(sp["source"], note_style)]],
        colWidths=[sw] * 3)
    t_stress.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BACKGROUND', (0, 1), (-1, 1), WHITE),
        ('BACKGROUND', (0, 2), (-1, 2), WHITE),
        ('BACKGROUND', (0, 3), (-1, 3), LIGHT_BG),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 0), (-1, 0), 1, TURQUOISE)]))
    story += [t_stress, Spacer(1, 3 * mm)]

    # Courbe taux US + Spreads credit
    usc = data["spread_us_curve"]
    cs = data["credit_spreads"]
    sw2 = col_w / 2

    arw_curve, col_curve = arrow(usc["spread"], usc["spread_prev"])
    sc = spread_color(usc["spread"])
    # Affichage propre du Prec. quand il est N/D
    usc_spread_v = parse_pct(usc.get("spread", "N/D"))
    usc_prev_v   = parse_pct(usc.get("spread_prev", "N/D"))
    usc_main_str = f'{usc_spread_v:+.2f}%' if usc_spread_v is not None else "N/D"
    usc_prev_str = f'{usc_prev_v:+.2f}%'   if usc_prev_v   is not None else "N/D"

    # Format unifie en bps pour IG/HY (correction du melange %/bps)
    ig_bps = fmt_bps(cs["ig_spread"])
    hy_bps = fmt_bps(cs["hy_spread"])
    ig_prev_bps = fmt_bps(cs["ig_spread_prev"])
    hy_prev_bps = fmt_bps(cs["hy_spread_prev"])
    ig_n1_bps = fmt_bps(cs["ig_spread_n1"])
    hy_n1_bps = fmt_bps(cs["hy_spread_n1"])
    ig_c = credit_spread_color(ig_bps, "ig")
    hy_c = credit_spread_color(hy_bps, "hy")
    arw_ig, col_ig = arrow(ig_bps, ig_prev_bps)
    arw_hy, col_hy = arrow(hy_bps, hy_prev_bps)

    t_new_stress = Table([
        [Paragraph("Courbe des taux US (2ans/10ans)", label_style),
         Paragraph("Spreads credit (IG / HY)", label_style)],
        [Paragraph(
            f'<font size="18" color="#{h(sc)}"><b>{usc_main_str}</b></font><br/>'
            f'<font size="7" color="#5D6D7E">US 2 ans : {usc["us_2y"]} | US 10 ans : {usc["us_10y"]}</font>',
            value_style),
         Paragraph(
            f'IG : <font color="#{h(ig_c)}"><b>{ig_bps}</b></font> <font color="#{h(col_ig)}">{arw_ig}</font>  '
            f'HY : <font color="#{h(hy_c)}"><b>{hy_bps}</b></font> <font color="#{h(col_hy)}">{arw_hy}</font>',
            value_style)],
        [Paragraph(
            f'<font color="#{h(sc)}"><b>Signal : {usc["signal"]}</b></font> — '
            f'Prec. : {usc_prev_str} <font color="#{h(col_curve)}">{arw_curve}</font><br/>'
            f'<font size="6" color="#C0392B">Inversion = signal historique de recession a 12-18 mois</font>',
            small_style),
         Paragraph(
            f'IG prec. : {ig_prev_bps} | IG A-1 : {ig_n1_bps}<br/>'
            f'HY prec. : {hy_prev_bps} | HY A-1 : {hy_n1_bps}<br/>'
            f'<font size="6" color="#5D6D7E">Spreads HY en hausse = stress sur entreprises endettees</font>',
            small_style)],
        [Paragraph(usc["source"], note_style),
         Paragraph(cs["source"], note_style)]],
        colWidths=[sw2] * 2)
    t_new_stress.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BACKGROUND', (0, 1), (-1, 1), WHITE),
        ('BACKGROUND', (0, 2), (-1, 2), WHITE),
        ('BACKGROUND', (0, 3), (-1, 3), LIGHT_BG),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 0), (-1, 0), 1, TURQUOISE)]))
    story += [t_new_stress, Spacer(1, 4 * mm)]

    # ── 5. INDICES BOURSIERS ─────────────────────────────────────────────────
    story += [sec_hdr("5  |  INDICES BOURSIERS MONDIAUX"), Spacer(1, 2 * mm)]
    idx_hdr = ["Indice", "Zone", "Niveau", "Var. 1 mois", "Var. 1 an", "Source"]
    idx_cw = [28 * mm, 22 * mm, 26 * mm, 24 * mm, 24 * mm, 34 * mm]
    rows = []
    for name, zone in [("CAC 40", "France"), ("Euro Stoxx 50", "Zone Euro"),
                       ("S&P 500", "Etats-Unis"), ("Nasdaq", "Etats-Unis"),
                       ("Dow Jones", "Etats-Unis"), ("FTSE 100", "UK"),
                       ("Nikkei 225", "Japon"), ("Shanghai", "Chine"),
                       ("MSCI EM", "Emergents")]:
        d = data["indices"].get(name)
        if d:
            val, pm, py = d["val"], d["prev_m"], d["prev_y"]
            pct_m = ((val - pm) / pm * 100) if pm else 0
            pct_y = ((val - py) / py * 100) if py else 0
            cm = GREEN if pct_m >= 0 else RED
            cy = GREEN if pct_y >= 0 else RED
            am = "▲" if pct_m > 0 else ("▼" if pct_m < 0 else "▶")
            ay = "▲" if pct_y > 0 else ("▼" if pct_y < 0 else "▶")
            vs = f"{val:,.0f}" if val > 1000 else f"{val:,.2f}"
            rows.append([
                Paragraph(f"<b>{name}</b>", label_style),
                Paragraph(zone, small_style),
                Paragraph(f"<b>{vs}</b>", value_style),
                Paragraph(f'<font color="#{h(cm)}">{am} {pct_m:+.1f}%</font>', value_style),
                Paragraph(f'<font color="#{h(cy)}">{ay} {pct_y:+.1f}%</font>', value_style),
                Paragraph("Yahoo Finance", note_style)])
    story += [std_table(idx_hdr, rows, idx_cw), Spacer(1, 4 * mm)]

    # ── 6. TAUX DE CHANGE ────────────────────────────────────────────────────
    story += [sec_hdr("6  |  TAUX DE CHANGE EUR vs PRINCIPALES DEVISES"), Spacer(1, 2 * mm)]
    fx_hdr = ["Paire", "Devise", "Taux actuel", "Mois prec.", "A-1", "Var. 1 mois", "Var. 1 an"]
    fx_cw = [20 * mm, 28 * mm, 22 * mm, 20 * mm, 20 * mm, 22 * mm, 22 * mm]
    fx_names = {"EUR/USD": "Dollar americain", "EUR/GBP": "Livre sterling",
                "EUR/JPY": "Yen japonais", "EUR/CHF": "Franc suisse",
                "EUR/CNY": "Yuan chinois"}
    rows = []
    for pair, label in fx_names.items():
        d = data["forex"].get(pair)
        if d:
            val, pm, py = d["val"], d["prev_m"], d["n1"]
            pct_m = ((val - pm) / pm * 100) if pm else 0
            pct_y = ((val - py) / py * 100) if py else 0
            cm = GREEN if pct_m >= 0 else RED
            cy = GREEN if pct_y >= 0 else RED
            am = "▲" if pct_m > 0 else ("▼" if pct_m < 0 else "▶")
            ay = "▲" if pct_y > 0 else ("▼" if pct_y < 0 else "▶")
            rows.append([
                Paragraph(f"<b>{pair}</b>", label_style),
                Paragraph(label, small_style),
                Paragraph(f"<b>{val:.4f}</b>", value_style),
                Paragraph(f"{pm:.4f}", small_style),
                Paragraph(f"{py:.4f}", small_style),
                Paragraph(f'<font color="#{h(cm)}">{am} {pct_m:+.2f}%</font>', value_style),
                Paragraph(f'<font color="#{h(cy)}">{ay} {pct_y:+.2f}%</font>', value_style)])
    story += [std_table(fx_hdr, rows, fx_cw),
              Spacer(1, 1 * mm),
              Paragraph("Source : Yahoo Finance (taux spot).",
                        S("s0", fontName="Helvetica-Oblique", fontSize=5.5, textColor=GREY_TEXT)),
              Spacer(1, 4 * mm)]

    # ── 7. CYCLE ECONOMIQUE ──────────────────────────────────────────────────
    # CORRECTIONS : bandeau "CORRECTION v2" supprime, zone_data_map lue dynamiquement
    story += [sec_hdr("7  |  POSITIONNEMENT DANS LE CYCLE ECONOMIQUE"), Spacer(1, 2 * mm)]

    claude_cycle = data["claude_cycle"]

    # Construction dynamique : on prend d'abord la valeur reelle de data["gdp_*"]
    # / data["cpi_*"], puis l'estimation Claude (pib_estime/cpi_estime) en repli,
    # puis "N/D".
    def cycle_value(zone, kind):
        """kind = 'pib' ou 'cpi'."""
        api_keys = {
            ("France", "pib"):     "gdp_fr",
            ("Etats-Unis", "pib"): "gdp_usa",
            ("Zone Euro", "pib"):  "gdp_ez",
            ("Chine", "pib"):      "gdp_chine",
            ("France", "cpi"):     "cpi_fr",
            ("Etats-Unis", "cpi"): "cpi_usa",
            ("Zone Euro", "cpi"):  "cpi_ez",
            ("Chine", "cpi"):      "cpi_chine",
        }
        # 1. API
        key = api_keys.get((zone, kind))
        if key:
            v = data.get(key, {}).get("val", "N/D")
            if v and v != "N/D":
                return v
        # 2. Estimation Claude (utile pour Amerique latine, Asie ex-Chine, ou en repli)
        claude_field = "pib_estime" if kind == "pib" else "cpi_estime"
        v_claude = claude_cycle.get(zone, {}).get(claude_field, "")
        if v_claude:
            return v_claude
        return "N/D"

    synth_hdr = ["Zone", "PIB", "Inflation", "Regime", "Commentaire Claude"]
    synth_cw = [28 * mm, 18 * mm, 18 * mm, 26 * mm, 68 * mm]
    synth_rows = []
    for zone, info in claude_cycle.items():
        regime = info.get("regime", "N/D")
        commentaire = info.get("commentaire", "")
        gdp_val = cycle_value(zone, "pib")
        cpi_val = cycle_value(zone, "cpi")
        rc = REGIME_COLORS.get(regime, GREY_TEXT)
        col_g = gdp_color(gdp_val)
        col_c = cpi_color(cpi_val)
        # Fleche directionnelle = signe de la valeur
        gv = parse_pct(gdp_val)
        cv = parse_pct(cpi_val)
        arw_g = "▲" if (gv is not None and gv > 0) else ("▼" if (gv is not None and gv < 0) else "■")
        arw_c = "▲" if (cv is not None and cv > 2) else ("▼" if (cv is not None and cv < 2) else "■")
        synth_rows.append([
            Paragraph(f"<b>{zone}</b>", label_style),
            Paragraph(f'<font color="#{h(col_g)}">{arw_g} {gdp_val}</font>', value_style),
            Paragraph(f'<font color="#{h(col_c)}">{arw_c} {cpi_val}</font>', value_style),
            Paragraph(f'<font color="#{h(rc)}"><b>{regime}</b></font>', value_style),
            Paragraph(commentaire, small_style)])
    story.append(std_table(synth_hdr, synth_rows, synth_cw))
    story.append(Spacer(1, 3 * mm))

    # Matrice 2x2
    zones_in = {(0, 0): [], (1, 0): [], (0, 1): [], (1, 1): []}
    regime_pos = {"Goldilocks": (0, 0), "Surchauffe": (1, 0),
                  "Obligations": (0, 1), "Stagflation": (1, 1)}
    for zone, info in claude_cycle.items():
        pos = regime_pos.get(info.get("regime", ""), None)
        if pos is not None:
            zones_in[pos].append(zone)

    labels_c = [
        ["GOLDILOCKS\nCroissance + Inflation bas\n-> Actions toutes classes",
         "SURCHAUFFE\nCroissance + Inflation hauts\n-> Mat. 1eres, Immo, Actions Value"],
        ["OBLIGATIONS D'ETAT\nCroissance bas + Inflation bas\n-> Duration, Souveraines",
         "STAGFLATION\nCroissance bas + Inflation haut\n-> Or, OATi, Cash / Monetaire"]]
    cw2 = col_w / 2

    def cycle_cell(txt, zones, active):
        lines = txt.split('\n')
        tc = TURQUOISE if active else BLUE
        cc = WHITE if active else GREY_TEXT
        rc = TURQUOISE if active else GREEN
        zc = colors.HexColor("#FFE066") if active else RED
        content = [
            Paragraph(f'<b>{lines[0]}</b>', S("c0", fontName="Helvetica-Bold", fontSize=8,
                                              textColor=tc, alignment=TA_CENTER)),
            Spacer(1, 1 * mm),
            Paragraph(lines[1] if len(lines) > 1 else "", S("c1", fontName="Helvetica",
                                                            fontSize=7, textColor=cc, alignment=TA_CENTER)),
            Spacer(1, 1 * mm),
            Paragraph(lines[2] if len(lines) > 2 else "", S("c2", fontName="Helvetica-Bold",
                                                            fontSize=7, textColor=rc, alignment=TA_CENTER))]
        if zones:
            content += [Spacer(1, 1 * mm),
                        Paragraph("★ " + " | ".join(zones),
                                  S("c3", fontName="Helvetica-Bold", fontSize=6.5,
                                    textColor=zc, alignment=TA_CENTER))]
        return content

    cycle_m = [[cycle_cell(labels_c[ri][ci], zones_in[(ci, ri)], len(zones_in[(ci, ri)]) > 0)
                for ci in range(2)] for ri in range(2)]
    t_cycle = Table(cycle_m, colWidths=[cw2] * 2, rowHeights=[28 * mm] * 2)
    t_cycle.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), NAVY if zones_in[(0, 0)] else LIGHT_BG),
        ('BACKGROUND', (1, 0), (1, 0), NAVY if zones_in[(1, 0)] else LIGHT_BG),
        ('BACKGROUND', (0, 1), (0, 1), NAVY if zones_in[(0, 1)] else LIGHT_BG),
        ('BACKGROUND', (1, 1), (1, 1), NAVY if zones_in[(1, 1)] else LIGHT_BG),
        ('GRID', (0, 0), (-1, -1), 1.5, TURQUOISE),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    story += [t_cycle, Spacer(1, 2 * mm)]
    story.append(note_box(data['commentaire_general']))

    # Vigilance + Opportunites
    v_txt = "<b>Points de vigilance :</b><br/>" + "<br/>".join(f"• {v}" for v in data["claude_vigilance"])
    o_txt = "<b>Opportunites identifiees :</b><br/>" + "<br/>".join(f"• {o}" for o in data["claude_opportunites"])
    story.append(Spacer(1, 2 * mm))
    t_vo = Table([[Paragraph(v_txt, S("vt", fontName="Helvetica", fontSize=7, textColor=NAVY, leading=11)),
                   Paragraph(o_txt, S("ot", fontName="Helvetica", fontSize=7, textColor=NAVY, leading=11))]],
                 colWidths=[col_w / 2] * 2)
    t_vo.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor("#FEF9EC")),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor("#EDF9F0")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story += [t_vo, Spacer(1, 4 * mm)]

    # ── 8. ALLOCATION ────────────────────────────────────────────────────────
    # CORRECTION : SCPI desormais incluse dans le dict icons
    alloc = data["claude_allocation"]
    story += [sec_hdr("8  |  ALLOCATION RECOMMANDEE - ANALYSE HEXA"), Spacer(1, 2 * mm)]
    alloc_hdr = ["Classe d'actif", "Recommandation HEXA"]
    alloc_cw = [38 * mm, 120 * mm]
    rows = []
    icons = {"actions": "Actions", "obligations": "Obligations",
             "matieres_premieres": "Matieres premieres", "immobilier": "Immobilier",
             "cash_monetaire": "Cash / Monetaire", "private_equity": "Private Equity",
             "scpi": "SCPI"}  # <-- SCPI ajoutee
    for key, label in icons.items():
        if key in alloc and alloc[key]:
            rows.append([Paragraph(f"<b>{label}</b>", label_style),
                         Paragraph(alloc[key], small_style)])
    story += [std_table(alloc_hdr, rows, alloc_cw), Spacer(1, 4 * mm)]

    # ── 9. MATIERES PREMIERES ────────────────────────────────────────────────
    story += [sec_hdr("9  |  COURS DES MATIERES PREMIERES"), Spacer(1, 2 * mm)]
    eurusd = data["eurusd"]
    units = {"Or": "$/oz", "Argent": "$/oz", "Cuivre": "$/lb",
             "Gaz naturel": "$/MMBtu", "Brent": "$/b"}
    commo_hdr = ["Matiere premiere", "Prix actuel", "Mois prec.", "A-1", "EUR (est.)", "Var. 1 an"]
    commo_cw = [30 * mm, 24 * mm, 22 * mm, 22 * mm, 24 * mm, 36 * mm]
    rows = []
    for name in ["Or", "Argent", "Cuivre", "Gaz naturel", "Brent"]:
        c = data["commodities"].get(name)
        if c:
            val, prev, n1 = c["val"], c["prev_m"], c["n1"]
            arw, ac = arrow(str(val), str(prev))
            pct = ((val - n1) / n1 * 100) if n1 else 0
            pc = GREEN if pct >= 0 else RED
            unit = units.get(name, "")
            if name in ("Or", "Argent"):
                act_str = f"{val:,.0f} {unit}"
                eur_str = f"{val/eurusd:,.0f} €/oz"
                prev_str = f"~{prev:,.0f}"
                n1_str = f"~{n1:,.0f}"
            else:
                act_str = f"{val:.2f} {unit}"
                eur_str = f"{val/eurusd:.2f} €"
                prev_str = f"~{prev:.2f}"
                n1_str = f"~{n1:.2f}"
            rows.append([
                Paragraph(f"<b>{name}</b>", label_style),
                Paragraph(f'<b>{act_str}</b> <font color="#{h(ac)}">{arw}</font>', value_style),
                Paragraph(prev_str, small_style),
                Paragraph(n1_str, small_style),
                Paragraph(eur_str, small_style),
                Paragraph(f'<font color="#{h(pc)}"><b>{pct:+.1f}%</b></font>', value_style)])
    story.append(std_table(commo_hdr, rows, commo_cw))
    story += [Spacer(1, 1 * mm),
              Paragraph(f"Sources : Yahoo Finance (futures). EUR/USD = {eurusd:.3f}.",
                        S("s1", fontName="Helvetica-Oblique", fontSize=5.5, textColor=GREY_TEXT)),
              Spacer(1, 4 * mm)]

    # ── 10. PRIX IMMOBILIER ──────────────────────────────────────────────────
    story += [sec_hdr("10  |  PRIX IMMOBILIER AU m2 - VILLES SELECTIONNEES"), Spacer(1, 2 * mm)]
    t_leg = Table([[Paragraph(
        "Source : DVF (Demandes de Valeurs Foncieres) - data.gouv.fr / Notaires de France. "
        "Prix medians transactions reelles. Delai publication ~6 mois.",
        note_style)]], colWidths=[col_w])
    t_leg.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('LINEBEFORE', (0, 0), (0, -1), 3, TURQUOISE)]))
    story += [t_leg, Spacer(1, 3 * mm)]

    prix_hdr = ["Ville / Secteur", "Prix median", "Var. 1 an", "Var. 5 ans", "Periode", "Source"]
    prix_cw = [46 * mm, 28 * mm, 22 * mm, 22 * mm, 20 * mm, 40 * mm]
    rows = []
    for ville, d in data["immo_prix"].items():
        c1 = GREEN if d["var_1an"] >= 0 else RED
        c5 = GREEN if d["var_5ans"] >= 0 else RED
        a1 = "▲" if d["var_1an"] >= 0 else "▼"
        a5 = "▲" if d["var_5ans"] >= 0 else "▼"
        rows.append([
            Paragraph(f"<b>{ville}</b>", label_style),
            Paragraph(f"<b>{d['val']:,} euros/m²</b>", value_style),
            Paragraph(f'<font color="#{h(c1)}">{a1} {d["var_1an"]:+.1f}%</font>', value_style),
            Paragraph(f'<font color="#{h(c5)}">{a5} {d["var_5ans"]:+.1f}%</font>', value_style),
            Paragraph(d["periode"], small_style),
            Paragraph(d.get("source", "DVF"), note_style)])
    story.append(std_table(prix_hdr, rows, prix_cw))
    story += [Spacer(1, 2 * mm),
              note_box(data['claude_synthese_immo']),
              Spacer(1, 4 * mm)]

    # ── 11. TAUX DE REFERENCE ────────────────────────────────────────────────
    story += [sec_hdr("11  |  TAUX DE REFERENCE - IMMOBILIER & CREDIT PRIVE"), Spacer(1, 2 * mm)]
    e = data["euribor"]
    immo_t = data["immobilier_taux"]
    # Affichage propre du Prec. / A-1 Euribor : evite "N/D (N/D)"
    def _fmt_period(v, d):
        if not v or v == "N/D":
            return "N/D"
        if not d or d == "N/D":
            return v
        return f'{v} ({d})'
    e_prev_str = _fmt_period(e["prev"], e["prev_date"])
    e_n1_str   = _fmt_period(e["n1"],   e["n1_date"])
    taux_hdr = ["Taux", "Valeur actuelle", "Prec.", "A-1", "Role & Commentaire"]
    taux_cw = [36 * mm, 24 * mm, 28 * mm, 24 * mm, 46 * mm]
    taux_rows = [
        [Paragraph("Euribor 3 mois", label_style),
         Paragraph(f'<font color="#{h(GREEN)}"><b>{e["val"]}</b></font>', value_style),
         Paragraph(e_prev_str, small_style),
         Paragraph(e_n1_str, small_style),
         Paragraph("Taux court terme BCE. Indexe credits immo variables et dettes LBO.", note_style)],
        [Paragraph("OAT 10 ans (France)", label_style),
         Paragraph(f'<font color="#{h(ORANGE)}"><b>{data["spread"]["oat"]}</b></font>', value_style),
         Paragraph("N/D", small_style), Paragraph("N/D", small_style),
         Paragraph("Taux sans risque de reference. Indexe taux immo 20 ans et prime PE.", note_style)],
        [Paragraph("Taux immo 20 ans moyen", label_style),
         Paragraph(f'<font color="#{h(ORANGE)}"><b>{immo_t["taux_20ans"]}</b></font>', value_style),
         Paragraph(immo_t["taux_20ans_prev"], small_style),
         Paragraph(immo_t["taux_20ans_n1"], small_style),
         Paragraph(immo_t["taux_20ans_commentaire"], note_style)],
        [Paragraph("Rendement minimal PE attendu", label_style),
         Paragraph("<b>OAT + 6,5%</b>", value_style),
         Paragraph("~10,6% (T4 2025)", small_style),
         Paragraph("~12,1% (T1 2025)", small_style),
         Paragraph("OAT 10 ans + prime PE historique 6,5%.", note_style)],
        [Paragraph("Spread credit IG (Investment Grade)", label_style),
         Paragraph(f'<font color="#{h(ig_c)}"><b>{ig_bps}</b></font> <font color="#{h(col_ig)}">{arw_ig}</font>', value_style),
         Paragraph(ig_prev_bps, small_style),
         Paragraph(ig_n1_bps, small_style),
         Paragraph("Prime de risque obligations Investment Grade. Signal de stress si > 180 bps.", note_style)],
        [Paragraph("Spread credit HY (High Yield)", label_style),
         Paragraph(f'<font color="#{h(hy_c)}"><b>{hy_bps}</b></font> <font color="#{h(col_hy)}">{arw_hy}</font>', value_style),
         Paragraph(hy_prev_bps, small_style),
         Paragraph(hy_n1_bps, small_style),
         Paragraph("Prime de risque High Yield. Pertinent pour fonds obligs dates. Signal d'alerte si > 600 bps.", note_style)],
    ]
    story += [std_table(taux_hdr, taux_rows, taux_cw), Spacer(1, 4 * mm)]

    # ── 12. PRIVATE EQUITY ───────────────────────────────────────────────────
    story += [sec_hdr("12  |  PRIVATE EQUITY - INDICATEURS DU SECTEUR"), Spacer(1, 2 * mm)]
    pe = data["private_equity"]
    argos = pe["argos"]
    sw3 = col_w / 3

    # Helper local : adapte la taille de la police selon la longueur de la chaine pour eviter le debordement
    def _kpi_font_size(s, ref_chars=8):
        n = len(str(s))
        if n <= ref_chars:    return 24
        if n <= ref_chars+4:  return 20
        if n <= ref_chars+8:  return 16
        if n <= ref_chars+14: return 13
        return 11

    argos_size = _kpi_font_size(argos[0])
    dp_size    = _kpi_font_size(pe["dp"][0])
    rdt_size   = _kpi_font_size(pe["rdt"][0])

    t_kpi = Table([
        [Paragraph("Multiple EV/EBITDA Mid-Market", label_style),
         Paragraph("Dry Powder mondial", label_style),
         Paragraph("Rendement net PE France (10 ans)", label_style)],
        # Style local avec leading proportionnel a la taille pour eviter le chevauchement
        # entre le gros chiffre et sa caption (corrige le bug visuel v6.2).
        [Paragraph(f'<font size="{argos_size}" color="#{h(NAVY_LIGHT)}"><b>{argos[0]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">Indice Argos Mid-Market</font>',
                   S("kpi_a", fontName="Helvetica", fontSize=argos_size, leading=argos_size + 6, alignment=TA_CENTER)),
         Paragraph(f'<font size="{dp_size}" color="#{h(TURQUOISE)}"><b>{pe["dp"][0]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">{pe["dp"][1]} {pe["dp"][2]}</font>',
                   S("kpi_d", fontName="Helvetica", fontSize=dp_size, leading=dp_size + 6, alignment=TA_CENTER)),
         Paragraph(f'<font size="{rdt_size}" color="#{h(GREEN)}"><b>{pe["rdt"][0]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">{pe["rdt"][1]}</font>',
                   S("kpi_r", fontName="Helvetica", fontSize=rdt_size, leading=rdt_size + 6, alignment=TA_CENTER))],
        [Paragraph(f'Prec. : {argos[1]} ({argos[2]})<br/>A-1 : {argos[3]} ({argos[4]})<br/>'
                   f'<font color="#{h(RED)}">Compression des multiples</font>', small_style),
         Paragraph("Capitaux non investis mondiaux.<br/>Pression sur valorisations.", small_style),
         Paragraph("Source : France Invest<br/>Rapport annuel 2025", small_style)],
        [Paragraph("Source : Argos Mid-Market", note_style),
         Paragraph("Source : Bain Global PE Report", note_style),
         Paragraph("Source : France Invest", note_style)],
    ], colWidths=[sw3] * 3)
    t_kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BACKGROUND', (0, 1), (-1, 1), WHITE),
        ('BACKGROUND', (0, 2), (-1, 2), WHITE),
        ('BACKGROUND', (0, 3), (-1, 3), LIGHT_BG),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        # Bloc KPI : padding important pour reserver l'espace au gros chiffre + caption
        ('TOPPADDING', (0, 1), (-1, 1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 12),
        # Bloc commentaire : padding genereux pour respirer
        ('TOPPADDING', (0, 2), (-1, 2), 8),
        ('BOTTOMPADDING', (0, 2), (-1, 2), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 1, TURQUOISE)]))
    story += [t_kpi, Spacer(1, 3 * mm)]

    fi_hdr = ["Indicateur", "Dernier publie", "Var.", "Commentaire"]
    fi_cw = [40 * mm, 24 * mm, 32 * mm, 62 * mm]
    fi_rows = [
        [Paragraph("Levees de fonds", label_style),
         Paragraph(f'<b>{pe["levees"][0]}</b>', value_style),
         Paragraph(f'<font color="#{h(RED)}"><b>{pe["levees"][1]}</b></font>', value_style),
         Paragraph("Recul lie a la hausse des taux. Attentisme des LP institutionnels.", note_style)],
        [Paragraph("Montants investis", label_style),
         Paragraph(f'<b>{pe["invest"][0]}</b>', value_style),
         Paragraph(f'<font color="#{h(RED)}"><b>{pe["invest"][1]}</b></font>', value_style),
         Paragraph("LBO ralenti. Venture & Growth resistants.", note_style)],
        [Paragraph("Cessions / desinvestissements", label_style),
         Paragraph(f'<b>{pe["cessions"][0]}</b>', value_style),
         Paragraph(f'<font color="#{h(RED)}"><b>{pe["cessions"][1]}</b></font>', value_style),
         Paragraph("Marche secondaire actif.", note_style)],
        [Paragraph("Entreprises en portefeuille", label_style),
         Paragraph(f'<b>{pe["nb_ent"][0]}</b>', value_style),
         Paragraph(f'<font color="#{h(GREEN)}"><b>{pe["nb_ent"][1]}</b></font>', value_style),
         Paragraph("PME/ETI majoritaires.", note_style)],
    ]
    story.append(std_table(fi_hdr, fi_rows, fi_cw))
    story += [Spacer(1, 2 * mm),
              note_box(data['claude_synthese_pe']),
              Spacer(1, 3 * mm)]

    # ── 13. SCPI ─────────────────────────────────────────────────────────────
    # CORRECTION : renumerotee 13 (etait 14) ; largeur TD elargie pour eviter le saut de ligne
    scpi = data["scpi"]
    mkt = scpi["marche"]

    story += [sec_hdr("13  |  SCPI - MARCHE ET ANALYSE PAR ACTIFS"), Spacer(1, 2 * mm)]

    arw_td, col_td = arrow(mkt["td_moyen"], mkt["td_moyen_prev"])
    arw_col, col_col = arrow(mkt["collecte_nette"], mkt["collecte_prev"])
    arw_dec, col_dec = arrow(mkt["decote_secondaire"], mkt["decote_prev"])

    sw4 = col_w / 4
    t_mkt = Table([
        [Paragraph("TD moyen marche", label_style),
         Paragraph("Collecte nette", label_style),
         Paragraph("Decote secondaire", label_style),
         Paragraph("TOF moyen", label_style)],
        # Taille reduite a 14pt pour eviter le retour a la ligne de "(annualise)"
        [Paragraph(f'<font size="14" color="#{h(GREEN)}"><b>{mkt["td_moyen"]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">Taux de distribution</font>', value_style),
         Paragraph(f'<font size="14" color="#{h(col_col)}"><b>{mkt["collecte_nette"]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">{mkt["collecte_periode"]}</font>', value_style),
         Paragraph(f'<font size="14" color="#{h(RED)}"><b>{mkt["decote_secondaire"]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">Marche secondaire</font>', value_style),
         Paragraph(f'<font size="14" color="#{h(GREEN)}"><b>{mkt["tof_moyen"]}</b></font><br/>'
                   f'<font size="7" color="#5D6D7E">Taux occupation financier</font>', value_style)],
        [Paragraph(f'Prec.: {mkt["td_moyen_prev"]} <font color="#{h(col_td)}">{arw_td}</font>'
                   f' | A-1: {mkt["td_moyen_n1"]}', small_style),
         Paragraph(f'Prec.: {mkt["collecte_prev"]} <font color="#{h(col_col)}">{arw_col}</font>', small_style),
         Paragraph(f'Prec.: {mkt["decote_prev"]} <font color="#{h(col_dec)}">{arw_dec}</font>', small_style),
         Paragraph(f'Source : {mkt["source"]}', small_style)],
    ], colWidths=[sw4] * 4)
    t_mkt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BACKGROUND', (0, 1), (-1, 1), WHITE),
        ('BACKGROUND', (0, 2), (-1, 2), LIGHT_BG),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, 0), 1, TURQUOISE)]))
    story += [t_mkt, Spacer(1, 3 * mm)]

    # Par secteur
    story.append(Paragraph("<b>Analyse par secteur d'actifs :</b>",
                           S("st", fontName="Helvetica-Bold", fontSize=8,
                             textColor=NAVY, spaceAfter=3)))
    story.append(Spacer(1, 1 * mm))

    sect_hdr = ["Secteur", "Poids", "TD moyen", "Tendance", "Commentaire"]
    sect_cw = [30 * mm, 16 * mm, 20 * mm, 18 * mm, 74 * mm]
    rows = []
    tend_colors = {"▲": GREEN, "▼": RED, "▶": GREY_TEXT, "■": GREY_TEXT}
    for s in scpi["par_secteur"]:
        tc = tend_colors.get(s["tendance"], GREY_TEXT)
        rows.append([
            Paragraph(f'<b>{s["secteur"]}</b>', label_style),
            Paragraph(s["poids"], small_style),
            Paragraph(f'<font color="#{h(GREEN)}"><b>{s["td"]}</b></font>', value_style),
            Paragraph(f'<font color="#{h(tc)}"><b>{s["tendance"]}</b></font>', value_style),
            Paragraph(s["commentaire"], small_style)])
    story += [std_table(sect_hdr, rows, sect_cw), Spacer(1, 3 * mm)]

    # SCPI top 10 par collecte v6.5.2
    story.append(Paragraph("<b>Top 10 SCPI par collecte nette — classement annuel :</b>",
                           S("st2", fontName="Helvetica-Bold", fontSize=8,
                             textColor=NAVY, spaceAfter=3)))
    story.append(Spacer(1, 1 * mm))

    # Colonnes : Rang / SCPI / Gestionnaire / Secteur / Collecte / TD / TOF / Prix part / Var. prix / Note
    scpi_hdr = ["#", "SCPI", "Gestionnaire", "Secteur", "Collecte", "TD", "TOF", "Prix part", "Var.", "Note"]
    scpi_cw = [8 * mm, 22 * mm, 20 * mm, 17 * mm, 16 * mm, 14 * mm, 12 * mm, 14 * mm, 12 * mm, 23 * mm]
    rows = []
    top10 = scpi.get("scpi_top10", [])
    for idx, s in enumerate(top10[:10], start=1):
        vp_raw = s.get("var_prix", "")
        if vp_raw.startswith("+"):
            vp_c = GREEN
        elif vp_raw.startswith("-"):
            vp_c = RED
        else:
            vp_c = GREY_TEXT
        rows.append([
            Paragraph(f"<b>{idx}</b>", value_style),
            Paragraph(f'<b>{s.get("nom","N/D")}</b>', label_style),
            Paragraph(s.get("gestionnaire", ""), small_style),
            Paragraph(s.get("secteur", ""), small_style),
            Paragraph(f'<b>{s.get("collecte", "N/D")}</b>', small_style),
            Paragraph(f'<font color="#{h(GREEN)}"><b>{s.get("td","")}</b></font>', value_style),
            Paragraph(s.get("tof", ""), small_style),
            Paragraph(f'<b>{s.get("prix_part","")}</b>', small_style),
            Paragraph(f'<font color="#{h(vp_c)}"><b>{vp_raw}</b></font>', small_style),
            Paragraph(s.get("note", ""), note_style)])
    # Si moins de 10 SCPI collectees, on n'affiche que celles disponibles avec une mention
    if not rows:
        rows.append([Paragraph("-", small_style)] * 10)
    story += [std_table(scpi_hdr, rows, scpi_cw), Spacer(1, 2 * mm)]
    if 0 < len(top10) < 10:
        story.append(Paragraph(
            f"<i>{len(top10)} SCPI collectees sur 10 demandees. "
            "Le reste sera complete au prochain run.</i>",
            S("st2", fontName="Helvetica-Oblique", fontSize=7, textColor=GREY_TEXT, spaceAfter=2)))
        story.append(Spacer(1, 1 * mm))

    story.append(note_box(scpi["analyse"]))
    story.append(Spacer(1, 2 * mm))

    v_scpi = "<b>Points de vigilance SCPI :</b><br/>" + "<br/>".join(f"• {v}" for v in scpi["points_vigilance"])
    o_scpi = "<b>Opportunites SCPI :</b><br/>" + "<br/>".join(f"• {o}" for o in scpi["opportunites"])
    t_vo_scpi = Table([
        [Paragraph(v_scpi, S("vs", fontName="Helvetica", fontSize=7, textColor=NAVY, leading=11)),
         Paragraph(o_scpi, S("os", fontName="Helvetica", fontSize=7, textColor=NAVY, leading=11))]],
        colWidths=[col_w / 2] * 2)
    t_vo_scpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor("#FEF9EC")),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor("#EDF9F0")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story += [t_vo_scpi, Spacer(1, 4 * mm)]

    # ── 14. IMMOBILIER MARCHE (etait 15) ─────────────────────────────────────
    # CORRECTION : ligne "Taux credit 20 ans" supprimee car deja en Section 11
    # CORRECTION : header_white_style pour rendre l'entete visible (fond NAVY_LIGHT)
    story += [sec_hdr("14  |  IMMOBILIER FRANCE - MARCHE LOCATIF"), Spacer(1, 2 * mm)]
    immo_table = Table([
        [Paragraph("Indicateur", header_white_style),
         Paragraph("Valeur", header_white_style),
         Paragraph("Ref. precedente", header_white_style),
         Paragraph("A-1", header_white_style),
         Paragraph("Commentaire", header_white_style)],
        [Paragraph("Bureaux vacants IDF (taux)", value_style),
         Paragraph(f'<b>{immo_t["bureaux_val"]}</b>', value_style),
         Paragraph(immo_t["bureaux_prev"], small_style),
         Paragraph(immo_t["bureaux_n1"], small_style),
         Paragraph(immo_t["bureaux_commentaire"], note_style)],
        [Paragraph("Surfaces commerciales (taux prime)", value_style),
         Paragraph(f'<b>{immo_t["commerces_val"]}</b>', value_style),
         Paragraph(immo_t["commerces_prev"], small_style),
         Paragraph(immo_t["commerces_n1"], small_style),
         Paragraph(immo_t["commerces_commentaire"], note_style)]],
        colWidths=[40 * mm, 24 * mm, 38 * mm, 24 * mm, 32 * mm])
    immo_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY_LIGHT),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, DARK_ROW]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor("#B0C4C4")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 1, TURQUOISE)]))
    story += [immo_table, Spacer(1, 2 * mm)]

    # Sources
    story += [
        HRFlowable(width="100%", thickness=0.8, color=TURQUOISE),
        Spacer(1, 1 * mm),
        Paragraph(
            "<b>Sources officielles :</b> INSEE - Eurostat (flash) - BEA - BLS - ECB SDW - "
            "Fed (FRED DFEDTARU / H.15) - S&P Global PMI / HCOB - CBOE - CNN Business - "
            "Yahoo Finance - FRED - Banque de France - CAFPI - DVF / data.gouv.fr - "
            "Notaires de France - Banque Mondiale - France Invest - Argos Mid-Market - "
            "Bain PE Report - FMI WEO.",
            S("srcs", fontName="Helvetica", fontSize=5.5, textColor=GREY_TEXT, leading=8))]

    doc.build(story)
    return output_path
