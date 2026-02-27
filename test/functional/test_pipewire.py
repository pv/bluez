# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
"""
Tests for Pipewire audio
"""
import sys
import os
import re
import pytest
import subprocess
import tempfile
import time
import logging
import json
import dbus
from pathlib import Path

import pytest

from .lib import (
    HostPlugin,
    host_config,
    find_exe,
    Bluetoothd,
    Bluetoothctl,
    DbusSession,
    LogStream,
)

pytestmark = [pytest.mark.vm, pytest.mark.pipewire]

log = logging.getLogger(__name__)


class Pipewire(HostPlugin):
    name = "pipewire"
    depends = [DbusSession(), Bluetoothd()]

    def __init__(
        self,
        uuids=(
            "0000110a-0000-1000-8000-00805f9b34fb",
            "0000110b-0000-1000-8000-00805f9b34fb",
        ),
        roles="a2dp_sink a2dp_source",
    ):
        self.uuids = tuple(uuids)
        self.roles = str(roles)

    def presetup(self):
        try:
            self.exe_pw = find_exe("", "pipewire")
            self.exe_wp = find_exe("", "wireplumber")
            self.exe_dump = find_exe("", "pw-dump")

            # check version
            res = subprocess.run(
                [self.exe_wp, "--version"], stdout=subprocess.PIPE, encoding="utf-8"
            )
            m = re.search("libwireplumber ([0-9.]+)", res.stdout)
            if m:
                version = tuple(int(x) for x in m.group(1).split("."))
                if version < (0, 5, 8):
                    raise ValueError("wireplumber too old")
            else:
                raise ValueError("wireplumber version unknown")
        except (FileNotFoundError, ValueError) as exc:
            pytest.skip(reason=f"Pipewire: {exc}")

    def setup(self, impl):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="pipewire-", dir="/run")
        conf_dir = Path(self.tmpdir.name) / "config"
        runtime_dir = Path(self.tmpdir.name) / "runtime"

        dropin_dir = conf_dir / "wireplumber" / "wireplumber.conf.d"
        wp_conf = dropin_dir / "01-config.conf"

        conf_dir.mkdir()
        runtime_dir.mkdir()
        dropin_dir.mkdir(parents=True)

        environ = dict(os.environ)

        environ["XDG_CONFIG_HOME"] = str(conf_dir)
        environ["XDG_STATE_HOME"] = str(runtime_dir)
        environ["XDG_RUNTIME_HOME"] = str(runtime_dir)
        environ["PIPEWIRE_RUNTIME_DIR"] = str(runtime_dir)
        environ["PIPEWIRE_DEBUG"] = "2"
        environ["WIREPLUMBER_DEBUG"] = "3"

        with open(wp_conf, "w") as f:
            text = f"""
            monitor.bluez.properties = {{
               bluez5.roles = [ {self.roles} ]
            }}
            """
            f.write(text)

        log.info("Start pipewire")

        self.logger = LogStream("pipewire")
        self.pw = subprocess.Popen(
            self.exe_pw,
            env=environ,
            stdout=self.logger.stream,
            stderr=subprocess.STDOUT,
        )
        self.wp = subprocess.Popen(
            self.exe_wp,
            env=environ,
            stdout=self.logger.stream,
            stderr=subprocess.STDOUT,
        )

        # Wait for Pipewire's bluetooth services
        log.info("Wait for Pipewire...")
        bus = dbus.SystemBus()
        adapter = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.freedesktop.DBus.Properties",
        )
        while True:
            uuids = [str(uuid) for uuid in adapter.Get("org.bluez.Adapter1", "UUIDs")]
            if all(uuid in uuids for uuid in self.uuids):
                break
            time.sleep(0.25)

        os.environ["PIPEWIRE_RUNTIME_DIR"] = str(runtime_dir)

        # Wait for wireplumber session services
        while True:
            data = json.loads(self.pw_dump())
            for item in data:
                if item.get("type", None) != "PipeWire:Interface:Client":
                    continue
                if item["info"]["props"]["application.name"] != "WirePlumber":
                    continue
                if "api.bluez" in item["info"]["props"].get("session.services", ""):
                    break
            else:
                time.sleep(0.25)
                continue
            break

        log.info("Pipewire ready")

    def pw_dump(self):
        ret = subprocess.run(["pw-dump"], stdout=subprocess.PIPE, encoding="utf-8")
        return ret.stdout

    def teardown(self):
        log.info("Stop pipewire")
        self.pw.terminate()
        self.wp.terminate()
        self.pw.wait()
        self.wp.wait()
        self.tmpdir.cleanup()


