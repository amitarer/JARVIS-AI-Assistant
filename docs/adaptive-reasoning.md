# Ragionamento adattivo — 0.7.2

## Comportamento

JARVIS distingue conversazione semplice, calcolo diretto, analisi e incarico
operativo. Le richieste esplicite di logica/vincoli passano direttamente
all'analisi, evitando che il selettore breve esaurisca i token tentando di risolverle.
I messaggi da scrivere/inviare e le risposte a un incarico in sospeso conservano
il percorso operativo e le sue autorizzazioni.

Per i problemi complessi si usa **il Qwen3.5:9b gia' installato**, con thinking
nativo attivo per un solo passaggio e massimo 2.048 token di generazione.
Il canale thinking viene scartato e non entra in UI, voce, database o richieste
successive. Se quel budget termina senza risposta completa, si ripete una volta
l'input originale in modalita' finale, senza riutilizzare pensieri o tool parziali.
Con meno di 20 secondi residui non si avvia un nuovo passaggio approfondito.

Prima di mostrare la soluzione, una seconda chiamata breve controlla il problema,
la **bozza pubblica** e le osservazioni, correggendo incongruenze. La bozza non
viene mostrata in streaming. Il controllo ha un massimo di 25 secondi e non ha
strumenti esecutivi. Lo stato `self_review_status` indica un autocontrollo del
modello, non una prova formale. STOP e il limite complessivo del task restano attivi.

La documentazione del parametro e' [Ollama: thinking](https://github.com/ollama/ollama/blob/main/docs/capabilities/thinking.mdx).
Il supporto e' stato verificato anche sul server locale reale, non solo dedotto dalla documentazione.

## Calcoli e contesto

`calculate` esegue aritmetica razionale esatta mediante AST/Fraction, senza
`eval`, nomi, funzioni, import o accessi al PC. Supporta +, -, *, /, //, %, **
e parentesi, con limiti su lunghezza, profondita', dimensione dei numeri ed
esponenti interi (-12..12). `0.1+0.2` restituisce esattamente `0.3`.
Le frazioni periodiche restano esatte come frazioni; il decimale approssimato
viene marcato separatamente. Un calcolo diretto richiede una sola inferenza
di selezione, poi restituisce il risultato dello strumento.

La richiesta corrente conserva fino a 8.000 caratteri per intero, incluse
negazioni e condizioni iniziali. La cronologia ha un budget di 11.000 caratteri.
Le osservazioni hanno un budget condiviso di 23.000 caratteri, oltre agli avvisi
di abbreviazione: si privilegiano le letture recenti e si conservano inizio e fine
di quelle vecchie. Le informazioni mancanti vengono indicate esplicitamente.

Il recupero delle letture usa ora un formato JSON semplice supportato dal
sampler locale, con nomi limitati agli strumenti di lettura effettivi. Una
classificazione troncata viene riclassificata una volta con schema minimale;
nessuna parte incompleta viene eseguita o riutilizzata come istruzione.

## Prove

- **224 test passati**, inclusi 18 nuovi casi: precisione, limiti, codice
  rifiutato, privacy dello streaming, budget, ripiego, controllo finale,
  richieste lunghe e confini fra analisi e azioni. Log:
  `data/verification/reasoning/regression.log`.
- Quattro richieste uguali a Qwen reale, con database isolati ed effetti
  esterni vietati: prodotto intero, problema logico, calendario con dipendenze,
  saluto. Risposte controllate: **2/4 prima, 4/4 dopo**. Il calendario viene
  validato su durate, precedenze, lavoratori, sovrapposizioni e termine minimo;
  una semplice comparsa del numero atteso non basta. Il confronto riguarda questi casi.
- Nell'ultima esecuzione: calcolo circa 1,1 s, saluto 1,0 s, logica 14,3 s,
  calendario 31,6 s (con ripiego dopo il budget di thinking). I problemi
  complessi privilegiano la qualita' della risposta rispetto alla latenza minima.
- Rapporti: `data/verification/reasoning/before.json` e `after.json`.
  `before-original-grading.json` conserva il primo rapporto, antecedente alla
  correzione del valutatore che contava anche menzioni del nome sbagliato.
  Le risposte pubbliche e i tempi originari sono conservati.
- Ricontrollati con Qwen reale gli incarichi di lettura e i dati WhatsApp
  mancanti; il percorso WhatsApp e' provato su Chrome reale nella pagina locale
  di laboratorio. Nessun messaggio inviato a persone reali.

Nessun modello o dipendenza installato, nessuna migrazione del database e
nessuna modifica al sistema multi-agente di sviluppo. Backup Git verificato
e copia SQLite online consistente in `data/backups/reasoning-20261115T170735Z`.
La versione precedente del codice e' `246e5e4e6df4a642ff37f274a7f86616374d601a`.
