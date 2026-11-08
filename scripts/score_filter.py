"""Exclude games whose displayed user score is at or below 40% of its scale (<= 4/10, <= 2/5).

The score is resolved exactly as the website resolves it (website/app.js `ratingFor`):
the fresher of the enrichment and legacy composite ratings, else the legacy single-source rating.
Games without a user score are kept.
"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MAX_EXCLUDED_RATIO = 0.4

def _games(root, name):
    path = Path(root)/'data'/name
    try: return json.loads(path.read_text(encoding='utf-8')).get('games', {})
    except (OSError, ValueError): return {}

def load_sources(root=ROOT):
    return {'enrichment': _games(root, 'enrichment-public.json'), 'composites': _games(root, 'composites.json'), 'ratings': _games(root, 'ratings.json')}

def user_ratio(key, sources):
    """User score as a fraction of its scale, or None when the game has no user score."""
    full = sources['composites'].get(key)
    fresh = (sources['enrichment'].get(key) or {}).get('ratings')
    composite = fresh if fresh and (not full or str(fresh.get('attempted') or '') >= str(full.get('attempted') or '')) else full
    user = (composite or sources['ratings'].get(key) or {}).get('user')
    if not isinstance(user, dict): return None
    score, scale = user.get('score'), user.get('scale')
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not isinstance(scale, (int, float)) or scale <= 0: return None
    return score / scale

def is_low_rated(key, sources):
    ratio = user_ratio(key, sources)
    return ratio is not None and ratio <= MAX_EXCLUDED_RATIO + 1e-9

def low_rated_keys(games, sources=None):
    sources = sources or load_sources()
    keys = (f"{g.get('platform')}:{g.get('id')}" for g in games)
    return {key for key in keys if is_low_rated(key, sources)}
