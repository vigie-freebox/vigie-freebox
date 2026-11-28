"""Assistant « surveillance permanente » : installe Vigie Freebox dans une machine virtuelle de la Freebox.

Fonctionne avec les Freebox qui proposent les VM (Delta, premières Ultra). Tout passe par l'API officielle
de Freebox OS :
  1. vérification    GET  /vm/info/                      (refusé ou absent : pas de VM sur cette box)
  2. stockage        GET  /fs/ls/<chemin base64>          (disque de la box, dossier « VMs »)
  3. image Debian    GET  /vm/distros/  puis POST /downloads/add  (téléchargée par la Freebox elle-même)
  4. disque          POST /vm/disk/resize/  + GET /vm/disk/task/<id>
  5. VM              POST /vm/  (cloud-init installe et lance Vigie)  puis POST /vm/<id>/start
  6. attente         navigateur réseau : la VM « vigie-freebox » obtient une adresse, l'interface web répond
"""

from __future__ import annotations

import base64
import json
import time

import requests

from .api import FreeboxError, PermissionMissing

VM_NAME = "vigie-freebox"
DISK_NAME = "vigie-freebox.qcow2"
DISK_SIZE = 6 * 1024 ** 3          # 6 Go vus par la VM (l'image n'occupe que l'espace réellement utilisé)
VM_MEMORY = 512                    # Mo
WEB_PORT = 8099
REPO = "https://github.com/vigie-freebox/vigie-freebox"
RIGHTS_LABEL = ("Gestion des machines virtuelles, Accès au gestionnaire de téléchargements et "
                "Accès aux fichiers de la Freebox")


def b64(path: str) -> str:
    return base64.b64encode(path.encode("utf-8")).decode("ascii")


class VMSetupError(Exception):
    pass


def cloud_init(config: dict) -> str:
    """user-data cloud-init : installe Vigie et reprend la configuration de l'application du PC."""
    cfg = {k: v for k, v in config.items() if k not in ("smtp_password_local", "last_auto_report")}
    cfg_json = json.dumps(cfg, ensure_ascii=False, indent=2)
    indented = "\n".join("      " + line for line in cfg_json.splitlines())
    return f"""#cloud-config
hostname: {VM_NAME}
package_update: true
packages:
  - python3
  - python3-venv
  - git
  - fonts-dejavu-core
write_files:
  - path: /var/lib/vigie-freebox/config.json
    permissions: '0600'
    content: |
{indented}
runcmd:
  - [bash, -c, "git clone --depth 1 {REPO} /opt/vigie-freebox && bash /opt/vigie-freebox/serveur/install.sh"]
"""


