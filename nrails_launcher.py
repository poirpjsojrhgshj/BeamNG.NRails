#!/usr/bin/env python3
"""BeamNG.EarthNRails: upstream's launcher.py with the fork's installer (nrails_install: its mod folder name, its
config file). The Hub starts the server through it:

    python nrails_launcher.py --server --user-dir ...      (or no argument: install, server and game, as upstream)
"""
import sys

import nrails_install  # noqa: F401  (sets install's names before launcher imports it)
import launcher

if __name__ == "__main__":
    sys.exit(launcher.main())
