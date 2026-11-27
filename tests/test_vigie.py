"""Tests avec une fausse Freebox (aucun accès réseau)."""

import copy
from datetime import datetime, timedelta

import pytest

from vigie.api import PermissionMissing
from vigie.monitor import Monitor
from vigie.report import generate
from vigie.store import Store


class FakeAPI:
    def __init__(self):
        self.box_info = {"box_model_name": "Freebox v7 (r1)"}
        self.app_token = "x"
        self.uptime = 1000
        self.link = "up"
        self.speed = "1000"
        self.fcs = 0
        self.internet = "up"
        self.rep_status = "running"
        self.gw = {
            "AA:BB:CC:00:00:01": ("Caméra AVANT", 0),
            "AA:BB:CC:00:00:02": ("Téléphone", 1),
            "AA:BB:CC:00:00:03": ("Tablette", 1),
            "AA:BB:CC:00:00:04": ("Imprimante", 1),
        }
        self.rep = {"AA:BB:CC:00:00:10": "Caméra solaire"}
        self.deny_stations = False
        self.deny_hosts = False
        self.tick = 1000
        self.sess = {}       # MAC -> durée de session imposée (sinon elle avance de 20 s par relevé)

    def discover(self):
        return self.box_info

    def login(self):
        return {}

    def get(self, path):
        if path == "/system/":
            return {"uptime_val": self.uptime, "firmware_version": "4.9.0", "model_info": {"pretty_name": "Freebox v7 (r1)"}}
        if path == "/connection/":
            return {"state": self.internet, "media": "ftth"}
        if path == "/connection/ftth/":
            return {"sfp_has_signal": True, "sfp_pwr_rx": -1850}
        if path == "/wifi/ap/":
            return [{"id": 0, "config": {"band": "2d4g"}}, {"id": 1, "config": {"band": "5g"}}]
        if path.startswith("/wifi/ap/"):
            if self.deny_stations:
                raise PermissionMissing("droits", "insufficient_rights")
            ap = int(path.split("/")[3])
            return [{"mac": m, "state": "authenticated", "signal": -60, "host": {"primary_name": n}}
                    for m, (n, a) in self.gw.items() if a == ap]
        if path == "/repeater/":
            return [{"id": 1, "name": "Répéteur salon", "status": self.rep_status, "main_mac": "AA:BB:CC:99:99:99",
                     "uid": "rep-uid-1"}]
        if path == "/lan/browser/pub/":
            self.tick += 20
            if self.deny_hosts:
                raise PermissionMissing("droits", "insufficient_rights")
            hosts = []
            for m, (n, a) in self.gw.items():
                hosts.append({"l2ident": {"id": m}, "primary_name": n, "active": True,
                              "access_point": {"type": "gateway", "connectivity_type": "wifi",
                                               "wifi_information": {"band": "2d4g" if a == 0 else "5g", "signal": -60,
                                                                    "sess_duration": self.sess.get(m, self.tick)}}})
            for m, n in self.rep.items():
                hosts.append({"l2ident": {"id": m}, "primary_name": n, "active": True,
                              "access_point": {"type": "repeater", "uid": "rep-uid-1", "connectivity_type": "wifi",
                                               "wifi_information": {"band": "5g", "signal": -70,
                                                                    "sess_duration": self.sess.get(m, self.tick)}}})
            hosts.append({"l2ident": {"id": "AA:BB:CC:00:00:50"}, "primary_name": "Freebox Player", "active": True,
                          "vendor_name": "Freebox SAS", "access_point": {"connectivity_type": "ethernet"}})
            return hosts
        if path == "/switch/status/":
            return [{"id": 1, "link": "up", "speed": "1000", "duplex": "full", "mac_list": []},
                    {"id": 2, "link": self.link, "speed": self.speed, "duplex": "full",
                     "mac_list": [{"mac": "AA:BB:CC:00:00:50", "hostname": "Freebox Player"}]}]
        if path == "/switch/port/2/stats/":
            return {"rx_fcs_packets": self.fcs, "rx_err_packets": 0}
        return {}


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data")
    store.set("app_token", "x")
    store.set("sentinels", ["AA:BB:CC:00:00:01"])
    api = FakeAPI()
    mon = Monitor(store, api)
    mon.connected = True
    return store, api, mon


def types(store):
    return [e["type"] for e in store.events()]


