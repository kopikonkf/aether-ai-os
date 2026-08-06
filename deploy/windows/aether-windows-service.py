"""SCM-compatible Windows service host for Aether child processes.

The Service Control Manager starts this Python process.  The host connects to
SCM through ``StartServiceCtrlDispatcherW``, reports lifecycle state, and owns
the configured child process tree in a Windows Job Object.  Closing or stopping
the service therefore cannot leave an orphaned Gateway or watchdog process.

The child command is intentionally opaque to this host and is never written to
the service receipt because future command arguments may contain sensitive
configuration.  Aether services currently pass only paths and local addresses.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Sequence


SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED = 0x00000001
SERVICE_START_PENDING = 0x00000002
SERVICE_STOP_PENDING = 0x00000003
SERVICE_RUNNING = 0x00000004
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_INTERROGATE = 0x00000004
SERVICE_CONTROL_SHUTDOWN = 0x00000005
ERROR_CALL_NOT_IMPLEMENTED = 120
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063
ERROR_SERVICE_SPECIFIC_ERROR = 1066
NO_ERROR = 0

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one child process as an SCM-aware Windows service."
    )
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--event-log-path", required=True)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Child executable and arguments; place them after --.",
    )
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a child command is required after --")
    return args


class _WindowsBindings:
    """Late-bound Win32 declarations so the asset remains importable in Linux CI."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("the Aether Windows service host requires Windows")

        self.SERVICE_MAIN_FUNCTION = ctypes.WINFUNCTYPE(
            None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR)
        )
        self.HANDLER_EX_FUNCTION = ctypes.WINFUNCTYPE(
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
        )

        service_main_function = self.SERVICE_MAIN_FUNCTION

        class SERVICE_STATUS(ctypes.Structure):
            _fields_ = [
                ("dwServiceType", wintypes.DWORD),
                ("dwCurrentState", wintypes.DWORD),
                ("dwControlsAccepted", wintypes.DWORD),
                ("dwWin32ExitCode", wintypes.DWORD),
                ("dwServiceSpecificExitCode", wintypes.DWORD),
                ("dwCheckPoint", wintypes.DWORD),
                ("dwWaitHint", wintypes.DWORD),
            ]

        class SERVICE_TABLE_ENTRYW(ctypes.Structure):
            _fields_ = [
                ("lpServiceName", wintypes.LPWSTR),
                ("lpServiceProc", service_main_function),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.SERVICE_STATUS = SERVICE_STATUS
        self.SERVICE_TABLE_ENTRYW = SERVICE_TABLE_ENTRYW
        self.JOBOBJECT_EXTENDED_LIMIT_INFORMATION = (
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        )

        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self.advapi32.StartServiceCtrlDispatcherW.argtypes = [
            ctypes.POINTER(SERVICE_TABLE_ENTRYW)
        ]
        self.advapi32.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
        self.advapi32.RegisterServiceCtrlHandlerExW.argtypes = [
            wintypes.LPCWSTR,
            self.HANDLER_EX_FUNCTION,
            wintypes.LPVOID,
        ]
        self.advapi32.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
        self.advapi32.SetServiceStatus.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(SERVICE_STATUS),
        ]
        self.advapi32.SetServiceStatus.restype = wintypes.BOOL

        self.kernel32.CreateJobObjectW.argtypes = [
            wintypes.LPVOID,
            wintypes.LPCWSTR,
        ]
        self.kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self.kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel32.TerminateJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        self.kernel32.TerminateJobObject.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL


class WindowsServiceHost:
    def __init__(
        self,
        *,
        service_name: str,
        command: Sequence[str],
        working_directory: Path,
        event_log_path: Path,
    ) -> None:
        self.service_name = service_name
        self.command = list(command)
        self.working_directory = working_directory
        self.event_log_path = event_log_path
        self.api = _WindowsBindings()
        self.stop_requested = threading.Event()
        self.status_handle: int | None = None
        self.current_state = SERVICE_STOPPED
        self.checkpoint = 0
        self.stopped_reported = False
        self.process: subprocess.Popen[bytes] | None = None
        self.job_handle: int | None = None
        self._handler_callback = self.api.HANDLER_EX_FUNCTION(self._control_handler)
        self._service_main_callback = self.api.SERVICE_MAIN_FUNCTION(
            self._service_main
        )

    def _write_event(self, event: str, **fields: object) -> None:
        payload = {
            "event": event,
            "service": self.service_name,
            "observed_at": _utc_now(),
            **fields,
        }
        try:
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except OSError:
            # Receipt failure must not prevent SCM from controlling the service.
            pass

    def _report_status(
        self,
        state: int,
        *,
        win32_exit_code: int = NO_ERROR,
        service_exit_code: int = 0,
        wait_hint_ms: int = 0,
    ) -> None:
        self.current_state = state
        pending = state in {SERVICE_START_PENDING, SERVICE_STOP_PENDING}
        self.checkpoint = self.checkpoint + 1 if pending else 0
        controls = 0
        if state == SERVICE_RUNNING:
            controls = SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN
        status = self.api.SERVICE_STATUS(
            SERVICE_WIN32_OWN_PROCESS,
            state,
            controls,
            win32_exit_code,
            service_exit_code,
            self.checkpoint,
            wait_hint_ms,
        )
        if state == SERVICE_STOPPED:
            # SCM invalidates the RPC context after the first STOPPED report.
            # Mark it before the call so no exception path attempts a second one.
            self.stopped_reported = True
        if self.status_handle and not self.api.advapi32.SetServiceStatus(
            self.status_handle, ctypes.byref(status)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def _control_handler(
        self,
        control: int,
        event_type: int,
        event_data: int,
        context: int,
    ) -> int:
        del event_type, event_data, context
        try:
            if control in {SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN}:
                if self.current_state not in {SERVICE_STOPPED, SERVICE_STOP_PENDING}:
                    self._report_status(SERVICE_STOP_PENDING, wait_hint_ms=20_000)
                    self.stop_requested.set()
                return NO_ERROR
            if control == SERVICE_CONTROL_INTERROGATE:
                return NO_ERROR
        except Exception as exc:  # callbacks must never unwind into SCM
            self._write_event(
                "service.host.control_error", error_type=type(exc).__name__
            )
        return ERROR_CALL_NOT_IMPLEMENTED

    def _create_job(self) -> int:
        job = self.api.kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = self.api.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.kernel32.SetInformationJobObject(
            job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.api.kernel32.CloseHandle(job)
            raise error
        return job

    def _start_child(self) -> None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self.job_handle = self._create_job()
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.working_directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except Exception:
            self._close_job()
            raise
        process_handle = wintypes.HANDLE(int(self.process._handle))  # type: ignore[attr-defined]
        if not self.api.kernel32.AssignProcessToJobObject(
            self.job_handle, process_handle
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.process.kill()
            self.process.wait(timeout=10)
            self.api.kernel32.CloseHandle(self.job_handle)
            self.job_handle = None
            raise error
        self._write_event("service.host.child_started", pid=self.process.pid)

    def _stop_child_tree(self) -> None:
        if self.job_handle:
            self.api.kernel32.TerminateJobObject(self.job_handle, NO_ERROR)
        if self.process:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def _close_job(self) -> None:
        if self.job_handle:
            self.api.kernel32.CloseHandle(self.job_handle)
            self.job_handle = None

    def _service_main(self, argc: int, argv: object) -> None:
        del argc, argv
        self.status_handle = self.api.advapi32.RegisterServiceCtrlHandlerExW(
            self.service_name, self._handler_callback, None
        )
        if not self.status_handle:
            self._write_event("service.host.registration_failed")
            return

        try:
            self._report_status(SERVICE_START_PENDING, wait_hint_ms=20_000)
            self._start_child()
            self._report_status(SERVICE_RUNNING)
            self._write_event("service.host.running")

            while not self.stop_requested.wait(0.5):
                assert self.process is not None
                exit_code = self.process.poll()
                if exit_code is not None:
                    service_code = max(1, min(abs(exit_code), 0xFFFFFFFF))
                    self._write_event(
                        "service.host.child_exited", exit_code=exit_code
                    )
                    self._close_job()
                    self._report_status(
                        SERVICE_STOPPED,
                        win32_exit_code=ERROR_SERVICE_SPECIFIC_ERROR,
                        service_exit_code=service_code,
                    )
                    return

            self._stop_child_tree()
            self._close_job()
            self._write_event("service.host.stopped")
            self._report_status(SERVICE_STOPPED)
        except Exception as exc:
            self._write_event(
                "service.host.failed", error_type=type(exc).__name__
            )
            try:
                self._stop_child_tree()
            finally:
                self._close_job()
            if not self.stopped_reported:
                try:
                    self._report_status(
                        SERVICE_STOPPED,
                        win32_exit_code=ERROR_SERVICE_SPECIFIC_ERROR,
                        service_exit_code=1,
                    )
                except Exception:
                    pass

    def run(self) -> None:
        table = (self.api.SERVICE_TABLE_ENTRYW * 2)()
        table[0].lpServiceName = self.service_name
        table[0].lpServiceProc = self._service_main_callback
        table[1].lpServiceName = None
        table[1].lpServiceProc = self.api.SERVICE_MAIN_FUNCTION()
        if not self.api.advapi32.StartServiceCtrlDispatcherW(table):
            error = ctypes.get_last_error()
            if error == ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
                raise RuntimeError(
                    "service host must be launched by Windows Service Control Manager"
                )
            raise ctypes.WinError(error)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if os.name != "nt":
        print("Aether Windows service host requires Windows.", file=sys.stderr)
        return 2
    host = WindowsServiceHost(
        service_name=args.service_name,
        command=args.command,
        working_directory=Path(args.working_directory),
        event_log_path=Path(args.event_log_path),
    )
    host.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
