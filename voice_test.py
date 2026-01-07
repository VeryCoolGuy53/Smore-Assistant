#!/usr/bin/env python3
"""
Real-time STT with Silero-VAD and sounddevice streaming.
- Continuous audio capture (no subprocess overhead)
- Neural VAD for accurate speech detection
- Transcribes sliding windows, not every 1s chunk
"""
import os
import sys
import time
import numpy as np

os.environ["CUDA_VISIBLE_DEVICES"] = "1"
sys.stdout.reconfigure(line_buffering=True)

import ctypes
cudnn_path = "/home/smore/assistant/venv/lib/python3.12/site-packages/nvidia/cudnn/lib"
for lib in ["libcudnn_ops.so.9", "libcudnn.so.9"]:
    ctypes.CDLL(os.path.join(cudnn_path, lib), mode=ctypes.RTLD_GLOBAL)

import torch
import sounddevice as sd
from faster_whisper import WhisperModel

# Config
SAMPLE_RATE = 16000
CHUNK_MS = 32  # 32ms chunks for VAD (min 512 samples at 16kHz)
PARTIAL_INTERVAL_MS = 500  # Update partials every 500ms
FINAL_SILENCE_MS = 800  # Finalize after 800ms silence
MIN_SPEECH_MS = 300  # Ignore very short speech
MAX_BUFFER_S = 60  # Max audio buffer size


class RingBuffer:
    """Efficient circular buffer for audio samples."""

    def __init__(self, max_seconds: int, sample_rate: int):
        self.max_samples = max_seconds * sample_rate
        self.buffer = np.zeros(self.max_samples, dtype=np.float32)
        self.write_pos = 0
        self.total_written = 0

    def write(self, data: np.ndarray):
        """Write audio data to buffer."""
        n = len(data)
        if n == 0:
            return

        if n >= self.max_samples:
            self.buffer[:] = data[-self.max_samples:]
            self.write_pos = 0
        else:
            end_pos = self.write_pos + n
            if end_pos <= self.max_samples:
                self.buffer[self.write_pos:end_pos] = data
            else:
                first_part = self.max_samples - self.write_pos
                self.buffer[self.write_pos:] = data[:first_part]
                self.buffer[:n - first_part] = data[first_part:]
            self.write_pos = end_pos % self.max_samples
        self.total_written += n

    def get_last(self, n_samples: int) -> np.ndarray:
        """Get last N samples from buffer."""
        n_samples = min(n_samples, self.max_samples, self.total_written)
        if n_samples == 0:
            return np.array([], dtype=np.float32)

        if n_samples <= self.write_pos:
            return self.buffer[self.write_pos - n_samples:self.write_pos].copy()
        else:
            first_part = n_samples - self.write_pos
            return np.concatenate([
                self.buffer[-first_part:],
                self.buffer[:self.write_pos]
            ])


class SileroVAD:
    """Silero VAD wrapper for speech detection."""

    def __init__(self):
        print("Loading Silero-VAD...")
        self.model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True
        )
        self.model.eval()

    def reset(self):
        """Reset internal states between utterances."""
        self.model.reset_states()

    def is_speech(self, audio: np.ndarray, threshold: float = 0.5) -> bool:
        """Check if audio chunk contains speech."""
        if len(audio) == 0:
            return False
        tensor = torch.from_numpy(audio).float()
        prob = self.model(tensor, SAMPLE_RATE).item()
        return prob > threshold


# States
IDLE = "idle"
LISTENING = "listening"
TRAILING = "trailing"


def has_audio_energy(audio: np.ndarray, threshold: float = 0.01) -> bool:
    """Check if audio has enough energy (not silence)."""
    return np.abs(audio).mean() > threshold


