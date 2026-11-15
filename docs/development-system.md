# Codex + Ruflo per JARVIS

Configurazione locale approvata e collaudata il **15 novembre 2026**.
Il flusso reale è: Ruflo coordina i metadati; un runner Python assegna il
lavoro a processi Codex, verifica i test e richiede una revisione indipendente.
La sola registrazione `agent_spawn` non viene considerata esecuzione di un agente.

## Uso e stato attuale

Aprire **`Sviluppo_JARVIS.bat`** per il pannello con ruoli, PID effettivi,
test, risorse, revisione, riepilogo e **STOP sviluppo**.
Il primo collaudo è concluso: il pannello mostra il risultato e impedisce di
riavviarlo accidentalmente. Non ci sono altri task autorizzati da eseguire.
Il pannello si apre anche dal pulsante **Agenti** nella dashboard JARVIS.
Gli agenti del collaudo sono terminati: i PID mostrati sono ricevute storiche,
non processi attualmente al lavoro. Il solo avvio dell'assistente non avvia agenti.

| Ruolo collaudato | Lavoro svolto nel ciclo |
| --- | --- |
| Coordinatore | Ha letto la richiesta e scelto i ruoli necessari dal catalogo |
| Python | Ha corretto il file assegnato nel worktree isolato |
| Testing | Ha eseguito i test e raccolto gli esiti reali |
| Sicurezza | Ha revisionato la modifica indipendentemente dall'autore |

Questi processi usano Codex con il login esistente; Ollama/Qwen resta il
motore dell'assistente vocale. Il catalogo contiene 14 specialità predisposte,
ma il collaudo ha effettivamente avviato soltanto i quattro ruoli indicati.

```powershell
# Leggere lo stato senza avviare agenti
.\development\development-status.ps1
# Arrestare un ciclo attivo attraverso il suo flag locale
.\development\stop-development.ps1
# Avvio esplicito di un solo ciclo, se esiste un task autorizzato pendente
.\development\start-development.ps1 -Once
```

L'autorizzazione attuale copre strumenti locali, baseline Git, configurazione
e **una prova isolata**. Il runner implementato accetta soltanto
`DEV-SMOKE-001`; non è un esecutore generico del backlog JARVIS.
La pianificazione continuativa, l'avvio con Windows e il native autopilot di
Ruflo sono disattivati. I nuovi problemi possono diventare proposte: non
generano attività eseguibili automaticamente. Non occorre configurare ogni
agente: il coordinatore sceglie i ruoli dal catalogo.

## Risultato misurato

Run: `run-20261115-104405-50f1f6`, stato `ready_for_review`.

- Quattro ruoli realmente eseguiti: coordinatore, Python, testing, sicurezza.
  Cinque invocazioni Codex: il tester è stato ripetuto dopo un blocco iniziale
  del sandbox. Le fasi sono sequenziali, con un solo autore del codice.
- Una fixture sintetica accettava erroneamente `bool` come intero. Il test
  iniziale fallisce realmente; la correzione passa i due test di accettazione,
  compresi sottotipi di `int`, limiti e valori non interi. Nessun bug JARVIS
  viene dedotto da questo difetto creato appositamente per il collaudo.
- Il revisore indipendente approva la modifica senza rilievi.
- Branch della fixture: `development/DEV-SMOKE-001`, commit candidato
  `c6aa12e725acc5fbc07590c13ee44a56eb7554da`.
- Report, patch, output e ricevute JSONL sono sotto
  `.development-state/runs/run-20261115-104405-50f1f6/`.
  Il codice è in `.development-state/worktrees/DEV-SMOKE-001/`.
- Il pulsante STOP è stato premuto automaticamente in una prova Qt reale:
  il figlio controllato termina in **0,078 s**, un processo estraneo sopravvive.
  Evidenza: `.development-state/supervision-verification.json`.
- Regressione del progetto: **170 test superati**.

La prima configurazione ha richiesto recuperi durante lo stesso collaudo:
contabilità dei token in cache, avvio dei processi annidati nel sandbox e
riconoscimento delle notifiche di riconnessione seguite da completamento.
I fallimenti precedenti e le ricevute originali restano conservati; il report
descrive ogni recupero. `operator_requested` nei vecchi eventi indica
l'invocazione esplicita del recupero da parte di Codex durante il setup,
non una nuova approvazione scritta dall'utente.

## Isolamento e limiti

