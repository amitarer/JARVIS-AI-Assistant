# Fixed read-only queries. Model parameters are data, never executable script.
$request = $env:JARVIS_TOOL_INPUT | ConvertFrom-Json
switch ($request.section) {
    'system' {
        $system = Get-CimInstance -ClassName Win32_OperatingSystem -OperationTimeoutSec 10
        @{ os_name = $system.Caption; os_version = $system.Version; build_number = $system.BuildNumber;
           architecture = $system.OSArchitecture; boot_time_utc = $system.LastBootUpTime.ToUniversalTime().ToString('o') } |
            ConvertTo-Json -Depth 6 -Compress
    }
    'hardware' {
        $cpus = @(Get-CimInstance -ClassName Win32_Processor -OperationTimeoutSec 10 | ForEach-Object {
            @{ name = $_.Name.Trim(); manufacturer = $_.Manufacturer; physical_cores = $_.NumberOfCores;
               logical_processors = $_.NumberOfLogicalProcessors; max_clock_mhz = $_.MaxClockSpeed }
        })
        $gpuError = $null
        $gpus = @()
        try {
            $gpus = @(Get-CimInstance -ClassName Win32_VideoController -OperationTimeoutSec 10 | ForEach-Object {
                # AdapterRAM is a 32-bit WMI field: omit it rather than invent VRAM for cards above 4 GB.
                @{ name = $_.Name; driver_version = $_.DriverVersion; status = $_.Status; vram_bytes = $null }
            })
        } catch { $gpuError = 'GPU non disponibile attraverso CIM.' }
        @{ processors = $cpus; graphics_adapters = $gpus; gpu_error = $gpuError;
           gpu_vram_note = 'La VRAM non viene riportata: il campo CIM AdapterRAM non e affidabile per schede oltre 4 GB.' } |
            ConvertTo-Json -Depth 6 -Compress
    }
    'processes' {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $ownerSid = $identity.User.Value
        $session = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
        $inaccessible = 0
        $exited = 0
        $own = @()
        $all = @(Get-CimInstance -ClassName Win32_Process -Filter "SessionId = $session" -OperationTimeoutSec 10)
        foreach ($candidate in $all) {
            if ($request.query -and $candidate.Name.IndexOf([string]$request.query, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
            try {
                $owner = Invoke-CimMethod -InputObject $candidate -MethodName GetOwnerSid -OperationTimeoutSec 3
                if ($owner.ReturnValue -ne 0) { $inaccessible++; continue }
                if ($owner.Sid -ne $ownerSid) { continue }
                $process = Get-Process -Id $candidate.ProcessId -ErrorAction Stop
                $own += $process
            } catch { $inaccessible++ }
        }
        $matches = $own.Count
        $selected = @($own | Sort-Object WorkingSet64 -Descending | Select-Object -First ([int]$request.limit))
        $samples = @()
        foreach ($process in $selected) {
            try {
                $samples += @{ process = $process; start = $process.StartTime.ToUniversalTime().ToString('o');
                               cpu = $process.TotalProcessorTime.TotalSeconds; ticks = [Diagnostics.Stopwatch]::GetTimestamp() }
            } catch { $exited++ }
        }
        if ($samples.Count -gt 0) { Start-Sleep -Milliseconds 200 }
        $rows = @()
        $logicalProcessors = [Environment]::ProcessorCount
        foreach ($sample in $samples) {
            try {
                $process = $sample.process
                $process.Refresh()
                if ($process.HasExited -or $process.StartTime.ToUniversalTime().ToString('o') -ne $sample.start) { $exited++; continue }
                $elapsed = ([Diagnostics.Stopwatch]::GetTimestamp() - $sample.ticks) / [double][Diagnostics.Stopwatch]::Frequency
                $cpu = $process.TotalProcessorTime.TotalSeconds
                $cpuPercent = $null
                if ($elapsed -gt 0 -and $cpu -ge $sample.cpu -and $logicalProcessors -gt 0) {
                    $cpuPercent = [Math]::Round([Math]::Min(100, 100 * ($cpu - $sample.cpu) / ($elapsed * $logicalProcessors)), 2)
                }
                $rows += @{ process_id = $process.Id; name = $process.ProcessName; memory_working_set_bytes = $process.WorkingSet64;
                            private_memory_bytes = $process.PrivateMemorySize64; cpu_time_seconds = $cpu; cpu_percent = $cpuPercent;
                            cpu_sample_seconds = [Math]::Round($elapsed, 3); started_at_utc = $sample.start; threads = $process.Threads.Count }
            } catch { $exited++ }
        }
        @{ processes = $rows; matched = $matches; returned = $rows.Count; limit = [int]$request.limit;
           truncated = $matches -gt $request.limit; inaccessible_count = $inaccessible; exited_during_sample = $exited;
           scope = 'Utente corrente nella sessione Windows corrente; nessuna riga di comando o ambiente letti.' } |
            ConvertTo-Json -Depth 6 -Compress
    }
    default { throw 'Sezione informazioni di sistema non valida.' }
}
