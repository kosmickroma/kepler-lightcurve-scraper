# XenoScan Validation Pipeline Remediation Plan

**Date**: 2026-01-17
**Status**: IMPLEMENTED - All 7 fixes applied, ready to resume processing
**Sources**: Gemini (astrophysicist review), Opus exploration agents, CSV analysis

---

## Gemini's Findings - VERIFIED BY CSV ANALYSIS

| Finding | Gemini Said | CSV Shows | Status |
|---------|-------------|-----------|--------|
| Kurtosis outlier | 11,683 (KIC 007510397) | 11,683.7 (KIC 007510397) | **EXACT MATCH** |
| Skewness outlier | -89.5 | -89.57 | **EXACT MATCH** |
| Max excursion | 1,553σ | 1,553.7σ | **EXACT MATCH** |
| Instrumental aliases | 40 stars | 44 stars | **CONFIRMED** |
| Time vs size correlation | ~0.10 | 0.083 | **CONFIRMED** |
| Mean extraction time | 24 min | 25.1 min | **CONFIRMED** |
| Transit BLS features | 100% null | 100% null | **CONFIRMED** |
| Centroid features | 100% null | 100% null | **CONFIRMED** |
| Ghost columns | ~40% | 25 columns (36%) | **CONFIRMED** |
| Inverse efficiency paradox | 6x slower on failures | 242s vs 1509s (6.2x) | **EXACT MATCH** |

### Critical Statistics from CSV

```
Total stars processed: 639
Stars with full features (48): 1 (0.16%)
Stars with partial features (37-38): 638 (99.84%)

CONTAMINATION IN "QUIET" BASELINE:
- Stars with |kurtosis| > 100: 106 (16.6%)
- Stars with |skewness| > 5: 62 (9.7%)
- Stars with stat_std > 2%: 21 (3.3%)
- Stars with excursion > 100σ: 16 (2.5%)
- Instrumental aliases: 44 (6.9%)
- Duration < 100 days: 47 (7.4%)

FEATURES COMPLETELY BROKEN:
- All 10 transit features: 100% NULL
- All 4 centroid features: 100% NULL
- All 8 residual features: 99.8% NULL (only 1 star succeeded)
- All 3 autocorrelation features: 99.8% NULL (only 1 star succeeded)
```

---

## Executive Summary

The validation pipeline has **five categories of issues** that must be addressed for scientifically valid ML training:

| Category | Severity | Impact | Fix Complexity |
|----------|----------|--------|----------------|
| 1. Efficiency Bottlenecks | CRITICAL | 24 min/star, 6x slower on failures | Medium |
| 2. Data Quality Gaps | CRITICAL | Contaminated training set | Medium |
| 3. Feature Extraction Bugs | HIGH | 40% features NULL/invalid | Easy-Medium |
| 4. Teff Distribution Mismatch | HIGH | Model learns stellar type, not transits | Easy |
| 5. BLS Feature Leakage | HIGH | Trivial anomaly detection | Easy |

---

## Phase 1: Emergency Efficiency Fixes (Do First)

**Goal**: Complete 900-star run in hours instead of days

### 1.1 Disable Pathological Algorithms (Temporary)

**File**: `preprocessing/features/residual.py`

The `lempel_ziv_complexity()` function (lines 14-64) has **O(N³) worst-case complexity**:
```python
# Line 47-48 - nested substring search
if s[l:l+k] in s[0:l+k-1]:  # O(N) search in O(N) loop
```

**Action**: Wrap in timeout or disable for this run:
```python
def lempel_ziv_complexity(signal: np.ndarray, bins: int = 10, timeout_sec: float = 5.0) -> float:
    # Add timeout wrapper - return 0.0 if exceeds limit
```

### 1.2 Add Operation-Level Timeouts

**File**: `preprocessing/streaming_worker.py`

Currently only has 3-minute worker timeout (line 101). Need per-operation timeouts.

**Action**: Add `concurrent.futures.TimeoutError` handling for expensive operations:
- BLS periodogram: 30 second timeout
- Hurst exponent: 10 second timeout
- Lempel-Ziv: 5 second timeout

### 1.3 Fix Error Handling Hang

**File**: Multiple feature extractors

The broad `except Exception` blocks (temporal.py:240, residual.py:199, etc.) catch errors but expensive operations complete before failing.