def test_wifi_deconnexion_reconnexion(env):
    store, api, mon = env
    mon.poll_once()
    assert types(store) == []
    saved = api.gw.pop("AA:BB:CC:00:00:01")
    mon.poll_once()
    assert types(store) == ["WIFI_DECONNEXION"]
    ev = store.events()[0]
    assert ev["appareil"] == "Caméra AVANT" and ev["bande"] == "2,4 GHz" and ev["sentinelle"] is True
    api.gw["AA:BB:CC:00:00:01"] = saved
    mon.poll_once()
    assert types(store)[-1] == "WIFI_RECONNEXION"


def test_decrochage_collectif_et_repeteur(env):
    store, api, mon = env
    mon.poll_once()
    for m in ["AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03", "AA:BB:CC:00:00:04"]:
        api.gw.pop(m)
    api.rep_status = "disconnected"
    api.rep.clear()
    mon.poll_once()
    t = types(store)
    assert t.count("WIFI_DECONNEXION") == 4
    assert "WIFI_DECROCHAGE_COLLECTIF" in t
    assert "REPETEUR_HORS_LIGNE" in t


def test_source_indisponible_ne_cree_pas_de_fausse_deconnexion(env):
    store, api, mon = env
    mon.poll_once()
    api.deny_hosts = True
    api.deny_stations = True
    mon.poll_once()
    assert "WIFI_DECONNEXION" not in types(store)


def test_repli_sur_les_bornes_si_navigateur_refuse(env):
    store, api, mon = env
    api.deny_hosts = True
    mon.poll_once()
    assert len(mon.last["stations"]) == 4          # seulement les appareils de la Freebox Server
    api.gw.pop("AA:BB:CC:00:00:02")
    mon.poll_once()
    assert types(store) == ["WIFI_DECONNEXION"]


def test_coupure_breve_session_redemarree(env):
    store, api, mon = env
    mon.poll_once()
    api.sess["AA:BB:CC:00:00:10"] = 3              # la session de la caméra solaire repart de zéro
    mon.poll_once()
    ev = store.events()[-1]
    assert ev["type"] == "WIFI_COUPURE_BREVE" and ev["borne"] == "Répéteur salon" and ev["sentinelle"] is False


def test_session_figee_vaut_deconnexion(env):
    store, api, mon = env
    mon.poll_once()
    api.sess["AA:BB:CC:00:00:01"] = 5000           # toujours listée mais la session n'avance plus
    for _ in range(4):
        mon.poll_once()
    assert types(store).count("WIFI_DECONNEXION") == 1
    api.sess.pop("AA:BB:CC:00:00:01")              # elle repart
    mon.poll_once()
    assert types(store)[-1] == "WIFI_RECONNEXION"


def test_tv_et_box(env):
    store, api, mon = env
    mon.poll_once()
    api.link = "down"
    mon.poll_once()
    api.link, api.speed, api.fcs = "up", "100", 42
    mon.poll_once()
    api.uptime = 10
    api.internet = "down"
    mon.poll_once()
    t = types(store)
    assert "TV_LIEN_COUPE" in t and "TV_LIEN_RETABLI" in t and "TV_ERREURS" in t
    assert "BOX_REDEMARRAGE" in t and "INTERNET_COUPE" in t


def test_rapport_hebdo(env, tmp_path):
    store, api, mon = env
    mon.poll_once()
    api.gw.pop("AA:BB:CC:00:00:01")
    mon.poll_once()
    api.link = "down"
    mon.poll_once()
    out = generate(store, box=mon.box_summary(), out_dir=tmp_path / "rapports")
    html = out["html"].read_text(encoding="utf-8")
    txt = out["txt"].read_text(encoding="utf-8")
    assert "Rapport des incidents" in html and "Caméra AVANT" in html
    assert "Article 10 (« Qualité de service »)" in html and "Article 1231-1 du Code civil" in txt
    assert txt.index("Article 10") < txt.index("Période")      # le message est en introduction
    assert out["pdf"].read_bytes()[:4] == b"%PDF"
    assert "AA:BB:CC:••:••:••" in html          # MAC masquée
    assert "AA:BB:CC:00:00:01" not in html
    assert "SENTINELLE" in txt and "Lien Player coupé" in txt
    store.set("show_names", False)
    html2 = generate(store, out_dir=tmp_path / "r2")["html"].read_text(encoding="utf-8")
    assert "Caméra AVANT" not in html2 and "Appareil 1" in html2


