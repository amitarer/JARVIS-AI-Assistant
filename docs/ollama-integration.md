# Qwen 3.5 9B — integrazione locale

Il provider principale è `qwen3.5:9b`, su `http://127.0.0.1:11434`. JARVIS usa l'API HTTP locale, senza SDK aggiuntivi, download di modelli o modifiche al servizio Ollama.

## Conversazione e ragionamento

Ogni chiamata chat invia `stream: true`, `think: false`, lingua e personalità italiane nel prompt di sistema. Il preflight consulta `/api/tags` e `/api/show` per verificare modello, capacità e metadati del thinking. Per modelli che non possono disabilitarlo, Ollama può usare il livello minimo supportato: il filtro rimane attivo indipendentemente dal controllo.

Solo `message.content` alimenta la risposta pubblica. I campi `thinking`, `reasoning`, `reasoning_content` e `analysis` sono scartati; per diagnostica si conserva soltanto il numero di caratteri scartati. Non vengono inoltrati a UI, memoria, log o voce. Un filtro incrementale rimuove blocchi `<think>`, `<analysis>` e `<reasoning>`, compresi tag spezzati tra frammenti. Blocchi non chiusi vengono scartati. Il motore vocale applica un ulteriore filtro al testo ricevuto.

La chat visualizza il contenuto finale in generazione in un'area streaming separata. Il TTS riceve soltanto l'evento di risposta conclusa, dopo la verifica e la scrittura in SQLite. Non legge i frammenti o il ragionamento. Limiti ordinari: 1024 token generati, contesto di 16384 token, timeout di 180 secondi. La configurazione 0.4 consente 10 passaggi del modello per le operazioni con più strumenti.

L'adapter non può riconoscere ogni ragionamento che un modello inserisca impropriamente come prosa non marcata. Il confine verificato è il protocollo dei campi Ollama e dei tag espliciti; non è una classificazione semantica universale del testo libero.

## Memoria e azioni

Il repository SQLite conserva messaggi utente e risposte finali. I turni recenti vengono passati a Qwen con un budget di testo limitato. `read_operations` consulta azioni, stati ed evidenze passate: una conversazione non costituisce prova di esecuzione.

Le chiamate agli strumenti sono validate soltanto dopo il completamento dello stream. Strumenti sconosciuti e parametri non validi sono rifiutati. Le applicazioni vengono risolte nel catalogo Windows o da un percorso `.exe` esplicito: non è più necessario aggiungere ogni app al file di configurazione. Policy e conferme restano applicate. Vedere [controllo Windows](pc-control.md).

Gli esiti delle azioni eseguite usano direttamente `ToolResult`: il modello non può aggiungervi verifiche inventate. Nell'apertura di applicazioni, `process_created=true` attesta il processo e `window_verified=false` rimane esplicito. Prima dell'esecuzione il worker attende che la GUI nasconda l'overlay. Nelle richieste vocali viene prima pronunciata un'intenzione breve.

Un controllo conservativo intercetta comuni dichiarazioni italiane di completamento senza strumenti eseguiti, come «Ho aperto Chrome» o «Email inviata». Non è una prova semantica per qualunque lingua o formulazione; il registro resta la fonte autorevole. Le funzioni assenti non vengono eseguite tramite testo generato.

## Voce e overlay

Il modello openWakeWord personalizzato e il renderer restano quelli esistenti. La finestra principale collega acquisizione, wake word, trascrizione locale, controller Ollama, risposta finale e TTS.

```powershell
.\.venv\Scripts\python.exe -m jarvis
```

L'avvio ordinario ora è in background con microfono attivo: attendere «in attesa di Jarvis» nell'icona vicino all'orologio, poi pronunciare «Jarvis» e la richiesta. Il click sull'icona apre la dashboard. **Ascolta** apre manualmente un turno; **Overlay** mostra un'anteprima dichiarata. Le impostazioni permettono di scegliere dispositivo, voce, sensibilità e conversazione continua facoltativa. Vedere [modalità background](background.md).

La trascrizione usa `whisper-small` già presente in `data/models`, senza download a runtime. La voce resta Cosimo, con il percorso audio corretto. Nessun nuovo TTS viene installato o scelto. Durante il parlato il riconoscimento è sospeso e i buffer svuotati; al termine si scartano 500 ms di eco. Dalla 0.4.3 le risposte vocali chiedono «Ha bisogno d'altro, signore?» e la conversazione continua per 30 secondi è attiva per impostazione iniziale. STOP interrompe generazione e parlato, senza annullare effetti già completati. Durante la voce usare STOP, Esc nella dashboard oppure Ctrl+Alt+Pausa globale se registrato.

`--voice-test` e `--voice-compare` conservano i test indipendenti dall'AI. Non attivare contemporaneamente più finestre sullo stesso microfono.

## Esiti reali del 14 novembre 2026

`scripts/verify_qwen.py --open-notepad` ha eseguito chiamate HTTP reali, con un database separato sotto `data/verification`, senza conversazioni di prova nella memoria personale.

- Codice casuale nuovo: risposta corretta, 24 frammenti finali, 3,28 s inclusa la prima preparazione.
- Domanda successiva sul codice: recupero dalla cronologia SQLite, 10 frammenti, 0,34 s.
- Domanda su una mail: registro consultato e risposta negativa; nessuna mail inviata o inventata.
- Applicazione non autorizzata: attività `failed`, nessuna risposta di successo.
- Blocco note: chiamata `open_application` richiesta dal modello, processo avviato e PID registrato, finestra non dichiarata verificata. Il programma resta aperto.
- Tutte le chiamate hanno richiesto `think: false`; zero caratteri di reasoning ricevuti in questi test.

`scripts/verify_qwen_ui.py` ha verificato GUI → Qwen reale → TTS: 37 frammenti, un'unica risposta finale passata al motore, PCM prodotto, STOP disponibile e rilascio audio riuscito. Microfono spento e audio muto: non è una prova della pronuncia dell'utente. STT locale verificato separatamente su un WAV italiano esistente, in circa 1,78 s, senza installazioni.

Report: `data/verification/qwen-integration.json`, `qwen-ui-verification.json`, `qwen-ui.png`.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/verify_qwen.py
.\.venv\Scripts\python.exe -B scripts/verify_qwen_ui.py
```

Aggiungere `--open-notepad` alla seconda riga soltanto per includere l'apertura reale dell'applicazione.

Fonti ufficiali: [thinking](https://docs.ollama.com/capabilities/thinking), [streaming](https://docs.ollama.com/capabilities/streaming), [tool calling](https://docs.ollama.com/capabilities/tool-calling).
