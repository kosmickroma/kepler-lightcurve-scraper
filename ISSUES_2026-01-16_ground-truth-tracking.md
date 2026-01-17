# Technical Issues: Ground Truth Tracking & Data Integrity
**Date:** 2026-01-16
**Status:** Identified during 486 quiet star validation run
**For Review By:** Claude Opus (scientific validation)

---

## Executive Summary

During validation of the hybrid pipeline, an astrophysicist consultant (Gemini) reviewed preliminary results and flagged **6 research-grade data integrity concerns**. These issues must be addressed before scaling to the full 1000-target validation set (900 quiet + 100 planet hosts) and eventual production run (~160K Kepler catalog).

**Critical Risk:** Without ground truth tracking, we cannot validate whether the Isolation Forest correctly identifies known planet hosts as anomalies. This breaks the entire scientific validation loop.

---

## Issue 1: No Ground Truth Labeling (CRITICAL)

### The Problem
The database has no way to track which targets are:
- **Quiet baseline stars** (expected to be "normal")
- **Known planet hosts** (expected to be flagged as anomalies)
- **Unknown/discovered anomalies** (AI findings)

### Current Code State
`scripts/local_processor.py` line 264:
```python
await self.database_client.insert_target(
    target_id=f"KIC {kic_id}",
    mission=mission,
    # ... other fields
)
```

No source tracking. All targets uploaded identically.

### Why This Matters
When Isolation Forest flags KIC 12345678 as an anomaly, we need to instantly check:
- Was it from `quiet_stars_900.txt`? → **New discovery**
- Was it from `known_planets_100.txt`? → **Correct detection (validation success)**

Without this, precision/recall metrics are impossible to calculate.

### Proposed Solution (For Opus to Review)
Add `is_salted` or `is_anomaly` boolean column to `targets` table:
- `FALSE` or `0`: Known quiet star (baseline)
- `TRUE` or `1`: Known anomaly (planet host, variable star, etc.)
- `NULL`: Unknown (not yet validated)

Modify upload logic to check source list and set flag accordingly.

### Questions for Opus
1. Should we track more granular categories (e.g., "quiet", "planet_host", "variable_star")?
2. What happens if a "quiet" star is later discovered to have a planet?
3. Should we version the ground truth labels?

---

## Issue 2: Target ID Standardization (HIGH PRIORITY)

### The Problem
KIC IDs can be represented multiple ways:
- `KIC 7510397` (raw)
- `KIC 007510397` (9-digit zero-padded)
- `7510397` (no prefix)

Current code is inconsistent:
- Line 49 of `local_processor.py`: Zero-pads to 9 digits for directory lookup
- Line 264: Uploads as `f"KIC {kic_id}"` without padding
- **Risk:** `KIC 7510397` and `KIC 007510397` treated as different stars → duplicates

### Current Code State
```python
# Lookup (correct):
kic_num = str(kic_id).zfill(9)  # → "007510397"

# Upload (inconsistent):
target_id=f"KIC {kic_id}"  # → "KIC 7510397" (NOT padded!)
```

### Why This Matters
Supabase will treat these as different rows:
- Target uploaded as `KIC 7510397`
- Re-run uploads as `KIC 007510397`
- Result: Duplicate rows, corrupted counts, broken FK relationships

### Proposed Solution
Enforce canonical format: `KIC 000000000` (space + 9-digit zero-padded)

Modify `local_processor.py` line 264:
```python
canonical_id = f"KIC {str(kic_id).zfill(9)}"
await self.database_client.insert_target(
    target_id=canonical_id,
    # ...
)
```

### Questions for Opus
1. Should we add a database constraint to enforce format?
2. Need a migration script to standardize existing rows?
3. Should we validate format on client side before upload?

---

## Issue 3: Feature Null Disambiguation (MEDIUM PRIORITY)

