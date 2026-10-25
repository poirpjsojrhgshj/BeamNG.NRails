#!/usr/bin/env python3
"""BeamNG.EarthNRails installer: upstream's install.py with the fork's names (standard library only).

    python nrails_install.py [install.py's options]     (the Hub's "Installer / mettre à jour" runs this)

The fork's mod is installed under its own folder name (mods/unpacked/beamng_earthnrails) so it never overwrites an
upstream copy. Both provide the same VFS paths (/levels/beamng_earth, lua/ge/extensions/beamngEarth), so only one may
be active: install_mod switches the upstream entry off in mods/db.json (reversible from the game's Mod Manager or the
Hub). The settings live in .beamng_earthnrails.json (the Hub keeps its own keys in it too).

install.py itself stays upstream's: this module sets its names and wraps the few functions that differ, so
`import nrails_install as install` gives the fork's installer, and launcher.py run through nrails_launcher.py too.
"""
import json
import os
import sys

import install as _up

ROOT = _up.ROOT
MOD_NAME = "beamng_earthnrails"
UPSTREAM_MOD_NAME = "beamng_earth"
CONFIG = os.path.join(ROOT, ".beamng_earthnrails.json")

_up.MOD_NAME = MOD_NAME
_up.CONFIG = CONFIG
_upstream_install_mod = _up.install_mod
_upstream_save_config = _up.save_config


def _set_active(user_dir, name, active):
    path = os.path.join(user_dir, "mods", "db.json")
    try:
        with open(path, encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return False
    entry = db.get("mods", {}).get(name) if isinstance(db, dict) else None
    if not isinstance(entry, dict) or entry.get("active") is bool(active):
        return False
    entry["active"] = bool(active)
    tmp = path + ".bnge-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
    os.replace(tmp, path)
    return True


def set_mod_active(user_dir, name, active):
    """Turn a listed mod on or off in mods/db.json (the game reads it at its start; close the game first). True if it
    changed."""
    return _set_active(user_dir, name, active)


def deactivate_upstream(user_dir):
    """Turn the upstream beamng_earth entry off in mods/db.json (same VFS paths as this fork; two active copies would
    shadow each other file by file). Its files are left in place. True if it changed."""
    return _set_active(user_dir, UPSTREAM_MOD_NAME, False)


def mod_states(user_dir):
    """{mod name: active (True / False / None: not listed)} for this fork's mod and the upstream one (mods/db.json)."""
    try:
        with open(os.path.join(user_dir, "mods", "db.json"), encoding="utf-8") as f:
            mods = json.load(f).get("mods", {})
    except (OSError, ValueError, AttributeError):
        mods = {}
    return {n: (mods.get(n) or {}).get("active") for n in (MOD_NAME, UPSTREAM_MOD_NAME)}


def install_mod(user_dir, assume_yes, dry_run, quiet=False):
    """upstream's install_mod under the fork's folder name, the upstream mod then turned off."""
    res = _upstream_install_mod(user_dir, assume_yes, dry_run, quiet)
    if not dry_run and deactivate_upstream(user_dir):
        _up.say(f"Mod: turned the upstream '{UPSTREAM_MOD_NAME}' off in the game's mod list (EarthNRails replaces it; "
                "re-enable it in the Mod Manager or the Hub to go back).")
    return res


def write_config(cfg):
    """The config file written atomically (the installer and the Hub share it)."""
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)


def save_config(user_dir, dry_run):
    """Merged into what is there (the Hub keeps its settings in the same file)."""
    cfg = dict(_up.load_config(), user_dir=user_dir, version=_up.version())
    if dry_run:
        _up.say(f"(dry run) would write {CONFIG}: {cfg}")
        return
    write_config(cfg)


_up.install_mod = install_mod
_up.save_config = save_config


def __getattr__(name):          # everything else: upstream's (venv_python, load_config, candidate_user_dirs ...)
    return getattr(_up, name)


if __name__ == "__main__":
    sys.exit(_up.main())
