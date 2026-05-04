"""
Runtime protection layer — anti-debug, anti-VM, anti-analysis.
Call run_protection_checks() as early as possible in the entry point.
Only active when running as a frozen EXE (sys.frozen == True) or when
ARC_FORCE_PROTECTION=1 is set (for manual testing).
"""
from __future__ import annotations

import ctypes
import os
import struct
import sys
import time


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _is_protection_active() -> bool:
    return getattr(sys, "frozen", False) or os.environ.get("ARC_FORCE_PROTECTION", "") == "1"


def _kill_self() -> None:
    """Terminate the process immediately without any traceback."""
    try:
        ctypes.windll.kernel32.TerminateProcess(
            ctypes.windll.kernel32.GetCurrentProcess(), 1
        )
    except Exception:
        pass
    os._exit(1)


# ─── Debugger detection ────────────────────────────────────────────────────────

def _check_is_debugger_present() -> bool:
    """Calls kernel32.IsDebuggerPresent via WinAPI."""
    try:
        return bool(ctypes.windll.kernel32.IsDebuggerPresent())
    except Exception:
        return False


def _check_remote_debugger() -> bool:
    """Calls CheckRemoteDebuggerPresent via WinAPI."""
    try:
        kernel32 = ctypes.windll.kernel32
        is_debugged = ctypes.c_bool(False)
        kernel32.CheckRemoteDebuggerPresent(
            kernel32.GetCurrentProcess(),
            ctypes.byref(is_debugged),
        )
        return is_debugged.value
    except Exception:
        return False


def _check_nt_debug_port() -> bool:
    """Uses NtQueryInformationProcess(ProcessDebugPort=7) to detect debugger attachment."""
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        hproc = kernel32.GetCurrentProcess()
        debug_port = ctypes.c_ulong(0)
        ret_len = ctypes.c_ulong(0)
        status = ntdll.NtQueryInformationProcess(
            hproc,
            7,  # ProcessDebugPort
            ctypes.byref(debug_port),
            ctypes.sizeof(debug_port),
            ctypes.byref(ret_len),
        )
        return status == 0 and debug_port.value != 0
    except Exception:
        return False


def _check_nt_debug_object_handle() -> bool:
    """Uses NtQueryInformationProcess(ProcessDebugObjectHandle=30) to detect debugger."""
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        hproc = kernel32.GetCurrentProcess()
        handle = ctypes.c_ulong(0)
        ret_len = ctypes.c_ulong(0)
        # STATUS_PORT_NOT_SET = 0xC0000353 means no debugger
        status = ntdll.NtQueryInformationProcess(
            hproc,
            30,  # ProcessDebugObjectHandle
            ctypes.byref(handle),
            ctypes.sizeof(handle),
            ctypes.byref(ret_len),
        )
        # Success (0) and handle non-null → debugger attached
        return status == 0 and handle.value != 0
    except Exception:
        return False


def _check_heap_flags() -> bool:
    """Checks NtGlobalFlag in the PEB — set by debuggers."""
    try:
        # Read PEB pointer from TEB
        # Only works on 64-bit; skip gracefully on 32-bit
        if struct.calcsize("P") != 8:
            return False
        ntdll = ctypes.windll.ntdll
        # NtQueryInformationProcess with ProcessBasicInformation (0)
        class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("ExitStatus", ctypes.c_ulong),
                ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_ulong64),
                ("BasePriority", ctypes.c_ulong),
                ("UniqueProcessId", ctypes.c_ulong64),
                ("InheritedFromUniqueProcessId", ctypes.c_ulong64),
            ]
        pbi = _PROCESS_BASIC_INFORMATION()
        status = ntdll.NtQueryInformationProcess(
            ctypes.windll.kernel32.GetCurrentProcess(),
            0,
            ctypes.byref(pbi),
            ctypes.sizeof(pbi),
            None,
        )
        if status != 0 or not pbi.PebBaseAddress:
            return False
        # NtGlobalFlag is at PEB+0xBC (64-bit)
        nt_global_flag = ctypes.c_ulong(0)
        ntdll.RtlMoveMemory(
            ctypes.byref(nt_global_flag),
            pbi.PebBaseAddress + 0xBC,
            4,
        )
        # Flags 0x70 are set when debugger creates the process
        return bool(nt_global_flag.value & 0x70)
    except Exception:
        return False


# ─── Timing checks ────────────────────────────────────────────────────────────

def _check_timing_rdtsc() -> bool:
    """
    Tight busy-loop timing check.
    Debuggers (especially when stepping) dramatically slow down execution.
    Threshold is intentionally generous to avoid false positives.
    """
    try:
        t1 = time.perf_counter_ns()
        x = 0
        for i in range(500_000):
            x ^= i
        t2 = time.perf_counter_ns()
        elapsed_ms = (t2 - t1) / 1_000_000
        # Normal: < 30 ms. Being stepped through: hundreds of ms.
        return elapsed_ms > 200
    except Exception:
        return False


# ─── Known analysis / debugger process names ──────────────────────────────────

