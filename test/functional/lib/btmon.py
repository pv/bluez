# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
"""
VM host plugin for btmon
"""
import os
import re
import subprocess
import tempfile
import time

from . import env, utils

__all__ = [
    "Btmon",
]


class Btmon(env.HostPlugin):
    """
    Host plugin running btmon and forwarding output to logging. Parses
    timestamps output by btmon.

    """

    name = "btmon"

    def __init__(self, args=None):
        self.args = None if args is None else list(args)

    def setup(self, impl):
        fd, self.dumpfile = tempfile.mkstemp()
        os.close(fd)

        if self.args is None:
            self.args = [
                "-S",
                "-A",
                "-I",
                "--color=always",
                f"--columns=160",
                "-w",
                self.dumpfile,
            ]

        exe = utils.find_exe("monitor", "btmon")
        self.log_stream = BtmonLogStream("btmon")
        cmd = [exe, "-T"] + self.args
        self.log_stream.log.info("Starting btmon: {}".format(utils.quoted(cmd)))
        self.job = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=self.log_stream.stream,
            stderr=subprocess.STDOUT,
        )

    def stop(self):
        """
        Stop btmon and return produced dump file data
        """
        if self.job.poll() is None:
            self.job.terminate()
            self.job.wait()

        with open(self.dumpfile, "rb") as f:
            return f.read()

    def teardown(self):
        if self.job.poll() is None:
            self.job.terminate()

            # Wait for btmon to exit: we want to get all the logs
            self.job.wait()

        self.log_stream.close()
        os.unlink(self.dumpfile)


class BtmonLogStream(utils.LogStream):
    """
    Log streams that parses timestamps from btmon output
    """

    def __init__(self, name):
        super().__init__(name)
        self._localtime_tail = time.localtime()[6:]
        self._time_pat = re.compile(
            rb"\s(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+)\.(\d+)(?:$|\x1b)"
        )

    def _get_time(self, line, anc):
        m = self._time_pat.search(line)
        if m:
            m = m.groups()
            ts = (
                int(m[0]),
                int(m[1]),
                int(m[2]),
                int(m[3]),
                int(m[4]),
                int(m[5]),
            ) + self._localtime_tail
            ts = time.mktime(ts) + int(m[6]) / 10 ** len(m[6])
            self._nsec = int(ts * 1e9)

        if self._nsec is None:
            return super()._get_time(line, anc)

        nsec = self._nsec
        self._nsec += 1
        return nsec