@pytest.fixture
def paired_hosts(hosts, host_setup):
    from .test_bluetoothctl_vm import test_bluetoothctl_pair, test_bluetoothctl_pair_le

    le = any(
        "ControllerMode = le" in (p.conf or "")
        for plugins in host_setup["setup"]
        for p in plugins
        if isinstance(p, Bluetoothd)
    )

    if le:
        test_bluetoothctl_pair_le(hosts)
    else:
        test_bluetoothctl_pair(hosts)

    return hosts


a2dp_host = [Bluetoothctl(), Pipewire(roles="a2dp_sink a2dp_source")]


@host_config(a2dp_host, a2dp_host)
def test_pipewire_a2dp(paired_hosts):
    host0, host1 = paired_hosts

    # Connect
    host1.bluetoothctl.send(f"trust {host0.bdaddr}\n")

    host0.bluetoothctl.send(f"scan off\n")
    host0.bluetoothctl.send(f"connect {host1.bdaddr}\n")

    # Wait for pipewire devices to appear
    check_pipewire_devices_exist(host0, "a2dp-sink")


bap_host = [
    Bluetoothd(conf="[General]\nControllerMode = le\n", args=["-E", "-K"]),
    Bluetoothctl(),
    Pipewire(
        roles="bap_sink bap_source", uuids=("00001850-0000-1000-8000-00805f9b34fb",)
    ),
]


@host_config(bap_host, bap_host)
def test_pipewire_bap(paired_hosts):
    host0, host1 = paired_hosts

    # Connect
    host1.bluetoothctl.send(f"trust {host0.bdaddr}\n")

    host0.bluetoothctl.send(f"scan off\n")
    host0.bluetoothctl.send(f"connect {host1.bdaddr}\n")

    # Wait for pipewire devices to appear
    check_pipewire_devices_exist(host0, "bap-sink")


hfp_hf_host = [
    Bluetoothctl(),
    Pipewire(
        roles="hfp_hf",
        uuids=("0000111e-0000-1000-8000-00805f9b34fb",),
    ),
]

hfp_ag_host = [
    Bluetoothctl(),
    Pipewire(
        roles="hfp_ag",
        uuids=("0000111f-0000-1000-8000-00805f9b34fb",),
    ),
]


@host_config(hfp_ag_host, hfp_hf_host)
def test_pipewire_hfp(paired_hosts):
    host0, host1 = paired_hosts

    # Connect
    host1.bluetoothctl.send(f"trust {host0.bdaddr}\n")

    host0.bluetoothctl.send(f"scan off\n")
    host0.bluetoothctl.send(f"connect {host1.bdaddr}\n")

    # Wait for pipewire devices to appear
    check_pipewire_devices_exist(host0, "hfp")


def check_pipewire_devices_exist(host, profile="a2dp-sink"):
    factories = {
        "a2dp-sink": ("api.bluez5.a2dp.sink",),
        "a2dp-source": ("api.bluez5.a2dp.source",),
        "hfp": ("api.bluez5.sco.sink", "api.bluez5.sco.source"),
        "bap-sink": ("api.bluez5.media.sink",),
        "bap-source": ("api.bluez5.media.source",),
        "bap-duplex": ("api.bluez5.media.sink", "api.bluez5.media.source"),
    }[profile]

    for j in range(20):
        text = host.pipewire.pw_dump()
        data = json.loads(text)

        seen = set()
        for item in data:
            if item.get("type", None) != "PipeWire:Interface:Node":
                continue
            seen.add(item["info"]["props"].get("factory.name", None))

        if not set(factories).difference(seen):
            break

        time.sleep(1)
    else:
        assert False, f"pipewire devices not seen within timeout:\n{text}"
