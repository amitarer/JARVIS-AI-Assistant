# Conversazione autonoma ChatGPT — 0.5.0

Questa modalità realizza il compito «inizia a chattare con ChatGPT finché non dico stop». Gli strumenti desktop preesistenti continuano a gestire scrittura, clic e scorciatoie nelle applicazioni Windows. La sessione autonoma qui descritta è circoscritta alla conversazione ChatGPT del browser dedicato; non è un permesso generale sul computer.

## Avvio e controllo

La selezione JSON di Qwen distingue `autonomous_chat` dall'apertura del sito. `start_autonomous_chat` richiede un obiettivo concreto e una conferma iniziale attraverso la policy esistente. La conferma vale per la sessione fino a STOP, non viene ripetuta per ogni messaggio. Senza argomento, l'obiettivo è una conversazione generale in italiano. Il codice convalida i parametri; negazioni e domande informative non vengono trasformate deliberatamente in avvii.

Solo l'esecuzione autorizzata dello strumento iniziale emette una `SessionPermission`, legata a ID attività, evento di cancellazione e obiettivo. `TaskExecutor` non può avviarsi senza questa autorizzazione. Il registro accetta il grant solo per `browser_chat_open`, `browser_chat_observe`, `browser_chat_send` e `browser_chat_reply`; il grant non autorizza strumenti desktop, shell, cronologia o file. Il permesso viene ricontrollato immediatamente prima di un effetto e revocato all'uscita.

Il ciclo apre una scheda nuova, osserva il campo, produce con Qwen un messaggio coerente con l'obiettivo, inserisce testo, clicca il pulsante verificato e controlla che il messaggio appaia nella conversazione. Attende poi un messaggio dell'assistente stabile e la fine dello stato di generazione. Ogni lettura e azione attraversa il registro e viene registrata in SQLite. Il messaggio generato e la risposta sono conservati come evidenze dell'operazione; non vengono importati nella cronologia ordinaria come istruzioni dell'assistente.

La modalità esplicita fino a STOP non ha una durata complessiva o un numero fisso di turni. Mantiene timeout separati: generazione locale 60 secondi, invio 60 secondi, risposta 180 secondi e singola chiamata browser al massimo 15 secondi. Tra i turni attende 5 secondi interrompibili. I timeout ordinari restano invariati per le altre attività.

STOP vocale, pulsante, testo nella dashboard e Ctrl+Alt+Pausa impostano lo stesso evento di cancellazione. Il microfono resta in modalità solo-arresto durante la sessione; le altre parole non diventano nuovi comandi. Whisper usa una decodifica breve locale per STOP. L'arresto vocale comprende il tempo di riconoscimento, mentre il pulsante e la scorciatoia non lo richiedono. Non vengono letti a voce tutti gli scambi, evitando che il TTS copra STOP. Il codice non annulla messaggi già inviati e non ripete un invio di esito incerto.

## Browser e account

`BrowserController` usa Chrome con `data/browser-profile`, una porta di debugging casuale su loopback e una scheda posseduta dalla sessione. Il trasporto WebSocket usa .NET già disponibile in Windows PowerShell. Playwright non era installato e non è stato aggiunto. Il browser personale preesistente non viene collegato. Chrome richiede un profilo distinto per il remote debugging: vedere le [indicazioni ufficiali Chrome](https://developer.chrome.com/blog/remote-debugging-port) e il [protocollo CDP](https://chromedevtools.github.io/devtools-protocol/).

Gli adapter JavaScript sono file fissi del repository. Il modello genera soltanto testo del messaggio e parametri strutturati, mai codice da eseguire. Ogni chiamata verifica l'origine `https://chatgpt.com` e la scheda corrente; una navigazione su un'altra origine blocca l'operazione. L'adapter legge il campo di composizione e gli ultimi messaggi del contenitore principale, non altre conversazioni, password, cookie o storage. Non sovrascrive una bozza esistente.

Il primo accesso si effettua manualmente nel profilo dedicato. CAPTCHA e verifiche restano manuali. Login non completato, pagina non compatibile, campo non disponibile o limiti del servizio tengono le azioni in attesa o le sospendono con una spiegazione. In caso di invio/risposta incerti, la sessione non invia altro e attende STOP: verificare la pagina e riavviare il compito. Cambiamenti dell'interfaccia ChatGPT possono richiedere un aggiornamento dei selettori. La verifica DOM dell'invio non costituisce da sola una ricevuta interna del server.

## Prove eseguite

- Test di permessi legati alla singola attività, revoca prima dell'effetto, assenza di approvazioni ripetute, rifiuto di strumenti fuori ambito, blocco senza obiettivo approvato e mancato reinvio dopo errore incerto.
- Test di continuazione oltre la deadline ordinaria, STOP testuale durante worker occupato e STOP vocale che ignora discorsi non pertinenti.
- `scripts/verify_pc_control.py`: finestra Windows reale, clic, testo Unicode, scorciatoie e chiusura della sola finestra di prova.
- `scripts/verify_autonomous_chat.py`: Chrome e Qwen reali, tre turni completi su una pagina locale, una sola conferma e nessun invio dopo STOP. Report `data/verification/autonomous-chat.json`. Le directory del browser di prova restano sotto `data/test-runs` per revisione; Chrome può proteggere alcune proprie directory cache su Windows.
- Qwen reale: avvio sessione con/senza argomento, semplice apertura sito, negazione e domanda informativa distinti correttamente. Report `data/verification/autonomy-routing.json`.
- Modello STT reale su voce Cosimo sintetica «Stop», senza microfono né riproduzione audio: `data/verification/voice-stop.json`. Questo non certifica il riconoscimento della pronuncia dell'utente.
- ChatGPT reale controllato in sola lettura: il profilo dedicato richiede l'accesso manuale. Nessun messaggio è stato inviato al servizio durante lo sviluppo. Report `data/verification/chatgpt-browser-readiness.json`.
