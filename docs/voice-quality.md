# Qualità vocale e confronto locale — 14 novembre 2026

## Motore effettivo

La voce attiva resta **Microsoft Cosimo**, italiana maschile. Il motore effettivo è `Windows.Media.SpeechSynthesis.SpeechSynthesizer` (WinRT), chiamato attraverso lo script fisso `scripts/synthesize_windows.ps1`. L'audio WAV viene decodificato in PCM, convertito al formato nativo del dispositivo e riprodotto con `QAudioSink`.

Il binding Qt installato enumera le voci Windows ma non espone `synthesize()`/`synthesized`, perciò l'adattatore WinRT produce i campioni reali. Le impostazioni Qt di pitch/velocità non si trasferivano all'adattatore; il parlato effettivo era già quello nativo Windows. Ora le impostazioni Qt sono neutre anche per un eventuale backend che le supporti: nessun rallentamento o abbassamento artificiale del timbro.

## Misure sulla frase richiesta

«Buongiorno, Gae. Sono Jarvis, il tuo assistente personale. Tutti i sistemi sono operativi. Come posso aiutarti?»

| Voce presente sul PC | Formato origine | Durata | Picco origine | Campioni saturati |
|---|---|---|---|---|
| Microsoft Cosimo, maschile | 16000 Hz, mono, PCM16 | 10,795 s | −3,04 dBFS | 0 |
| Microsoft Elsa, femminile di riferimento | 16000 Hz, mono, PCM16 | 11,010 s | −4,37 dBFS | 0 |

Entrambi i WAV sono generati localmente dal motore Windows, con la stessa frase, senza effetti. Le durate dopo conversione a 48000 Hz stereo coincidono con gli originali. Il dettaglio riproducibile è in `data/voice-comparison/manifest.json`.

Queste misure escludono clipping digitale e un errore di velocità per questi due campioni. Non dimostrano l'assenza di artefatti nella voce, distorsioni analogiche o problemi del dispositivo. L'ascolto A/B serve a separare queste cause. Il carattere robotico può essere già nel WAV WinRT: cambiare soltanto il player non rende neurale o più naturale il modello Windows.

## Correzioni al percorso audio

- Calcolo PCM in float64: corretto un overflow riproducibile nella quantizzazione PCM32. In precedenza un picco positivo poteva diventare `INT32_MIN`; l'uscita attuale ME6S usa float32, quindi questo difetto non dimostra la causa del problema segnalato su quel dispositivo.
- Resampling polifase con frequenze esplicite; durata, frequenza del parlato e canali preservati.
- Attenuazione soltanto in caso di picchi superiori a −1,5 dBFS dopo il resampling. Nessun aumento automatico dei segnali deboli, compressore o modifica del pitch.
- Volume applicativo iniziale 85%, regolabile nel comparatore. Nessuna modifica al volume di sistema.
- Buffer richiesto di 200 ms per la riproduzione; formato nativo WASAPI del dispositivo, inizialmente ME6S a 48000 Hz, stereo float32. Il buffer effettivo è riportato dalla verifica hardware.
- STOP rilascia sink e buffer; le risposte di una sintesi annullata non possono riavviare il parlato dopo l'arrivo di una nuova richiesta.

## Ascolto comparativo

```powershell
.\.venv\Scripts\python.exe -m jarvis --voice-compare
```

Selezionare prima **Microsoft Cosimo**, poi **Microsoft Elsa**. Elsa è un riferimento femminile per la qualità di sintesi, non una proposta maschile per la voce definitiva.

- **Originale · player Windows** riproduce il WAV WinRT tramite il player Windows, sull'uscita predefinita di sistema.
- **JARVIS · PCM corretto** riproduce il campione attraverso il percorso audio dell'app, sull'uscita selezionata. Il cursore regola soltanto questo player.
- **STOP audio** interrompe l'ascolto. Il comparatore non cambia la voce configurata, non avvia il microfono e non accede a Ollama o SQLite.

Per evitare che un'altra finestra del test vocale riconosca la parola «Jarvis» contenuta nei campioni, disattivare il microfono di quella finestra durante il confronto. Riattivarlo al termine.

File separati:

```text
data/voice-comparison/cosimo_originale.wav
data/voice-comparison/cosimo_48k.wav
data/voice-comparison/elsa_originale.wav
data/voice-comparison/elsa_48k.wav
```

Se Cosimo è robotico anche in **Originale · player Windows**, il limite è prevalentemente nella sintesi. Se il riferimento è pulito e JARVIS distorce, confrontare la stessa uscita audio in entrambi i percorsi e segnalare la differenza. Se la distorsione dipende dal dispositivo, provare un'altra uscita nel comparatore senza modificare il sistema.

## Candidati per la voce definitiva — non installati

**Chatterbox Multilingual** supporta l'italiano e una voce condizionata da un campione audio. È il candidato da valutare per naturalezza e personalità maschile, con un riferimento italiano appropriato. La profondità del timbro andrebbe ottenuta dalla voce scelta, non rallentando il WAV.

Esistono però vincoli concreti: il manifest corrente fissa NumPy <2 e PyTorch/Torchaudio 2.6 su Python 3.12. La `.venv` JARVIS contiene NumPy 2.5.4 e SciPy 1.18.1, che richiede NumPy >=2. Inoltre la RTX 5070 Ti richiede di verificare una build PyTorch adatta a Blackwell: il supporto è stato introdotto dopo 2.6. Il README attuale segnala che il progetto non è più mantenuto da agosto 2026. Un'installazione diretta potrebbe quindi danneggiare l'ambiente vocale già funzionante. Nessun downgrade o sostituzione è stato eseguito.

**Kokoro `im_nicola`** è una voce italiana maschile esistente per il modello da 82 milioni di parametri. La variante ONNX riutilizzerebbe NumPy e ONNX Runtime già presenti; richiederebbe `kokoro-onnx`, `phonemizer`, `espeakng-loader` e relative dipendenze, oltre ai pesi e alle voci. Il loader include il supporto eSpeak nella libreria: l'obiettivo è evitare installazioni globali o modifiche a Windows. La qualità italiana va comunque ascoltata: la scheda delle voci segnala dati di addestramento limitati.

Proposta: dopo approvazione delle nuove installazioni, produrre un campione **Kokoro im_nicola** e, dopo aver risolto il piano di compatibilità, uno **Chatterbox Multilingual**, mantenendoli nel comparatore. Solo dopo l'ascolto e l'approvazione della voce scelta si collegherà il nuovo provider a JARVIS e si salverà la scelta nelle impostazioni.

Fonti primarie consultate:

- [Chatterbox: progetto, lingue e stato di manutenzione](https://github.com/resemble-ai/chatterbox)
- [Chatterbox: dipendenze dichiarate](https://github.com/resemble-ai/chatterbox/blob/master/pyproject.toml)
- [PyTorch 2.7 e supporto Blackwell](https://pytorch.org/blog/pytorch-2-7/)
- [Kokoro: voci italiane](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md#italian)
- [Kokoro ONNX: dipendenze](https://github.com/thewh1teagle/kokoro-onnx/blob/main/pyproject.toml)

## Ripetizione delle verifiche

```powershell
.\.venv\Scripts\python.exe -B scripts/compare_voices.py
.\.venv\Scripts\python.exe -B -m unittest tests.test_pcm -v
.\.venv\Scripts\python.exe -B scripts/verify_voice_comparison.py
```

L'ultimo script esegue una breve verifica **muta** del driver audio e dell'interruzione, senza microfono. Non certifica la qualità percepita dagli altoparlanti; quella richiede l'ascolto del confronto.
