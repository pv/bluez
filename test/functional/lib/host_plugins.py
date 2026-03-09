# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
"""
VM host plugins
"""
import os
import sys
import subprocess
import collections
import logging
import tempfile
import time
import shutil
from pathlib import Path

import pytest
import pexpect

from . import env, utils

__all__ = [
    "host_config",
    "parametrized_host_config",
    "Bdaddr",
    "Call",
    "Chronyd",
    "Bluetoothd",
    "Bluetoothctl",
    "DbusSession",
]


class Bdaddr(env.HostPlugin):
    name = "bdaddr"

    def setup(self, impl):
        self.value = utils.get_bdaddr()


class Rcvbuf(env.HostPlugin):
    name = "rcvbuf"

    def __init__(self, rcvbuf=None):
        self.rcvbuf = rcvbuf

    def presetup(self, config):
        if self.rcvbuf is None:
            self.rcvbuf = config.getini("host_plugins.rcvbuf.default")

        self.rcvbuf = int(self.rcvbuf)

    def setup(self, impl):
        self.log = logging.getLogger(self.name)

        self.log.info(f"Set SO_RCVBUF default = {self.rcvbuf}")
        with open("/proc/sys/net/core/rmem_default", "wb") as f:
            f.write(f"{self.rcvbuf}".encode("ascii"))


class Call(env.HostPlugin):
    name = "call"

    def __call__(self, func, *a, **kw):
        return func(*a, **kw)


class Chronyd(env.HostPlugin):
    name = "chronyd"

    def __init__(self):
        try:
            self.exe = utils.find_exe("", "chronyd")
        except FileNotFoundError:
            self.exe = None

    def setup(self, impl):
        self.log = logging.getLogger(self.name)
        self.log_stream = utils.LogStream(self.name)

        if self.exe is None:
            self.log.warn("chronyd not found")
            return
        if not Path("/dev/ptp0").exists():
            self.log.warn("/dev/ptp0 not available")
            return

        self.tmpdir = utils.TmpDir(prefix=f"{self.name}-")
        config = Path(self.tmpdir.name) / "chronyd.conf"

        with open(config, "w") as f:
            text = f"makestep 0.1 3\nrefclock PHC /dev/ptp0 poll -2\n"
            f.write(text)

        cmd = [self.exe, "-n", "-f", str(config), "-q"]
        self.log.debug("Synchronizing clock: {}".format(utils.quoted(cmd)))
        subprocess.run(cmd, stdout=self.log_stream.stream, stderr=subprocess.STDOUT)

        cmd = [self.exe, "-n", "-f", str(config)]
        self.log.debug("Starting chronyd: {}".format(utils.quoted(cmd)))
        self.job = subprocess.Popen(
            cmd, stdout=self.log_stream.stream, stderr=subprocess.STDOUT
        )

    def teardown(self):
        self.job.terminate()
        self.tmpdir.cleanup()
        self.log_stream.close()


class _Dbus(env.HostPlugin):
    def __init__(self):
        self.exe = utils.find_exe("", "dbus-daemon")

    def setup(self, impl):
        self.log = logging.getLogger(self.name)
        self.log_stream = utils.LogStream(self.name)

        self.tmpdir = utils.TmpDir(prefix=f"{self.name}-")
        self.config = Path(self.tmpdir.name) / "config.xml"

        socket = (Path(self.tmpdir.name) / "socket").resolve()
        self.address = "unix:path={}".format(socket)

        with open(self.config, "w") as f:
            text = f"""
            <!DOCTYPE busconfig PUBLIC
                    "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
                    "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
            <busconfig>
            <type>{self.dbus_type}</type>
            <listen>{self.address}</listen>
            <policy context="default">
            <allow user="*"/>
            <allow own="*"/>
            <allow send_type="method_call"/>
            <allow send_type="signal"/>
            <allow send_type="method_return"/>
            <allow send_type="error"/>
            <allow receive_type="method_call"/>
            <allow receive_type="signal"/>
            <allow receive_type="method_return"/>
            <allow receive_type="error"/>
            </policy>
            </busconfig>
            """
            f.write(text)

        cmd = [
            self.exe,
            "--nofork",
            "--nopidfile",
            "--nosyslog",
            f"--config-file={self.config}",
        ]

        self.log.debug(
            "Starting dbus-session @ {}: {}".format(self.address, utils.quoted(cmd))
        )

        self.job = subprocess.Popen(
            cmd,
            stdout=self.log_stream.stream,
            stderr=subprocess.STDOUT,
        )
        utils.wait_files([self.job], [socket])
        self.log.debug("dbus-session ready")

        if self.dbus_type == "system":
            os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = self.address
        elif self.dbus_type == "session":
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = self.address

    def teardown(self):
        self.job.terminate()
        self.tmpdir.cleanup()
        self.log_stream.close()


class DbusSystem(_Dbus):
    name = "dbus-system"
    dbus_type = "system"


class DbusSession(_Dbus):
    name = "dbus-session"
    dbus_type = "session"


