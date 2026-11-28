"""Relevés périodiques de la Freebox et détection des incidents.

Événements enregistrés (champ « type ») :
  WIFI_DECONNEXION        un appareil Wi-Fi disparaît d'une borne (Freebox ou répéteur)
  WIFI_RECONNEXION        il réapparaît (durée d'absence indiquée)
  WIFI_COUPURE_BREVE      sa session radio a redémarré entre deux relevés (coupure courte)
  WIFI_CHANGEMENT_BORNE   il passe d'une borne/bande à une autre (itinérance, information)
  WIFI_DECROCHAGE_COLLECTIF  au moins 3 appareils perdus au même moment sur la même borne
  REPETEUR_HORS_LIGNE / REPETEUR_RETABLI
  INTERNET_COUPE / INTERNET_RETABLI
  FIBRE                   perte ou retour du signal optique
  BOX_REDEMARRAGE         la Freebox Server a redémarré
  TV_LIEN_COUPE / TV_LIEN_RETABLI   le câble du Player perd / retrouve le lien Ethernet
  TV_LIEN_VITESSE         la vitesse ou le duplex négociés changent
  TV_ERREURS              des trames corrompues apparaissent sur le port du Player
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from .api import AuthRequired, FreeboxAPI, FreeboxError, PermissionMissing
from .store import Store

BANDS = {"2d4g": "2,4 GHz", "5g": "5 GHz", "6g": "6 GHz", "60g": "60 GHz"}
COLLECTIVE_MIN = 3
FROZEN_POLLS = 3      # relevés sans progression de la session radio avant de conclure à une perte


def band_label(b) -> str:
    if not b:
        return "?"
    b = str(b).lower().replace(".", "d").replace(",", "d")
    return BANDS.get(b, BANDS.get(b.replace("ghz", "g"), str(b)))


def norm_mac(m) -> str:
    return str(m or "").upper().replace("-", ":")


class Monitor:
    def __init__(self, store: Store, api: FreeboxAPI | None = None, report_callback=None):
        self.store = store
        cfg = store.config
        self.api = api or FreeboxAPI(cfg["freebox_url"], cfg.get("app_token"))
        self.report_callback = report_callback  # appelé avec (chemin_html) après un rapport auto
        self.prev: dict | None = None
        self.last: dict | None = None
        self.absent: dict[str, dict] = {}     # mac -> infos au moment de la perte
        self._frozen: dict[str, int] = {}
        self._frozen_ref: dict[str, dict] = {}
        self.status = "Démarrage…"
        self.error: str | None = None
        self.missing_rights: set[str] = set()
        self.connected = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.listeners = []                    # fonctions appelées après chaque relevé

    # ================================================================ cycle de vie
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="vigie-monitor")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def wake(self):
        """Relance un relevé tout de suite (après une autorisation, un changement de réglage…)."""
        self._wake.set()

    def _loop(self):
        pruned_day = None
        while not self._stop.is_set():
            if not self.store.config.get("local_monitoring", True):
                self.status = "Surveillance assurée par la machine virtuelle de la Freebox"
                for fn in list(self.listeners):
                    try:
                        fn()
                    except Exception:
                        pass
                self._wake.wait(30)
                self._wake.clear()
                continue
            try:
                if not self.connected:
                    self.connect()
                if self.connected:
                    self.poll_once()
                    self.check_scheduled_report()
                    if pruned_day != datetime.now().date():
                        self.store.prune()
                        pruned_day = datetime.now().date()
            except AuthRequired as e:
                self.connected = False
                self.status = "Autorisation nécessaire"
                self.error = str(e)
            except FreeboxError as e:
                self.connected = False
                self.status = "Freebox injoignable"
                self.error = str(e)
            except Exception as e:  # ne jamais tuer la surveillance
                self.error = f"Erreur inattendue : {e}"
            for fn in list(self.listeners):
                try:
                    fn()
                except Exception:
                    pass
            self._wake.wait(max(10, int(self.store.config.get("interval", 20))))
            self._wake.clear()

    def connect(self):
        if not self.store.config.get("app_token"):
            self.status = "Autorisation nécessaire"
            return
        self.api.app_token = self.store.config["app_token"]
        self.api.discover()
        self.api.login()
        self.connected = True
        self.error = None
        name = self.api.box_info.get("box_model_name") or self.api.box_info.get("device_name") or "Freebox"
        self.status = f"Connecté à {name}"

    # ================================================================ autorisation
    def begin_authorization(self) -> int:
        self.api.discover()
        token, track = self.api.request_authorization()
        self.store.set("app_token", token)
        return track

    def authorization_status(self, track: int) -> str:
        return self.api.authorization_status(track)

    # ================================================================ relevé
    def _try(self, path, default=None, right=None):
        try:
            return self.api.get(path)
        except PermissionMissing:
            if right:
                self.missing_rights.add(right)
            return default
        except AuthRequired:
            raise
        except FreeboxError as e:
            if e.code == "unreachable":
                raise
            return default

    def collect(self) -> dict:
        now = datetime.now()
        snap = {"ts": now.isoformat(timespec="seconds"), "ok": {}, "stations": {}, "repeaters": {}}

        sysinfo = self._try("/system/", {}) or {}
        snap["uptime"] = sysinfo.get("uptime_val")
        snap["firmware"] = sysinfo.get("firmware_version")
        snap["model"] = (sysinfo.get("model_info") or {}).get("pretty_name") or self.api.box_info.get("box_model_name")

        conn = self._try("/connection/", {}) or {}
        snap["internet"] = conn.get("state")
        snap["media"] = conn.get("media")
        ftth = self._try("/connection/ftth/", None) if conn.get("media") == "ftth" else None
        if isinstance(ftth, dict):
            snap["fibre_signal"] = ftth.get("sfp_has_signal")
            pwr = ftth.get("sfp_pwr_rx")
            snap["fibre_rx_dbm"] = round(pwr / 100, 2) if isinstance(pwr, (int, float)) else None

        hosts = {}
        for h in self._try("/lan/browser/pub/", [], right="explorer") or []:
            mac = norm_mac((h.get("l2ident") or {}).get("id"))
            if mac:
                hosts[mac] = h
        snap["ok"]["hosts"] = bool(hosts)

        def host_name(mac, fallback=None):
            alias = self.store.config.get("aliases", {}).get(mac)
            if alias:
                return alias
            h = hosts.get(mac) or {}
            return h.get("primary_name") or fallback or mac

        # --- répéteurs Free
        reps = self._try("/repeater/", None, right="settings")
        snap["ok"]["repeater"] = isinstance(reps, list)
        rep_names = {}
        for r in reps or []:
            name = r.get("name") or r.get("model") or f"Répéteur {r.get('id')}"
            snap["repeaters"][str(r.get("id"))] = {
                "name": name, "status": r.get("status"), "connection": r.get("connection"),
                "mac": norm_mac(r.get("main_mac")),
            }
            for key in (r.get("id"), r.get("main_mac"), r.get("uid")):
                if key is not None:
                    rep_names[str(key).upper()] = name

        # --- appareils Wi-Fi : navigateur réseau de la Freebox (Freebox Server et répéteurs)
        if hosts:
            snap["ok"]["wifi"] = True
            for mac, h in hosts.items():
                ap = h.get("access_point") or {}
                if ap.get("connectivity_type") != "wifi" or h.get("active") is False:
                    continue
                wi = ap.get("wifi_information") or {}
                if ap.get("type") == "repeater":
                    borne = (rep_names.get(str(ap.get("uid", "")).upper())
                             or rep_names.get(norm_mac(ap.get("mac"))) or "Répéteur")
                else:
                    borne = "Freebox"
                snap["stations"][mac] = {"name": host_name(mac), "borne": borne, "bande": band_label(wi.get("band")),
                                         "signal": wi.get("signal"), "sess": wi.get("sess_duration")}
        else:
            # repli si le navigateur réseau est refusé : bornes de la Freebox Server uniquement
            aps = self._try("/wifi/ap/", None, right="settings")
            snap["ok"]["wifi"] = isinstance(aps, list)
            for ap in aps or []:
                band = band_label((ap.get("config") or {}).get("band"))
                sts = self._try(f"/wifi/ap/{ap.get('id')}/stations/", None, right="settings")
                if sts is None:
                    snap["ok"]["wifi"] = False
                    continue
                for st in sts:
                    mac = norm_mac(st.get("mac"))
                    if not mac or (st.get("state") and st.get("state") != "authenticated"):
                        continue
                    hname = (st.get("host") or {}).get("primary_name") or st.get("hostname")
                    snap["stations"][mac] = {"name": host_name(mac, hname), "borne": "Freebox", "bande": band,
                                             "signal": st.get("signal"), "sess": st.get("conn_duration")}

        # --- lien du Freebox Player (port Ethernet de la box)
        ports = self._try("/switch/status/", None, right="settings")
        snap["player"] = None
        if isinstance(ports, list) and ports:
            port = self._find_player_port(ports, hosts)
            if port:
                stats = self._try(f"/switch/port/{port['id']}/stats/", {}) or {}
                snap["player"] = {
                    "port": port["id"], "link": port.get("link"), "speed": port.get("speed"),
                    "duplex": port.get("duplex"),
                    "fcs": stats.get("rx_fcs_packets"), "rx_err": stats.get("rx_err_packets"),
                }
        return snap

    def _find_player_port(self, ports, hosts):
        wanted = self.store.config.get("player_port")
        if wanted is not None:
            return next((p for p in ports if str(p.get("id")) == str(wanted)), None)
        for p in ports:
            for m in p.get("mac_list") or []:
                name = (m.get("hostname") or "") + " " + ((hosts.get(norm_mac(m.get("mac"))) or {}).get("primary_name") or "")
                vendor = (hosts.get(norm_mac(m.get("mac"))) or {}).get("vendor_name") or ""
                if "player" in name.lower() or ("freebox" in vendor.lower() and "server" not in name.lower()):
                    return p
        return None

    # ================================================================ comparaison
    def _drop_frozen(self, cur: dict):
        """Un appareil encore listé mais dont la session radio n'avance plus est en réalité déconnecté."""
        prev_st = (self.prev or {}).get("stations", {})
        for mac, st in list(cur["stations"].items()):
            p = prev_st.get(mac) or self._frozen_ref.get(mac)
            sess = st.get("sess")
            if sess is not None and p is not None and p.get("sess") == sess:
                self._frozen[mac] = self._frozen.get(mac, 0) + 1
                self._frozen_ref.setdefault(mac, dict(st))
            else:
                self._frozen.pop(mac, None)
                self._frozen_ref.pop(mac, None)
            if self._frozen.get(mac, 0) >= FROZEN_POLLS:
                del cur["stations"][mac]

    def poll_once(self):
        cur = self.collect()
        self._drop_frozen(cur)
        self.process(self.prev, cur)
        self.prev = cur
        self.last = cur
        pl = cur.get("player") or {}
        rep = ", ".join(f"{v['name']}={v['status']}" for v in cur["repeaters"].values())
        self.store.add_measure({
            "ts": cur["ts"], "wifi_stations": len(cur["stations"]), "repeteur": rep,
            "internet": cur.get("internet"), "fibre_rx_dbm": cur.get("fibre_rx_dbm"),
            "player_lien": f"{pl.get('link')} {pl.get('speed') or ''}".strip() if pl else "",
            "player_erreurs": (pl.get("fcs") or 0) + (pl.get("rx_err") or 0) if pl else "",
        })
        self.status = f"Connecté à {cur.get('model') or 'la Freebox'} — dernier relevé {datetime.now():%H:%M:%S}"
        return cur

    def _ev(self, ts, typ, **kw):
        return self.store.add_event({"ts": ts, "type": typ, **kw})

    def process(self, prev: dict | None, cur: dict) -> list[dict]:
        evs = []
        ts = cur["ts"]
        if prev is None:
            return evs

        # Freebox redémarrée
        if isinstance(prev.get("uptime"), int) and isinstance(cur.get("uptime"), int) and cur["uptime"] < prev["uptime"]:
            evs.append(self._ev(ts, "BOX_REDEMARRAGE", detail=f"en service depuis {cur['uptime']} s"))

        # Internet / fibre
        if prev.get("internet") and cur.get("internet") and prev["internet"] != cur["internet"]:
            typ = "INTERNET_RETABLI" if cur["internet"] == "up" else "INTERNET_COUPE"
            evs.append(self._ev(ts, typ, detail=f"{prev['internet']} → {cur['internet']}"))
        if prev.get("fibre_signal") is not None and cur.get("fibre_signal") is not None \
                and prev["fibre_signal"] != cur["fibre_signal"]:
            evs.append(self._ev(ts, "FIBRE", detail="signal optique " + ("retrouvé" if cur["fibre_signal"] else "perdu"),
                                rx_dbm=cur.get("fibre_rx_dbm")))

        # Répéteurs
        for rid, r in prev.get("repeaters", {}).items():
            c = cur.get("repeaters", {}).get(rid)
            was_ok = r.get("status") == "running"
            now_ok = bool(c) and c.get("status") == "running"
            if cur["ok"].get("repeater") and was_ok and not now_ok:
                evs.append(self._ev(ts, "REPETEUR_HORS_LIGNE", borne=r["name"],
                                    detail=f"état : {c.get('status') if c else 'disparu'}"))
            elif cur["ok"].get("repeater") and not was_ok and now_ok:
                evs.append(self._ev(ts, "REPETEUR_RETABLI", borne=r["name"]))

        # Appareils Wi-Fi
        def comparable(_st):
            return prev["ok"].get("wifi") and cur["ok"].get("wifi")

        prev_st, cur_st = prev.get("stations", {}), cur["stations"]
        lost_by_ap: dict[tuple, list] = {}
        for mac, st in prev_st.items():
            if mac in cur_st:
                c = cur_st[mac]
                ps, cs = st.get("sess"), c.get("sess")
                if isinstance(ps, (int, float)) and isinstance(cs, (int, float)) and cs + 5 < ps:
                    # la session radio a redémarré entre deux relevés : coupure courte puis réassociation
                    evs.append(self._ev(ts, "WIFI_COUPURE_BREVE", mac=mac, appareil=c["name"], borne=c["borne"],
                                        bande=c["bande"], signal=st.get("signal"),
                                        sentinelle=mac in self.store.config.get("sentinels", []),
                                        detail=f"réassocié il y a {int(cs)} s (session précédente : {int(ps)} s)"))
                if (c["borne"], c["bande"]) != (st["borne"], st["bande"]):
                    evs.append(self._ev(ts, "WIFI_CHANGEMENT_BORNE", mac=mac, appareil=c["name"],
                                        borne=c["borne"], bande=c["bande"],
                                        detail=f"{st['borne']} {st['bande']} → {c['borne']} {c['bande']}"))
                continue
            if not comparable(st):
                cur_st[mac] = st   # source indisponible ce coup-ci : on garde l'état connu
                continue
            self.absent[mac] = {"since": ts, **st}
            evs.append(self._ev(ts, "WIFI_DECONNEXION", mac=mac, appareil=st["name"], borne=st["borne"],
                                bande=st["bande"], signal=st.get("signal"),
                                sentinelle=mac in self.store.config.get("sentinels", [])))
            lost_by_ap.setdefault((st["borne"], st["bande"]), []).append(st["name"])
        for (borne, bande), names in lost_by_ap.items():
            if len(names) >= COLLECTIVE_MIN:
                evs.append(self._ev(ts, "WIFI_DECROCHAGE_COLLECTIF", borne=borne, bande=bande, nombre=len(names),
                                    detail=", ".join(sorted(names))))
        for mac, c in cur_st.items():
            if mac in prev_st:
                continue
            gone = self.absent.pop(mac, None)
            if gone:
                absence = int((datetime.fromisoformat(ts) - datetime.fromisoformat(gone["since"])).total_seconds())
                evs.append(self._ev(ts, "WIFI_RECONNEXION", mac=mac, appareil=c["name"], borne=c["borne"],
                                    bande=c["bande"], absence_s=absence,
                                    sentinelle=mac in self.store.config.get("sentinels", [])))

        # Lien du Player
        p, c = prev.get("player"), cur.get("player")
        if p and c and p.get("port") == c.get("port"):
            if p.get("link") == "up" and c.get("link") != "up":
                evs.append(self._ev(ts, "TV_LIEN_COUPE", port=c["port"]))
            elif p.get("link") != "up" and c.get("link") == "up":
                evs.append(self._ev(ts, "TV_LIEN_RETABLI", port=c["port"], detail=f"{c.get('speed')} {c.get('duplex')}"))
            elif c.get("link") == "up" and (p.get("speed"), p.get("duplex")) != (c.get("speed"), c.get("duplex")):
                evs.append(self._ev(ts, "TV_LIEN_VITESSE", port=c["port"],
                                    detail=f"{p.get('speed')} {p.get('duplex')} → {c.get('speed')} {c.get('duplex')}"))
            delta = 0
            for k in ("fcs", "rx_err"):
                if isinstance(p.get(k), int) and isinstance(c.get(k), int) and c[k] >= p[k]:
                    delta += c[k] - p[k]
            if delta > 0:
                evs.append(self._ev(ts, "TV_ERREURS", port=c["port"], nombre=delta,
                                    detail=f"{delta} trame(s) corrompue(s) depuis le relevé précédent"))
        return evs

    # ================================================================ rapports automatiques
    def last_scheduled(self, now: datetime | None = None) -> datetime:
        from .schedule import last_occurrence
        return last_occurrence(now or datetime.now(), self.store.config)

    def check_scheduled_report(self, now: datetime | None = None):
        from .schedule import previous_occurrence
        now = now or datetime.now()
        cfg = self.store.config
        due = self.last_scheduled(now)
        last = cfg.get("last_auto_report")
        if not last:
            # première utilisation : le premier rapport sera fait à la prochaine échéance
            self.store.set("last_auto_report", due.isoformat(timespec="minutes"))
            return None
        if last >= due.isoformat(timespec="minutes"):
            return None
        if not (self.store.events()[:1] or self.store.measures()[:1]):
            return None
        from .report import generate
        start = previous_occurrence(due, cfg)
        paths = generate(self.store, start=start, end=now, box=self.box_summary(),
                         freq=cfg.get("report_freq", "hebdomadaire"))
        self.store.set("last_auto_report", due.isoformat(timespec="minutes"))
        paths["mail"] = None
        if cfg.get("email_auto"):
            paths["mail"] = self.mail_report(paths)
        if self.report_callback:
            self.report_callback(paths)
        return paths

    check_weekly_report = check_scheduled_report   # compatibilité

    def mail_report(self, paths: dict) -> str:
        """Envoie le PDF par e-mail ; renvoie un message d'état (jamais d'exception)."""
        from . import mailer
        try:
            subject, body = mailer.report_mail(paths)
            to = mailer.send(self.store.config, mailer.get_password(self.store), subject, body, [paths["pdf"]])
            msg = "envoyé à " + ", ".join(to)
        except Exception as e:
            msg = f"échec de l'envoi : {e}"
        self.store.add_event({"type": "RAPPORT_ENVOYE" if msg.startswith("envoyé") else "RAPPORT_NON_ENVOYE",
                              "detail": f"{paths['pdf'].name} {msg}"})
        return msg

    def box_summary(self) -> dict:
        s = self.last or {}
        return {"model": s.get("model") or self.api.box_info.get("box_model_name"),
                "firmware": s.get("firmware"), "media": s.get("media"),
                "repeaters": [v["name"] for v in (s.get("repeaters") or {}).values()]}
