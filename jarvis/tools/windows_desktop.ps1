# Native UI Automation bridge. Inputs arrive as JSON, never interpolated into code.
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class JarvisDesktop {
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int command);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint message, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern uint SendInput(uint n, INPUT[] inputs, int size);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int n);
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT {
        public int dx, dy; public uint data, flags, time; public UIntPtr extra;
    }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT {
        public ushort vk, scan; public uint flags, time; public UIntPtr extra;
    }
    [StructLayout(LayoutKind.Explicit)] struct INPUTUNION {
        [FieldOffset(0)] public MOUSEINPUT mouse;
        [FieldOffset(0)] public KEYBDINPUT key;
    }
    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public INPUTUNION data; }
    public static void Focus(IntPtr target) {
        if (IsIconic(target)) ShowWindow(target, 9);
        uint ignored;
        uint foregroundThread = GetWindowThreadProcessId(GetForegroundWindow(), out ignored);
        uint currentThread = GetCurrentThreadId();
        bool attached = foregroundThread != 0 && foregroundThread != currentThread
            && AttachThreadInput(currentThread, foregroundThread, true);
        try { BringWindowToTop(target); SetForegroundWindow(target); }
        finally { if (attached) AttachThreadInput(currentThread, foregroundThread, false); }
    }
    static INPUT Key(ushort vk, ushort scan, uint flags) {
        var input = new INPUT(); input.type = 1;
        input.data.key.vk = vk; input.data.key.scan = scan; input.data.key.flags = flags;
        return input;
    }
    static void Send(INPUT[] inputs) {
        if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT))) != inputs.Length)
            throw new InvalidOperationException("Windows ha bloccato l'input, oppure l'app richiede privilegi superiori.");
    }
    public static void Text(IntPtr target, string text) {
        foreach (char ch in text) {
            if (GetForegroundWindow() != target) throw new InvalidOperationException("Il focus e cambiato. Input interrotto.");
            Send(new INPUT[] { Key(0, ch, 4), Key(0, ch, 6) });
        }
    }
    public static void Keys(int[] keys) {
        var inputs = new INPUT[keys.Length * 2];
        for (int i = 0; i < keys.Length; i++) inputs[i] = Key((ushort)keys[i], 0, 0);
        for (int i = 0; i < keys.Length; i++) inputs[keys.Length + i] = Key((ushort)keys[keys.Length - 1 - i], 0, 2);
        Send(inputs);
    }
    public static void Click(int x, int y) {
        if (!SetCursorPos(x, y)) throw new InvalidOperationException("Posizione mouse non disponibile.");
        var down = new INPUT(); down.data.mouse.flags = 2;
        var up = new INPUT(); up.data.mouse.flags = 4;
        Send(new INPUT[] { down, up });
    }
}
'@
$null = [JarvisDesktop]::SetProcessDPIAware()
$request = $env:JARVIS_TOOL_INPUT | ConvertFrom-Json

function Get-WindowEntry($element) {
    $current = $element.Current
    $processName = ''
    try { $processName = (Get-Process -Id $current.ProcessId -ErrorAction Stop).ProcessName } catch {}
    return @{ window_id = [long]$current.NativeWindowHandle; title = $current.Name;
              process_id = $current.ProcessId; process_name = $processName }
}

if ($request.action -eq 'inspect' -and $request.window_id -eq 0) {
    $windows = @()
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $children = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($element in $children) {
        try {
            $current = $element.Current
            if ($current.ProcessId -eq $request.jarvis_pid -or $current.NativeWindowHandle -eq 0) { continue }
            if (-not [JarvisDesktop]::IsWindowVisible([IntPtr]$current.NativeWindowHandle)) { continue }
            $windows += Get-WindowEntry $element
            if ($windows.Count -ge 80) { break }
        } catch {}
    }
    @{ windows = $windows; foreground_window_id = [JarvisDesktop]::GetForegroundWindow().ToInt64() } | ConvertTo-Json -Depth 6 -Compress
    exit 0
}

$windowHandle = [IntPtr][long]$request.window_id
if (-not [JarvisDesktop]::IsWindow($windowHandle)) { throw 'La finestra non esiste piu. Rileggi inspect_desktop.' }
[uint32]$ownerProcess = 0
$null = [JarvisDesktop]::GetWindowThreadProcessId($windowHandle, [ref]$ownerProcess)
if ($ownerProcess -eq $request.jarvis_pid) { throw 'Gli strumenti non possono controllare JARVIS o le sue conferme.' }
if ($request.expected_process_id -and $ownerProcess -ne $request.expected_process_id) { throw 'La finestra e cambiata. Rileggi inspect_desktop.' }
$window = [System.Windows.Automation.AutomationElement]::FromHandle($windowHandle)
$entry = Get-WindowEntry $window

