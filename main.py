import json
import math
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "nexus.json"
CYAN = "#00d4ff"
BG = "#00060a"
APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "command prompt": "cmd.exe",
}
SITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "outlook": "https://outlook.office.com",
}


def blank():
    return {"key": "", "lines": [], "tasks": [], "voice": True}


def load():
    try:
        saved = json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    state = blank()
    state.update({key: saved.get(key, state[key]) for key in state})
    return state


def save(state):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(state, indent=2), encoding="utf-8")


def match_pc(text):
    clean = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.lower())).strip()
    if not clean:
        return None
    if re.search(r"\b(shut down|shutdown|restart|delete|format)\b", clean):
        return {"say": "I will not shut down, restart, or delete anything from a command."}
    if re.search(r"\b(volume|sound)\b", clean) and re.search(r"\b(up|louder)\b", clean):
        return {"say": "Volume up.", "key": 175}
    if re.search(r"\b(volume|sound)\b", clean) and re.search(r"\b(down|lower|quieter)\b", clean):
        return {"say": "Volume down.", "key": 174}
    if re.search(r"\b(mute|unmute)\b", clean):
        return {"say": "Mute toggled.", "key": 173}
    opened = re.match(r"^(?:open|launch|start)\s+(.+)$", clean)
    if not opened:
        return None
    name = opened.group(1).strip()
    if name in APPS:
        return {"say": f"Opening {name}.", "app": APPS[name]}
    if name in SITES:
        return {"say": f"Opening {name}.", "url": SITES[name]}
    return {"say": f"I can open Notepad, Calculator, Paint, Explorer, Google, YouTube, or Outlook. I cannot open {name}."}


def run_pc(action):
    hidden = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if "key" in action:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", f"$w = New-Object -ComObject WScript.Shell; $w.SendKeys([char]{int(action['key'])})"],
            creationflags=hidden,
        )
    if "app" in action:
        subprocess.Popen([action["app"]])
    if "url" in action:
        os.startfile(action["url"])


