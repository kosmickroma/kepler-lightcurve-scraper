# XENOSCAN Checkpoint: NASA-Style Pipeline Optimization

**Date:** 2026-01-18 ~4:30 PM
**Author:** Claude Opus 4.5
**Status:** 900-star validation run in progress (~37 hour marathon)
**Commit:** `3b54922` - feat: NASA-style pipeline optimization for consumer hardware

---

## Executive Summary

Today we transformed XENOSCAN from a pipeline that hung indefinitely on BLS computations to one that completes deep 100-day period searches on consumer hardware. The key insight: **optimize the math, not the science**.

Rather than reducing the period search range (which would miss habitable zone planets), we implemented NASA SOC-style preprocessing that makes the computation tractable on a 2-core laptop.

**Current state:** 900 quiet stars processing at ~4-5 min/star with 2 parallel workers. Expected completion: ~37 hours (Sunday evening).

---

## What Was Fixed Today

### Problem 1: BLS Taking 6+ Minutes Per Star (Hanging Indefinitely)

**Root cause discovered:** BLS computational complexity scales with baseline length, not just point count.

Testing revealed:
| Points | Baseline | Period Cap | Time |
|--------|----------|------------|------|
| 5,000 | 100 days | 50 days | 1.1 sec |
| 5,000 | 400 days | 50 days | 21.4 sec |
| 5,000 | 1,400 days | 50 days | >60 sec (timeout) |

A typical Kepler target has 65,264 points spanning 1,470 days. Even with period caps, this baseline length was causing BLS to crawl.

### Solution: NASA SOC-Style Preprocessing

**File:** `preprocessing/features/transit.py`

#### Optimization 1: Median Filter Flattening
```python
FLATTEN_WINDOW = 401  # ~8 days at 30-min cadence

flux_trend = median_filter(flux, size=FLATTEN_WINDOW)
flux_flat = flux / flux_trend
```
- Removes stellar variability (rotation, starspots)
- Irons out quarter boundary jumps
- Preserves transit dips (hours, not days)

#### Optimization 2: 4-Hour Time Binning
```python
BIN_SIZE_HOURS = 4.0

from scipy.stats import binned_statistic
flux_binned, _, _ = binned_statistic(time, flux_flat, statistic='mean', bins=bin_edges)
```
- Reduces 65,264 → 8,146 points (87% reduction)
- Transit dips preserved (they last hours)
- Signal-to-noise actually improves (noise cancels)

#### Optimization 3: Segmented BLS for Long Baselines
```python
MAX_SEGMENT_DAYS = 350.0

if baseline_days > MAX_SEGMENT_DAYS * 1.5:
    n_segments = int(np.ceil(baseline_days / MAX_SEGMENT_DAYS))
    for seg_idx in range(n_segments):
        # Run BLS on each segment, take best result
```
- Splits 1,470-day baseline into 5 segments of ~350 days
- Each segment completes in ~55 seconds
- Total: ~4-5 minutes per star (vs indefinite hang)

#### Optimization 4: 100-Day Period Cap (Scientific Requirement)
```python
MAX_PERIOD_DAYS = 100.0
```
- Catches habitable zone planets around M-dwarfs (10-50 day periods)
- Catches all hot/warm planets around any star
- User-approved tradeoff: Cannot detect Earth analogs (365-day period)

---

### Problem 2: Memory Bloat Over Long Runs

**Root cause:** Python doesn't aggressively release memory after large computations.

**Solution:** Explicit garbage collection after each star.

**File:** `scripts/local_processor.py`
```python
import gc

# After each star is processed:
gc.collect()
```

Also configured `max_tasks_per_child=1` in ProcessPoolExecutor to recycle workers.

---

### Problem 3: Timeout Status Not Tracked

**Solution:** Added `processing_status` field to track completion state.

**File:** `scripts/local_processor.py`
```python
bls_timed_out = features.pop('_bls_timed_out', False)
lz_timed_out = features.pop('_lz_timed_out', False)

if bls_timed_out and lz_timed_out:
    features['processing_status'] = 'bls_lz_timeout'
elif bls_timed_out:
    features['processing_status'] = 'bls_timeout'
elif lz_timed_out:
    features['processing_status'] = 'lz_timeout'
else:
    features['processing_status'] = 'success'
```

**Why this matters:** Timeouts are anomaly signals, not failures. ML can learn from them.

---

### Problem 4: Lempel-Ziv Still Disabled

**Previous state:** Lempel-Ziv was disabled because ThreadPoolExecutor timeout doesn't work inside ProcessPoolExecutor.

