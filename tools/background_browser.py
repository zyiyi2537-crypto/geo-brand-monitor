"""Keep headed monitoring browsers off the interactive Windows desktop."""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from uuid import uuid4


class BrowserDesktop:
    """Own a private desktop inherited by the service and all its children.

    Chromium remains headed, so the existing login/session and rendering paths
    keep working. Login helpers are launched separately on the normal desktop.
    Never switch the user's input desktop.
    """

    def __init__(self) -> None:
        self.name = f"GEO-Monitor-{uuid4().hex}"
        self.handle = None
        self.user32 = None
        if os.name != "nt":
            return
        from ctypes import wintypes

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.CreateDesktopW.argtypes = (
            wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        )
        self.user32.CreateDesktopW.restype = wintypes.HANDLE
        self.user32.CloseDesktop.argtypes = (wintypes.HANDLE,)
        self.user32.CloseDesktop.restype = wintypes.BOOL
        self.handle = self.user32.CreateDesktopW(self.name, None, None, 0, 0x01FF, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def launch(self, args, *, env, cwd, stdout, stderr):
        if self.handle is None:
            return subprocess.Popen(args, env=env, cwd=cwd, stdout=stdout, stderr=stderr)
        # subprocess.STARTUPINFO does not expose lpDesktop to CreateProcessW;
        # assigning an arbitrary Python attribute there is silently ignored.
        return _DesktopProcess(args, desktop=self.name, env=env, cwd=cwd,
                               stdout=stdout, stderr=stderr)

    def close(self) -> None:
        if self.handle is not None:
            self.user32.CloseDesktop(self.handle)
            self.handle = None


class _DesktopProcess:
    """Small Popen-compatible process handle with native lpDesktop support."""

    def __init__(self, args, *, desktop, env, cwd, stdout, stderr):
        import msvcrt
        from ctypes import wintypes as w

        class StartupInfo(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR),
                        ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR),
                        ("dwX", w.DWORD), ("dwY", w.DWORD),
                        ("dwXSize", w.DWORD), ("dwYSize", w.DWORD),
                        ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD),
                        ("dwFillAttribute", w.DWORD), ("dwFlags", w.DWORD),
                        ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                        ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE),
                        ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]

        class ProcessInfo(ctypes.Structure):
            _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE),
                        ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_processes", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD),
                        ("scheduling", w.DWORD)]

        class JobLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = (w.HANDLE,)
        kernel.DuplicateHandle.argtypes = (w.HANDLE, w.HANDLE, w.HANDLE,
                                          ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD)
        kernel.CreateProcessW.argtypes = (w.LPCWSTR, w.LPWSTR, ctypes.c_void_p,
                                         ctypes.c_void_p, w.BOOL, w.DWORD,
                                         ctypes.c_void_p, w.LPCWSTR,
                                         ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo))
        kernel.GetExitCodeProcess.argtypes = (w.HANDLE, ctypes.POINTER(w.DWORD))
        kernel.TerminateProcess.argtypes = (w.HANDLE, w.UINT)
        kernel.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
        kernel.WaitForSingleObject.restype = w.DWORD
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, w.LPCWSTR)
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
        kernel.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
        kernel.ResumeThread.argtypes = (w.HANDLE,)
        kernel.ResumeThread.restype = w.DWORD
        self._kernel = kernel
        self._handle = None
        self._job = None
        self.returncode = None
        inherited = []

        def duplicate(stream):
            handle = w.HANDLE()
            current = kernel.GetCurrentProcess()
            if not kernel.DuplicateHandle(current, msvcrt.get_osfhandle(stream.fileno()),
                                          current, ctypes.byref(handle), 0, True, 2):
                raise ctypes.WinError(ctypes.get_last_error())
            inherited.append(handle)
            return handle

        startup = StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.lpDesktop = desktop
        startup.dwFlags = 0x100  # STARTF_USESTDHANDLES
        info = ProcessInfo()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(arg) for arg in args]))
        environment = ctypes.create_unicode_buffer(
            "\0".join(f"{key}={value}" for key, value in sorted(env.items(), key=lambda item: item[0].upper())) + "\0\0")
        try:
            self._job = kernel.CreateJobObjectW(None, None)
            if not self._job:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = JobLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            with open(os.devnull, "rb") as stdin:
                startup.hStdInput = duplicate(stdin)
                startup.hStdOutput = duplicate(stdout)
                startup.hStdError = duplicate(stderr)
                if not kernel.CreateProcessW(str(args[0]), command, None, None, True,
                                              0x08000404, environment, str(cwd),
                                              ctypes.byref(startup), ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
            self._handle = info.hProcess
            self.pid = info.dwProcessId
            try:
                if not kernel.AssignProcessToJobObject(self._job, self._handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                if kernel.ResumeThread(info.hThread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
            except Exception:
                kernel.TerminateProcess(self._handle, 1)
                raise
            finally:
                kernel.CloseHandle(info.hThread)
        finally:
            for handle in inherited:
                kernel.CloseHandle(handle)

    def poll(self):
        if self.returncode is None and self._kernel.WaitForSingleObject(self._handle, 0) == 0:
            from ctypes import wintypes
            code = wintypes.DWORD()
            if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.05)
        return self.returncode

    def terminate(self):
        if self.poll() is None and not self._kernel.TerminateProcess(self._handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def stop_tree(self):
        if self._job:
            self._kernel.CloseHandle(self._job)
            self._job = None
        self.wait(timeout=5)

    def __del__(self):
        job = getattr(self, "_job", None)
        if job:
            self._kernel.CloseHandle(job)
        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel.CloseHandle(handle)


def service_environment(base: dict[str, str], *, isolated: bool) -> dict[str, str]:
    env = dict(base)
    env["GEO_BROWSER_BACKGROUND"] = "1"
    env["GEO_BROWSER_PRIVATE_DESKTOP"] = "1" if isolated else "0"
    return env


def background_service_ready(payload: dict) -> bool:
    return (payload.get("background_mode") is True
            and (os.name != "nt" or payload.get("desktop_isolated") is True))


def stop_service(process) -> None:
    """Close only our service tree, including its browser and driver children."""
    if process is None:
        return
    if isinstance(process, _DesktopProcess):
        process.stop_tree()
        return
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            result = subprocess.run(
                [os.path.join(os.environ["SystemRoot"], "System32", "taskkill.exe"),
                 "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=8,
            )
            if result.returncode == 0:
                process.wait(timeout=5)
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)