**Action**: Add early validation checks BEFORE expensive computations:
```python
# Check data quality FIRST
if np.max(np.abs(flux - 1.0)) > 100:  # Cosmic ray present
    return null_features  # Don't waste time on bad data
```

---

## Phase 2: Data Quality Layer (Pre-Extraction Filtering)

**Goal**: Clean input data before feature extraction

### 2.1 Sigma Clipping for Cosmic Rays

**File**: `preprocessing/feature_extractor.py` (add to `load_light_curve_from_fits`)

**Problem**: Cosmic ray hits create 1,553σ excursions, kurtosis > 11,000

**Action**: Add sigma clipping after normalization:
```python
def load_light_curve_from_fits(self, fits_path):
    # ... existing load code ...

    # NEW: Sigma clip cosmic rays (5σ threshold)
    median = np.median(flux)
    mad = np.median(np.abs(flux - median))
    robust_std = 1.4826 * mad  # MAD to σ conversion

    valid_mask = np.abs(flux - median) < 5 * robust_std
    n_clipped = np.sum(~valid_mask)

    if n_clipped > 0:
        logger.info(f"Clipped {n_clipped} cosmic ray points ({100*n_clipped/len(flux):.2f}%)")
        flux = flux[valid_mask]
        time = time[valid_mask]
```

### 2.2 Pre-Extraction Quality Gates

**File**: `preprocessing/feature_extractor.py`

Add validation before expensive extraction:

```python
def validate_input_quality(self, flux, time):
    """Check for data quality issues before extraction."""
    issues = []

    # Duration check (Gemini: 44 days vs 1,470 days)
    duration = time[-1] - time[0]
    if duration < 90:  # Less than 1 Kepler quarter
        issues.append(f"Short duration: {duration:.1f} days")

    # Variability check (Gemini: freq_dominant_power = 0.94)
    std = np.std(flux)
    if std > 0.05:  # 5% variability = variable star
        issues.append(f"High variability: {std:.4f}")

    # Extreme outlier check
    kurtosis = stats.kurtosis(flux)
    if kurtosis > 100:
        issues.append(f"Extreme kurtosis: {kurtosis:.1f}")

    return issues
```

### 2.3 Outlier Flagging in Database

**File**: `preprocessing/database.py`

Add `data_quality_flags` column to store issues for post-hoc analysis:
- `is_cosmic_ray_contaminated`
- `is_high_variability`
- `is_short_duration`
- `is_instrumental_alias`

---

## Phase 3: Feature Extraction Bug Fixes

### 3.1 Fix Centroid Column Name Mismatch (CRITICAL)

**File**: `preprocessing/features/centroid.py` (lines 29-36)

**Root Cause**: Lightkurve converts column names to lowercase, but code checks uppercase.

**Current (broken)**:
```python
has_centr1 = 'MOM_CENTR1' in lc.columns  # Always False!
```

**Fixed**:
```python
# Option A: Check lowercase
has_centr1 = 'mom_centr1' in lc.columns

# Option B (better): Use lightkurve properties
if hasattr(lc, 'centroid_col') and hasattr(lc, 'centroid_row'):
    centr_x = lc.centroid_col.value
    centr_y = lc.centroid_row.value
```

### 3.2 Fix BLS Feature Leakage (CRITICAL)

**File**: `preprocessing/features/transit.py` (lines 268-273)

**Problem**: Setting ALL transit features to NULL when power < 0.05 creates feature leakage.

**Current (problematic)**:
```python
if power < 0.05:
    for key in features.keys():
        features[key] = None  # Model learns "has value" = anomaly
```

**Fixed**:
```python
# ALWAYS return BLS values, add significance flag
features['transit_bls_power'] = float(power)
features['transit_bls_period'] = float(period)
features['transit_bls_depth'] = float(abs(depth))
features['transit_bls_duration'] = float(duration)
features['transit_significant'] = 1.0 if power >= 0.05 else 0.0  # NEW FLAG

# Only null the derived features if no significant transit
if power < 0.05:
    features['transit_n_detected'] = 0
    features['transit_depth_consistency'] = None
    features['transit_timing_consistency'] = None
    # ... etc for derived features only
```

### 3.3 Add Logging to Autocorr/Residual Failures

**Files**: `preprocessing/features/temporal.py`, `preprocessing/features/residual.py`

**Problem**: Silent failures in `except Exception` blocks.

