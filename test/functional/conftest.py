# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
import os
import re
import logging
from pathlib import Path

import pytest

from .lib import utils


# For logging test status messages to test-functional.log
status_log = logging.getLogger("pytest")
status_log_seen = set()


def pytest_addoption(parser):
    parser.addoption(
        "--kernel",
        action="store",
        default=None,
        help=("Kernel image to use"),
    )
    parser.addoption(
        "--usb",
        action="store",
        default=None,
        help=("USB HCI devices to use, e.g. 'hci0,hci1'"),
    )
    parser.addoption(
        "--force-usb",
        action="store_true",
        default=None,
        help=("Force tests to run with USB controllers instead of btvirt"),
    )
    parser.addoption(
        "--build-dir",
        action="store",
        default=None,
        type=Path,
        help=("Build directory to find development binaries"),
    )
    parser.addoption(
        "--list",
        action="store_true",
        default=None,
        help=("List tests"),
    )
    parser.addoption(
        "--log-filter",
        action="append",
        default=None,
        help=(
            "Enable/disable loggers by name. Can be passed multiple times. Example: +host.0,-rpc"
        ),
    )
    parser.addoption(
        "--no-log-reorder",
        action="store_true",
        default=False,
        help="Don't reorder logs to timestamp order",
    )
    parser.addoption(
        "--vm-timeout",
        action="store",
        default=20,
        type=float,
        help="Timeout in seconds for waiting for RPC reply with VM (default: 20 s)",
    )
    parser.addoption(
        "--btmon",
        action="store_true",
        help="Launch btmon on all hosts to log events, and dump traffic to test-functional-host.*.btsnoop",
    )


def pytest_configure(config):
    if config.option.list:
        config.option.reportchars = "A"
        config.option.no_header = True
        config.option.verbose = -2

    if config.option.build_dir is not None:
        utils.BUILD_DIR = config.option.build_dir


COLLECT_ERRORS = []


def pytest_collectreport(report):
    if report.outcome != "passed":
        COLLECT_ERRORS.append((report.outcome, report.fspath))


def pytest_collection_finish(session):
    if session.config.option.list:
        regex = re.compile(r"\[.*")
        names = set(regex.sub("", item.nodeid) for item in session.items)
        for name in sorted(names):
            print(f"test/{name}")
        for outcome, name in COLLECT_ERRORS:
            print(f"{outcome.upper()} test/{name}")
        print()
        os._exit(0)


def _get_item_vm_host_setup(item):
    callspec = getattr(item, "callspec", None)
    if callspec is not None:
        return (
            callspec.params.get("vm_setup", None),
            callspec.params.get("host_setup", None),
        )
    return None, None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    # Sort VM-using tests to minimize VM setup/teardown
    def sort_key(item):
        vm_setup, host_setup = _get_item_vm_host_setup(item)
        key = ()
        if vm_setup:
            key += tuple(sorted(vm_setup.items()))
        if host_setup:
            key += (host_setup["reuse_group"] or "",)
        return key

    if not config.option.list:
        items.sort(key=sort_key)

    # Specify default groups for pytest-xdist --dist loadgroup
    if config.pluginmanager.has_plugin("xdist"):
        prev_reuse_group = None
        for item in items:
            if item.get_closest_marker("xdist_group") is not None:
                continue

            _, host_setup = _get_item_vm_host_setup(item)
            if not host_setup or not host_setup["reuse_group"]:
                continue

            xdist_group = "reuse-{}".format(host_setup["reuse_group"])
            item.add_marker(pytest.mark.xdist_group(xdist_group))


#
# Logging customization:
#
# - pattern-based log filtering
# - log entry reordering to timestamp order
# - logging test stages and outcomes to test log file
#


def pytest_sessionstart(session):
    config = session.config

    allow = set()
    deny = set()

    if config.option.log_filter is not None:
        for item in config.option.log_filter:
            for name in item.split(","):
                if name.startswith("+"):
                    allow.add(name[1:])
                elif name.startswith("-"):
                    deny.add(name[1:])
                else:
                    allow.add(name)

        utils.LogNameFilter.enable(logging.root.handlers, allow, deny)

    if not config.option.no_log_reorder:
        utils.LogReorderFilter.enable(logging.root.handlers)

    for handler in logging.root.handlers:
        fmt = getattr(handler, "formatter", None)
        if hasattr(fmt, "add_color_level"):
            fmt.add_color_level(utils.OUT, "yellow")


def pytest_sessionfinish(session):
    utils.LogNameFilter.disable(logging.root.handlers)
    utils.LogReorderFilter.disable(logging.root.handlers)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_logstart(nodeid, location):
    utils.LogReorderFilter.flush_all()
    yield


def status_log_stage(name, stage):
    status_log.info(f"\n\n==== {name}: {stage} ====")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    status_log_stage(item.nodeid, "setup")
    yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    status_log_stage(item.nodeid, "call")
    yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    status_log_stage(item.nodeid, "teardown")
    yield
    utils.LogReorderFilter.flush_all()


@pytest.hookimpl(wrapper=True)
def pytest_report_teststatus(report, config):
    if not isinstance(report, pytest.TestReport):
        return (yield)

    key = (report.nodeid, report.when)
    if key not in status_log_seen:
        status_log_seen.add(key)
        outcome = (
            report.outcome.upper() if report.when == "call" or report.failed else "done"
        )
        status_log.info(f"\n==== {report.nodeid}: {report.when} {outcome} ====\n")
        if report.failed:
            status_log.error(str(report.longrepr))
            for header, content in report.sections:
                if header.startswith("Captured log"):
                    continue
                status_log.error(f"--- {header} ---\n{content}")
                status_log.error(f"---")

    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_logfinish(nodeid, location):
    utils.LogReorderFilter.flush_all()
    yield


