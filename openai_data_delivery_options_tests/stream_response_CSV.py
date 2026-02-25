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
    #print(f"\n\nmake sound {soundFileIndex}")
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
        while ". " in buffer:
            line, buffer = buffer.split(". ", 1)
            line = line.strip()
            if not line:
                continue
            ttsQueue(line)
        while "! " in buffer:
            line, buffer = buffer.split("! ", 1)
            line = line.strip()
            if not line:
                continue
            ttsQueue(line)
        if buffer.endswith("."):
            line = buffer.strip()
            buffer = ""
            if not line:
                continue
            ttsQueue(line)
        if buffer.endswith("!"):
            line = buffer.strip()
            buffer = ""
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

    system_prompt = (
        "You are a careful data analyst."
        "Always base your answers strictly on the provided file contents."
        "The file contains these important colums 'Summary', 'Issue key', 'Assignee'."
        "When checking who the ticket is assigned to, base you answer strictly on the 'Assignee' column."
        "Never use markdown."
        "Your response will be streamed to the enduser using text-to-speech engine, so act as a human, when performing a time consuming operations, such as using code interpreter tool or writing some code, give status updates to the user."
    )

    user_prompt = (
        #"Count how many data rows are present in the csv file"
        "Which tickets are assigned to Hrishikesh Patidar? Return the list of ticket keyss and their summary."
        #"Who are you?"
    )

    initial_note = "\n\nIMPORTANT: don't respond to the user prompt. Check if the request requires access to additional data that you don't have. If so, then instead of the response print a note for the user saying that you need to look up some data and estimate the time required, else respond with an empty string."

    #model = "gpt-4o-mini"
    model = "gpt-5.2-chat-latest"

    fileId = 'file-95YP2vCoCxvhAnw1x9s1xQ'

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
    stream = client.responses.create(
        model=model,
        #tools=[
        #    {
        #        "type": "code_interpreter",
        #        "container": {
        #            "type": "auto",
        #            "file_ids": [fileId],
        #        },
        #    },
        #],
        input=[
            {
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": system_prompt + initial_note},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt + initial_note},
                ],
            },
        ],
        stream=True,
    )

    for event in stream:
        # We only care about incremental text output events.
        if getattr(event, "type", "") != "response.output_text.delta":
            continue

        delta = getattr(event, "delta", None)
        text_piece = None

        # Handle different possible shapes of the delta payload.
        if isinstance(delta, str):
            text_piece = delta
        elif delta is not None:
            text_piece = getattr(delta, "text", None) or getattr(
                delta, "output_text", None
            )

        if not text_piece:
            continue

        # Print to stdout so you can see the text as it streams.
        print(text_piece, end="", flush=True)

        # Forward raw text pieces directly to the TTS worker; it
        # will buffer until it sees newline characters.
        text_queue.put(text_piece)
    print()

    end = time.perf_counter()
    elapsed = (end - start)
    print(f"\nModel {model} invocation time: {elapsed:.3f} s")
    print("\n\ncall 2")

    start = time.perf_counter()
    stream = client.responses.create(
        model=model,
        tools=[
            {
                "type": "code_interpreter",
                "container": {
                    "type": "auto",
                    "file_ids": [fileId],
                },
            },
        ],
        input=[
            {
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": system_prompt},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                ],
            },
        ],
        stream=True,
    )

    for event in stream:
        
        # We only care about incremental text output events.
        if getattr(event, "type", "") != "response.output_text.delta":
            continue

        delta = getattr(event, "delta", None)
        text_piece = None

        # Handle different possible shapes of the delta payload.
        if isinstance(delta, str):
            text_piece = delta
        elif delta is not None:
            text_piece = getattr(delta, "text", None) or getattr(
                delta, "output_text", None
            )

        if not text_piece:
            continue

        # Print to stdout so you can see the text as it streams.
        print(text_piece, end="", flush=True)

        # Forward raw text pieces directly to the TTS worker; it
        # will buffer until it sees newline characters.
        text_queue.put(text_piece)
    print()

    end = time.perf_counter()
    elapsed = (end - start)
    print(f"\nModel {model} invocation time: {elapsed:.3f} s")

    
    text_queue.put(None)
    worker_thread.join()
    # After all text has been processed into MP3 files, signal the
    # audio player to finish after playing everything in its queue.
    audio_queue.put(None)
    player_thread.join()


if __name__ == "__main__":
    stream_openai_to_tts()

