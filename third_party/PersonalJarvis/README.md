# PersonalJarvis: attribuzione delle parti adattate

Sorgente fornita dall'utente: `PersonalJarvis-main.zip`, versione dichiarata
2.7.1. Archivio SHA-256:
`b29edfaf0a117bd31697e511f66b451014959074c75ce6ae8cf08e6581e3b306`.

Progetto originale: https://github.com/PersonalJarvis/PersonalJarvis
Copyright 2026 Ruben Lütke e contributori. Licenza Apache-2.0.
`LICENSE` e `NOTICE` in questa cartella sono copie integrali dei corrispondenti
file nell'archivio fornito. Non è stata scaricata una versione alternativa.

Parti adattate: confronto dei nomi modello (`same_model`) ed estrazione del
contesto nativo (`native_context_length`) da
`jarvis/brain/ollama_inventory.py`, SHA-256 originale
`c01facfd57b38761c491e8bf25b9ea5d8052c3ba2ae160704f637bbc36fe1b60`.

Destinazione: `jarvis/brain/ollama_inventory.py` di JARVIS.
Modifiche: validazione più rigorosa di booleani, valori non finiti e dimensioni;
API sincrona compatibile con il trasporto già presente; stato runtime ignoto
distinto da non caricato; formatter italiano. Niente client HTTP duplicato,
cache globale, download, alias, cancellazione o unload.

Nessun asset, modello vocale/VAD, runtime Piper, servizio web o dipendenza
cloud di PersonalJarvis è stato copiato. I riferimenti a componenti bundled
nel NOTICE originale descrivono il progetto di origine, non nuovi asset
incorporati in JARVIS. L'attribuzione non cambia la licenza degli altri file
preesistenti del progetto.
