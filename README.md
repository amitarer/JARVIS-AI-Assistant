# JARVIS — assistente Windows con Qwen locale

JARVIS usa **Qwen 3.5 9B tramite Ollama**, chat e memoria SQLite, strumenti Windows autorizzati, attivazione locale «Jarvis» con openWakeWord e overlay animato. Richiede Windows 11 e la `.venv` Python 3.12 già presente.

## Avvio

Il pulsante **Modello** mostra lo stato locale Ollama verificato, con contesto
nativo e runtime distinti, capacità e memoria del modello. Il primo modulo
di fusione e i suoi limiti sono descritti in [FUSION_PLAN.md](FUSION_PLAN.md)
e nel [report di verifica](docs/fusion-module-1.md).

Per il sistema **Codex + Ruflo**, aprire `Sviluppo_JARVIS.bat`:
mostra agenti realmente eseguiti, test, revisione, risorse e STOP sviluppo.
Il primo ciclo isolato è collaudato; l'esecuzione continua resta disattivata.
Vedi [configurazione e risultati](docs/development-system.md).

Fare doppio clic su **`Avvia_JARVIS.bat`** nella cartella del progetto. Il launcher usa la `.venv`, apre JARVIS e verifica o avvia Ollama in background, senza lasciare aperto il terminale. Funziona anche da un collegamento e con spazi nel percorso. Non scarica modelli; eventuali errori del launcher vengono mostrati in una finestra e registrati, quando possibile, in `data/logs/startup.log`. Ollama avviato dal launcher resta disponibile anche dopo l'uscita da JARVIS.

Per aprire subito la dashboard usare `Avvia_JARVIS.bat --dashboard`; per partire senza microfono usare `Avvia_JARVIS.bat --no-microphone`.

La dashboard mostra ora il **nucleo ambra 3D**, con zoom e selezione dei nodi;
la stessa scena appare nell'overlay durante ascolto e risposta vocale reali.
Il pulsante **Agenti** apre la supervisione Codex + Ruflo. Un secondo avvio
riporta in primo piano JARVIS già aperto, senza duplicare microfono e memoria.
L'avvio di Ollama avviene fuori dal thread grafico: la finestra resta utilizzabile.
Qwen e il riconoscimento vocale vengono preparati in anticipo; le domande brevi
usano una sola inferenza. Vedi [misure e verifiche di reattività](docs/latency-optimization.md).

In alternativa, dalla cartella del progetto con Ollama già disponibile:

```powershell
.\.venv\Scripts\pythonw.exe -m jarvis
```

JARVIS mostra la dashboard, con il microfono attivo e un'icona vicino all'orologio.
Per avviarlo soltanto nel tray usare `Avvia_JARVIS.bat --background`.
Non servono privilegi amministrativi, Node.js o modifiche ai servizi Windows
per l'assistente. Ollama deve essere disponibile su `http://127.0.0.1:11434`
con `qwen3.5:9b` installato. JARVIS verifica la disponibilità; non scarica modelli
e non sostituisce un errore con risposte AI simulate.

## Chat e voce

- Scrivere una domanda naturale in italiano: Qwen risponde in streaming con un tono professionale e conciso.
- Il thinking è disabilitato con `think: false`; eventuali campi o tag di ragionamento vengono filtrati. Il TTS legge soltanto la risposta finale delle richieste vocali.
- Il microfono si attiva all'avvio. Attendere lo stato pronto nell'icona e pronunciare **«Jarvis»**, seguito dalla richiesta: compare l'overlay trasparente con il cervello. La trascrizione è locale.
- JARVIS annuncia a voce l'intenzione, nasconde l'overlay e avvia lo strumento autorizzato. L'esito può essere letto a voce senza riaprire l'overlay.
- Le risposte vocali terminano con **«Ha bisogno d'altro, signore?»**. JARVIS resta in ascolto per 30 secondi senza ripetere il nome, con overlay nascosto; «no, grazie» o «basta» tornano all'attesa di **«Jarvis»**. La conversazione continua si può disattivare nelle impostazioni.
- La voce resta Microsoft Cosimo. Il riconoscimento è sospeso durante il parlato. STOP o Esc interrompono generazione e audio, senza annullare gli effetti Windows già completati.
- **Overlay** mostra un'anteprima manuale del cervello. Prima delle azioni Windows, il worker attende che l'overlay sia nascosto. Le conferme restano visibili e interattive.

