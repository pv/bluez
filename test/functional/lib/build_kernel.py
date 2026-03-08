# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
import subprocess
import shutil
import os
from pathlib import Path

from . import utils


tester_config = utils.SRC_DIR / "doc" / "tester.config"


def run(*cmd):
    print("\n$", utils.quoted(cmd))
    subprocess.run(cmd, check=True)


def build_kernel(base_dir, upstream, branch):
    base_dir = Path(base_dir)
    repo = base_dir / "linux"

    if not repo.exists():
        run("git", "clone", "--depth", "1", upstream, str(repo))

    run("git", "-C", str(repo), "remote", "set-url", "origin", upstream)
    run("git", "-C", str(repo), "fetch", "--depth", "1", "origin", branch)
    run("git", "-C", str(repo), "reset", "--hard", "FETCH_HEAD")
    run("git", "-C", str(repo), "clean", "-f", "-d", "-x")

    config = repo / ".config"
    shutil.copyfile(tester_config, config)

    ncpu = os.cpu_count()

    run("make", "-C", str(repo), "olddefconfig")
    run("make", "-C", str(repo), f"-j{ncpu}")

    kernel = repo / "arch" / "x86" / "boot" / "bzImage"
    return kernel
