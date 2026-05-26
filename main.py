"""
Point d'entrée — GitHub Actions, le 2 de chaque mois.
Flux : APIs → Claude web_search → Analyse Claude → PDF → Email
"""
import os
import sys
import smtplib
import datetime
import shutil
import importlib.util
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
    gmail_user = os.environ.get("GMAIL_USER","")
    gmail_pass = os.environ.get("GMAIL_APP_PASS","")
    recipients_raw = os.environ.get("RECIPIENTS","")

    if not gmail_user or not gmail_pass or not recipients_raw:
        print("  Variables email manquantes — email non envoye")
        return False

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        print("  Aucun destinataire — email non envoye")
        return False

    print(f"  Envoi a : {', '.join(recipients)}")

    subject = f"Tableau de bord HEXA Patrimoine – {date_str}"

    commentaire  = analysis.get("commentaire_general","Analyse disponible en PDF.")
    vigilance    = "\n".join(f"  - {v}" for v in analysis.get("points_vigilance",[]))
    opportunites = "\n".join(f"  - {o}" for o in analysis.get("opportunites",[]))

    body = f"""Bonjour,

Veuillez trouver en piece jointe le tableau de bord HEXA Patrimoine de {date_str}.

SYNTHESE DU MOIS :
{commentaire}

POINTS DE VIGILANCE :
{vigilance}

OPPORTUNITES :
{opportunites}

Le rapport complet est en piece jointe.

Cordialement,
HEXA Patrimoine
"""
    try:
        msg = MIMEMultipart()
        msg["From"]    = gmail_user
        msg["To"]      = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Pièce jointe PDF
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = Path(pdf_path).name
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

        # Envoi
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipients, msg.as_string())

        print(f"  Email envoye avec succes a : {', '.join(recipients)}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        print(f"  Erreur authentification Gmail: {e}")
        print("  Verifiez GMAIL_USER et GMAIL_APP_PASS dans les secrets GitHub")
        return False
    except smtplib.SMTPException as e:
        print(f"  Erreur SMTP: {e}")
        return False
    except Exception as e:
        print(f"  Erreur email inattendue: {e}")
        return False


def main():
    today    = datetime.date.today()
    mois_fr  = ["janvier","fevrier","mars","avril","mai","juin",
                "juillet","aout","septembre","octobre","novembre","decembre"]
    date_str = f"{mois_fr[today.month-1].capitalize()} {today.year}"
    print(f"=== Tableau de bord HEXA Patrimoine – {date_str} ===")

    # 1. Collecte APIs
    print("\n[1/4] Collecte des donnees (APIs)...")
    data = collect_all()

    # 2. Claude web_search + analyse
    print("\n[2/4] Recherche web + Analyse Claude...")
    try:
        analysis, dynamic_data = get_analysis(data)
    except Exception as e:
        print(f"  Erreur Claude: {e} — utilisation fallbacks")
        analysis = {
            "commentaire_general": f"Analyse indisponible pour {date_str}.",
            "analyse_cycle": {},
            "points_vigilance": [], "opportunites": [],
            "allocation_recommandee": {},
            "synthese_immobilier": "", "synthese_pe": "",
            "synthese_scpi": "", "analyse_courbe_taux": "",
            "analyse_credit": "",
        }
        dynamic_data = {}

    # 3. Injecter commentaires Claude dans data
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

    # 4. Génération PDF
    print("\n[3/4] Generation PDF...")
    pdf_name = f"Dashboard_HEXA_{today.strftime('%B_%Y')}.pdf"
    pdf_path = Path("/tmp") / pdf_name

    try:
        generate_pdf(data, str(pdf_path))
        print(f"  PDF genere : {pdf_path}")
    except Exception as e:
        print(f"  Erreur generation PDF: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Copier dans artifacts
    artifact_dir = ROOT / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    artifact_path = artifact_dir / pdf_name
    shutil.copy(pdf_path, artifact_path)
    print(f"  PDF copie dans artifacts : {artifact_path}")

    # 5. Envoi email
    print("\n[4/4] Envoi email...")
    email_ok = send_email(str(pdf_path), analysis, date_str)

    if not email_ok:
        print("  Email non envoye mais PDF disponible dans les Artifacts GitHub")

    print(f"\n=== Termine : {date_str} ===")
    # Ne pas faire sys.exit(1) si email échoue — le PDF est généré
    # Le workflow réussit même sans email


if __name__ == "__main__":
    main()