L'icona vicino all'orologio permette di aprire la conversazione, disattivare completamente il microfono, fermare l'attività o uscire. Chiudere la dashboard con X la nasconde mantenendo l'ascolto. **Ctrl+Alt+Pausa** è lo STOP globale quando la scorciatoia è disponibile. `--dashboard` mostra la finestra all'avvio; `--no-microphone` avvia con acquisizione disabilitata. Se il tray non è disponibile, resta visibile la dashboard con i controlli.

Non attivare insieme il microfono della finestra principale e quello del test autonomo. Durante il confronto vocale, disattivare il microfono di un'eventuale altra finestra che ascolti «Jarvis».

## Strumenti realmente disponibili

| Operazione | Comportamento |
|---|---|
| `get_current_datetime` | Ora/data Windows, giorno italiano, fuso e offset UTC, letti di nuovo a ogni richiesta |
| `get_system_information` | Windows, versione, architettura, nome computer e uptime |
| `get_hardware_information` | CPU, GPU, utilizzo CPU campionato, RAM, dischi e alimentazione |
| `get_memory_information`, `get_disk_information`, `get_battery_status` | Letture mirate di RAM, spazio locale e batteria |
| `get_process_information`, `get_open_applications` | Processi dell'utente, risorse, finestre e finestra attiva |
| `list_applications` | Cerca le app installate nel menu Start, comprese quelle Microsoft Store |
| `open_application` | Apre app per nome, ID del menu Start o percorso completo `.exe`, senza argomenti |
| `open_resource` | Apre siti tramite URL validato e alias in `config/websites.json`, cartelle, documenti e pannelli `ms-settings:` |
| `inspect_files` | Elenca cartelle e legge anteprime di file di testo UTF-8 |
| `inspect_desktop` | Legge finestre, controlli accessibili e coordinate; esclude i valori dei campi password |
| `desktop_action` | Focus, minimizza, massimizza, ripristina; con conferma: chiude, clicca, scrive testo e invia scorciatoie |
| `read_operations` | Consulta azioni, stati e verifiche del registro locale |
| Cancella cronologia | Conferma concreta; conserva preferenze e log tecnici |
| Ripristina preferenze | Conferma concreta; conserva le conversazioni |

`/aiuto`, `/app` e `/apri chrome` restano comandi locali espliciti. Anche le richieste naturali passano dal registro strumenti e dalla policy. Gli esiti usano i risultati degli strumenti: un processo creato non viene presentato come finestra verificata. Esempi: «Che ore sono?», «Che giorno è oggi?», «Quali CPU e GPU ho?», «Quanta RAM è disponibile?», «Quanto spazio libero c'è?», «Apri Chrome».

La **Fase 1 — System Information** è implementata senza nuove dipendenze. Qwen seleziona letture strutturate validate dal registro; i dati di sistema vengono formulati direttamente dalle osservazioni Windows per evitare numeri inventati o valori riusati dalla cronologia. Nella 0.4.2 il selettore considera soltanto la richiesta corrente e distingue le domande di sistema dalle richieste semplici di avvio app: queste ultime eseguono direttamente `open_application`, anche quando Chrome era già aperto. `run_powershell` non è registrato nell'app e non viene offerto al modello: il backend PowerShell serve soltanto adapter predefiniti. Creazione/modifica di file attraverso un File Manager strutturato e le fasi successive restano da approvare. Dettagli e verifiche in [System Information](docs/system-information.md).

Il controllo grafico usa Windows UI Automation: la disponibilità dei controlli dipende dall'app. JARVIS deve leggere le finestre prima di agire e rileggere lo stato dopo l'input. Le sue finestre di conferma non sono controllabili dagli strumenti. Gli adapter Windows usano i permessi dell'utente corrente; non superano UAC, password o permessi Windows. Non ci sono integrazioni automatiche con account email o altri servizi autenticati. STOP interrompe l'attività e l'eventuale collector PowerShell in corso, ma non annulla effetti già avvenuti o processi esterni già avviati.

Dalla 0.4.3 anche i siti passano dal selettore strutturato: ad esempio «chatgbt.com» viene associato a `https://chatgpt.com/`, senza digitazione tramite tastiera. I domini pronunciati non presenti nel catalogo richiedono la conferma dell'indirizzo esatto. Il riconoscimento vocale usa un beam più ampio e nomi di app/siti come contesto, ma può ancora trascrivere male: il catalogo corregge solo varianti configurate, senza indovinare domini sconosciuti.

