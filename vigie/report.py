"""Rapport hebdomadaire (7 jours glissants) au format HTML et texte.

Le rapport est pensé pour être transmis au service technique de Free :
factuel, horodaté, et anonymisable (adresses MAC masquées, noms remplacés).
"""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import APP_NAME, __version__
from .schedule import ADJECTIFS
from .store import DEFAULT_INTRO, Store, reports_dir

LABELS = {
    "WIFI_DECONNEXION": "Déconnexion Wi-Fi",
    "WIFI_RECONNEXION": "Reconnexion Wi-Fi",
    "WIFI_COUPURE_BREVE": "Coupure brève Wi-Fi",
    "WIFI_CHANGEMENT_BORNE": "Changement de borne",
    "WIFI_DECROCHAGE_COLLECTIF": "Décrochage collectif",
    "REPETEUR_HORS_LIGNE": "Répéteur hors ligne",
    "REPETEUR_RETABLI": "Répéteur rétabli",
    "INTERNET_COUPE": "Internet coupé",
    "INTERNET_RETABLI": "Internet rétabli",
    "FIBRE": "Fibre",
    "BOX_REDEMARRAGE": "Redémarrage Freebox",
    "TV_LIEN_COUPE": "Lien Player coupé",
    "TV_LIEN_RETABLI": "Lien Player rétabli",
    "TV_LIEN_VITESSE": "Vitesse du lien Player",
    "TV_ERREURS": "Trames corrompues (Player)",
    "RAPPORT_ENVOYE": "Rapport envoyé par e-mail",
    "RAPPORT_NON_ENVOYE": "Rapport non envoyé",
}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def fmt_duration(s) -> str:
    if s is None:
        return "–"
    s = int(s)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    h, r = divmod(s, 3600)
    if h < 24:
        return f"{h} h {r // 60:02d} min"
    d, h = divmod(h, 24)
    return f"{d} j {h} h"


class Anonymizer:
    def __init__(self, mask_mac: bool, show_names: bool):
        self.mask_mac, self.show_names = mask_mac, show_names
        self.ids: dict[str, str] = {}

    def mac(self, m: str | None) -> str:
        if not m:
            return ""
        if not self.mask_mac:
            return m
        p = m.split(":")
        return ":".join(p[:3] + ["••"] * (len(p) - 3)) if len(p) == 6 else "••"

    def name(self, n: str | None, mac: str | None = None) -> str:
        if self.show_names:
            return n or (self.mac(mac) if mac else "?")
        key = mac or n or "?"
        if key not in self.ids:
            self.ids[key] = f"Appareil {len(self.ids) + 1}"
        return self.ids[key]


def period_label(start: datetime, end: datetime) -> str:
    sec = (end - start).total_seconds()
    if sec < 36 * 3600:
        return f"{round(sec / 3600)} heures"
    return f"{round(sec / 86400)} jours"


def report_title(freq: str) -> str:
    adj = ADJECTIFS.get(freq, "")
    return f"Rapport {adj} des incidents Wi-Fi et TV Freebox".replace("  ", " ")


