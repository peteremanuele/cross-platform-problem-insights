"""
Drop-in replacements for the notebook.
Copy each section into the corresponding cell.
"""

# ── CELL 2 addition: bump trends sleep ───────────────────────────────────────
# Change this line in Cell 2:
TRENDS_SLEEP = 15   # was 8 — gives Google more breathing room


# ── CELL 4: replace compute_youtube_velocity only ────────────────────────────
# The problem: top-viewed home repair videos are years old, so "recent"
# bucket is always empty → ratio = 0.
#
# New approach — two sub-signals averaged together:
#
#   1. RECENCY WEIGHT: among the top-N videos, what fraction were uploaded
#      in the last 12 months? If creators are actively uploading to this
#      topic, it's growing.
#
#   2. VIEWS-PER-DAY DISTRIBUTION: newer videos (< 12 months) that are
#      already in the top results must be accumulating views fast.
#      We compare their vpd against the full-set median.
#
# Together these capture: "is this topic attracting new content AND
# is that new content performing well relative to old content?"

from datetime import datetime, timedelta, timezone

def compute_youtube_velocity(videos, active_window_days=365):
    """
    Returns a 0-1 velocity score based on:
      - Recency fraction: % of top videos published within active_window_days
      - VPD ratio: new videos' views-per-day vs median views-per-day of all videos

    Interpretation:
      0.7+  topic is actively growing
      0.5   mixed — some new content, some evergreen
      0.3-  dominated by old evergreen content, low current momentum
    """
    if not videos:
        return 0.0

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=active_window_days)

    all_vpd, recent_vpd = [], []

    for v in videos:
        if v['published_at'] is None:
            continue
        age_days = max((now - v['published_at']).days, 1)
        vpd = v['view_count'] / age_days
        all_vpd.append(vpd)
        if v['published_at'] >= cutoff:
            recent_vpd.append(vpd)

    if not all_vpd:
        return 0.0

    # Signal 1: what fraction of top results are recent?
    recency_fraction = len(recent_vpd) / len(all_vpd)

    # Signal 2: how do recent videos perform vs the field?
    # If no recent videos at all, this signal is 0.
    if recent_vpd:
        median_all    = sorted(all_vpd)[len(all_vpd) // 2]
        avg_recent_vpd = sum(recent_vpd) / len(recent_vpd)
        vpd_ratio = avg_recent_vpd / (median_all + 1)
        # Normalize: ratio of 1 (equal to median) → 0.5, ratio of 3 → 0.75
        vpd_signal = vpd_ratio / (vpd_ratio + 1)
    else:
        vpd_signal = 0.0

    # Weighted average: recency matters more than raw VPD
    velocity = (recency_fraction * 0.6) + (vpd_signal * 0.4)

    # Debug line — remove once you're happy with scores
    print(f'         [yt debug] recency={recency_fraction:.2f} ({len(recent_vpd)}/{len(all_vpd)} recent)  vpd_signal={vpd_signal:.2f}')

    return round(min(velocity, 1.0), 4)


# ── QUICK TEST (run this standalone to verify before full pipeline) ───────────
if __name__ == '__main__':
    # Simulate what the API returns for a healthy topic
    now = datetime.now(timezone.utc)

    mock_videos = [
        # Old evergreen videos with lots of views
        {'published_at': now - timedelta(days=1200), 'view_count': 2_000_000, 'title': 'old hit 1'},
        {'published_at': now - timedelta(days=900),  'view_count': 800_000,  'title': 'old hit 2'},
        {'published_at': now - timedelta(days=700),  'view_count': 500_000,  'title': 'old hit 3'},
        # Newer videos gaining traction — this is the signal we want
        {'published_at': now - timedelta(days=180),  'view_count': 120_000,  'title': 'new rising 1'},
        {'published_at': now - timedelta(days=90),   'view_count': 80_000,   'title': 'new rising 2'},
        {'published_at': now - timedelta(days=45),   'view_count': 40_000,   'title': 'new rising 3'},
        {'published_at': now - timedelta(days=20),   'view_count': 15_000,   'title': 'very new'},
    ]

    score = compute_youtube_velocity(mock_videos)
    print(f'\nMock score (mixed old/new): {score}')
    print('Expected: roughly 0.45-0.65\n')

    # All-old scenario
    old_only = [
        {'published_at': now - timedelta(days=1500), 'view_count': 3_000_000, 'title': 'ancient'},
        {'published_at': now - timedelta(days=1200), 'view_count': 1_000_000, 'title': 'old'},
        {'published_at': now - timedelta(days=900),  'view_count': 500_000,   'title': 'older'},
    ]
    score2 = compute_youtube_velocity(old_only)
    print(f'All-old score: {score2}')
    print('Expected: 0.0\n')

    # All-new scenario
    new_only = [
        {'published_at': now - timedelta(days=30),  'view_count': 50_000, 'title': 'new 1'},
        {'published_at': now - timedelta(days=60),  'view_count': 40_000, 'title': 'new 2'},
        {'published_at': now - timedelta(days=90),  'view_count': 30_000, 'title': 'new 3'},
    ]
    score3 = compute_youtube_velocity(new_only)
    print(f'All-new score: {score3}')
    print('Expected: 0.5-0.7')