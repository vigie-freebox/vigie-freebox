"""Version serveur de Vigie Freebox (VM de la Freebox, Raspberry Pi, NAS…).

Même surveillance et mêmes rapports que l'application de bureau, avec une interface web :
    VIGIE_DATA=/var/lib/vigie-freebox python3 -m vigie.server --port 8099
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import threading
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import APP_NAME, __version__, mailer
from .api import FreeboxAPI
from .monitor import Monitor
from .report import JOURS, LABELS, analyse, fmt_duration, generate
from .schedule import FREQUENCES, last_occurrence, next_occurrence
from .store import DEFAULT_INTRO, Store, reports_dir

E = html.escape
ASSETS = Path(__file__).resolve().parent.parent / "assets"

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f3f5f9;color:#1d2433}
header{background:#09203f;color:#fff;padding:12px 20px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
header b{font-size:18px}header nav a{color:#dfe6ff;text-decoration:none;margin-right:14px}header nav a.on{color:#fff;font-weight:700}
.st{margin-left:auto;font-size:13px;color:#cfe0ff}main{max-width:1050px;margin:18px auto;padding:0 16px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.card{background:#fff;border:1px solid #e1e6ef;border-radius:10px;padding:12px}.card span{color:#5a6478;font-size:12px}
.card b{display:block;font-size:22px;margin:4px 0}.ok{color:#1e8449}.ko{color:#c0392b}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e1e6ef;border-radius:10px;overflow:hidden;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid #eef1f6}th{background:#f5f7fb}
tr.alert td{color:#c0392b}tr.good td{color:#1e8449}
h2{font-size:17px;margin:22px 0 8px}form.inline{display:inline}
.box{background:#fff;border:1px solid #e1e6ef;border-radius:10px;padding:14px;margin:12px 0}
label{display:block;margin:8px 0 3px;font-size:13px;color:#3a4458}input,select,textarea{font:inherit;padding:6px 8px;border:1px solid #c9d1df;border-radius:6px;width:100%;max-width:520px}
textarea{max-width:none}button,.btn{background:#1f4fbf;color:#fff;border:0;border-radius:7px;padding:8px 14px;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button.light,.btn.light{background:#e6ebf5;color:#1d2433}.muted{color:#5a6478;font-size:13px}.msg{background:#e3f4e8;padding:10px;border-radius:8px}
.warn{background:#fff4d6;padding:10px;border-radius:8px}
table.data th{cursor:pointer;user-select:none;white-space:nowrap}table.data th .ar{color:#8a94a8;font-size:11px}
table.data tr.flt th{background:#fff;cursor:default;padding:4px 6px}table.data tr.flt select,table.data tr.flt input{width:100%;padding:3px 4px;font-size:12px}
.cnt{color:#5a6478;font-size:12px;margin:4px 2px}
"""
TABLE_JS = """
<script>
document.querySelectorAll('table.data').forEach(function(t){
  var head=t.rows[0], body=Array.prototype.slice.call(t.rows,1), n=head.cells.length;
  var cnt=document.createElement('div'); cnt.className='cnt'; t.parentNode.insertBefore(cnt,t);
  var fr=t.insertRow(1); fr.className='flt'; var ctl=[];
  function val(r,i){var c=r.cells[i]; return c?(c.getAttribute('data-f')||c.textContent.trim()):'';}
  function key(r,i){var c=r.cells[i]; if(!c)return ''; var s=c.getAttribute('data-s'); if(s!==null){var x=parseFloat(s); return isNaN(x)?s.toLowerCase():x;} return c.textContent.trim().toLowerCase();}
  for(var i=0;i<n;i++){
    var th=document.createElement('th'); fr.appendChild(th); var kind=head.cells[i].getAttribute('data-k')||'liste';
    if(kind==='aucun'){ctl.push(null);continue;}
    var el;
    if(kind==='texte'){el=document.createElement('input');el.placeholder='contient…';el.oninput=function(){window.vigieTouched=1;apply();};}
    else{el=document.createElement('select');var vs={};body.forEach(function(r){var v=val(r,i);if(v)vs[v]=1;});
      var o=document.createElement('option');o.value='';o.textContent='(tous)';el.appendChild(o);
      Object.keys(vs).sort().forEach(function(v){var o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);});
      el.onchange=function(){window.vigieTouched=1;apply();};}
    th.appendChild(el); ctl.push(el);
  }
  var sc=-1, desc=false;
  function arrows(){for(var i=0;i<n;i++){var h=head.cells[i],a=h.querySelector('.ar');if(!a){a=document.createElement('span');a.className='ar';h.appendChild(a);}
    a.textContent=(i===sc&&desc)?' \u25BC':' \u25B2';a.style.color='#000';a.style.fontSize=(i===sc?'1em':'0.65em');}}
  function sortNow(){if(sc<0)return;arrows();
    body.sort(function(a,b){var x=key(a,sc),y=key(b,sc);return (x<y?-1:x>y?1:0)*(desc?-1:1);});
    body.forEach(function(r){t.tBodies[0].appendChild(r);});apply();}
  for(var i=0;i<n;i++)(function(i){head.cells[i].onclick=function(){window.vigieTouched=1;if(sc===i)desc=!desc;else{sc=i;desc=false;}sortNow();};})(i);
  function apply(){var k=0;body.forEach(function(r){var ok=true;for(var i=0;i<n;i++){var c=ctl[i];if(!c||!c.value)continue;
      if(c.tagName==='INPUT'){if(r.cells[i].textContent.toLowerCase().indexOf(c.value.toLowerCase())<0)ok=false;}
      else if(val(r,i)!==c.value)ok=false;}
    r.style.display=ok?'':'none';if(ok)k++;});cnt.textContent=k+' / '+body.length+' ligne(s)';}
  var d=head.getAttribute('data-sort'); if(d!==null){sc=parseInt(d);desc=head.getAttribute('data-desc')==='1';}
  arrows(); sortNow(); apply();
});
</script>"""
PERIODES = {"24 dernières heures": 1, "7 derniers jours": 7, "15 derniers jours": 15, "30 derniers jours": 30}


