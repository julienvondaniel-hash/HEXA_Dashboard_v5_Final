"""
Point d'entrée — GitHub Actions, le 2 de chaque mois.
Flux : APIs → Claude web_search → Analyse Claude → PDF → Email
100% automatique, aucune intervention manuelle requise.
"""
import os, sys, smtplib, datetime, shutil, importlib.util
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

dashboard_mod    = load_module("dashboard",       ROOT/"src"/"dashboard.py")
generate_pdf_mod = load_module("generate_pdf",    ROOT/"src"/"generate_pdf.py")
claude_mod       = load_module("claude_analysis", ROOT/"src"/"claude_analysis.py")

collect_all  = dashboard_mod.collect_all
generate_pdf = generate_pdf_mod.generate_pdf
get_analysis = claude_mod.get_claude_analysis


def send_email(pdf_path: str, analysis: dict, date_str: str):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASS"]
    recipients = [r.strip() for r in os.environ.get("RECIPIENTS","").split(",") if r.strip()]

    subject    = f"Tableau de bord HEXA Patrimoine – {date_str}"
    commentaire  = analysis.get("commentaire_general","")
    vigilance    = "\n".join(f"  • {v}" for v in analysis.get("points_vigilance",[]))
    opportunites = "\n".join(f"  • {o}" for o in analysis.get("opportunites",[]))
    scpi_note    = analysis.get("synthese_scpi","")
    courbe_note  = analysis.get("analyse_courbe_taux","")

    body = f"""Bonjour,

Veuillez trouver en piece jointe le tableau de bord HEXA Patrimoine de {date_str}.

SYNTHESE DU MOIS :
{commentaire}

COURBE DES TAUX US :
{courbe_note}

POINTS DE VIGILANCE :
{vigilance}

OPPORTUNITES IDENTIFIEES :
{opportunites}

SCPI DU MOIS :
{scpi_note}

Le rapport complet (15 sections) est en piece jointe.

Cordialement,
HEXA Patrimoine — Tableau de bord automatique
"""
    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body,"plain","utf-8"))

    with open(pdf_path,"rb") as f:
        part = MIMEBase("application","pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{Path(pdf_path).name}"')
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, recipients, msg.as_string())
    print(f"Email envoye a : {', '.join(recipients)}")


def main():
    today    = datetime.date.today()
    mois_fr  = ["janvier","fevrier","mars","avril","mai","juin",
                "juillet","aout","septembre","octobre","novembre","decembre"]
    date_str = f"{mois_fr[today.month-1].capitalize()} {today.year}"
    print(f"=== Tableau de bord HEXA Patrimoine – {date_str} ===")

    # 1. APIs officielles
    print("\n[1/4] Collecte APIs...")
    data = collect_all()

    # 2. Claude web_search + analyse
    print("\n[2/4] Recherche web + Analyse Claude...")
    analysis, dynamic_data = get_analysis(data)

    # 3. Commentaires Claude → data
    data["commentaire_general"]    = analysis.get("commentaire_general","")
    data["claude_cycle"]           = analysis.get("analyse_cycle",{})
    data["claude_vigilance"]       = analysis.get("points_vigilance",[])
    data["claude_opportunites"]    = analysis.get("opportunites",[])
    data["claude_allocation"]      = analysis.get("allocation_recommandee",{})
    data["claude_synthese_immo"]   = analysis.get("synthese_immobilier","")
    data["claude_synthese_pe"]     = analysis.get("synthese_pe","")
    data["claude_synthese_scpi"]   = analysis.get("synthese_scpi","")
    data["claude_courbe_taux"]     = analysis.get("analyse_courbe_taux","")
    data["claude_credit"]          = analysis.get("analyse_credit","")

    # 4. PDF
    print("\n[3/4] Generation PDF...")
    pdf_name = f"Dashboard_HEXA_{today.strftime('%B_%Y')}.pdf"
    pdf_path = Path("/tmp") / pdf_name
    generate_pdf(data, str(pdf_path))
    print(f"PDF : {pdf_path}")

    artifact_dir = ROOT / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    shutil.copy(pdf_path, artifact_dir / pdf_name)

    # 5. Email
    print("\n[4/4] Envoi email...")
    if all(os.environ.get(k) for k in ["GMAIL_USER","GMAIL_APP_PASS","RECIPIENTS"]):
        send_email(str(pdf_path), analysis, date_str)
    else:
        print("Variables email non configurees — PDF genere uniquement.")

    print(f"\n✅ Tableau de bord HEXA {date_str} genere avec succes !")


if __name__ == "__main__":
    main()
