import queue
import threading
import time
import os
from pathlib import Path
from typing import Optional

from gtts import gTTS
from openai import OpenAI
from playsound import playsound

import csv
import json
import os
from pathlib import Path
from typing import List, Dict

import logging
import time
from threading import Thread

import uvicorn
from fastmcp import FastMCP
from openai import OpenAI
from openai.types.responses import ResponseOutputText
from openai.types.responses.response_output_message import ResponseOutputMessage
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

openAIKey = "<YOUR OPEN AI TOKEN>"
server_address = "https://<PUT YOUR SERVER HOST HERE, HAS TO HAVE A VALID HTTPS CERT>/mcp"
server_port = 9999

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "Jira.csv"


soundFileIndex = 0
audio_queue: "queue.Queue[Optional[Path]]" = queue.Queue()

logging.basicConfig(
    level=logging.ERROR,
    #level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("jira_mcp_server")

def load_jira_rows() -> List[Dict[str, str]]:
    """Load Jira CSV rows into memory."""
    if not CSV_PATH.exists():
        logger.error("CSV file not found at %s", CSV_PATH)
        raise FileNotFoundError(f"CSV file not found at {CSV_PATH}")

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    logger.info("Loaded %d Jira rows from %s", len(rows), CSV_PATH)
    return rows


JIRA_ROWS: List[Dict[str, str]] = load_jira_rows()


def search_tickets_by_assignee(assignee: str) -> List[Dict[str, str]]:
    """
    Search Jira tickets by the 'Assignee' column (case-insensitive exact match).
    Returns only Assignee, Summary and Issue key columns.
    """
    assignee_normalized = assignee.strip().lower()
    results: List[Dict[str, str]] = []

    for row in JIRA_ROWS:
        row_assignee = (row.get("Assignee") or "").strip().lower()
        if assignee_normalized in row_assignee:
            results.append(
                {
                    "Assignee": row.get("Assignee", ""),
                    "Summary": row.get('\ufeffSummary', ""),
                    "Issue key": row.get("Issue key", ""),
                }
            )

    return results


# FastMCP server definition
mcp = FastMCP(
    "Jira tickets search MCP",
    instructions=(
        "This MCP server provides search capability for Jira tickets. "
        "Use the 'assignee' param for the 'search_jira' tool."
    ),
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            body_bytes = await request.body()
            body_text = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            body_text = "<unreadable>"

        logger.info(
            "Incoming HTTP[%s] %s query=%s body=%s",
            request.method,
            request.url.path,
            request.url.query,
            body_text[:2000],
        )

        response = await call_next(request)

        return response

@mcp.tool()
async def search_jira(assignee: str) -> str:
    matches = search_tickets_by_assignee(assignee)
    return json.dumps(matches)


def ttsQueue(text: str) -> None:
    """
    Generate an MP3 file for the given text as soon as it is ready and
    enqueue it for playback. Actual audio playback happens in a separate
    worker that consumes from the audio_queue so files are played
    sequentially.
    """
    global soundFileIndex
    soundFileIndex += 1
    filePath = BASE_DIR / f"speech_{soundFileIndex}.mp3"
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
    
    http_app = mcp.http_app(
        path="/mcp",
        middleware=[Middleware(RequestLoggingMiddleware)],
        stateless_http=True,
    )

    # Start the HTTP server in a background thread so we can call OpenAI.
    server_thread = Thread(
        target=lambda: uvicorn.run(
            http_app,
            host="0.0.0.0",
            port=server_port,
            log_level="info",
        ),
        daemon=True,
    )
    server_thread.start()

    # Give the server a brief moment to start up before invoking the model.
    time.sleep(5)

    text_queue: "queue.Queue[Optional[str]]" = queue.Queue()
    player_thread = threading.Thread(
        target=audio_player_worker, args=(audio_queue,), daemon=True
    )
    player_thread.start()

    worker_thread = threading.Thread(
        target=tts_worker, args=(text_queue,), daemon=True
    )
    worker_thread.start()

    system_prompt = (
        "You are a careful data analyst working with 'search_jira' tool."
        "The tool accepts only the 'assignee' param to search tickets by assignee and returns 'Summary', 'Issue key', 'Assignee' columns."
        "Use the available MCP tools when the user asks about Jira issues."
        "Never use markdown, output in plain text."
        "Your response will be streamed to the enduser using text-to-speech engine, so act as a human, when performing a time consuming operations, such as using external tools or writing some code, give status updates to the user."
    )

    user_prompt = (
        #"Find all Jira tickets assigned to 'Hrishikesh Patidar' and summarize them."
        "Find all Jira tickets assigned to Arpit and summarize them."
    )

    initial_note = "\n\nIMPORTANT: DO NOT do ANY call to a tool or mcp, instead of responding to the user prompt, respond with some short note that you are going to do a data lookup asking the user to wait for a while, if no external tool call is required return an empty response."

    #model = "gpt-4o-mini"
    model = "gpt-5.2-chat-latest"

    start = time.perf_counter()
    stream = client.responses.create(
        model=model,
        #tools=[
        #    {
        #        "type": "mcp",
        #        "server_label": "search_jira",
        #        "server_url": server_address,
        #        "server_description": "MCP server that can search Jira tickets. Use 'search_jira' tool with 'assignee' param to search tickets by assignee. The tool returns 'Summary', 'Issue key', 'Assignee' columns. Do only POST requests to this server.",
        #        "allowed_tools": ["search_jira"],
        #        "require_approval": "never",
        #    }
        #],
        input=[
            {
                "role": "system",
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

    # Stream the model output as it is generated and immediately forward each
    # piece of text to the TTS worker via a queue.
    for event in stream:
        #print("new event")
        #print(event)
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

    retry = True
    while retry:
        try:
            start = time.perf_counter()
            stream = client.responses.create(
                model=model,
                tools=[
                    {
                        "type": "mcp",
                        "server_label": "search_jira",
                        "server_url": server_address,
                        "server_description": "MCP server that can search Jira tickets. Use 'search_jira' tool with 'assignee' param to search tickets by assignee. The tool returns 'Summary', 'Issue key', 'Assignee' columns. Do only POST requests to this server.",
                        "allowed_tools": ["search_jira"],
                        "require_approval": "never",
                    }
                ],
                input=[
                    {
                        "role": "system",
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

            # Stream the model output as it is generated and immediately forward each
            # piece of text to the TTS worker via a queue.
            for event in stream:
                #print("new event")
                #print(event)
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
            retry = False
        except Exception:
            pass

    end = time.perf_counter()
    elapsed = (end - start)
    print(f"\nModel {model} invocation time: {elapsed:.3f} s")

    # Signal the worker to stop and wait for it to finish.
    text_queue.put(None)
    worker_thread.join()
    # After all text has been processed into MP3 files, signal the
    # audio player to finish after playing everything in its queue.
    audio_queue.put(None)
    player_thread.join()


if __name__ == "__main__":
    stream_openai_to_tts()