class App:
    def __init__(self):
        self.store = Store()
        cfg = self.store.config
        self.monitor = Monitor(self.store, FreeboxAPI(cfg["freebox_url"], cfg.get("app_token")))
        self.track = None
        self.monitor.start()


APPLI: App | None = None


def page(title, body, active="", msg=""):
    m = APPLI.monitor
    nav = "".join(f"<a class='{'on' if k == active else ''}' href='{k}'>{v}</a>" for k, v in [
        ("/", "Accueil"), ("/appareils", "Appareils Wi-Fi"), ("/journal", "Journal"), ("/rapports", "Rapports"),
        ("/email", "E-mail"), ("/free", "Réclamation Free"), ("/reglages", "Réglages")])
    note = f"<p class='msg'>{E(msg)}</p>" if msg else ""
    return (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>{E(title)} — {APP_NAME}</title><style>{CSS}</style></head><body><header><a href='/'><img src='/logo.png' alt='{APP_NAME}' height='48' style='display:block'></a>"
            f"<nav>{nav}</nav><span class='st'>{E(m.status)}{(' — ' + E(m.error)) if m.error and not m.connected else ''}"
            f"</span></header><main>{note}{body}</main>{TABLE_JS}</body></html>")


def ev_row(e):
    typ = e["type"]
    if typ.startswith("WIFI_") and typ != "WIFI_DECROCHAGE_COLLECTIF":
        parts = [e.get("appareil") or "?", f"{e.get('borne')} {e.get('bande')}"]
        if e.get("absence_s") is not None:
            parts.append(f"absent {fmt_duration(e['absence_s'])}")
        if e.get("detail"):
            parts.append(e["detail"])
        if e.get("sentinelle"):
            parts.append("sentinelle")
        detail = " — ".join(parts)
    else:
        detail = " ".join(x for x in [e.get("borne"), e.get("detail")] if x)
    cls = "alert" if typ in ("TV_LIEN_COUPE", "INTERNET_COUPE", "REPETEUR_HORS_LIGNE", "BOX_REDEMARRAGE",
                             "WIFI_DECROCHAGE_COLLECTIF") or (typ in ("WIFI_DECONNEXION", "WIFI_COUPURE_BREVE")
                                                              and e.get("sentinelle")) else \
        ("good" if typ.endswith("RETABLI") or typ == "WIFI_RECONNEXION" else "")
    ts = datetime.fromisoformat(e["ts"])
    day = f"{JOURS[ts.weekday()][:3]}. {ts:%d/%m}"
    return (f"<tr class='{cls}'><td data-s='{E(e['ts'])}' data-f='{day}'>{day} {ts:%H:%M:%S}</td>"
            f"<td>{E(LABELS.get(typ, typ))}</td><td>{E(detail)}</td></tr>")


