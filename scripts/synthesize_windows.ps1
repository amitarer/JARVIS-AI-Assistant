# Fixed local WinRT adapter. Input is JSON data on stdin, never executable text.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($request.text.Length -gt 2000) { throw 'Speech text exceeds limit' }
$awaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Wait-WinRTOperation($operation, $resultType) {
    $task = $awaitMethod.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}
$synthesizer = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
try {
    $voices = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
    $voice = $voices | Where-Object DisplayName -eq $request.voice | Select-Object -First 1
    if ($null -eq $voice -and $request.allow_fallback) {
        $voice = $voices | Where-Object { $_.Language -eq 'it-IT' -and $_.Gender -eq 'Male' } | Select-Object -First 1
        if ($null -eq $voice) { $voice = $voices | Where-Object Language -eq 'it-IT' | Select-Object -First 1 }
    }
    if ($null -eq $voice) { throw 'Configured Italian voice unavailable' }
    $synthesizer.Voice = $voice
    $stream = Wait-WinRTOperation ($synthesizer.SynthesizeTextToStreamAsync([string]$request.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    try {
        if ($stream.Size -gt 16000000) { throw 'Speech audio exceeds limit' }
        $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
        try {
            $null = Wait-WinRTOperation ($reader.LoadAsync([uint32]$stream.Size)) ([uint32])
            $bytes = New-Object byte[] ([int]$stream.Size)
            $reader.ReadBytes($bytes)
            @{ voice = $voice.DisplayName; wav = [Convert]::ToBase64String($bytes) } | ConvertTo-Json -Compress
        } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
} finally { $synthesizer.Dispose() }