class Bluetoothd(env.HostPlugin):
    name = "bluetoothd"
    depends = [DbusSystem()]

    def __init__(self, debug=True, conf=None, args=()):
        super().__init__()

        self.conf = conf
        self.args = tuple(args)
        if debug and "-d" not in self.args:
            self.args += ("-d",)

    def setup(self, impl):
        import dbus

        self.log = logging.getLogger(self.name)

        exe = utils.find_exe("src", "bluetoothd")

        self.tmpdir = utils.TmpDir(prefix="bluetoothd-state-")
        state_dir = Path(self.tmpdir.name) / "state"
        conf = Path(self.tmpdir.name) / "main.conf"

        state_dir.mkdir()

        if self.conf is None:
            shutil.copyfile(utils.SRC_DIR / "src" / "main.conf", conf)
        else:
            with open(str(conf), "w") as f:
                f.write(self.conf)

        envvars = dict(os.environ)
        envvars["STATE_DIRECTORY"] = str(state_dir)

        cmd = [exe, "--nodetach", "-f", str(conf)] + list(self.args)

        self.log.info("Start bluetoothd: {}".format(utils.quoted(cmd)))

        self.log_stream = utils.LogStream("bluetoothd")
        self.job = subprocess.Popen(
            cmd,
            env=envvars,
            stdin=subprocess.DEVNULL,
            stdout=self.log_stream.stream,
            stderr=subprocess.STDOUT,
        )

        # Wait for the adapter to appear powered
        self.log.info("Wait for bluetoothd...")
        bus = dbus.SystemBus()
        while True:
            try:
                adapter = dbus.Interface(
                    bus.get_object("org.bluez", "/org/bluez/hci0"),
                    "org.freedesktop.DBus.Properties",
                )
                if adapter.Get("org.bluez.Adapter1", "Powered"):
                    break
            except dbus.DBusException:
                pass
            time.sleep(0.5)

        self.log.info("Bluetoothd ready")

    def teardown(self):
        self.log.info("Stop bluetoothd")
        self.job.terminate()
        self.tmpdir.cleanup()
        self.log_stream.close()


class Bluetoothctl(env.HostPlugin):
    name = "bluetoothctl"
    depends = [Bluetoothd()]

    def __init__(self):
        self.exe = utils.find_exe("client", "bluetoothctl")

    def setup(self, impl):
        self.log = logging.getLogger(self.name)
        self.log_stream = utils.LogStream(self.name)
        self.ctl = pexpect.spawn(self.exe, logfile=self.log_stream.stream)

    def teardown(self):
        self.ctl.terminate()
        self.log_stream.close()

    def expect(self, *a, **kw):
        ret = self.ctl.expect(*a, **kw)
        self.log.debug("match found")
        return ret, self.ctl.match.groups()

    def send(self, *a, **kw):
        return self.ctl.send(*a, **kw)


HOST_SETUPS = 0
DEFAULT_PLUGINS = [Rcvbuf(), Bdaddr(), Call(), Chronyd()]


def _expand_plugins(plugins):
    """
    Resolve plugin dependencies to linear load order
    """
    plugins = DEFAULT_PLUGINS + list(plugins)
    to_load = []
    seen = set()

    while plugins:
        deps = []
        for dep in plugins[0].depends or ():
            if type(dep) not in seen:
                deps.append(dep)
                seen.add(type(dep))
                continue

        if deps:
            plugins = deps + plugins
            continue

        to_load.append(plugins.pop(0))

    return tuple(to_load)


def parametrized_host_config(param_host_setups, hw=False, ids=None, reuse=False):
    """
    Declare parametrized host configurations.

    See https://docs.pytest.org/en/stable/how-to/parametrize.html for the
    concept.

    Args:
        param_host_setups (list): list of host setups
        hw (bool): whether to require hardware BT controller
        reuse (bool): whether to define a setup where the test host processes
            are not required to be torn down between tests. This is only useful
            for tests that do not perturb e.g. bluetoothd state too much.

    Returns:
        callable: decorator setting pytest attributes
    """
    global HOST_SETUPS

    host_setups = []
    host_ids = []

    if ids is not None:
        if len(ids) != len(param_host_setups):
            raise ValueError("Wrong number of ids")
        host_ids = list(ids)

    num_hosts = set(len(setup) for setup in param_host_setups)
    if len(num_hosts) > 1:
        raise ValueError("Parametrized host setups must have same host count")
    num_hosts = num_hosts.pop()

    for host_setup in param_host_setups:
        setup = tuple(_expand_plugins(plugins) for plugins in host_setup)

        name = f"hosts{HOST_SETUPS}"
        HOST_SETUPS += 1

        host_setup = dict(setup=setup, name=name, reuse=bool(reuse))
        host_setups.append(host_setup)

        if ids is None:
            host_ids.append(name)

    vm_setup = dict(num_hosts=num_hosts, hw=hw)
    vm_ids = ["vm{}{}".format(len(setup), "hw" if hw else "")]

    def decorator(func):
        func = pytest.mark.parametrize(
            "host_setup", host_setups, indirect=True, ids=host_ids
        )(func)
        func = pytest.mark.parametrize(
            "vm_setup", [vm_setup], indirect=True, ids=vm_ids
        )(func)
        return func

    return decorator


def host_config(*host_setup, hw=False, reuse=False):
    """
    Declare host configuration.

    Args:
        *host_setup: each argument is a list of plugins to be loaded on a host.
            The number of arguments specifies the number of hosts.
        hw (bool): whether to require hardware BT controller
        reuse (bool): whether to define a setup where the test host processes
            are not required to be torn down between tests. This is only useful
            for tests that do not perturb e.g. bluetoothd state too much.

    Returns:
        callable: decorator setting pytest attributes

    Example:

        @host_config([Bluetoothd()], [Bluetoothd()])
        def test_something(hosts):
            host0, host1 = hosts

    Example:

        # Allow not restarting Bluetoothd between tests sharing this configuration
        base_config = host_config([Bluetoothd()], reuse=True)

        @base_config
        def test_one(hosts):
            host0, = hosts

        @base_config
        def test_two(hosts):
            # Note: uses same Bluetoothd() instance as above
            host0, = hosts

    """
    return parametrized_host_config([host_setup], hw=hw, reuse=reuse)