## Sessione autonoma con ChatGPT

Dire **«Jarvis, inizia a chattare con ChatGPT fino a quando non ti dico stop»**, eventualmente aggiungendo un argomento. Una conferma iniziale autorizza la conversazione e gli invii successivi su quel compito. JARVIS apre Chrome con un profilo dedicato, scrive, clicca Invia, verifica il messaggio e attende una risposta completata prima di proseguire. Non chiede conferma per ogni tasto della sessione.

La sessione continua fino a **STOP** senza il limite ordinario di 10 passaggi o 180 secondi; ogni operazione rimane limitata nel tempo. Si può pronunciare **«stop»**, scrivere **STOP** nella dashboard, usare il pulsante STOP oppure **Ctrl+Alt+Pausa**. Durante la sessione il microfono, se attivo, interpreta soltanto comandi di arresto. Non legge ad alta voce ogni scambio, così può ascoltare STOP. Gli invii già completati restano registrati.

L'accesso a ChatGPT va completato manualmente una volta nel profilo dedicato. Login, CAPTCHA, bozze esistenti, limiti del servizio o un invio incerto sospendono le azioni: non vengono aggirati e il clic non viene ripetuto alla cieca. La sessione autorizza soltanto quella conversazione, senza accesso a file, altre chat, credenziali o altri siti. Browser e controlli Windows riusano gli strumenti presenti; non sono stati installati Playwright, pacchetti o modelli nuovi. Dettagli in [autonomia ChatGPT](docs/autonomous-chat.md).

Dopo questo aggiornamento uscire da JARVIS tramite il menu dell'icona e riaprire `Avvia_JARVIS.bat`: il processo già aperto continua a usare il vecchio codice. La nuova versione è **0.7.0** e compare anche in `data/runtime.json`.

La 0.7.0 recupera gli errori di lettura attraverso scelte strutturate di Qwen: ad esempio può rileggere la cartella e trovare un documento rinominato. Non ripete automaticamente azioni con esito incerto. Tiene memoria dei passaggi del compito, abbrevia le osservazioni vecchie e arresta le letture ripetute senza nuovi risultati. Dopo un input desktop consulta di nuovo lo stato; durante i compiti con strumenti resta disponibile STOP vocale. Dettagli in [autonomia adattiva](docs/adaptive-agent.md).

## Ricerca autonoma e consegna PDF

Esempio: **«Fai una ricerca con ChatGPT e Google Documenti sui vantaggi e i limiti del fotovoltaico domestico e consegnami un PDF con le fonti»**. JARVIS prepara il piano, raccoglie e legge pagine pubbliche, controlla la pertinenza, scrive il rapporto con riferimenti e produce un PDF verificato. Una conferma iniziale copre il lavoro indicato; STOP resta disponibile. Nella dashboard compare **Apri PDF verificato** e i file sono conservati in `data/reports/`.

ChatGPT e Google Documenti richiedono il primo accesso manuale nel profilo Chrome dedicato. Il controllo Google verifica il testo effettivamente esportato prima di consegnare il PDF; il percorso autenticato con entrambi i servizi resta da provare dopo il login. La ricerca pubblica e il PDF locale sono stati provati con Qwen e fonti reali. Se Google Search richiede verifiche, viene usata la ricerca pubblica MediaWiki con riferimenti esterni: il rapporto segnala questa copertura parziale. Dettagli e verifiche in [ricerca e PDF](docs/research.md).

## Test indipendenti

L’anteprima del nucleo organico ambra, basato sul video locale, si apre con **`Anteprima_Neurale.bat`**
oppure `.\.venv\Scripts\python.exe -m jarvis --neural-preview`. Include zoom fino
a 6×, selezione dei neuroni e informazioni su coordinate e sinapsi del prototipo.
È una simulazione grafica separata: non avvia Ollama o microfono e non sostituisce
l’overlay operativo. Il pulsante **Ascolta Cosimo · PCM reale** prova la reattività
al campione vocale locale; **Solo nucleo / Tab** nasconde i controlli. Analisi del
filmato e piano operativo: [esperienza di riferimento](docs/reference-driven-experience.md).
Comandi e verifiche: [anteprima neurale](docs/neural-preview.md).

```powershell
.\.venv\Scripts\python.exe -m jarvis --voice-test
.\.venv\Scripts\python.exe -m jarvis --voice-compare
```

