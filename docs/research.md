# Ricerca autonoma e PDF — 0.7.0

Esempio: «Jarvis, fai una ricerca con ChatGPT e Google Documenti sui vantaggi e i limiti del fotovoltaico domestico e consegnami un PDF con le fonti».

Il modello seleziona `run_research` e prepara argomento, query e servizi richiesti. La conferma iniziale mostra questo piano concreto e autorizza soltanto i suoi passaggi. ChatGPT e Google Documenti vengono usati quando richiesti esplicitamente; una ricerca senza quei servizi produce direttamente il PDF locale. Se manca l'argomento, JARVIS lo chiede prima di iniziare.

Il lavoro termina dopo la consegna: raccolta dei risultati, lettura parallela delle pagine pubbliche, selezione della pertinenza, stesura con riferimenti numerati, eventuale riscontro ChatGPT, eventuale creazione del Google Documento ed esportazione. Il riscontro ChatGPT non viene trattato come una fonte. Servono almeno due pagine leggibili; il rapporto contiene URL e date di consultazione. Le valutazioni e la sintesi dipendono dal modello locale e possono richiedere una revisione umana.

Dalla 0.7.0 la raccolta valuta la copertura e può riformulare le query fino a due volte sullo stesso argomento. Un errore di ricerca o una pagina non disponibile non interrompe le altre letture. URL già tentati e pagine con testo identico vengono esclusi dalle nuove raccolte. Se restano lacune dopo il budget previsto, vengono dichiarate nel rapporto e nel messaggio di consegna.

Prima della consegna, Qwen confronta affermazioni del rapporto e passaggi delle fonti identificati dal codice. Distingue contraddizioni, compatibilità e incertezze. Le contraddizioni portano a una correzione e a una nuova revisione; se persistono, il rapporto resta conservato e il PDF non viene consegnato. Le incertezze diventano limiti espliciti. Il controllo resta una valutazione del modello, non una certificazione di verità. `qualita.json` registra copertura e revisione; `stato.json` conserva anche tentativi, errori e riformulazioni.

La ricerca prova Google. Se richiede verifiche o non fornisce risultati leggibili, usa l'API pubblica MediaWiki e i riferimenti esterni degli articoli trovati. Il registro conserva il motore effettivo e il PDF segnala la copertura parziale; questa alternativa non equivale a una ricerca completa di tutto il web. Le pagine non leggibili, i download non testuali e gli errori HTTP vengono scartati. Gli indirizzi privati vengono rifiutati anche dopo reindirizzamenti, collegando il socket all'IP pubblico verificato.

## Accessi ai servizi

Chrome usa il profilo dedicato `data/browser-profile`, separato dal browser personale. Al primo uso bisogna completare manualmente gli accessi a ChatGPT e Google nella sua finestra. JARVIS mostra il passaggio in attesa e resta interrompibile. Non legge credenziali o cookie e non aggira verifiche o limiti dei servizi.

La raccolta e la bozza vengono preparate prima di attendere gli accessi. Il nuovo Google Documento viene creato soltanto dopo la stesura e la revisione, evitando documenti vuoti per ricerche non riuscite.

Per Google Documenti viene creato un nuovo documento. Il controllo rifiuta documenti già intitolati o contenenti testo, vincola le operazioni al documento identificato e non ripete la scrittura dopo un esito incerto. Prima della consegna scarica il testo salvato e lo confronta integralmente con il rapporto, poi scarica il PDF. Se il servizio fallisce, l'attività resta incompleta: non viene dichiarata conclusa mediante un PDF locale sostitutivo.

Il controllo Google Documenti dipende dall'interfaccia web corrente: il campo di modifica deve essere accessibile. L'esportazione verificata rileva un inserimento non riuscito. Il test locale del controllo browser non certifica la compatibilità con un account Google autenticato.

## Consegna e arresto

La dashboard mostra lo stadio corrente e il pulsante **Apri PDF verificato**. I risultati sono in `data/reports/<data-id>/`: `ricerca.pdf`, rapporto strutturato, fonti lette e `stato.json`. Per il PDF locale sono disponibili anche HTML e testo. Un'attività interrotta o fallita conserva il proprio stato senza emettere una consegna riuscita.

Dire «stop», scrivere STOP nella dashboard, premere il pulsante STOP o usare Ctrl+Alt+Pausa. Gli effetti già completati, compresi documenti creati e messaggi inviati, restano. La sessione ha passaggi con timeout e un budget di lavoro di 15 minuti; le attese per l'intervento umano non consumano il tempo di attesa esplicito. Non ci sono nuove dipendenze, API a pagamento o modelli aggiunti.

## Verifiche riproducibili

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests
.venv\Scripts\python.exe -B scripts/verify_research.py
.venv\Scripts\python.exe -B scripts/verify_google_docs_fixture.py
```

`verify_research.py` usa ricerche e pagine pubbliche reali, Qwen locale e un PDF Qt riaperto per controllare pagine e titolo. Il suo database è separato; non accede ad account ChatGPT/Google e non crea documenti esterni. Il report è `data/verification/research.json`.

`verify_google_docs_fixture.py` usa Chrome reale, una pagina locale con campo titolo e iframe di modifica, inserimento nativo e download di testo/PDF. Non è il servizio Google: report `data/verification/google-docs-fixture.json`. La verifica in sola lettura del servizio reale ha rilevato accesso richiesto: `data/verification/google-docs-readiness.json`. Il percorso autenticato ChatGPT → Google Documenti → PDF deve ancora essere verificato dopo il login dell'utente.

La comunicazione Chrome ora riusa una connessione WebSocket attraverso un helper Windows persistente. Nella stessa prova locale di tre scambi ChatGPT, il tempo è sceso da circa 27 a 12 secondi; non è una misura della latenza del servizio ChatGPT reale.
