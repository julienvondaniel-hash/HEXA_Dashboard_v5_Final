"""
HEXA Patrimoine - main.py v7.0
==============================
Point d'entree GitHub Actions, le 2 de chaque mois.

Architecture v7.0 :
  [1/3] APIs structurees (dashboard.collect_all)
  [2/3] 1 seul appel Claude (claude_analysis.run_analysis)
  [3/3] PDF + Email

Aucune intervention manuelle requise.
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

# Force le flush immediat de stdout/stderr pour que les logs GitHub Actions
# s'affichent en temps reel et non par blocs apres plusieurs minutes.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dashboard_mod    = load_module("dashboard",       ROOT / "src" / "dashboard.py")
generate_pdf_mod = load_module("generate_pdf",    ROOT / "src" / "generate_pdf.py")
claude_mod       = load_module("claude_analysis", ROOT / "src" / "claude_analysis.py")

collect_all  = dashboard_mod.collect_all
generate_pdf = generate_pdf_mod.generate_pdf
run_analysis = claude_mod.run_analysis


def send_email(pdf_path: str, data: dict, date_str: str):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASS"]
    recipients = [r.strip() for r in os.environ.get("RECIPIENTS", "").split(",") if r.strip()]

    subject = f"Tableau de bord HEXA Patrimoine - {date_str}"
    commentaire  = data.get("commentaire_general", "")
    vigilance    = "\n".join(f"  - {v}" for v in data.get("claude_vigilance", []))
    opportunites = "\n".join(f"  - {o}" for o in data.get("claude_opportunites", []))
    scpi_note    = data.get("claude_synthese_scpi", "")

    body = f"""Bonjour,

Veuillez trouver en piece jointe le tableau de bord HEXA Patrimoine de {date_str}.

SYNTHESE DU MOIS :
{commentaire}

POINTS DE VIGILANCE :
{vigilance}

OPPORTUNITES IDENTIFIEES :
{opportunites}

SCPI DU MOIS :
{scpi_note}

Le rapport complet (14 sections) est en piece jointe.

Cordialement,
HEXA Patrimoine - Tableau de bord automatique
"""
    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{Path(pdf_path).name}"')
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, recipients, msg.as_string())
        print(f"  Email envoye a : {', '.join(recipients)}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"  Erreur authentification Gmail: {e}")
        print(f"  Verifiez GMAIL_USER et GMAIL_APP_PASS dans les secrets GitHub")
        print(f"  Le mot de passe doit etre un 'mot de passe d application' Gmail (16 caracteres),")
        print(f"  pas le mot de passe principal du compte. Voir : https://myaccount.google.com/apppasswords")
        print(f"  Email non envoye mais PDF disponible dans les Artifacts GitHub")
    except Exception as e:
        print(f"  Erreur envoi email: {type(e).__name__}: {e}")
        print(f"  Email non envoye mais PDF disponible dans les Artifacts GitHub")


def main():
    today    = datetime.date.today()
    mois_fr  = ["Janvier", "Fevrier", "Mars", "Avril", "Mai", "Juin",
                "Juillet", "Aout", "Septembre", "Octobre", "Novembre", "Decembre"]
    date_str = f"{mois_fr[today.month - 1]} {today.year}"
    print(f"=== Tableau de bord HEXA Patrimoine v7.0 - {date_str} ===")

    # [1/3] Collecte APIs structurees
    print("\n[1/3] Collecte des donnees (APIs)...")
    data = collect_all()

    # [2/3] Analyse Claude (un seul appel)
    print("\n[2/3] Analyse Claude (1 seul appel)...")
    data = run_analysis(data)

    # [3/3] Generation PDF + envoi email
    print("\n[3/3] Generation PDF et envoi email...")
    pdf_name = f"Dashboard_HEXA_{mois_fr[today.month - 1]}_{today.year}.pdf"
    pdf_path = Path("/tmp") / pdf_name
    generate_pdf(data, str(pdf_path))
    print(f"  PDF genere : {pdf_path}")

    artifact_dir = ROOT / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    shutil.copy(pdf_path, artifact_dir / pdf_name)
    print(f"  PDF copie dans artifacts : {artifact_dir / pdf_name}")

    # Envoi email
    if all(os.environ.get(k) for k in ["GMAIL_USER", "GMAIL_APP_PASS", "RECIPIENTS"]):
        send_email(str(pdf_path), data, date_str)
    else:
        print("  Variables email non configurees - PDF genere uniquement.")

    print(f"\n=== Termine : {date_str} ===")


if __name__ == "__main__":
    main()