_ANALYSIS_PROCS: frozenset[str] = frozenset({
    # Debuggers
    "ollydbg.exe", "ollydbg2.exe",
    "x64dbg.exe", "x32dbg.exe",
    "windbg.exe", "windbg preview.exe",
    "idaq.exe", "idaq64.exe", "idaw.exe", "idaw64.exe",
    "ida.exe", "ida64.exe",
    # Decompilers
    "ghidra.exe", "ghidrarun.exe",
    "dnspy.exe", "ilspy.exe", "dotpeek.exe", "justdecompile.exe",
    "reflector.exe",
    # Monitors / proxies
    "procmon.exe", "procmon64.exe",
    "procexp.exe", "procexp64.exe",
    "processhacker.exe", "processhacker2.exe",
    "apimonitor-x64.exe", "apimonitor-x86.exe",
    "wireshark.exe", "fiddler.exe", "fiddler everywhere.exe",
    "charles.exe", "mitmproxy.exe", "burpsuite.exe",
    "httpdebugger.exe", "httpdebuggerui.exe",
    # PE / binary analysis
    "pestudio.exe", "die.exe", "detect-it-easy.exe",
    "cff explorer.exe", "cffexplorer.exe",
    "lordpe.exe", "lordpe_x64.exe",
    "exeinfope.exe", "peid.exe",
    "reshacker.exe", "resource hacker.exe",
    # Memory / cheating
    "cheatengine.exe", "cheatengine-x86_64.exe",
    "cheatengine-x86_64-SSE4-AVX2.exe",
    "scylla.exe", "scylla_x64.exe", "scylla_x86.exe",
    "pchunter.exe",
    # Misc unpacking
    "immunitydebugger.exe", "mpengine.exe",
    "radare2.exe", "r2.exe", "r2agent.exe",
    "binary ninja.exe",
})


def _check_analysis_processes() -> bool:
    """Scans the running process list for known analysis / reverse-engineering tools."""
    try:
        import subprocess
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=no_win,
        )
        lowered = out.stdout.lower()
        for name in _ANALYSIS_PROCS:
            if name in lowered:
                return True
    except Exception:
        pass
    return False


# ─── VM / sandbox detection ───────────────────────────────────────────────────

_VM_REGISTRY_KEYS: list[str] = [
    # VirtualBox
    r"HARDWARE\ACPI\DSDT\VBOX__",
    r"HARDWARE\ACPI\FADT\VBOX__",
    r"HARDWARE\ACPI\RSDT\VBOX__",
    r"SOFTWARE\Oracle\VirtualBox Guest Additions",
    r"SYSTEM\ControlSet001\Services\VBoxGuest",
    r"SYSTEM\ControlSet001\Services\VBoxMouse",
    r"SYSTEM\ControlSet001\Services\VBoxService",
    r"SYSTEM\ControlSet001\Services\VBoxSF",
    r"SYSTEM\ControlSet001\Services\VBoxVideo",
    # VMware
    r"SOFTWARE\VMware, Inc.\VMware Tools",
    r"SYSTEM\ControlSet001\Services\vmhgfs",
    r"SYSTEM\ControlSet001\Services\vmci",
    r"SYSTEM\ControlSet001\Services\VMMEMCTL",
    r"SYSTEM\ControlSet001\Services\vmx86",
    r"SYSTEM\ControlSet001\Services\VMTools",
    # QEMU / KVM  (Hyper-V key removed — Windows 11 VBS creates it on real hardware)
    r"HARDWARE\DEVICEMAP\Scsi\Scsi Port 0\Scsi Bus 0\Target Id 0\Logical Unit Id 0",
    # Sandboxie
    r"SYSTEM\CurrentControlSet\Services\SbieDrv",
    r"SOFTWARE\Sandboxie-Plus",
]

_VM_FILES: list[str] = [
    r"C:\windows\system32\drivers\vmmouse.sys",
    r"C:\windows\system32\drivers\vmhgfs.sys",
    r"C:\windows\system32\drivers\VBoxMouse.sys",
    r"C:\windows\system32\drivers\VBoxGuest.sys",
    r"C:\windows\system32\drivers\VBoxSF.sys",
    r"C:\windows\system32\vboxdisp.dll",
    r"C:\windows\system32\vboxhook.dll",
    r"C:\windows\system32\vboxmrxnp.dll",
    r"C:\windows\system32\vboxogl.dll",
    r"C:\windows\system32\vboxtray.exe",
    r"C:\windows\system32\VBoxControl.exe",
    r"C:\windows\system32\VBoxService.exe",
    r"C:\windows\system32\vmtoolsd.exe",
    r"C:\windows\system32\vmwaretray.exe",
    r"C:\windows\system32\vmwareuser.exe",
]

