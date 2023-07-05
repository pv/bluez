#!/usr/bin/python3 -P
# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / ".." / ".."))

import functional.lib.env

sys.exit(functional.lib.env._main_runner())
