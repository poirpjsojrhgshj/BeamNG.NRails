#!/usr/bin/env python3
"""BeamNG.EarthNRails Hub: one window to install, update, start and look after BeamNG.Earth + rails.

Standard library only (tkinter): it runs with any Python 3.10+, before the server's .venv exists.

    run_hub.bat            (Windows: double-click)        python hub.py   (anywhere)

Tabs: Home (status, install / update, start server, start game), Server (options, live log), Rails (track
generation settings, passed to the server as BNGE_RAIL* environment variables), Cache (where the download cache lives,
its size, its cap, cleaning the game's temp folders), Tools (environment check, mod switch EarthNRails / BeamNG.Earth,
folders). Settings are kept in .beamng_earthnrails.json next to this file (shared with install.py / start.py).
"""
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(1, os.path.join(ROOT, "server"))
import nrails_install as install  # noqa: E402  (upstream's install.py with the fork's names; standard library only)
from nrails import paths    # noqa: E402  (server/nrails/paths.py: standard library only)

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW: no console flashing for the children
PORT = 47613
APP_ID = "284160"
REPO_URL = "https://github.com/"                  # set to the published repository

DEFAULTS = {
    "lang": "fr",
    "server": {"deshadow": "full", "near_visual": "detail", "airports": True, "sea": True, "trees": True,
               "buildings": True, "cache_cap_gb": 20, "extra": ""},
    "rails": {"enabled": True, "profile": "uic60", "trams": True, "crossings": True, "catenary": True, "cant": True,
              "max_grade": 35, "vehicles": ""},
    "cache_dir": "",
}