#
# Fixtures
#


@pytest.fixture(scope="session")
def kernel(pytestconfig):
    """
    Fixture for kernel image. Skips tests if no kernel available.

    Yields:
        kernel (str): path to the kernel image
    """
    kernel = pytestconfig.getoption("kernel")

    if kernel is None:
        kernel = os.environ.get("FUNCTIONAL_TESTING_KERNEL")

    if not kernel:
        pytest.skip("No kernel image")

    if Path(kernel).is_dir():
        kernel = str(Path(kernel) / "arch" / "x86" / "boot" / "bzImage")

    if not Path(kernel).is_file():
        pytest.skip("no kernel image")

    return kernel


@pytest.fixture(scope="session")
def usb_indices(pytestconfig):
    """
    Fixture for available HW USB controllers. Skips tests if not available.

    Yields:
        usb_indices: list of usb controller names (hci0, hci1, ...)
        messages: error messages associated with each
    """
    from .lib import env

    usb_indices = pytestconfig.getoption("usb")

    if usb_indices is None:
        usb_indices = os.environ.get("FUNCTIONAL_TESTING_CONTROLLERS")

    if usb_indices is None:
        usb_indices = [item.name for item in Path("/sys/class/bluetooth").iterdir()]
    else:
        usb_indices = usb_indices.replace(",", " ").split()

    messages = []
    for name in list(usb_indices):
        subsys = Path("/sys/class/bluetooth") / name / "device" / "subsystem"
        if subsys.resolve() != Path("/sys/bus/usb"):
            usb_indices.remove(name)
            continue

        try:
            env.Environment.check_controller(name)
            messages.append("")
        except ValueError as exc:
            usb_indices.remove(name)
            messages.append(str(exc))

    return usb_indices, messages


@pytest.fixture(scope="session")
def host_setup(request):
    """
    Host setup configuration

    Yields:
        dict(setup=plugins: tuple[HostPlugin], reuse_group=None | str)
    """
    if getattr(request, "param", None) is None:
        raise pytest.fail("host setup not specified")

    for plugins in request.param.get("setup", ()):
        for plugin in plugins:
            plugin.presetup()

    return request.param


@pytest.fixture(scope="session")
def vm_setup(request):
    """
    VM setup configuration

    Yields:
        (num_hosts: int, hw_controllers: bool)
    """
    if getattr(request, "param", None) is None:
        raise pytest.fail("env setup not specified")

    return request.param


def _vm_impl(request, kernel, num_hosts, hw):
    from .lib import env

    config = request.session.config

    if hw or config.option.force_usb:
        usb_indices, messages = request.getfixturevalue("usb_indices")
        if len(usb_indices) < num_hosts:
            message = "\n".join(m for m in messages[:num_hosts] if m)
            pytest.skip(reason=f"Not enough USB controllers: {message}")
    else:
        usb_indices = None

    with env.Environment(
        kernel, num_hosts, usb_indices=usb_indices, timeout=config.option.vm_timeout
    ) as vm:
        yield vm


def _hosts_impl(request, vm, setup, reuse_group):
    from .lib import Btmon

    vm_timeout = request.session.config.option.vm_timeout
    timeout = vm_timeout

    if reuse_group is not None and vm.reuse_group != reuse_group:
        _close_hosts(request, vm)

    for h, plugins in zip(vm.hosts, setup):
        timeout = max(vm_timeout * len(plugins), timeout)

        if request.session.config.option.btmon:
            plugins = (Btmon(),) + plugins

        for p in plugins:
            h.start_load(p)

    for h in vm.hosts:
        h.wait_load(timeout=timeout)

    yield vm.hosts

    if reuse_group is None:
        _close_hosts(request, vm)

    vm.reuse_group = reuse_group


def _close_hosts(request, vm):
    try:
        if request.session.config.option.btmon:
            for h in vm.hosts:
                with open(f"test-functional-{h._name}.btsnoop", "wb") as f:
                    f.write(h.btmon.stop())
    finally:
        vm.close_hosts()


@pytest.fixture(scope="package")
def vm(request, kernel, vm_setup):
    """
    Session-scope virtual machine fixture. Used internally by `hosts`.

    Yields:
        env.Environment
    """
    yield from _vm_impl(request, kernel, **vm_setup)


@pytest.fixture
def hosts(request, vm, host_setup):
    """
    Session-scope fixture that expands to a list of VM host proxies
    (`HostProxy`), with configuration as specified in `host_config`. The
    VM instances used may be reused by other tests.  The userspace test
    runner is torn down between tests.

    Example:

        def test_something(hosts):
            host0 = hosts[0]
            host1 = hosts[1]
    """
    yield from _hosts_impl(request, vm, **host_setup)


# Same with single-test scope:


@pytest.fixture
def vm_once(request, kernel, vm_setup):
    """
    Function-scope virtual machine fixture. Used internally by `hosts_once`.

    Yields:
        env.Environment
    """
    yield from _vm_impl(request, kernel, **vm_setup)


@pytest.fixture
def hosts_once(request, vm_module, host_setup):
    """
    Function-scope fixture. Same as `hosts`, but spawn separate VM
    instances for this test only.

    Example:

        def test_something(hosts_once):
            host0 = hosts_once[0]
            host1 = hosts_once[1]
    """
    yield from _hosts_impl(request, vm_module, **host_setup)
