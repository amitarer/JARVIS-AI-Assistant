# JARVIS: analisi del video e piano operativo

**Aggiornamento dopo la richiesta di applicare il lavoro:** il nucleo ambra è
ora integrato nella dashboard normale e nell'overlay vocale. `run.py` e
`Avvia_JARVIS.bat` usano la nuova interfaccia: zoom e ispezione dei nodi sono
nella dashboard; ascolto, voce e ampiezza PCM arrivano dal Presenter reale.
Le 15 verifiche native sono in `data/verification/runtime-integration/verification.json`.
La regressione aggiornata supera **172 test**. Nell'avvio reale sono stati
verificati renderer WebGL attivo, microfono acceso, wake word pronta e
secondo Start sulla stessa istanza in circa 0,4 secondi.
È disponibile il pulsante **Agenti** per la supervisione Codex + Ruflo.
L'avvio mostra la dashboard, inizializza Ollama fuori dal thread grafico e
riporta in primo piano l'istanza già aperta. `--background` mantiene l'avvio nel tray.

Le sezioni seguenti conservano l'analisi iniziale e i suoi risultati storici.
Gmail applicativo, nuovi TTS e Playwright restano attività future: non sono
funzioni abilitate dal collegamento della grafica. Stato agenti e limiti:
[sistema di sviluppo](development-system.md).

Verifica del 15 novembre 2026. Consegna iniziale: analisi, piano e anteprima
funzionante. L’assistente operativo, la voce configurata, Ollama, SQLite e gli
strumenti Windows non sono stati sostituiti. Il progetto effettivo resta
`C:\Users\VGgot\Desktop\JARVIS`; il percorso Documents nel brief non esiste.

## Cosa è stato analizzato nel filmato

File locale: `C:\Users\VGgot\Downloads\WhatsApp Video 2026-11-15 at 09.47.45.mp4`.
Durata 82,03 secondi; H.264, 576×1024, 30 FPS; audio AAC 44.100 Hz. È stato
decodificato localmente con PyAV già installato. Non sono stati installati codec,
pacchetti o programmi. Sono stati esaminati fotogrammi distribuiti nella durata
e fotogrammi ravvicinati delle sequenze rilevanti; l’audio è stato trascritto e
misurato localmente con i modelli già presenti. Questa sessione non dispone di
ascolto diretto: l’analisi acustica non equivale a un giudizio percettivo.

| Tempo approssimativo | Evidenza visiva |
| --- | --- |
| 3,8 s | Nucleo luminoso oro/bianco su pagina nera, compatto, con contorno irregolare |
| 5,8 s | Il nucleo assume pieghe e lobi più marcati; tessitura fitta di granuli e filamenti, didascalia sotto |
| 8,2–26 s | Gmail e uno scambio di messaggi sul portatile |
| 42–50 s | Gmail e un documento/PDF aperto nel browser |
| 59–75 s | Presentazione verbale dell’automazione; non una traccia completa e verificabile degli strumenti |

Il riferimento visivo è un **nucleo astratto organico**, non una corteccia
anatomica a due emisferi. La scena ha fondo nero, filamenti sottili, molti punti
chiari e una silhouette deformabile. Non ci sono card o grafici di telemetria
decorativi. Il filmato non dimostra la trasparenza di un overlay Windows:
si vede una pagina sul display di un portatile con un sistema differente.

Le affermazioni su ricerca di sponsor, trattative, fatture, pagamenti e
pubblicazione sono contenuto del filmato. I fotogrammi non consentono di
verificare ogni azione, le autorizzazioni, l’assenza di interventi umani o
l’architettura del sistema mostrato. Non sono quindi trattate come funzionalità
già riprodotte o come autorizzazioni a compiere azioni negli account dell’utente.

Materiale di analisi: `data/verification/reference-video/detail-03.8.png`,
`detail-05.8.png`, gli altri fotogrammi con timestamp, `transcript.json` e
`audio-analysis.json`. La trascrizione automatica contiene errori e non è una
trascrizione certificata.

## Voce: riscontri e proposta

