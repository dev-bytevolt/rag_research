import os
import sys
import select
import io
import re
from pathlib import Path
import speech_recognition as sr

from pm_tts import TTSEngine


SCRIPT_DIR = Path(__file__).resolve().parent


def load_system_prompts() -> dict[str:str]:
    prompts: dict[str:str] = {}
    prompts_dir = SCRIPT_DIR / "prompts"
    for (dirpath, _, filenames) in os.walk(prompts_dir):
        for f in filenames:
            if f.endswith(".md"):
                with Path(os.path.join(dirpath,f)).open("r", encoding="utf-8") as data:
                    prompt = data.read()
                    name = f.removesuffix(".md")
                    prompts[name] = prompt

    for name in prompts:
        prompts[name] = substitute_templates(prompts[name], prompts)
        
    return prompts

def substitute_templates(prompt: str, prompts:dict[str:str]) -> str:
    substitution_template = re.compile(r'\{\{(.*?)\}\}')
    for match in re.finditer(substitution_template, prompt):
        template_name = match.group(1)
        if template_name in prompts:
            prompt = prompt.replace(match.group(0), substitute_templates(prompts[template_name], prompts))
    return prompt

def getUserInput(tts: TTSEngine) -> str:
    voice_enabled = tts.is_enabled()

    while True:
        if voice_enabled:
            prompt = "\nYou say [TYPE your prompt OR leave field empty and press ENTER to speak]: "
        else:
            prompt = "\nYou say [TYPE your prompt]: "

        user_input = input(prompt).strip()
        tts.stopPlayback()

        if user_input != "":
            return user_input

        if not voice_enabled:
            continue

        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                # Adjust for ambient noise.
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                print("Listening... (press ENTER when done)")

                audio_buffer = io.BytesIO()

                while True:
                    # If user pressed ENTER, stop recording.
                    rlist, _, _ = select.select([sys.stdin], [], [], 0)
                    if sys.stdin in rlist:
                        _ = sys.stdin.readline()
                        break

                    # Read raw audio frames from the microphone stream.
                    data = source.stream.read(source.CHUNK)
                    if not data:
                        break
                    audio_buffer.write(data)

                if audio_buffer.tell() == 0:
                    print("No audio captured.")
                    continue

                audio = sr.AudioData(
                    audio_buffer.getvalue(),
                    source.SAMPLE_RATE,
                    source.SAMPLE_WIDTH,
                )
        except Exception as e:
            print(f"Error accessing microphone: {e}")
            continue

        print("Transcribing your speech...")
        try:
            text = recognizer.recognize_google(audio)
            text = text.strip()
            print(f"\nYou said: {text}")
            return text
        except sr.UnknownValueError:
            print("Sorry, I could not understand what you said.")
            continue
        except sr.RequestError as e:
            print(f"Speech recognition service error: {e}")
            continue