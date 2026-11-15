# Autonomia adattiva — 0.7.0

Il ciclo degli strumenti usa osservazioni aggiornate per scegliere il prossimo passo. Se una lettura fallisce, l'errore viene passato al modello come dato strutturato. Se Qwen si ferma senza proporre un recupero, un selettore JSON sceglie un prossimo strumento tra le sole letture disponibili. Il risultato passa comunque da validazione, autorizzazione e registro operazioni.

Per esempio, dopo un errore leggendo `appunti.txt`, può elencare la cartella, trovare `appunti-aggiornati.txt` e leggerne il contenuto. Un semplice elenco non viene considerato recupero concluso quando era richiesta la lettura del file. I passaggi successivi di un gruppo vengono scartati se dipendono da una lettura fallita; il modello rivaluta prima di agire.

Gli errori di scrittura, avvio, input o invio e le richieste di intervento umano interrompono il ciclo. Non vengono ritentati automaticamente. Dopo ogni `desktop_action`, una nuova `inspect_desktop` osserva lo stato; l'input consegnato rimane distinto dalla riuscita dell'obiettivo richiesto. La politica delle conferme continua ad applicarsi.

La memoria di lavoro conserva gli esiti del compito e rende esplicite le osservazioni vecchie abbreviate. Tre letture identiche senza nuovi risultati fermano il ciclo; gli errori ripetuti e il limite configurato di passaggi impediscono tentativi indefiniti. Le operazioni già completate restano registrate anche se un passaggio successivo fallisce. Questa è memoria operativa del compito, senza addestramento o modifica automatica del modello.

Durante i compiti con strumenti, la dashboard mostra i passaggi e accetta STOP anche da tastiera o voce. Gli aggiornamenti di avanzamento non azzerano l'audio di STOP in acquisizione. Per la ricerca, riformulazione e revisione sono descritte in [ricerca e PDF](research.md).

## Verifica

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests
.venv\Scripts\python.exe -B scripts/verify_adaptive_agent.py
.venv\Scripts\python.exe -B scripts/verify_research.py
```

La prova di recupero usa Qwen e filesystem reali in una cartella isolata: il file viene rinominato proprio al primo tentativo di lettura. L'agente deve trovare e leggere il nuovo file e restituire il codice contenuto nel documento, non incluso nella richiesta. Nessuna scrittura esterna; report `data/verification/adaptive-agent.json`.

La prova di ricerca usa pagine pubbliche reali, riformulazioni, revisione e PDF Qt; non effettua invii ChatGPT o scritture su account Google. Il percorso con account autenticati resta da verificare dopo il primo accesso dell'utente. Nessuna dipendenza, modello o API a pagamento aggiunta.
