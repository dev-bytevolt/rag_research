import argparse
import json
import os
import time

from openai import OpenAI

from pm_tts import TTSEngine
from pm_prompts import getUserInput, load_system_prompts

openAIKey = "<YOUR OPEN AI TOKEN>"



def performEngineCycle(model: str, tts_engine: TTSEngine, system_prompts: dict[str:str], client:OpenAI, conversation: list) -> tuple[bool, list]:
    print("===================================")
    mode_select_prompt = system_prompts["00_mode_select"]

    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": mode_select_prompt}]+conversation,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "mode_and_message",
                "schema": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["mode", "message"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
        stream=False,
    )
    try:
        mode_data = json.loads(response.choices[0].message.content)
    except Exception as e:
        print(e)
        raise e
    if "mode" not in mode_data:
        print("ERROR: No mode selected")
        return (True, conversation)

    mode = mode_data["mode"]

    end = time.perf_counter()
    elapsed = (end - start)
    print(f"Mode selected {mode} time: {elapsed:.3f} s")
    
    if mode == "IDLE" or mode == "END":
        if "message" in mode_data and mode_data["message"] != "":
            message = mode_data["message"]
            print(f"\nPM: {message}")
            tts_engine.put_text_chunk(message+"\n")
            conversation.append({"role": "assistant", "content": message})
        return (mode == "END", conversation)
    if mode == "GENERATE":
        if "message" in mode_data and mode_data["message"] != "":
            message = mode_data["message"]
            print(f"\nPM: {message}")
            tts_engine.put_text_chunk(message+"\n")
            conversation.append({"role": "assistant", "content": message})
        
        system_prompt = system_prompts["04_mode_generate"]

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}]+conversation,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "document_and_message",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "document": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "required": ["document", "message"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
            stream=False,
        )

        try:
            data = json.loads(response.choices[0].message.content)
        except Exception as e:
            raise e
        
        print("\n===================================")
        if "document" in data and data["document"] != "":
            doc = data["document"]
            print("   DOCUMENT PRODUCED")
            print("===================================")
            print(doc)
            conversation.append({"role": "assistant", "content": f"Here is the document:\n\n\n{doc}"})
        else:
            print("   NO DOCUMENT PRODUCED!")
        print("===================================")

        if "message" in data and data["message"] != "":
            message = data["message"]
            print(f"\nPM: {message}")
            tts_engine.put_text_chunk(message+"\n")
            conversation.append({"role": "assistant", "content": message})

    else:
        system_prompt = ""
        if mode == "RECOMMEND":
            system_prompt = system_prompts["01_mode_recommend"]
        elif mode == "REQUIREMENTS":
            system_prompt = system_prompts["02_mode_requirements"]
        elif mode == "FOLLOWUP":
            system_prompt = system_prompts["03_mode_followup"]
        else:
            print(f"ERROR: Unknown mode {mode} selected")
            return (False, conversation)
        
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}]+conversation,
            stream=True,
        )

        output = ""
        startedPronouncing = False
        try:
            print("PM: ", end="", flush=True)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # `delta.content` may be None or an empty string.
                text_piece = getattr(delta, "content", None)
                if not text_piece:
                    continue

                if tts_engine.is_enabled() and not startedPronouncing:
                    startedPronouncing = True
                    end = time.perf_counter()
                    elapsed = (end - start)
                    print(f"\n\nMode {mode} started speaking in: {elapsed:.3f} s")

                # Print to stdout so you can see the text as it streams.
                print(text_piece, end="", flush=True)
                
                # Forward raw text pieces directly to the TTS worker; it
                # will buffer until it sees newline characters.
                output += text_piece
                tts_engine.put_text_chunk(text_piece)
            print()
        except Exception as e:
            raise e
        
        tts_engine.put_text_chunk("\n")
        
        conversation.append({"role": "assistant", "content": output})

    end = time.perf_counter()
    elapsed = (end - start)
    print(f"Mode {mode} invocation time: {elapsed:.3f} s")

    return (False, conversation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Product manager mock")
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Disable TTS playback and microphone-based voice recognition.",
    )
    args = parser.parse_args()
    text_only = args.text_only
    text_only = True

    system_prompts = load_system_prompts()
    
    client = OpenAI(api_key=openAIKey)

    tts_engine = TTSEngine()
    tts_engine.set_enabled(not text_only)
    tts_engine.start()

    #model = "gpt-4o-mini"
    model = "gpt-5.2-chat-latest"

    conversation = [{"role": "user", "content": ""}]

    while True:
        shouldTerminate, conversation = performEngineCycle(model, tts_engine, system_prompts, client, conversation)
        if shouldTerminate:
            break
        userPrompt = getUserInput(tts_engine)
        conversation.append({"role": "user", "content": userPrompt})


    tts_engine.close()
    print(f"\nExecution complete")
