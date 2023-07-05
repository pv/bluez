# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
import os
import pytest
import subprocess
import threading

from .. import utils


def test_log_stream(caplog):
    with utils.LogStream(__name__) as log_stream:
        log_stream.stream.write(b"hello")

    (record,) = (r for r in caplog.records if r.name == __name__)
    assert "hello" in record.message