**Action**: Add specific exception logging:
```python
except Exception as e:
    logger.warning(f"temp_autocorr_1hr failed: {type(e).__name__}: {e}")
    features['temp_autocorr_1hr'] = None
```

---

## Phase 4: Validation Dataset Fixes

### 4.1 Fix Teff Distribution in Planet Hosts (CRITICAL)

**File**: `scripts/fetch_planet_hosts.py` (lines 93-94)

**Problem**: Takes first 100 alphabetically with NO Teff filtering.

**Current (biased)**:
```python
kepler_hosts = [h for h in unique_hosts if h.startswith('Kepler-')]
selected_hosts = kepler_hosts[:n_stars]  # Alphabetical = biased
```

**Fixed**:
```python
def fetch_planet_hosts(n_stars=100, mdwarf_fraction=0.20, output_file="data/known_planets_100.txt"):
    """Match quiet star Teff distribution: 80% Sun-like, 20% M-dwarf."""

    n_mdwarfs = int(n_stars * mdwarf_fraction)  # 20
    n_sunlike = n_stars - n_mdwarfs              # 80

    # Query already fetches st_teff (line 39)

    # Filter by Teff
    sunlike_hosts = df[(df['st_teff'] >= 4000) & (df['st_teff'] <= 7000)]
    mdwarf_hosts = df[df['st_teff'] < 4000]

    # Select from each category
    selected_sunlike = sunlike_hosts['hostname'].unique()[:n_sunlike]
    selected_mdwarfs = mdwarf_hosts['hostname'].unique()[:n_mdwarfs]

    selected_hosts = list(selected_sunlike) + list(selected_mdwarfs)
```

### 4.2 Export Stellar Parameters to Supabase

**File**: `preprocessing/database.py`

Add columns to `targets` table:
- `st_teff` (effective temperature, K)
- `st_rad` (stellar radius, R_sun)
- `st_mass` (stellar mass, M_sun)

This enables:
1. Stratified analysis by stellar type
2. Physical plausibility checks (transit depth → planet radius)
3. Post-hoc bias detection

---

## Phase 5: ML Training Preparation

### 5.1 Pre-Training Purge Script

**New File**: `scripts/prepare_training_data.py`

```python
def prepare_training_data(df):
    """Clean features before Isolation Forest training."""

    # 1. Drop constant columns (Gemini: stat_median always 1)
    for col in df.columns:
        if df[col].nunique() <= 1:
            logger.info(f"Dropping constant column: {col}")
            df = df.drop(columns=[col])

    # 2. Drop ghost columns (>95% null)
    null_pct = df.isnull().sum() / len(df)
    ghost_cols = null_pct[null_pct > 0.95].index
    logger.info(f"Dropping {len(ghost_cols)} ghost columns: {list(ghost_cols)}")
    df = df.drop(columns=ghost_cols)

    # 3. Purge outlier "quiet" stars
    purge_mask = (
        (df['stat_kurtosis'].abs() > 100) |
        (df['stat_skewness'].abs() > 5) |
        (df['stat_std'] > 0.02) |
        (df['freq_dominant_power'] > 0.5)
    )
    n_purged = purge_mask.sum()
    logger.info(f"Purging {n_purged} outlier 'quiet' stars")
    df = df[~purge_mask]

    # 4. Move instrumental aliases to separate test set
    alias_mask = df['freq_is_instrumental_alias'] == 1
    df_aliases = df[alias_mask]
    df = df[~alias_mask]

    return df, df_aliases
```

### 5.2 Feature Selection for ML

Based on Gemini's analysis, these features should be **excluded** from initial training:

| Feature | Reason |
|---------|--------|
| `stat_median` | Always 1.0 (constant) |
| `freq_high_freq_power` | Always 0 (constant) |
| `freq_power_ratio` | Always 0 (constant) |
| `temp_stationarity_pvalue` | Always ~0 (no variance) |
| `temp_autocorr_*` | 99.8% null (extraction failing) |
| `resid_*` | 99.8% null (extraction failing) |
| `centroid_*` | 100% null until fix applied |

---

## Implementation Order

### Immediate (Before Continuing Run)
1. **Phase 1.1**: Disable/timeout `lempel_ziv_complexity`
2. **Phase 3.1**: Fix centroid column names
3. **Phase 3.2**: Fix BLS feature leakage

