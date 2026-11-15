# Reattività di JARVIS

Ottimizzazione verificata il 15 novembre 2026, sul modello esistente
`qwen3.5:9b` e sulla RTX 5070 Ti. Nessun modello nuovo o servizio cloud.

## Cambiamenti applicati

- La prima chiamata al modello può produrre direttamente una risposta breve
  conversazionale. Prima classificava soltanto la richiesta e richiedeva una
  seconda inferenza con tutti gli schemi degli strumenti.
- Il prompt di selezione è più compatto e distingue conversazione, dati
  Windows, aperture, attività miste, ricerche e conversazione con ChatGPT.
  Le risposte dettagliate o complesse conservano il normale generatore in
  streaming. La memoria conversazionale resta entro lo stesso budget precedente.
- I dati del PC passano ancora dagli strumenti reali; le affermazioni di azioni
  non eseguite vengono bloccate anche nel percorso rapido.
- Qwen viene precaricato in background all'avvio con una richiesta locale senza
  prompt o messaggi. Le richieste mantengono il modello residente per 30 minuti
  dall'ultimo utilizzo, anziché 5, riducendo i caricamenti dopo brevi pause.
- Whisper viene preparato sul proprio thread quando il microfono è pronto,
  prima del primo comando. Restano modello `whisper-small`, CPU int8, quattro
  thread, lingua italiana e beam size 5. Voce Cosimo e soglie audio sono conservate.

Il precaricamento e `keep_alive` usano le API descritte nella
[documentazione ufficiale Ollama](https://github.com/ollama/ollama/blob/main/docs/faq.mdx).
Il contesto rimane a 16.384 token. Non sono cambiate impostazioni globali GPU,
Windows o Ollama; non vengono scaricati pesi.

## Misure reali

Mediana di tre esecuzioni per scenario, con modello già caricato, repository
SQLite di prova separato e catalogo reale degli strumenti:

| Richiesta | Prima | Dopo | Riduzione |
| --- | ---: | ---: | ---: |
| Spiegazione breve di una sinapsi | 1,360 s | 0,766 s | 43,7% |
| Ora corrente, letta da Windows | 1,110 s | 0,578 s | 47,9% |

Sono tempi dall'ingresso della richiesta testuale alla risposta finale del
controller: escludono registrazione, attesa di fine frase e riproduzione vocale.
Non sono una promessa sui tempi di una ricerca lunga o di qualunque richiesta.
Le risposte sono generate dal modello, non recuperate da frasi preimpostate.

La prova Whisper ha verificato il modello pronto **prima** del comando,
caricamento anticipato di circa 1,05 s e trascrizione effettiva di un campione
Cosimo locale. Non è una misura della voce umana o dell'acustica del microfono.

## Verifiche e riproduzione

- **176 test automatici superati**: filtri del ragionamento, assenza di false
  conferme di operazioni, rifiuto di strumenti nascosti nel JSON conversazionale,
  cancellazione e funzionamento dei percorsi precedenti.
- **12 casi con Qwen reale**: negazioni, richieste di spiegazione, letture fresche,
  aperture, memoria operativa, richieste miste e risposta estesa. Nessuno strumento
  è stato eseguito durante questa prova di selezione.
- I benchmark eseguono soltanto la lettura autorizzata dell'ora; non aprono app,
  accedono ad account o usano il database personale.

Risultati dettagliati: `data/verification/latency/before.json`, `after.json`,
`routing-verification.json`, `stt-preload.json` e `regression.log`.

```powershell
.\.venv\Scripts\python.exe -B scripts/benchmark_latency.py --label after
.\.venv\Scripts\python.exe -B scripts/verify_fast_routing.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

`data/runtime.json` riporta anche lo stato di caricamento del riconoscimento
vocale e la durata dell'ultima trascrizione, senza salvare audio o testo in quei campi.