### The Problem
Features can be NULL for two reasons:
1. **Natural nulls** - Star has no signal (e.g., quiet star has no transits → `transit_bls_power` is NULL)
2. **Execution nulls** - Code crashed before feature extraction (→ all features NULL or partial)

Currently, we can't distinguish between these cases.

### Observed Data
Current run shows 37-38/63 features for quiet stars. This is likely **natural** because:
- Quiet stars have no transit signals → 10-15 transit features NULL
- Weak periodicity → 5-8 frequency features NULL
- Smooth lightcurves → 2-5 shape complexity features NULL

### Why This Matters
If a target has 20/63 features, we need to know:
- Is it an extremely quiet star? (natural)
- Did the feature extractor crash? (bug to fix)

Without this, we can't distinguish data quality issues from real astrophysical properties.

### Proposed Solution
Track `extraction_time_seconds` in database (already done at line 274 of `local_processor.py`).

**Red flag heuristic:**
- If `extraction_time_seconds < 5` AND `n_features_valid < 30` → likely a crash
- If `extraction_time_seconds > 30` AND `n_features_valid` 35-40 → likely natural (slow but complete)

### Questions for Opus
1. What's the expected feature count range for different star types?
   - Quiet stars: 35-40/63?
   - Planet hosts: 45-55/63?
   - Variable stars: 50-60/63?
2. Should we log which specific features are NULL to identify patterns?
3. Is there a minimum threshold below which we shouldn't upload? (Gemini suggested < 30)

---

## Issue 4: Cross-Contamination Risk (MEDIUM PRIORITY)

### The Problem
The "quiet stars" list may contain mislabeled variables:
- Eclipsing binaries with deep dips
- Flare stars with high variability
- Undetected planet hosts

If these are in the "quiet" baseline, they will:
- Inflate baseline variability
- Reduce anomaly detection sensitivity
- Create false negatives (real anomalies look "normal")

### Why This Matters
Isolation Forest learns "normal" from the training data. If the training data is contaminated, the model will think anomalies are normal.

Example: If 10% of "quiet" stars actually have deep transits, the model learns "deep transits are normal" → won't flag real planets.

### Proposed Solution
**Post-run IQR (Interquartile Range) filter:**

After the 899 quiet stars are processed, run:
```sql
SELECT target_id, stat_std, stat_skewness
FROM features
WHERE target_id IN (SELECT target_id FROM targets WHERE is_anomaly = FALSE)
  AND stat_std > (
    SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY stat_std) +
           1.5 * (PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY stat_std) -
                  PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY stat_std))
    FROM features
  )
ORDER BY stat_std DESC;
```

Flag outliers for manual review. If they're truly variable, relabel as `is_anomaly = TRUE`.

### Questions for Opus
1. What's the acceptable variability range for "quiet" Kepler stars?
2. Should we use multiple features for outlier detection (std + skewness + BLS power)?
3. How many outliers would indicate a bad source list?
4. Should we pull stellar parameters (Teff, radius, etc.) from MAST to validate?

---

## Issue 5: Failed Extraction Handling (LOW PRIORITY)

### The Problem
Currently, if feature extraction completely fails (features=None), the target is logged as failed but **not tracked in a persistent failure log**.

Re-running the script will re-attempt failed targets, potentially hitting the same error indefinitely.

### Current Code State
`local_processor.py` line 252-258:
```python
if features is None:
    return {
        'kic_id': kic_id,
        'success': False,
        'error': 'Feature extraction failed',
        'elapsed': time.time() - start_time
    }
```

Logged to console, but not persisted to file or database.

### Proposed Solution
Maintain `failed_targets.log`:
```
KIC 003831297,2026-01-16 09:54:23,Feature extraction failed,No valid flux points
KIC 012345678,2026-01-16 10:12:45,Database upload failed,Supabase timeout
```

Add `--skip-failed` flag to re-runs to avoid re-processing known failures.

