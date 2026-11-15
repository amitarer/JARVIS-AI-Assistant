"""Device capture and streaming conversion to 16 kHz mono PCM without disk IO."""

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtMultimedia import QtAudio as QAudio, QAudioFormat, QAudioSource, QMediaDevices


class PcmConverter:
    def __init__(self, sample_rate: int, channels: int, sample_format):
        self.rate, self.channels, self.format = sample_rate, channels, sample_format
        self.buffer = np.empty(0, np.float32)
        self.position = 0.0
        self.byte_remainder = b""
        self.lowpass = self.filter_state = None
        self.channel_rms = []
        if sample_rate > 16000:
            from scipy.signal import butter
            self.lowpass = butter(6, 7200, fs=sample_rate, output='sos')
            self.filter_state = np.zeros((len(self.lowpass), 2))

    def convert(self, data: bytes) -> np.ndarray:
        types = {QAudioFormat.SampleFormat.Int16: (np.dtype('<i2'), 32768),
                 QAudioFormat.SampleFormat.Int32: (np.dtype('<i4'), 2147483648),
                 QAudioFormat.SampleFormat.Float: (np.dtype('<f4'), 1),
                 QAudioFormat.SampleFormat.UInt8: (np.dtype('u1'), 128)}
        if self.format not in types:
            raise ValueError("Formato audio non supportato.")
        dtype, divisor = types[self.format]
        raw = self.byte_remainder + data
        frame_size = dtype.itemsize * self.channels
        length = len(raw) - len(raw) % frame_size
        self.byte_remainder = raw[length:]
        if not length:
            return np.empty(0, np.int16)
        samples = np.frombuffer(raw[:length], dtype=dtype).astype(np.float32)
        if self.format == QAudioFormat.SampleFormat.UInt8:
            samples -= 128
        channels = np.nan_to_num(samples / divisor).reshape(-1, self.channels)
        self.channel_rms = np.sqrt(np.mean(channels.astype(np.float64) ** 2, axis=0)).tolist()
        samples = channels.mean(axis=1)
        if self.rate == 16000:
            return (np.clip(samples, -1, 1) * 32767).astype(np.int16)
        if self.lowpass is not None:
            from scipy.signal import sosfilt
            samples, self.filter_state = sosfilt(self.lowpass, samples, zi=self.filter_state)
        self.buffer = np.concatenate((self.buffer, samples))
        step = self.rate / 16000
        positions = np.arange(self.position, max(self.position, len(self.buffer) - 1), step)
        output = np.interp(positions, np.arange(len(self.buffer)), self.buffer) if positions.size else np.empty(0)
        next_position = float(positions[-1] + step) if positions.size else self.position
        consumed = min(int(next_position), max(0, len(self.buffer) - 1))
        self.buffer = self.buffer[consumed:]
        self.position = next_position - consumed
        return (np.clip(output, -1, 1) * 32767).astype(np.int16)


class AudioInput(QObject):
    frames = Signal(object)
    level = Signal(float)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.device = None
        self.converter = None
        self.enabled = False
        self.connected = False
        self.device_name = ""
        self.captured_samples = 0
        self.rms = self.peak_rms = 0.0

    def start(self, device_id: str = ""):
        self.stop()
        devices = QMediaDevices.audioInputs()
        if not devices:
            raise RuntimeError("Nessun microfono disponibile.")
        selected = next((d for d in devices if bytes(d.id()).hex() == device_id), None)
        if device_id and selected is None:
            raise RuntimeError("Il microfono selezionato non è più disponibile. Selezionalo nelle impostazioni.")
        selected = selected or QMediaDevices.defaultAudioInput()
        self.device_name = selected.description()
        self.captured_samples = 0
        self.rms = self.peak_rms = 0.0
        desired = QAudioFormat()
        desired.setSampleRate(16000)
        desired.setChannelCount(1)
        desired.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        # Capture in the native WASAPI format; convert in our bounded pipeline.
        # Some drivers advertise a 16 kHz format but fail to open it in practice.
        fmt = selected.preferredFormat()
        self.converter = PcmConverter(fmt.sampleRate(), fmt.channelCount(), fmt.sampleFormat())
        self.source = QAudioSource(selected, fmt, self)
        self.source.stateChanged.connect(self._state_changed)
        self.device = self.source.start()
        if self.device is None or self.source.error() != QAudio.Error.NoError:
            reason = str(self.source.error())
            self.stop()
            raise RuntimeError("Impossibile aprire il microfono (" + reason + "). Verifica autorizzazioni Windows e dispositivo.")
        self.enabled = True
        self.device.readyRead.connect(self._read)
        self.connected = True

    def _read(self):
        if not self.enabled or self.device is None:
            return
        samples = self.converter.convert(bytes(self.device.readAll()))
        if samples.size:
            rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768) ** 2)))
            self.captured_samples += samples.size
            self.rms = rms
            self.peak_rms = max(self.peak_rms, rms)
            self.level.emit(min(1.0, rms * 10))
            self.frames.emit(samples)

    @Slot()
    def _state_changed(self):
        state = self.source.state() if self.source else None
        if self.enabled and state == QAudio.State.StoppedState and self.source.error() != QAudio.Error.NoError:
            self.error.emit("Microfono disconnesso o non accessibile.")

    def stop(self):
        self.enabled = False
        if self.device and self.connected:
            try:
                self.device.readyRead.disconnect(self._read)
            except (RuntimeError, TypeError):
                pass
        self.connected = False
        if self.source:
            self.source.stop()
            self.source.deleteLater()
        self.device = self.source = self.converter = None
        self.level.emit(0.0)