function Get-Controls($element) {
    $queue = [System.Collections.Generic.Queue[object]]::new()
    $queue.Enqueue(@{ element = $element; depth = 0 })
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $count = 0
    while ($queue.Count -gt 0 -and $count -lt 160) {
        $item = $queue.Dequeue()
        if ($item.depth -ge 7) { continue }
        $child = $walker.GetFirstChild($item.element)
        while ($null -ne $child -and $count -lt 160) {
            $count++
            Write-Output $child
            $queue.Enqueue(@{ element = $child; depth = $item.depth + 1 })
            $child = $walker.GetNextSibling($child)
        }
    }
}

if ($request.action -eq 'inspect') {
    $controls = @()
    foreach ($element in (Get-Controls $window)) {
        try {
            $current = $element.Current
            if ($current.IsOffscreen) { continue }
            $bounds = $current.BoundingRectangle
            $value = ''
            $pattern = $null
            if (-not $current.IsPassword -and $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) {
                $value = $pattern.Current.Value
                if ($value.Length -gt 500) { $value = $value.Substring(0, 500) }
            }
            $label = $current.Name
            if ($label.Length -gt 500) { $label = $label.Substring(0, 500) }
            $controls += @{ control_id = ($element.GetRuntimeId() -join '.'); name = $label;
                            type = $current.ControlType.ProgrammaticName; enabled = $current.IsEnabled;
                            password = $current.IsPassword; value = $value;
                            x = [int]($bounds.X + $bounds.Width / 2); y = [int]($bounds.Y + $bounds.Height / 2) }
        } catch {}
    }
    @{ window = $entry; controls = $controls; limit = 160 } | ConvertTo-Json -Depth 7 -Compress
    exit 0
}

switch ($request.action) {
    'minimize' { $null = [JarvisDesktop]::ShowWindow($windowHandle, 6) }
    'maximize' { $null = [JarvisDesktop]::ShowWindow($windowHandle, 3) }
    'restore' { $null = [JarvisDesktop]::ShowWindow($windowHandle, 9) }
    'close' {
        if (-not [JarvisDesktop]::PostMessage($windowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)) { throw 'Chiusura rifiutata da Windows.' }
    }
    default {
        [JarvisDesktop]::Focus($windowHandle)
        Start-Sleep -Milliseconds 100
        if ([JarvisDesktop]::GetForegroundWindow() -ne $windowHandle) { throw 'Windows non ha consentito il focus. Seleziona la finestra e riprova.' }
        switch ($request.action) {
            'focus' {}
            'click' {
                if ($request.control_id) {
                    $matches = @(Get-Controls $window | Where-Object { ($_.GetRuntimeId() -join '.') -eq $request.control_id })
                    if ($matches.Count -ne 1) { throw 'Il controllo non e piu disponibile. Rileggi inspect_desktop.' }
                    $control = $matches[0]
                    if ($control.Current.IsPassword) { throw 'Non e consentita interazione con campi password.' }
                    $pattern = $null
                    if ($control.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
                        $pattern.Invoke()
                    } else {
                        $rect = $control.Current.BoundingRectangle
                        if ($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0 -or $control.Current.IsOffscreen) { throw 'Controllo non visibile.' }
                        [JarvisDesktop]::Click([int]($rect.X + $rect.Width/2), [int]($rect.Y + $rect.Height/2))
                    }
                } else {
                    $rect = $window.Current.BoundingRectangle
                    if (-not $rect.Contains([double]$request.x, [double]$request.y)) { throw 'Coordinate esterne alla finestra richiesta.' }
                    [JarvisDesktop]::Click([int]$request.x, [int]$request.y)
                }
            }
            'type_text' {
                $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
                if ($null -eq $focused -or $focused.Current.IsPassword) { throw 'Campo non disponibile o protetto.' }
                if ([JarvisDesktop]::GetForegroundWindow() -ne $windowHandle) { throw 'Il focus e cambiato. Input annullato.' }
                [JarvisDesktop]::Text($windowHandle, [string]$request.text)
            }
            'press_keys' {
                $mapping = @{ CTRL = 17; ALT = 18; SHIFT = 16; WIN = 91; ENTER = 13; TAB = 9; ESC = 27; SPACE = 32;
                              BACKSPACE = 8; DELETE = 46; HOME = 36; END = 35; LEFT = 37; UP = 38; RIGHT = 39; DOWN = 40; PAGEUP = 33; PAGEDOWN = 34 }
                $codes = @()
                foreach ($token in ($request.keys -split '\+')) {
                    if ($mapping.ContainsKey($token)) { $codes += $mapping[$token] }
                    elseif ($token -match '^F([1-9]|1[0-2])$') { $codes += 111 + [int]$token.Substring(1) }
                    elseif ($token -match '^[A-Z0-9]$') { $codes += [int][char]$token }
                    else { throw 'Tasto non valido.' }
                }
                [JarvisDesktop]::Keys([int[]]$codes)
            }
            default { throw 'Azione desktop non riconosciuta.' }
        }
    }
}
@{ message = "Input o richiesta '$($request.action)' consegnati a Windows per '$($entry.title)'. Verifica lo stato con inspect_desktop.";
   window_id = $request.window_id; action = $request.action; input_delivered = $true; effect_verified = $false } | ConvertTo-Json -Compress
