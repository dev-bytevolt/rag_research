import os
import time
from pathlib import Path

from openai import OpenAI
from openai.types.responses import ResponseOutputText
from openai.types.responses.response_output_message import ResponseOutputMessage

openAIKey = "<YOUR OPEN AI TOKEN>"

def main() -> None:
    client = OpenAI(api_key=openAIKey)

    script_dir = Path(__file__).resolve().parent
    csv_path = script_dir / "Jira.csv"

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found at {csv_path}")

    fileId = 'file-95YP2vCoCxvhAnw1x9s1xQ'
    #with csv_path.open("rb") as f:
    #    uploaded_file = client.files.create(file=f, purpose="assistants")
    #fileId = uploaded_file.id
    #print(f'uploaded file {fileId}')

    modelsToBenchmark = ["gpt-4o-mini", "gpt-5-mini", "gpt-4o", "gpt-5.2-chat-latest"]

    system_prompt = (
        "You are a careful data analyst working with a CSV file named Jira.csv."
        "You will be provided with the CSV file contents as an attached file."
        "Always base your answers strictly on the provided file contents."
        "The file contains these important colums 'Summary', 'Issue key', 'Assignee'."
        "When checking who the ticket is assigned to, base you answer strictly on the 'Assignee' column."
    )

    user_prompt = (
        #"Count how many data rows are present in the csv file"
        "Which tickets are assigned to Hrishikesh Patidar? Return the list of ticket keyss and their summary."
    )

    for model in modelsToBenchmark:
        print("\n========================")
        print(f"model: {model}")
        start = time.perf_counter()
        response = client.responses.create(
            model=model,
            tools=[
                {
                    "type": "code_interpreter",
                    "container": {
                        "type":     "auto",
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


if __name__ == "__main__":
    main()