def events_table(evs):
    if not evs:
        return "<p class='muted'>Aucun événement.</p>"
    return ("<table class='data'><tr data-sort='0' data-desc='1'><th>Date et heure</th><th>Événement</th>"
            "<th data-k='texte'>Détail</th></tr>") + "".join(
        ev_row(e) for e in evs) + "</table>"


# =============================================================================== pages
def p_home(q, msg=""):
    st, m = APPLI.store, APPLI.monitor
    if not st.config.get("app_token") or (not m.connected and m.status == "Autorisation nécessaire"):
        return page("Autorisation", f"""<h2>Autoriser l'application sur la Freebox</h2>
<div class='box'><p>Cliquez sur « Autoriser », puis validez la demande sur l'écran de la Freebox Server
(flèche ► puis OK) dans la minute qui suit.</p>
<form method='post' action='/autoriser'><button>Autoriser</button></form>
<p class='muted' id='etat'>{E(APPLI.track and 'Demande envoyée : validez sur la Freebox…' or '')}</p></div>
<script>setTimeout(()=>location.reload(),4000)</script>""", "/", msg)
    s = m.last or {}
    stations = s.get("stations", {})
    reps = s.get("repeaters", {})
    pl = s.get("player")
    rep_ok = all(r.get("status") == "running" for r in reps.values()) if reps else None
    evs = st.events(datetime.now() - timedelta(days=7))
    serious = [e for e in evs if e["type"] not in ("WIFI_RECONNEXION", "WIFI_CHANGEMENT_BORNE")
               and not e["type"].endswith("RETABLI") and not e["type"].startswith("RAPPORT_")]
    card = lambda t, v, d, ok=None: (f"<div class='card'><span>{E(t)}</span><b class='{'' if ok is None else ('ok' if ok else 'ko')}'>"
                                     f"{E(str(v))}</b><span>{E(d)}</span></div>")
    cards = "".join([
        card("Internet", "OK" if s.get("internet") == "up" else (s.get("internet") or "?"),
             f"fibre {s['fibre_rx_dbm']} dBm" if s.get("fibre_rx_dbm") is not None else "", s.get("internet") == "up"),
        card("Appareils Wi-Fi", len(stations), ""),
        card("Répéteur", "–" if rep_ok is None else ("OK" if rep_ok else "Hors ligne"),
             ", ".join(r["name"] for r in reps.values()), rep_ok),
        card("Lien du Player TV", "–" if not pl else ("OK" if pl.get("link") == "up" else "Coupé"),
             f"port {pl['port']} — {pl.get('speed')} Mb/s" if pl else "non trouvé", None if not pl else pl.get("link") == "up"),
        card("Incidents (7 jours)", len(serious), "déconnexions, coupures, erreurs"),
    ])
    rights = ""
    if m.missing_rights:
        rights = ("<p class='warn'>Droits refusés par la Freebox : " + E(", ".join(sorted(m.missing_rights))) +
                  ". Freebox OS › Paramètres › Gestion des accès › Applications › Vigie Freebox.</p>")
    return page("Accueil", f"{rights}<div class='cards'>{cards}</div><h2>Derniers événements</h2>"
                           f"{events_table(list(reversed(evs[-40:])))}<script>setTimeout(function(){{if(!window.vigieTouched)location.reload();}},30000)</script>",
                "/", msg)


