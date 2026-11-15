"""PCM format conversion with explicit sample rates, channels and headroom."""

from math import gcd

import numpy as np
from PySide6.QtMultimedia import QAudioFormat

TYPES = {QAudioFormat.SampleFormat.Int16: (np.dtype('<i2'), 32768),
         QAudioFormat.SampleFormat.Int32: (np.dtype('<i4'), 2147483648),
         QAudioFormat.SampleFormat.Float: (np.dtype('<f4'), 1)}


def decode_pcm(data: bytes, fmt: QAudioFormat) -> np.ndarray:
    if fmt.sampleFormat() not in TYPES or fmt.sampleRate() <= 0 or fmt.channelCount() < 1:
        raise ValueError("Formato PCM non supportato.")
    dtype, divisor = TYPES[fmt.sampleFormat()]
    if not data or len(data) % (dtype.itemsize * fmt.channelCount()):
        raise ValueError("Buffer PCM vuoto o non allineato ai canali.")
    values = np.frombuffer(data, dtype=dtype).astype(np.float64).reshape(-1, fmt.channelCount()) / divisor
    if not np.isfinite(values).all():
        raise ValueError("Il buffer PCM contiene campioni non finiti.")
    return values


def output_pcm(data: bytes, source: QAudioFormat, target: QAudioFormat) -> bytes:
    from scipy.signal import resample_poly
    values = decode_pcm(data, source)
    if target.sampleFormat() not in TYPES or target.sampleRate() <= 0 or target.channelCount() < 1:
        raise ValueError("Formato audio di destinazione non supportato.")
    if source.sampleRate() != target.sampleRate():
        common = gcd(source.sampleRate(), target.sampleRate())
        values = resample_poly(values, target.sampleRate() // common, source.sampleRate() // common, axis=0)
    if target.channelCount() != source.channelCount():
        values = np.repeat(values.mean(axis=1, keepdims=True), target.channelCount(), axis=1)
    # Attenuate only when required; never boost quiet speech, change pitch or speed.
    peak = float(np.max(np.abs(values)))
    ceiling = 10 ** (-1.5 / 20)
    if peak > ceiling:
        values *= ceiling / peak
    dtype, divisor = TYPES[target.sampleFormat()]
    if divisor == 1:
        return values.astype(dtype).tobytes()
    # Float64 arithmetic is essential here: float32 rounds INT32_MAX to 2**31,
    # and casting that positive value wraps into a negative sample.
    info = np.iinfo(dtype)
    quantized = np.rint(values * divisor)
    return np.clip(quantized, info.min, info.max).astype(dtype).tobytes()


def pcm_amplitudes(data: bytes, fmt: QAudioFormat) -> list[float]:
    samples = decode_pcm(data, fmt).mean(axis=1)
    size = max(1, int(fmt.sampleRate() * 0.02))
    return [min(1.0, float(np.sqrt(np.mean(samples[start:start + size] ** 2))) * 6)
            for start in range(0, len(samples), size)]
