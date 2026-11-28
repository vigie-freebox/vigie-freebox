"""Stockage local : configuration (JSON), journal d'événements (JSONL), mesures (CSV)."""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

RETENTION_DAYS = 90

DEFAULT_INTRO = ("Je paie un abonnement pour un service sans incident. Les incidents qui sont identifiés dans ce "
                 "rapport relèvent de l'Article 10 (« Qualité de service ») de vos Conditions Générales d'Abonnement "
                 "(CGA) et de l'obligation de résultat (Article 1231-1 du Code civil - Responsabilité contractuelle "
                 "en cas d'inexécution ou de retard) imposée au professionnel.")

DEFAULT_CONFIG = {
    "freebox_url": "http://mafreebox.freebox.fr",
    "app_token": None,
    "interval": 20,
    "report_day": 0,          # 0 = lundi … 6 = dimanche
    "report_time": "07:30",
    "last_auto_report": None,  # date ISO (AAAA-MM-JJ) du dernier rapport automatique
    "mask_mac": True,
    "show_names": True,
    "sentinels": [],          # adresses MAC des appareils « toujours allumés »
    "player_port": None,      # n° du port Ethernet du Player (None = détection auto)
    "aliases": {},            # MAC -> nom donné par l'utilisateur
    "report_freq": "hebdomadaire",   # quotidien | hebdomadaire | bihebdomadaire | bimensuel
    "report_day2": 3,         # second jour pour le rythme bihebdomadaire (3 = jeudi)
    "intro_text": DEFAULT_INTRO,
    # envoi par e-mail
    "email_auto": False,
    "email_to": "",
    "smtp_from": "",
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_security": "ssl",   # ssl | starttls | aucune
    "smtp_user": "",
    # coordonnées de l'abonné (courrier de réclamation à Free)
    "abonne_nom": "",
    "abonne_adresse": "",
    "abonne_id": "",          # identifiant Freebox (ex. fbx12345678)
    "abonne_ligne": "",       # numéro de ligne fixe Free
    "free_service": "Service Réclamation",
}


def data_dir() -> Path:
    if os.environ.get("VIGIE_DATA"):          # version serveur (VM, Raspberry Pi…)
        d = Path(os.environ["VIGIE_DATA"])
        d.mkdir(parents=True, exist_ok=True)
        return d
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "VigieFreebox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def reports_dir() -> Path:
    if os.environ.get("VIGIE_DATA"):
        d = Path(os.environ["VIGIE_DATA"]) / "rapports"
        d.mkdir(parents=True, exist_ok=True)
        return d
    docs = Path.home() / "Documents"
    d = (docs if docs.exists() else Path.home()) / "Vigie Freebox"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.root / "config.json"
        self.events_file = self.root / "evenements.jsonl"
        self.measures_file = self.root / "mesures.csv"
        self._lock = threading.Lock()
        self.config = dict(DEFAULT_CONFIG)
        if self.config_file.exists():
            try:
                self.config.update(json.loads(self.config_file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    # ---------------------------------------------------------------- config
    def save_config(self):
        with self._lock:
            tmp = self.config_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.config_file)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    # ---------------------------------------------------------------- événements
    def add_event(self, ev: dict):
        ev = dict(ev)
        ev.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        with self._lock, open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def events(self, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
        out = []
        if not self.events_file.exists():
            return out
        with self._lock, open(self.events_file, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                    ts = datetime.fromisoformat(ev["ts"])
                except (ValueError, KeyError):
                    continue
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
                out.append(ev)
        return out

    # ---------------------------------------------------------------- mesures
    MEASURE_FIELDS = ["ts", "wifi_stations", "repeteur", "internet", "fibre_rx_dbm",
                      "player_lien", "player_erreurs"]

    def add_measure(self, row: dict):
        new = not self.measures_file.exists()
        with self._lock, open(self.measures_file, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.MEASURE_FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)

    def measures(self, since: datetime | None = None) -> list[dict]:
        if not self.measures_file.exists():
            return []
        with self._lock, open(self.measures_file, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if since:
            rows = [r for r in rows if r.get("ts") and datetime.fromisoformat(r["ts"]) >= since]
        return rows

    # ---------------------------------------------------------------- ménage
    def prune(self, days: int = RETENTION_DAYS):
        limit = datetime.now() - timedelta(days=days)
        with self._lock:
            if self.events_file.exists():
                keep = []
                with open(self.events_file, encoding="utf-8") as f:
                    for line in f:
                        try:
                            if datetime.fromisoformat(json.loads(line)["ts"]) >= limit:
                                keep.append(line)
                        except (ValueError, KeyError):
                            pass
                self.events_file.write_text("".join(keep), encoding="utf-8")
            if self.measures_file.exists():
                with open(self.measures_file, newline="", encoding="utf-8") as f:
                    rows = [r for r in csv.DictReader(f)
                            if r.get("ts") and datetime.fromisoformat(r["ts"]) >= limit]
                with open(self.measures_file, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=self.MEASURE_FIELDS, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