### Before Planet Host Processing
4. **Phase 4.1**: Fix Teff distribution in `fetch_planet_hosts.py`
5. **Phase 2.1**: Add sigma clipping for cosmic rays

### Before ML Training
6. **Phase 5.1**: Create pre-training purge script
7. **Phase 2.2**: Add pre-extraction quality gates
8. **Phase 4.2**: Export stellar parameters

### Post-Validation (Nice to Have)
9. **Phase 1.2**: Add operation-level timeouts
10. **Phase 3.3**: Improve error logging

---

## Scientific Validation Checklist

After implementing fixes, verify:

- [ ] Teff distribution: Planet hosts match 80/20 Sun-like/M-dwarf ratio
- [ ] BLS features: Quiet stars have low power values (not NULL)
- [ ] Centroid features: Non-null for processed stars
- [ ] Kurtosis range: No values > 100 in training set
- [ ] Skewness range: |skew| < 5 for all training stars
- [ ] Variability: stat_std < 0.02 for "quiet" baseline
- [ ] Duration: All stars > 90 days of data
- [ ] Instrumental aliases: Separated from training set
- [ ] Feature variance: No constant columns in ML input

---

## Files to Modify

| File | Changes |
|------|---------|
| `preprocessing/features/residual.py` | Add timeout to lempel_ziv_complexity |
| `preprocessing/features/centroid.py` | Fix column name case (MOM_CENTR1 → mom_centr1) |
| `preprocessing/features/transit.py` | Always return BLS values, add transit_significant flag |
| `preprocessing/feature_extractor.py` | Add sigma clipping, quality gates |
| `scripts/fetch_planet_hosts.py` | Add Teff-stratified selection |
| `scripts/prepare_training_data.py` | NEW: Pre-training purge script |
| `preprocessing/database.py` | Add stellar parameter columns |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Reprocessing needed after fixes | Can re-extract features from cached FITS files |
| M-dwarf planet hosts may be scarce | Query NASA archive first to check availability |
| Timeout values too aggressive | Start conservative (30s BLS), adjust based on data |
| Purge removes too many stars | Log purged stars, can adjust thresholds |

---

## User Decisions (Confirmed)

1. **Run Status**: PAUSE current run, apply efficiency fixes immediately, then resume
2. **Outlier Handling**: Move to "Known Artifacts" test set (preserve for analysis, exclude from training)
3. **CSV Review**: User will provide data for cross-reference

---

## Execution Sequence (Updated)

### Step 1: Stop Current Run
- Gracefully stop the quiet star processor
- Note the last successfully processed target

### Step 2: Apply Critical Fixes
1. Fix `lempel_ziv_complexity` timeout (residual.py)
2. Fix centroid column names (centroid.py)
3. Fix BLS feature leakage (transit.py)

### Step 3: Resume Processing
- Resume from last checkpoint with fixed code
- Expect ~2 hours for remaining ~300 stars (vs ~10 hours unfixed)

### Step 4: Pre-Training Data Prep
- Export to CSV
- Run purge script to separate outliers into "Known Artifacts" set
- Verify Teff distribution

### Step 5: Planet Host Processing
- Apply Teff-stratified selection (80/20)
- Process 100 planet hosts with fixed extraction

---

## GEMINI REVIEW SUMMARY

*Copy this section to Gemini for scientific validation before implementation*

---

### What We Found (Your Analysis = 100% Correct)

**Your exact findings verified:**
- KIC 007510397: kurtosis=11,683.7, skew=-89.57 ✓
- Max excursion: 1,553.7σ ✓
- Inverse efficiency paradox: 242s (success) vs 1,509s (failure) = 6.2x ✓
- All transit/centroid features: 100% NULL ✓
- 44 instrumental aliases (you said 40) ✓

**Root causes identified by code analysis:**

1. **Lempel-Ziv Complexity** (`residual.py:47-56`) - O(N³) substring search causing 25-68 min extraction times

2. **Centroid Column Mismatch** (`centroid.py:29-36`) - Code checks for `MOM_CENTR1` (uppercase), but lightkurve converts to `mom_centr1` (lowercase). 100% failure rate.

3. **BLS Feature Leakage** (`transit.py:268-273`) - Sets ALL transit features to NULL when power < 0.05. Quiet stars will never have transits, so this creates trivial detection.

