"""
Run this file directly:  python diagnose.py
It will tell you exactly what is broken and why.
"""

import os, json, time, requests
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', 'PASTE_YOUR_KEY_HERE')

TEST_TOPIC = 'garage door not closing'

print("=" * 60)
print("DIAGNOSTIC REPORT")
print("=" * 60)

# ─────────────────────────────────────────────────────────────
# 1. YouTube: raw HTTP call (bypasses the SDK to see raw errors)
# ─────────────────────────────────────────────────────────────
print("\n[1] YOUTUBE API KEY CHECK")
print(f"    Key loaded: {YOUTUBE_API_KEY[:12]}..." if len(YOUTUBE_API_KEY) > 12 else f"    Key: {YOUTUBE_API_KEY}")

url = "https://www.googleapis.com/youtube/v3/search"
params = {
    "key": YOUTUBE_API_KEY,
    "q": TEST_TOPIC,
    "part": "id,snippet",
    "type": "video",
    "maxResults": 3,
}

try:
    resp = requests.get(url, params=params, timeout=10)
    print(f"    HTTP status: {resp.status_code}")
    data = resp.json()

    if resp.status_code == 200:
        items = data.get("items", [])
        print(f"    ✅ SUCCESS — {len(items)} videos returned")
        for item in items:
            print(f"       - {item['snippet']['title'][:60]}")
    else:
        # Print the full error so we know exactly what's wrong
        error = data.get("error", {})
        print(f"    ❌ FAILED")
        print(f"    Error code:    {error.get('code')}")
        print(f"    Error message: {error.get('message')}")
        print(f"    Error reason:  {error.get('errors', [{}])[0].get('reason')}")
        print()
        print("    COMMON FIXES:")
        if error.get('code') == 400:
            print("    → API key is malformed or empty. Re-copy from Google Cloud Console.")
        elif error.get('code') == 403:
            reason = error.get('errors', [{}])[0].get('reason', '')
            if 'keyInvalid' in reason:
                print("    → API key is invalid. Re-generate it in Cloud Console.")
            elif 'accessNotConfigured' in reason:
                print("    → YouTube Data API v3 is NOT enabled for this project.")
                print("      Go to: https://console.cloud.google.com/apis/library/youtube.googleapis.com")
            elif 'forbidden' in reason or 'ipRefererBlocked' in reason:
                print("    → Key has HTTP referrer or IP restrictions. Remove them for local dev.")
            else:
                print(f"    → 403 reason: {reason}")
        elif error.get('code') == 401:
            print("    → API key is not authorized. Check key restrictions.")

except Exception as e:
    print(f"    ❌ EXCEPTION: {e}")

# ─────────────────────────────────────────────────────────────
# 2. Google Trends: test with a real browser session
# ─────────────────────────────────────────────────────────────
print("\n[2] GOOGLE TRENDS CHECK")

try:
    from pytrends.request import TrendReq
    import pandas as pd

    # The key fix: pass a real browser User-Agent.
    # Plain pytrends gets blocked; this mimics an actual browser.
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })

    pytrends = TrendReq(
        hl='en-US',
        tz=360,
        timeout=(10, 30),
        retries=2,
        backoff_factor=1.0,
        requests_args={"headers": session.headers},
    )

    print(f"    Querying: '{TEST_TOPIC}' for last 3 months...")
    pytrends.build_payload([TEST_TOPIC], timeframe='today 3-m', geo='US')

    time.sleep(2)  # be polite
    df = pytrends.interest_over_time()

    if df.empty:
        print("    ❌ FAILED — empty DataFrame returned")
        print("    This usually means Google is blocking the request.")
        print()
        print("    FIXES TO TRY:")
        print("    A) Add a longer sleep: time.sleep(10) before build_payload")
        print("    B) Try without geo restriction: geo=''")
        print("    C) Try a very common keyword first (e.g. 'weather') to test")
        print("    D) If on a VPN, disconnect — Google blocks many VPN IPs")
    else:
        print(f"    ✅ SUCCESS — {len(df)} data points returned")
        print(f"    Columns: {list(df.columns)}")
        print(f"    Last 5 rows:")
        print(df.tail(5).to_string())

except ImportError:
    print("    ❌ pytrends not installed. Run: pip install pytrends")
except Exception as e:
    print(f"    ❌ EXCEPTION: {type(e).__name__}: {e}")

# ─────────────────────────────────────────────────────────────
# 3. Trends fallback test: try a simpler keyword
# ─────────────────────────────────────────────────────────────
print("\n[3] TRENDS FALLBACK — testing with 'weather' (should always work)")

try:
    from pytrends.request import TrendReq
    pt2 = TrendReq(hl='en-US', tz=360, timeout=(10, 30))
    pt2.build_payload(['weather'], timeframe='today 1-m', geo='US')
    time.sleep(2)
    df2 = pt2.interest_over_time()
    if df2.empty:
        print("    ❌ Even 'weather' returned empty — network/IP block likely")
        print("    Try running from a different network or disabling VPN")
    else:
        print(f"    ✅ 'weather' returned {len(df2)} rows — pytrends is working")
        print("    The issue is likely the specific keywords being blocked.")
        print("    Try shorter, simpler keywords (e.g. 'garage door' not 'garage door not closing')")

except Exception as e:
    print(f"    ❌ EXCEPTION: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("Run this output back to Claude for next steps.")
print("=" * 60)