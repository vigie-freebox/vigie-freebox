"""Détection automatique des réglages d'envoi (SMTP) à partir d'une adresse e-mail.

1. table des messageries françaises et internationales courantes ;
2. sinon, base publique de Thunderbird (autoconfig.thunderbird.net) puis autoconfig.<domaine> ;
3. import depuis les comptes Thunderbird déjà configurés sur l'ordinateur (sans le mot de passe).
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# domaine -> (fournisseur, serveur, port, sécurité, identifiant, lien mot de passe d'application, remarque)
_ADDR, _LOCAL = "adresse", "local"
KNOWN = [
    (("free.fr", "aliceadsl.fr", "libertysurf.fr", "online.fr"),
     "Free", "smtp.free.fr", 465, "ssl", _ADDR, None,
     "Identifiant : votre adresse complète. Mot de passe : celui de votre boîte e-mail Free "
     "(pas celui de l'Espace Abonné)."),
    (("gmail.com", "googlemail.com"),
     "Gmail", "smtp.gmail.com", 465, "ssl", _ADDR, "https://myaccount.google.com/apppasswords",
     "Gmail refuse votre mot de passe habituel : activez la validation en deux étapes puis créez un "
     "« mot de passe d'application » (16 lettres) et collez-le ici."),
    (("orange.fr", "wanadoo.fr"),
     "Orange", "smtp.orange.fr", 465, "ssl", _ADDR, None,
     "Identifiant : votre adresse complète. Mot de passe : celui de votre messagerie Orange."),
    (("sfr.fr", "neuf.fr", "cegetel.net", "club-internet.fr", "9online.fr"),
     "SFR", "smtp.sfr.fr", 465, "ssl", _ADDR, None,
     "Identifiant : votre adresse complète. Mot de passe : celui de votre messagerie SFR."),
    (("bbox.fr",),
     "Bouygues Telecom", "smtp.bbox.fr", 587, "starttls", _ADDR, None,
     "Identifiant : votre adresse complète."),
    (("laposte.net",),
     "La Poste", "smtp.laposte.net", 465, "ssl", _ADDR, None,
     "Identifiant : votre adresse complète. L'accès « logiciel de messagerie » doit être autorisé dans "
     "les options de sécurité de votre compte laposte.net."),
    (("yahoo.fr", "yahoo.com", "ymail.com"),
     "Yahoo", "smtp.mail.yahoo.com", 465, "ssl", _ADDR, "https://login.yahoo.com/account/security",
     "Yahoo exige un « mot de passe d'application » (Sécurité du compte › Générer un mot de passe "
     "d'application)."),
    (("icloud.com", "me.com", "mac.com"),
     "iCloud", "smtp.mail.me.com", 587, "starttls", _ADDR, "https://account.apple.com",
     "iCloud exige un « mot de passe pour app » (Compte Apple › Connexion et sécurité › Mots de passe "
     "pour app)."),
    (("outlook.fr", "outlook.com", "hotmail.fr", "hotmail.com", "live.fr", "live.com", "msn.com"),
     "Outlook / Hotmail", "smtp-mail.outlook.com", 587, "starttls", _ADDR,
     "https://account.microsoft.com/security",
     "Microsoft limite l'envoi par logiciel tiers : il faut la vérification en deux étapes et un "
     "« mot de passe d'application ». Si l'envoi échoue, utilisez une autre adresse (Gmail, Free…)."),
    (("gmx.fr", "gmx.com", "gmx.net"),
     "GMX", "mail.gmx.com", 587, "starttls", _ADDR, None,
     "L'accès POP3/IMAP doit être activé dans les paramètres de votre compte GMX."),
    (("proton.me", "protonmail.com"),
     "Proton", "127.0.0.1", 1025, "starttls", _ADDR, None,
     "Proton nécessite le logiciel « Proton Mail Bridge » (abonnement payant) installé sur cet ordinateur."),
]


def _result(provider, host, port, sec, user, link=None, note="", source="table"):
    return {"provider": provider, "smtp_host": host, "smtp_port": int(port), "smtp_security": sec,
            "smtp_user": user, "app_password_url": link, "note": note, "source": source}


def _domain(address: str) -> str | None:
    m = re.fullmatch(r"\s*([^@\s]+)@([^@\s]+\.[^@\s]+)\s*", address or "")
    return m.group(2).lower() if m else None


def from_table(address: str):
    d = _domain(address)
    if not d:
        return None
    for domains, prov, host, port, sec, user, link, note in KNOWN:
        if d in domains:
            u = address.strip() if user == _ADDR else address.split("@")[0].strip()
            return _result(prov, host, port, sec, u, link, note)
    return None


def parse_autoconfig(xml_text: str, address: str, source: str):
    """Lit un fichier autoconfig (format Thunderbird) et renvoie le premier serveur SMTP."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    local, dom = address.split("@", 1)
    best = None
    for srv in root.iter("outgoingServer"):
        if srv.get("type") != "smtp":
            continue
        host = (srv.findtext("hostname") or "").strip()
        port = (srv.findtext("port") or "").strip()
        sock = (srv.findtext("socketType") or "").strip().upper()
        user = (srv.findtext("username") or "%EMAILADDRESS%").strip()
        if not host or not port.isdigit():
            continue
        sec = {"SSL": "ssl", "STARTTLS": "starttls"}.get(sock, "aucune")
        user = (user.replace("%EMAILADDRESS%", address.strip()).replace("%EMAILLOCALPART%", local)
                .replace("%EMAILDOMAIN%", dom))
        cand = _result(root.findtext(".//displayShortName") or dom, host, port, sec, user, None,
                       "Réglages trouvés dans la base publique de Thunderbird.", source)
        if sec != "aucune":
            return cand
        best = best or cand
    return best


