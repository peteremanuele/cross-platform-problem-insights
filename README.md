# Home Repair Trend Pipeline

Early-stage research pipeline for identifying emerging and seasonal home repair topics using lightweight public signals.

---

## Overview

Online communities often contain fragmented signals about real-world problems and recurring "how-to" questions.

This project explores whether lightweight cross-platform public signals can help provide additional context around discussions occurring within DIY and home improvement communities.

Examples of those signals include:

- **Reddit** → recurring questions and problem discussions
- **YouTube** → engagement with repair and tutorial content
- **Google Trends** → broader search interest and seasonality

The goal is to better understand when recurring Reddit discussions may reflect broader emerging, seasonal, or high-interest practical problems.

---

## What This Project Does

- Extracts recurring problem-oriented phrases (e.g., "how to fix X", "why is Y happening")
- Tracks discussion frequency and engagement patterns
- Uses external public trend signals to provide additional context around recurring Reddit discussions
- Identifies emerging or seasonal problem patterns
- Produces aggregated analytical insights rather than raw content feeds

---

## Example Output

```json
{
  "topic": "toilet running constantly",
  "reddit_signal": "increasing discussion frequency",
  "external_context": {
    "youtube": "higher engagement on recent repair tutorials",
    "google_trends": "seasonal increase in search interest"
  },
  "interpretation": "possible recurring seasonal maintenance issue"
}
```

---

## Design Principles

- Focus on aggregated analytical insights rather than raw content collection
- Minimize data retention and avoid storing unnecessary user-generated content
- Operate within public API policies and reasonable request limits
- Use external public trend signals only to provide additional context around recurring community discussions

---

## Project Status

Early-stage development.

Current prototype functionality includes:

- YouTube engagement and velocity scoring
- Google Trends growth analysis
- Cross-platform trend scoring workflows
- JSON-based analytical output generation

Planned future work includes limited Reddit integration focused on lightweight metadata analysis within selected DIY-related communities.

---

## Setup

### Requirements

```
google-api-python-client
requests
pandas
numpy
python-dotenv
```

Install with:

```bash
pip install -r requirements.txt
```

### Credentials

Create a `.env` file in the project root:

```
YOUTUBE_API_KEY=your_key_here
```

- YouTube Data API v3 key — obtain from [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
- Google Trends — no key required

**Never commit your `.env` file.** It is listed in `.gitignore`.

### Running

```bash
# Activate your environment
source venv/bin/activate        # macOS/Linux
.\Scripts\activate              # Windows

# Launch the notebook
jupyter notebook home_repair_trends.ipynb
```

---

## Data Sources

| Source | Access | What we collect |
|---|---|---|
| YouTube Data API v3 | API key (free tier) | Video metadata, view counts, publish dates |
| Google Trends | No key required | Relative search interest over time |
| Reddit | Pending approval | Lightweight discussion metadata |

---

## Notes

- YouTube API free tier allows 10,000 units/day. A full 10-topic run costs approximately 1,010 units.
- Google Trends requests are rate-limited. The pipeline enforces a configurable sleep between requests (default: 20 seconds).
- All output is aggregated and analytical. No raw user-generated content is stored.