def main():
    # Initialize components
    print("Loading Whisper large-v3 on GPU 1...")
    whisper = WhisperModel("large-v3", device="cuda", compute_type="float16")

    vad = SileroVAD()
    buffer = RingBuffer(MAX_BUFFER_S, SAMPLE_RATE)

    # State
    state = IDLE
    speech_start_time = None
    last_speech_time = None
    last_partial_time = 0
    previous_context = ""

    chunk_samples = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 480 samples at 30ms

    def audio_callback(indata, _frames, _time_info, _status):
        """Called by sounddevice for each audio chunk."""
        buffer.write(indata[:, 0])

    print("=" * 50)
    print("STREAMING STT - Speak into microphone")
    print("=" * 50)

    # Start audio stream (device 4 = USB audio CODEC hw:1,0)
    stream = sd.InputStream(
        device=4,
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        blocksize=chunk_samples,
        callback=audio_callback
    )

    try:
        stream.start()

        while True:
            current_time = time.time() * 1000  # ms

            # Get last 30ms for VAD check
            chunk = buffer.get_last(chunk_samples)
            if len(chunk) < chunk_samples:
                time.sleep(0.01)
                continue

            is_speech = vad.is_speech(chunk)

            if is_speech:
                last_speech_time = current_time

                if state == IDLE:
                    # Speech started
                    state = LISTENING
                    speech_start_time = current_time
                    print("\n[listening...]", end="", flush=True)

                elif state == TRAILING:
                    # Speech resumed
                    state = LISTENING

                # Update partial transcription periodically
                if state == LISTENING:
                    speech_duration = current_time - speech_start_time

                    if (current_time - last_partial_time >= PARTIAL_INTERVAL_MS
                            and speech_duration >= MIN_SPEECH_MS):
                        # Get audio from speech start
                        n_samples = int(speech_duration * SAMPLE_RATE / 1000)
                        audio = buffer.get_last(min(n_samples, SAMPLE_RATE * 10))  # Max 10s

                        if len(audio) > 0 and has_audio_energy(audio):
                            segments, _ = whisper.transcribe(
                                audio,
                                language="en",
                                beam_size=1,
                                best_of=1,
                                initial_prompt=previous_context[-200:] if previous_context else None,
                            )
                            text = " ".join(s.text.strip() for s in segments)
                            if text:
                                # Clear line fully before printing partial
                                print(f"\r{' ' * 80}\r[...] {text}", end="", flush=True)

                        last_partial_time = current_time

            else:
                # Silence
                if state == LISTENING:
                    state = TRAILING

                elif state == TRAILING and last_speech_time:
                    silence_duration = current_time - last_speech_time

                    if silence_duration >= FINAL_SILENCE_MS:
                        # Finalize transcription
                        speech_duration = last_speech_time - speech_start_time
                        n_samples = int(speech_duration * SAMPLE_RATE / 1000)
                        silence_samples = int(silence_duration * SAMPLE_RATE / 1000)

                        # Get speech + silence, then trim off the silence
                        total_samples = min(n_samples + silence_samples, SAMPLE_RATE * 30)
                        all_audio = buffer.get_last(total_samples)
                        # Trim trailing silence to get just the speech
                        audio = all_audio[:len(all_audio) - silence_samples] if silence_samples < len(all_audio) else all_audio

                        if len(audio) > MIN_SPEECH_MS * SAMPLE_RATE / 1000 and has_audio_energy(audio):
                            segments, _ = whisper.transcribe(
                                audio,
                                language="en",
                                beam_size=5,
                                best_of=5,
                                initial_prompt=previous_context[-200:] if previous_context else None,
                            )
                            text = " ".join(s.text.strip() for s in segments)
                            # Skip Whisper's most common hallucination
                            if text and text.strip().lower() not in ("thank you.", "thank you", "thanks."):
                                # Clear line fully before printing final
                                print(f"\r{' ' * 80}\r>>> {text}")
                                previous_context += " " + text

                        # Reset
                        state = IDLE
                        speech_start_time = None
                        last_speech_time = None
                        vad.reset()  # Reset VAD state for next utterance

            time.sleep(0.01)  # 10ms loop

    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        stream.stop()
        stream.close()


if __name__ == "__main__":
    main()
