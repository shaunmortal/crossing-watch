"""Spoken notes: the principal records the notes on a phone, Muse Voice Transcribe writes them down, and pack.py
--voice-notes AUDIO hands the text to --notes exactly as typed notes. Only the transcript (notes-<sha8>.txt) and the
audio's sha256 are kept, beside plan.json; the audio itself is never copied, and its WAV lives in a temporary folder."""
import hashlib
import http.client
import json
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path

# https://dev.meta.ai/docs/speech-to-text.md: "POST https://api.meta.ai/v1/asr/transcribe", multipart/form-data with
# a `request` part (JSON, type=application/json) and an `audio` part: a RIFF/WAVE file, mono, 16-bit PCM, 16 or 24 kHz,
# up to 10 minutes and 32 MB. The reply's top-level "transcript" holds the whole text.
URL = "https://api.meta.ai/v1/asr/transcribe"
MODEL = "muse-voice-transcribe-1.0"
NAME = "Muse Voice Transcribe"
SAMPLE_RATE = 24_000  # the docs' own ffmpeg line
TIMEOUT_S = 300
# "languageBias" steers recognition without forcing a language: Hindi and English both, for mixed speech
REQUEST = {"mode": "PUSH_TO_TALK", "model": MODEL, "audioEncoding": "WAV", "languageBias": ["Hindi", "English"]}
TRANSCRIPT = "notes-{sha8}.txt"  # beside plan.json, named by the first 8 hex digits of the audio's sha256


def to_wav(audio, wav):
    """Any phone audio (m4a, opus, ogg, aac, wav) as the docs' WAV, with its metadata dropped; SystemExit if ffmpeg
    cannot read it. Only the first audio track, as listen.audio_around reads a phone video."""
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-map", "0:a:0", "-vn", "-ac", "1", "-ar",
                        str(SAMPLE_RATE), "-c:a", "pcm_s16le", "-map_metadata", "-1", str(wav)],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as err:
        raise SystemExit(f"cannot read {audio} as audio: {getattr(err, 'stderr', b'') or err}")
    return wav


def transcribe(wav, api_key):
    """Muse Voice Transcribe's text for one WAV (stripped, may be ""). The key goes to URL only."""
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\nContent-Type: application/json\r\n\r\n'
            f"{json.dumps(REQUEST)}\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; "
            f'filename="notes.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode() + wav.read_bytes() + (
            f"\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
            reply = json.load(response)
    except (OSError, ValueError, http.client.HTTPException) as err:
        raise SystemExit(f"{NAME} failed, nothing was revised: {err}")
    text = reply.get("transcript") if isinstance(reply, dict) else None
    return text.strip() if isinstance(text, str) else ""


def spoken_notes(audio, out_dir, api_key):
    """(transcript, audio sha256): read again from notes-<sha8>.txt when this audio was transcribed before (a re-run
    pays nothing), else transcribed and saved there. SystemExit on an empty transcript: there are no notes to give."""
    audio = Path(audio)
    try:
        digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    except OSError as err:
        raise SystemExit(f"cannot read the spoken notes: {err}")
    saved = Path(out_dir) / TRANSCRIPT.format(sha8=digest[:8])
    if saved.is_file() and (text := saved.read_text().strip()):
        return text, digest
    if not api_key:
        raise SystemExit(f"{NAME} needs MODEL_API_KEY: set it, or type the notes and use --notes FILE")
    with tempfile.TemporaryDirectory() as folder:
        text = transcribe(to_wav(audio, Path(folder) / "notes.wav"), api_key)
    if not text:
        raise SystemExit(f"{NAME} heard no words in {audio.name}: nothing was revised. Record the notes again, closer "
                         "to the phone, or type them and use --notes FILE")
    saved.write_text(text + "\n")
    return text, digest