def from_internet(address: str, timeout=6):
    d = _domain(address)
    if not d:
        return None
    import requests
    urls = [(f"https://autoconfig.thunderbird.net/v1.1/{d}", "thunderbird"),
            (f"https://autoconfig.{d}/mail/config-v1.1.xml?emailaddress={address.strip()}", "fournisseur")]
    for url, src in urls:
        try:
            r = requests.get(url, timeout=timeout)
            if r.ok and "outgoingServer" in r.text:
                res = parse_autoconfig(r.text, address, src)
                if res:
                    return res
        except Exception:
            continue
    return None


def detect(address: str, online=True):
    """Renvoie un dict de réglages, ou None si rien n'a été trouvé."""
    return from_table(address) or (from_internet(address) if online else None)


# ------------------------------------------------------------------ Thunderbird
def _thunderbird_roots():
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return [base / "Thunderbird" / "Profiles"]
    if sys.platform == "darwin":
        return [home / "Library" / "Thunderbird" / "Profiles"]
    return [home / ".thunderbird", home / "snap" / "thunderbird" / "common" / ".thunderbird"]


_PREF = re.compile(r'user_pref\("([^"]+)",\s*(.+?)\);')


def thunderbird_accounts(roots=None):
    """Comptes d'envoi configurés dans Thunderbird (adresse, serveur, port, sécurité, identifiant)."""
    out, seen = [], set()
    for root in roots or _thunderbird_roots():
        for prefs in Path(root).glob("*/prefs.js") if Path(root).exists() else []:
            try:
                txt = prefs.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            p = {k: v.strip().strip('"') for k, v in _PREF.findall(txt)}
            smtp = {}
            for k, v in p.items():
                m = re.match(r"mail\.smtpserver\.(\w+)\.(hostname|port|try_ssl|username)$", k)
                if m:
                    smtp.setdefault(m.group(1), {})[m.group(2)] = v
            for k, v in p.items():
                m = re.match(r"mail\.identity\.(\w+)\.useremail$", k)
                if not m:
                    continue
                sid = p.get(f"mail.identity.{m.group(1)}.smtpServer") or p.get("mail.smtp.defaultserver")
                s = smtp.get(sid or "", {})
                if not s.get("hostname"):
                    continue
                ssl = s.get("try_ssl", "0")
                sec = {"3": "ssl", "2": "starttls", "1": "starttls"}.get(ssl, "aucune")
                port = int(s.get("port") or (465 if sec == "ssl" else 587))
                key = (v.lower(), s["hostname"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"address": v, **_result("Thunderbird", s["hostname"], port, sec,
                                                     s.get("username") or v, None,
                                                     "Réglages repris de Thunderbird (le mot de passe, chiffré par "
                                                     "Thunderbird, doit être saisi à nouveau).", "thunderbird-local")})
    return out
