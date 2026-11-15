# Anteprima neurale 3D

Aggiornamento del 15 novembre: l’anteprima predefinita è ora il **nucleo organico
ambra** analizzato dal video MP4 locale. Analisi, limiti e verifiche sono in
[esperienza guidata dal riferimento](reference-driven-experience.md). La
corteccia ciano rimane disponibile con `--neural-style cortex --neural-particles 2800`.

## Analisi dell’applicazione esistente

La copia effettiva è `C:\Users\VGgot\Desktop\JARVIS`; il percorso `Documents\JARVIS`
del brief non esiste su questo PC. Il precedente riferimento TikTok fornito
(`https://vm.tiktok.com/ZGdXQADgv/`) reindirizza al login obbligatorio: il filmato
non è stato visionato e non si dichiara fedeltà a quel riferimento.

L’applicazione usa PySide6 6.12.0. `jarvis/ui/overlay.py` contiene `BrainOverlay`,
un QWidget trasparente, senza titolo, sempre in primo piano e non interattivo;
`brain_renderer.py` proietta punti 3D usando QPainter a circa 30 FPS. Non è WebGL.
`visualizer.py` è un widget distinto della dashboard.

Gli stati reali sono in `core/assistant_state.py` e arrivano al `Presenter`
attraverso gli eventi dei worker e i segnali di `VoiceSession` e `SpeechOutput`.
L’attivazione wake word chiama `_wake_activated`; la transizione d’attivazione
non ha un enum distinto nell’app attuale. Il livello del microfono proviene
dall’RMS PCM in `voice/audio.py`; il livello TTS proviene dal PCM sintetizzato,
sincronizzato con `QAudioSink.processedUSecs()`. Il presenter collega già questi
segnali all’overlay. `execution_barrier` attende che l’overlay sia nascosto prima
di consentire l’operazione. Le autorizzazioni usano dialoghi Qt separati.

## Soluzione implementata: fasi 1 e 2

Il prototipo è separato dall’assistente: non costruisce controller, database,
provider Ollama, riconoscitore, TTS o strumenti Windows. L’overlay operativo e il
suo protocollo di autorizzazione/esecuzione restano quelli esistenti.

Qt WebEngine è già disponibile nella `.venv`. Il renderer usa **WebGL 2 nativo**,
buffer GPU e shader GLSL locali, senza Three.js aggiuntivo, Node.js, npm,
installazioni, CDN, immagini o filmati. Questo permette di provare la soluzione
senza nuove dipendenze. La geometria è una rappresentazione artistica cerebrale,
non un modello anatomico o una visualizzazione dei pesi di Qwen.

Il grafo della modalità `cortex`, con budget 2.800, contiene neuroni su due
emisferi con fessura centrale, pieghe corticali e una rete interna più rarefatta.
Le sinapsi collegano al massimo cinque vicini per neurone nella costruzione del
grafo; altri neuroni possono aggiungere collegamenti entranti, quindi il grado
finale può superare cinque. La distanza massima dipende dal budget dei neuroni.
Pochi ponti centrali collegano gli emisferi. Le distanze minime sul grafo
temporizzano le onde; gli impulsi viaggiano dai nodi con arrivo anticipato a
quelli successivi. Respirazione e deformazioni avvengono nello shader.

## Avvio e comandi

Doppio clic su `Anteprima_Neurale.bat`, oppure:

```powershell
.\.venv\Scripts\python.exe -m jarvis --neural-preview
```

L’anteprima predefinita `organic` usa 4.800 nodi su filamenti deformati, con
colori oro/ambra. Non presenta emisferi anatomici: nell’ispettore i settori
sinistro/destro indicano soltanto la posizione geometrica.

Controlli disponibili:

- Rotella oppure cursore **Zoom**: ingrandimento da 0,5× a 6×.
- Trascinamento: orbita tridimensionale. Shift+trascinamento: spostamento della vista.
- Clic su un neurone: selezione e illuminazione delle sue connessioni.
- **Neurone / Ispeziona**: selezione per ID; **Centra**: porta il neurone al centro con zoom ravvicinato.
- Ispettore: ID, emisfero, coordinate nello spazio del modello e ID dei vicini effettivi.
- **Deseleziona / Ripristina vista**: rimuovono l’evidenziazione o ripristinano la telecamera.
- **Solo nucleo / Tab**: nasconde o ripristina i controlli di prova.
- **Ascolta Cosimo · PCM reale**: riproduce il campione locale generato con
  `scripts/prepare_reference_voice.py`; l’animazione segue il PCM del player.
