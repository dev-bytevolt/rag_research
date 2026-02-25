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

# Basic logging configuration; adjust level/format as needed.
logging.basicConfig(
    level=logging.ERROR,
    #level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("jira_mcp_server")

openAIKey = "<YOUR OPEN AI TOKEN>"
server_address = "https://<PUT YOUR SERVER HOST HERE, HAS TO HAVE A VALID HTTPS CERT>/mcp"
server_port = 9999

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "Jira.csv"


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


def call_openai_with_mcp_example() -> None:
    client = OpenAI(api_key=openAIKey)
    system_prompt = (
        "You are a careful data analyst working with 'search_jira' tool."
        "The tool accepts only the 'assignee' param to search tickets by assignee and returns 'Summary', 'Issue key', 'Assignee' columns."
        "Use the available MCP tools when the user asks about Jira issues."
    )

    user_prompt = (
        #"Find all Jira tickets assigned to 'Hrishikesh Patidar' and summarize them."
        "Find all Jira tickets assigned to Arpit and summarize them."
    )

    modelsToBenchmark = ["gpt-4o-mini", "gpt-5-mini", "gpt-4o", "gpt-5.2-chat-latest"]

    for model in modelsToBenchmark:
        print("\n========================")
        print(f"model: {model}")

        retry = True
        while retry:
            try:
                start = time.perf_counter()

                response = client.responses.create(
                    model=model,
                    tools=[
                        {
                            "type": "mcp",
                            "server_label": "search_jira",
                            "server_url": server_address,
                            "server_description": "MCP server that can search Jira tickets. Use 'search_jira' tool with 'assignee' param to search tickets by assignee. The tool returns 'Summary', 'Issue key', 'Assignee' columns. Do only POST requests to this server.",
                            "allowed_tools": [
                                "search_jira"
                            ],
                            "require_approval": "never",
                        }
                    ],
                    input=[
                        {
                            "role": "system",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": system_prompt,
                                }
                            ],
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": user_prompt,
                                }
                            ],
                        },
                    ],
                )

                end = time.perf_counter()
                elapsed = (end - start)

                print(f"Model {model} response:")
                for res in response.output:
                    if type(res) is ResponseOutputMessage:
                        for content in res.content:
                            if type(content) is ResponseOutputText:
                                print(content.text)
                print(f"\nModel {model} invocation time: {elapsed:.3f} s")
                retry = False
            except Exception:
                time.sleep(1)
                pass

    print("\n\ntested all models")


if __name__ == "__main__":
    # Create HTTP app with global request/response logging middleware.
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

    # Run the OpenAI call once the server is up.
    call_openai_with_mcp_example()

    #server_thread.join()
    os._exit(0)

