"""
JARVIS-lite v2: free voice assistant with "Hey Jarvis" wake word + memory.

STACK (all $0):
  - Wake word: openWakeWord (free, offline, ships a pretrained "hey jarvis" model)
  - Brain:     Groq API (free tier)
  - Hearing:   Google's free web speech recognition (via SpeechRecognition)
  - Voice:     edge-tts (free Microsoft Edge neural voices -- British accent)
  - Memory:    saved to jarvis_memory.json next to this script

SETUP (Command Prompt):
    pip install SpeechRecognition edge-tts playsound==1.2.2 groq keyboard
    pip install pyautogui pipwin openwakeword pyaudio numpy requests feedparser
    pipwin install pyaudio
    (if pipwin fails, use a prebuilt wheel from the Gohlke unofficial
     wheels site instead: pip install that_file.whl)

FIRST RUN ONLY: openWakeWord needs to download its models once. This
script does that automatically the first time you run it (nees internet).

RUN:
    python jarvis.py

Say "Hey Jarvis" and wait for the confirmation sound/print, then speak
your command. Say "quit" or "exit" to close it.
"""

import os
import re
import json
import asyncio
import threading
import subprocess
import webbrowser
import datetime

import numpy as np
import pyaudio
import requests
import feedparser
import speech_recognition as sr
import edge_tts
from playsound import playsound
from groq import Groq
import openwakeword
from openwakeword.model import Model

# ---------- CONFIG ----------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
ASSISTANT_NAME = "Jarvis"
MODEL = "openai/gpt-oss-20b"       # fast + free on Groq
VOICE_NAME = "en-GB-RyanNeural"      # British accent -- change to taste
TEMP_AUDIO_FILE = "jarvis_reply.mp3"
MEMORY_FILE = "jarvis_memory.json"
MAX_SAVED_MESSAGES = 40              # how many past turns to keep on disk
WAKE_THRESHOLD = 0.5                 # lower = more sensitive (more false triggers)

SYSTEM_PROMPT = (
    f"You are {ASSISTANT_NAME}, a concise, helpful voice assistant. "
    "Keep answers short (1-3 sentences) since they will be spoken aloud. "
    "You have memory of past conversations with this user, provided below."
)

# ---------- MEMORY ----------
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_memory(messages):
    trimmed = messages[-MAX_SAVED_MESSAGES:]
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2)


past_messages = load_memory()
conversation = [{"role": "system", "content": SYSTEM_PROMPT}] + past_messages

# ---------- SETUP ----------
recognizer = sr.Recognizer()
client = Groq(api_key=GROQ_API_KEY)

print("Loading wake word model (first run downloads it, needs internet)...")
openwakeword.utils.download_models()
oww_model = Model(wakeword_models=["hey_jarvis"])


async def _generate_speech(text: str):
    communicate = edge_tts.Communicate(text, VOICE_NAME)
    await communicate.save(TEMP_AUDIO_FILE)


def speak(text: str):
    print(f"{ASSISTANT_NAME}: {text}")
    asyncio.run(_generate_speech(text))
    playsound(TEMP_AUDIO_FILE)
    os.remove(TEMP_AUDIO_FILE)


def listen_for_command() -> str:
    with sr.Microphone() as source:
        print("Listening for your command...")
        recognizer.adjust_for_ambient_noise(source, duration=0.4)
        try:
            audio = recognizer.listen(source, timeout=6, phrase_time_limit=12)
        except sr.WaitTimeoutError:
            return ""
    try:
        text = recognizer.recognize_google(audio)
        print(f"You: {text}")
        return text
    except sr.UnknownValueError:
        speak("Sorry, I didn't catch that.")
        return ""
    except sr.RequestError:
        speak("I couldn't reach the speech service. Check your internet connection.")
        return ""


def get_weather() -> str:
    try:
        loc = requests.get("http://ip-api.com/json/", timeout=5).json()
        lat, lon = loc["lat"], loc["lon"]
        city = loc.get("city", "your area")
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&current=temperature_2m",
            timeout=5,
        ).json()
        temp = w["current"]["temperature_2m"]
        return f"It's currently {temp} degrees Celsius in {city}."
    except Exception:
        return "I couldn't get the weather right now -- check your internet connection."