def p_devices(q, msg=""):
    st, s = APPLI.store, APPLI.monitor.last or {}
    sent = set(st.config.get("sentinels", []))
    decos = {}
    for e in st.events(datetime.now() - timedelta(days=7)):
        if e["type"] in ("WIFI_DECONNEXION", "WIFI_COUPURE_BREVE") and e.get("mac"):
            decos[e["mac"]] = decos.get(e["mac"], 0) + 1
    rows = dict(s.get("stations", {}))
    for mac in sent:
        rows.setdefault(mac, {"name": st.config.get("aliases", {}).get(mac, mac), "borne": "DÉCONNECTÉ", "bande": "", "signal": None})
    tr = []
    for mac, v in sorted(rows.items(), key=lambda kv: (kv[0] not in sent, str(kv[1]["name"]).lower())):
        tr.append(f"<tr class='{'alert' if v['borne'] == 'DÉCONNECTÉ' else ''}'>"
                  f"<td data-f='{'oui' if mac in sent else 'non'}' data-s='{0 if mac in sent else 1}'>"
                  f"<form class='inline' method='post' action='/sentinelle'><input type='hidden' name='mac' value='{E(mac)}'>"
                  f"<button class='{'' if mac in sent else 'light'}'>{'✔ sentinelle' if mac in sent else 'sentinelle ?'}</button></form></td>"
                  f"<td>{E(str(v['name']))}</td><td>{E(v['borne'])}</td><td>{E(v.get('bande') or '')}</td>"
                  f"<td data-s='{v['signal'] if isinstance(v.get('signal'), (int, float)) else -999}'>"
                  f"{E(str(v['signal']) + ' dBm') if v.get('signal') is not None else ''}</td><td>{E(mac)}</td>"
                  f"<td data-s='{decos.get(mac, 0)}'>{decos.get(mac, 0)}</td></tr>")
    return page("Appareils", "<p class='muted'>Marquez comme sentinelles les appareils qui ne se mettent jamais en veille "
                             "(caméras, prises, imprimantes…).</p><table class='data'><tr data-sort='0'><th>Sentinelle</th>"
                             "<th data-k='texte'>Appareil</th><th>Borne</th><th>Bande</th><th data-k='aucun'>Signal</th>"
                             "<th data-k='texte'>MAC</th><th>Déco. 7 j</th></tr>" + "".join(tr) + "</table>",
                "/appareils", msg)


def p_journal(q, msg=""):
    days = int(q.get("jours", ["7"])[0])
    evs = APPLI.store.events(datetime.now() - timedelta(days=days))
    sel = "".join(f"<a class='btn {'light' if d != days else ''}' href='/journal?jours={d}'>{l}</a> "
                  for d, l in [(1, "24 h"), (7, "7 jours"), (30, "30 jours")])
    return page("Journal", f"<p>{sel}</p>{events_table(list(reversed(evs)))}", "/journal", msg)


def p_reports(q, msg=""):
    cfg = APPLI.store.config
    files = sorted(reports_dir().glob("*.pdf"), reverse=True)[:60]
    li = "".join(f"<tr><td><a href='/fichier/{urllib.parse.quote(p.name)}'>{E(p.name)}</a></td><td>"
                 f"<form class='inline' method='post' action='/envoyer'><input type='hidden' name='nom' value='{E(p.name)}'>"
                 f"<button class='light'>Envoyer par e-mail</button></form></td></tr>" for p in files)
    nxt = next_occurrence(datetime.now(), cfg)
    opts = "".join(f"<option value='{d}' {'selected' if d == 7 else ''}>{E(l)}</option>" for l, d in PERIODES.items())
    return page("Rapports", f"""<div class='box'><b>Rapport automatique :</b> {E(FREQUENCES.get(cfg.get('report_freq'), ''))}
— prochain : {JOURS[nxt.weekday()]} {nxt:%d/%m à %H:%M} <a href='/reglages'>(modifier)</a></div>
<div class='box'><form method='post' action='/generer'>Rapport à la demande sur les <select name='jours' style='width:auto'>{opts}</select>
<button>Générer maintenant</button></form></div>
<h2>Rapports enregistrés</h2>{('<table>' + li + '</table>') if li else "<p class='muted'>Aucun rapport pour l'instant.</p>"}""",
                "/rapports", msg)


def _field(label, name, value, typ="text"):
    return f"<label>{E(label)}</label><input type='{typ}' name='{name}' value='{E(str(value or ''))}'>"


