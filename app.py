from flask import Flask, render_template, request, redirect, url_for, jsonify
import json
import os
from datetime import datetime
import subprocess
from collections import Counter


app = Flask(__name__)

# Load settings.json
SETTINGS_PATH = "settings.json"
with open(SETTINGS_PATH, "r") as f:
    CONFIG = json.load(f)

STREAM_URLS = CONFIG["modules"]["stream_ear_bowr"].get("STREAM_URLS", [])
REPORTS_DIR = os.path.join(CONFIG["BASE_DIR"], CONFIG["REPORT_SUBDIR"])
SEED_INDEX_PATH = os.path.join(CONFIG["BASE_DIR"], "static", "seed_index.json")

# In-memory status tracker
status = {
    "last_run": None,
    "last_stream": None,
    "last_result": None,
    "last_keywords": []
}

@app.route("/chirp")
def chirp():
    try:
        with open("static/last_chirp.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/")
def index():
    try:
        with open(os.path.join(CONFIG["BASE_DIR"], "static", "status.json")) as f:
            latest_status = json.load(f)
            status.update(latest_status)
    except:
        pass

    # Ensure keywords always reflect current config if not explicitly set
    if not status.get("last_keywords"):
        with open(SETTINGS_PATH, "r") as f:
            cfg = json.load(f)
            status["last_keywords"] = cfg["modules"]["stream_ear_bowr"].get("KEYWORDS", [])

    return render_template("dashboard.html", stream_urls=STREAM_URLS, status=status)



@app.route("/trigger", methods=["POST"])
def trigger_listen():
    stream_url = request.form.get("stream_url")
    print(f"[Cockpit] Listening triggered for: {stream_url}")

    # Update config with selected stream URL
    CONFIG["modules"]["stream_ear_bowr"]["STREAM_URLS"] = [stream_url]
    with open(SETTINGS_PATH, "w") as f:
        json.dump(CONFIG, f, indent=2)

    try:
        subprocess.Popen(["python", "stream_ear_bowrv2.py"])
        status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status["last_stream"] = stream_url
        status["last_result"] = "Triggered via UI"
        return redirect(url_for("index"))
    except Exception as e:
        print(f"Trigger error: {e}")
        return "Error launching listener", 500

@app.route("/seeds")
def view_seeds():
    status_filter = request.args.get("status")  # from dropdown
    seeds = []

    if os.path.exists(SEED_INDEX_PATH):
        with open(SEED_INDEX_PATH, "r", encoding="utf-8") as f:
            raw_seeds = json.load(f)

        # 🔽 Normalize all statuses first
        for s in raw_seeds:
            status = s.get("status", "unknown").lower()
            s["status"] = status  # update the record itself

        # 🧮 Count statuses
        status_counts = Counter(s["status"] for s in raw_seeds)
        status_counts["all"] = len(raw_seeds)
        print("🧪 Statuses found:", set(status_counts.keys()))

        # 🔍 Filter seeds based on selected status
        unique = {}
        for s in raw_seeds:
            ts = s.get("timestamp")
            text_snippet = s.get("text", "")[:50]
            if ts:
                if not status_filter or s["status"] == status_filter:
                    key = (ts, text_snippet)
                    unique[key] = s


        seeds = list(unique.values())

    return render_template("seeds.html", seeds=seeds, current_status=status_filter, status_counts=status_counts)




@app.route("/status")
def get_status():
    return jsonify(status)
    
@app.route("/add_keyword", methods=["POST"])
def add_keyword():
    new_kw = request.form.get("new_keyword", "").strip().lower()

    if not new_kw:
        return redirect(url_for("index"))

    with open(SETTINGS_PATH, "r") as f:
        config = json.load(f)

    keywords = config["modules"]["stream_ear_bowr"].get("KEYWORDS", [])
    if new_kw not in keywords:
        keywords.append(new_kw)
        config["modules"]["stream_ear_bowr"]["KEYWORDS"] = keywords
        with open(SETTINGS_PATH, "w") as f:
            json.dump(config, f, indent=2)
        print(f"[+] Keyword added to settings: {new_kw}")

    status["last_keywords"] = keywords
    return redirect(url_for("index"))
      

@app.route("/germinate")
def run_germinator():
    try:
        subprocess.run(["python", "germinator.py"], check=True)
        status["last_result"] = "Germinator executed"
    except Exception as e:
        status["last_result"] = f"Germinator error: {e}"
    return redirect(url_for("index"))    

if __name__ == "__main__":
    app.run(debug=True, port=5000)
