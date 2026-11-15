# Architettura Foundation 0.1

## Confini e dipendenze

`run.py` controlla Python 3.12 e la `.venv` locale, inizializza Qt e protegge il processo con `QLockFile`. `bootstrap.py` costruisce configurazione, logging, SQLite, policy, registro strumenti e controller. Le importazioni dei moduli non avviano automazioni né creano dati.

```text
MainWindow → Presenter → TaskWorker (QThread) → Controller
                                                   ↓
                                            ToolRegistry
                                                   ↓
                                   validazione → SecurityPolicy
                                                   ↓
                                       conferma, se necessaria
                                                   ↓
                                          Tool.execute()
                                                   ↓
                                          ToolResult + evidenza

Controller → Repository → SQLite
TaskWorker → segnali Qt → Presenter → aggiornamento widget
```

| Modulo | Responsabilità |
|---|---|
| `core/models.py` | Valori immutabili per chiamate, risultati, eventi e conferme |
| `core/controller.py` | Ciclo richiesta, strumenti, persistenza, errori e stato |
| `core/commands.py` | Comandi documentati della demo; nessuna classificazione NLP |
| `core/tasks.py` | Deadline e cancellazione cooperativa |
| `brain/protocol.py` | Contratto asincrono per provider reali futuri |
| `tools/registry.py` | Unico punto di esecuzione con validazione e autorizzazione |
| `tools/open_application.py` | Avvio di un eseguibile autorizzato, senza shell o argomenti |
| `tools/history.py` | Cancellazioni locali ad alto rischio |
| `security/` | Rischio e autorizzazioni concrete monouso |
| `memory/` | Migrazione, transazioni e repository separati per tipo di dato |
| `infrastructure/` | Configurazione limitata al progetto e log JSON minimali |
| `ui/` | Presentazione, thread adapter, dialoghi e HUD geometrico |

## Thread e ciclo delle attività

L'interfaccia vive esclusivamente nel thread Qt principale. Il Presenter consente un solo TaskWorker alla volta. Lettura della memoria, esecuzione dei comandi e strumenti lavorano nel worker; i segnali trasportano gli eventi alla GUI. Nessuna connessione SQLite viene condivisa tra thread. Le operazioni SQLite usano connessioni brevi, transazioni e un'attesa lock di 2 secondi.

Stati persistenti delle attività: `running`, `waiting_approval`, `succeeded`, `failed`, `cancelled`, `timed_out`, `interrupted`. Al riavvio, attività rimaste in esecuzione vengono marcate `interrupted`. Il lock di istanza protegge questo recupero dalle altre istanze della stessa applicazione.

La deadline operativa predefinita è 20 secondi; l'attesa di conferma ha un limite separato di 90 secondi e non consuma la deadline operativa. Ogni strumento deve controllare `TaskContext.checkpoint()` prima di un effetto e durante operazioni ripetute. I timeout sono cooperativi: non interrompono forzatamente una chiamata nativa già entrata nel sistema operativo. La chiusura dell'app richiede STOP e attende il completamento del worker senza distruggere un thread ancora attivo.

## Sicurezza

Il rischio è dichiarato dal codice dello strumento registrato; non è un parametro fornito dalla chat. Gli strumenti non registrati vengono negati. La validazione precede la conferma, e i parametri validati vengono serializzati in JSON canonico.

Le operazioni a rischio medio e alto richiedono una conferma. Ogni autorizzazione lega strumento, parametri, rischio e ID attività; scade ed è consumabile una sola volta. Il controllo STOP avviene anche dopo la conferma e immediatamente prima dell'esecuzione. La chiusura o la scadenza del dialogo equivale al rifiuto. I token di conferma restano soltanto in memoria.

I messaggi della chat vengono convertiti in testo HTML escapato. Il visualizzatore della conversazione non carica risorse esterne e non apre collegamenti. Non esiste ancora un percorso di ingestione di pagine o documenti esterni: le difese contro prompt injection per browser e documenti dovranno essere implementate e verificate prima dell'introduzione di tali strumenti.

La lista applicazioni è fidata, gestita dall'utente. Nessun programma viene installato, chiuso o avviato come amministratore. I controlli sui percorsi dati rifiutano symlink, junction e destinazioni risolte fuori dal progetto prima dell'avvio dei servizi. Questo non sostituisce le protezioni Windows contro un altro processo locale che modifica file o directory durante l'esecuzione.

## Persistenza

Migrazione `001_initial.sql`, versione schema in `PRAGMA user_version`. Un database di una versione futura viene rifiutato. Tabelle distinte: `messages`, `tasks`, `preferences`. SQL parametrizzato, journal WAL, cancellazione con `secure_delete` e checkpoint del WAL durante la rimozione della cronologia. La GUI mostra gli ultimi 200 messaggi e le ultime 50 attività; gli altri dati rimangono nel database fino alla cancellazione.

Le preferenze UI salvate prevalgono sulla configurazione iniziale. Ordine della configurazione iniziale: variabili d'ambiente → `.env` del progetto → `config/defaults.json`.

## Preparazione alle versioni successive

Il provider futuro riceverà cronologia e schemi da `ToolRegistry.schemas()` e produrrà `ModelReply` con `ToolCall`. Anche le chiamate del modello dovranno attraversare il registro e la policy esistenti. L'adapter effettivo, autenticazione, retry, limiti di utilizzo, costi e cronologia delle chiamate AI restano nella 0.2.

Voce, controllo Windows avanzato e browser avranno adapter separati. Non sono implementati o attivati nella Foundation. Anche l'eventuale esecuzione asincrona del provider andrà integrata nel worker senza bloccare il thread Qt. Non è necessario introdurre adesso un secondo event loop o dipendenze di automazione.
