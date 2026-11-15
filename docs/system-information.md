# Fase 1 — System Information (0.4.1)

Correzione 0.4.2: il selettore iniziale usa soltanto l'ultima richiesta, con un tipo esplicito (`system_information`, `open_application`, `other`). Il precedente selector di sole letture poteva scegliere orario e finestre per un comando di apertura. Ora una richiesta semplice di avvio produce una `ToolCall` per `open_application`, che attraversa il registro e restituisce l'esito reale senza una risposta libera «sto aprendo» o «è già aperto» priva di esecuzione. Le richieste miste continuano nel ciclo ordinario. Gli alias delle applicazioni sono configurabili e gestiscono le trascrizioni osservate «microm» e «micron» per Chrome senza regole rigide sul testo del comando.

Il progetto esistente è stato verificato in `C:\Users\VGgot\Desktop\JARVIS`: il percorso `Documents\JARVIS` del documento di richiesta non è presente. Python della `.venv` è 3.12.10; Ollama risponde come 0.33.3 e dispone di `qwen3.5:9b`. La suite iniziale di 74 test passa e SQLite supera `quick_check`. UI, worker, overlay, flusso vocale e registro esistevano già; questa fase non rifà questi componenti. La verifica iniziale ha osservato il microfono disattivato: non viene dichiarata una nuova prova della wake word o dell'audio reale.

`jarvis/infrastructure/system_information.py` contiene `SystemInformation`. Non importa `psutil`, non installa pacchetti e non apre terminali visibili. Le interrogazioni PowerShell/CIM sono codice fisso del repository; i filtri del modello sono dati JSON in una variabile d'ambiente.

| Strumento | Letture e origine |
|---|---|
| `get_current_datetime` | Orologio Win32 preciso, conversione al fuso Windows, data/ora ISO, giorno e mese in italiano, ID fuso e offset UTC |
| `get_system_information` | CIM `Win32_OperatingSystem`, hostname e `GetTickCount64` |
| `get_hardware_information` | CIM CPU/GPU, utilizzo CPU misurato per circa 200 ms, RAM, dischi e batteria |
| `get_memory_information` | `GlobalMemoryStatusEx`, quantità in byte/GiB e utilizzo percentuale |
| `get_disk_information` | Drive locali, `GetDiskFreeSpaceExW`, spazio libero totale e disponibile all'utente |
| `get_battery_status` | `GetSystemPowerStatus`, assenza distinta da stato/carica sconosciuti |
| `get_process_information` | Processi dell'utente nella sessione corrente, ownership SID verificata, memoria e CPU campionata |
| `get_open_applications` | Bridge UI Automation esistente, finestre visibili e finestra attiva |

Le letture sono automatiche e di sola lettura. Ogni strumento controlla annullamento e deadline e ha un limite di 20 secondi; il selector ha un limite di 30 secondi, sempre entro la deadline complessiva. Le query CIM hanno inoltre timeout locali. STOP termina il collector esterno quando presente. Le chiamate native già entrate nel sistema operativo non sono interrompibili a metà; le unità di rete non vengono interrogate automaticamente.

Non vengono lette righe di comando, variabili d'ambiente dei processi, password, cookie o token. SID dell'utente e owner SID servono soltanto al filtro e non sono inclusi nei risultati. I processi inaccessibili o terminati durante il campionamento sono conteggiati esplicitamente. L'assenza di risultati non è prova dell'assenza di processi non accessibili. La VRAM è `null`: il campo CIM `AdapterRAM` è a 32 bit e non è usato per attribuire una capacità falsa a una GPU oltre 4 GB.

## Integrazione con il modello

Un primo test nativo con Qwen ha mostrato un limite reale: nei turni successivi il modello talvolta rispondeva direttamente, inventando quantità di RAM o disco. Un semplice prompt «usa lo strumento» non è stato sufficiente.

Per le domande sui dati attuali del PC, Qwen seleziona ora al massimo tre letture tramite un [formato JSON vincolato nell'API Ollama](https://docs.ollama.com/api/chat). Il codice valida nomi, tipi, limiti e duplicati, costruisce `ToolCall` e attraversa il registro e la policy già presenti. Non ci sono regole di esecuzione basate su frasi come `if 'apri chrome' in text`. Il selector non può proporre strumenti generici o codice da eseguire. Dalla 0.4.2 può selezionare anche un singolo avvio tramite lo strumento registrato `open_application`. La selezione viene eseguita di nuovo a ogni turno usando la richiesta corrente, senza includere risposte vecchie nel messaggio del classificatore.

`ToolResult` conserva l'osservazione JSON e può includere un `public_message` formulato dal codice a partire dai valori misurati. Per queste letture la risposta finale usa quel testo, senza una generazione libera che possa sostituire i numeri. Il normale ciclo di tool calling resta disponibile per le altre richieste. Una classificazione non pertinente del modello rimane un limite possibile; le selezioni strutturalmente non valide vengono rifiutate senza esecuzione.

`run_powershell` è stato tolto dal registro dell'app: il modello non può chiedere l'esecuzione di testo PowerShell generato. La classe legacy resta soltanto per test isolati; gli adapter interni usano script predefiniti. File Manager, browser Playwright e il motore autonomo completo non vengono introdotti in questa fase.

Letture ed evidenze sono registrate in SQLite con timestamp UTC e sorgente. La risposta finale continua sul percorso `Controller → TaskWorker → Presenter → TTS` esistente; non viene letto il JSON del selector o lo stream privato. Le operazioni restano nel worker, con STOP disponibile.

## Verifica riproducibile

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/verify_system_information.py --with-ollama
```

Lo script confronta orologio, fuso, OS, CPU, GPU, RAM e dischi con letture Windows indipendenti. I valori dinamici hanno tolleranze esplicite per il tempo intercorso tra campioni. Verifica anche processi, finestre, rifiuto di parametri e shell generica, STOP reale e persistenza SQLite. La prova Qwen comprende cinque richieste consecutive: ora, data, CPU/GPU, RAM disponibile e spazio disco. Nessuna applicazione viene aperta e un controllo prima dell'esecuzione ammette soltanto letture; nessun file personale viene modificato.

Report: `data/verification/system-information.json`. Il database è un file `system-info-<id>.sqlite3` dedicato sotto `data/verification`, separato dalla memoria personale. I test unitari usano directory temporanee sotto `data/test-runs`.

La Fase 1 si ferma qui. La Fase 2 — Application Control richiede l'approvazione dell'utente come indicato nella richiesta.