def analyse(store: Store, start: datetime, end: datetime, freq: str = "manuel") -> dict:
    cfg = store.config
    an = Anonymizer(cfg.get("mask_mac", True), cfg.get("show_names", True))
    sentinels = set(cfg.get("sentinels", []))
    evs = [e for e in store.events(start, end) if not e["type"].startswith("RAPPORT_")]
    meas = store.measures(start)
    meas = [m for m in meas if datetime.fromisoformat(m["ts"]) <= end]
    interval = max(10, int(cfg.get("interval", 20)))

    # couverture : part de la période pendant laquelle l'application tournait
    covered = 0.0
    times = [datetime.fromisoformat(m["ts"]) for m in meas]
    for a, b in zip(times, times[1:]):
        gap = (b - a).total_seconds()
        covered += gap if gap <= interval * 3 else interval
    total = (end - start).total_seconds()
    coverage = min(100.0, 100.0 * covered / total) if total else 0.0

    devices: dict[str, dict] = {}
    for e in evs:
        if e["type"] not in ("WIFI_DECONNEXION", "WIFI_RECONNEXION", "WIFI_COUPURE_BREVE"):
            continue
        d = devices.setdefault(e.get("mac") or e.get("appareil"), {
            "mac": e.get("mac"), "name": e.get("appareil"), "decos": 0, "absences": [],
            "bornes": Counter(), "sentinelle": e.get("mac") in sentinels})
        if e["type"] in ("WIFI_DECONNEXION", "WIFI_COUPURE_BREVE"):
            d["decos"] += 1
            d["bornes"][f"{e.get('borne')} {e.get('bande')}"] += 1
        elif e.get("absence_s") is not None:
            d["absences"].append(e["absence_s"])
    dev_rows = []
    for d in devices.values():
        if not d["decos"]:
            continue
        ab = d["absences"]
        dev_rows.append({
            "name": an.name(d["name"], d["mac"]), "mac": an.mac(d["mac"]), "sentinelle": d["sentinelle"],
            "decos": d["decos"], "borne": ", ".join(f"{k} ({v})" for k, v in d["bornes"].most_common()),
            "abs_moy": sum(ab) / len(ab) if ab else None, "abs_max": max(ab) if ab else None,
            "abs_tot": sum(ab) if ab else None,
        })
    dev_rows.sort(key=lambda r: (not r["sentinelle"], -r["decos"]))

    decos = [e for e in evs if e["type"] in ("WIFI_DECONNEXION", "WIFI_COUPURE_BREVE")]
    by_ap = Counter(f"{e.get('borne')} {e.get('bande')}" for e in decos)
    by_day = Counter(e["ts"][:10] for e in decos)
    by_hour = Counter(int(e["ts"][11:13]) for e in decos)
    collectives = [e for e in evs if e["type"] == "WIFI_DECROCHAGE_COLLECTIF"]

    tv = [e for e in evs if e["type"].startswith("TV_")]
    tv_err = sum(int(e.get("nombre") or 0) for e in tv if e["type"] == "TV_ERREURS")
    cuts, open_cut = [], None
    for e in tv:
        if e["type"] == "TV_LIEN_COUPE":
            open_cut = e["ts"]
        elif e["type"] == "TV_LIEN_RETABLI" and open_cut:
            cuts.append((datetime.fromisoformat(e["ts"]) - datetime.fromisoformat(open_cut)).total_seconds())
            open_cut = None

    counts = Counter(e["type"] for e in evs)
    sentinel_decos = sum(1 for e in decos if e.get("mac") in sentinels)

    # faits marquants rédigés
    facts = []
    if coverage < 90:
        facts.append(f"La surveillance n'a fonctionné que {coverage:.0f} % du temps (ordinateur éteint ou en veille) : "
                     "les chiffres ci-dessous sont des minimums.")
    if counts["BOX_REDEMARRAGE"]:
        facts.append(f"La Freebox Server a redémarré {counts['BOX_REDEMARRAGE']} fois.")
    if counts["INTERNET_COUPE"]:
        facts.append(f"Internet a été coupé {counts['INTERNET_COUPE']} fois.")
    if counts["REPETEUR_HORS_LIGNE"]:
        facts.append(f"Le répéteur est passé hors ligne {counts['REPETEUR_HORS_LIGNE']} fois.")
    if collectives:
        facts.append(f"{len(collectives)} décrochage(s) collectif(s) : plusieurs appareils perdus au même instant "
                     "sur la même borne, ce qui désigne la borne plutôt que les appareils.")
    if sentinels:
        facts.append(f"Appareils « toujours allumés » (sentinelles) : {sentinel_decos} déconnexion(s). "
                     "Ces appareils ne se mettent pas en veille ; une déconnexion est donc anormale.")
    if by_ap:
        ap, n = by_ap.most_common(1)[0]
        facts.append(f"Borne la plus touchée : {ap} ({n} déconnexion(s) sur {len(decos)}).")
    if counts["TV_LIEN_COUPE"]:
        facts.append(f"Le câble du Freebox Player a perdu le lien {counts['TV_LIEN_COUPE']} fois"
                     + (f" (coupure la plus longue : {fmt_duration(max(cuts))})." if cuts else "."))
    if tv_err:
        facts.append(f"{tv_err} trame(s) Ethernet corrompue(s) reçue(s) sur le port du Player "
                     "(signe d'un câble ou d'une prise défectueux).")
    if counts["TV_LIEN_VITESSE"]:
        facts.append(f"La vitesse du lien du Player a changé {counts['TV_LIEN_VITESSE']} fois "
                     "(renégociation : souvent un câble abîmé).")
    if not evs:
        facts.append("Aucun incident enregistré sur la période.")

    detail = []
    for e in evs:
        if e["type"] == "WIFI_CHANGEMENT_BORNE":
            continue
        txt = e.get("detail") or ""
        if e["type"] in ("WIFI_DECONNEXION", "WIFI_RECONNEXION", "WIFI_COUPURE_BREVE"):
            parts = [an.name(e.get("appareil"), e.get("mac"))]
            if e.get("mac"):
                parts.append(an.mac(e["mac"]))
            parts.append(f"{e.get('borne')} {e.get('bande')}")
            if e.get("signal") is not None:
                parts.append(f"signal {e['signal']} dBm")
            if e.get("absence_s") is not None:
                parts.append(f"absent {fmt_duration(e['absence_s'])}")
            if e["type"] == "WIFI_COUPURE_BREVE" and e.get("detail"):
                parts.append(e["detail"])
            if e.get("sentinelle"):
                parts.append("SENTINELLE")
            txt = " — ".join(parts)
        elif e["type"] == "WIFI_DECROCHAGE_COLLECTIF":
            names = (e.get("detail") or "").split(", ")
            txt = f"{e.get('borne')} {e.get('bande')} : {e.get('nombre')} appareils ({', '.join(an.name(n) for n in names)})"
        elif e.get("borne"):
            txt = f"{e['borne']} {txt}".strip()
        detail.append({"ts": e["ts"], "type": LABELS.get(e["type"], e["type"]), "code": e["type"], "txt": txt})

    return {
        "freq": freq, "title": report_title(freq), "intro": (cfg.get("intro_text") or DEFAULT_INTRO).strip(),
        "period": period_label(start, end), "box_from_store": None,
        "start": start, "end": end, "coverage": coverage, "counts": counts, "facts": facts,
        "devices": dev_rows, "by_ap": by_ap, "by_day": by_day, "by_hour": by_hour,
        "tv_err": tv_err, "tv_cuts": cuts, "detail": detail, "nb_decos": len(decos),
        "anon": an,
    }


