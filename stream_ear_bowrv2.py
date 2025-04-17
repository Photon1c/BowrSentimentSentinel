import os
import sys
import subprocess
import time
import csv
import json
import uuid
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

# ─── LOAD CONFIG ──────────────────────────────────────────────────────────────
load_dotenv()
with open("settings.json") as f:
    CONFIG = json.load(f)

BASE_DIR = CONFIG["BASE_DIR"]
REPORTS_DIR = os.path.join(BASE_DIR, CONFIG["REPORT_SUBDIR"])
os.makedirs(REPORTS_DIR, exist_ok=True)

MODULE = CONFIG["modules"]["stream_ear_bowr"]
STREAM_URLS = MODULE.get("STREAM_URLS", [])
RECORD_SECONDS = MODULE.get("RECORD_SECONDS", 30)
INTERVAL_MINUTES = MODULE.get("INTERVAL_MINUTES", 15)
TOKEN_CAP = MODULE.get("TOKEN_CAP", 5000)
KEYWORDS = MODULE.get("KEYWORDS", [])

TMP_TS = os.path.join(BASE_DIR, "temp_stream.ts")
OUTPUT_WAV = os.path.join(BASE_DIR, "stream_audio.wav")
LAST_CHIRP_PATH = os.path.join(BASE_DIR, "static", "last_chirp.json")
SEED_INDEX_PATH = os.path.join(BASE_DIR, "static", "seed_index.json")

# ─── UTILS ─────────────────────────────────────────────────────────────────────
def show_progress_bar(task_name="Processing", duration=3):
    for _ in tqdm(range(duration), desc=task_name, ncols=75):
        time.sleep(1)

def show_live_timer(seconds):
    for i in range(seconds):
        sys.stdout.write(f"\r🔄 Listening: {i+1:02d}s")
        sys.stdout.flush()
        time.sleep(1)
    print()

# ─── AUDIO ─────────────────────────────────────────────────────────────────────
def record_stream(stream_url, output_file, duration=30, retries=2):
    for attempt in range(1, retries + 1):
        print(f"[*] Attempt {attempt}: Recording {duration}s of stream...")
        if os.path.exists(TMP_TS):
            os.remove(TMP_TS)
        cmd = ["streamlink", "--hls-duration", str(duration), "-o", TMP_TS, stream_url, "best"]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            print("[!] Streamlink error – is this a live stream?")
            return False
        if not os.path.exists(TMP_TS) or os.path.getsize(TMP_TS) < 200000:
            print("[!] Stream file missing or too small — likely an ad or dead air.")
            return False
        ffmpeg_cmd = ["ffmpeg", "-y", "-i", TMP_TS, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", output_file]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("[!] ffmpeg failed:", result.stderr)
            return False
        if os.path.exists(output_file) and os.path.getsize(output_file) > 50000:
            os.remove(TMP_TS)
            print("[*] Recording and conversion complete.")
            return True
    return False

# ─── TRANSCRIBE ────────────────────────────────────────────────────────────────
def transcribe_audio(file_path):
    print("[*] Transcribing audio with OpenAI GPT-4o...")
    client = OpenAI()
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=audio_file
        )
    return transcript.text

def estimate_token_usage(text):
    return int(len(text) / 4)

# ─── SCORE + LOG ───────────────────────────────────────────────────────────────
def score_confidence(keywords):
    if not keywords:
        return 0.1
    return min(0.3 + len(keywords) * 0.1, 0.95)

def determine_status(confidence):
    if confidence >= 0.8:
        return "blooming"
    elif confidence >= 0.6:
        return "sprouting"
    elif confidence >= 0.4:
        return "planted"
    elif confidence < 0.2:
        return "discarded"
    return "dormant"

def log_transcription_with_keywords(text, stream_url):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    keywords_hit = [kw for kw in KEYWORDS if kw.lower() in text.lower()]
    matched_str = ", ".join(keywords_hit) if keywords_hit else ""
    day_stamp = datetime.now().strftime("%Y_%m_%d")
    all_path = os.path.join(REPORTS_DIR, f"all_transcripts_{day_stamp}.csv")
    master_path = os.path.join(REPORTS_DIR, f"master_hits_{day_stamp}.csv")
    with open(all_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "matched_keywords", "snippet"])
        writer.writerow([timestamp, matched_str, text.strip()])
    if keywords_hit:
        with open(master_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(["timestamp", "matched_keywords", "snippet"])
            writer.writerow([timestamp, matched_str, text.strip()])
        print("\n🐦 CHIRP DETECTED!")

    confidence = score_confidence(keywords_hit)
    status = determine_status(confidence)
    seed_entry = {
        "id": f"SEED-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        "timestamp": timestamp,
        "stream_url": stream_url,
        "keywords": keywords_hit,
        "text": text.strip(),
        "confidence": round(confidence, 2),
        "status": status,
        "source": "Live Stream",
        "tags": []
    }

    with open(LAST_CHIRP_PATH, "w", encoding="utf-8") as f:
        json.dump(seed_entry, f, indent=2)

    seed_log = []
    if os.path.exists(SEED_INDEX_PATH):
        with open(SEED_INDEX_PATH, "r", encoding="utf-8") as f:
            seed_log = json.load(f)
    seed_log.append(seed_entry)
    with open(SEED_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(seed_log, f, indent=2)

    print("\n📦 Stream Ear Summary")
    print("─────────────────────────────")
    print(f"🕒 Timestamp: {timestamp}")
    print(f"📄 Transcript Length: {len(text)} characters")
    print(f"🎯 Confidence: {confidence:.2f} → {status.upper()}")
    print(f"📁 Reports Saved To: {REPORTS_DIR}")

# ─── LOOP ──────────────────────────────────────────────────────────────────────
def bowr_loop():
    token_tally = 0
    for stream_url in STREAM_URLS:
        while True:
            try:
                print(f"\n🔄 Listening for {RECORD_SECONDS} seconds...")
                show_live_timer(RECORD_SECONDS)
                success = record_stream(stream_url, OUTPUT_WAV, duration=RECORD_SECONDS)
                if not success:
                    break
                show_progress_bar("Transcribing", duration=3)
                text = transcribe_audio(OUTPUT_WAV)
                token_count = estimate_token_usage(text)
                token_tally += token_count
                if token_tally > TOKEN_CAP:
                    print(f"🛑 Token cap reached ({token_tally}). Ending session.")
                    return
                print(f"🔢 Estimated token usage: ~{token_count} tokens (total: {token_tally})")
                log_transcription_with_keywords(text, stream_url)
                
                # Update dashboard status file
                with open(os.path.join(BASE_DIR, "static", "status.json"), "w", encoding="utf-8") as f:
                    json.dump({
                        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_stream": stream_url,
                        "last_result": "Chirp processed",
                        "last_keywords": keywords_hit
                    }, f, indent=2)                
                print("\n📋 Transcript Snippet:\n", text)
            except Exception as e:
                print("❌ Error during cycle:", e)
            print(f"\n⏳ Waiting {INTERVAL_MINUTES} minutes until next sample...\n")
            time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    bowr_loop()
