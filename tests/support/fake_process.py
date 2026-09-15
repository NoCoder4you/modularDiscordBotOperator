"""Controllable process fixture; never imports or connects to Discord."""

from __future__ import annotations

import os
import signal
import sys
import time

mode = os.environ.get("FAKE_MODE", "run")
exit_code = int(os.environ.get("FAKE_EXIT_CODE", "7"))


def terminate(_signal: int, _frame: object) -> None:
    print("terminated", flush=True)
    raise SystemExit(0)


if mode == "crash":
    print("startup failed", file=sys.stderr, flush=True)
    raise SystemExit(exit_code)
if mode == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, terminate)

print("ready", flush=True)
print("diagnostic", file=sys.stderr, flush=True)
if mode == "delayed-crash":
    time.sleep(float(os.environ.get("FAKE_DELAY", "0.1")))
    raise SystemExit(exit_code)
while True:
    time.sleep(0.05)
