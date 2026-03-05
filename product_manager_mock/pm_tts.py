import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from gtts import gTTS
from pygame import mixer


class TTSEngine:
    """
    Text-to-speech engine that streams text pieces into a background
    worker, generates MP3 files, and plays them sequentially.

    All state (queues, threads, counters) is kept on the instance so
    there are no module-level globals.
    """

    def __init__(self) -> None:
        self._audio_queue: "queue.Queue[Optional[Path]]" = queue.Queue()
        self._text_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._sound_file_index: int = 0
        self._sound_dir: Path = Path(__file__).resolve().parent / "tmp_sound"
        if not self._sound_dir.is_dir():
            self._sound_dir.mkdir()

        self._worker_thread: Optional[threading.Thread] = None
        self._player_thread: Optional[threading.Thread] = None
        self._current_channel_lock = threading.Lock()
        self._current_channel: Optional[object] = None

        # When False, this engine becomes a no-op: it will not start
        # background workers, enqueue audio, or play sounds.
        self._enabled: bool = True

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all audio output for this engine."""
        self._enabled = enabled

    def is_enabled(self) -> bool:
        """Return True if this engine is currently enabled."""
        return self._enabled

    def start(self) -> None:
        """
        Start background threads for TTS processing and audio playback.
        Safe to call multiple times; threads are created only if needed.
        """
        if not self._enabled:
            return

        if self._player_thread is None or not self._player_thread.is_alive():
            self._player_thread = threading.Thread(
                target=self._audio_player_worker,
                daemon=True,
            )
            self._player_thread.start()

        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self._tts_worker,
                daemon=True,
            )
            self._worker_thread.start()

    def stopPlayback(self) -> None:
        """
        Stop any playback (including the current sound) and clear queues
        without stopping threads.

        This clears both the text and audio queues and deletes any queued
        or on-disk MP3 files. The background worker and player threads stay
        alive so new text chunks can be enqueued and played afterwards.
        If audio is currently playing via `pygame.mixer`, it is stopped
        immediately.
        """
        if not self._enabled:
            return

        # Stop the sound that is currently being played, if any.
        channel: Optional[object] = None
        with self._current_channel_lock:
            channel = self._current_channel
        if channel is not None:
            try:
                # `Channel` exposes `stop()`; using `object` typing to avoid
                # depending on pygame's stubs.
                channel.stop()  # type: ignore[union-attr]
            except Exception:
                # Best-effort stop; ignore any errors from the audio backend.
                pass

        # Drain the text queue so no further TTS work is performed for
        # already-queued text. Preserve any sentinel that might have been
        # enqueued by `close()`.
        try:
            while True:
                item = self._text_queue.get_nowait()
                if item is None:
                    # Put the sentinel back and stop draining.
                    self._text_queue.put_nowait(None)
                    break
        except queue.Empty:
            pass

        # Drain the audio queue, deleting any MP3s that were queued
        # but have not yet been played. Preserve a close sentinel if
        # one is present.
        try:
            while True:
                file_path = self._audio_queue.get_nowait()
                if file_path is None:
                    self._audio_queue.put_nowait(None)
                    break
                try:
                    os.remove(file_path)
                except OSError:
                    # Best-effort cleanup; ignore errors.
                    pass
        except queue.Empty:
            pass

        # Best-effort cleanup of any stray MP3 files in the sound directory.
        if self._sound_dir.is_dir():
            for mp3_path in self._sound_dir.glob("*.mp3"):
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass

    def close(self) -> None:
        """
        Signal workers to finish processing and wait for them to exit.
        """
        if not self._enabled:
            return

        if self._worker_thread is not None:
            # Tell the TTS worker there is no more text to process.
            self._text_queue.put(None)
            self._worker_thread.join()
            self._worker_thread = None

        if self._player_thread is not None:
            # After all text has been processed into MP3 files, signal the
            # audio player to finish after playing everything in its queue.
            self._audio_queue.put(None)
            self._player_thread.join()
            self._player_thread = None

    def put_text_chunk(self, text_piece: str) -> None:
        """
        Enqueue a raw piece of text to be spoken.

        The worker buffers these pieces until it decides to speak a
        full sentence or line.
        """
        if not self._enabled:
            return
        self._text_queue.put(text_piece)

    def _enqueue_tts(self, text: str) -> None:
        """
        Generate an MP3 file for the given text as soon as it is ready and
        enqueue it for playback. Actual audio playback happens in a separate
        worker that consumes from the audio queue so files are played
        sequentially.
        """
        self._sound_file_index += 1
        file_path = self._sound_dir / f"speech_{self._sound_file_index}.mp3"
        myobj = gTTS(text=text, lang="en", slow=False)
        myobj.save(file_path)
        self._audio_queue.put(file_path)

    def _audio_player_worker(self) -> None:
        """
        Consume generated MP3 files from the queue and play them one after
        another, deleting each file after it has been played.
        """
        if not mixer.get_init():
            mixer.init()

        while True:
            file_path = self._audio_queue.get()
            if file_path is None:
                break

            channel = None
            try:
                sound = mixer.Sound(str(file_path))
                channel = sound.play()
                with self._current_channel_lock:
                    self._current_channel = channel

                # Wait until playback is finished (or stopped).
                while channel.get_busy():
                    time.sleep(0.05)
            finally:
                with self._current_channel_lock:
                    if self._current_channel is channel:
                        self._current_channel = None
                try:
                    os.remove(file_path)
                except OSError:
                    # Best-effort cleanup; ignore errors.
                    pass

    def _tts_worker(self) -> None:
        """
        TTS worker that buffers incoming text chunks until it sees a newline
        character or sentence delimiters, then speaks the full line. This
        way, the producer can just push raw streamed text pieces without
        worrying about line boundaries.
        """
        buffer = ""

        def _flush_buffer_on_delimiter(buf: str, delimiter: list[str]) -> str:
            for d in delimiter:
                while d in buf:
                    line, buf = buf.split(d, 1)
                    line = line.strip()
                    if not line:
                        continue
                    self._enqueue_tts(line)
            return buf

        def _flush_if_endswith(buf: str, ending: list[str]) -> str:
            for e in ending:
                if buf.endswith(e):
                    line = buf.strip()
                    buf = ""
                    if not line:
                        return buf
                    self._enqueue_tts(line)
                    return buf
            return buf

        while True:
            chunk = self._text_queue.get()
            if chunk is None:
                # Flush any remaining buffered text that did not end with a
                # newline so it is still spoken once.
                remaining = buffer.strip()
                if remaining:
                    self._enqueue_tts(remaining)
                break
            if not chunk:
                continue

            buffer += chunk

            # Whenever we see a newline or sentence terminators, speak
            # everything up to that delimiter as one chunk, then keep
            # buffering the rest.
            buffer = _flush_buffer_on_delimiter(buffer, ["\n", ". ", "! ", "? ", "; "])
            buffer = _flush_if_endswith(buffer, [".", "!", "?"])