### Questions for Opus
1. Should failed targets be logged to database instead of file?
2. What's the retry strategy for transient failures (network errors)?
3. Should we have a failure threshold to abort the run? (e.g., >10% failures = stop)

---

## Issue 6: Deduplication Strategy (LOW PRIORITY)

### The Problem
Multiple runs on overlapping target lists could create duplicates, especially with non-standardized IDs (see Issue 2).

### Current Code State
`database.py` line 121-124:
```python
response = self.client.table('targets').upsert(
    data,
    on_conflict='target_id'
).execute()
```

Upsert on `target_id` prevents duplicates **if IDs are standardized**. But if IDs vary, duplicates slip through.

### Proposed Solution
1. **Fix Issue 2 first** (standardize IDs)
2. Post-run deduplication query:
```sql
-- Find duplicates
SELECT
    LPAD(REGEXP_REPLACE(target_id, '[^0-9]', '', 'g'), 9, '0') as normalized_id,
    COUNT(*) as count
FROM targets
GROUP BY normalized_id
HAVING COUNT(*) > 1;

-- Keep row with most features
DELETE FROM targets
WHERE target_id IN (
    SELECT target_id FROM (
        SELECT target_id,
               ROW_NUMBER() OVER (
                   PARTITION BY LPAD(REGEXP_REPLACE(target_id, '[^0-9]', '', 'g'), 9, '0')
                   ORDER BY features_extracted DESC, features_extracted_at DESC
               ) as rn
        FROM targets
    ) t WHERE rn > 1
);
```

### Questions for Opus
1. Should we add a unique constraint on normalized KIC number?
2. How to handle legitimately different targets with similar IDs? (e.g., KIC vs EPIC)

---

## Data to Review (When Run Completes)

**Opus should receive:**
1. `validation_486_features.csv` - Full features table export
2. `validation_486_targets.csv` - Full targets table export
3. This issues file
4. `checkpoints/CHECKPOINT_2026-01-16_hybrid-pipeline.md` - Architecture context

**Validation queries to run:**
```sql
-- 1. Feature count distribution
SELECT
    n_features_valid,
    COUNT(*) as targets
FROM features
GROUP BY n_features_valid
ORDER BY n_features_valid;

-- 2. Extraction time vs feature count
SELECT
    target_id,
    extraction_time_seconds,
    n_features_valid
FROM features
WHERE extraction_time_seconds < 5 OR n_features_valid < 30
ORDER BY extraction_time_seconds;

-- 3. Statistical distributions
SELECT
    MIN(stat_mean) as min_mean,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY stat_mean) as q1_mean,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY stat_mean) as median_mean,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY stat_mean) as q3_mean,
    MAX(stat_mean) as max_mean,
    STDDEV(stat_mean) as std_mean
FROM features;

-- Repeat for stat_std, stat_skewness, etc.

-- 4. Potential outliers
SELECT target_id, stat_std, stat_skewness, transit_bls_power
FROM features
WHERE stat_std > (SELECT AVG(stat_std) + 3*STDDEV(stat_std) FROM features)
ORDER BY stat_std DESC
LIMIT 20;
```

---

## Recommendations for Opus

**Please evaluate:**
1. Which of these 6 issues are blocking vs nice-to-have?
2. Scientifically, is 37-38/63 features acceptable for quiet stars?
3. Should we proceed with current 486 targets or fix issues first and re-run?
4. What database schema changes are needed?
5. Should we add more validation steps before the full 1000-target run?

**Deliverable:**
Provide a prioritized action plan with:
- SQL migration scripts for schema changes
- Modified upload logic for ground truth tracking
- Data quality thresholds (feature counts, extraction time, etc.)
- Go/no-go criteria for scaling to 1000 targets

---

**Created:** 2026-01-16 10:00 UTC
**Author:** Claude Sonnet (code analysis) + Gemini (astrophysics review)
**For Review By:** Claude Opus (scientific validation & decision-making)
