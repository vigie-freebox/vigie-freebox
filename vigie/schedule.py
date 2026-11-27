"""Calendrier des rapports automatiques."""

from __future__ import annotations

from datetime import date, datetime, timedelta

FREQUENCES = {
    "quotidien": "Quotidien (tous les jours)",
    "hebdomadaire": "Hebdomadaire (1 fois par semaine)",
    "bihebdomadaire": "Bihebdomadaire (2 fois par semaine)",
    "bimensuel": "Bimensuel (le 1er et le 15 du mois)",
}
ADJECTIFS = {"quotidien": "quotidien", "hebdomadaire": "hebdomadaire",
             "bihebdomadaire": "bihebdomadaire", "bimensuel": "bimensuel", "manuel": ""}


def is_report_day(d: date, cfg: dict) -> bool:
    freq = cfg.get("report_freq", "hebdomadaire")
    if freq == "quotidien":
        return True
    if freq == "bimensuel":
        return d.day in (1, 15)
    days = {int(cfg.get("report_day", 0))}
    if freq == "bihebdomadaire":
        days.add(int(cfg.get("report_day2", 3)))
    return d.weekday() in days


def _at(d: date, cfg: dict) -> datetime:
    hh, mm = [int(x) for x in str(cfg.get("report_time", "07:30")).split(":")[:2]]
    return datetime(d.year, d.month, d.day, hh, mm)


def last_occurrence(now: datetime, cfg: dict) -> datetime:
    """Dernière échéance passée (ou égale à maintenant)."""
    d = now.date()
    for _ in range(40):
        if is_report_day(d, cfg) and _at(d, cfg) <= now:
            return _at(d, cfg)
        d -= timedelta(days=1)
    return now - timedelta(days=7)


def previous_occurrence(occ: datetime, cfg: dict) -> datetime:
    """Échéance qui précède `occ` : début de la période couverte par le rapport."""
    return last_occurrence(occ - timedelta(seconds=1), cfg)


def next_occurrence(now: datetime, cfg: dict) -> datetime:
    d = now.date()
    for _ in range(40):
        if is_report_day(d, cfg) and _at(d, cfg) > now:
            return _at(d, cfg)
        d += timedelta(days=1)
    return now + timedelta(days=7)