- Pulsanti degli stati e **Sequenza simulata**: attivazione, ascolto, elaborazione,
  voce, esecuzione, conferma, errore e riposo, tutti esplicitamente simulati.
- **Ampiezza manuale**: prova il bridge del livello negli stati ascolto/voce;
  non acquisisce audio e non inventa un segnale TTS. Un livello non aggiornato decade.
- **Prova overlay**: apre la superficie trasparente sul monitor selezionato,
  senza catturare mouse o tastiera; si chiude dopo 12 secondi.
- Esc: arresta la sequenza, sospende il rendering e nasconde l’overlay.

Il pannello di anteprima è interattivo; l’overlay dimostrativo lascia passare
l’input al desktop. Le informazioni dei neuroni riguardano il grafo procedurale;
non rappresentano memoria SQLite, ricordi, token, neuroni biologici o unità di Qwen.

Budget configurabili senza modificare le preferenze dell’assistente:

```powershell
.\.venv\Scripts\python.exe -m jarvis --neural-preview --neural-particles 1800 --neural-pixel-ratio 1.0 --neural-fps 30
```

Neuroni: 400–6.000; DPR massimo: 0,75 / 1 / 1,25 / 1,5 / 2; FPS: 24 / 30 / 60.
Il DPR effettivo non supera quello del monitor. La qualità automatica riduce
prima risoluzione e numero di impulsi quando gli FPS restano insufficienti.
Non sono presenti catene di post-processing o texture grandi. Vengono rilasciati
buffer, programmi, query e contesto GPU alla chiusura. Nessun frame viene
richiesto in idle, executing, quando la finestra è nascosta o minimizzata.

## Bridge e isolamento

`NeuralView.set_state()` e `set_level()` inviano soltanto valori validati con
serializzazione JSON a metodi JavaScript prestabiliti. La pagina non riceve
oggetti Python, QWebChannel, porte HTTP o funzioni per eseguire comandi Windows.
La lettura dello snapshot è asincrona. Un profilo WebEngine privato e un
interceptor consentono esclusivamente i tre file locali del renderer; navigazioni,
download, permessi, accesso remoto e clipboard sono bloccati. Una CSP vieta
connessioni di rete e contenuti esterni.

Le impostazioni di trasparenza usano un contesto WebGL con alpha, CSS trasparente,
`WA_TranslucentBackground` e `QWebEnginePage.setBackgroundColor` trasparente.
La documentazione Qt descrive il [colore di sfondo della pagina](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineCore/QWebEnginePage.html)
e le [restrizioni WebEngine](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineCore/QWebEngineSettings.html).
Questi flag da soli non costituiscono una verifica della composizione Windows:
lo script sotto confronta pixel dello schermo con uno sfondo di prova controllato.
Se WebGL o il processo grafico non sono disponibili, l’anteprima mostra un errore;
l’overlay QPainter operativo rimane disponibile nell’assistente.

## Verifiche e limiti

```powershell
.\.venv\Scripts\python.exe -B scripts/verify_neural_preview.py --with-local-pcm
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Il primo apre finestre di prova, verifica WebGL reale, FPS, rotazione, bridge
dell’ampiezza manuale, selezione tramite clic, dati dell’ispettore, zoom,
sospensione e trasparenza sul desktop. Le catture contengono l’interfaccia di
prova e lo sfondo controllato. Non avvia Ollama o il microfono.

Il report è `data/verification/neural-preview/verification.json`; le immagini sono
`preview.png`, `neuron-inspector.png` e `overlay-composited.png`. Riporta FPS,
tempo CPU di invio dei comandi, tempo GPU tramite query WebGL se supportate,
dimensione dei buffer del grafo e campioni di utilizzo GPU/VRAM da `nvidia-smi`.
CPU submit e tempo GPU non sono l’intero tempo della pipeline Chromium/compositore.
I campioni NVIDIA riguardano il dispositivo completo, comprese altre applicazioni:
non vanno attribuiti interamente al visualizzatore. Il contesto Chromium può
consumare più VRAM dei soli buffer del grafo.

Sono richieste prove successive per carico concorrente con inferenza Qwen,
microfono/TTS reali collegati al nuovo renderer, DPI misti, cambio monitor a caldo,
driver differenti e approvazioni reali. In questa consegna questi percorsi
**non sono integrati né dichiarati verificati**. La sostituzione di BrainOverlay
è una fase successiva alla valutazione visiva dell’utente.
