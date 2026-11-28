"""Interface graphique (tkinter) — fonctionne à l'identique sous Windows et macOS."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from . import APP_NAME, __version__, autostart, mailer
from .api import FreeboxAPI
from .monitor import Monitor
from .report import JOURS, LABELS, analyse, fmt_duration, generate
from .schedule import FREQUENCES, last_occurrence, next_occurrence
from .store import DEFAULT_INTRO, Store, reports_dir
from .table import FilterTable
from . import mailconf

BLEU = "#1f4fbf"
ROUGE = "#c0392b"
VERT = "#1e8449"
MARINE = "#09203f"
GRIS = "#5a6478"
FILTRES = {"Tous": None, "Wi-Fi": ("WIFI_",), "Répéteur": ("REPETEUR_",), "TV / Player": ("TV_",),
           "Box / Internet": ("BOX_", "INTERNET_", "FIBRE")}
GITHUB_URL = "https://github.com/"
ESPACE_ABONNE_URL = "https://subscribe.free.fr/login/"
MESSAGERIE_FREE_URL = "https://monassistance.free.fr/messagerie"
MEDIATEUR_URL = "https://www.mediation-telecom.org/"
PERIODES = {"24 dernières heures": 1, "7 derniers jours": 7, "15 derniers jours": 15, "30 derniers jours": 30}


def open_path(path):
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal(path):
    """Ouvre le dossier du fichier en le sélectionnant (pour le glisser dans un formulaire web)."""
    path = str(path)
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        open_path(os.path.dirname(path))


class App(tk.Tk):
    def __init__(self, start_minimised: bool = False):
        super().__init__()
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1000x700")
        self.minsize(820, 540)
        self.store = Store()
        cfg = self.store.config
        self.monitor = Monitor(self.store, FreeboxAPI(cfg["freebox_url"], cfg.get("app_token")),
                               report_callback=self._on_auto_report)
        self._dirty = threading.Event()
        self._new_report = None
        self.monitor.listeners.append(self._dirty.set)
        self._track = None

        self._style()
        self._set_icon()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.monitor.start()
        self.after(800, self._tick)
        if start_minimised:
            self.after(500, self.iconify)

    # ================================================================== mise en page
    def _set_icon(self):
        from pathlib import Path
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        try:
            self._icon = tk.PhotoImage(file=str(base / "assets" / "icon.png")).subsample(16, 16)
            self.iconphoto(True, self._icon)
        except tk.TclError:
            pass

    def _style(self):
        s = ttk.Style(self)
        if "clam" in s.theme_names() and sys.platform != "darwin":
            s.theme_use("clam")
        s.configure("Title.TLabel", font=("TkDefaultFont", 16, "bold"))
        s.configure("Big.TLabel", font=("TkDefaultFont", 18, "bold"))
        s.configure("Muted.TLabel", foreground=GRIS)
        s.configure("Card.TFrame", relief="solid", borderwidth=1)
        s.configure("Accent.TButton", font=("TkDefaultFont", 11, "bold"))
        s.configure("Treeview", rowheight=24)

    def _build(self):
        top = tk.Frame(self, bg=MARINE)
        top.pack(fill="x")
        from pathlib import Path
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        try:
            self._logo = tk.PhotoImage(file=str(base / "assets" / "logo_56.png"))
            tk.Label(top, image=self._logo, bg=MARINE, bd=0).pack(side="left", padx=(12, 8), pady=6)
        except tk.TclError:
            tk.Label(top, text=APP_NAME, bg=MARINE, fg="white",
                     font=("TkDefaultFont", 16, "bold")).pack(side="left", padx=14, pady=10)
        self.lbl_status = tk.Label(top, text="Démarrage…", bg=MARINE, fg="#c9d4ea")
        self.lbl_status.pack(side="right", padx=14)

        self.banner = tk.Frame(self, bg="#fff4d6")
        self.banner_lbl = tk.Label(self.banner, bg="#fff4d6", anchor="w", justify="left", wraplength=760)
        self.banner_lbl.pack(side="left", fill="x", expand=True, padx=12, pady=6)
        self.banner_btn = ttk.Button(self.banner, text="Ouvrir")
        self.banner_btn.pack(side="right", padx=10, pady=4)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._tab_home()
        self._tab_devices()
        self._tab_journal()
        self._tab_reports()
        self._tab_email()
        self._tab_free()
        self._tab_settings()

    def _show_banner(self, text, button=None, command=None, color="#fff4d6"):
        self.banner.configure(bg=color)
        self.banner_lbl.configure(text=text, bg=color)
        if button:
            self.banner_btn.configure(text=button, command=command)
            self.banner_btn.pack(side="right", padx=10, pady=4)
        else:
            self.banner_btn.pack_forget()
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", before=self.nb, padx=10, pady=(0, 8))

    def _hide_banner(self):
        self.banner.pack_forget()

    # ------------------------------------------------------------------ Accueil
    def _tab_home(self):
        f = ttk.Frame(self.nb, padding=14)
        self.nb.add(f, text="Accueil")

        self.auth_box = ttk.Frame(f)
        ttk.Label(self.auth_box, text="Première utilisation : autoriser l'application sur votre Freebox",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.auth_box, justify="left", wraplength=820, text=(
            "1. Vérifiez que cet ordinateur est connecté au réseau de votre Freebox (Wi-Fi ou câble).\n"
            "2. Cliquez sur « Autoriser ». Une demande s'affiche sur l'écran de la Freebox Server "
            "(ou sur l'application Freebox Connect pour les modèles sans écran).\n"
            "3. Validez la demande avec la flèche ► puis OK sur la Freebox (vous avez environ 1 minute).\n\n"
            "L'application ne lit que des informations (aucun réglage n'est modifié). "
            "Toutes les données restent sur votre ordinateur.")).pack(anchor="w", pady=10)
        row = ttk.Frame(self.auth_box)
        row.pack(anchor="w")
        self.btn_auth = ttk.Button(row, text="Autoriser", style="Accent.TButton", command=self._start_auth)
        self.btn_auth.pack(side="left")
        self.lbl_auth = ttk.Label(row, text="", style="Muted.TLabel")
        self.lbl_auth.pack(side="left", padx=12)

        self.dash = ttk.Frame(f)
        cards = ttk.Frame(self.dash)
        cards.pack(fill="x")
        self.cards = {}
        for i, (key, title) in enumerate([("internet", "Internet"), ("wifi", "Appareils Wi-Fi"),
                                          ("repeater", "Répéteur"), ("player", "Lien du Player TV"),
                                          ("week", "Incidents (7 jours)")]):
            c = ttk.Frame(cards, style="Card.TFrame", padding=10)
            c.grid(row=0, column=i, sticky="nsew", padx=4)
            cards.columnconfigure(i, weight=1)
            ttk.Label(c, text=title, style="Muted.TLabel").pack(anchor="w")
            v = ttk.Label(c, text="…", style="Big.TLabel")
            v.pack(anchor="w")
            d = ttk.Label(c, text="", style="Muted.TLabel", wraplength=170)
            d.pack(anchor="w")
            self.cards[key] = (v, d)
        ttk.Label(self.dash, text="Derniers événements", font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(16, 4))
        self.t_last = FilterTable(self.dash, [("ts", "Date et heure", 150, "jour"), ("type", "Événement", 200, "liste"), ("detail", "Détail", 520, "texte")], height=10, default_sort=0)
        self.tv_last = self.t_last.tree

    # ------------------------------------------------------------------ Appareils
    def _tab_devices(self):
        f = ttk.Frame(self.nb, padding=14)
        self.nb.add(f, text="Appareils Wi-Fi")
        ttk.Label(f, wraplength=900, justify="left", style="Muted.TLabel", text=(
            "Cochez comme « sentinelles » les appareils qui ne se mettent jamais en veille (caméras, prises, "
            "imprimantes, box TV…) : leurs déconnexions sont la preuve la plus solide d'un problème Wi-Fi. "
            "Les téléphones et ordinateurs se déconnectent normalement quand ils dorment.")).pack(anchor="w")
        self.t_dev = FilterTable(f, [("sent", "Sentinelle", 100, "liste"), ("name", "Appareil", 210, "texte"),
                                     ("borne", "Borne", 150, "liste"), ("band", "Bande", 80, "liste"),
                                     ("signal", "Signal", 80, None), ("mac", "Adresse MAC", 150, None),
                                     ("decos", "Déco. 7 j", 80, "nombre")], height=14, default_sort=0)
        self.tv_dev = self.t_dev.tree
        self.tv_dev.bind("<Double-1>", lambda e: self._toggle_sentinel())
        b = ttk.Frame(f)
        b.pack(anchor="w", pady=6)
        ttk.Button(b, text="Sentinelle oui / non", command=self._toggle_sentinel).pack(side="left")
        ttk.Button(b, text="Renommer…", command=self._rename).pack(side="left", padx=6)

    # ------------------------------------------------------------------ Journal
    def _tab_journal(self):
        f = ttk.Frame(self.nb, padding=14)
        self.nb.add(f, text="Journal")
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Label(bar, text="Période :").pack(side="left")
        self.filter = tk.StringVar(value="Tous")
        self.days = tk.StringVar(value="7 jours")
        cb2 = ttk.Combobox(bar, textvariable=self.days, values=["24 heures", "7 jours", "30 jours"], state="readonly", width=10)
        cb2.pack(side="left", padx=6)
        cb2.bind("<<ComboboxSelected>>", lambda e: self._refresh_journal())
        ttk.Button(bar, text="Actualiser", command=self._refresh_journal).pack(side="left", padx=6)
        self.t_journal = FilterTable(f, [("ts", "Date et heure", 150, "jour"), ("type", "Événement", 200, "liste"), ("detail", "Détail", 560, "texte")], height=18, default_sort=0)
        self.tv_journal = self.t_journal.tree

    # ------------------------------------------------------------------ Rapports
    def _tab_reports(self):
        outer = ttk.Frame(self.nb, padding=14)
        self.nb.add(outer, text="Rapports")
        cfg = self.store.config

        box = ttk.LabelFrame(outer, text="Rapport automatique", padding=10)
        box.pack(fill="x")
        ttk.Label(box, text="Fréquence").grid(row=0, column=0, sticky="w")
        self.var_freq = tk.StringVar(value=FREQUENCES.get(cfg.get("report_freq", "hebdomadaire")))
        cbf = ttk.Combobox(box, textvariable=self.var_freq, values=list(FREQUENCES.values()), state="readonly", width=36)
        cbf.grid(row=0, column=1, columnspan=3, sticky="w", padx=4)
        cbf.bind("<<ComboboxSelected>>", lambda e: self._freq_widgets())
        self.lbl_day = ttk.Label(box, text="Jour")
        self.lbl_day.grid(row=1, column=0, sticky="w", pady=4)
        self.var_day = tk.StringVar(value=JOURS[int(cfg.get("report_day", 0))])
        self.cb_day = ttk.Combobox(box, textvariable=self.var_day, values=JOURS, state="readonly", width=11)
        self.cb_day.grid(row=1, column=1, sticky="w", padx=4)
        self.lbl_day2 = ttk.Label(box, text="et")
        self.lbl_day2.grid(row=1, column=2)
        self.var_day2 = tk.StringVar(value=JOURS[int(cfg.get("report_day2", 3))])
        self.cb_day2 = ttk.Combobox(box, textvariable=self.var_day2, values=JOURS, state="readonly", width=11)
        self.cb_day2.grid(row=1, column=3, sticky="w", padx=4)
        ttk.Label(box, text="Heure").grid(row=2, column=0, sticky="w")
        self.var_time = tk.StringVar(value=cfg.get("report_time", "07:30"))
        ttk.Entry(box, textvariable=self.var_time, width=6).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(box, text="(si l'ordinateur était éteint, le rapport est fait au démarrage suivant)",
                  style="Muted.TLabel").grid(row=2, column=2, columnspan=4, sticky="w")
        self.var_mask = tk.BooleanVar(value=cfg.get("mask_mac", True))
        self.var_names = tk.BooleanVar(value=cfg.get("show_names", True))
        ttk.Checkbutton(box, text="Masquer la fin des adresses MAC", variable=self.var_mask).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(box, text="Afficher le nom des appareils (sinon « Appareil 1, 2… »)",
                        variable=self.var_names).grid(row=3, column=3, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(box, text="Message d'introduction (en tête de chaque rapport, e-mail et courrier) :").grid(
            row=4, column=0, columnspan=6, sticky="w", pady=(8, 2))
        self.txt_intro = tk.Text(box, height=3, wrap="word", font=("TkDefaultFont", 10))
        self.txt_intro.grid(row=5, column=0, columnspan=6, sticky="we")
        self.txt_intro.insert("1.0", cfg.get("intro_text") or DEFAULT_INTRO)
        box.columnconfigure(5, weight=1)
        row = ttk.Frame(box)
        row.grid(row=6, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(row, text="Enregistrer", command=self._save_report_settings).pack(side="left")
        ttk.Button(row, text="Texte d'origine", command=lambda: (self.txt_intro.delete("1.0", "end"),
                                                                 self.txt_intro.insert("1.0", DEFAULT_INTRO))).pack(side="left", padx=6)
        self.lbl_next = ttk.Label(row, text="", style="Muted.TLabel")
        self.lbl_next.pack(side="left", padx=10)
        self._freq_widgets()

        now = ttk.Frame(outer)
        now.pack(fill="x", pady=(12, 4))
        ttk.Label(now, text="Rapport à la demande sur les").pack(side="left")
        self.var_periode = tk.StringVar(value="7 derniers jours")
        ttk.Combobox(now, textvariable=self.var_periode, values=list(PERIODES), state="readonly", width=18).pack(side="left", padx=4)
        ttk.Button(now, text="Générer maintenant", style="Accent.TButton", command=self._report_now).pack(side="left", padx=4)

        act = ttk.Frame(outer)
        act.pack(side="bottom", anchor="w", pady=(6, 0))
        ttk.Label(outer, text="Rapports enregistrés (double-clic pour ouvrir le PDF)",
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(8, 2))
        self.lst_reports = tk.Listbox(outer, height=4)
        self.lst_reports.pack(fill="both", expand=True)
        self.lst_reports.bind("<Double-1>", self._open_selected_report)
        ttk.Button(act, text="Télécharger le PDF…", command=self._save_pdf_as).pack(side="left")
        ttk.Button(act, text="Envoyer par e-mail", command=self._mail_selected).pack(side="left", padx=6)
        ttk.Button(act, text="Préparer le courrier pour Free", command=lambda: self._letter(self._selected_report())).pack(side="left")
        ttk.Button(act, text="Ouvrir le dossier", command=lambda: open_path(reports_dir())).pack(side="left", padx=6)
        self._refresh_reports()

    def _freq_widgets(self):
        freq = self._freq_key()
        one = freq in ("hebdomadaire", "bihebdomadaire")
        for w in (self.lbl_day, self.cb_day):
            w.grid() if one else w.grid_remove()
        for w in (self.lbl_day2, self.cb_day2):
            w.grid() if freq == "bihebdomadaire" else w.grid_remove()

    def _freq_key(self):
        return next((k for k, v in FREQUENCES.items() if v == self.var_freq.get()), "hebdomadaire")

    # ------------------------------------------------------------------ E-mail
    def _tab_email(self):
        f = ttk.Frame(self.nb, padding=(14, 8))
        self.nb.add(f, text="E-mail")
        cfg = self.store.config
        ttk.Label(f, wraplength=920, justify="left", text=(
            "Recevez chaque rapport en pièce jointe (PDF). L'envoi se fait depuis VOTRE adresse e-mail, comme si "
            "vous l'envoyiez vous-même. En général, il suffit de saisir votre adresse et votre mot de passe : "
            "les réglages techniques sont trouvés automatiquement.")).pack(anchor="w")
        self.mail_vars = {}
        HELP = 470

        def section(title):
            lf = ttk.LabelFrame(f, text=title, padding=(10, 4))
            lf.pack(fill="x", pady=(8, 0))
            lf.columnconfigure(2, weight=1)
            return lf

        def field(g, r, label, key, help_text="", width=36, show=None, value=None):
            ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar(value=str(cfg.get(key, "") if value is None else value))
            e = ttk.Entry(g, textvariable=v, width=width, show=show)
            e.grid(row=r, column=1, sticky="w", padx=8)
            if help_text:
                ttk.Label(g, text=help_text, style="Muted.TLabel", wraplength=HELP,
                          justify="left").grid(row=r, column=2, sticky="w")
            self.mail_vars[key] = v
            return e

        g1 = section("① Votre adresse e-mail (l'expéditeur)")
        e_from = field(g1, 0, "Adresse e-mail", "smtp_from",
                       "L'adresse avec laquelle vous envoyez vos e-mails (ex. : jean.dupont@free.fr).")
        e_from.bind("<FocusOut>", lambda e: self._autodetect(quiet=True))
        e_from.bind("<Return>", lambda e: self._autodetect())
        field(g1, 1, "Mot de passe", "_password",
              "Le mot de passe de cette boîte e-mail. Gmail, Yahoo, iCloud et Outlook exigent un « mot de passe "
              "d'application » (voir le lien ci-dessous). Il est rangé dans le trousseau sécurisé de l'ordinateur.",
              show="•", value=mailer.get_password(self.store))
        bar = ttk.Frame(g1)
        bar.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Button(bar, text="Trouver les réglages automatiquement", command=self._autodetect).pack(side="left")
        ttk.Button(bar, text="Importer depuis Thunderbird…", command=self._import_thunderbird).pack(side="left", padx=8)
        self.btn_apppw = ttk.Button(bar, text="Créer un mot de passe d'application ↗", command=self._open_apppw)
        self._apppw_url = None
        self.lbl_detect = ttk.Label(g1, text="", wraplength=900, justify="left")
        self.lbl_detect.grid(row=3, column=0, columnspan=3, sticky="w")

        g2 = section("② À qui envoyer les rapports")
        field(g2, 0, "Destinataire(s)", "email_to",
              "Votre propre adresse le plus souvent. Plusieurs adresses possibles, séparées par des virgules.", 44)

        g3 = section("③ Réglages techniques (remplis automatiquement — à ne modifier qu'en cas de besoin)")
        ttk.Label(g3, text="Messagerie").grid(row=0, column=0, sticky="w", pady=2)
        self.var_preset = tk.StringVar(value="Autre")
        cb = ttk.Combobox(g3, textvariable=self.var_preset, values=list(mailer.PRESETS), state="readonly", width=34)
        cb.grid(row=0, column=1, sticky="w", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset())
        ttk.Label(g3, text="Choisir ici remplit le serveur, le port et la sécurité.", style="Muted.TLabel",
                  wraplength=HELP).grid(row=0, column=2, sticky="w")
        field(g3, 1, "Identifiant de connexion", "smtp_user",
              "Presque toujours votre adresse e-mail complète.")
        field(g3, 2, "Serveur d'envoi (SMTP)", "smtp_host", "Ex. : smtp.free.fr, smtp.gmail.com, smtp.orange.fr.")
        field(g3, 3, "Port", "smtp_port", "465 avec la sécurité « ssl », 587 avec « starttls ».", 8)
        ttk.Label(g3, text="Sécurité").grid(row=4, column=0, sticky="w", pady=2)
        self.var_sec = tk.StringVar(value=cfg.get("smtp_security", "ssl"))
        ttk.Combobox(g3, textvariable=self.var_sec, values=["ssl", "starttls", "aucune"], state="readonly",
                     width=10).grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(g3, text="Chiffrement de la connexion : « ssl » ou « starttls », jamais « aucune » sauf cas "
                           "particulier.", style="Muted.TLabel", wraplength=HELP).grid(row=4, column=2, sticky="w")

        self.var_email_auto = tk.BooleanVar(value=cfg.get("email_auto", False))
        ttk.Checkbutton(f, text="Envoyer automatiquement chaque rapport programmé par e-mail (PDF en pièce jointe)",
                        variable=self.var_email_auto).pack(anchor="w", pady=(8, 0))
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=6)
        ttk.Button(row, text="Enregistrer", command=self._save_email).pack(side="left")
        ttk.Button(row, text="Envoyer un e-mail de test", command=self._test_email).pack(side="left", padx=8)
        self.lbl_mail = ttk.Label(f, text="", wraplength=900, justify="left")
        self.lbl_mail.pack(anchor="w")

    def _show_detect(self, res, origin=""):
        v = self.mail_vars
        v["smtp_host"].set(res["smtp_host"])
        v["smtp_port"].set(str(res["smtp_port"]))
        v["smtp_user"].set(res["smtp_user"])
        self.var_sec.set(res["smtp_security"])
        self.var_preset.set(next((k for k, p in mailer.PRESETS.items() if p[0] == res["smtp_host"]), "Autre"))
        if not v["email_to"].get().strip() and v["smtp_from"].get().strip():
            v["email_to"].set(v["smtp_from"].get().strip())
        self.lbl_detect.configure(foreground=VERT, text=(
            f"✔ {origin or res['provider']} : {res['smtp_host']}, port {res['smtp_port']} ({res['smtp_security']}). "
            + (res.get("note") or "")))
        self._apppw_url = res.get("app_password_url")
        if self._apppw_url:
            self.btn_apppw.pack(side="left")
        else:
            self.btn_apppw.pack_forget()

    def _autodetect(self, quiet=False):
        addr = self.mail_vars["smtp_from"].get().strip()
        if not addr:
            if not quiet:
                self.lbl_detect.configure(foreground=ROUGE, text="Saisissez d'abord votre adresse e-mail.")
            return
        if quiet and self.mail_vars["smtp_host"].get().strip() and getattr(self, "_detected_for", None) in (None, addr):
            return   # réglages déjà présents : ne rien écraser en quittant le champ
        self._detected_for = addr
        res = mailconf.from_table(addr)
        if res:
            return self._show_detect(res)
        if mailconf._domain(addr) is None:
            self.lbl_detect.configure(foreground=ROUGE, text="Cette adresse e-mail ne semble pas valide.")
            return
        self.lbl_detect.configure(foreground=GRIS, text="Recherche des réglages sur Internet…")

        def work():
            r = mailconf.from_internet(addr)
            self.after(0, lambda: self._show_detect(r) if r else self.lbl_detect.configure(
                foreground=ROUGE, text="Réglages introuvables automatiquement pour ce domaine : choisissez votre "
                                       "messagerie dans la liste ③ ou demandez le « serveur SMTP » à votre "
                                       "fournisseur d'e-mail."))
        threading.Thread(target=work, daemon=True).start()

    def _import_thunderbird(self):
        accs = mailconf.thunderbird_accounts()
        if not accs:
            messagebox.showinfo(APP_NAME, "Aucun compte Thunderbird trouvé sur cet ordinateur.\n\n"
                                          "Les réglages d'Outlook, de Mail (Mac) ou du navigateur ne sont pas "
                                          "lisibles par l'application : utilisez « Trouver les réglages "
                                          "automatiquement ».")
            return
        acc = accs[0]
        if len(accs) > 1:
            win = tk.Toplevel(self)
            win.title("Comptes Thunderbird")
            win.transient(self)
            ttk.Label(win, text="Quel compte utiliser pour envoyer les rapports ?", padding=10).pack(anchor="w")
            lb = tk.Listbox(win, width=60, height=min(8, len(accs)))
            for a in accs:
                lb.insert("end", f"{a['address']}  —  {a['smtp_host']}")
            lb.selection_set(0)
            lb.pack(padx=10)
            choice = {}
            ttk.Button(win, text="Utiliser ce compte",
                       command=lambda: (choice.update(i=lb.curselection()[0] if lb.curselection() else 0),
                                        win.destroy())).pack(pady=10)
            win.grab_set()
            self.wait_window(win)
            if "i" not in choice:
                return
            acc = accs[choice["i"]]
        self.mail_vars["smtp_from"].set(acc["address"])
        self._detected_for = acc["address"]
        self._show_detect(acc, "Repris de Thunderbird")
        table = mailconf.from_table(acc["address"])
        if table and table.get("app_password_url"):
            self._apppw_url = table["app_password_url"]
            self.btn_apppw.pack(side="left")

    def _open_apppw(self):
        if self._apppw_url:
            import webbrowser
            webbrowser.open(self._apppw_url)

    # ------------------------------------------------------------------ Réclamation Free
    def _tab_free(self):
        f = ttk.Frame(self.nb, padding=14)
        self.nb.add(f, text="Réclamation Free")
        cfg = self.store.config
        ttk.Label(f, wraplength=900, justify="left", text=(
            "Free ne propose pas d'adresse e-mail pour son service client. Deux voies écrites : le courrier "
            "(de préférence recommandé avec accusé de réception) ou la messagerie « Mon Assistance » de votre "
            "Espace Abonné. L'application prépare la réclamation et le rapport PDF pour les deux.")).pack(anchor="w")
        ttk.Label(f, wraplength=900, justify="left", style="Muted.TLabel", text=(
            "Étapes : 1) Service Réclamation  ›  2) sans réponse satisfaisante sous un mois : Service National "
            "Consommateur  ›  3) sans réponse satisfaisante sous un mois : Médiateur des communications électroniques "
            "(gratuit, dans l'année qui suit la première réclamation écrite).")).pack(anchor="w", pady=(6, 0))
        g = ttk.LabelFrame(f, text="Mes coordonnées (pour le courrier)", padding=10)
        g.pack(fill="x", pady=10)
        self.free_vars = {}
        for r, (label, key) in enumerate([("Nom et prénom", "abonne_nom"), ("Identifiant Freebox (fbx…)", "abonne_id"),
                                          ("Numéro de ligne Free", "abonne_ligne")]):
            ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=cfg.get(key, ""))
            ttk.Entry(g, textvariable=v, width=40).grid(row=r, column=1, sticky="w", padx=8)
            self.free_vars[key] = v
        ttk.Label(g, text="Adresse postale").grid(row=0, column=2, sticky="nw", padx=(20, 0))
        self.txt_addr = tk.Text(g, height=4, width=26, font=("TkDefaultFont", 10))
        self.txt_addr.grid(row=0, column=3, rowspan=3, sticky="w", padx=8)
        self.txt_addr.insert("1.0", cfg.get("abonne_adresse", ""))
        ttk.Label(g, text="Destinataire").grid(row=3, column=0, sticky="w", pady=3)
        self.var_service = tk.StringVar(value=cfg.get("free_service", "Service Réclamation"))
        ttk.Combobox(g, textvariable=self.var_service, values=["Service Réclamation", "Service National Consommateur"],
                     state="readonly", width=30).grid(row=3, column=1, sticky="w", padx=8)
        ttk.Label(g, text="Free – 75371 Paris Cedex 08", style="Muted.TLabel").grid(row=3, column=2, columnspan=2, sticky="w", padx=(20, 0))
        ttk.Button(g, text="Enregistrer", command=self._save_free).grid(row=4, column=0, sticky="w", pady=6)

        row = ttk.Frame(f)
        row.pack(anchor="w", pady=4)
        ttk.Label(row, text="Incidents des").pack(side="left")
        self.var_free_periode = tk.StringVar(value="30 derniers jours")
        ttk.Combobox(row, textvariable=self.var_free_periode, values=list(PERIODES), state="readonly",
                     width=18).pack(side="left", padx=4)
        ttk.Button(row, text="Préparer le courrier recommandé (PDF)", style="Accent.TButton",
                   command=lambda: self._letter(None)).pack(side="left", padx=4)
        msg = ttk.LabelFrame(f, text="Messagerie « Mon Assistance » de Free (sans courrier)", padding=10)
        msg.pack(fill="x", pady=8)
        ttk.Label(msg, wraplength=860, justify="left", text=(
            "1. Le bouton ci-dessous prépare le message (copié dans le presse-papiers), crée le PDF du rapport et "
            "ouvre la messagerie Free dans votre navigateur ainsi que le dossier contenant le PDF.\n"
            "2. Connectez-vous à votre Espace Abonné si Free le demande (identifiant Freebox + mot de passe).\n"
            "3. Dans la conversation, cliquez « Répondre », collez le texte (Ctrl+V / Cmd+V), puis « Importer un "
            "document » et choisissez le PDF (ou glissez-le), et validez.")).pack(anchor="w")
        row2 = ttk.Frame(msg)
        row2.pack(anchor="w", pady=(8, 0))
        ttk.Button(row2, text="Préparer l'envoi dans la messagerie Free", style="Accent.TButton",
                   command=self._send_to_free_messagerie).pack(side="left")
        ttk.Button(row2, text="Site du Médiateur des communications électroniques",
                   command=lambda: webbrowser.open(MEDIATEUR_URL)).pack(side="left", padx=8)
        self.lbl_free = ttk.Label(f, text="", wraplength=900, justify="left", style="Muted.TLabel")
        self.lbl_free.pack(anchor="w", pady=6)

    # ------------------------------------------------------------------ Paramètres
    def _tab_settings(self):
        f = ttk.Frame(self.nb, padding=14)
        self.nb.add(f, text="Paramètres")
        cfg = self.store.config
        g = ttk.Frame(f)
        g.pack(anchor="w")
        ttk.Label(g, text="Adresse de la Freebox").grid(row=0, column=0, sticky="w", pady=4)
        self.var_url = tk.StringVar(value=cfg.get("freebox_url"))
        ttk.Entry(g, textvariable=self.var_url, width=36).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(g, text="Relevé toutes les (secondes)").grid(row=1, column=0, sticky="w", pady=4)
        self.var_interval = tk.IntVar(value=int(cfg.get("interval", 20)))
        ttk.Spinbox(g, from_=10, to=300, increment=5, textvariable=self.var_interval, width=6).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(g, text="Port Ethernet du Player TV").grid(row=2, column=0, sticky="w", pady=4)
        self.var_port = tk.StringVar(value="Automatique" if cfg.get("player_port") is None else str(cfg["player_port"]))
        ttk.Combobox(g, textvariable=self.var_port, values=["Automatique", "1", "2", "3", "4"], width=12,
                     state="readonly").grid(row=2, column=1, sticky="w", padx=8)
        self.var_auto = tk.BooleanVar(value=autostart.is_enabled())
        cb = ttk.Checkbutton(g, text="Lancer automatiquement à l'ouverture de session (recommandé : la surveillance "
                                     "ne fonctionne que quand l'application est ouverte)", variable=self.var_auto)
        cb.grid(row=3, column=0, columnspan=2, sticky="w", pady=8)
        if not autostart.supported():
            cb.state(["disabled"])
        ttk.Button(g, text="Enregistrer", command=self._save_settings).grid(row=4, column=0, sticky="w", pady=6)

        vmbox = ttk.LabelFrame(f, text="Surveillance permanente (sans laisser l'ordinateur allumé)", padding=10)
        vmbox.pack(fill="x", pady=(14, 0))
        ttk.Label(vmbox, wraplength=860, justify="left", text=(
            "Sur les Freebox qui proposent des machines virtuelles (Delta, premières Ultra), Vigie peut s'installer "
            "dans la Freebox elle-même et surveiller 24 h/24. L'assistant vérifie votre box puis fait tout "
            "automatiquement.")).pack(anchor="w")
        rowvm = ttk.Frame(vmbox)
        rowvm.pack(anchor="w", pady=(6, 0))
        ttk.Button(rowvm, text="Installer la surveillance dans la Freebox…", style="Accent.TButton",
                   command=self._vm_wizard).pack(side="left")
        self.btn_vm_open = ttk.Button(rowvm, text="Ouvrir la surveillance de la Freebox",
                                      command=lambda: webbrowser.open(self.store.config.get("vm_url") or ""))
        if self.store.config.get("vm_url"):
            self.btn_vm_open.pack(side="left", padx=8)
        self.var_local = tk.BooleanVar(value=not self.store.config.get("local_monitoring", True))
        ttk.Checkbutton(vmbox, text="Ne plus surveiller depuis cet ordinateur (la Freebox s'en charge)",
                        variable=self.var_local, command=self._toggle_local).pack(anchor="w", pady=(6, 0))

        ttk.Separator(f).pack(fill="x", pady=14)
        row = ttk.Frame(f)
        row.pack(anchor="w")
        ttk.Button(row, text="Ouvrir le dossier des données", command=lambda: open_path(self.store.root)).pack(side="left")
        ttk.Button(row, text="Réautoriser l'application sur la Freebox", command=self._reset_auth).pack(side="left", padx=8)
        self.lbl_rights = ttk.Label(f, text="", foreground=ROUGE, wraplength=880, justify="left")
        self.lbl_rights.pack(anchor="w", pady=10)
        ttk.Label(f, style="Muted.TLabel", wraplength=880, justify="left", text=(
            f"{APP_NAME} {__version__} — application communautaire gratuite et open source (licence MIT), "
            "non officielle et sans lien avec Free / Iliad. Elle utilise uniquement l'API locale de la Freebox "
            "et ne transmet aucune donnée à l'extérieur.")).pack(anchor="w", side="bottom")

    # ================================================================== outils
    def _tree(self, parent, cols, height=10):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True, pady=6)
        tv = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="headings", height=height)
        for key, title, w in cols:
            tv.heading(key, text=title)
            tv.column(key, width=w, anchor="w", stretch=key in ("detail", "name"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("alert", foreground=ROUGE)
        tv.tag_configure("ok", foreground=VERT)
        return tv

    def _ev_dict(self, e):
        vals, tag = self._ev_row(e)
        return {"values": vals, "tag": tag, "sort": (e["ts"], vals[1].lower(), vals[2].lower())}

    @staticmethod
    def _ev_row(e):
        typ = e["type"]
        if typ in ("WIFI_DECONNEXION", "WIFI_RECONNEXION", "WIFI_CHANGEMENT_BORNE", "WIFI_COUPURE_BREVE"):
            parts = [e.get("appareil") or "?", f"{e.get('borne')} {e.get('bande')}"]
            if e.get("absence_s") is not None:
                parts.append(f"absent {fmt_duration(e['absence_s'])}")
            if e.get("signal") is not None:
                parts.append(f"signal {e['signal']} dBm")
            if typ == "WIFI_COUPURE_BREVE" and e.get("detail"):
                parts.append(e["detail"])
            if e.get("sentinelle"):
                parts.append("sentinelle")
            if typ == "WIFI_CHANGEMENT_BORNE":
                parts = [e.get("appareil") or "?", e.get("detail") or ""]
            detail = " — ".join(parts)
        else:
            detail = " ".join(x for x in [e.get("borne"), e.get("detail")] if x)
        ts = datetime.fromisoformat(e["ts"])
        tag = "alert" if typ in ("TV_LIEN_COUPE", "INTERNET_COUPE", "REPETEUR_HORS_LIGNE", "BOX_REDEMARRAGE",
                                 "WIFI_DECROCHAGE_COLLECTIF") or (typ in ("WIFI_DECONNEXION", "WIFI_COUPURE_BREVE") and e.get("sentinelle")) \
            else ("ok" if typ.endswith("RETABLI") or typ == "WIFI_RECONNEXION" else "")
        return (f"{JOURS[ts.weekday()][:3]}. {ts:%d/%m %H:%M:%S}", LABELS.get(typ, typ), detail), tag

    # ================================================================== rafraîchissement
    def _tick(self):
        try:
            self._refresh_status()
            if self._dirty.is_set():
                self._dirty.clear()
                self._refresh_dashboard()
                self._refresh_devices()
                self._refresh_journal()
            if self._new_report:
                paths, self._new_report = self._new_report, None
                extra = f" — e-mail : {paths['mail']}" if paths.get("mail") else ""
                self._show_banner(f"Nouveau rapport : {paths['pdf'].name}{extra}", "Ouvrir",
                                  lambda p=paths["pdf"]: (open_path(p), self._hide_banner()), "#e3f4e8")
                self._refresh_reports()
        finally:
            self.after(1000, self._tick)

    def _refresh_status(self):
        m = self.monitor
        has_token = bool(self.store.config.get("app_token"))
        self.lbl_status.configure(text=m.status + (f" — {m.error}" if m.error and not m.connected else ""),
                                  foreground="#7ee2a8" if m.connected else ("#ff9c94" if m.error else "#c9d4ea"))
        if m.connected or (has_token and self._track is None and m.status != "Autorisation nécessaire"):
            self.auth_box.pack_forget()
            if not self.dash.winfo_ismapped():
                self.dash.pack(fill="both", expand=True)
        else:
            self.dash.pack_forget()
            if not self.auth_box.winfo_ismapped():
                self.auth_box.pack(fill="both", expand=True)
        if m.missing_rights:
            self.lbl_rights.configure(text=(
                "Certaines informations sont refusées par la Freebox (droit(s) manquant(s) : "
                + ", ".join(sorted(m.missing_rights)) + "). Ouvrez Freebox OS (http://mafreebox.freebox.fr) › "
                "Paramètres de la Freebox › Gestion des accès › onglet Applications › « Vigie Freebox », puis cochez "
                "« Modification des réglages de la Freebox » et « Accès au gestionnaire de fichiers / explorateur réseau ». "
                "L'application ne modifie aucun réglage : ce droit est seulement exigé pour lire l'état du Wi-Fi."))
            if not self.banner.winfo_ismapped():
                self._show_banner("Droits insuffisants sur la Freebox : voir l'onglet Paramètres.", "Voir",
                                  lambda: (self.nb.select(6), self._hide_banner()))
        else:
            self.lbl_rights.configure(text="")

    def _refresh_dashboard(self):
        s = self.monitor.last or {}
        st = s.get("stations", {})
        inet = s.get("internet")
        self._card("internet", "OK" if inet == "up" else (inet or "?"),
                   (f"Fibre : {s['fibre_rx_dbm']} dBm" if s.get("fibre_rx_dbm") is not None else s.get("media") or ""),
                   VERT if inet == "up" else ROUGE)
        bornes = {}
        for v in st.values():
            bornes[f"{v['borne']} {v['bande']}"] = bornes.get(f"{v['borne']} {v['bande']}", 0) + 1
        self._card("wifi", str(len(st)), ", ".join(f"{k} : {n}" for k, n in sorted(bornes.items())))
        reps = s.get("repeaters", {})
        if reps:
            ok = all(r.get("status") == "running" for r in reps.values())
            self._card("repeater", "OK" if ok else "Hors ligne",
                       ", ".join(f"{r['name']} ({r.get('status')})" for r in reps.values()), VERT if ok else ROUGE)
        else:
            self._card("repeater", "–", "aucun répéteur détecté")
        pl = s.get("player")
        if pl:
            up = pl.get("link") == "up"
            self._card("player", "OK" if up else "Coupé",
                       f"port {pl['port']} — {pl.get('speed')} Mb/s {pl.get('duplex') or ''}", VERT if up else ROUGE)
        else:
            self._card("player", "–", "Player non trouvé (voir Paramètres)")
        evs = self.store.events(datetime.now() - timedelta(days=7))
        serious = [e for e in evs if e["type"] not in ("WIFI_RECONNEXION", "WIFI_CHANGEMENT_BORNE")
                   and not e["type"].endswith("RETABLI") and not e["type"].startswith("RAPPORT_")]
        self._card("week", str(len(serious)), "déconnexions, coupures et erreurs")
        self.t_last.set_rows([self._ev_dict(e) for e in evs[-200:]])

    def _card(self, key, value, detail, color=None):
        v, d = self.cards[key]
        v.configure(text=value, foreground=color or "")
        d.configure(text=detail)

    def _refresh_devices(self):
        s = self.monitor.last or {}
        sent = set(self.store.config.get("sentinels", []))
        decos = {}
        for e in self.store.events(datetime.now() - timedelta(days=7)):
            if e["type"] in ("WIFI_DECONNEXION", "WIFI_COUPURE_BREVE") and e.get("mac"):
                decos[e["mac"]] = decos.get(e["mac"], 0) + 1
        rows = dict(s.get("stations", {}))
        for mac in sent:   # les sentinelles déconnectées restent visibles
            rows.setdefault(mac, {"name": self.store.config.get("aliases", {}).get(mac, mac),
                                  "borne": "DÉCONNECTÉ", "bande": "", "signal": None})
        out = []
        for mac, v in rows.items():
            sig = v.get("signal")
            vals = ("✔" if mac in sent else "", v["name"], v["borne"], v["bande"],
                    f"{sig} dBm" if sig is not None else "", mac, decos.get(mac, 0))
            out.append({"values": vals, "iid": mac, "tag": "alert" if v["borne"] == "DÉCONNECTÉ" else "",
                        "sort": (mac in sent, str(v["name"]).lower(), str(v["borne"]), str(v["bande"]),
                                 sig if isinstance(sig, (int, float)) else -999, mac, decos.get(mac, 0))})
        self.t_dev.set_rows(out)

    def _refresh_journal(self):
        days = {"24 heures": 1, "7 jours": 7, "30 jours": 30}[self.days.get()]
        pref = FILTRES[self.filter.get()]
        evs = self.store.events(datetime.now() - timedelta(days=days))
        self.t_journal.set_rows([self._ev_dict(e) for e in evs if not (pref and not e["type"].startswith(pref))])

    def _refresh_reports(self):
        self.lst_reports.delete(0, "end")
        self._report_files = sorted(reports_dir().glob("rapport_freebox_*.pdf"), reverse=True)
        for p in self._report_files[:80]:
            self.lst_reports.insert("end", p.name)
        if self._report_files:
            self.lst_reports.selection_set(0)
        nxt = next_occurrence(datetime.now(), self.store.config)
        self.lbl_next.configure(text=f"Prochain rapport automatique : {JOURS[nxt.weekday()]} {nxt:%d/%m à %H:%M}")

    # ================================================================== actions
    def _start_auth(self):
        self.btn_auth.state(["disabled"])
        self.lbl_auth.configure(text="Connexion à la Freebox…")

        def work():
            try:
                self.monitor.api.base_url = self.store.config["freebox_url"].rstrip("/")
                self._track = self.monitor.begin_authorization()
                self.after(0, lambda: self.lbl_auth.configure(
                    text="➜ Validez la demande sur l'écran de la Freebox Server (flèche ► puis OK)…"))
                self.after(2000, self._poll_auth)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: (self.lbl_auth.configure(text=f"Échec : {msg}"), self.btn_auth.state(["!disabled"])))
        threading.Thread(target=work, daemon=True).start()

    def _poll_auth(self):
        track = self._track

        def work():
            try:
                st = self.monitor.authorization_status(track)
            except Exception as e:
                st = f"erreur ({e})"
            self.after(0, lambda: self._auth_result(st))
        threading.Thread(target=work, daemon=True).start()

    def _auth_result(self, st):
        if st == "pending":
            self.after(2000, self._poll_auth)
            return
        self.btn_auth.state(["!disabled"])
        self._track = None
        if st == "granted":
            self.lbl_auth.configure(text="Autorisation accordée ✔ — la surveillance démarre.")
            self.monitor.connected = False
            self.monitor.status = "Connexion…"
            self.monitor.wake()
            self._dirty.set()
        else:
            self.store.set("app_token", None)
            texte = {"timeout": "délai dépassé, recommencez", "denied": "demande refusée sur la Freebox"}.get(st, st)
            self.lbl_auth.configure(text=f"Autorisation non accordée : {texte}.")

    def _reset_auth(self):
        if messagebox.askyesno(APP_NAME, "Oublier l'autorisation actuelle et en demander une nouvelle à la Freebox ?"):
            self.store.set("app_token", None)
            self.monitor.connected = False
            self.monitor.status = "Autorisation nécessaire"
            self.nb.select(0)

    def _toggle_sentinel(self):
        sel = self.tv_dev.selection()
        if not sel:
            return
        sent = set(self.store.config.get("sentinels", []))
        for mac in sel:
            sent.symmetric_difference_update({mac})
        self.store.set("sentinels", sorted(sent))
        self._refresh_devices()

    def _rename(self):
        sel = self.tv_dev.selection()
        if not sel:
            return
        mac = sel[0]
        cur = self.tv_dev.item(mac, "values")[1]
        name = simpledialog.askstring(APP_NAME, f"Nom de l'appareil {mac} :", initialvalue=cur, parent=self)
        if name is None:
            return
        aliases = dict(self.store.config.get("aliases", {}))
        if name.strip():
            aliases[mac] = name.strip()
        else:
            aliases.pop(mac, None)
        self.store.set("aliases", aliases)
        if self.monitor.last and mac in self.monitor.last.get("stations", {}):
            self.monitor.last["stations"][mac]["name"] = name.strip() or mac
        self._refresh_devices()

    def _report_now(self):
        days = PERIODES[self.var_periode.get()]

        def work():
            try:
                paths = generate(self.store, days=days, box=self.monitor.box_summary())
                self.after(0, lambda: (self._refresh_reports(), open_path(paths["pdf"])))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: messagebox.showerror(APP_NAME, f"Rapport impossible : {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def _selected_report(self):
        i = self.lst_reports.curselection()
        if i:
            return self._report_files[i[0]]
        return self._report_files[0] if self._report_files else None

    def _open_selected_report(self, _e=None):
        p = self._selected_report()
        if p:
            open_path(p)

    def _save_pdf_as(self):
        from tkinter import filedialog
        p = self._selected_report()
        if not p:
            messagebox.showinfo(APP_NAME, "Aucun rapport : cliquez d'abord sur « Générer maintenant ».")
            return
        dest = filedialog.asksaveasfilename(parent=self, title="Enregistrer le rapport PDF", initialfile=p.name,
                                            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                            initialdir=str(Path.home() / "Downloads") if (Path.home() / "Downloads").exists() else None)
        if dest:
            import shutil
            shutil.copyfile(p, dest)
            messagebox.showinfo(APP_NAME, f"Rapport enregistré :\n{dest}")

    def _report_meta(self, pdf: Path) -> dict:
        """Objet et corps d'e-mail d'un rapport déjà enregistré (repris de sa version texte)."""
        intro = self.store.config.get("intro_text") or DEFAULT_INTRO
        periode, faits = "", []
        txt = pdf.with_suffix(".txt")
        if txt.exists():
            lines = txt.read_text(encoding="utf-8").splitlines()
            periode = next((x for x in lines if x.startswith("Période")), "")
            if "FAITS MARQUANTS" in lines:
                k = lines.index("FAITS MARQUANTS") + 1
                while k < len(lines) and lines[k].strip():
                    faits.append(lines[k])
                    k += 1
        subject = "Rapport des incidents Wi-Fi et TV Freebox" + (f" — {periode.split(':', 1)[1].strip()}" if periode else "")
        body = "\n".join([intro, "", periode, "", "Faits marquants :"] + faits +
                          ["", "Le rapport complet est joint au format PDF.", "", "— Envoyé par Vigie Freebox."])
        return {"subject": subject, "body": body}

    def _mail_selected(self):
        p = self._selected_report()
        if not p:
            messagebox.showinfo(APP_NAME, "Aucun rapport à envoyer.")
            return
        if not mailer.recipients(self.store.config) or not self.store.config.get("smtp_host"):
            messagebox.showinfo(APP_NAME, "Renseignez d'abord l'onglet E-mail (destinataire et serveur d'envoi).")
            self.nb.select(4)
            return
        meta = self._report_meta(p)

        def work():
            try:
                to = mailer.send(self.store.config, mailer.get_password(self.store), meta["subject"], meta["body"], [p])
                self.after(0, lambda: messagebox.showinfo(APP_NAME, "Rapport envoyé à " + ", ".join(to)))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: messagebox.showerror(APP_NAME, f"Envoi impossible : {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def _on_auto_report(self, paths):
        self._new_report = paths

    def _save_report_settings(self):
        t = self.var_time.get().strip()
        try:
            hh, mm = [int(x) for x in t.split(":")]
            assert 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            messagebox.showerror(APP_NAME, "Heure invalide : utilisez le format HH:MM (ex. 07:30).")
            return
        cfg = self.store.config
        cfg["report_freq"] = self._freq_key()
        cfg["report_day"] = JOURS.index(self.var_day.get())
        cfg["report_day2"] = JOURS.index(self.var_day2.get())
        if cfg["report_freq"] == "bihebdomadaire" and cfg["report_day2"] == cfg["report_day"]:
            messagebox.showerror(APP_NAME, "Choisissez deux jours différents pour le rythme bihebdomadaire.")
            return
        cfg["report_time"] = f"{hh:02d}:{mm:02d}"
        cfg["mask_mac"] = bool(self.var_mask.get())
        cfg["show_names"] = bool(self.var_names.get())
        cfg["intro_text"] = self.txt_intro.get("1.0", "end").strip() or DEFAULT_INTRO
        # ne pas déclencher immédiatement un rapport pour l'échéance déjà passée
        cfg["last_auto_report"] = last_occurrence(datetime.now(), cfg).isoformat(timespec="minutes")
        self.store.save_config()
        self._refresh_reports()
        messagebox.showinfo(APP_NAME, "Réglages du rapport enregistrés.")

    # ------------------------------------------------------------------ e-mail
    def _collect_email(self):
        cfg = self.store.config
        for k, v in self.mail_vars.items():
            if k != "_password":
                cfg[k] = v.get().strip()
        try:
            cfg["smtp_port"] = int(cfg.get("smtp_port") or 465)
        except ValueError:
            cfg["smtp_port"] = 465
        cfg["smtp_security"] = self.var_sec.get()
        cfg["email_auto"] = bool(self.var_email_auto.get())
        self.store.save_config()
        where = mailer.set_password(self.store, self.mail_vars["_password"].get())
        return where

    def _apply_preset(self):
        host, port, sec = mailer.PRESETS.get(self.var_preset.get(), (None, None, None))
        if host:
            self.mail_vars["smtp_host"].set(host)
            self.mail_vars["smtp_port"].set(str(port))
            self.var_sec.set(sec)

    def _save_email(self):
        where = self._collect_email()
        self.lbl_mail.configure(text="Réglages enregistrés. Mot de passe rangé dans "
                                + ("le trousseau sécurisé du système." if where == "trousseau"
                                   else "la configuration locale de l'application."), foreground=VERT)

    def _test_email(self):
        self._collect_email()
        self.lbl_mail.configure(text="Envoi en cours…", foreground=GRIS)
        cfg = dict(self.store.config)

        def work():
            try:
                to = mailer.send(cfg, mailer.get_password(self.store), f"{APP_NAME} — e-mail de test",
                                 "Si vous lisez ce message, l'envoi des rapports par e-mail fonctionne.")
                self.after(0, lambda: self.lbl_mail.configure(text="E-mail de test envoyé à " + ", ".join(to)
                                                              + ". Vérifiez aussi vos indésirables.", foreground=VERT))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: self.lbl_mail.configure(text=f"Échec : {msg}", foreground=ROUGE))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ réclamation Free
    def _save_free(self, quiet=False):
        cfg = self.store.config
        for k, v in self.free_vars.items():
            cfg[k] = v.get().strip()
        cfg["abonne_adresse"] = self.txt_addr.get("1.0", "end").strip()
        cfg["free_service"] = self.var_service.get()
        self.store.save_config()
        if not quiet:
            self.lbl_free.configure(text="Coordonnées enregistrées.")

    def _letter_analysis(self, report: Path | None):
        """Période du rapport sélectionné, sinon période choisie dans l'onglet Réclamation."""
        end = datetime.now()
        days = PERIODES[self.var_free_periode.get()]
        if report is not None:
            parts = report.stem.split("_")
            try:
                end = datetime.strptime("_".join(parts[2:4]), "%Y-%m-%d_%Hh%M")
                days = {"quotidien": 1, "hebdomadaire": 7, "bihebdomadaire": 4, "bimensuel": 16}.get(
                    parts[4] if len(parts) > 4 else "", days)
            except ValueError:
                pass
        return analyse(self.store, end - timedelta(days=days), end)

    def _letter(self, report: Path | None):
        self._save_free(quiet=True)
        if not self.store.config.get("abonne_nom"):
            messagebox.showinfo(APP_NAME, "Indiquez d'abord vos coordonnées dans l'onglet « Réclamation Free ».")
            self.nb.select(5)
            return
        a = self._letter_analysis(report)

        def work():
            try:
                from .pdf import render_letter
                path = reports_dir() / f"reclamation_free_{datetime.now():%Y-%m-%d_%Hh%M}.pdf"
                render_letter(self.store.config, a, self.monitor.box_summary(), path)
                self.after(0, lambda: (self.lbl_free.configure(
                    text=f"Courrier prêt : {path.name} (dans le dossier des rapports). Imprimez-le et envoyez-le en "
                         "recommandé avec accusé de réception, ou déposez le PDF sur le service de lettre "
                         "recommandée en ligne de La Poste."), open_path(path)))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: messagebox.showerror(APP_NAME, f"Courrier impossible : {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def _send_to_free_messagerie(self):
        self._save_free(quiet=True)
        if not self.store.config.get("abonne_id"):
            messagebox.showinfo(APP_NAME, "Indiquez d'abord votre identifiant Freebox (ci-dessus), puis recommencez.")
            return
        days = PERIODES[self.var_free_periode.get()]

        def work():
            try:
                from .pdf import letter_plain
                res = generate(self.store, days=days, box=self.monitor.box_summary())
                texte = letter_plain(self.store.config, res["analyse"]).replace(
                    "Vous trouverez ci-joint", "Vous trouverez en pièce jointe (PDF)")

                def ui():
                    self.clipboard_clear()
                    self.clipboard_append(texte)
                    num = "".join(ch for ch in self.store.config.get("abonne_id", "") if ch.isdigit())
                    # « id » = partie numérique de l'identifiant Freebox (identifiant hotline) ; Free ajoute
                    # lui-même le jeton de session (idt) après la connexion à l'Espace Abonné.
                    webbrowser.open(f"{MESSAGERIE_FREE_URL}?id={num}" if num else MESSAGERIE_FREE_URL)
                    reveal(res["pdf"])
                    self._refresh_reports()
                    self.lbl_free.configure(text=f"Texte copié. PDF à joindre : {res['pdf'].name} (dossier ouvert). "
                                                 "Collez le texte dans « Répondre », importez le PDF, puis validez.")
                self.after(0, ui)
            except Exception as e:
                msg = str(e)
                self.after(0, lambda: messagebox.showerror(APP_NAME, f"Préparation impossible : {msg}"))
        threading.Thread(target=work, daemon=True).start()

    def _copy_and_open_free(self):
        self._save_free(quiet=True)
        from .pdf import letter_plain
        txt = letter_plain(self.store.config, self._letter_analysis(None))
        self.clipboard_clear()
        self.clipboard_append(txt)
        webbrowser.open(ESPACE_ABONNE_URL)
        self.lbl_free.configure(text="Le texte de la réclamation est copié : collez-le (Ctrl+V / Cmd+V) dans le "
                                     "formulaire de contact de votre Espace Abonné, et joignez le PDF du rapport si le "
                                     "formulaire le permet.")

    def _save_settings(self):
        cfg = self.store.config
        url = self.var_url.get().strip().rstrip("/") or "http://mafreebox.freebox.fr"
        if not url.startswith("http"):
            url = "http://" + url
        changed = url != cfg.get("freebox_url")
        cfg["freebox_url"] = url
        cfg["interval"] = max(10, int(self.var_interval.get() or 20))
        cfg["player_port"] = None if self.var_port.get() == "Automatique" else int(self.var_port.get())
        self.store.save_config()
        if autostart.supported():
            try:
                autostart.set_enabled(bool(self.var_auto.get()))
            except Exception as e:
                messagebox.showwarning(APP_NAME, f"Lancement automatique non modifié : {e}")
        if changed:
            self.monitor.api.base_url = url
            self.monitor.api.api_prefix = None
            self.monitor.connected = False
        self.monitor.wake()
        messagebox.showinfo(APP_NAME, "Paramètres enregistrés.")

    # ------------------------------------------------------------------ machine virtuelle
    def _toggle_local(self):
        off = bool(self.var_local.get())
        if off and not self.store.config.get("vm_url"):
            messagebox.showinfo(APP_NAME, "Installez d'abord la surveillance dans la Freebox.")
            self.var_local.set(False)
            return
        self.store.set("local_monitoring", not off)
        self.monitor.connected = False
        self.monitor.wake()

    def _vm_wizard(self):
        from .vmsetup import VM_MEMORY, VMInstaller, VMSetupError
        w = tk.Toplevel(self)
        w.title("Surveillance permanente dans la Freebox")
        w.geometry("720x520")
        w.transient(self)
        ttk.Label(w, wraplength=680, justify="left", padding=12, text=(
            "L'assistant va :\n"
            "  1. vérifier que votre Freebox accepte les machines virtuelles et qu'il reste de la place ;\n"
            "  2. faire télécharger par la Freebox l'image Debian qu'elle propose pour ses machines virtuelles ;\n"
            f"  3. créer une petite machine virtuelle « vigie-freebox » ({VM_MEMORY} Mo de mémoire, 1 processeur) ;\n"
            "  4. y installer Vigie avec vos réglages actuels (sentinelles, rapports, coordonnées…).\n\n"
            "Vos autres machines virtuelles éventuelles ne sont pas modifiées. Le mot de passe e-mail n'est pas "
            "copié : vous le ressaisirez dans l'interface de la Freebox.")).pack(anchor="w")
        log = tk.Text(w, height=12, wrap="word", font=("TkDefaultFont", 10))
        log.pack(fill="both", expand=True, padx=12)
        btns = ttk.Frame(w, padding=10)
        btns.pack(fill="x")
        b_check = ttk.Button(btns, text="1. Vérifier ma Freebox")
        b_install = ttk.Button(btns, text="2. Installer", style="Accent.TButton", state="disabled")
        b_open = ttk.Button(btns, text="Ouvrir la surveillance")
        b_check.pack(side="left")
        b_install.pack(side="left", padx=8)

        def say(msg):
            self.after(0, lambda: (log.insert("end", msg + "\n"), log.see("end")))

        def check():
            b_check.state(["disabled"])
            say("Vérification…")

            def work():
                inst = VMInstaller(FreeboxAPI(self.store.config["freebox_url"], self.store.config.get("app_token")),
                                   self.store, say)
                r = inst.check()
                say(("✔ " if r["ok"] else "✘ ") + r["message"])
                self.after(0, lambda: (b_check.state(["!disabled"]),
                                       b_install.state(["!disabled"] if r["ok"] else ["disabled"])))
            threading.Thread(target=work, daemon=True).start()

        def install():
            if not messagebox.askyesno(APP_NAME, "Créer la machine virtuelle « vigie-freebox » sur votre Freebox ?",
                                       parent=w):
                return
            b_install.state(["disabled"])
            b_check.state(["disabled"])

            def work():
                inst = VMInstaller(FreeboxAPI(self.store.config["freebox_url"], self.store.config.get("app_token")),
                                   self.store, say)
                try:
                    res = inst.install()
                    say("✔ Terminé." if not res.get("pending") else
                        "La VM tourne ; l'installation se termine encore (quelques minutes).")
                    say(f"Adresse de la surveillance : {res['url']}")

                    def done():
                        b_open.configure(command=lambda: webbrowser.open(res["url"]))
                        b_open.pack(side="left", padx=8)
                        self.btn_vm_open.pack(side="left", padx=8)
                        if messagebox.askyesno(APP_NAME, "La Freebox surveille maintenant en permanence.\n\n"
                                                         "Arrêter la surveillance depuis cet ordinateur ?", parent=w):
                            self.var_local.set(True)
                            self._toggle_local()
                    self.after(0, done)
                except (VMSetupError, Exception) as e:
                    say(f"✘ {e}")
                    self.after(0, lambda: (b_check.state(["!disabled"]),))
            threading.Thread(target=work, daemon=True).start()

        b_check.configure(command=check)
        b_install.configure(command=install)

    def _on_close(self):
        r = messagebox.askyesnocancel(
            APP_NAME, "La surveillance s'arrête quand l'application est fermée.\n\n"
                      "Oui : quitter quand même\nNon : réduire la fenêtre et continuer la surveillance")
        if r is None:
            return
        if r:
            self.monitor.stop()
            self.destroy()
        else:
            self.iconify()


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    app = App(start_minimised="--minimise" in argv)
    app.mainloop()