Il primo abilita esplicitamente il microfono per provare wake word, overlay e voce senza AI. Il secondo permette di ascoltare campioni senza acquisire audio o cambiare la voce attiva. Chatterbox e Kokoro non sono installati: aggiungere modelli e dipendenze richiede autorizzazione.

## Configurazione e dati

- `config/defaults.json`: Ollama, timeout e valori vocali iniziali.
- `config/applications.json`: nomi, percorsi espliciti e `aliases` facoltativi per nomi alternativi o trascrizioni vocali. Le voci hanno priorità sulle app rilevate dal menu Start; i nomi esatti reali hanno priorità sugli alias. Le modifiche vengono rilette a ogni ricerca/apertura; il catalogo Start si aggiorna ogni 60 secondi. Per Chrome sono configurati anche crom, crome, microm e micron.
- `config/websites.json`: URL HTTPS e nomi alternativi di siti conosciuti. Il sito ChatGPT è verificato dalla [pagina ufficiale](https://openai.com/chatgpt/overview/). Nessuna lettura di password o cookie del browser.
- `.env`: override facoltativi, esclusi da Git e documentati in `.env.example`. Nessuna API key richiesta per Ollama o openWakeWord.
- `data/jarvis.sqlite3`: conversazioni, preferenze, attività e operazioni, **senza cifratura**. Non inserire credenziali in chat.
- `data/logs/operations.jsonl`: metadati operativi con rotazione, senza testo delle conversazioni o reasoning.
- `assets/wakeword/Jarvis_20260313_215039.onnx`: classificatore personalizzato.
- `data/models/openwakeword` e `data/models/whisper-small`: modelli locali già predisposti.

Le preferenze SQLite prevalgono sui valori iniziali. La configurazione iniziale segue l'ordine: variabili d'ambiente, `.env` del progetto, `config/defaults.json`. L'endpoint Ollama accetta soltanto loopback. L'app non espone Ollama in rete né ne modifica il servizio.

Installare dipendenze esclusivamente nella `.venv`, dopo autorizzazione. Non usare Python globale o Python 3.13. L'app parte dai sorgenti; il packaging Windows resta una fase successiva.

## Verifica

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B scripts/verify_system_information.py --with-ollama
.\.venv\Scripts\python.exe -B scripts/verify_qwen.py
.\.venv\Scripts\python.exe -B scripts/verify_pc_control.py
.\.venv\Scripts\python.exe -m pip check
```

Il test Qwen usa il server reale e un database separato sotto `data/verification`. Aggiungere `--open-notepad` per includere l'apertura reale di Blocco note. `scripts/verify_qwen_ui.py` verifica UI, Qwen e TTS con audio muto e microfono spento.

`verify_pc_control.py` apre una finestra di prova dedicata, verifica clic, testo Unicode, scorciatoie, un comando PowerShell innocuo e chiusura; approva esclusivamente le azioni della prova e salva `data/verification/pc-control.json`. Non interagisce con altre finestre.

`scripts/verify_application_routing.py` verifica con Qwen reale aperture, domande, conversazione e negazioni dopo una cronologia con orario e finestre. L'opzione `--open-chrome` verifica anche due avvii reali di Chrome dal controller. Il database è separato e il report è `data/verification/application-routing.json`.

`scripts/verify_voice_followup.py` sintetizza localmente campioni Cosimo senza riprodurli, esegue i modelli wake word e Whisper reali e verifica che Qwen risolva il sito trascritto all'URL configurato. Non apre il microfono: è una verifica su voce sintetica, non una certificazione della pronuncia dell'utente. Report: `data/verification/voice-followup.json`. Le prove sui siti con Qwen e apertura reale sono registrate in `data/verification/website-voice.json`.

`scripts/verify_autonomous_chat.py` usa Chrome e Qwen reali con una pagina locale di prova: tre invii, tre risposte, una conferma iniziale, arresto e nessun invio successivo. Non manda messaggi al servizio ChatGPT. I dati del test restano in una directory dedicata sotto `data/test-runs`; il report è `data/verification/autonomous-chat.json`. L'interfaccia reale di ChatGPT è stata controllata in sola lettura e richiede il primo accesso manuale: report `data/verification/chatgpt-browser-readiness.json`.

Dettagli: [controllo Windows](docs/pc-control.md), [modalità background](docs/background.md), [integrazione Ollama](docs/ollama-integration.md), [diagnosi e confronto vocale](docs/voice-quality.md), [architettura della Foundation](docs/architecture.md).
