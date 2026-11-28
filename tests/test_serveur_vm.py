"""Version serveur (interface web) et assistant d'installation de la VM, avec une fausse Freebox."""

import base64
import json
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import vigie.server as server
from vigie.monitor import Monitor
from vigie.store import Store
from vigie.vmsetup import VM_NAME, VMInstaller, VMSetupError, cloud_init
from test_vigie import FakeAPI


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("VIGIE_DATA", str(tmp_path / "data"))
    store = Store()
    store.set("app_token", "x")
    api = FakeAPI()
    app = server.App.__new__(server.App)
    app.store, app.track = store, None
    app.monitor = Monitor(store, api)
    app.monitor.connected = True
    app.monitor.poll_once()
    api.gw.pop("AA:BB:CC:00:00:01")
    app.monitor.poll_once()
    server.APPLI = app
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", store
    srv.shutdown()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read().decode("utf-8", "replace")


def post(url, data):
    op = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        op.open(req)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location")


def test_pages_web(web):
    base, store = web
    for p in ["/", "/appareils", "/journal?jours=30", "/rapports", "/email", "/free", "/reglages"]:
        code, body = get(base + p)
        assert code == 200 and "Vigie Freebox" in body, p
    assert "Déconnexion Wi-Fi" in get(base + "/")[1]
    assert json.loads(get(base + "/etat")[1])["connecte"] is True


def test_actions_web(web):
    base, store = web
    code, loc = post(base + "/sentinelle", {"mac": "AA:BB:CC:00:00:02"})
    assert code == 303 and "AA:BB:CC:00:00:02" in store.config["sentinels"]
    code, loc = post(base + "/generer", {"jours": "7"})
    assert code == 303 and "Rapport" in urllib.parse.unquote(loc)
    name = sorted((store.root / "rapports").glob("*.pdf"))[0].name
    code, body = get(base + "/fichier/" + urllib.parse.quote(name))
    assert code == 200
    code, loc = post(base + "/reglages", {"report_freq": "quotidien", "report_day": "0", "report_day2": "3",
                                         "report_time": "08:15", "intro_text": "Texte", "interval": "30"})
    assert store.config["report_freq"] == "quotidien" and store.config["report_time"] == "08:15"
    code, loc = post(base + "/courrier", {})
    assert code == 303 and loc.startswith("/fichier/reclamation_free_")


def test_mot_de_passe_web(web):
    base, store = web
    store.set("web_password", "secret")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/")
    assert e.value.code == 401
    req = urllib.request.Request(base + "/", headers={"Authorization": "Basic " + base64.b64encode(b"x:secret").decode()})
    assert urllib.request.urlopen(req).status == 200
    assert get(base + "/etat")[0] == 200            # la sonde reste accessible


def test_cloud_init_valide():
    yaml = pytest.importorskip("yaml")
    cfg = {"app_token": "abc", "sentinels": ["AA"], "intro_text": "Je paie « un » abonnement\nligne 2",
           "smtp_password_local": "NE PAS COPIER"}
    doc = cloud_init(cfg)
    assert doc.startswith("#cloud-config")
    y = yaml.safe_load(doc)
    copied = json.loads(y["write_files"][0]["content"])
    assert copied["app_token"] == "abc" and "smtp_password_local" not in copied
    assert "install.sh" in " ".join(y["runcmd"][0])


class FakeVMAPI:
    def __init__(self, has_vm=True, perms=None):
        self.has_vm, self.permissions = has_vm, perms or {"vm": True, "downloader": True, "explorer": True}
        self.calls, self.vms, self.dirs = [], [], {"/": ["Freebox"], "/Freebox": ["Téléchargements"]}
        self.dl = 0

    def discover(self):
        return {}

    def login(self):
        return {}

    def get(self, path):
        from vigie.api import FreeboxError
        if path == "/vm/info/":
            if not self.has_vm:
                raise FreeboxError("Service indisponible", "nodev")
            return {"total_memory": 2048, "used_memory": 0, "total_cpus": 2, "used_cpus": 0}
        if path == "/vm/":
            return self.vms
        if path.startswith("/fs/ls/"):
            p = base64.b64decode(path[7:]).decode()
            return [{"name": n, "type": "dir"} for n in self.dirs.get(p, [])]
        if path == "/vm/distros/":
            return [{"name": "Debian 12", "os": "debian", "url": "https://ftp.free.fr/debian.qcow2", "hash": ""},
                    {"name": "Ubuntu", "os": "ubuntu", "url": "u"}]
        if path.startswith("/downloads/"):
            self.dl += 5000
            return {"status": "done" if self.dl >= 10000 else "downloading", "rx_pct": min(self.dl, 10000)}
        if path.startswith("/vm/disk/task/"):
            return {"done": True}
        if path == "/lan/browser/pub/":
            return [{"l2ident": {"id": "02:00:00:00:00:99"}, "primary_name": VM_NAME,
                     "l3connectivities": [{"af": "ipv4", "addr": "192.168.1.77"}]}]
        return {}

    def post_form(self, path, form):
        self.calls.append(("FORM", path, form))
        return {"id": 3}

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == "/fs/mkdir/":
            self.dirs["/Freebox"].append("VMs")
        if path == "/vm/disk/resize/":
            return {"id": 9}
        if path == "/vm/" and method == "POST":
            vm = {"id": 1, "mac": "02:00:00:00:00:99", "name": payload["name"], "status": "stopped"}
            self.vms.append(vm)
            return vm
        return {}


def test_vm_absente(tmp_path):
    inst = VMInstaller(FakeVMAPI(has_vm=False), Store(tmp_path), log=lambda m: None)
    r = inst.check()
    assert not r["ok"] and "ne propose pas de machines virtuelles" in r["message"]


def test_vm_droits_manquants(tmp_path):
    inst = VMInstaller(FakeVMAPI(perms={"vm": False, "downloader": True, "explorer": True}), Store(tmp_path), log=lambda m: None)
    r = inst.check()
    assert not r["ok"] and r.get("rights")


def test_installation_vm(tmp_path, monkeypatch):
    monkeypatch.setattr("vigie.vmsetup.time.sleep", lambda s: None)
    store = Store(tmp_path)
    store.set("app_token", "tok")
    api = FakeVMAPI()
    logs = []
    inst = VMInstaller(api, store, log=logs.append)
    assert inst.check()["ok"]
    res = inst.install(wait_web=False)
    assert res["ip"] == "192.168.1.77" and store.config["vm_url"] == "http://192.168.1.77:8099/"
    form = next(c for c in api.calls if c[0] == "FORM")[2]
    assert base64.b64decode(form["download_dir"]).decode() == "/Freebox/VMs"
    create = next(c for c in api.calls if c[1] == "/vm/" and c[0] == "POST")[2]
    assert base64.b64decode(create["disk_path"]).decode() == "/Freebox/VMs/vigie-freebox.qcow2"
    assert create["enable_cloudinit"] and "tok" in create["cloudinit_userdata"]
    assert ("POST", "/vm/1/start", None) in api.calls
    # deuxième passage : la VM existe déjà, rien n'est recréé
    inst2 = VMInstaller(api, store, log=logs.append)
    assert inst2.check().get("existing")