class VMInstaller:
    def __init__(self, api, store, log=print):
        self.api = api
        self.store = store
        self.log = log
        self.vm_id = None
        self.vm_mac = None

    # ---------------------------------------------------------------- vérification
    def check(self) -> dict:
        """Renvoie {'ok': bool, 'message': str, ...} sans rien modifier sur la Freebox."""
        try:
            self.api.discover()
            self.api.login()
        except FreeboxError as e:
            return {"ok": False, "message": f"Freebox injoignable ou application non autorisée : {e}"}
        perms = self.api.permissions or {}
        missing = [p for p in ("vm", "downloader", "explorer") if perms and not perms.get(p)]
        try:
            info = self.api.get("/vm/info/")
        except PermissionMissing:
            return {"ok": False, "rights": True, "message": (
                "La Freebox refuse l'accès aux machines virtuelles à l'application. Dans Freebox OS › Paramètres "
                "de la Freebox › Gestion des accès › Applications › Vigie Freebox, cochez : " + RIGHTS_LABEL + ".")}
        except FreeboxError as e:
            return {"ok": False, "message": (
                "Cette Freebox ne propose pas de machines virtuelles (seules la Delta et les premières Ultra "
                f"le permettent). Détail : {e}")}
        if missing:
            return {"ok": False, "rights": True, "message": (
                "Il manque des droits à l'application (" + ", ".join(missing) + "). Dans Freebox OS › Paramètres "
                "de la Freebox › Gestion des accès › Applications › Vigie Freebox, cochez : " + RIGHTS_LABEL + ".")}
        free_mem = (info.get("total_memory") or 0) - (info.get("used_memory") or 0)
        free_cpu = (info.get("total_cpus") or 0) - (info.get("used_cpus") or 0)
        existing = self.existing_vm()
        if existing:
            return {"ok": True, "existing": existing, "message": (
                f"Une VM « {VM_NAME} » existe déjà (état : {existing.get('status')}).")}
        if free_mem < VM_MEMORY or free_cpu < 1:
            return {"ok": False, "message": (
                f"Ressources insuffisantes : {free_mem} Mo de mémoire et {free_cpu} processeur(s) libres "
                f"(il faut {VM_MEMORY} Mo et 1 processeur). Arrêtez ou réduisez une autre VM.")}
        try:
            root = self.storage_root()
        except VMSetupError as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "message": (
            f"Machines virtuelles disponibles : {free_mem} Mo et {free_cpu} processeur(s) libres, "
            f"stockage « {root} ». La VM utilisera {VM_MEMORY} Mo et 1 processeur."), "root": root}

    def existing_vm(self):
        for vm in self.api.get("/vm/") or []:
            if vm.get("name") == VM_NAME:
                self.vm_id, self.vm_mac = vm.get("id"), vm.get("mac")
                return vm
        return None

    def storage_root(self) -> str:
        try:
            entries = self.api.get("/fs/ls/" + b64("/")) or []
        except FreeboxError as e:
            raise VMSetupError(f"Impossible de lire le stockage de la Freebox : {e}")
        dirs = [e.get("name") for e in entries if e.get("type") == "dir" and e.get("name")]
        if not dirs:
            raise VMSetupError("Aucun disque n'est disponible sur la Freebox pour stocker la VM "
                               "(sur la Delta, il faut un disque interne ou externe).")
        for d in dirs:                                   # le disque qui contient déjà un dossier VMs
            try:
                names = [e.get("name") for e in (self.api.get("/fs/ls/" + b64(f"/{d}")) or [])]
            except FreeboxError:
                continue
            if "VMs" in names:
                return d
        return dirs[0]

    # ---------------------------------------------------------------- installation
    def install(self, wait_web=True) -> dict:
        chk = self.check()
        if not chk["ok"]:
            raise VMSetupError(chk["message"])
        if chk.get("existing"):
            self.log(chk["message"] + " Démarrage si nécessaire…")
            if chk["existing"].get("status") != "running":
                self.api.call("POST", f"/vm/{self.vm_id}/start")
            return self.wait_ready(wait_web)
        root = chk["root"]
        vm_dir = f"/{root}/VMs"
        self._mkdir(f"/{root}", "VMs")
        disk = f"{vm_dir}/{DISK_NAME}"

        distro = self._debian()
        self.log(f"Téléchargement de l'image {distro.get('name')} par la Freebox…")
        self._download(distro, vm_dir)

        self.log("Agrandissement du disque virtuel…")
        task = self.api.call("POST", "/vm/disk/resize/", {"disk_path": b64(disk), "size": DISK_SIZE,
                                                          "shrink_allow": False})
        self._wait_disk_task(task.get("id") if isinstance(task, dict) else None)

        self.log("Création de la machine virtuelle…")
        vm = self.api.call("POST", "/vm/", {
            "name": VM_NAME, "disk_path": b64(disk), "disk_type": "qcow2", "memory": VM_MEMORY, "vcpus": 1,
            "os": "debian", "enable_screen": False, "enable_cloudinit": True,
            "cloudinit_hostname": VM_NAME, "cloudinit_userdata": cloud_init(self.store.config),
        })
        self.vm_id, self.vm_mac = vm.get("id"), vm.get("mac")
        self.log("Démarrage de la machine virtuelle…")
        self.api.call("POST", f"/vm/{self.vm_id}/start")
        return self.wait_ready(wait_web)

    def _mkdir(self, parent, name):
        try:
            names = [e.get("name") for e in (self.api.get("/fs/ls/" + b64(parent)) or [])]
            if name not in names:
                self.api.call("POST", "/fs/mkdir/", {"parent": b64(parent), "dirname": name})
        except FreeboxError as e:
            raise VMSetupError(f"Impossible de créer le dossier {parent}/{name} : {e}")

    def _debian(self) -> dict:
        distros = self.api.get("/vm/distros/") or []
        deb = [d for d in distros if (d.get("os") == "debian") or "debian" in (d.get("name") or "").lower()]
        if not deb:
            raise VMSetupError("La Freebox ne propose pas d'image Debian prête à l'emploi.")
        return sorted(deb, key=lambda d: d.get("name") or "")[-1]

    def _download(self, distro, vm_dir, timeout=1800):
        form = {"download_url": distro["url"], "download_dir": b64(vm_dir), "filename": DISK_NAME}
        if distro.get("hash"):
            form["hash"] = distro["hash"]
        res = self.api.post_form("/downloads/add", form)
        tid = res.get("id")
        t0, last = time.time(), -1
        while time.time() - t0 < timeout:
            d = self.api.get(f"/downloads/{tid}") or {}
            st = d.get("status")
            pct = int((d.get("rx_pct") or 0) / 100)
            if pct // 10 != last // 10:
                self.log(f"  téléchargement : {pct} %")
                last = pct
            if st == "done":
                try:
                    self.api.call("DELETE", f"/downloads/{tid}")   # retire la tâche, garde le fichier
                except FreeboxError:
                    pass
                return
            if st == "error":
                raise VMSetupError(f"Échec du téléchargement de l'image : {d.get('error')}")
            time.sleep(3)
        raise VMSetupError("Téléchargement de l'image trop long (plus de 30 min).")

    def _wait_disk_task(self, tid, timeout=600):
        if tid is None:
            return
        t0 = time.time()
        while time.time() - t0 < timeout:
            t = self.api.get(f"/vm/disk/task/{tid}") or {}
            if t.get("error"):
                raise VMSetupError("La Freebox n'a pas pu agrandir le disque virtuel.")
            if t.get("done"):
                try:
                    self.api.call("DELETE", f"/vm/disk/task/{tid}")
                except FreeboxError:
                    pass
                return
            time.sleep(2)
        raise VMSetupError("Agrandissement du disque trop long.")

    # ---------------------------------------------------------------- attente
    def vm_ip(self):
        mac = (self.vm_mac or "").upper()
        for h in self.api.get("/lan/browser/pub/") or []:
            hmac = str((h.get("l2ident") or {}).get("id", "")).upper()
            if (mac and hmac == mac) or h.get("primary_name") == VM_NAME:
                for c in h.get("l3connectivities") or []:
                    if c.get("af") == "ipv4" and c.get("addr"):
                        return c["addr"]
        return None

    def wait_ready(self, wait_web=True, timeout=1500) -> dict:
        self.log("Installation de Vigie dans la VM (5 à 15 minutes : mise à jour de Debian, puis de l'application)…")
        t0, ip = time.time(), None
        while time.time() - t0 < timeout:
            ip = ip or self.vm_ip()
            if ip and not wait_web:
                break
            if ip:
                try:
                    r = requests.get(f"http://{ip}:{WEB_PORT}/etat", timeout=4)
                    if r.ok:
                        url = f"http://{ip}:{WEB_PORT}/"
                        self.store.set("vm_url", url)
                        self.log(f"Surveillance permanente opérationnelle : {url}")
                        return {"ip": ip, "url": url}
                except requests.RequestException:
                    pass
            time.sleep(10)
        if ip:
            url = f"http://{ip}:{WEB_PORT}/"
            self.store.set("vm_url", url)
            return {"ip": ip, "url": url, "pending": True}
        raise VMSetupError("La VM a démarré mais n'apparaît pas encore sur le réseau. Réessayez dans quelques minutes.")
