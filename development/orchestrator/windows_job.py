"""Owned Windows Job Object: aggregate resource limits and process-tree STOP."""

import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t


class BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", SIZE_T), ("MaximumWorkingSetSize", SIZE_T),
                ("ActiveProcessLimit", w.DWORD), ("Affinity", ULONG_PTR), ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", SIZE_T), ("JobMemoryLimit", SIZE_T),
                ("PeakProcessMemoryUsed", SIZE_T), ("PeakJobMemoryUsed", SIZE_T)]


class CpuRate(ctypes.Structure):
    _fields_ = [("ControlFlags", w.DWORD), ("CpuRate", w.DWORD)]


class BasicAccounting(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", w.DWORD), ("TotalProcesses", w.DWORD),
                ("ActiveProcesses", w.DWORD), ("TotalTerminatedProcesses", w.DWORD)]


class JobProcess:
    def __init__(self, process):
        self.process = process
        self.pid = process.pid
        self.stdout, self.stderr = process.stdout, process.stderr
        self._lock = threading.Lock()

    def send(self, text):
        with self._lock:
            self.process.stdin.write((json.dumps({"text": text}) + "\n").encode("utf-8"))
            self.process.stdin.flush()

    def eof(self):
        with self._lock:
            try:
                self.process.stdin.write(b'{"eof":true}\n')
                self.process.stdin.flush()
                self.process.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        return self.process.wait(timeout=timeout)


class WindowsJob:
    def __init__(self, memory_mib=8192, cpu_percent=25):
        if os.name != "nt":
            raise RuntimeError("Windows Job Objects required")
        if not 256 <= memory_mib <= 16384 or not 1 <= cpu_percent <= 50:
            raise ValueError("Invalid job resource limits")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        self.closed = False
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limit = ExtendedLimit()
            limit.BasicLimitInformation.LimitFlags = 0x200 | 0x2000  # JOB_MEMORY | KILL_ON_JOB_CLOSE
            limit.JobMemoryLimit = memory_mib * 1024 * 1024
            self._set(9, limit)
            self._set(15, CpuRate(0x1 | 0x4, cpu_percent * 100))
            # MXC creates nested native jobs. Parent UI restrictions prevent
            # that on Windows; desktop isolation belongs to MXC, not this job.
            self.memory_mib, self.cpu_percent = memory_mib, cpu_percent
        except BaseException:
            self.close()
            raise

    def _set(self, information_class, value):
        if not self.kernel.SetInformationJobObject(self.handle, information_class, ctypes.byref(value), ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _query(self, information_class, value):
        if not self.kernel.QueryInformationJobObject(self.handle, information_class, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def spawn(self, argv, *, cwd, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pid_file=None):
        if self.closed:
            raise RuntimeError("Job already closed")
        gate = Path(__file__).with_name("launch_gate.py")
        # Use the real interpreter, not the venv redirector that could spawn a
        # child before assignment. -S also excludes startup site customizations.
        interpreter = str(Path(sys.base_prefix) / "python.exe")
        process = subprocess.Popen([interpreter, "-I", "-S", "-B", str(gate)], cwd=str(cwd),
                                   env=env, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW, shell=False)
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, w.HANDLE(int(process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
            specification = {"argv": [str(value) for value in argv], "cwd": str(cwd), "env": env,
                             "pid_file": str(pid_file) if pid_file else None}
            process.stdin.write((json.dumps(specification) + "\n").encode("utf-8"))
            process.stdin.flush()
            return JobProcess(process)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise

    def sample(self):
        limit = self._query(9, ExtendedLimit())
        cpu = self._query(15, CpuRate())
        accounting = self._query(1, BasicAccounting())
        return {"memory_limit_mib": limit.JobMemoryLimit // (1024 * 1024),
                "cpu_rate_percent": cpu.CpuRate / 100, "cpu_hard_cap": bool(cpu.ControlFlags & 4),
                "peak_job_memory_mib": round(limit.PeakJobMemoryUsed / (1024 * 1024), 2),
                "active_processes": accounting.ActiveProcesses,
                "cpu_seconds": round((accounting.TotalUserTime + accounting.TotalKernelTime) / 10_000_000, 3),
                "kill_on_close": bool(limit.BasicLimitInformation.LimitFlags & 0x2000)}

    def terminate(self):
        if not self.closed and not self.kernel.TerminateJobObject(self.handle, 130):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if not self.closed:
            self.closed = True
            self.kernel.CloseHandle(self.handle)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
