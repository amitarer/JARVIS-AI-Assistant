"""Read-only Windows observations, without extra packages or generated commands."""

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import time

from jarvis.core.models import UserError
from jarvis.infrastructure.windows import powershell


WEEKDAYS_IT = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
MONTHS_IT = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
             "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            "total_physical", "available_physical", "total_pagefile", "available_pagefile",
            "total_virtual", "available_virtual", "available_extended_virtual")]


class PowerStatus(ctypes.Structure):
    _fields_ = [("ac", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                ("system_flags", ctypes.c_ubyte), ("remaining", ctypes.c_uint32), ("full_lifetime", ctypes.c_uint32)]


def _filetime_ticks(value):
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


class SystemInformation:
    """All values come from live Win32 APIs or a fixed, local CIM collector."""

    def __init__(self):
        self._kernel32 = None

    @property
    def kernel32(self):
        if os.name != "nt":
            raise UserError("SystemInformation richiede Windows.")
        if self._kernel32 is None:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetSystemTimePreciseAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
            kernel.GetSystemTimePreciseAsFileTime.restype = None
            kernel.GetTickCount64.argtypes = []
            kernel.GetTickCount64.restype = ctypes.c_uint64
            kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
            kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
            kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
            kernel.GetSystemTimes.restype = wintypes.BOOL
            kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(PowerStatus)]
            kernel.GetSystemPowerStatus.restype = wintypes.BOOL
            kernel.GetLogicalDriveStringsW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
            kernel.GetLogicalDriveStringsW.restype = wintypes.DWORD
            kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
            kernel.GetDriveTypeW.restype = wintypes.UINT
            kernel.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR] + [ctypes.POINTER(ctypes.c_uint64)] * 3
            kernel.GetDiskFreeSpaceExW.restype = wintypes.BOOL
            self._kernel32 = kernel
        return self._kernel32

    def _utc_now(self):
        value = wintypes.FILETIME()
        self.kernel32.GetSystemTimePreciseAsFileTime(ctypes.byref(value))
        seconds, ticks = divmod(_filetime_ticks(value), 10_000_000)
        return datetime.fromtimestamp(seconds - 11_644_473_600, timezone.utc).replace(microsecond=ticks // 10)

    def _stamp(self, source):
        return {"observed_at_utc": self._utc_now().isoformat(), "source": source}

    def _timezone_id(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as key:
                return winreg.QueryValueEx(key, "TimeZoneKeyName")[0].strip("\x00")
        except OSError:
            return None

    def _query(self, section, context, **parameters):
        context.checkpoint()
        script = Path(__file__).with_name("system_information.ps1").read_text(encoding="utf-8")
        code, output = powershell(script, context, payload={"section": section, **parameters})
        if code:
            raise UserError(f"Impossibile leggere le informazioni Windows ({section}). Verifica che CIM sia disponibile.")
        try:
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError
        except (ValueError, TypeError):
            raise UserError("Risposta del servizio informazioni Windows non valida.") from None
        context.checkpoint()
        return result

    def get_current_datetime(self, context):
        context.checkpoint()
        utc = self._utc_now()
        local = utc.astimezone()
        offset = local.utcoffset()
        offset_seconds = int(offset.total_seconds()) if offset is not None else None
        return {
            "source": "GetSystemTimePreciseAsFileTime / Windows local timezone",
            "observed_at_utc": utc.isoformat(), "local_iso": local.isoformat(),
            "date": local.date().isoformat(), "time": local.strftime("%H:%M:%S"),
            "time_it": local.strftime("%H:%M"), "weekday_it": WEEKDAYS_IT[local.weekday()],
            "date_it": f"{local.day} {MONTHS_IT[local.month - 1]} {local.year}",
            "timezone": {"windows_id": self._timezone_id(), "name": local.tzname(),
                         "utc_offset_seconds": offset_seconds,
                         "utc_offset": local.strftime("%z")[:3] + ":" + local.strftime("%z")[3:]},
        }

    def get_system_information(self, context):
        result = self._query("system", context)
        uptime = self.kernel32.GetTickCount64() / 1000
        result.update(self._stamp("Win32_OperatingSystem / GetTickCount64"))
        result.update(computer_name=socket.gethostname(), uptime_seconds=round(uptime, 3))
        return result

    def get_memory_information(self, context):
        context.checkpoint()
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not self.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise UserError("Windows non ha restituito lo stato della memoria RAM.")
        total, available = status.total_physical, status.available_physical
        return {**self._stamp("GlobalMemoryStatusEx"), "total_bytes": total, "available_bytes": available,
                "used_bytes": total - available, "used_percent": round(100 * (total - available) / total, 2) if total else None,
                "total_gib": round(total / 1024**3, 2), "available_gib": round(available / 1024**3, 2)}

    def _cpu_times(self):
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not self.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise UserError("Windows non ha restituito i contatori della CPU.")
        return _filetime_ticks(idle), _filetime_ticks(kernel) + _filetime_ticks(user)

    def _cpu_usage(self, context):
        context.checkpoint()
        first_idle, first_total = self._cpu_times()
        started = time.monotonic()
        while time.monotonic() - started < 0.2:
            context.checkpoint()
            context.cancellation.wait(min(0.05, max(0, 0.2 - (time.monotonic() - started))))
        context.checkpoint()
        last_idle, last_total = self._cpu_times()
        total, idle = last_total - first_total, last_idle - first_idle
        valid = total > 0 and 0 <= idle <= total
        return {"percent": round(100 * (total - idle) / total, 2) if valid else None,
                "sample_seconds": round(time.monotonic() - started, 3), "source": "GetSystemTimes"}

    def get_hardware_information(self, context):
        result = self._query("hardware", context)
        result["cpu_usage"] = self._cpu_usage(context)
        result["memory"] = self.get_memory_information(context)
        result["disks"] = self.get_disk_information(context)["disks"]
        result["battery"] = self.get_battery_status(context)
        result.update(self._stamp("Win32_Processor / Win32_VideoController / Win32 APIs"))
        return result

    def get_disk_information(self, context):
        context.checkpoint()
        kernel = self.kernel32
        length = kernel.GetLogicalDriveStringsW(0, None)
        if not length:
            raise UserError("Impossibile elencare le unita' Windows.")
        buffer = ctypes.create_unicode_buffer(length + 1)
        count = kernel.GetLogicalDriveStringsW(len(buffer), buffer)
        if not count or count >= len(buffer):
            raise UserError("L'elenco delle unita' Windows e' cambiato. Riprova.")
        disks = []
        types = {0: "unknown", 1: "unavailable", 2: "removable", 3: "fixed", 4: "network", 5: "optical", 6: "ramdisk"}
        for root in buffer[:count].split("\x00"):
            if not root:
                continue
            context.checkpoint()
            drive_type = kernel.GetDriveTypeW(root)
            item = {"path": root, "drive_type": types.get(drive_type, "unknown"), "available": False}
            if drive_type in {2, 3, 6}:
                available, total, free = ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64()
                if kernel.GetDiskFreeSpaceExW(root, ctypes.byref(available), ctypes.byref(total), ctypes.byref(free)):
                    item.update(available=True, total_bytes=total.value, free_bytes=free.value,
                                available_bytes=available.value, used_bytes=total.value - free.value,
                                free_gib=round(free.value / 1024**3, 2))
                else:
                    item["unavailable_reason"] = "Accesso negato o supporto non disponibile."
            else:
                item["unavailable_reason"] = "Unita' di rete, ottica o non disponibile: nessun accesso automatico."
            disks.append(item)
        return {**self._stamp("GetLogicalDriveStringsW / GetDiskFreeSpaceExW"), "disks": disks}

    def get_battery_status(self, context):
        context.checkpoint()
        status = PowerStatus()
        if not self.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            raise UserError("Windows non ha restituito lo stato di alimentazione.")
        present = None if status.flags == 255 else not bool(status.flags & 128)
        return {**self._stamp("GetSystemPowerStatus"), "present": present,
                "ac_connected": {0: False, 1: True}.get(status.ac),
                "percent": int(status.percent) if present is True and status.percent <= 100 else None,
                "charging": bool(status.flags & 8) if present is True else None,
                "remaining_seconds": int(status.remaining) if present is True and status.remaining != 0xFFFFFFFF else None}

    def get_process_information(self, context, query="", limit=20):
        result = self._query("processes", context, query=query, limit=limit)
        result.update(self._stamp("Win32_Process.GetOwnerSid / Get-Process"))
        return result

    def get_open_applications(self, context):
        # Reuse the existing, read-only UI Automation bridge.
        from jarvis.tools.desktop import desktop_request
        result = desktop_request({"action": "inspect", "window_id": 0}, context)
        foreground = result["foreground_window_id"]
        result["active_window"] = next((window for window in result["windows"] if window["window_id"] == foreground), None)
        if foreground and result["active_window"] is None:
            result["active_window_unavailable_reason"] = "Finestra esclusa (JARVIS) o non accessibile."
        result.update(self._stamp("Windows UI Automation / GetForegroundWindow"))
        return result
