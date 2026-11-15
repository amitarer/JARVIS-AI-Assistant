"""Windows male Italian TTS → actual PCM → controlled output and amplitude meter."""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Signal, Slot
from PySide6.QtMultimedia import QtAudio as QAudio, QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtTextToSpeech import QTextToSpeech, QVoice
from jarvis.voice.windows_synthesis import WindowsSynthesis
from jarvis.voice.pcm import output_pcm, pcm_amplitudes
from jarvis.brain.response_text import final_text


class SpeechOutput(QObject):
    started = Signal()
    finished = Signal()
    level = Signal(float)
    error = Signal(str)
    pcm_ready = Signal(bytes, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        engines = QTextToSpeech.availableEngines()
        engine = "winrt" if "winrt" in engines else "sapi" if "sapi" in engines else None
        self.engine = QTextToSpeech(engine, self) if engine else None
        self.voice_name = "Microsoft Cosimo"
        self.allow_fallback = False
        self.output_device_id = ""
        self.last_device_name = ""
        self.played_microseconds = 0
        self.volume = 0.85
        self.playback_diagnostics = {}
        self.pending = False
        self.active = False
        self.chunks = bytearray()
        self.format = None
        self.sink = self.buffer = None
        self.envelope = []
        self.synthesis_worker = None
        self._synthesis_workers = set()
        self._generation = 0
        self.meter = QTimer(self)
        self.meter.setInterval(20)
        self.meter.timeout.connect(self._meter)
        if self.engine:
            if hasattr(self.engine, "synthesized"):
                self.engine.synthesized.connect(self._pcm)
            self.engine.stateChanged.connect(self._state)
            self.engine.errorOccurred.connect(self._engine_error)

    def voices(self) -> list[str]:
        if not self.engine:
            return []
        return [v.name() for v in self.engine.availableVoices()
                if v.locale().name().startswith("it") and v.gender() == QVoice.Gender.Male]

    def speak(self, text: str) -> bool:
        self.stop()
        if not isinstance(text, str):
            self.error.emit("Il motore vocale accetta soltanto la risposta finale testuale.")
            return False
        text = final_text(text)
        if not text:
            return False
        if not self.engine:
            self.error.emit("Motore vocale Windows non disponibile.")
            return False
        voice = next((v for v in self.engine.availableVoices() if v.name() == self.voice_name
                      and v.locale().name().startswith("it") and v.gender() == QVoice.Gender.Male), None)
        if voice is None:
            if self.allow_fallback:
                available = [v for v in self.engine.availableVoices() if v.locale().name().startswith("it")]
                voice = next((v for v in available if v.gender() == QVoice.Gender.Male), next(iter(available), None))
            if voice is None:
                self.error.emit("Voce italiana locale configurata non disponibile.")
                return False
        if not self.engine.engineCapabilities() & QTextToSpeech.Capability.Synthesize:
            self.error.emit("Il motore vocale non supporta l'audio PCM necessario alla sincronizzazione.")
            return False
        self.engine.setVoice(voice)
        self.engine.setPitch(0.0)
        self.engine.setRate(0.0)
        self.chunks.clear()
        self.played_microseconds = 0
        self.pending = self.active = True
        self.started.emit()
        if hasattr(self.engine, "synthesize"):
            self.engine.synthesize(text[:2000])
        else:
            worker = WindowsSynthesis(text, self.voice_name, self.allow_fallback, self)
            self.synthesis_worker = worker
            self._synthesis_workers.add(worker)
            generation = self._generation
            worker.audio.connect(lambda data, rate, channels, width: self._windows_pcm(data, rate, channels, width)
                                 if generation == self._generation else None)
            worker.error.connect(lambda message: self._synthesis_error(message) if generation == self._generation else None)
            worker.finished.connect(lambda: self._worker_finished(worker))
            worker.start()
        return True

    def _worker_finished(self, worker):
        self._synthesis_workers.discard(worker)
        if self.synthesis_worker is worker:
            self.synthesis_worker = None
        worker.deleteLater()

    def is_stopped(self):
        return all(not worker.isRunning() for worker in self._synthesis_workers)

    def play_pcm(self, data: bytes, fmt: QAudioFormat):
        """Play a local comparison sample, without changing the configured voice."""
        self.stop()
        self.chunks = bytearray(data)
        self.format = fmt
        self.played_microseconds = 0
        self.pending = self.active = True
        self.started.emit()
        self._play()

    def _windows_pcm(self, data: bytes, rate: int, channels: int, width: int):
        if not self.pending:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(rate)
        fmt.setChannelCount(channels)
        fmt.setSampleFormat({2: QAudioFormat.SampleFormat.Int16, 4: QAudioFormat.SampleFormat.Int32}.get(width, QAudioFormat.SampleFormat.Unknown))
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Unknown:
            self._synthesis_error("Formato PCM della voce Windows non supportato.")
            return
        self.format = fmt
        self.chunks.extend(data)
        self._play()

    def _synthesis_error(self, message):
        if self.active:
            self.error.emit(message)
            self.stop()

    def _pcm(self, fmt, data):
        if not self.pending:
            return
        self.format = fmt
        self.chunks.extend(bytes(data))
        if len(self.chunks) > 16_000_000:
            self.error.emit("Risposta vocale troppo lunga.")
            self.stop()

    def _state(self, state):
        if self.pending and hasattr(self.engine, "synthesize") and state == QTextToSpeech.State.Ready:
            QTimer.singleShot(0, self._play)

    def _play(self):
        if not self.pending:
            return
        self.pending = False
        if not self.chunks or self.format is None:
            self.error.emit("Il motore non ha prodotto audio vocale.")
            self.stop()
            return
        data = bytes(self.chunks)
        self.pcm_ready.emit(data, self.format)
        device = next((d for d in QMediaDevices.audioOutputs() if bytes(d.id()).hex() == self.output_device_id), None)
        if self.output_device_id and device is None:
            self.error.emit("Il dispositivo audio selezionato non è più disponibile.")
            self.stop()
            return
        device = device or QMediaDevices.defaultAudioOutput()
        self.last_device_name = device.description()
        if device.isNull():
            self.error.emit("Nessun dispositivo di uscita audio disponibile.")
            self.stop()
            return
        native_format = device.preferredFormat()
        source_format = self.format
        try:
            data = output_pcm(data, self.format, native_format)
        except ValueError:
            self.error.emit("Formato PCM non valido: riproduzione arrestata.")
            self.stop()
            return
        self.format = native_format
        self.playback_diagnostics = {"source_rate": source_format.sampleRate(),
                                     "source_channels": source_format.channelCount(),
                                     "output_rate": native_format.sampleRate(), "output_channels": native_format.channelCount(),
                                     "output_format": str(native_format.sampleFormat()), "volume": self.volume,
                                     "requested_buffer_ms": 200, "output_device": self.last_device_name}
        self.envelope = pcm_amplitudes(data, self.format)
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(data))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.sink = QAudioSink(device, self.format, self)
        sink = self.sink
        sink.setVolume(max(0.0, min(1.0, self.volume)))
        sink.setBufferSize(native_format.bytesForDuration(200000))
        sink.stateChanged.connect(self._play_state)
        sink.start(self.buffer)
        if self.sink is not sink:
            return
        if sink.error() != QAudio.Error.NoError:
            self.error.emit("Impossibile riprodurre l'audio sul dispositivo selezionato.")
            self.stop()
            return
        self.playback_diagnostics["actual_buffer_bytes"] = sink.bufferSize()
        self.meter.start()

    def _meter(self):
        if self.sink and self.envelope:
            self.played_microseconds = self.sink.processedUSecs()
            index = int(self.sink.processedUSecs() / 20000)
            self.level.emit(self.envelope[min(index, len(self.envelope) - 1)])

    @Slot()
    def _play_state(self):
        if not self.active or self.sink is None:
            return
        state = self.sink.state()
        if state == QAudio.State.IdleState and self.active:
            self.stop()
        elif state == QAudio.State.StoppedState and self.sink and self.sink.error() != QAudio.Error.NoError:
            self.error.emit("Riproduzione audio interrotta dal dispositivo.")
            self.stop()

    def _engine_error(self, error, message):
        if self.active:
            self.error.emit("Sintesi vocale Windows non riuscita.")
            self.stop()

    def stop(self):
        self._generation += 1
        was_active = self.active
        self.pending = self.active = False
        self.meter.stop()
        if self.engine:
            self.engine.stop()
        if self.synthesis_worker is not None:
            try:
                if self.synthesis_worker.isRunning():
                    self.synthesis_worker.cancel()
            except RuntimeError:
                pass
            self.synthesis_worker = None
        sink, buffer = self.sink, self.buffer
        self.sink = self.buffer = None
        if sink:
            self.played_microseconds = max(self.played_microseconds, sink.processedUSecs())
            sink.stop()
            sink.deleteLater()
        if buffer:
            buffer.close()
            buffer.deleteLater()
        self.chunks.clear()
        self.level.emit(0.0)
        if was_active:
            self.finished.emit()