_VM_PROCS: frozenset[str] = frozenset({
    "vmtoolsd.exe", "vmwaretray.exe", "vmwareuser.exe",
    "vmacthlp.exe", "vmnat.exe",
    "vboxservice.exe", "vboxtray.exe",
    "vmsrvc.exe", "vmusrvc.exe",
    "df5serv.exe",          # Parallels
    "prl_cc.exe",           # Parallels
    "sandboxiedcomlaunch.exe",  # Sandboxie
    "sandboxierpcss.exe",
    "joeboxcontrol.exe", "joeboxserver.exe",  # Joe Sandbox
    "cuckoomon.dll",        # Cuckoo
    "sbiesvc.exe",          # Sandboxie service
})


def _check_vm_registry() -> bool:
    try:
        import winreg
        for key_path in _VM_REGISTRY_KEYS:
            try:
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                return True
            except OSError:
                pass
    except Exception:
        pass
    return False


def _check_vm_files() -> bool:
    for path in _VM_FILES:
        if os.path.isfile(path):
            return True
    return False


def _check_vm_processes() -> bool:
    try:
        import subprocess
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=no_win,
        )
        lowered = out.stdout.lower()
        for name in _VM_PROCS:
            if name in lowered:
                return True
    except Exception:
        pass
    return False


def _check_cpuid_hypervisor() -> bool:
    """CPUID leaf 0x1 bit 31 of ECX is set by hypervisors."""
    try:
        # Only available on some platforms via ctypes assembly tricks;
        # safest cross-Python method is to check the registry / WMI instead.
        import subprocess
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance -Class Win32_ComputerSystem).Model",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=no_win,
        )
        model = (out.stdout or "").strip().lower()
        for keyword in ("vmware", "virtualbox", "qemu", "kvm", "xen"):  # "hyper-v" removed — false positive on Win11
            if keyword in model:
                return True
    except Exception:
        pass
    return False


# ─── Anti-dump: make it harder to dump from memory ────────────────────────────

def _apply_anti_dump() -> None:
    """
    Sets the PE SizeOfImage to 0 in memory, which breaks many process-dumpers
    that rely on the in-memory PE header to reconstruct the binary.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        # Get base address of this module
        h_module = kernel32.GetModuleHandleW(None)
        if not h_module:
            return
        # SizeOfImage is at offset 0x50 into the OptionalHeader (PE32+)
        # PE header offset is at 0x3C into the DOS header
        dos_sig = ctypes.c_ushort.from_address(h_module)
        if dos_sig.value != 0x5A4D:  # 'MZ'
            return
        pe_offset = ctypes.c_uint32.from_address(h_module + 0x3C).value
        # Magic: 0x10B = PE32, 0x20B = PE32+
        magic = ctypes.c_ushort.from_address(h_module + pe_offset + 0x18).value
        size_of_image_offset = pe_offset + 0x50 if magic == 0x20B else pe_offset + 0x50
        old_prot = ctypes.c_ulong(0)
        addr = h_module + size_of_image_offset
        kernel32.VirtualProtect(addr, 4, 0x40, ctypes.byref(old_prot))  # PAGE_EXECUTE_READWRITE
        ctypes.c_uint32.from_address(addr).value = 0
        kernel32.VirtualProtect(addr, 4, old_prot.value, ctypes.byref(old_prot))
    except Exception:
        pass


# ─── Public API ───────────────────────────────────────────────────────────────

def run_protection_checks(
    *,
    skip_vm: bool = False,
    skip_timing: bool = False,
    silent: bool = True,
) -> None:
    """
    Run all protection checks.  Call this as the very first thing in main().

    Parameters
    ----------
    skip_vm : bool
        Skip VM/sandbox detection (useful for dev builds running inside VMs).
    skip_timing : bool
        Skip timing-based anti-step check (useful on slow CI machines).
    silent : bool
        If True (default), kill silently.  If False, print which check failed
        before killing (for debugging the protection layer only).
    """
    if sys.platform != "win32":
        return
    if not _is_protection_active():
        return

    def _fail(reason: str) -> None:
        if not silent:
            print(f"[protection] FAIL: {reason}", flush=True)
        _kill_self()

    # --- Debugger checks (fast, WinAPI) ---
    if _check_is_debugger_present():
        _fail("IsDebuggerPresent")

    if _check_remote_debugger():
        _fail("CheckRemoteDebuggerPresent")

    if _check_nt_debug_port():
        _fail("NtQueryInformationProcess(ProcessDebugPort)")

    if _check_nt_debug_object_handle():
        _fail("NtQueryInformationProcess(ProcessDebugObjectHandle)")

    if _check_heap_flags():
        _fail("PEB NtGlobalFlag")

    # --- Analysis process scan ---
    if _check_analysis_processes():
        _fail("analysis process detected")

    # --- VM / sandbox checks ---
    if not skip_vm:
        if _check_vm_registry():
            _fail("VM registry keys")
        if _check_vm_files():
            _fail("VM driver files")
        if _check_vm_processes():
            _fail("VM processes")
        if _check_cpuid_hypervisor():
            _fail("hypervisor CPUID / WMI model")

    # --- Timing check (run last, it's the slowest) ---
    if not skip_timing and _check_timing_rdtsc():
        _fail("timing check (step-through detected)")

    # --- Anti-dump: corrupt in-memory PE header ---
    _apply_anti_dump()