def get_news() -> str:
    try:
        feed = feedparser.parse("http://feeds.bbci.co.uk/news/rss.xml")
        headlines = [entry.title for entry in feed.entries[:3]]
        if not headlines:
            return "I couldn't find any headlines right now."
        return "Here are the top headlines. " + ". ".join(headlines)
    except Exception:
        return "I couldn't fetch the news right now -- check your internet connection."


def start_timer(amount: int, unit: str):
    unit = unit.rstrip("s")  # normalize "minutes" -> "minute"
    seconds = amount * {"hour": 3600, "minute": 60, "second": 1}[unit]
    label = f"{amount} {unit}{'s' if amount != 1 else ''}"

    def alert():
        speak(f"Your {label} timer is up.")

    threading.Timer(seconds, alert).start()
    speak(f"Timer set for {label}.")


def handle_command(text: str) -> bool:
    """Local commands handled instantly, no AI call needed."""
    t = text.lower()

    if "timer" in t:
        match = re.search(r"(\d+)\s*(hour|minute|second)s?", t)
        if match:
            start_timer(int(match.group(1)), match.group(2))
            return True
        speak("Tell me the duration, like 'set a timer for 5 minutes'.")
        return True

    if "weather" in t:
        speak(get_weather())
        return True

    if "news" in t or "headlines" in t:
        speak(get_news())
        return True

    if "play" in t and "youtube" in t:
        query = t.split("play", 1)[1].replace("on youtube", "").strip()
        webbrowser.open(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")
        speak(f"Searching YouTube for {query}.")
        return True

    if "youtube" in t:
        webbrowser.open("https://www.youtube.com")
        speak("Opening YouTube.")
        return True

    if "open notepad" in t:
        subprocess.Popen(["notepad.exe"])
        speak("Opening Notepad.")
        return True
    if "open browser" in t or "open chrome" in t:
        webbrowser.open("https://www.google.com")
        speak("Opening your browser.")
        return True
    if "search for" in t:
        query = t.split("search for", 1)[1].strip()
        webbrowser.open(f"https://www.google.com/search?q={query}")
        speak(f"Searching for {query}.")
        return True
    if "what time" in t:
        now = datetime.datetime.now().strftime("%I:%M %p")
        speak(f"It's {now}.")
        return True
    if "what's the date" in t or "what is the date" in t:
        today = datetime.datetime.now().strftime("%A, %B %d")
        speak(f"Today is {today}.")
        return True
    if "forget everything" in t or "clear your memory" in t:
        conversation[:] = [{"role": "system", "content": SYSTEM_PROMPT}]
        save_memory([])
        speak("I've cleared my memory.")
        return True

    return False


def ask_brain(text: str) -> str:
    conversation.append({"role": "user", "content": text})
    response = client.chat.completions.create(
        model=MODEL,
        messages=conversation,
        max_tokens=200,
    )
    reply = response.choices[0].message.content
    conversation.append({"role": "assistant", "content": reply})
    # persist everything except the system prompt
    save_memory(conversation[1:])
    return reply


def wake_word_loop():
    """Blocks until 'hey jarvis' is heard, then returns."""
    CHUNK = 1280  # openWakeWord expects 80ms chunks at 16kHz
    RATE = 16000
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                      input=True, frames_per_buffer=CHUNK)
    print(f'Listening for "Hey {ASSISTANT_NAME}"...')
    try:
        while True:
            audio_chunk = np.frombuffer(stream.read(CHUNK, exception_on_overflow=False),
                                         dtype=np.int16)
            prediction = oww_model.predict(audio_chunk)
            score = prediction.get("hey_jarvis", 0)
            if score > WAKE_THRESHOLD:
                oww_model.reset()
                break
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def main():
    speak(f"{ASSISTANT_NAME} online. Say hey {ASSISTANT_NAME.lower()} to talk to me.")
    while True:
        wake_word_loop()
        speak("Yes?")
        text = listen_for_command()
        if not text:
            continue
        if "quit" in text.lower() or "exit" in text.lower():
            speak("Goodbye.")
            break
        if handle_command(text):
            continue
        reply = ask_brain(text)
        speak(reply)


if __name__ == "__main__":
    main()