def p_email(q, msg=""):
    c = APPLI.store.config
    presets = "".join(f"<option>{E(k)}</option>" for k in mailer.PRESETS)
    return page("E-mail", f"""<form method='post' action='/email' class='box'>
{_field('Envoyer les rapports à (séparer par des virgules)', 'email_to', c.get('email_to'))}
<label>Ma messagerie</label><select name='preset'>{presets}</select>
{_field("Adresse d'envoi", 'smtp_from', c.get('smtp_from'))}{_field('Identifiant', 'smtp_user', c.get('smtp_user'))}
{_field('Mot de passe (laisser vide pour ne pas changer)', 'password', '', 'password')}
{_field('Serveur SMTP (sinon celui de la messagerie choisie)', 'smtp_host', c.get('smtp_host'))}
{_field('Port', 'smtp_port', c.get('smtp_port'))}
<label>Sécurité</label><select name='smtp_security'>{''.join(f"<option {'selected' if c.get('smtp_security') == v else ''}>{v}</option>" for v in ('ssl', 'starttls', 'aucune'))}</select>
<label><input type='checkbox' name='email_auto' style='width:auto' {'checked' if c.get('email_auto') else ''}> Envoyer automatiquement chaque rapport programmé</label>
<p><button>Enregistrer</button> <button name='test' value='1' class='light'>Enregistrer et envoyer un e-mail de test</button></p></form>""",
                "/email", msg)


def p_free(q, msg=""):
    c = APPLI.store.config
    num = "".join(ch for ch in c.get("abonne_id", "") if ch.isdigit())
    a = analyse(APPLI.store, datetime.now() - timedelta(days=30), datetime.now())
    from .pdf import letter_plain
    txt = letter_plain(c, a)
    return page("Réclamation Free", f"""<form method='post' action='/free' class='box'>
<p class='muted'>Free n'a pas d'adresse e-mail pour son service client : courrier (recommandé) ou messagerie « Mon Assistance ».</p>
{_field('Nom et prénom', 'abonne_nom', c.get('abonne_nom'))}{_field('Identifiant Freebox (fbx…)', 'abonne_id', c.get('abonne_id'))}
{_field('Numéro de ligne', 'abonne_ligne', c.get('abonne_ligne'))}
<label>Adresse postale</label><textarea name='abonne_adresse' rows='3'>{E(c.get('abonne_adresse', ''))}</textarea>
<p><button>Enregistrer</button></p></form>
<div class='box'><form method='post' action='/courrier'><button>Préparer le courrier recommandé (PDF, 30 derniers jours)</button></form></div>
<div class='box'><b>Messagerie Free</b> : copiez le texte ci-dessous, ouvrez
<a href='https://monassistance.free.fr/messagerie{('?id=' + num) if num else ''}' target='_blank'>la messagerie Mon Assistance</a>,
cliquez « Répondre », collez le texte et joignez le PDF du dernier rapport (onglet Rapports).
<textarea rows='14' onclick='this.select()'>{E(txt)}</textarea></div>""", "/free", msg)


def p_settings(q, msg=""):
    c = APPLI.store.config
    freq = "".join(f"<option value='{k}' {'selected' if c.get('report_freq') == k else ''}>{E(v)}</option>"
                   for k, v in FREQUENCES.items())
    jour = lambda name, cur: "".join(f"<option value='{i}' {'selected' if int(cur) == i else ''}>{j}</option>"
                                     for i, j in enumerate(JOURS))
    return page("Réglages", f"""<form method='post' action='/reglages' class='box'>
<label>Fréquence du rapport</label><select name='report_freq'>{freq}</select>
<label>Jour (hebdomadaire / bihebdomadaire)</label><select name='report_day'>{jour('report_day', c.get('report_day', 0))}</select>
<label>Second jour (bihebdomadaire)</label><select name='report_day2'>{jour('report_day2', c.get('report_day2', 3))}</select>
{_field('Heure (HH:MM)', 'report_time', c.get('report_time'))}
<label><input type='checkbox' name='mask_mac' style='width:auto' {'checked' if c.get('mask_mac', True) else ''}> Masquer la fin des adresses MAC</label>
<label><input type='checkbox' name='show_names' style='width:auto' {'checked' if c.get('show_names', True) else ''}> Afficher le nom des appareils</label>
<label>Message d'introduction</label><textarea name='intro_text' rows='4'>{E(c.get('intro_text') or DEFAULT_INTRO)}</textarea>
{_field('Relevé toutes les (secondes)', 'interval', c.get('interval', 20))}
{_field("Mot de passe d'accès à cette page (vide = aucun)", 'web_password', '', 'password')}
<p><button>Enregistrer</button></p></form>
<p class='muted'>{APP_NAME} {__version__} — version serveur. Application communautaire, non officielle.</p>""", "/reglages", msg)


