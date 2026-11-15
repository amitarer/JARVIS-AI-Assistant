# Fusione — modulo 1: stato Ollama in sola lettura

Implementato sul branch `codex/jarvis-fusion`, nel worktree
`.development-state/fusion-worktree/`. La versione stabile nella root rimane
al commit `3346034ef9d329893ce644a98a7df84f043ba40f` e non è stata sostituita.

## Risultato

Un pannello **Modello**, nella stessa finestra JARVIS, mostra:

- Modello configurato e modelli effettivamente installati.
- Capacità dichiarate dal server, senza abilitarle automaticamente come strumenti.
- Contesto nativo, contesto configurato e contesto di esecuzione, separatamente.
- Caricamento effettivo, ripartizione CPU/GPU e VRAM attribuita al modello,
  quando Ollama fornisce i dati. I dati mancanti restano «non verificati».
- Timestamp della rilevazione; aggiornamento sul worker Qt esistente.

Il codice adatta due funzioni pure di PersonalJarvis e usa un solo trasporto:
`jarvis.brain.ollama.OllamaProvider`. Il normale percorso delle risposte mantiene
le sue due letture di verifica e non effettua scansioni runtime aggiuntive.
L'inventario aggiunge `/api/ps` solo nella diagnostica provider/pannello.
Quella lettura opzionale ha un massimo di tre secondi e conserva la cancellazione.

Nessun modello viene caricato, scaricato, cancellato o scaricato dalla memoria
da questo modulo. Nessun cambiamento a voce, wake word, rendering, permessi,
database, server Ollama, API cloud o dipendenze dell'assistente.

## Verifiche effettuate

- Baseline stabile: **176 test superati** prima della modifica.
- Branch di fusione: **189 test superati**, inclusi 13 nuovi test su metadati
  malformati, dati sconosciuti, booleani/NaN/infinito, cancellazione,
  timeout parziale, alias `:latest`, assenza di download e pannello asincrono.
- Il test harness importa il codice dal worktree e riutilizza in sola lettura
  Node/Git già verificati nella root per i test preesistenti dell'orchestratore.
  Non installa un secondo ambiente e non modifica i percorsi di import globali.
- Server reale: GET `/api/tags`, POST `/api/show` per il modello configurato,
  GET `/api/ps`. **Zero richieste di generazione o mutazione**, zero accessi al
  database personale. Rilevazione circa 0,047 s: misura di diagnostica, non
  un benchmark della velocità di ragionamento.
- Riscontro: `qwen3.5:9b` presente, capacità completion/vision/tools/thinking,
  contesto nativo 262.144, contesto configurato 16.384. Nella rilevazione il
  modello non era caricato; contesto runtime e VRAM restano non verificati.
- Pannello Qt verificato con gli stessi metadati reali, senza acquisire audio.

Evidenze nella root:
`.development-state/fusion-verification/ollama-inventory.json`,
`model-panel.png`, `.development-state/fusion-verification-tests.log`.

## Licenze e confezionamento

Copiati integralmente LICENSE e NOTICE Apache-2.0 di PersonalJarvis. I file
adattati dichiarano provenienza e modifiche. Il manifest di setuptools include
quegli avvisi nelle future distribuzioni; percorsi e TOML sono stati validati.

La costruzione locale del wheel non è stata completata perché la `.venv`
esistente non contiene `setuptools.build_meta`. Non sono stati installati
strumenti di build per aggirare questo limite e non è stata pubblicata alcuna
release. Questo limite riguarda la verifica del pacchetto, non l'esecuzione dei
189 test o il client Ollama già verificato.

## Ripetere la verifica dal worktree

```powershell
C:/Users/VGgot/Desktop/JARVIS/.venv/Scripts/python.exe -B -m unittest tests.test_ollama_inventory -v
C:/Users/VGgot/Desktop/JARVIS/.venv/Scripts/python.exe -B scripts/verify_fusion_ollama.py --project-root C:/Users/VGgot/Desktop/JARVIS
```

Non fare `pip install -e` dal worktree. L'integrazione nella versione stabile
e il Workspace agentico completo non sono attivati da questo modulo.
Vedi [piano di fusione](../FUSION_PLAN.md) per i moduli successivi.