def powershell(script, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return (completed.stdout or "").strip()


def speak(text):
    powershell(
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak($env:NEXUS_SAY)",
        {"NEXUS_SAY": text[:500]},
    )


def listen():
    return powershell(
        "Add-Type -AssemblyName System.Speech; "
        "$e = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
        "$e.SetInputToDefaultAudioDevice(); "
        "$e.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
        "$e.InitialSilenceTimeout = [TimeSpan]::FromSeconds(5); "
        "$r = $e.Recognize(); if ($r) { $r.Text }"
    )


def ask_xai(key, lines, message):
    history = [{
        "role": "system",
        "content": "You are NEXUS, Cai's private assistant. Address him as Cai. Be short and direct.",
    }]
    for line in lines[-8:]:
        history.append({"role": "assistant" if line["role"] == "nexus" else "user", "content": line["text"]})
    history.append({"role": "user", "content": message})
    request = urllib.request.Request(
        "https://api.x.ai/v1/chat/completions",
        data=json.dumps({"model": "grok-4.3", "max_tokens": 400, "messages": history}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace").replace("\n", " ")[:180]
        raise RuntimeError(f"The core refused the request ({error.code}). {detail}") from error
    return body["choices"][0]["message"]["content"].strip()


def main():
    import tkinter as tk

    state = load()
    root = tk.Tk()
    root.title("NEXUS")
    root.geometry("820x940")
    root.configure(bg=BG)
    root.resizable(False, False)
    angle = {"value": 0}
    busy = {"on": False}
    phase = {"text": "ADD YOUR KEY" if not state["key"] else "STANDBY"}

    canvas = tk.Canvas(root, width=760, height=560, bg=BG, highlightthickness=0)
    canvas.pack(pady=(12, 0))
    log_box = tk.Text(root, height=8, bg=BG, fg=CYAN, insertbackground=CYAN, font=("Consolas", 11), wrap="word", bd=0, padx=18)
    log_box.pack(fill="x")
    log_box.configure(state="disabled")
    bar = tk.Frame(root, bg=BG)
    bar.pack(fill="x", padx=18, pady=12)
    entry = tk.Entry(bar, bg="#010d14", fg="#e8fbff", insertbackground=CYAN, font=("Consolas", 12), bd=0)
    entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))

    def paint_log():
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        for line in state["lines"][-12:]:
            who = "YOU" if line["role"] == "user" else "NEXUS"
            log_box.insert("end", f"{who}: {line['text']}\n")
        log_box.configure(state="disabled")
        log_box.see("end")

    def remember(role, text):
        state["lines"].append({"role": role, "text": text})
        state["lines"] = state["lines"][-40:]
        save(state)
        paint_log()

    def say(text):
        remember("nexus", text)
        if state["voice"]:
            phase["text"] = "SPEAKING"
            threading.Thread(target=lambda: (speak(text), root.after(0, lambda: phase.update(text="STANDBY"))), daemon=True).start()
        else:
            phase["text"] = "STANDBY"

    def submit(_event=None):
        text = entry.get().strip()
        if not text or busy["on"]:
            return
        entry.delete(0, "end")
        remember("user", text)
        busy["on"] = True

        def work():
            try:
                action = match_pc(text)
                if action:
                    run_pc(action)
                    reply = action["say"]
                elif not state["key"]:
                    reply = "Add your xAI key in Settings."
                else:
                    phase["text"] = "THINKING"
                    reply = ask_xai(state["key"], state["lines"], text)
            except Exception as error:
                reply = str(error)

            def finish():
                say(reply)
                busy["on"] = False

            root.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def on_mic():
        if busy["on"]:
            return
        busy["on"] = True
        phase["text"] = "LISTENING"

        def work():
            try:
                heard = listen()
            except Exception as error:
                root.after(0, lambda: (phase.update(text=str(error)[:40]), busy.__setitem__("on", False)))
                return

            def finish():
                busy["on"] = False
                phase["text"] = "STANDBY"
                if not heard:
                    return
                entry.delete(0, "end")
                entry.insert(0, heard)
                submit()

            root.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def draw():
        canvas.delete("all")
        angle["value"] = (angle["value"] + 2) % 360
        cx, cy, radius = 380, 270, 190
        gap = radius * 0.62
        canvas.create_line(30, cy, cx - gap, cy, fill="#0d3347")
        canvas.create_line(cx + gap, cy, 730, cy, fill="#0d3347")
        canvas.create_line(cx, 30, cx, cy - gap, fill="#0d3347")
        canvas.create_line(cx, cy + gap, cx, 530, fill="#0d3347")
        for mark in range(72):
            theta = math.radians(mark * 5 + angle["value"] * 0.15)
            inner = radius * (0.90 if mark % 3 else 0.84)
            canvas.create_line(
                cx + math.cos(theta) * inner,
                cy + math.sin(theta) * inner,
                cx + math.cos(theta) * radius,
                cy + math.sin(theta) * radius,
                fill=CYAN,
            )
        for index, scale in enumerate((1.05, 0.82, 0.58, 0.36)):
            size = radius * scale
            start = angle["value"] * (1 if index % 2 == 0 else -1.4)
            canvas.create_arc(cx - size, cy - size, cx + size, cy + size, start=start, extent=270, style="arc", outline=CYAN, width=2)
        canvas.create_oval(cx - 14, cy - 14, cx + 14, cy + 14, fill=CYAN, outline="")
        canvas.create_text(cx, cy - 42, text="NEXUS", fill="#e8fbff", font=("Consolas", 18, "bold"))
        canvas.create_text(cx, cy + radius + 28, text=phase["text"], fill=CYAN, font=("Consolas", 12, "bold"))
        root.after(40, draw)

    def open_settings():
        box = tk.Toplevel(root)
        box.title("NEXUS")
        box.configure(bg="#010d14")
        box.geometry("420x200")
        tk.Label(box, text="xAI key", fg=CYAN, bg="#010d14", font=("Consolas", 11)).pack(anchor="w", padx=16, pady=(16, 4))
        key = tk.Entry(box, show="*", bg=BG, fg="#e8fbff", font=("Consolas", 11), bd=0)
        key.pack(fill="x", padx=16, ipady=6)
        voice = tk.BooleanVar(value=state["voice"])
        tk.Checkbutton(box, text="Speak the reply", variable=voice, fg="#e8fbff", bg="#010d14", selectcolor=BG, font=("Consolas", 11)).pack(anchor="w", padx=16, pady=12)

        def keep():
            typed = key.get().strip()
            if typed:
                state["key"] = typed
            state["voice"] = bool(voice.get())
            save(state)
            phase["text"] = "STANDBY" if state["key"] else "ADD YOUR KEY"
            box.destroy()

        tk.Button(box, text="Save", command=keep, bg=CYAN, fg="#001018", font=("Consolas", 11, "bold"), bd=0, padx=14, pady=6).pack(anchor="e", padx=16)

    def button(label, command):
        return tk.Button(bar, text=label, command=command, bg=CYAN, fg="#001018", font=("Consolas", 11, "bold"), bd=0, padx=12, pady=6)

    button("Settings", open_settings).pack(side="right", padx=(8, 0))
    button("Mic", on_mic).pack(side="right", padx=8)
    button("Ask", submit).pack(side="right")
    entry.bind("<Return>", submit)
    paint_log()
    draw()
    root.mainloop()


if __name__ == "__main__":
    main()
