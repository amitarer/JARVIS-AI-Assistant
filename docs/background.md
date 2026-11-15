# JARVIS in background e overlay su wake word

Avvio ordinario dalla cartella del progetto:

```powershell
.\.venv\Scripts\pythonw.exe -m jarvis
```

L'applicazione avvia il microfono locale, mostra soltanto l'icona nell'area di notifica e lascia nascosti dashboard e overlay. L'ascolto continua mentre si usano altre applicazioni e mentre la dashboard è chiusa. Si tratta di un'applicazione in esecuzione, non di un servizio Windows.

## Flusso

1. In attesa: openWakeWord elabora localmente la parola «Jarvis»; nessun overlay visibile.
2. Wake word: compare il cervello trasparente, sopra le finestre senza sottrarre il focus.
3. Richiesta: trascrizione locale e Qwen; l'overlay indica ascolto ed elaborazione, senza mostrare il reasoning.
4. Operazione: JARVIS pronuncia l'intenzione; alla fine della frase nasconde l'overlay e solo dopo sblocca lo strumento.
5. Esecuzione: l'overlay resta nascosto, anche se seguono ulteriori passaggi del modello. Le conferme sensibili hanno una finestra separata in primo piano.
6. Esito: risposta vocale senza riapertura dell'overlay dopo le azioni. Se non c'erano azioni, il cervello resta visibile durante la risposta e si chiude al termine.
7. Ritorno alla wake word: si può richiamare con «Jarvis»; nessun pannello resta aperto.

La modalità predefinita 0.4.3 termina le risposte vocali con «Ha bisogno d'altro, signore?» e ascolta richieste successive per 30 secondi senza ripetere il nome. «No, grazie» o «basta» tornano all'attesa di «Jarvis». La conversazione continua si può disattivare nelle impostazioni. Durante il parlato dell'assistente, il riconoscimento è sospeso per escludere la sua voce; l'audio non viene inviato continuamente a Ollama o al cloud.

## Controlli sempre disponibili

Click sull'icona: apre la conversazione e le impostazioni. Click destro: microfono ON/OFF, STOP ed **Esci da JARVIS**. Icona ciano = microfono attivo; icona grigia = disattivato. Il tooltip riporta lo stato effettivo o l'errore di dispositivo/modello.

Chiudere la dashboard con X la nasconde, lasciando attivo il processo. Per chiudere realmente scegliere **Esci da JARVIS**, che ferma acquisizione, worker e voce e libera la scorciatoia globale.

**Ctrl+Alt+Pausa** richiede STOP anche quando la dashboard è nascosta. La registrazione è limitata al processo, senza modifiche a Windows; se la combinazione è già occupata, resta disponibile lo STOP dal tray. Esc resta disponibile nella dashboard.

Opzioni:

```powershell
.\.venv\Scripts\python.exe -m jarvis --dashboard
.\.venv\Scripts\pythonw.exe -m jarvis --no-microphone
```

`config/defaults.json` contiene `desktop.start_hidden=true`, `desktop.auto_listen=true` e `voice.continuous_conversation=true`. Il modello wake word, il motore TTS e Ollama rimangono quelli già configurati. Nessuna nuova dipendenza o servizio installato. Se il sistema non offre il tray, la dashboard resta visibile per garantire i controlli.

## Verifica

59 test automatici superati. La prova `scripts/verify_background.py` ha confermato, su Windows e con microfono reale:

- tray disponibile, dashboard e overlay nascosti in attesa;
- acquisizione di 12.640 campioni reali a 16 kHz e fase `wake`;
- chiusura della dashboard senza interrompere il microfono;
- registrazione e successivo rilascio dello STOP globale;
- arresto del microfono all'uscita.

La prova automatica non simula una pronuncia riuscita: verifica l'ascolto reale in attesa. I test del controller verificano separatamente l'ordine intenzione vocale → fine audio → overlay nascosto → autorizzazione all'esecuzione e impediscono la riapertura durante i passaggi successivi.

Report: `data/verification/background-mode.json`.