# =============================================================================== actions
def a_autoriser(f):
    try:
        APPLI.track = APPLI.monitor.begin_authorization()

        def poll():
            import time
            for _ in range(60):
                time.sleep(2)
                try:
                    st = APPLI.monitor.authorization_status(APPLI.track)
                except Exception:
                    continue
                if st == "granted":
                    APPLI.monitor.connected = False
                    APPLI.monitor.status = "Connexion…"
                    APPLI.monitor.wake()
                    break
                if st in ("denied", "timeout"):
                    APPLI.store.set("app_token", None)
                    break
            APPLI.track = None
        threading.Thread(target=poll, daemon=True).start()
        return "/", "Demande envoyée : validez sur l'écran de la Freebox."
    except Exception as e:
        return "/", f"Échec : {e}"


def a_sentinelle(f):
    mac = f.get("mac", [""])[0]
    sent = set(APPLI.store.config.get("sentinels", []))
    sent.symmetric_difference_update({mac})
    APPLI.store.set("sentinels", sorted(sent))
    return "/appareils", ""


def a_generer(f):
    days = int(f.get("jours", ["7"])[0])
    res = generate(APPLI.store, days=days, box=APPLI.monitor.box_summary())
    return "/rapports", f"Rapport créé : {res['pdf'].name}"


def a_envoyer(f):
    p = reports_dir() / Path(f.get("nom", [""])[0]).name
    try:
        to = mailer.send(APPLI.store.config, mailer.get_password(APPLI.store),
                         "Rapport des incidents Wi-Fi et TV Freebox",
                         (APPLI.store.config.get("intro_text") or DEFAULT_INTRO) +
                         "\n\nLe rapport complet est joint au format PDF.\n\n— Vigie Freebox", [p])
        return "/rapports", "Envoyé à " + ", ".join(to)
    except Exception as e:
        return "/rapports", f"Envoi impossible : {e}"


def a_email(f):
    c = APPLI.store.config
    for k in ("email_to", "smtp_from", "smtp_user", "smtp_host", "smtp_security"):
        c[k] = f.get(k, [""])[0].strip()
    host, port, sec = mailer.PRESETS.get(f.get("preset", ["Autre"])[0], (None, None, None))
    if host and not c["smtp_host"]:
        c["smtp_host"], c["smtp_security"] = host, sec
        c["smtp_port"] = port
    else:
        try:
            c["smtp_port"] = int(f.get("smtp_port", ["465"])[0])
        except ValueError:
            c["smtp_port"] = 465
    c["email_auto"] = "email_auto" in f
    APPLI.store.save_config()
    if f.get("password", [""])[0]:
        mailer.set_password(APPLI.store, f["password"][0])
    if "test" in f:
        try:
            to = mailer.send(c, mailer.get_password(APPLI.store), f"{APP_NAME} — e-mail de test",
                             "L'envoi des rapports par e-mail fonctionne.")
            return "/email", "E-mail de test envoyé à " + ", ".join(to)
        except Exception as e:
            return "/email", f"Échec de l'envoi : {e}"
    return "/email", "Réglages enregistrés."


def a_free(f):
    c = APPLI.store.config
    for k in ("abonne_nom", "abonne_id", "abonne_ligne", "abonne_adresse"):
        c[k] = f.get(k, [""])[0].strip()
    APPLI.store.save_config()
    return "/free", "Coordonnées enregistrées."


def a_courrier(f):
    from .pdf import render_letter
    a = analyse(APPLI.store, datetime.now() - timedelta(days=30), datetime.now())
    path = reports_dir() / f"reclamation_free_{datetime.now():%Y-%m-%d_%Hh%M}.pdf"
    render_letter(APPLI.store.config, a, APPLI.monitor.box_summary(), path)
    return f"/fichier/{urllib.parse.quote(path.name)}", ""