TEXT = {
    "fr": {
        "home": "Accueil", "server": "Serveur", "rails": "Rails", "cache": "Cache", "tools": "Outils",
        "status": "État", "python": "Python du serveur (.venv)", "packages": "Paquets (numpy, Pillow, duckdb)",
        "native": "Module natif earthfast", "userdir": "Dossier utilisateur BeamNG", "mod": "Mod dans le jeu",
        "cachepath": "Cache de téléchargement", "srv": "Serveur (port 47613)", "game": "BeamNG.drive",
        "install": "Installer / mettre à jour", "start": "Démarrer le serveur", "stop": "Arrêter le serveur",
        "play": "Lancer BeamNG.drive", "refresh": "Actualiser", "running": "en marche", "stopped": "arrêté",
        "ok": "OK", "missing": "manquant", "notfound": "introuvable", "active": "actif", "inactive": "désactivé",
        "notinstalled": "pas installé", "options": "Options du serveur", "log": "Journal",
        "deshadow": "Suppression des ombres (deshadow)", "near": "Rendu proche", "airports": "Aéroports",
        "sea": "Mer", "trees": "Arbres", "buildings": "Bâtiments", "cap": "Taille max du cache (Go, 0 = illimité)",
        "extra": "Arguments en plus pour earthd.py", "save": "Enregistrer",
        "rails_on": "Générer les voies ferrées", "profile": "Profil de rail", "trams": "Voies de tramway (au ras de la rue)",
        "crossings": "Passages à niveau (dalles + rainures 45 mm)",
        "catenary": "Caténaire (poteaux + fils, voies normales et légères)",
        "cant": "Dévers dans les courbes (max 150 mm)",
        "max_grade": "Pente max des voies (‰ : 12,5-25 ligne classique, 35 LGV, 60+ montagne)",
        "vehicles": "Véhicules ferroviaires en plus (noms jbeam, séparés par des virgules)",
        "rails_note": "Écartement 1 435 mm. Les rails se recalculent quand le serveur redémarre. Véhicules ferroviaires "
                      "reconnus (passages à niveau) : TEM2, WLD FS30-2, wagon-citerne, DMM512.",
        "cache_now": "Cache utilisé", "real": "Emplacement réel", "size": "Taille", "free": "Libre sur le disque",
        "compute": "Calculer la taille", "choose": "Choisir un autre dossier…", "reset": "Dossier par défaut",
        "open": "Ouvrir", "purge": "Vider les dossiers temporaires du jeu",
        "purge_q": "Supprimer les sessions temporaires de BeamNG.Earth (dossier temp du jeu et dossier de staging) ?\n"
                   "Le serveur et le jeu doivent être fermés.",
        "purged": "Supprimé : {n} fichiers, {mb:.0f} Mo.", "busy": "Ferme d'abord le serveur et le jeu.",
        "check": "Vérifier l'environnement", "envelope": "Mesurer les trains installés",
        "switch_fork": "Utiliser EarthNRails dans le jeu", "switch_up": "Revenir à BeamNG.Earth d'origine",
        "open_user": "Dossier utilisateur du jeu", "open_root": "Dossier du projet", "open_logs": "Journaux",
        "github": "Page GitHub", "lang": "Langue", "restart_note": "Redémarre le Hub pour changer la langue.",
        "game_running": "Le jeu tourne : ferme-le avant de changer de mod.", "done": "Terminé.",
        "no_venv": "Le serveur n'est pas installé : clique d'abord sur « Installer / mettre à jour ».",
        "srv_already": "Un serveur écoute déjà sur le port 47613.",
        "need_restart": "Paramètres enregistrés. Ils s'appliquent au prochain démarrage du serveur.",
    },
    "en": {
        "home": "Home", "server": "Server", "rails": "Rails", "cache": "Cache", "tools": "Tools",
        "status": "Status", "python": "Server Python (.venv)", "packages": "Packages (numpy, Pillow, duckdb)",
        "native": "Native module earthfast", "userdir": "BeamNG user folder", "mod": "Mod in the game",
        "cachepath": "Download cache", "srv": "Server (port 47613)", "game": "BeamNG.drive",
        "install": "Install / update", "start": "Start server", "stop": "Stop server",
        "play": "Start BeamNG.drive", "refresh": "Refresh", "running": "running", "stopped": "stopped",
        "ok": "OK", "missing": "missing", "notfound": "not found", "active": "active", "inactive": "disabled",
        "notinstalled": "not installed", "options": "Server options", "log": "Log",
        "deshadow": "Shadow removal (deshadow)", "near": "Near rendering", "airports": "Airports",
        "sea": "Sea", "trees": "Trees", "buildings": "Buildings", "cap": "Cache size cap (GB, 0 = no cap)",
        "extra": "Extra earthd.py arguments", "save": "Save",
        "rails_on": "Generate railways", "profile": "Rail profile", "trams": "Tram tracks (flush with the street)",
        "crossings": "Level crossings (slabs + 45 mm flangeways)",
        "catenary": "Overhead line (masts + wires, standard gauge and light rail)",
        "cant": "Cant in curves (150 mm max)",
        "max_grade": "Max track grade (per mille: 12.5-25 classic main line, 35 high speed, 60+ mountain)",
        "vehicles": "More rail vehicles (jbeam names, comma-separated)",
        "rails_note": "Gauge 1,435 mm. Rails are rebuilt when the server restarts. Rail vehicles known to the level "
                      "crossings: TEM2, WLD FS30-2, tanker wagon, DMM512.",
        "cache_now": "Cache in use", "real": "Real location", "size": "Size", "free": "Free on the drive",
        "compute": "Compute size", "choose": "Choose another folder…", "reset": "Default folder",
        "open": "Open", "purge": "Empty the game's temp folders",
        "purge_q": "Delete BeamNG.Earth's temporary sessions (the game's temp folder and the staging folder)?\n"
                   "The server and the game must be closed.",
        "purged": "Deleted: {n} files, {mb:.0f} MB.", "busy": "Close the server and the game first.",
        "check": "Check the environment", "envelope": "Measure the installed trains",
        "switch_fork": "Use EarthNRails in the game", "switch_up": "Back to the original BeamNG.Earth",
        "open_user": "Game user folder", "open_root": "Project folder", "open_logs": "Logs",
        "github": "GitHub page", "lang": "Language", "restart_note": "Restart the Hub to change the language.",
        "game_running": "The game is running: close it before switching mods.", "done": "Done.",
        "no_venv": "The server is not installed: click \"Install / update\" first.",
        "srv_already": "A server is already listening on port 47613.",
        "need_restart": "Settings saved. They apply at the next server start.",
    },
}


# --- helpers (no tkinter) ---------------------------------------------------------------------------------------

def load_settings():
    cfg = install.load_config()
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def save_settings(s):
    cfg = install.load_config()
    cfg.update(s)
    install.write_config(cfg)