**Solution:** Re-enabled with signal.SIGALRM timeout (works in subprocess main thread).

**File:** `preprocessing/features/residual.py`
```python
LEMPEL_ZIV_TIMEOUT_SEC = 10

old_handler = signal.signal(signal.SIGALRM, _lempel_ziv_timeout_handler)
signal.alarm(timeout_sec)
try:
    result = _lempel_ziv_core(input_signal, bins)
    signal.alarm(0)
    return result
except LempelZivTimeout:
    return -1.0  # Special value indicating timeout
finally:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old_handler)
```

Returns -1.0 on timeout, which gets translated to `_lz_timed_out = True`.

---

## Database State

**Supabase:** https://dumfpzgybgjapxgpdkil.supabase.co

**Schema addition required before run:**
```sql
ALTER TABLE features ADD COLUMN IF NOT EXISTS processing_status TEXT;
```
(User added this manually)

**Current contents (as of run start):**
- targets: 0 rows → accumulating
- features: 0 rows → accumulating

---

## Files Modified

| File | Changes |
|------|---------|
| `preprocessing/features/transit.py` | Flattening, binning, segmentation, 100d cap |
| `preprocessing/features/residual.py` | Signal-based LZ timeout, return -1.0 on timeout |
| `scripts/local_processor.py` | gc.collect(), processing_status tracking |
| `scripts/add_scientific_validation_columns.sql` | Added processing_status column |
| `README.md` | New Section 11: NASA-Style Pipeline Optimization |
| `checkpoints/CHECKPOINT_2026-01-18_opus-handoff.md` | Previous checkpoint (kept) |

---

## Configuration Parameters

| Parameter | Value | Location |
|-----------|-------|----------|
| FLATTEN_WINDOW | 401 points (~8 days) | transit.py |
| BIN_SIZE_HOURS | 4.0 | transit.py |
| MAX_SEGMENT_DAYS | 350.0 | transit.py |
| MAX_PERIOD_DAYS | 100.0 | transit.py |
| frequency_factor | 10.0 | transit.py |
| LEMPEL_ZIV_TIMEOUT_SEC | 10 | residual.py |
| max_workers | 2 | local_processor.py (via run_validation_local.py) |
| max_tasks_per_child | 1 | local_processor.py |

---

## Expected Validation Results

| Metric | Expected |
|--------|----------|
| Processing rate | ~4-5 min/star |
| Total time (900 stars, 2 workers) | ~37 hours |
| Valid features per quiet star | 48/64 (transit derived features NULL by design) |
| Transit features | Low power (noise floor), transit_significant=0 |
| Processing status | Mostly "success", some "lz_timeout" expected |

---

## Run Progress (Started 2026-01-18 16:01)

First stars completed successfully:
```
KIC 001296779: Extracted 48/64 valid features (status: success)
KIC 001435467: Extracted 48/64 valid features (status: success)
```

Database uploads working:
```
HTTP Request: POST .../features "HTTP/2 201 Created"
```

---

## Hardware Profile

**User's machine:**
- CPU: Intel i3-1115G4 (2 physical cores, 4 threads)
- RAM: ~4GB available
- Storage: WSL2 on Windows
- Workers: 2 (1 per physical core)

**Why 2 workers:** Hyperthreading doesn't help CPU-bound BLS math. 3 workers on 2 cores = fighting for hardware = potential crashes.

---

## Next Steps After This Run

1. **Monitor progress** - Check Supabase periodically for accumulating rows
2. **Generate planet host URLs** - Run MAST lookup for 100 Teff-stratified hosts
3. **Process planet hosts** - Expect higher transit_bls_power values
4. **Compare distributions** - Quiet vs planet host feature analysis
5. **Train ML models** - XGBoost (supervised) + Isolation Forest (unsupervised)

---

## Key Commands

```bash
# Check run progress (in another terminal)
source venv/bin/activate
python -c "
from preprocessing.database import XenoscanDatabase
db = XenoscanDatabase()
result = db.client.table('features').select('*', count='exact').execute()
print(f'Features processed: {result.count}')
"

# If run crashes, can resume (skips completed targets)
python scripts/run_validation_local.py

# Reset and start fresh
python scripts/reset_validation.py
```

---

## Commit Reference

```
commit 3b54922a4fe5d63d822e86d7687315e98d290b90
Author: K.K. <kosmickroma@gmail.com>
Date:   Sun Jan 18 16:28:18 2026 -0500

    feat: NASA-style pipeline optimization for consumer hardware
```

6 files changed, 915 insertions(+), 100 deletions(-)

---

*Checkpoint created by Claude Opus 4.5 on 2026-01-18*
