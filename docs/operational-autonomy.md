# Autonomia operativa, WhatsApp e letture silenziose — 0.7.1

Questa modifica interviene sul comportamento dell'assistente quotidiano. Non
attiva agenti di sviluppo fittizi e non modifica Ruflo o il Development Command Center.

## Cambiamenti

- Le richieste operative composte raggiungono un ciclo strutturato: un'azione,
  risultato reale, scelta del passo successivo. Il saluto conserva il percorso
  veloce a una sola inferenza. Il modello e' sempre Qwen3.5:9b gia' installato.
- I nomi degli strumenti sono vincolati al catalogo effettivo. I parametri sono
  validati dal registro esistente prima dell'approvazione e dell'esecuzione.
  Lo schema generale evita un `oneOf` esteso rifiutato dal sampler Ollama locale
  durante la verifica reale (HTTP 400).
- I dati indispensabili mancanti diventano una domanda e uno stato `waiting_input`,
  non un incarico dichiarato concluso. La risposta successiva riceve l'obiettivo
  rimasto aperto. Timeout, STOP e registro operazioni restano attivi.
- `search_web` e `read_web_page` riutilizzano il trasporto pubblico gia' presente:
  nessun PDF obbligatorio per leggere una pagina. Gli output sono dati non fidati.
- Eliminata la domanda vocale automatica «Ha bisogno d'altro, signore?».
  Le letture intermedie sono silenziose e il contenuto dei siti non viene
  pronunciato, salvo richiesta esplicita di lettura ad alta voce.
- **Risposte vocali ON/OFF** controlla l'audio delle risposte, indipendentemente
  dal microfono. La preferenza resta nel database esistente. «In silenzio» e
  «non voglio sentirle» silenziano anche l'incarico corrente.

## WhatsApp: utilizzo e limiti effettivi

L'app installata e' `WhatsApp.Root`, versione `2.2641.101.0`. La verifica reale
UI Automation ha trovato soltanto il contenitore WebView e i pulsanti della
finestra: nessun campo ricerca/messaggio utilizzabile, anche nella scansione
dei discendenti. Per la scrittura si usa quindi **WhatsApp Web**, attraverso
lo stesso browser controllato gia' utilizzato da JARVIS, con un profilo distinto
in `data/whatsapp-browser-profile`. Non si modificano l'app WhatsApp o Windows.

1. Premi **WhatsApp** dentro JARVIS. Al primo utilizzo collega il telefono dal
   menu WhatsApp → Dispositivi collegati, scansionando il QR della finestra dedicata.
   Non vengono richiesti password o codici a JARVIS. Il collegamento resta locale.
2. Esempio: `Prepara una bozza WhatsApp per Paolo: "Arrivo tra dieci minuti"`.
   JARVIS cerca un contatto con nome esatto e univoco, controlla l'intestazione,
   inserisce il testo e rilegge la bozza. Non preme Invia.
3. Per un invio richiesto esplicitamente, viene preparata/verificata la bozza
   nell'incarico corrente e appare **una conferma per destinatario e testo esatti**.
   Una bozza gia' diversa non viene sovrascritta. Un omonimo non viene scelto a caso.
4. «Mio padre» non identifica automaticamente una persona: JARVIS consulta
   gli alias esplicitamente memorizzati o chiede il nome. Non inventa il testo
   del messaggio. L'associazione di un alias viene mostrata prima di salvarla.

L'invio e' disponibile al pianificatore solo dopo la verifica della bozza nello
stesso incarico. Prima del clic vengono ricontrollati scheda, origine, chat e testo.
La bozza viene consumata prima del tentativo: un esito incerto non viene ripetuto.
La comparsa del messaggio nel DOM non prova la consegna al telefono: il risultato
distingue esplicitamente i due fatti. STOP impedisce i nuovi passi; non annulla
un clic gia' completato. Prima versione: messaggi su una riga, massimo 400 caratteri;
niente allegati, audio, gruppi omonimi, selezione arbitraria o accesso ad altre chat.

La connessione WhatsApp Web reale e' stata aperta senza modificare campi o inviare
messaggi. Il collegamento del telefono richiede l'intervento del proprietario.
Non si dichiara verificato un invio sul suo account prima di quella prova.

## Evidenze e ripetizione

Regressione completa: **206 test superati**, rispetto ai 189 della versione
precedente, con 17 nuovi casi. Log: `data/verification/operational-regression.log`.

- `tests/test_operational_agent.py` e test Qt: richieste composte, dati mancanti,
  ripresa, negazione dell'invio, bozza alterata, risultato incerto, STOP,
  memorizzazione alias e isolamento audio/microfono.
- `scripts/verify_operational_agent.py`: **Qwen reale locale**, file di laboratorio
  realmente letti e orologio Windows reale; ogni effetto esterno e' bloccato.
- `scripts/verify_whatsapp_fixture.py`: **Chrome/CDP reali e Qwen reale** su una
  pagina HTTP locale esplicitamente marcata laboratorio. Verifica preparazione,
  approvazione negata, approvazione concessa, messaggio nel DOM e rifiuto duplicati.
  Non e' un account WhatsApp e non e' presentato come tale.
- Rapporti in `data/verification/operational-agent.json`, `whatsapp-fixture.json`,
  `whatsapp-accessibility.json`, `whatsapp-connection.json`.

Nessuna dipendenza o modello installato. Nessuna migrazione di schema. Prima
delle modifiche: bundle Git verificato e backup SQLite online con quick_check=ok,
con manifest SHA-256 in `data/backups/autonomy-20261115T121931Z`.
Il codice precedente e' al commit `7947cc2944240b21c6a2c55382bade1fe8b6f7fe`;
il rollback del codice non richiede ripristinare/sovrascrivere il database personale.