def server_env(s):
    """The environment the server runs with: rails settings, the cache folder, unbuffered UTF-8 output."""
    env = dict(os.environ)
    r = s["rails"]
    env["BNGE_RAILS"] = "on" if r.get("enabled", True) else "off"
    env["BNGE_RAIL_PROFILE"] = str(r.get("profile", "uic60"))
    env["BNGE_RAIL_TRAMS"] = "on" if r.get("trams", True) else "off"
    env["BNGE_RAIL_CROSSINGS"] = "on" if r.get("crossings", True) else "off"
    env["BNGE_RAIL_CATENARY"] = "on" if r.get("catenary", True) else "off"
    env["BNGE_RAIL_CANT"] = "on" if r.get("cant", True) else "off"
    env["BNGE_RAIL_MAX_GRADE"] = str(r.get("max_grade", 35))
    if s.get("cache_dir"):
        env[paths.ENV] = s["cache_dir"]
    else:
        env.pop(paths.ENV, None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


VEHICLES_FILE = ("settings", "beamngEarth", "nrails_vehicles.json")     # nrails.lua M.VEHICLES_FILE


def parse_vehicles(text):
    """The jbeam names in a comma / space separated list, once each, in order."""
    out = []
    for name in text.replace(";", ",").replace("\n", ",").split(","):
        name = name.strip()
        if name and name not in out:
            out.append(name)
    return out


def write_vehicle_list(user_dir, names):
    """<user_dir>/settings/beamngEarth/nrails_vehicles.json: {"vehicles": [...]}, the rail vehicles the mod adds to its
    own (nrails.lua loadVehicleList: the level crossings open for them, snapToRail takes them). The path, or None
    without a user folder."""
    if not user_dir:
        return None
    path = os.path.join(user_dir, *VEHICLES_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"vehicles": list(names)}, f, indent=1)
    return path


def server_command(s, user_dir):
    """[python, earthd.py, ...] with the chosen options (only those this server version knows)."""
    import start
    py = install.venv_python()
    help_text = start.server_flags(py)
    sv = s["server"]
    want = [("--deshadow", sv.get("deshadow", "full")), ("--near-visual", sv.get("near_visual", "detail")),
            ("--airports", "on" if sv.get("airports") else "off"), ("--sea", "on" if sv.get("sea") else "off"),
            ("--trees", "on" if sv.get("trees") else "off"), ("--buildings", "on" if sv.get("buildings") else "off"),
            ("--cache-cap", str(sv.get("cache_cap_gb", 20)))]
    # through launcher.py's --server mode: its watch_parent() ends the server (and its workers) with the Hub
    cmd = [py, os.path.join(ROOT, "nrails_launcher.py"), "--server", "--user-dir", user_dir]
    if s.get("cache_dir"):
        cmd += ["--cache-dir", s["cache_dir"]]
    for flag, value in want:
        if start.has_flag(help_text, flag):
            cmd += [flag, value]
    cmd += [a for a in str(sv.get("extra", "")).split() if a]
    return cmd


def port_open(port=PORT):
    """Is a server listening on the port? Tested by binding it, not connecting: a connection showed in the server's
    log as a client that came and went ("client connected / disconnected") at every status refresh."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if IS_WIN and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def listening_pid(port=PORT):
    """Windows: the PID listening on 127.0.0.1:port (netstat -ano), else None."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, errors="replace",
                             creationflags=NO_WINDOW).stdout or ""
    except OSError:
        return None
    for line in out.splitlines():
        parts = line.split()
        # (a listening row's remote address is 0.0.0.0:0; its state word is localised: LISTENING, ÉCOUTE ...)
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[2] == "0.0.0.0:0":
            try:
                return int(parts[4])
            except ValueError:
                pass
    return None


def game_running():
    if not IS_WIN:
        try:
            out = subprocess.run(["pgrep", "-f", "BeamNG.drive"], capture_output=True, text=True).stdout
            return bool(out.strip())
        except OSError:
            return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq BeamNG.drive*", "/NH"], capture_output=True,
                             text=True, errors="replace", creationflags=NO_WINDOW).stdout or ""
        return "BeamNG.drive" in out
    except OSError:
        return False


def dir_size(path, stop=None):
    total = n = 0
    stack = [path]
    while stack:
        if stop is not None and stop.is_set():
            break
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            n += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total, n


def open_path(p):
    if not p or not os.path.exists(p):
        return
    if IS_WIN:
        os.startfile(p)     # noqa: S606
    else:
        subprocess.Popen(["xdg-open", p])


def user_dir_now():
    cfg = install.load_config()
    if cfg.get("user_dir"):
        return cfg["user_dir"]
    found = install.candidate_user_dirs()
    return found[0] if found else None


def temp_folders(user_dir):
    """The game-side temporary folders BeamNG.Earth fills: <user>/temp/beamngEarth and the staging folder beside it."""
    out = []
    if user_dir:
        out.append(os.path.join(user_dir, "temp", "beamngEarth"))
        out.append(os.path.join(os.path.dirname(user_dir), "beamngEarth_staging"))
    return [p for p in out if os.path.isdir(p)]


