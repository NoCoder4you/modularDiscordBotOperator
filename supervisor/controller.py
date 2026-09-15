"""Shell-free development process backend and Linux identity evidence."""

from __future__ import annotations

import asyncio
import os
import signal
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

from .models import OutputLine, ProcessRecord, utcnow


ExitCallback = Callable[[ProcessRecord, int], Awaitable[None]]


def linux_process_identity(pid: int) -> tuple[int, tuple[str, ...]] | None:
    """Return kernel start ticks and argv; neither field alone proves ownership."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # comm may contain spaces/parentheses, so fields begin after its final ')'.
        start_ticks = int(stat[stat.rfind(")") + 2 :].split()[19])
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        argv = tuple(value.decode(errors="surrogateescape") for value in command if value)
        return start_ticks, argv
    except (OSError, ValueError, IndexError):
        return None


class SubprocessController:
    """Development/test backend; production ownership remains fixed systemd units."""

    def __init__(self, *, output_limit: int = 1000, line_limit: int = 16_384) -> None:
        self.output: deque[OutputLine] = deque(maxlen=output_limit)
        self._line_limit = line_limit
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._tasks: set[asyncio.Task[object]] = set()
        self._sequence = 0

    async def spawn(
        self,
        record: ProcessRecord,
        argv: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str],
        callback: ExitCallback,
    ) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._processes[record.process_instance_id] = process
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            task = asyncio.create_task(self._read(record, name, stream))
            self._track(task)
        waiter = asyncio.create_task(self._wait(record, process, callback))
        self._track(waiter)
        return process

    def _track(self, task: asyncio.Task[object]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read(
        self, record: ProcessRecord, stream_name: str, stream: asyncio.StreamReader | None
    ) -> None:
        if stream is None:
            return
        while line := await stream.readline():
            self._sequence += 1
            text = line[: self._line_limit].decode(errors="replace").rstrip("\r\n")
            self.output.append(
                OutputLine(
                    self._sequence,
                    utcnow(),
                    record.bot_id,
                    record.process_instance_id,
                    stream_name,
                    text,
                )
            )

    async def _wait(
        self,
        record: ProcessRecord,
        process: asyncio.subprocess.Process,
        callback: ExitCallback,
    ) -> None:
        code = await process.wait()
        self._processes.pop(record.process_instance_id, None)
        await callback(record, code)

    async def terminate(self, record: ProcessRecord) -> None:
        process = self._processes.get(record.process_instance_id)
        if process is not None:
            process.terminate()
        else:
            os.kill(record.pid, signal.SIGTERM)

    async def kill(self, record: ProcessRecord) -> None:
        process = self._processes.get(record.process_instance_id)
        if process is not None:
            process.kill()
        else:
            os.kill(record.pid, signal.SIGKILL)

    async def wait_for_exit(self, record: ProcessRecord, timeout: float) -> int:
        process = self._processes.get(record.process_instance_id)
        if process is not None:
            return await asyncio.wait_for(asyncio.shield(process.wait()), timeout)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if linux_process_identity(record.pid) is None:
                return record.exit_code or 0
            await asyncio.sleep(min(0.05, timeout))
        raise TimeoutError

    async def close(self) -> None:
        # Deliberately do not terminate bots: systemd owns production lifetime.
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
