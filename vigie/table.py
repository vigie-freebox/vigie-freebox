"""Tableau tkinter avec tri par colonne (triangle noir ▲/▼ sur chaque colonne, plus grand sur la colonne triée) et filtres déroulants."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

TOUS = "(tous)"


class FilterTable:
    """cols : liste de (clé, titre, largeur, genre)
         genre « liste »  : filtre déroulant des valeurs présentes ;
         genre « jour »   : filtre déroulant par jour (début de la valeur jusqu'au premier espace double) ;
         genre « texte »  : champ « contient » ;
         genre « nombre » : tri numérique + filtre déroulant.
    Lignes : dicts {"values": tuple, "tag": str, "iid": str|None, "sort": tuple (clés de tri, facultatif)}."""

    def __init__(self, parent, cols, height=10, default_sort=None, descending=True):
        self.cols = cols
        self.rows: list[dict] = []
        self.sort_col = default_sort if default_sort is not None else None
        self.sort_desc = descending
        self.filters: dict[int, tk.StringVar] = {}
        self.combos: dict[int, ttk.Combobox] = {}

        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True, pady=6)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Filtrer :").pack(side="left", padx=(0, 4))
        for i, (key, title, width, kind) in enumerate(cols):
            if kind is None:
                continue
            ttk.Label(bar, text=title).pack(side="left")
            var = tk.StringVar(value="" if kind == "texte" else TOUS)
            self.filters[i] = var
            if kind == "texte":
                e = ttk.Entry(bar, textvariable=var, width=12)
                e.pack(side="left", padx=(2, 6))
                var.trace_add("write", lambda *a: self._apply())
            else:
                cb = ttk.Combobox(bar, textvariable=var, state="readonly",
                                  width=max(7, min(12, width // 12)), values=[TOUS])
                cb.pack(side="left", padx=(2, 6))
                cb.bind("<<ComboboxSelected>>", lambda e: self._apply())
                self.combos[i] = cb
        ttk.Button(bar, text="Effacer", command=self.reset).pack(side="left")
        self.count = ttk.Label(bar, text="", foreground="#5a6478")
        self.count.pack(side="right")

        wrap = ttk.Frame(self.frame)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=[c[0] for c in cols], show="headings", height=height)
        for i, (key, title, width, kind) in enumerate(cols):
            self.tree.heading(key, text=title, command=lambda i=i: self.sort_by(i))
            self.tree.column(key, width=width, anchor="w", stretch=key in ("detail", "name"))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("alert", foreground="#c0392b")
        self.tree.tag_configure("ok", foreground="#1e8449")
        self._headings()

    # ------------------------------------------------------------------ données
    @staticmethod
    def day_of(v: str) -> str:
        parts = str(v).split()
        return " ".join(parts[:2]) if len(parts) >= 2 else str(v)

    def _filter_value(self, i, v):
        return self.day_of(v) if self.cols[i][3] == "jour" else str(v)

    def set_rows(self, rows):
        self.rows = list(rows)
        for i, cb in self.combos.items():
            vals = sorted({self._filter_value(i, r["values"][i]) for r in self.rows if str(r["values"][i]) != ""},
                          key=self._key_for(i))
            if self.cols[i][3] == "jour":
                vals = sorted(vals, key=lambda d: self._day_sort(d), reverse=True)
            cb.configure(values=[TOUS] + vals)
            if self.filters[i].get() not in cb["values"]:
                self.filters[i].set(TOUS)
        self._apply()

    @staticmethod
    def _day_sort(label):
        try:
            dd, mm = label.split()[1].split("/")
            return (int(mm), int(dd))
        except (IndexError, ValueError):
            return (0, 0)

    def _key_for(self, i):
        if self.cols[i][3] == "nombre":
            def k(v):
                try:
                    return (0, float(str(v).split()[0]))
                except (ValueError, IndexError):
                    return (1, 0.0)
            return k
        return lambda v: str(v).lower()

    def _apply(self):
        sel = self.tree.selection()
        out = []
        for r in self.rows:
            ok = True
            for i, var in self.filters.items():
                f = var.get()
                if self.cols[i][3] == "texte":
                    if f and f.lower() not in str(r["values"][i]).lower():
                        ok = False
                        break
                elif f and f != TOUS and self._filter_value(i, r["values"][i]) != f:
                    ok = False
                    break
            if ok:
                out.append(r)
        if self.sort_col is not None:
            i, kf = self.sort_col, self._key_for(self.sort_col)
            out.sort(key=lambda r: r["sort"][i] if r.get("sort") else kf(r["values"][i]), reverse=self.sort_desc)
        self.tree.delete(*self.tree.get_children())
        for r in out:
            kw = {"values": r["values"], "tags": (r.get("tag") or "",)}
            if r.get("iid"):
                kw["iid"] = r["iid"]
            self.tree.insert("", "end", **kw)
        keep = [s for s in sel if self.tree.exists(s)]
        if keep:
            self.tree.selection_set(keep)
        self.count.configure(text=f"{len(out)}/{len(self.rows)}")

    # ------------------------------------------------------------------ tri
    def sort_by(self, i):
        if self.sort_col == i:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = i, False
        self._headings()
        self._apply()

    def _triangle(self, up: bool, h: int = 6):
        """Triangle plein noir (image, rendu identique sous Windows et macOS)."""
        w = 2 * h - 1
        img = tk.PhotoImage(master=self.tree, width=w, height=h)
        for y in range(h):
            row = y if up else h - 1 - y          # largeur croissante vers le bas si ▲
            x0, x1 = (w // 2) - row, (w // 2) + row
            img.put("#000000", to=(x0, y, x1 + 1, y + 1))
        return img

    def _headings(self):
        if not hasattr(self, "_img_up"):
            self._img_up, self._img_down = self._triangle(True), self._triangle(False)
            self._img_idle = self._triangle(True, 4)   # colonnes non triées : petit ▲
        for i, (key, title, width, kind) in enumerate(self.cols):
            if i == self.sort_col:
                img = self._img_down if self.sort_desc else self._img_up
                self.tree.heading(key, text=title + " ", image=img)
            else:
                self.tree.heading(key, text=title + " ", image=self._img_idle)

    def reset(self):
        for i, var in self.filters.items():
            var.set("" if self.cols[i][3] == "texte" else TOUS)
        self._apply()
