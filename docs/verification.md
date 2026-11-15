# Verifica della versione 0.1

Usare soltanto `.venv\Scripts\python.exe` dalla radice del progetto.

## Verifica automatica

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

La suite copre:

- persistenza reale SQLite, migrazione, recupero attività interrotte e query parametrizzate;
- priorità e validazione configurazione, assenza di modifica alle variabili del processo;
- rifiuto di strumenti sconosciuti, applicazioni non autorizzate e argomenti aggiuntivi;
- conferme legate a parametri, rischio e attività, scadenza, revoca e utilizzo singolo;
- impossibilità di cancellare la cronologia senza conferma;
- STOP dopo conferma e durante l'attesa della conferma;
- GUI reattiva mentre uno strumento controllato dal test è in esecuzione;
- chiusura in inattività e durante una richiesta di conferma;
- preferenze persistenti, animazioni ridotte e timer sospesi;
- visualizzazione letterale di HTML inserito in chat;
- risultati di lancio che distinguono processo creato da finestra verificata.

I test creano directory temporanee esclusivamente sotto `data/test-runs`. Nel sandbox di Codex Windows, la creazione di directory temporanee con ACL private può richiedere di eseguire i test fuori sandbox. Questo riguarda il contesto di verifica di Codex: l'applicazione normale non richiede privilegi amministrativi.

I test Qt usano il backend `offscreen` e caricano i font Windows solo nel processo di test. Non modificano font o impostazioni di sistema. Non avviano applicazioni esterne. L'anteprima fuori schermo viene salvata in `data/verification/foundation-offscreen.png`.

## Avvio Windows reale

Con JARVIS chiuso:

```powershell
.\.venv\Scripts\python.exe -B scripts/verify_startup.py
```

Lo script usa l'entrypoint reale e il backend Windows nativo, attende che sia visibile la finestra e caricata la memoria, salva `data/verification/foundation-preview.png`, poi chiude JARVIS. Restituisce un riepilogo JSON e un exit code non zero in caso di errore. Non apre Blocco note e non acquisisce il resto del desktop.

## Prova manuale

| Azione | Risultato atteso |
|---|---|
| Aprire `run.py` con la `.venv` | HUD scuro, badge demo, chat e STOP inattivo |
| Inviare `/aiuto` e `/app` | Comandi e lista realmente configurata |
| Inviare `/apri blocco_note` | Blocco note avviato; PID riportato senza dichiarare la verifica della finestra |
| Inviare `/apri powershell` | Rifiuto; nessun interprete aperto |
| Inviare `/apri blocco_note argomento` | Comando rifiutato |
| Inviare `apri Blocco note` | Messaggio conservato e indicazione che l'AI è assente; nessuna automazione |
| Salvare animazioni ridotte e riavviare | Preferenza conservata, visualizzatore statico |
| Premere Cancella… e Nega | Messaggi conservati, rifiuto visibile |
| Premere Cancella… e STOP | Nessuna cancellazione, attività annullata |
| Premere Cancella… e approvare | Cronologia rimossa; resta l'esito della cancellazione |
| Ripristinare preferenze dalle impostazioni | Conferma specifica; cronologia conservata |
| Minimizzare | Timer del visualizzatore sospeso |
| Aprire una seconda istanza | Avviso, nessuna seconda UI sulla stessa memoria |

I tempi di avvio dipendono da Qt, filesystem e PC. La suite controlla che il ciclo eventi riceva eventi durante una lavorazione; non è un benchmark di prestazioni. Voce, provider AI, automazione grafica e browser non fanno parte di questa verifica.

## Esito della verifica iniziale — 14 novembre 2026

- **38 test automatici superati**, inclusi controlli Qt, autorizzazioni e cancellazione.
- `pip check`: nessuna dipendenza incompatibile.
- Avvio nativo attraverso `run.py`: exit code `0`, finestra caricata, font Segoe UI disponibili, anteprima salvata e chiusura automatica riuscita.
- Prova reale di `OpenApplicationTool` con `blocco_note`: processo creato da Windows, PID restituito, `window_verified=false`. La finestra dell'applicazione avviata non viene chiusa automaticamente.

Non sono state installate dipendenze fuori dalla `.venv` né modificate configurazioni Windows. La prova di avvio dell'applicazione esterna non equivale a una verifica grafica dei suoi contenuti.