def a_reglages(f):
    c = APPLI.store.config
    c["report_freq"] = f.get("report_freq", ["hebdomadaire"])[0]
    c["report_day"] = int(f.get("report_day", ["0"])[0])
    c["report_day2"] = int(f.get("report_day2", ["3"])[0])
    t = f.get("report_time", ["07:30"])[0]
    try:
        hh, mm = [int(x) for x in t.split(":")]
        c["report_time"] = f"{hh:02d}:{mm:02d}"
    except ValueError:
        return "/reglages", "Heure invalide (format HH:MM)."
    c["mask_mac"] = "mask_mac" in f
    c["show_names"] = "show_names" in f
    c["intro_text"] = f.get("intro_text", [""])[0].strip() or DEFAULT_INTRO
    try:
        c["interval"] = max(10, int(f.get("interval", ["20"])[0]))
    except ValueError:
        pass
    if f.get("web_password", [""])[0]:
        c["web_password"] = f["web_password"][0]
    c["last_auto_report"] = last_occurrence(datetime.now(), c).isoformat(timespec="minutes")
    APPLI.store.save_config()
    return "/reglages", "Réglages enregistrés."


PAGES = {"/": p_home, "/appareils": p_devices, "/journal": p_journal, "/rapports": p_reports, "/email": p_email,
         "/free": p_free, "/reglages": p_settings}
ACTIONS = {"/autoriser": a_autoriser, "/sentinelle": a_sentinelle, "/generer": a_generer, "/envoyer": a_envoyer,
           "/email": a_email, "/free": a_free, "/courrier": a_courrier, "/reglages": a_reglages}


class Handler(BaseHTTPRequestHandler):
    server_version = "VigieFreebox"

    def log_message(self, *a):
        pass

    def _auth_ok(self):
        pw = APPLI.store.config.get("web_password")
        if not pw:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                return base64.b64decode(h[6:]).decode().split(":", 1)[1] == pw
            except Exception:
                return False
        return False

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _deny(self):
        self._send(401, b"Mot de passe requis", "text/plain; charset=utf-8",
                   {"WWW-Authenticate": 'Basic realm="Vigie Freebox"'})

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/etat":                       # sonde utilisée par l'assistant d'installation
            m = APPLI.monitor
            return self._send(200, json.dumps({"app": APP_NAME, "version": __version__, "connecte": m.connected,
                                               "statut": m.status}).encode(), "application/json")
        if u.path in ("/logo.png", "/favicon.ico"):
            f = ASSETS / ("logo_110.png" if u.path == "/logo.png" else "icon.ico")
            if f.is_file():
                return self._send(200, f.read_bytes(), "image/png" if f.suffix == ".png" else "image/x-icon",
                                  {"Cache-Control": "max-age=86400"})
            return self._send(404, b"", "text/plain")
        if not self._auth_ok():
            return self._deny()
        if u.path.startswith("/fichier/"):
            name = Path(urllib.parse.unquote(u.path[len("/fichier/"):])).name
            p = reports_dir() / name
            if not p.is_file():
                return self._send(404, b"introuvable", "text/plain")
            return self._send(200, p.read_bytes(), "application/pdf" if p.suffix == ".pdf" else "text/plain; charset=utf-8",
                              {"Content-Disposition": f'inline; filename="{name}"'})
        fn = PAGES.get(u.path)
        if not fn:
            return self._send(404, b"page introuvable", "text/plain")
        q = urllib.parse.parse_qs(u.query)
        self._send(200, fn(q, q.get("msg", [""])[0]).encode("utf-8"))

    def do_POST(self):
        if not self._auth_ok():
            return self._deny()
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
        fn = ACTIONS.get(u.path)
        if not fn:
            return self._send(404, b"action inconnue", "text/plain")
        try:
            dest, msg = fn(form)
        except Exception as e:
            dest, msg = "/", f"Erreur : {e}"
        sep = "&" if "?" in dest else "?"
        self._send(303, b"", extra={"Location": dest + (f"{sep}msg={urllib.parse.quote(msg)}" if msg else "")})


def main(argv=None):
    global APPLI
    ap = argparse.ArgumentParser(description="Vigie Freebox — version serveur avec interface web")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args(argv)
    APPLI = App()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"{APP_NAME} {__version__} — interface web sur http://{args.host}:{args.port}/", flush=True)
    try:
        srv.serve_forever()
    finally:
        APPLI.monitor.stop()


if __name__ == "__main__":
    main()