# ====================================================================== rendus
def render_txt(a: dict, box: dict) -> str:
    L = []
    L.append(a["title"].upper() + f" ({APP_NAME} {__version__})")
    L.append("")
    L.append(a["intro"])
    L.append("")
    L.append(f"Période : du {a['start']:%d/%m/%Y %H:%M} au {a['end']:%d/%m/%Y %H:%M} ({a['period']})")
    if box.get("model"):
        L.append(f"Box : {box['model']}" + (f" — micrologiciel {box['firmware']}" if box.get("firmware") else ""))
    if box.get("repeaters"):
        L.append("Répéteur(s) : " + ", ".join(box["repeaters"]))
    L.append(f"Couverture de la surveillance : {a['coverage']:.0f} % de la période")
    L.append("")
    L.append("FAITS MARQUANTS")
    L.extend(f"  • {f}" for f in a["facts"])
    L.append("")
    L.append("SYNTHÈSE")
    for code, n in sorted(a["counts"].items()):
        if code != "WIFI_CHANGEMENT_BORNE":
            L.append(f"  {LABELS.get(code, code):<32} {n}")
    L.append("")
    if a["devices"]:
        L.append("DÉCONNEXIONS PAR APPAREIL")
        for d in a["devices"]:
            L.append(f"  {'[S] ' if d['sentinelle'] else '    '}{d['name']:<28} {d['mac']:<18} "
                     f"{d['decos']:>3} déco. — absence moy. {fmt_duration(d['abs_moy'])}, "
                     f"max {fmt_duration(d['abs_max'])} — {d['borne']}")
        L.append("  [S] = sentinelle (appareil qui ne se met jamais en veille)")
        L.append("")
    if a["by_ap"]:
        L.append("PAR BORNE / BANDE : " + ", ".join(f"{k} = {v}" for k, v in a["by_ap"].most_common()))
        L.append("PAR JOUR          : " + ", ".join(
            f"{JOURS[datetime.fromisoformat(k).weekday()]} {k[8:10]}/{k[5:7]} = {v}" for k, v in sorted(a["by_day"].items())))
        L.append("PAR HEURE         : " + ", ".join(f"{h} h = {v}" for h, v in sorted(a["by_hour"].items())))
        L.append("")
    L.append("JOURNAL DÉTAILLÉ")
    for d in a["detail"]:
        L.append(f"  {d['ts'].replace('T', ' ')}  {d['type']:<28} {d['txt']}")
    if not a["detail"]:
        L.append("  (aucun événement)")
    L.append("")
    L.append("Rapport généré automatiquement à partir de l'API locale de la Freebox. "
             "Adresses MAC partiellement masquées." if a["anon"].mask_mac else
             "Rapport généré automatiquement à partir de l'API locale de la Freebox.")
    return "\n".join(L)


CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1d2433;max-width:1000px;margin:24px auto;padding:0 18px;line-height:1.45}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:26px 0 8px;border-bottom:2px solid #e3e7ef;padding-bottom:4px}
.meta{color:#5a6478;font-size:13px} .cards{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.card{flex:1 1 140px;border:1px solid #e3e7ef;border-radius:10px;padding:10px 12px}
.card b{display:block;font-size:22px} .card span{font-size:12px;color:#5a6478}
.warn b{color:#c0392b} ul.facts li{margin:4px 0}
.intro{margin:14px 0 6px;padding:12px 16px;border-left:4px solid #c0392b;background:#fdf2f1;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px} th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #eef1f6;vertical-align:top}
th{background:#f5f7fb;font-weight:600} td.n{text-align:right;white-space:nowrap}
.bar{display:flex;align-items:center;gap:8px;font-size:12px;margin:2px 0}.bar i{display:block;height:12px;background:#3b6fe0;border-radius:3px}
.bar span{width:150px;flex:none}.tag{font-size:11px;background:#fde8e8;color:#b02a2a;border-radius:6px;padding:1px 6px}
.code-TV_LIEN_COUPE,.code-INTERNET_COUPE,.code-REPETEUR_HORS_LIGNE,.code-BOX_REDEMARRAGE,.code-WIFI_DECROCHAGE_COLLECTIF{color:#b02a2a;font-weight:600}
footer{margin-top:28px;font-size:12px;color:#7a8396}
@media print{body{margin:0}}
"""


def _bars(items: list, label) -> str:
    if not items:
        return "<p class='meta'>Aucune donnée.</p>"
    m = max(v for _, v in items)
    return "".join(f"<div class='bar'><span>{html.escape(label(k))}</span><i style='width:{max(4, 420 * v // m)}px'></i>{v}</div>"
                   for k, v in items)


def render_html(a: dict, box: dict) -> str:
    e = html.escape
    c = a["counts"]
    cards = [
        ("Déconnexions Wi-Fi", a["nb_decos"], a["nb_decos"] > 0),
        ("Décrochages collectifs", c["WIFI_DECROCHAGE_COLLECTIF"], c["WIFI_DECROCHAGE_COLLECTIF"] > 0),
        ("Répéteur hors ligne", c["REPETEUR_HORS_LIGNE"], c["REPETEUR_HORS_LIGNE"] > 0),
        ("Coupures lien Player", c["TV_LIEN_COUPE"], c["TV_LIEN_COUPE"] > 0),
        ("Trames corrompues TV", a["tv_err"], a["tv_err"] > 0),
        ("Coupures Internet", c["INTERNET_COUPE"], c["INTERNET_COUPE"] > 0),
        ("Redémarrages box", c["BOX_REDEMARRAGE"], c["BOX_REDEMARRAGE"] > 0),
        ("Couverture", f"{a['coverage']:.0f} %", a["coverage"] < 90),
    ]
    H = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>{e(a['title'])} — "
         f"{a['end']:%d/%m/%Y}</title><style>{CSS}</style></head><body>"]
    H.append(f"<h1>{e(a['title'])}</h1>")
    H.append(f"<div class='intro'>{e(a['intro'])}</div>")
    meta = f"Du {a['start']:%d/%m/%Y %H:%M} au {a['end']:%d/%m/%Y %H:%M} ({a['period']})"
    if box.get("model"):
        meta += f" · {e(box['model'])}" + (f" (micrologiciel {e(str(box['firmware']))})" if box.get("firmware") else "")
    if box.get("repeaters"):
        meta += " · répéteur : " + e(", ".join(box["repeaters"]))
    H.append(f"<div class='meta'>{meta}</div>")
    H.append("<div class='cards'>" + "".join(
        f"<div class='card{' warn' if w else ''}'><b>{v}</b><span>{e(t)}</span></div>" for t, v, w in cards) + "</div>")
    H.append("<h2>Faits marquants</h2><ul class='facts'>" + "".join(f"<li>{e(f)}</li>" for f in a["facts"]) + "</ul>")
    if a["devices"]:
        H.append("<h2>Déconnexions par appareil</h2><table><tr><th>Appareil</th><th>MAC</th><th class='n'>Déco.</th>"
                 "<th class='n'>Absence moy.</th><th class='n'>Absence max</th><th>Borne / bande</th></tr>")
        for d in a["devices"]:
            tag = " <span class='tag'>sentinelle</span>" if d["sentinelle"] else ""
            H.append(f"<tr><td>{e(d['name'])}{tag}</td><td>{e(d['mac'])}</td><td class='n'>{d['decos']}</td>"
                     f"<td class='n'>{fmt_duration(d['abs_moy'])}</td><td class='n'>{fmt_duration(d['abs_max'])}</td>"
                     f"<td>{e(d['borne'])}</td></tr>")
        H.append("</table><p class='meta'>Sentinelle : appareil qui ne se met jamais en veille (caméra, prise…) ; "
                 "sa déconnexion est anormale.</p>")
    if a["by_ap"]:
        H.append("<h2>Répartition des déconnexions</h2><h3 style='font-size:14px'>Par borne et bande</h3>")
        H.append(_bars(a["by_ap"].most_common(), str))
        H.append("<h3 style='font-size:14px'>Par jour</h3>")
        H.append(_bars(sorted(a["by_day"].items()),
                       lambda k: f"{JOURS[datetime.fromisoformat(k).weekday()]} {k[8:10]}/{k[5:7]}"))
        H.append("<h3 style='font-size:14px'>Par heure de la journée</h3>")
        H.append(_bars(sorted(a["by_hour"].items()), lambda h: f"{h:02d} h – {h:02d} h 59"))
    H.append("<h2>Journal détaillé</h2>")
    if a["detail"]:
        H.append("<table><tr><th>Date et heure</th><th>Événement</th><th>Détail</th></tr>")
        for d in a["detail"]:
            ts = datetime.fromisoformat(d["ts"])
            H.append(f"<tr><td style='white-space:nowrap'>{JOURS[ts.weekday()][:3]}. {ts:%d/%m %H:%M:%S}</td>"
                     f"<td class='code-{d['code']}'>{e(d['type'])}</td><td>{e(d['txt'])}</td></tr>")
        H.append("</table>")
    else:
        H.append("<p>Aucun événement sur la période.</p>")
    H.append(f"<footer>Généré le {datetime.now():%d/%m/%Y à %H:%M} par {APP_NAME} {__version__} "
             "(application communautaire, non officielle) à partir de l'API locale de la Freebox. "
             + ("Adresses MAC partiellement masquées. " if a["anon"].mask_mac else "")
             + "</footer></body></html>")
    return "\n".join(H)


def generate(store: Store, end: datetime | None = None, start: datetime | None = None, days: int = 7,
             box: dict | None = None, out_dir: Path | None = None, freq: str = "manuel") -> dict:
    end = end or datetime.now()
    start = start or end - timedelta(days=days)
    a = analyse(store, start, end, freq)
    box = box or {}
    out = Path(out_dir) if out_dir else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    stem = f"rapport_freebox_{end:%Y-%m-%d_%Hh%M}" + (f"_{freq}" if freq != "manuel" else "")
    html_path, txt_path, pdf_path = out / f"{stem}.html", out / f"{stem}.txt", out / f"{stem}.pdf"
    html_path.write_text(render_html(a, box), encoding="utf-8")
    txt_path.write_text(render_txt(a, box), encoding="utf-8")
    from .pdf import render_pdf
    render_pdf(a, box, pdf_path)
    return {"html": html_path, "txt": txt_path, "pdf": pdf_path, "events": len(a["detail"]),
            "title": a["title"], "intro": a["intro"], "facts": a["facts"], "start": start, "end": end,
            "period": a["period"], "analyse": a, "box": box}
