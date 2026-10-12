"""
JARVIS-lite v2: free voice assistant with "Hey Jarvis" wake word + memory.
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
import pygame
from groq import Groq
import openwakeword
from openwakeword.model import Model
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# ---------- CONFIG ----------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
ASSISTANT_NAME = "Jarvis"
MODEL = "openai/gpt-oss-20b"
VOICE_NAME = "en-GB-RyanNeural"
TEMP_AUDIO_FILE = "jarvis_reply.mp3"
MEMORY_FILE = "jarvis_memory.json"
MAX_SAVED_MESSAGES = 40
WAKE_THRESHOLD = 0.5

SYSTEM_PROMPT = (
    f"You are {ASSISTANT_NAME}, a sophisticated, impeccably well-mannered English "
    "butler serving as a personal voice assistant. Speak with dry wit, formal "
    "courtesy, and quiet confidence -- address the user respectfully, favour "
    "understated British phrasing, and never sound like a generic chatbot. "
    "Despite the refined manner, keep answers short (1-3 sentences) since they "
    "will be spoken aloud. You have memory of past conversations with this "
    "user, provided below."
)
SILENCE_TIMEOUT = 6

GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_SEARCH_ENGINE_ID = os.environ.get("GOOGLE_SEARCH_ENGINE_ID", "")


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

recognizer = sr.Recognizer()
client = Groq(api_key=GROQ_API_KEY)

print("Loading wake word model (first run downloads it, needs internet)...")
openwakeword.utils.download_models()
oww_model = Model(wakeword_models=["hey_jarvis"])

pygame.mixer.init()


async def _generate_speech(text: str):
    communicate = edge_tts.Communicate(text, VOICE_NAME)
    await communicate.save(TEMP_AUDIO_FILE)


def speak(text: str):
    if not text or not text.strip():
        text = "I'm afraid I didn't quite catch a response for that, sir."
    print(f"{ASSISTANT_NAME}: {text}")
    asyncio.run(_generate_speech(text))
    pygame.mixer.music.load(TEMP_AUDIO_FILE)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    pygame.mixer.music.unload()
    os.remove(TEMP_AUDIO_FILE)


def listen_for_command() -> str:
    with sr.Microphone() as source:
        print("Listening...")
        recognizer.adjust_for_ambient_noise(source, duration=0.4)
        try:
            audio = recognizer.listen(source, timeout=SILENCE_TIMEOUT, phrase_time_limit=15)
        except sr.WaitTimeoutError:
            return None
    try:
        text = recognizer.recognize_google(audio)
        print(f"You: {text}")
        return text
    except sr.UnknownValueError:
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
    unit = unit.rstrip("s")
    seconds = amount * {"hour": 3600, "minute": 60, "second": 1}[unit]
    label = f"{amount} {unit}{'s' if amount != 1 else ''}"

    def alert():
        speak(f"Your {label} timer is up.")

    threading.Timer(seconds, alert).start()
    speak(f"Timer set for {label}.")


def _get_volume_interface():
    devices = AudioUtilities.GetSpeakers()
    if hasattr(devices, "EndpointVolume"):
        return devices.EndpointVolume
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume_percent(percent: int):
    percent = max(0, min(100, percent))
    volume = _get_volume_interface()
    volume.SetMasterVolumeLevelScalar(percent / 100.0, None)


def adjust_volume(delta_percent: int):
    volume = _get_volume_interface()
    current = volume.GetMasterVolumeLevelScalar() * 100
    set_volume_percent(current + delta_percent)


APP_SHORTCUTS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
}


def launch_app(name: str) -> bool:
    name = name.strip().lower()
    if name in APP_SHORTCUTS:
        subprocess.Popen(APP_SHORTCUTS[name])
        return True
    try:
        subprocess.Popen(name if name.endswith(".exe") else name + ".exe")
        return True
    except OSError:
        return False


def google_lookup(query: str) -> str:
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_ENGINE_ID:
        return ("Google Search isn't set up yet -- I'd need a free API key and "
                "search engine ID for that.")
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_SEARCH_API_KEY,
                "cx": GOOGLE_SEARCH_ENGINE_ID,
                "q": query,
                "num": 3,
            },
            timeout=6,
        ).json()
        items = resp.get("items", [])
        if not items:
            return "I couldn't find anything on that, sir."
        top = items[0]
        return f"{top.get('title', '')}. {top.get('snippet', '')}"
    except Exception:
        return "I wasn't able to search just now."


def handle_command(text: str) -> bool:
    t = text.lower()

    if "set volume to" in t or "set the volume to" in t:
        match = re.search(r"(\d+)\s*percent", t) or re.search(r"(\d+)", t)
        if match:
            pct = int(match.group(1))
            set_volume_percent(pct)
            speak(f"Volume set to {pct} percent.")
            return True

    if "volume up" in t or "louder" in t or "turn it up" in t:
        adjust_volume(10)
        speak("Turning it up.")
        return True

    if "volume down" in t or "quieter" in t or "turn it down" in t:
        adjust_volume(-10)
        speak("Lowering the volume.")
        return True

    if t.startswith("open ") or t.startswith("launch "):
        app_name = t.split(" ", 1)[1].replace("the app", "").strip()
        if app_name not in ("browser", "chrome", "youtube") and launch_app(app_name):
            speak(f"Opening {app_name}.")
            return True

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
    if "look up" in t or "google" in t:
        query = t.replace("look up", "").replace("google", "").strip()
        speak(google_lookup(query))
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
    reply = response.choices[0].message.content or "I'm sorry, I don't have a response for that."
    conversation.append({"role": "assistant", "content": reply})
    save_memory(conversation[1:])
    return reply


def wake_word_loop():
    CHUNK = 1280
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
        speak("At your service.")
        while True:
            text = listen_for_command()
            if text is None:
                break
            if not text:
                continue
            if "quit" in text.lower() or "exit" in text.lower():
                speak("Very good. Goodbye.")
                return
            if handle_command(text):
                continue
            reply = ask_brain(text)
            speak(reply)


if __name__ == "__main__":
    main()