# --- the window ---------------------------------------------------------------------------------------------------

class Hub(tk.Tk):
    def __init__(self):
        super().__init__()
        self.s = load_settings()
        self.t = TEXT.get(self.s.get("lang", "fr"), TEXT["fr"])
        self.title(f"BeamNG.EarthNRails Hub — {install.version()}")
        self.geometry("980x680")
        self.minsize(820, 560)
        self.q = queue.Queue()
        self.proc = None            # the server we started
        self.busy = None            # a running tool (install, check ...)
        self.size_stop = threading.Event()
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", padding=(14, 8))
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tabs = {}
        for key in ("home", "server", "rails", "cache", "tools"):
            f = ttk.Frame(nb, padding=12)
            nb.add(f, text=self.t[key])
            self.tabs[key] = f
        self._home()
        self._server()
        self._rails()
        self._cache()
        self._tools()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.pump)
        self.after(200, self.refresh)

    # ---- layout ----
    def _home(self):
        f = self.tabs["home"]
        ttk.Label(f, text="BeamNG.Earth + Rails", style="Head.TLabel").pack(anchor="w")
        grid = ttk.Frame(f)
        grid.pack(fill="x", pady=8)
        self.status = {}
        for i, key in enumerate(("python", "packages", "native", "userdir", "mod", "cachepath", "srv", "game")):
            ttk.Label(grid, text=self.t[key] + " :").grid(row=i, column=0, sticky="w", padx=(0, 12), pady=2)
            v = tk.StringVar(value="…")
            ttk.Label(grid, textvariable=v).grid(row=i, column=1, sticky="w")
            self.status[key] = v
        row = ttk.Frame(f)
        row.pack(fill="x", pady=10)
        ttk.Button(row, text=self.t["install"], style="Big.TButton", command=self.do_install).pack(side="left")
        self.btn_start = ttk.Button(row, text=self.t["start"], style="Big.TButton", command=self.toggle_server)
        self.btn_start.pack(side="left", padx=8)
        ttk.Button(row, text=self.t["play"], style="Big.TButton", command=self.start_game).pack(side="left")
        ttk.Button(row, text=self.t["refresh"], command=self.refresh).pack(side="right")
        ttk.Label(f, text=self.t["log"], style="Head.TLabel").pack(anchor="w", pady=(8, 0))
        self.home_log = self._logbox(f)

    def _logbox(self, parent):
        fr = ttk.Frame(parent)
        fr.pack(fill="both", expand=True)
        txt = tk.Text(fr, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        sb = ttk.Scrollbar(fr, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return txt

    def _server(self):
        f = self.tabs["server"]
        sv = self.s["server"]
        ttk.Label(f, text=self.t["options"], style="Head.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        self.v_deshadow = tk.StringVar(value=sv["deshadow"])
        self.v_near = tk.StringVar(value=sv["near_visual"])
        ttk.Label(f, text=self.t["deshadow"]).grid(row=1, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_deshadow, values=("full", "on", "off"), width=10,
                     state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Label(f, text=self.t["near"]).grid(row=2, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_near, values=("detail", "photo"), width=10,
                     state="readonly").grid(row=2, column=1, sticky="w")
        self.v_flags = {}
        for i, key in enumerate(("airports", "sea", "trees", "buildings")):
            v = tk.BooleanVar(value=bool(sv[key]))
            ttk.Checkbutton(f, text=self.t[key], variable=v).grid(row=1 + i // 2, column=2 + i % 2, sticky="w", padx=8)
            self.v_flags[key] = v
        ttk.Label(f, text=self.t["cap"]).grid(row=3, column=0, sticky="w", pady=4)
        self.v_cap = tk.StringVar(value=str(sv["cache_cap_gb"]))
        ttk.Entry(f, textvariable=self.v_cap, width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(f, text=self.t["extra"]).grid(row=4, column=0, sticky="w")
        self.v_extra = tk.StringVar(value=sv["extra"])
        ttk.Entry(f, textvariable=self.v_extra, width=50).grid(row=4, column=1, columnspan=3, sticky="we")
        bar = ttk.Frame(f)
        bar.grid(row=5, column=0, columnspan=4, sticky="w", pady=8)
        ttk.Button(bar, text=self.t["save"], command=self.save_server).pack(side="left")
        self.btn_start2 = ttk.Button(bar, text=self.t["start"], command=self.toggle_server)
        self.btn_start2.pack(side="left", padx=8)
        holder = ttk.Frame(f)
        holder.grid(row=6, column=0, columnspan=4, sticky="nsew")
        f.rowconfigure(6, weight=1)
        f.columnconfigure(3, weight=1)
        self.srv_log = self._logbox(holder)

    def _rails(self):
        f = self.tabs["rails"]
        r = self.s["rails"]
        self.v_rails = tk.BooleanVar(value=bool(r["enabled"]))
        self.v_profile = tk.StringVar(value=r["profile"])
        self.v_trams = tk.BooleanVar(value=bool(r["trams"]))
        self.v_cross = tk.BooleanVar(value=bool(r["crossings"]))
        self.v_cat = tk.BooleanVar(value=bool(r.get("catenary", True)))
        self.v_cant = tk.BooleanVar(value=bool(r.get("cant", True)))
        self.v_grade = tk.StringVar(value=str(r.get("max_grade", 35)))
        self.v_vehicles = tk.StringVar(value=str(r.get("vehicles", "")))
        ttk.Checkbutton(f, text=self.t["rails_on"], variable=self.v_rails).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(f, text=self.t["profile"]).grid(row=1, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_profile, values=("uic60", "uic54", "uic50", "jis60"), width=10,
                     state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(f, text=self.t["trams"], variable=self.v_trams).grid(row=2, column=0, sticky="w", pady=4)
        ttk.Checkbutton(f, text=self.t["crossings"], variable=self.v_cross).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(f, text=self.t["catenary"], variable=self.v_cat).grid(row=4, column=0, sticky="w", pady=4)
        ttk.Checkbutton(f, text=self.t["cant"], variable=self.v_cant).grid(row=5, column=0, sticky="w")
        ttk.Label(f, text=self.t["max_grade"]).grid(row=6, column=0, sticky="w", pady=4)
        ttk.Spinbox(f, from_=5, to=80, increment=2.5, textvariable=self.v_grade, width=6).grid(row=6, column=1,
                                                                                                sticky="w")
        ttk.Label(f, text=self.t["vehicles"]).grid(row=7, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.v_vehicles, width=40).grid(row=7, column=1, columnspan=2, sticky="w")
        ttk.Label(f, text=self.t["rails_note"], wraplength=760, foreground="#555").grid(row=8, column=0, columnspan=3,
                                                                                         sticky="w", pady=12)
        table = ("UIC 60 / 60E1 : H 172 mm, C 72 mm, B 150 mm, t 16.5 mm\n"
                 "UIC 54 / 54E1 : H 159 mm, C 70 mm\nUIC 50 : H 152 mm, C 70 mm\nJIS 60 : H 174 mm, C 65 mm")
        ttk.Label(f, text=table, font=("Consolas", 9)).grid(row=9, column=0, columnspan=3, sticky="w")
        ttk.Button(f, text=self.t["save"], command=self.save_rails).grid(row=10, column=0, sticky="w", pady=10)

    def _cache(self):
        f = self.tabs["cache"]
        self.v_cache = {k: tk.StringVar(value="…") for k in ("cache_now", "real", "size", "free")}
        for i, k in enumerate(("cache_now", "real", "size", "free")):
            ttk.Label(f, text=self.t[k] + " :").grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(f, textvariable=self.v_cache[k]).grid(row=i, column=1, sticky="w")
        bar = ttk.Frame(f)
        bar.grid(row=4, column=0, columnspan=2, sticky="w", pady=10)
        ttk.Button(bar, text=self.t["compute"], command=self.compute_size).pack(side="left")
        ttk.Button(bar, text=self.t["open"], command=lambda: open_path(self.cache_dir())).pack(side="left", padx=6)
        ttk.Button(bar, text=self.t["choose"], command=self.choose_cache).pack(side="left")
        ttk.Button(bar, text=self.t["reset"], command=self.reset_cache).pack(side="left", padx=6)
        ttk.Button(f, text=self.t["purge"], command=self.purge_temp).grid(row=5, column=0, sticky="w")

    def _tools(self):
        f = self.tabs["tools"]
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text=self.t["check"], command=lambda: self.run_tool(["tools/check_env.py"])).pack(side="left")
        ttk.Button(bar, text=self.t["envelope"],
                   command=lambda: self.run_tool(["tools/train_envelope.py"])).pack(side="left", padx=6)
        bar2 = ttk.Frame(f)
        bar2.pack(fill="x", pady=6)
        ttk.Button(bar2, text=self.t["switch_fork"], command=lambda: self.switch_mod(True)).pack(side="left")
        ttk.Button(bar2, text=self.t["switch_up"], command=lambda: self.switch_mod(False)).pack(side="left", padx=6)
        bar3 = ttk.Frame(f)
        bar3.pack(fill="x")
        ttk.Button(bar3, text=self.t["open_user"], command=lambda: open_path(user_dir_now())).pack(side="left")
        ttk.Button(bar3, text=self.t["open_root"], command=lambda: open_path(ROOT)).pack(side="left", padx=6)
        ttk.Button(bar3, text=self.t["open_logs"],
                   command=lambda: open_path(os.path.join(self.cache_dir(), "logs"))).pack(side="left")
        ttk.Button(bar3, text=self.t["github"], command=lambda: webbrowser.open(REPO_URL)).pack(side="left", padx=6)
        lang = ttk.Frame(f)
        lang.pack(fill="x", pady=6)
        ttk.Label(lang, text=self.t["lang"] + " :").pack(side="left")
        self.v_lang = tk.StringVar(value=self.s.get("lang", "fr"))
        cb = ttk.Combobox(lang, textvariable=self.v_lang, values=("fr", "en"), width=5, state="readonly")
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", self.set_lang)
        self.tool_log = self._logbox(f)

    # ---- output ----
    def log(self, box, text):
        self.q.put((box, text))

    def pump(self):
        try:
            for _ in range(400):
                box, text = self.q.get_nowait()
                for b in ([self.home_log, box] if box is not self.home_log and box is self.srv_log else [box]):
                    b.configure(state="normal")
                    b.insert("end", text if text.endswith("\n") else text + "\n")
                    if int(b.index("end-1c").split(".")[0]) > 4000:
                        b.delete("1.0", "1000.0")
                    b.see("end")
                    b.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def stream(self, proc, box, done=None, logfile=None):
        def reader():
            f = None
            if logfile:             # the server's log kept on disk too (Outils > Journaux): to send when asked
                try:
                    os.makedirs(os.path.dirname(logfile), exist_ok=True)
                    f = open(logfile, "w", encoding="utf-8")
                except OSError:
                    f = None
            for line in iter(proc.stdout.readline, ""):
                self.log(box, line.rstrip("\n"))
                if f is not None:
                    f.write(line)
                    f.flush()
            if f is not None:
                f.close()
            proc.wait()
            # (a server the Hub stopped ends with taskkill's code 1: not an error)
            self.log(box, "[" + self.t["stopped"] + "]" if getattr(proc, "hub_stopped", False)
                     else f"[exit {proc.returncode}]")
            if done:
                self.after(0, done)
        threading.Thread(target=reader, daemon=True).start()

    def popen(self, cmd, env=None):
        return subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW, start_new_session=not IS_WIN)

    # ---- status ----
    def cache_dir(self):
        return self.s.get("cache_dir") or paths.default_cache_dir()

    def refresh(self):
        t = self.t
        py = install.venv_python()
        st = self.status
        st["python"].set(f"{t['ok']} — {py}" if os.path.isfile(py) else t["missing"])
        ud = user_dir_now()
        st["userdir"].set(ud or t["notfound"])
        if ud:
            ms = install.mod_states(ud)
            word = lambda a: t["active"] if a is True else t["inactive"] if a is False else t["notinstalled"]  # noqa
            st["mod"].set(f"EarthNRails : {word(ms[install.MOD_NAME])}   |   BeamNG.Earth : "
                          f"{word(ms[install.UPSTREAM_MOD_NAME])}")
        cd = self.cache_dir()
        real = os.path.realpath(cd) if os.path.exists(cd) else cd
        st["cachepath"].set(cd + ("" if real == cd else f"  →  {real}"))
        self.v_cache["cache_now"].set(cd)
        self.v_cache["real"].set(real)
        try:
            self.v_cache["free"].set(f"{shutil.disk_usage(real if os.path.exists(real) else ROOT).free / 2**30:.1f} Go")
        except OSError:
            self.v_cache["free"].set("?")
        up = port_open()
        st["srv"].set(t["running"] if up else t["stopped"])
        label = t["stop"] if (self.proc is not None and self.proc.poll() is None) or up else t["start"]
        self.btn_start.configure(text=label)
        self.btn_start2.configure(text=label)
        st["game"].set(t["running"] if game_running() else t["stopped"])
        if os.path.isfile(py):
            threading.Thread(target=self._check_packages, args=(py,), daemon=True).start()
        else:
            st["packages"].set(t["missing"])
            st["native"].set("—")

    def _check_packages(self, py):
        code = ("import importlib.util as u, sys; sys.path.insert(0, 'server');"
                "print(' '.join(m for m in ('numpy','PIL','duckdb','fsspec') if u.find_spec(m) is None) or 'OK');"
                "import earthfast; print('earthfast', getattr(earthfast, 'VERSION', '?'))")
        try:
            r = subprocess.run([py, "-c", code], cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=60,
                               creationflags=NO_WINDOW)
            lines = (r.stdout or "").splitlines()
            pk = lines[0] if lines else "?"
            nat = lines[1] if len(lines) > 1 else (r.stderr.strip().splitlines() or ["?"])[-1]
        except (OSError, subprocess.TimeoutExpired) as e:
            pk, nat = str(e), "?"
        self.after(0, lambda: (self.status["packages"].set(self.t["ok"] if pk == "OK" else
                                                            f"{self.t['missing']}: {pk}"),
                               self.status["native"].set(nat)))

    # ---- actions ----
    def do_install(self):
        if self.busy is not None and self.busy.poll() is None:
            return
        py = sys.executable
        self.log(self.home_log, "> nrails_install.py --yes")
        self.busy = self.popen([py, "nrails_install.py", "--yes"])
        self.stream(self.busy, self.home_log, done=self.refresh)

    def toggle_server(self):
        # (the buttons rest a few seconds after each click: a second click on "Start" before the label changed stopped
        # the server just started, its log ending in "[exit 1]", the user's first try 2026-10-24)
        for b in (self.btn_start, self.btn_start2):
            b.state(["disabled"])
        self.after(4000, lambda: [b.state(["!disabled"]) for b in (self.btn_start, self.btn_start2)])
        if (self.proc is not None and self.proc.poll() is None) or port_open():
            self.stop_server()
            label = self.t["start"]
        else:
            self.start_server()
            label = self.t["stop"] if self.proc is not None and self.proc.poll() is None else self.t["start"]
        for b in (self.btn_start, self.btn_start2):
            b.configure(text=label)

    def start_server(self):
        if not os.path.isfile(install.venv_python()):
            messagebox.showwarning("Hub", self.t["no_venv"])
            return
        if port_open():
            messagebox.showinfo("Hub", self.t["srv_already"])
            return
        ud = user_dir_now()
        if not ud:
            messagebox.showwarning("Hub", self.t["userdir"] + " : " + self.t["notfound"])
            return
        self.save_server(quiet=True)
        try:
            install.install_mod(ud, True, dry_run=False, quiet=True)    # the game gets this folder's mod
        except (OSError, SystemExit) as e:
            self.log(self.srv_log, f"mod: {e}")
        try:
            cmd = server_command(self.s, ud)
        except SystemExit as e:
            self.log(self.srv_log, f"server: {e}")
            return
        env = server_env(self.s)
        env["BNGEARTH_PARENT"] = str(os.getpid())       # the server ends with the Hub (earthd watch_parent)
        self.log(self.srv_log, "> " + " ".join(cmd))
        self.proc = self.popen(cmd, env)
        self.stream(self.proc, self.srv_log, done=self.refresh,
                    logfile=os.path.join(self.cache_dir(), "logs", "server_hub.log"))
        self.after(3000, self.refresh)

    def stop_server(self):
        p = self.proc
        if p is not None and p.poll() is None:
            p.hub_stopped = True
            if IS_WIN:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                               creationflags=NO_WINDOW)
            else:
                import signal
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    p.terminate()
        elif IS_WIN and port_open():        # a server this Hub did not start (an earlier Hub, run_server.bat)
            pid = listening_pid()
            if pid:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
                self.log(self.srv_log, f"[{self.t['stopped']}: PID {pid}]")
        self.proc = None
        self.after(1500, self.refresh)

    def start_game(self):
        d = None
        if IS_WIN:
            try:
                import launcher
                d = launcher.windows_game_dir()
            except Exception:       # noqa: BLE001
                d = None
        if d and os.path.isfile(os.path.join(d, "BeamNG.drive.exe")):
            subprocess.Popen([os.path.join(d, "BeamNG.drive.exe")], cwd=d)
            self.log(self.home_log, f"> {d}\\BeamNG.drive.exe")
        else:
            webbrowser.open(f"steam://rungameid/{APP_ID}")
            self.log(self.home_log, "> steam://rungameid/" + APP_ID)
        self.after(5000, self.refresh)

    def save_server(self, quiet=False):
        sv = self.s["server"]
        sv["deshadow"] = self.v_deshadow.get()
        sv["near_visual"] = self.v_near.get()
        for k, v in self.v_flags.items():
            sv[k] = bool(v.get())
        try:
            sv["cache_cap_gb"] = max(0.0, float(self.v_cap.get().replace(",", ".")))
        except ValueError:
            pass
        sv["extra"] = self.v_extra.get()
        save_settings(self.s)
        if not quiet:
            messagebox.showinfo("Hub", self.t["need_restart"])

    def save_rails(self):
        try:
            grade = min(max(float(self.v_grade.get().replace(",", ".")), 5.0), 80.0)
        except ValueError:
            grade = 35.0
        names = parse_vehicles(self.v_vehicles.get())
        self.s["rails"] = {"enabled": bool(self.v_rails.get()), "profile": self.v_profile.get(),
                           "trams": bool(self.v_trams.get()), "crossings": bool(self.v_cross.get()),
                           "catenary": bool(self.v_cat.get()), "cant": bool(self.v_cant.get()),
                           "max_grade": grade, "vehicles": ", ".join(names)}
        save_settings(self.s)
        try:
            write_vehicle_list(user_dir_now(), names)
        except OSError as e:
            messagebox.showwarning("Hub", str(e))
        messagebox.showinfo("Hub", self.t["need_restart"])

    def compute_size(self):
        self.size_stop.set()
        self.size_stop = threading.Event()
        stop = self.size_stop
        self.v_cache["size"].set("…")
        cd = self.cache_dir()

        def work():
            b, n = dir_size(cd, stop)
            if not stop.is_set():
                self.after(0, lambda: self.v_cache["size"].set(f"{b / 2**30:.2f} Go ({n} fichiers)"))
        threading.Thread(target=work, daemon=True).start()

    def choose_cache(self):
        d = filedialog.askdirectory(title=self.t["choose"], initialdir=self.cache_dir())
        if d:
            self.s["cache_dir"] = os.path.normpath(d)
            save_settings(self.s)
            self.refresh()
            messagebox.showinfo("Hub", self.t["need_restart"])

    def reset_cache(self):
        self.s["cache_dir"] = ""
        save_settings(self.s)
        self.refresh()

    def purge_temp(self):
        if port_open() or game_running():
            messagebox.showwarning("Hub", self.t["busy"])
            return
        if not messagebox.askyesno("Hub", self.t["purge_q"]):
            return
        n = size = 0
        for root in temp_folders(user_dir_now()):
            for entry in os.listdir(root):
                p = os.path.join(root, entry)
                b, k = dir_size(p) if os.path.isdir(p) else (os.path.getsize(p), 1)
                try:
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                    n, size = n + k, size + b
                except OSError as e:
                    self.log(self.tool_log, f"{p}: {e}")
        messagebox.showinfo("Hub", self.t["purged"].format(n=n, mb=size / 2**20))

    def run_tool(self, args):
        py = install.venv_python()
        if not os.path.isfile(py):
            py = sys.executable
        self.log(self.tool_log, "> " + " ".join(args))
        p = self.popen([py] + args, server_env(self.s))
        self.stream(p, self.tool_log)

    def switch_mod(self, fork):
        if game_running():
            messagebox.showwarning("Hub", self.t["game_running"])
            return
        ud = user_dir_now()
        if not ud:
            return
        if fork:
            install.install_mod(ud, True, dry_run=False, quiet=True)
            install.set_mod_active(ud, install.MOD_NAME, True)
            install.set_mod_active(ud, install.UPSTREAM_MOD_NAME, False)
        else:
            install.set_mod_active(ud, install.MOD_NAME, False)
            install.set_mod_active(ud, install.UPSTREAM_MOD_NAME, True)
        self.log(self.tool_log, self.t["done"])
        self.refresh()

    def set_lang(self, _event=None):
        self.s["lang"] = self.v_lang.get()
        save_settings(self.s)
        messagebox.showinfo("Hub", self.t["restart_note"])

    def on_close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.stop_server()
        self.size_stop.set()
        self.destroy()


def selftest(png, tab="home"):
    """Development: open the Hub on a tab, wait for its status, save a screenshot of the window (Pillow), close."""
    hub = Hub()
    nb = hub.nametowidget(hub.winfo_children()[0])
    nb.select(list(hub.tabs).index(tab))

    def shot():
        try:
            from PIL import ImageGrab
            hub.update()
            x, y = hub.winfo_rootx(), hub.winfo_rooty()
            ImageGrab.grab((x, y, x + hub.winfo_width(), y + hub.winfo_height())).save(png)
            print("saved", png)
        finally:
            hub.on_close()
    hub.after(6000, shot)
    hub.mainloop()


def main():
    if sys.version_info < (3, 10):
        print("Python 3.10+ is needed")
        return 1
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "home")
        return 0
    Hub().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
