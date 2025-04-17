import os
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
NEWS_API_KEY = os.getenv("NEWS_API")
SEED_INDEX_PATH = os.path.join("static", "seed_index.json")
TRUSTED_SOURCES = ["bloomberg", "reuters", "wsj", "cnbc", "marketwatch"]

# ─── FETCH NEWS ───────────────────────────────────────────────────────────────
def get_news_for_keyword(keyword):
    url = f"https://newsapi.org/v2/everything?q={keyword}&language=en&sortBy=publishedAt&apiKey={NEWS_API_KEY}"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"[!] News API error: {response.status_code}")
        return []
    news_data = response.json()
    return news_data.get("articles", [])

# ─── SCORE BOOST ──────────────────────────────────────────────────────────────
def score_news_boost(articles):
    if not articles:
        return 0

    count = len(articles)
    trusted_hits = sum(1 for a in articles if any(t in a["source"]["name"].lower() for t in TRUSTED_SOURCES))

    boost = 0.1 * min(count, 5)  # basic count bonus
    if trusted_hits >= 2:
        boost += 0.2

    return min(boost, 0.5)

# ─── PROMOTE/DEMOTE LOGIC ─────────────────────────────────────────────────────
def evaluate_seed(seed):
    base = seed.get("confidence", 0.2)
    keywords = seed.get("keywords", [])
    total_boost = 0

    for kw in keywords:
        articles = get_news_for_keyword(kw)
        boost = score_news_boost(articles)
        total_boost += boost
        time.sleep(1)  # avoid rate limit

    updated_confidence = min(base + total_boost, 1.0)

    # Determine new status
    if updated_confidence >= 0.8:
        status = "blooming"
    elif updated_confidence >= 0.6:
        status = "sprouting"
    elif updated_confidence < 0.3:
        age = datetime.now() - datetime.strptime(seed["timestamp"], "%Y-%m-%d %H:%M:%S")
        status = "discarded" if age > timedelta(hours=24) else seed["status"]
    else:
        status = seed["status"]

    seed["confidence"] = round(updated_confidence, 2)
    seed["status"] = status
    return seed

# ─── GERMINATE INDEX ──────────────────────────────────────────────────────────
def germinate():
    if not os.path.exists(SEED_INDEX_PATH):
        print("[!] No seed index found.")
        return

    with open(SEED_INDEX_PATH, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    updated = []
    for seed in seeds:
        if seed["status"] in ["planted", "sprouting"]:
            print(f"🌱 Evaluating seed: {seed['id']}")
            updated.append(evaluate_seed(seed))
        else:
            updated.append(seed)

    with open(SEED_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)

    print("✅ Germination complete.")

if __name__ == "__main__":
    germinate()
