"""Envoi du rapport en pièce jointe par e-mail (SMTP de la messagerie de l'abonné)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

KEYRING_SERVICE = "VigieFreebox-SMTP"

# Réglages usuels des messageries ; l'utilisateur peut toujours choisir « Autre ».
PRESETS = {
    "Free (adresse @free.fr)": ("smtp.free.fr", 465, "ssl"),
    "Gmail (mot de passe d'application)": ("smtp.gmail.com", 465, "ssl"),
    "Orange": ("smtp.orange.fr", 465, "ssl"),
    "SFR": ("smtp.sfr.fr", 465, "ssl"),
    "Laposte.net": ("smtp.laposte.net", 465, "ssl"),
    "Yahoo": ("smtp.mail.yahoo.com", 465, "ssl"),
    "iCloud": ("smtp.mail.me.com", 587, "starttls"),
    "Autre": (None, None, None),
}


# ------------------------------------------------------------------ mot de passe
def get_password(store) -> str:
    try:
        import keyring
        pw = keyring.get_password(KEYRING_SERVICE, store.config.get("smtp_user") or "default")
        if pw:
            return pw
    except Exception:
        pass
    return store.config.get("smtp_password_local") or ""


def set_password(store, password: str) -> str:
    """Range le mot de passe dans le trousseau du système ; à défaut dans la configuration locale."""
    user = store.config.get("smtp_user") or "default"
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, user, password)
        store.config.pop("smtp_password_local", None)
        store.save_config()
        return "trousseau"
    except Exception:
        store.set("smtp_password_local", password)
        return "local"


# ------------------------------------------------------------------ envoi
def recipients(cfg: dict) -> list[str]:
    raw = (cfg.get("email_to") or "").replace(";", ",")
    return [x.strip() for x in raw.split(",") if x.strip()]


def send(cfg: dict, password: str, subject: str, body: str, attachments=(), to=None, timeout=30):
    to = to or recipients(cfg)
    if not to:
        raise ValueError("aucune adresse de destination")
    host = (cfg.get("smtp_host") or "").strip()
    if not host:
        raise ValueError("serveur d'envoi (SMTP) non renseigné")
    port = int(cfg.get("smtp_port") or 465)
    sender = (cfg.get("smtp_from") or cfg.get("smtp_user") or to[0]).strip()

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] if "@" in sender else None)
    msg.set_content(body)
    for p in attachments:
        p = Path(p)
        sub = {"pdf": ("application", "pdf"), "txt": ("text", "plain"), "html": ("text", "html")}.get(
            p.suffix.lower().lstrip("."), ("application", "octet-stream"))
        msg.add_attachment(p.read_bytes(), maintype=sub[0], subtype=sub[1], filename=p.name)

    sec = cfg.get("smtp_security", "ssl")
    ctx = ssl.create_default_context()
    if sec == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    try:
        server.ehlo()
        if sec == "starttls":
            server.starttls(context=ctx)
            server.ehlo()
        if cfg.get("smtp_user"):
            server.login(cfg["smtp_user"], password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return to


def report_mail(result: dict) -> tuple[str, str]:
    """Objet et corps d'e-mail pour un rapport généré par report.generate()."""
    subject = f"{result['title']} — du {result['start']:%d/%m/%Y} au {result['end']:%d/%m/%Y}"
    lines = [result["intro"], "",
             f"Période : du {result['start']:%d/%m/%Y %H:%M} au {result['end']:%d/%m/%Y %H:%M} ({result['period']}).",
             "", "Faits marquants :"]
    lines += [f"  • {f}" for f in result["facts"]]
    lines += ["", "Le rapport complet est joint au format PDF.", "",
              "— Envoyé automatiquement par Vigie Freebox (application communautaire, non officielle)."]
    return subject, "\n".join(lines)
