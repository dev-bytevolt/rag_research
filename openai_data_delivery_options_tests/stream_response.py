import queue
import threading
import time
import os
from pathlib import Path
from typing import Optional

from gtts import gTTS
from openai import OpenAI
from playsound import playsound

openAIKey = "<YOUR OPEN AI TOKEN>"


SCRIPT_DIR = Path(__file__).resolve().parent
soundFileIndex = 0
audio_queue: "queue.Queue[Optional[Path]]" = queue.Queue()


def ttsQueue(text: str) -> None:
    """
    Generate an MP3 file for the given text as soon as it is ready and
    enqueue it for playback. Actual audio playback happens in a separate
    worker that consumes from the audio_queue so files are played
    sequentially.
    """
    global soundFileIndex
    soundFileIndex += 1
    filePath = SCRIPT_DIR / f"speech_{soundFileIndex}.mp3"
    myobj = gTTS(text=text, lang="en", slow=False)
    myobj.save(filePath)
    audio_queue.put(filePath)


def audio_player_worker(audio_q: "queue.Queue[Optional[Path]]") -> None:
    """
    Consume generated MP3 files from the queue and play them one after
    another, deleting each file after it has been played.
    """
    while True:
        filePath = audio_q.get()
        if filePath is None:
            break
        try:
            playsound(str(filePath))
        finally:
            try:
                os.remove(filePath)
            except OSError:
                pass

def tts_worker(text_queue: "queue.Queue[Optional[str]]") -> None:
    """
    TTS worker that buffers incoming text chunks until it sees a newline
    character, then speaks the full line. This way, the producer can
    just push raw streamed text pieces without worrying about line
    boundaries.
    """
    buffer = ""

    while True:
        chunk = text_queue.get()
        if chunk is None:
            # Flush any remaining buffered text that did not end with a
            # newline so it is still spoken once.
            remaining = buffer.strip()
            if remaining:
                ttsQueue(remaining)
            break
        if not chunk:
            continue

        buffer += chunk

        # Whenever we see a newline, speak everything up to that newline
        # as one chunk, then keep buffering the rest.
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            ttsQueue(line)


def stream_openai_to_tts() -> None:
    """
    Call OpenAI with a long prompt, stream the text response, and send
    chunks to a TTS service without waiting for the full HTTP response.
    """
    # Read API key from the standard environment variable.
    # Make sure OPENAI_API_KEY is set before running this script.
    client = OpenAI(api_key=openAIKey)

    long_prompt = (
        "You are a narrator reading a long story out loud. "
        "Tell me a detailed, engaging story about an explorer "
        "who travels through several strange worlds. "
        "Speak in the first person."
        "Avoid lists and headings; just tell the story naturally."
        #"Make the story have 4 short paragraphs, no more than 30 words each."
    )

    text_queue: "queue.Queue[Optional[str]]" = queue.Queue()
    player_thread = threading.Thread(
        target=audio_player_worker, args=(audio_queue,), daemon=True
    )
    player_thread.start()

    worker_thread = threading.Thread(
        target=tts_worker, args=(text_queue,), daemon=True
    )
    worker_thread.start()

    start = time.perf_counter()
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": long_prompt}],
        stream=False,
    )
    end = time.perf_counter()
    elapsed = (end - start)
    print(f"\n\nModel invocation time, no sound: {elapsed:.3f} s\n")

    # Stream the model output token-by-token and immediately forward each
    # piece of text to the TTS worker via a queue.
    start = time.perf_counter()
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": long_prompt}],
        stream=True,
    )

    started = False
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # `delta.content` may be None or an empty string.
            text_piece = getattr(delta, "content", None)
            if not text_piece:
                continue

            # Print to stdout so you can see the text as it streams.
            print(text_piece, end="", flush=True)
            if not started:
                end = time.perf_counter()
                elapsed = (end - start)
                print(f"\n\nModel invocation time, with sound: {elapsed:.3f} s\n")
                started = True

            # Forward raw text pieces directly to the TTS worker; it
            # will buffer until it sees newline characters.
            text_queue.put(text_piece)
        print()
    finally:
        # Signal the worker to stop and wait for it to finish.
        text_queue.put(None)
        worker_thread.join()
        # After all text has been processed into MP3 files, signal the
        # audio player to finish after playing everything in its queue.
        audio_queue.put(None)
        player_thread.join()


if __name__ == "__main__":
    stream_openai_to_tts()

