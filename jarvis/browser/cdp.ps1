# Fixed loopback CDP transport. It never reads cookies, credentials or browser storage.
$request = $env:JARVIS_TOOL_INPUT | ConvertFrom-Json
$uri = [Uri]$request.endpoint
if ($uri.Scheme -ne 'ws' -or $uri.Host -ne '127.0.0.1') { throw 'Endpoint browser non locale.' }
$socket = [System.Net.WebSockets.ClientWebSocket]::new()
$cancellation = [System.Threading.CancellationTokenSource]::new([int]$request.timeout_ms)
try {
    $null = $socket.ConnectAsync($uri, $cancellation.Token).GetAwaiter().GetResult()
    $packet = @{ id = 1; method = $request.method; params = $request.params } | ConvertTo-Json -Depth 25 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($packet)
    $segment = [ArraySegment[byte]]::new($bytes)
    $null = $socket.SendAsync($segment, [Net.WebSockets.WebSocketMessageType]::Text, $true, $cancellation.Token).GetAwaiter().GetResult()
    while ($socket.State -eq [Net.WebSockets.WebSocketState]::Open) {
        $stream = [IO.MemoryStream]::new()
        try {
            do {
                $buffer = New-Object byte[] 16384
                $read = $socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cancellation.Token).GetAwaiter().GetResult()
                if ($read.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) { throw 'Connessione browser chiusa.' }
                $stream.Write($buffer, 0, $read.Count)
                if ($stream.Length -gt 1000000) { throw 'Risposta browser oltre il limite.' }
            } while (-not $read.EndOfMessage)
            $text = [Text.Encoding]::UTF8.GetString($stream.ToArray())
            $message = $text | ConvertFrom-Json
            if ($message.id -eq 1) {
                [Console]::WriteLine($text)
                break
            }
        } finally { $stream.Dispose() }
    }
} finally {
    $socket.Abort()
    $socket.Dispose()
    $cancellation.Dispose()
}
