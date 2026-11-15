import unittest

import numpy as np
from PySide6.QtMultimedia import QAudioFormat

from jarvis.voice.pcm import decode_pcm, output_pcm


def audio_format(rate=48000, channels=1, sample_format=QAudioFormat.SampleFormat.Float):
    fmt = QAudioFormat()
    fmt.setSampleRate(rate)
    fmt.setChannelCount(channels)
    fmt.setSampleFormat(sample_format)
    return fmt


class PcmTests(unittest.TestCase):
    def test_positive_int32_peaks_never_wrap_negative(self):
        source = audio_format()
        target = audio_format(sample_format=QAudioFormat.SampleFormat.Int32)
        values = np.array([1, -1, 0, 0.9999999, -0.9999999], np.float32)
        result = np.frombuffer(output_pcm(values.tobytes(), source, target), dtype='<i4')
        self.assertGreater(result[0], 0)
        self.assertGreater(result[3], 0)
        self.assertLess(result[1], 0)
        self.assertEqual(result[2], 0)

    def test_resampling_preserves_duration_pitch_and_both_channels(self):
        rate = 16000
        tone = (np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 12000).astype('<i2')
        source = audio_format(rate, 1, QAudioFormat.SampleFormat.Int16)
        target = audio_format(48000, 2)
        result = decode_pcm(output_pcm(tone.tobytes(), source, target), target)
        self.assertEqual(result.shape, (48000, 2))
        np.testing.assert_array_equal(result[:, 0], result[:, 1])
        frequency = np.fft.rfftfreq(len(result), 1 / 48000)[np.argmax(np.abs(np.fft.rfft(result[:, 0])))]
        self.assertAlmostEqual(frequency, 440, places=0)

    def test_quiet_audio_is_not_normalized_or_boosted(self):
        source = audio_format()
        values = np.array([0, 0.02, -0.01, 0.03], np.float32)
        result = decode_pcm(output_pcm(values.tobytes(), source, source), source).ravel()
        np.testing.assert_allclose(result, values, atol=1e-7)

    def test_clipping_overshoot_gets_headroom_without_nan(self):
        source = audio_format()
        values = np.array([1.1, -1.05, 0.5], np.float32)
        result = decode_pcm(output_pcm(values.tobytes(), source, source), source)
        self.assertLessEqual(np.abs(result).max(), 10 ** (-1.5 / 20) + 1e-7)

    def test_corrupt_pcm_is_rejected(self):
        fmt = audio_format()
        for data in (b'', b'123', np.array([np.nan], np.float32).tobytes()):
            with self.subTest(data=data), self.assertRaises(ValueError):
                output_pcm(data, fmt, fmt)
