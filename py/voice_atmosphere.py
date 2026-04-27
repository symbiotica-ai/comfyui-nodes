# ABOUTME: Adds background noise and room reverb to voice audio for natural depth.
# ABOUTME: Processes AUDIO with configurable noise type, level, and reverb settings.

import torch
import numpy as np


class NSVoiceAtmosphere:
    """Adds subtle background noise and reverb to voice audio to give it depth."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "audio": ("AUDIO",),
                "noise_type": (["pink", "white", "brown"],),
                "noise_level": ("FLOAT", {
                    "default": 0.02,
                    "min": 0.0,
                    "max": 0.5,
                    "step": 0.005,
                    "tooltip": "Volume of background noise (0 = none)",
                }),
                "reverb_mix": ("FLOAT", {
                    "default": 0.15,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Wet/dry mix (0 = dry, 1 = fully wet)",
                }),
                "room_size": ("FLOAT", {
                    "default": 0.3,
                    "min": 0.05,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "Simulated room size (small to large)",
                }),
                "reverb_decay": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.1,
                    "max": 3.0,
                    "step": 0.1,
                    "tooltip": "Reverb tail length in seconds",
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xFFFFFFFF,
                }),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/audio"

    def _generate_noise(self, rng, noise_type, num_samples, num_channels):
        """Generate noise of the specified type."""
        if noise_type == "white":
            return rng.standard_normal((num_channels, num_samples)).astype(np.float32)

        if noise_type == "pink":
            noise = np.zeros((num_channels, num_samples), dtype=np.float32)
            for ch in range(num_channels):
                white = rng.standard_normal(num_samples)
                X = np.fft.rfft(white)
                freqs = np.fft.rfftfreq(num_samples)
                freqs[0] = 1.0
                X *= 1.0 / np.sqrt(freqs)
                X[0] = 0.0
                pink = np.fft.irfft(X, n=num_samples)
                mx = np.max(np.abs(pink))
                if mx > 0:
                    pink /= mx
                noise[ch] = pink.astype(np.float32)
            return noise

        # brown
        white = rng.standard_normal((num_channels, num_samples)).astype(np.float32)
        brown = np.cumsum(white, axis=1)
        for ch in range(num_channels):
            mx = np.max(np.abs(brown[ch]))
            if mx > 0:
                brown[ch] /= mx
        return brown

    def _generate_impulse_response(self, rng, sample_rate, room_size, decay):
        """Generate a synthetic room impulse response with early reflections and tail."""
        ir_length = max(1, int(sample_rate * decay))
        ir = np.zeros(ir_length, dtype=np.float32)
        ir[0] = 1.0

        # Early reflections at delays proportional to room size
        base_delay = max(1, int(room_size * 0.01 * sample_rate))
        reflections = [
            (base_delay, 0.6),
            (int(base_delay * 1.5), 0.4),
            (int(base_delay * 2.3), 0.3),
            (int(base_delay * 3.1), 0.2),
            (int(base_delay * 4.7), 0.15),
        ]
        for delay, gain in reflections:
            if delay < ir_length:
                sign = 1.0 if rng.random() > 0.5 else -1.0
                ir[delay] += gain * sign

        # Late reverb: exponentially decaying noise
        valid_delays = [d for d, _ in reflections if d < ir_length]
        late_start = max(valid_delays) if valid_delays else base_delay
        if late_start < ir_length:
            tail_len = ir_length - late_start
            late_noise = rng.standard_normal(tail_len).astype(np.float32)
            t = np.arange(tail_len, dtype=np.float32) / sample_rate
            envelope = np.exp(-t * 3.0 / max(decay, 0.01)) * 0.3
            ir[late_start:] += late_noise * envelope

        mx = np.max(np.abs(ir))
        if mx > 0:
            ir /= mx
        return ir

    def _apply_reverb(self, audio_np, ir, mix):
        """Apply reverb via FFT convolution and mix with dry signal."""
        from scipy.signal import fftconvolve

        num_channels, num_samples = audio_np.shape
        result = np.zeros_like(audio_np)

        for ch in range(num_channels):
            wet = fftconvolve(audio_np[ch], ir, mode="full")[:num_samples]
            # Level-match wet to dry
            dry_rms = np.sqrt(np.mean(audio_np[ch] ** 2))
            wet_rms = np.sqrt(np.mean(wet ** 2))
            if wet_rms > 0:
                wet *= dry_rms / wet_rms
            result[ch] = (1.0 - mix) * audio_np[ch] + mix * wet

        return result

    def execute(self, audio, noise_type, noise_level, reverb_mix, room_size,
                reverb_decay, seed):
        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]
        batch_size, num_channels, num_samples = waveform.shape

        rng = np.random.default_rng(seed)

        results = []
        for b in range(batch_size):
            audio_np = waveform[b].cpu().numpy().astype(np.float32)

            if reverb_mix > 0:
                ir = self._generate_impulse_response(
                    rng, sample_rate, room_size, reverb_decay
                )
                audio_np = self._apply_reverb(audio_np, ir, reverb_mix)

            if noise_level > 0:
                noise = self._generate_noise(
                    rng, noise_type, num_samples, num_channels
                )
                audio_np = audio_np + noise * noise_level

            audio_np = np.clip(audio_np, -1.0, 1.0)
            results.append(audio_np)

        out = torch.from_numpy(np.stack(results)).to(waveform.device)
        return ({"waveform": out, "sample_rate": sample_rate},)


NODE_CLASS_MAPPINGS = {"NSVoiceAtmosphere": NSVoiceAtmosphere}
NODE_DISPLAY_NAME_MAPPINGS = {"NSVoiceAtmosphere": "NS Voice Atmosphere"}