I comandi degli agenti e Ruflo girano nel sandbox Windows MXC con accesso ai
soli percorsi assegnati e rete dei comandi disabilitata. Sono verificati con
canary sintetici il rifiuto delle letture esterne e delle scritture vietate,
la protezione dei test e l'avvio dei sottoprocessi consentiti.
Il client Codex riutilizza internamente il login esistente per l'inferenza;
non vengono esportate credenziali o passate chiavi API agli ambienti shell.

Il Windows Job Object applica al gruppo controllato **8 GiB RAM e CPU 25%**,
con terminazione dei figli alla chiusura. Il runner limita il ciclo a 20 minuti,
ogni agente a 5 minuti, ogni test a 3 minuti, le invocazioni Codex a 8 e
i tentativi di correzione a 2. STOP riguarda soltanto i processi posseduti.
La VRAM e le chiamate interne di un singolo turno Codex non hanno un limite
rigido disponibile. I 100.000 token di input non in cache più output sono
una soglia misurata tra invocazioni, non un tetto del singolo turno.
I log dei singoli processi sono limitati; la conservazione 14 giorni/256 MiB
è un parametro predisposto per un futuro runner continuo, senza cancellazione
periodica automatica in questa implementazione a ciclo singolo.

Non sono avviati Ollama ausiliario o inferenza GPU per questa prova.
Le funzioni voce, SQLite e automazione di JARVIS restano nel progetto esistente.
Il runner non esegue merge, push, release o modifiche ai servizi Windows.
L'integrazione del setup in `main` è eseguita separatamente da Codex in seguito
alla richiesta dell'utente di applicare il lavoro completato.

## MCP e Codex

`.codex/config.toml` registra un bridge MCP locale di sola lettura.
`jarvis_development_status` legge il report reale del runner; i sei strumenti
Ruflo espongono lo stato del proprio server di coordinamento. Ogni processo
Ruflo ha il proprio ciclo di vita: usare il primo strumento o il pannello per
lo stato effettivo del ciclo JARVIS. Le richieste raw a `agent_execute`,
`agent_spawn` e autopilot sono rifiutate dal bridge.

Il bridge è stato verificato con handshake, catalogo, lettura stato e rifiuto
di un'esecuzione non consentita, senza altre chiamate al modello.
La sessione Codex già aperta non acquisisce strumenti nuovi retroattivamente:
serve ricaricare l'estensione/aprire una nuova sessione nel progetto attendibile.
Su questa installazione il comando di gestione `codex mcp get` non carica da
solo il file locale. Questo launcher applica i soli override MCP del progetto,
verificati dal CLI, senza scrivere la configurazione globale:

```powershell
.\.venv\Scripts\python.exe -B development/codex_project.py mcp get ruflo --json
# Aprire una sessione CLI con gli stessi strumenti
.\.venv\Scripts\python.exe -B development/codex_project.py
```

## Installazione riproducibile

Tutti gli strumenti stanno in `.devtools/`, fuori dalla `.venv` di JARVIS:
Node **24.22.3**, MinGit **2.56.1.windows.1**, Ruflo **3.77.1**.
Gli archivi Node/Git sono verificati con SHA-256 ufficiali; versioni e checksum
sono fissati in `development/locks/portable-tools.json`. Il wrapper Ruflo
pubblicato corrisponde al wrapper nell'archivio esaminato.

Il lockfile npm fissa le dipendenze e le integrità. Il ripristino usa `npm ci`,
senza dipendenze opzionali e con tutti gli script lifecycle disabilitati
(47 script inventariati, nessuno eseguito). Un override locale Zod **4.6.6**
corregge l'advisory rilevato dal primo audit; i contratti MCP esposti sono
stati ricollaudati. L'audit finale restituisce **0 vulnerabilità note**,
senza costituire una garanzia di assenza di ogni difetto del pacchetto.

Gli script di avvio non installano né aggiornano software. Per ripristinare
esplicitamente gli strumenti già approvati:

```powershell
.\.venv\Scripts\python.exe -B development/bootstrap_tools.py
.\.venv\Scripts\python.exe -B development/install_ruflo.py
```

Le prove senza inferenza si possono ripetere con `development/verify_ide_mcp.py`,
`development/verify_mcp_contracts.py` e `development/verify_supervision.py`.
Lo stato temporaneo è escluso da Git. Il setup iniziale è conservato sul branch
`codex/ruflo-setup`; il lavoro completato viene integrato anche in `main`
su richiesta dell'utente. La correzione della fixture sintetica rimane nel suo
repository di prova e non viene inserita nel codice dell'assistente.
