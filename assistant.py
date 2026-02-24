import subprocess
import os
import sys
import winreg
import time

# -------- SETTINGS ----------
FRONTEND_PORT = "5500"
BACKEND_PORT = "8000"

PROJECT_DIR = r"D:\voice-assistant\voice-assistant"

WEBSITE_URL = f"http://127.0.0.1:5501/login.html"

ASSISTANT_NAME = "Learn Out Loud Assistant"
WAKE_COMMAND = "open learn out loud"
# ----------------------------


# -------- TEXT TO SPEECH --------
def speak(text):
    print(f"{ASSISTANT_NAME}: {text}")

    subprocess.run([
        "powershell",
        "-Command",
        f"Add-Type -AssemblyName System.Speech; "
        f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text}')"
    ], shell=True)





# -------- START BACKEND SERVER --------
def start_backend():
    try:
        subprocess.Popen(
            ["python", "backend.py"],
            cwd=PROJECT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        time.sleep(3)

        print("Backend started on port", BACKEND_PORT)

    except Exception as e:
        print("Backend start error:", e)


# -------- VOICE RECOGNITION --------
def listen():

    try:

        print("Listening...")

        command = subprocess.check_output([
            "powershell",
            "-Command",
            """
            Add-Type -AssemblyName System.Speech;

            $recognizer = New-Object System.Speech.Recognition.SpeechRecognitionEngine;

            # Define exact commands
            $choices = New-Object System.Speech.Recognition.Choices;
            $choices.Add('open learn out loud');
            $choices.Add('open learn aloud');
            $choices.Add('open learn outloud');
            $choices.Add('exit');

            $builder = New-Object System.Speech.Recognition.GrammarBuilder;
            $builder.Append($choices);

            $grammar = New-Object System.Speech.Recognition.Grammar($builder);

            $recognizer.LoadGrammar($grammar);

            $recognizer.SetInputToDefaultAudioDevice();

            $result = $recognizer.Recognize();

            if ($result -ne $null) {
                $result.Text
            }
            """
        ], universal_newlines=True)

        command = command.strip().lower()

        print("Heard:", command)

        return command

    except Exception as e:

        print("Recognition error:", e)

        return ""

# -------- OPEN WEBSITE --------
def open_website():

    start_backend()

    os.startfile(WEBSITE_URL)

    speak("Opening Learn Out Loud")


# -------- ADD TO STARTUP --------
def add_to_startup():

    try:

        exe_path = sys.executable

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )

        winreg.SetValueEx(
            key,
            "LearnOutLoudAssistant",
            0,
            winreg.REG_SZ,
            exe_path
        )

        winreg.CloseKey(key)

    except:
        pass


# -------- MAIN LOOP --------
def main():

    speak("Learn Out Loud assistant is ready. Say open learn out loud to begin.")

    while True:

        command = listen()

        if ("learn" in command and("loud" in command or "aloud" in command or "outloud" in command)):
            open_website()

        elif "exit" in command or "stop" in command:

            speak("Goodbye")

            break


# -------- ENTRY --------
if __name__ == "__main__":

    add_to_startup()

    main()