4. **No Cosmic Ray Clipping** - Single-point outliers (1,553σ) inflate kurtosis to 11,683 because no sigma-clipping before feature extraction.

---

### Proposed Fix Sequence

**Phase 1: Emergency Speed Fix** (apply now, resume run)
```
1. Add 5-second timeout to lempel_ziv_complexity() → ~10x speedup
2. Fix centroid column names (uppercase → lowercase)
3. Fix BLS: always return values, add transit_significant flag
```

**Phase 2: Data Quality Layer** (before planet hosts)
```
4. Add 5σ sigma-clipping before feature extraction
5. Add pre-extraction quality gates (kurtosis, duration, variability)
```

**Phase 3: Training Data Prep** (before ML)
```
6. Purge to "Known Artifacts" set:
   - 106 stars with |kurtosis| > 100
   - 62 stars with |skewness| > 5
   - 44 instrumental aliases
   - 47 stars with duration < 100 days

7. Drop constant/ghost columns (25 columns, 36% of features)
```

**Phase 4: Validation Balance** (critical for scientific validity)
```
8. Fix fetch_planet_hosts.py: Add Teff stratification (80% Sun-like, 20% M-dwarf)
   Current: Takes first 100 alphabetically (biased)
   Fixed: Match quiet star distribution to prevent stellar-type leakage
```

---

### Gemini's Scientific Validation (APPROVED)

**1. Purge thresholds**: ✅ APPROVED as scientifically appropriate
   - |kurtosis| > 100 → "Leptokurtic behavior - data dominated by rare extreme spikes"
   - |skewness| > 5 → "Massive asymmetry from ramps or data drops"
   - stat_std > 2% → "20,000 ppm = Variable Star or Binary, not quiet"
   - duration < 100 days → "Need 3-4 months to distinguish transit from noise"

**2. BLS for quiet stars**: ✅ Option (A) - Always run and report low power
   > "The Noise Floor is just as important as the Signal. By providing low-power
   > results for quiet stars, we teach the model the difference between
   > astrophysical noise and a coherent planetary signal."

**3. Sigma clipping threshold**: ✅ 5σ is the "Golden Rule" for Kepler
   - 3σ too aggressive (might clip Hot Jupiter transits)
   - 10σ too loose (leaves in 1,553σ glitches)
   - 5σ is the standard in Kepler data processing

**4. Ghost columns**: ✅ Option (C) - Re-extract after fixes
   > "Since the Ghost status was caused by bugs (case-sensitivity and low-power
   > NULLing), we shouldn't drop these features yet. They are some of the most
   > powerful tools for finding planets (especially Centroids)."

   Action: After fixes, drop any columns that STILL remain NULL.

**5. Instrumental aliases**: ✅ Option (C) - Separate "Known Artifact" test set
   > "I want to see if the model can tell the difference between a Planet and a
   > Reaction Wheel Glitch. By putting them in a separate test set, you can run
   > a Diagnostic Check: Does my model flag the aliases as anomalies?"

---

**FINAL VERDICT FROM GEMINI:**
> "The plan is Scientifically Valid. Proceed with Option 1: Pause, Fix, and Restart."
>
> "The Inverse Efficiency Paradox fix alone (Lempel-Ziv timeout) is going to save
> you nearly 20 hours of compute time. More importantly, the Teff Stratification
> fix ensures that your Planet Host training set is a true apples-to-apples
> comparison with your Quiet baseline."

---

### Expected Outcomes After Fixes

| Metric | Current | After Fix |
|--------|---------|-----------|
| Extraction time | 25 min/star | ~4 min/star |
| Valid features | 37-38/63 | 55-60/63 |
| Transit features | 0% valid | 100% valid |
| Centroid features | 0% valid | 100% valid |
| Training set size | 639 stars | ~450 clean stars |
| Ghost columns | 25 | 0-5 |

---

### Scientific Validation Checklist (for Gemini)

Before ML training, verify:
- [ ] Teff distribution matches between quiet stars and planet hosts
- [ ] No |kurtosis| > 100 in training set
- [ ] No |skewness| > 5 in training set
- [ ] All training stars have duration > 100 days
- [ ] BLS features populated for all stars (quiet = low power, hosts = high power)
- [ ] Centroid features populated (for false positive detection)
- [ ] Instrumental aliases separated from training
- [ ] No constant columns in feature matrix

---

*End of Gemini Review Summary*