Il riconoscimento locale individua italiano con probabilità circa 0,97. Il
passaggio 3,44–26,92 s è stato selezionato come risposta dell’assistente in base
alla sequenza e alla trascrizione, senza diarizzazione automatica. Stima circa
75 parole in 23,48 s, cioè **192 parole/minuto**: un riferimento di ritmo
conversazionale piuttosto scorrevole.

L’autocorrelazione sulle porzioni periodiche stima F0 mediana **165 Hz**, con
percentili 10–90 di circa **91–308 Hz**. Può contenere errori di ottava, musica,
riverbero o contaminazioni. Questi numeri non bastano a certificare una voce
"molto profonda"; la profondità percepita dipende anche da formanti e timbro.
Livello RMS del passaggio circa −15,4 dBFS e picco −2,5 dBFS.

| Caratteristica | Conclusione utilizzabile |
| --- | --- |
| Lingua | Italiano, confermato dalla trascrizione locale |
| Accento | Non certificato: ASR e spettro non permettono un giudizio fine affidabile |
| Profondità | Frequenza fondamentale stimata medio-bassa in parte del passaggio; non una misura della profondità percepita |
| Ritmo | Circa 192 parole/minuto sul segmento indicato, con pause tra frasi |
| Intonazione | Variazione di F0 presente nelle stime; la qualità prosodica richiede ascolto |
| Timbro e naturalezza | Da valutare con ascolto A/B; non vengono inventati giudizi percettivi |

Il target proposto è una voce italiana maschile, chiara, autorevole, con pause
brevi e intonazione conversazionale. È un obiettivo di progetto, non una
identificazione del motore o della persona nel video. Non si clona la traccia.

Sono stati generati due WAV locali **con la voce esistente Microsoft Cosimo**:
`data/voice-reference/cosimo_neutro.wav` (11,34 s) e
`cosimo_operativo.wav` (8,36 s), con manifest e testi. Sono campioni di ascolto,
non risposte a operazioni realmente compiute. Non sono una nuova voce neurale.

