import csv
import json
import os
from pathlib import Path
from typing import List, Dict

import logging
import time

from openai import OpenAI

# Basic logging configuration; adjust level/format as needed.
logging.basicConfig(
    level=logging.ERROR,
    # level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("jira_function_tools")

openAIKey = "<YOUR OPEN AI TOKEN>"

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
                    "Summary": row.get("\ufeffSummary", ""),
                    "Issue key": row.get("Issue key", ""),
                }
            )

    return results


def call_openai_with_function_tools_example() -> None:
    client = OpenAI(api_key=openAIKey)
    system_prompt = (
        "You are a careful data analyst working with the 'search_jira' function tool. "
        "The tool accepts only the 'assignee' param to search tickets by assignee and "
        "returns 'Summary', 'Issue key', 'Assignee' columns. "
        "Use the available function tools when the user asks about Jira issues."
    )

    user_prompt = (
        # "Find all Jira tickets assigned to 'Hrishikesh Patidar' and summarize them."
        "Find all Jira tickets assigned to Arpit and summarize them."
    )

    # Define the function tool we expose to the model.
    tools = [
        {
            "type": "function",
            "name": "search_jira",
            "description": (
                "Search Jira tickets in a local CSV file by the assignee name and "
                "return matching rows with 'Summary', 'Issue key', and 'Assignee'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "assignee": {
                        "type": "string",
                        "description": (
                            "The name of the assignee to search for, e.g. 'Arpit'. "
                            "Match should be case-insensitive and may be a substring."
                        ),
                    }
                },
                "required": ["assignee"],
            },
        }
    ]

    modelsToBenchmark = ["gpt-4o-mini", "gpt-5-mini", "gpt-4o", "gpt-5.2-chat-latest"]

    for model in modelsToBenchmark:
        print("\n========================")
        print(f"model: {model}")

        start = time.perf_counter()

        # Conversation history that will be augmented with tool calls.
        input_list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # First call: let the model decide whether to call the tool.
        response = client.responses.create(
            model=model,
            tools=tools,
            input=input_list,
        )

        # Append tool call events to the running input list.
        input_list += response.output

        # Execute any function calls returned by the model.
        for item in response.output:
            if item.type == "function_call" and item.name == "search_jira":
                args = json.loads(item.arguments or "{}")
                assignee = args.get("assignee", "")
                matches = search_tickets_by_assignee(assignee)

                input_list.append(
                    {
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": json.dumps(matches),
                    }
                )

        end = time.perf_counter()
        elapsed = end - start
        print(f"\nModel {model} func call: {elapsed:.3f} s")

        # Second call: ask the model to summarize based on tool outputs.
        final_response = client.responses.create(
            model=model,
            tools=tools,
            instructions=(
                "Summarize the Jira tickets returned by the 'search_jira' "
                "function tool. Focus on key themes, priorities if available, "
                "and any notable blockers."
            ),
            input=input_list,
        )

        end = time.perf_counter()
        elapsed = end - start

        print(f"Model {model} response:")
        print(final_response.output_text)
        print(f"\nModel {model} invocation time: {elapsed:.3f} s")

    print("\n\ntested all models")


if __name__ == "__main__":
    call_openai_with_function_tools_example()
    os._exit(0)
