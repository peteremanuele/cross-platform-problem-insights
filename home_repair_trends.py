"""
home_repair_trends.py
---------------------
Scores a list of home-repair topics using YouTube velocity and Google Trends growth.

Usage:
    python home_repair_trends.py                          # uses topics_input.json
    python home_repair_trends.py my_topics.json           # custom input file
    python home_repair_trends.py topics_input.json --out results.json

Input JSON schema (all keys except "topics" are optional overrides):
    {
      "topics": ["garage door not closing", ...],

      "weight_youtube":        0.55,
      "weight_trends":         0.45,
      "yt_results_per_topic":  10,
      "yt_active_window_days": 365,
      "trends_sleep":          20,
      "trends_timeframe":      "today 3-m",
      "trends_geo":            "US"
    }
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Defaults — override any of these via the input JSON file
# ---------------------------------------------------------------------------

DEFAULT_WEIGHT_YOUTUBE        = 0.55
DEFAULT_WEIGHT_TRENDS         = 0.45
DEFAULT_YT_RESULTS_PER_TOPIC  = 10
DEFAULT_YT_ACTIVE_WINDOW_DAYS = 365
DEFAULT_TRENDS_SLEEP          = 20      # seconds between Trends requests
DEFAULT_TRENDS_TIMEFRAME      = "today 3-m"
DEFAULT_TRENDS_GEO            = "US"

DEFAULT_INPUT_FILE  = "topics_input.json"
DEFAULT_OUTPUT_FILE = "trend_results.json"

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(input_path: str) -> dict:
    """Load topics_input.json and merge with defaults."""
    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    if not raw.get("topics"):
        raise ValueError(f"Input file '{input_path}' must contain a non-empty 'topics' list.")

    cfg = {
        "topics":               raw["topics"],
        "weight_youtube":       raw.get("weight_youtube",        DEFAULT_WEIGHT_YOUTUBE),
        "weight_trends":        raw.get("weight_trends",         DEFAULT_WEIGHT_TRENDS),
        "yt_results_per_topic": raw.get("yt_results_per_topic",  DEFAULT_YT_RESULTS_PER_TOPIC),
        "yt_active_window_days":raw.get("yt_active_window_days", DEFAULT_YT_ACTIVE_WINDOW_DAYS),
        "trends_sleep":         raw.get("trends_sleep",          DEFAULT_TRENDS_SLEEP),
        "trends_timeframe":     raw.get("trends_timeframe",      DEFAULT_TRENDS_TIMEFRAME),
        "trends_geo":           raw.get("trends_geo",            DEFAULT_TRENDS_GEO),
    }
    return cfg

# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def build_youtube_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key)


def _search_video_ids(client, query: str, max_results: int, order: str,
                      published_after: str = None) -> list:
    req_kwargs = {
        "q": query,
        "part": "id,snippet",
        "type": "video",
        "maxResults": max_results,
        "order": order,
        "relevanceLanguage": "en",
    }
    if published_after:
        req_kwargs["publishedAfter"] = published_after

    resp = client.search().list(**req_kwargs).execute()
    return [
        item["id"]["videoId"]
        for item in resp.get("items", [])
        if item.get("id", {}).get("videoId")
    ]


def fetch_youtube_videos(client, query: str, max_results: int = 10,
                         active_window_days: int = 365) -> list:
    """
    Fetch two slices and merge:
      1) Relevance-ranked results  (demand signal)
      2) Date-ranked recent uploads (momentum signal)
    """
    try:
        now_utc = datetime.now(timezone.utc)
        published_after = (
            (now_utc - timedelta(days=active_window_days))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        ids_relevance = _search_video_ids(
            client, query, max_results=max_results, order="relevance"
        )
        ids_recent = _search_video_ids(
            client, query, max_results=max_results,
            order="date", published_after=published_after,
        )

        merged_ids: list = []
        for vid in ids_recent + ids_relevance:
            if vid not in merged_ids:
                merged_ids.append(vid)
        video_ids = merged_ids[: max_results * 2]

        if not video_ids:
            return []

        stats_resp = client.videos().list(
            id=",".join(video_ids),
            part="statistics,snippet",
        ).execute()

        videos = []
        for item in stats_resp.get("items", []):
            published_raw = item.get("snippet", {}).get("publishedAt", "")
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

            videos.append({
                "video_id":     item.get("id", ""),
                "title":        item.get("snippet", {}).get("title", ""),
                "published_at": published_at,
                "view_count":   int(item.get("statistics", {}).get("viewCount", 0)),
                "channel":      item.get("snippet", {}).get("channelTitle", ""),
            })

        return videos

    except Exception as e:
        print(f"  YouTube error: {e}")
        return []


def compute_youtube_velocity(videos: list, active_window_days: int = 365) -> float:
    """
    0-1 velocity score: recency fraction × VPD performance.
    Falls back to a small floor when no videos fall inside the active window.
    """
    if not videos:
        return 0.0

    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=active_window_days)

    all_vpd, recent_vpd, valid_ages = [], [], []

    for v in videos:
        pub = v.get("published_at")
        if pub is None:
            continue
        age_days = max((now - pub).days, 1)
        valid_ages.append(age_days)
        vpd = v.get("view_count", 0) / age_days
        all_vpd.append(vpd)
        if pub >= cutoff:
            recent_vpd.append(vpd)

    if not all_vpd:
        return 0.0

    recency_fraction = len(recent_vpd) / len(all_vpd)

    if recent_vpd:
        median_all    = sorted(all_vpd)[len(all_vpd) // 2]
        median_recent = sorted(recent_vpd)[len(recent_vpd) // 2]
        vpd_ratio  = median_recent / (median_all + 1)
        vpd_signal = vpd_ratio / (vpd_ratio + 1)
    else:
        newest_age = min(valid_ages) if valid_ages else active_window_days * 5
        freshness  = active_window_days / (active_window_days + newest_age)
        vpd_signal = max(0.15, min(freshness, 0.35))

    velocity = (recency_fraction * 0.65) + (vpd_signal * 0.35)
    print(
        f"         [yt debug] recency={recency_fraction:.2f} "
        f"({len(recent_vpd)}/{len(all_vpd)} recent)  vpd_signal={vpd_signal:.2f}"
    )
    return round(min(velocity, 1.0), 4)

# ---------------------------------------------------------------------------
# Google Trends helpers
# ---------------------------------------------------------------------------

def _make_trends_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://trends.google.com/",
    })
    return session


def _strip_xssi(text: str) -> str:
    """Google Trends prepends a protective ')]}' line — strip it."""
    return text.split("\n", 1)[1] if "\n" in text else text


def _get_with_backoff(session: requests.Session, url: str, params: dict,
                      label: str, attempts: int = 5, base_wait: float = 8.0):
    """GET with exponential backoff + jitter on 429 / 5xx."""
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, params=params, timeout=20)
        except Exception as e:
            if attempt == attempts:
                raise RuntimeError(f"{label} request exception: {e}")
            wait_s = base_wait * (2 ** (attempt - 1)) + random.uniform(0, 2)
            print(f"  {label} network error (attempt {attempt}/{attempts}); waiting {wait_s:.1f}s...")
            time.sleep(wait_s)
            continue

        if resp.status_code == 200:
            return resp

        retriable = resp.status_code == 429 or 500 <= resp.status_code < 600
        if not retriable or attempt == attempts:
            return resp

        wait_s = base_wait * (2 ** (attempt - 1)) + random.uniform(0, 2)
        print(
            f"  {label} HTTP {resp.status_code} (attempt {attempt}/{attempts}); "
            f"waiting {wait_s:.1f}s..."
        )
        time.sleep(wait_s)

    return None


def fetch_trends_data(session: requests.Session, keyword: str,
                      timeframe: str = "today 3-m", geo: str = "US") -> list:
    """
    Returns list of (date_str, value) tuples, or [] on failure.
    Step 1: explore endpoint → one-time token.
    Step 2: multiline endpoint → time-series values.
    """
    explore_url = "https://trends.google.com/trends/api/explore"
    payload = {
        "hl": "en-US",
        "tz": "360",
        "req": json.dumps({
            "comparisonItem": [{"keyword": keyword, "geo": geo, "time": timeframe}],
            "category": 0,
            "property": "",
        }),
    }

    try:
        resp = _get_with_backoff(session, explore_url, payload, label="Trends explore")
        if resp is None or resp.status_code != 200:
            status = "no response" if resp is None else f"HTTP {resp.status_code}"
            print(f"  Trends explore failed: {status}")
            return []

        data    = json.loads(_strip_xssi(resp.text))
        token   = None
        req_obj = None
        for w in data.get("widgets", []):
            if w.get("id") == "TIMESERIES":
                token   = w.get("token")
                req_obj = w.get("request")
                break

        if not token or not req_obj:
            print("  No TIMESERIES widget found in response")
            return []

    except Exception as e:
        print(f"  Trends explore error: {e}")
        return []

    time.sleep(1)
    multiline_url = "https://trends.google.com/trends/api/widgetdata/multiline"
    multiline_params = {
        "hl": "en-US",
        "tz": "360",
        "req": json.dumps(req_obj),
        "token": token,
        "user_type": "USER_TYPE_SCRAPER",
    }

    try:
        resp2 = _get_with_backoff(session, multiline_url, multiline_params, label="Trends multiline")
        if resp2 is None or resp2.status_code != 200:
            status = "no response" if resp2 is None else f"HTTP {resp2.status_code}"
            print(f"  Trends multiline failed: {status}")
            return []

        data2  = json.loads(_strip_xssi(resp2.text))
        points = []
        for row in data2.get("default", {}).get("timelineData", []):
            date_str = row.get("formattedAxisTime", row.get("formattedTime", ""))
            value    = row.get("value", [0])[0]
            points.append((date_str, value))

        return points

    except Exception as e:
        print(f"  Trends multiline error: {e}")
        return []


def compute_trends_growth(session: requests.Session, keyword: str,
                          timeframe: str = "today 3-m", geo: str = "US") -> float:
    """Compare last third vs first two-thirds of the time window. Returns 0-1."""
    points = fetch_trends_data(session, keyword, timeframe=timeframe, geo=geo)

    if len(points) < 8:
        print(f"  Not enough data points: {len(points)}")
        return 0.0

    values       = np.array([p[1] for p in points], dtype=float)
    split        = len(values) * 2 // 3
    baseline_avg = np.mean(values[:split]) + 0.01
    recent_avg   = np.mean(values[split:])
    ratio        = recent_avg / baseline_avg
    return round(min(ratio / (ratio + 1), 1.0), 4)

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(cfg: dict, api_key: str, output_path: str):
    topics     = cfg["topics"]
    n          = len(topics)
    yt_client  = build_youtube_client(api_key)

    trends_session = _make_trends_session()
    print("Warming up Google Trends session...")
    warmup = trends_session.get("https://trends.google.com/", timeout=15)
    print(f"Warm-up status: {warmup.status_code}")
    time.sleep(2)

    results = []
    for i, topic in enumerate(topics):
        print(f"\n[{i+1}/{n}] \"{topic}\"")

        yt_videos   = fetch_youtube_videos(
            yt_client, topic,
            max_results=cfg["yt_results_per_topic"],
            active_window_days=cfg["yt_active_window_days"],
        )
        yt_velocity = compute_youtube_velocity(
            yt_videos, active_window_days=cfg["yt_active_window_days"]
        )
        print(f"       YT velocity:    {yt_velocity:.3f}  ({len(yt_videos)} videos)")

        time.sleep(cfg["trends_sleep"])
        trends_growth = compute_trends_growth(
            trends_session, topic,
            timeframe=cfg["trends_timeframe"],
            geo=cfg["trends_geo"],
        )
        print(f"       Trends growth:  {trends_growth:.3f}")

        score = round(
            yt_velocity * cfg["weight_youtube"] +
            trends_growth * cfg["weight_trends"],
            4
        )
        print(f"       Score:          {score:.3f}")

        results.append({
            "topic":            topic,
            "youtube_velocity": yt_velocity,
            "trends_growth":    trends_growth,
            "score":            score,
            "yt_videos":        len(yt_videos),
        })

    df = (
        pd.DataFrame(results)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )

    print("\n=== TREND SCORES ===")
    print(df[["topic", "youtube_velocity", "trends_growth", "score"]].to_string())

    output = {
        "meta": {
            "run_at":               datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topic_count":          len(results),
            "weight_youtube":       cfg["weight_youtube"],
            "weight_trends":        cfg["weight_trends"],
            "trends_sleep_s":       cfg["trends_sleep"],
            "trends_timeframe":     cfg["trends_timeframe"],
            "trends_geo":           cfg["trends_geo"],
            "yt_window_days":       cfg["yt_active_window_days"],
            "yt_results_per_topic": cfg["yt_results_per_topic"],
        },
        "results": df[["topic", "youtube_velocity", "trends_growth", "score"]].to_dict(orient="records"),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved: {output_path}")
    return output

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Home repair trend scorer")
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT_FILE,
        help=f"Path to input JSON file (default: {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Path to output JSON file (default: {DEFAULT_OUTPUT_FILE})",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        print("⚠️  YOUTUBE_API_KEY not set. Set it in .env or as an environment variable.")
        sys.exit(1)

    print(f"✅ YouTube API key loaded: {api_key[:12]}...")
    print(f"Input : {args.input}")
    print(f"Output: {args.out}")

    cfg = load_config(args.input)
    print(f"Topics : {len(cfg['topics'])}")
    print(f"Weights: YT={cfg['weight_youtube']}  Trends={cfg['weight_trends']}")
    print(f"Trends sleep: {cfg['trends_sleep']}s | timeframe: {cfg['trends_timeframe']} | geo: {cfg['trends_geo']}")

    output = run_pipeline(cfg, api_key, args.out)
    print("\nTop results:")
    print(json.dumps(output["results"][:3], indent=2))


if __name__ == "__main__":
    main()