Il primo candidato nuovo da confrontare è **Kokoro `im_nicola`**, presente nel
[catalogo ufficiale delle voci italiane](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).
La qualità italiana deve essere ascoltata; il catalogo stesso indica dati limitati.
Seconda opzione: **Piper**, motore neurale locale, da confrontare su un modello
italiano con licenza verificata. Vedi [progetto Piper](https://github.com/OHF-Voice/piper1-gpl)
e [catalogo voci](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md).
Nessuno dei due è installato nella `.venv` attuale. Installazione e pesi richiedono
approvazione; i campioni dei nuovi motori verranno confrontati senza sostituire
Cosimo, e la scelta finale richiederà ascolto e approvazione dell’utente.

## Stato attuale rispetto all’esperienza richiesta

| Area | Esiste nel progetto | Manca o resta da verificare |
| --- | --- | --- |
| Wake word | Modello locale openWakeWord e gate con filtro energetico | Prova attuale con voce umana; il campione Cosimo non passa il gate alla sensibilità corrente |
| Ascolto | Whisper locale, acquisizione PCM, sessione e follow-up | Collaudo end-to-end con microfono dell’utente e ambiente reale |
| AI | Ollama e `qwen3.5:9b`, selezione strutturata degli strumenti | Latenza e recupero su attività Gmail complesse |
| Voce | WinRT Cosimo, PCM effettivo, STOP, esclusione eco | Voce neurale italiana scelta dopo ascolto |
| Grafica | Overlay operativo QPainter; anteprima WebGL separata | Integrazione del nuovo nucleo nell’overlay dopo valutazione visiva |
| Desktop | Windows UI Automation, finestre, clic, testo Unicode e scorciatoie | Copertura delle app e casi d’errore dipendenti dai controlli disponibili |
| Browser | Adapter CDP/PowerShell dedicati ai flussi esistenti | Playwright non installato, adapter generico e cancellazione da collaudare |
| Screenshot | Catture tecniche usate nelle verifiche | Strumento registrato di cattura/interpretazione schermate per l’agente |
| File | Apertura, elenchi e anteprime di testo | CRUD autorizzato con radici e operazioni esplicite |
| Gmail | Apertura di URL attraverso strumenti esistenti | Nessun tool applicativo per cercare/leggere/bozzare/inviare email |
| Sicurezza | Registro strumenti, schemi validati, conferme, memoria operazioni | Contratti Gmail, conferma del messaggio esatto e test di prompt injection specifici |

La disponibilità di un connettore Gmail nella chat non crea automaticamente una
connessione nell’app JARVIS locale. Non sono state lette email o credenziali,
create bozze o inviate comunicazioni durante questa consegna.

## Anteprima ambra implementata

L’anteprima usa gli stessi servizi Qt/WebEngine già disponibili e asset WebGL 2
locali. Nessun video, GIF, immagine o servizio remoto sostituisce il rendering.
La geometria iniziale è un grafo deterministico di **4.800 nodi**, **75 filamenti
principali** e **12.232 connessioni corte**. Gli elementi fini lungo i filamenti
sono campioni grafici interpolati: non sono altri neuroni o unità del modello.

Le pieghe hanno una forma irregolare tridimensionale; shader, deformazione
coerente e lenta rotazione producono il movimento organico. Le onde usano le
distanze sul grafo. Le sinapsi sono suddivise in piccoli archi; gli impulsi
seguono gli archi. Le transizioni di attività sono interpolate e il tempo dei
segnali viene integrato, evitando salti di fase tra stati. La palette è oro,
ambra e bianco caldo, con variazione controllata per lo stato errore.

Sono preservati zoom 0,5–6×, orbita, spostamento, selezione e ispezione dei nodi.
L’ispettore mostra ID, coordinate, settore geometrico e connessioni effettive
del prototipo; non pretende di mostrare neuroni, ricordi o pesi interni di Qwen.
**Solo nucleo / Tab** nasconde i controlli di prova. Esc interrompe e li ripristina.

Gli stati manuali sono esplicitamente simulazioni grafiche. **Ascolta Cosimo ·
PCM reale** riproduce invece un WAV locale attraverso il percorso audio esistente:
l’ampiezza arriva dal misuratore PCM sincronizzato al player, senza microfono
o richiesta AI. Fine campione, STOP e chiusura rilasciano la riproduzione.
Questa finestra di prova resta separata; la medesima scena è ora anche
collegata agli eventi reali nella dashboard e nell'overlay operativo.

Avvio:

```powershell
.\.venv\Scripts\python.exe -m jarvis --neural-preview
```

Oppure doppio clic su `Anteprima_Neurale.bat`. La precedente corteccia ciano resta
disponibile con `--neural-style cortex --neural-particles 2800`.

## Piano concreto di integrazione

1. **Validazione visiva:** valutare il nucleo ambra in finestra e nell’overlay di
   prova, mantenendo l’app operativa. Regolare densità e movimento sulla base
   del confronto; non dichiarare una replica esatta del filmato.
2. **Bridge agli eventi reali:** adattare l’interfaccia esistente
   `present/dismiss/set_level/set_reduced_motion` al renderer WebGL. Riutilizzare
   `Presenter`, `VoiceSession` e `SpeechOutput`; nessun nuovo controller AI.
   Idle/executing nascondono immediatamente l’overlay; `execution_barrier`
   rilascia l’azione solo dopo conferma della chiusura. Conservare QPainter come
   fallback verificato in assenza di WebGL.
3. **Voce:** installare un candidato solo dopo approvazione, preparare campioni
   identici e misurare tempo al primo audio, durata, memoria e qualità percepita.
   Restare su Cosimo fino alla scelta dell’utente; nessuna clonazione del video.
4. **Prima attività Gmail:** preferire API OAuth a interazioni GUI fragili per
   ricerca, lettura e bozza; altrimenti adapter browser con sessione dedicata e
   accesso manuale. Disambiguare "professore" e il messaggio quando necessario,
   usando mittente, data e oggetto. Non indovinare identità o destinatari.
5. **Conferma invio:** introdurre strumenti separati per ricerca/lettura/bozza e
   invio. Prima dell’invio mostrare destinatari, oggetto e corpo finali. Legare
   l’approvazione al loro hash e all’identità del thread, con scadenza e uso
   singolo. Una modifica annulla la conferma. Nessuna autorizzazione ricavata dal
   testo di email, pagine o documenti, né dalla sola autorizzazione generale al task.
   Dopo l’invio verificare l’ID del messaggio e registrare l’esito; un timeout con
   esito incerto impone verifica, non un secondo invio alla cieca.
6. **Browser e screenshot:** dopo autorizzazione alle dipendenze, aggiungere
   Playwright in ambiente separato e un adapter stretto con processi cancellabili,
   profili dedicati e tempi massimi. L’installazione richiede pacchetto e browser,
   come descrive la [documentazione Playwright](https://playwright.dev/python/docs/library).
   Prevedere screenshot limitati alla finestra autorizzata; i contenuti esterni
   rimangono dati non fidati. Nessun terminale generico controllato dal modello.
7. **Accettazione operativa:** prima fixture Gmail locale con email ostile e STOP
   durante ciascuna fase; poi account reale autorizzato. Provare lettura e bozza
   prima dell’invio. Separare test automatici da qualunque invio reale.

Le azioni desktop, le credenziali OAuth, l’accesso alle email e l’installazione di
Playwright/TTS non vengono abilitate dal solo filmato o da un’anteprima riuscita.
L'overlay è stato successivamente integrato su richiesta dell'utente;
Ruflo è stato installato e collaudato dopo l'approvazione dedicata.

## Risultati verificati e problemi aperti

- **162 test di regressione passati**, exit code 0, log in
  `data/verification/reference-video/regression-tests.txt`.
- **WebGL reale ambra e ciano:** circa 60 FPS nei campioni effettuati sulla RTX
  5070 Ti, selezione tramite clic, centratura, zoom, stati e sospensione verificati.
  Buffer del grafo ambra circa 1,65 MB. La misura non include tutta la memoria di
  Chromium o del compositore; i campioni NVIDIA riguardano l’intero dispositivo.
- **Trasparenza desktop e rilascio input:** verificati con sfondo controllato e
  flag dell’overlay di prova. DPI misti e altri driver restano da collaudare.
- **PCM reale:** riproduzione muta di verifica, misuratore variabile, stato voce
  e rilascio del sink con STOP passati. Non certifica qualità degli altoparlanti.
- **Attività Windows reale:** la fixture dedicata ha verificato clic UIA,
  digitazione Unicode, scorciatoia, risultato e chiusura. Non ha operato su Gmail
  o finestre personali; report `data/verification/pc-control.json`.
- **Parlato sintetico → STT → Qwen → lettura Windows → risposta PCM:**
  "Che ore sono?" è stato trascritto dal modello locale, Qwen ha selezionato
  `get_current_datetime`, la lettura è stata registrata in SQLite separato e
  sintetizzata in PCM. Nella prova: STT circa 0,80 s, AI/lettura circa 3,50 s,
  sintesi risposta circa 0,38 s. Non sono benchmark generali o prove al microfono.
- **Verifica wake word fallita sul campione sintetico:** picco circa 0,54, ma il
  gate alla sensibilità configurata non scatta. Il test complessivo
  `pipeline-verification.json` è pertanto **failed**, non interamente operativo.
  Non sono state abbassate soglie o modificate le impostazioni stabili per farlo
  passare. Serve un confronto con registrazione umana autorizzata e analisi
  dell’energia/continuità dei frame prima di decidere una correzione.

Non verificati: invio Gmail, nuovo TTS neurale, attività dell’agente basate su
screenshot, Playwright, microfono umano nel ciclo completo, prestazioni sotto
inferenza prolungata e sostituzione del visualizzatore operativo.

Comandi riproducibili:

```powershell
.\.venv\Scripts\python.exe -B scripts/prepare_reference_voice.py
.\.venv\Scripts\python.exe -B scripts/verify_neural_preview.py --with-local-pcm
.\.venv\Scripts\python.exe -B scripts/verify_neural_preview.py --style cortex
.\.venv\Scripts\python.exe -B scripts/verify_pc_control.py
.\.venv\Scripts\python.exe -B scripts/verify_reference_pipeline.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```
