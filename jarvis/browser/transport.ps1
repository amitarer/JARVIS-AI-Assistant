# Persistent transport for fixed CDP operations. Input is data, not executable code.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$sockets = @{}
try {
    while ($null -ne ($line = [Console]::ReadLine())) {
        $request = $null
        $cancellation = $null
        try {
            $request = $line | ConvertFrom-Json
            $uri = [Uri]$request.endpoint
            if ($uri.Scheme -ne 'ws' -or $uri.Host -ne '127.0.0.1') { throw 'Endpoint non locale.' }
            $cancellation = [Threading.CancellationTokenSource]::new([int]$request.timeout_ms)
            $socket = $sockets[$request.endpoint]
            if ($null -eq $socket -or $socket.State -ne [Net.WebSockets.WebSocketState]::Open) {
                if ($null -ne $socket) { $socket.Dispose() }
                $socket = [Net.WebSockets.ClientWebSocket]::new()
                $null = $socket.ConnectAsync($uri, $cancellation.Token).GetAwaiter().GetResult()
                $sockets[$request.endpoint] = $socket
            }
            $packet = @{ id = $request.id; method = $request.method; params = $request.params } | ConvertTo-Json -Depth 40 -Compress
            $bytes = [Text.Encoding]::UTF8.GetBytes($packet)
            $null = $socket.SendAsync([ArraySegment[byte]]::new($bytes), [Net.WebSockets.WebSocketMessageType]::Text, $true, $cancellation.Token).GetAwaiter().GetResult()
            while ($socket.State -eq [Net.WebSockets.WebSocketState]::Open) {
                $stream = [IO.MemoryStream]::new()
                try {
                    do {
                        $buffer = New-Object byte[] 65536
                        $read = $socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cancellation.Token).GetAwaiter().GetResult()
                        if ($read.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) { throw 'Connessione chiusa.' }
                        $stream.Write($buffer, 0, $read.Count)
                        if ($stream.Length -gt 24000000) { throw 'Risposta troppo grande.' }
                    } while (-not $read.EndOfMessage)
                    $text = [Text.Encoding]::UTF8.GetString($stream.ToArray())
                    $response = $text | ConvertFrom-Json
                    if ($response.id -eq $request.id) {
                        [Console]::WriteLine($text)
                        break
                    }
                } finally { $stream.Dispose() }
            }
        } catch {
            if ($request -and $sockets.ContainsKey($request.endpoint)) {
                $sockets[$request.endpoint].Abort()
                $sockets[$request.endpoint].Dispose()
                $sockets.Remove($request.endpoint)
            }
            [Console]::WriteLine((@{ id = $request.id; error = @{ message = 'Trasporto browser non riuscito.' } } | ConvertTo-Json -Compress))
        } finally { if ($cancellation) { $cancellation.Dispose() } }
    }
} finally {
    foreach ($socket in $sockets.Values) { $socket.Abort(); $socket.Dispose() }
}