def test_planification_hebdo(env, tmp_path, monkeypatch):
    store, api, mon = env
    monkeypatch.setattr("vigie.report.reports_dir", lambda: tmp_path / "auto")
    mon.poll_once()
    api.gw.pop("AA:BB:CC:00:00:02")
    mon.poll_once()
    store.set("report_day", 0)
    store.set("report_time", "07:30")
    assert mon.check_weekly_report(datetime(2026, 11, 25, 9, 0)) is None   # 1re utilisation : pas de rapport
    assert store.config["last_auto_report"] == "2026-11-23T07:30"
    lundi = datetime(2026, 11, 30, 8, 0)        # un lundi après 7 h 30
    assert mon.last_scheduled(lundi) == datetime(2026, 11, 30, 7, 30)
    assert mon.last_scheduled(datetime(2026, 11, 30, 7, 0)) == datetime(2026, 11, 23, 7, 30)
    p = mon.check_weekly_report(lundi)
    assert p and p["html"].exists()
    assert mon.check_weekly_report(lundi + timedelta(hours=2)) is None   # pas deux fois
    assert store.config["last_auto_report"] == "2026-11-30T07:30"
    assert "hebdomadaire" in p["title"] and p["start"] == datetime(2026, 11, 23, 7, 30)


def test_prune(env):
    store, api, mon = env
    store.add_event({"ts": (datetime.now() - timedelta(days=200)).isoformat(), "type": "X"})
    store.add_event({"type": "Y"})
    store.prune()
    assert types(store) == ["Y"]


def test_frequences():
    from vigie.schedule import last_occurrence, next_occurrence, previous_occurrence
    jeudi = datetime(2026, 11, 26, 12, 0)
    cfg = {"report_freq": "quotidien", "report_time": "07:30"}
    assert last_occurrence(jeudi, cfg) == datetime(2026, 11, 26, 7, 30)
    assert previous_occurrence(datetime(2026, 11, 26, 7, 30), cfg) == datetime(2026, 11, 25, 7, 30)
    cfg = {"report_freq": "bihebdomadaire", "report_day": 0, "report_day2": 3, "report_time": "07:30"}
    assert last_occurrence(jeudi, cfg) == datetime(2026, 11, 26, 7, 30)
    assert previous_occurrence(datetime(2026, 11, 26, 7, 30), cfg) == datetime(2026, 11, 23, 7, 30)
    assert next_occurrence(jeudi, cfg) == datetime(2026, 11, 30, 7, 30)
    cfg = {"report_freq": "bimensuel", "report_time": "08:00"}
    assert last_occurrence(jeudi, cfg) == datetime(2026, 11, 15, 8, 0)
    assert next_occurrence(jeudi, cfg) == datetime(2026, 12, 1, 8, 0)


def test_courrier_free_et_mail(env, tmp_path, monkeypatch):
    store, api, mon = env
    mon.poll_once()
    api.gw.pop("AA:BB:CC:00:00:01")
    mon.poll_once()
    store.config.update({"abonne_nom": "Jean Test", "abonne_adresse": "1 rue X\n57000 Metz", "abonne_id": "fbx1"})
    from vigie.pdf import letter_plain, render_letter
    from vigie.report import analyse, generate
    a = analyse(store, datetime.now() - timedelta(days=7), datetime.now())
    p = render_letter(store.config, a, {}, tmp_path / "lettre.pdf")
    assert p.read_bytes()[:4] == b"%PDF"
    txt = letter_plain(store.config, a)
    assert "Article 10" in txt and "fbx1" in txt and "Médiateur" in txt

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            sent["host"] = host
        def ehlo(self): pass
        def login(self, u, p): sent["login"] = (u, p)
        def send_message(self, m):
            sent["to"] = m["To"]
            sent["files"] = [x.get_filename() for x in m.iter_attachments()]
        def quit(self): pass

    import vigie.mailer as mailer
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailer, "get_password", lambda st: "secret")
    store.config.update({"email_to": "moi@example.fr", "smtp_host": "smtp.example.fr", "smtp_user": "moi@example.fr"})
    res = generate(store, out_dir=tmp_path / "r")
    msg = mon.mail_report(res)
    assert msg.startswith("envoyé") and sent["to"] == "moi@example.fr" and sent["files"][0].endswith(".pdf")
    assert sent["login"] == ("moi@example.fr", "secret")
