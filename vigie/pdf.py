"""Rendu PDF du rapport (ReportLab) et du courrier de réclamation adressé à Free."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import APP_NAME, __version__

BLEU = colors.HexColor("#1f4fbf")
ROUGE = colors.HexColor("#b02a2a")
GRIS = colors.HexColor("#5a6478")
FOND = colors.HexColor("#f5f7fb")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
ADRESSE_FREE = "75371 Paris Cedex 08"

_FONTS_OK = None


def _fonts():
    global _FONTS_OK
    if _FONTS_OK is not None:
        return _FONTS_OK
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / "fonts"
    try:
        pdfmetrics.registerFont(TTFont("Vigie", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("Vigie-Bold", str(base / "DejaVuSans-Bold.ttf")))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily("Vigie", normal="Vigie", bold="Vigie-Bold", italic="Vigie", boldItalic="Vigie-Bold")
        _FONTS_OK = ("Vigie", "Vigie-Bold")
    except Exception:
        _FONTS_OK = ("Helvetica", "Helvetica-Bold")
    return _FONTS_OK


def _styles():
    f, fb = _fonts()
    st = {
        "title": ParagraphStyle("t", fontName=fb, fontSize=16, leading=20, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=fb, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=5,
                             textColor=colors.HexColor("#1d2433")),
        "body": ParagraphStyle("b", fontName=f, fontSize=9.5, leading=13, alignment=TA_LEFT),
        "small": ParagraphStyle("s", fontName=f, fontSize=8, leading=10.5, textColor=GRIS),
        "cell": ParagraphStyle("c", fontName=f, fontSize=7.6, leading=9.4),
        "cellb": ParagraphStyle("cb", fontName=fb, fontSize=7.6, leading=9.4),
        "intro": ParagraphStyle("i", fontName=fb, fontSize=9.5, leading=13.5, textColor=colors.HexColor("#5b1610")),
        "bullet": ParagraphStyle("bl", fontName=f, fontSize=9.3, leading=12.5, leftIndent=10, bulletIndent=0),
        "letter": ParagraphStyle("l", fontName=f, fontSize=10.5, leading=15),
    }
    return st


def _esc(t) -> str:
    return (str(t if t is not None else "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _footer(title):
    def draw(canvas, doc):
        f, _ = _fonts()
        canvas.saveState()
        canvas.setFont(f, 7.5)
        canvas.setFillColor(GRIS)
        canvas.drawString(15 * mm, 9 * mm, f"{title} — généré par {APP_NAME} {__version__} (application non officielle)")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"page {doc.page}")
        canvas.restoreState()
    return draw


def _intro_box(text, st):
    t = Table([[Paragraph(_esc(text), st["intro"])]], colWidths=[180 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf2f1")),
                           ("LINEBEFORE", (0, 0), (0, -1), 3, ROUGE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def _table(rows, widths, st, header=True, zebra=True):
    data = [[Paragraph(_esc(c), st["cellb"] if header and i == 0 else st["cell"]) for c in r]
            for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e3e7ef")),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), FOND))
    t.setStyle(TableStyle(style))
    return t


def _bars(items, label, st):
    if not items:
        return Paragraph("Aucune donnée.", st["small"])
    m = max(v for _, v in items) or 1
    rows = []
    for k, v in items:
        d = Drawing(95 * mm, 8)
        d.add(Rect(0, 1, max(2, 95 * mm * v / m), 6, fillColor=BLEU, strokeColor=None))
        rows.append([Paragraph(_esc(label(k)), st["cell"]), d, Paragraph(str(v), st["cell"])])
    t = Table(rows, colWidths=[45 * mm, 98 * mm, 15 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def report_flowables(a: dict, box: dict, st=None) -> list:
    st = st or _styles()
    _, fb = _fonts()
    c = a["counts"]
    F = [Paragraph(_esc(a["title"]), st["title"]), Spacer(1, 3), _intro_box(a["intro"], st), Spacer(1, 6)]
    meta = f"Période : du {a['start']:%d/%m/%Y %H:%M} au {a['end']:%d/%m/%Y %H:%M} ({a['period']})"
    if box.get("model"):
        meta += f" · {box['model']}" + (f" (micrologiciel {box['firmware']})" if box.get("firmware") else "")
    if box.get("repeaters"):
        meta += " · répéteur : " + ", ".join(box["repeaters"])
    F.append(Paragraph(_esc(meta), st["small"]))
    F.append(Spacer(1, 6))

    cards = [("Déconnexions Wi-Fi", a["nb_decos"]), ("Décrochages collectifs", c["WIFI_DECROCHAGE_COLLECTIF"]),
             ("Répéteur hors ligne", c["REPETEUR_HORS_LIGNE"]), ("Coupures lien Player", c["TV_LIEN_COUPE"]),
             ("Trames corrompues TV", a["tv_err"]), ("Coupures Internet", c["INTERNET_COUPE"]),
             ("Redémarrages box", c["BOX_REDEMARRAGE"]), ("Couverture", f"{a['coverage']:.0f} %")]
    cells = []
    for title, val in cards:
        warn = (title == "Couverture" and a["coverage"] < 90) or (title != "Couverture" and val)
        cells.append(Paragraph(f"<font name='{fb}' size='14' color='{'#b02a2a' if warn else '#1d2433'}'>{val}</font>"
                               f"<br/><font size='7.5' color='#5a6478'>{_esc(title)}</font>", st["cell"]))
    t = Table([cells[:4], cells[4:]], colWidths=[45 * mm] * 4)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3e7ef")),
                           ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3e7ef")),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    F.append(t)

    F.append(Paragraph("Faits marquants", st["h2"]))
    for f in a["facts"]:
        F.append(Paragraph(_esc(f), st["bullet"], bulletText="•"))

    if a["devices"]:
        rows = [["Appareil", "MAC", "Déco.", "Absence moy.", "Absence max", "Borne / bande"]]
        from .report import fmt_duration
        for d in a["devices"]:
            rows.append([d["name"] + (" (sentinelle)" if d["sentinelle"] else ""), d["mac"], str(d["decos"]),
                         fmt_duration(d["abs_moy"]), fmt_duration(d["abs_max"]), d["borne"]])
        F.append(Paragraph("Déconnexions par appareil", st["h2"]))
        F.append(_table(rows, [44 * mm, 30 * mm, 12 * mm, 22 * mm, 22 * mm, 50 * mm], st))
        F.append(Paragraph("Sentinelle : appareil qui ne se met jamais en veille (caméra, prise…) ; "
                           "sa déconnexion est anormale.", st["small"]))

    if a["by_ap"]:
        F.append(Paragraph("Répartition des déconnexions", st["h2"]))
        F.append(KeepTogether([Paragraph("Par borne et bande", st["cellb"]),
                               _bars(a["by_ap"].most_common(), str, st)]))
        F.append(Spacer(1, 4))
        F.append(KeepTogether([Paragraph("Par jour", st["cellb"]), _bars(
            sorted(a["by_day"].items()),
            lambda k: f"{JOURS[datetime.fromisoformat(k).weekday()]} {k[8:10]}/{k[5:7]}", st)]))
        F.append(Spacer(1, 4))
        F.append(KeepTogether([Paragraph("Par heure de la journée", st["cellb"]),
                               _bars(sorted(a["by_hour"].items()), lambda h: f"{h:02d} h – {h:02d} h 59", st)]))

    F.append(Paragraph("Journal détaillé", st["h2"]))
    if a["detail"]:
        rows = [["Date et heure", "Événement", "Détail"]]
        for d in a["detail"]:
            ts = datetime.fromisoformat(d["ts"])
            rows.append([f"{JOURS[ts.weekday()][:3]}. {ts:%d/%m %H:%M:%S}", d["type"], d["txt"]])
        F.append(_table(rows, [28 * mm, 36 * mm, 116 * mm], st))
    else:
        F.append(Paragraph("Aucun événement sur la période.", st["body"]))
    F.append(Spacer(1, 8))
    F.append(Paragraph(f"Rapport généré le {datetime.now():%d/%m/%Y à %H:%M} par {APP_NAME} {__version__} "
                       "(application communautaire, non officielle) à partir de l'API locale de la Freebox.",
                       st["small"]))
    return F


def render_pdf(a: dict, box: dict, path) -> Path:
    path = Path(path)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title=a["title"], author=APP_NAME)
    doc.build(report_flowables(a, box), onFirstPage=_footer(a["title"]), onLaterPages=_footer(a["title"]))
    return path


# ====================================================================== courrier
def letter_text(cfg: dict, a: dict) -> dict:
    """Contenu du courrier de réclamation (réutilisé pour le PDF et pour le presse-papiers)."""
    nom = cfg.get("abonne_nom") or "[Votre nom]"
    ident = cfg.get("abonne_id") or "[identifiant Freebox]"
    objet = (f"Réclamation – incidents de service constatés du {a['start']:%d/%m/%Y} au {a['end']:%d/%m/%Y} "
             f"(identifiant {ident})")
    faits = [f for f in a["facts"] if not f.startswith("La surveillance n'a fonctionné")] or a["facts"]
    corps = [
        "Madame, Monsieur,",
        a["intro"],
        (f"Vous trouverez ci-joint le rapport horodaté des incidents relevés automatiquement sur mon accès "
         f"Freebox entre le {a['start']:%d/%m/%Y à %H:%M} et le {a['end']:%d/%m/%Y à %H:%M}. "
         "Il fait notamment apparaître les éléments suivants :"),
    ]
    demandes = [
        "le rétablissement sans délai d'un service conforme à mon contrat ;",
        "l'indication des mesures correctives que vous allez mettre en œuvre ;",
        "l'application des compensations prévues par vos Conditions Générales d'Abonnement au titre de la qualité de service.",
    ]
    if "Consommateur" in (cfg.get("free_service") or ""):
        suite = ("À défaut de réponse satisfaisante dans un délai d'un mois, je saisirai le Médiateur des "
                 "communications électroniques.")
    else:
        suite = ("À défaut de réponse satisfaisante dans un délai d'un mois, je saisirai votre Service National "
                 "Consommateur puis, le cas échéant, le Médiateur des communications électroniques.")
    fin = [
        suite,
        "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.",
        nom,
    ]
    return {"objet": objet, "corps": corps, "faits": faits, "demandes": demandes, "fin": fin}


def letter_plain(cfg: dict, a: dict) -> str:
    L = letter_text(cfg, a)
    out = [f"Objet : {L['objet']}", ""] + [L["corps"][0], "", L["corps"][1], "", L["corps"][2]]
    out += [f"  • {f}" for f in L["faits"]] + ["", "Je vous demande en conséquence :"]
    out += [f"  • {d}" for d in L["demandes"]] + [""] + [x for f in L["fin"] for x in (f, "")]
    return "\n".join(out).strip()


def render_letter(cfg: dict, a: dict, box: dict, path) -> Path:
    """Courrier de réclamation (1re page) suivi du rapport complet, en un seul PDF."""
    st = _styles()
    _, fb = _fonts()
    L = letter_text(cfg, a)
    exp = [cfg.get("abonne_nom") or "[Votre nom]"] + \
          [x for x in (cfg.get("abonne_adresse") or "[Votre adresse]").splitlines() if x.strip()]
    if cfg.get("abonne_id"):
        exp.append(f"Identifiant Freebox : {cfg['abonne_id']}")
    if cfg.get("abonne_ligne"):
        exp.append(f"Ligne : {cfg['abonne_ligne']}")
    dest = ["Free", cfg.get("free_service") or "Service Réclamation", ADRESSE_FREE]
    head = Table([[Paragraph("<br/>".join(_esc(x) for x in exp), st["letter"]), ""],
                  ["", Paragraph("<br/>".join(_esc(x) for x in dest), st["letter"])]],
                 colWidths=[100 * mm, 80 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 1), (-1, 1), 10)]))
    F = [head, Spacer(1, 10),
         Paragraph(f"Le {datetime.now():%d/%m/%Y}", st["letter"]),
         Paragraph("Lettre recommandée avec accusé de réception", st["letter"]), Spacer(1, 8),
         Paragraph(f"<font name='{fb}'>Objet : {_esc(L['objet'])}</font>", st["letter"]),
         Paragraph("Pièce jointe : rapport des incidents (pages suivantes)", st["letter"]), Spacer(1, 10),
         Paragraph(_esc(L["corps"][0]), st["letter"]), Spacer(1, 6),
         Paragraph(f"<font name='{fb}'>{_esc(L['corps'][1])}</font>", st["letter"]), Spacer(1, 6),
         Paragraph(_esc(L["corps"][2]), st["letter"])]
    F += [Paragraph(_esc(f), ParagraphStyle("lb", parent=st["letter"], leftIndent=12), bulletText="•") for f in L["faits"]]
    F += [Spacer(1, 6), Paragraph("Je vous demande en conséquence :", st["letter"])]
    F += [Paragraph(_esc(d), ParagraphStyle("ld", parent=st["letter"], leftIndent=12), bulletText="•") for d in L["demandes"]]
    F += [Spacer(1, 6)] + [Paragraph(_esc(x), st["letter"]) for x in L["fin"][:-1]]
    F += [Spacer(1, 14), Paragraph(_esc(L["fin"][-1]), st["letter"]), PageBreak()]
    F += report_flowables(a, box, st)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=L["objet"], author=cfg.get("abonne_nom") or APP_NAME)
    doc.build(F, onFirstPage=lambda c, d: None, onLaterPages=_footer(a["title"]))
    return Path(path)
