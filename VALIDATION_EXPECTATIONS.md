# Validation Run Expectations & Success Criteria

**Date:** 2026-01-15
**Status:** Ready to run 1000-target validation
**Expected Duration:** 10-15 hours

---

## What the Validation Run Does

Processes 1000 Kepler targets (900 quiet stars + 100 planet hosts) to:
1. Download light curves from NASA MAST archive
2. Extract 62 scientific features per target
3. Upload results to Supabase database
4. Validate that the pipeline produces scientifically meaningful results

---

## Target Breakdown

| Category | Count | Purpose |
|----------|-------|---------|
| Quiet Stars | 900 | Baseline (no known planets, low noise) |
| - Sun-like (Teff 4000-7000K) | 720 | Standard stellar population |
| - M-Dwarfs (Teff < 4000K) | 180 | Pandora mission compatibility |
| Planet Hosts | 100 | Positive controls (known transits) |
| **Total** | **1000** | |

---

## Success Criteria

### 1. Completion Rate
- **Target:** ≥95% success (950+ / 1000)
- **Acceptable:** ≥90% success (900+ / 1000)
- **Failure:** <90% success

### 2. Feature Extraction
- **Target:** All 62 features extracted for successful targets
- **Acceptable:** 58+ features (some optional features NULL)
- Check: No systematic NULL patterns across targets

### 3. Data Quality Indicators

| Feature | Quiet Stars | Planet Hosts | Expected Difference |
|---------|-------------|--------------|---------------------|
| `stat_std` | Lower | Higher | Planet hosts more variable |
| `transit_bls_power` | Low/NULL | High | Planet hosts have transits |
| `transit_n_detected` | 0 or NULL | >0 | Planet hosts have transits |
| `freq_dominant_power` | Lower | Higher | Transits create periodicity |

### 4. Scientific Validation Features
- `transit_physically_plausible`: Most planet hosts = 1.0 (valid planets)
- `transit_odd_even_consistent`: Most planet hosts = 1.0 (not binaries)
- `freq_is_instrumental_alias`: Most targets = 0.0 (real signals)

---

## What to Look For When Done

### Immediate Checks (First 5 Minutes)

1. **Check completion rate:**
   ```sql
   SELECT
     COUNT(*) as total,
     COUNT(CASE WHEN stat_mean IS NOT NULL THEN 1 END) as successful
   FROM features
   WHERE created_at > '2026-01-15';
   ```

2. **Check feature coverage:**
   ```sql
   SELECT
     COUNT(*) as total,
     COUNT(stat_mean) as stat_mean,
     COUNT(transit_bls_power) as transit_bls_power,
     COUNT(freq_dominant_period) as freq_dominant_period
   FROM features;
   ```

3. **Verify no duplicates:**
   ```sql
   SELECT target_id, COUNT(*)
   FROM features
   GROUP BY target_id
   HAVING COUNT(*) > 1;
   ```

### Statistical Analysis (First Hour)

1. **Compare quiet vs planet hosts:**
   ```sql
   -- Get stats by target type
   SELECT
     CASE
       WHEN target_id LIKE 'Kepler-%' THEN 'planet_host'
       ELSE 'quiet_star'
     END as target_type,
     AVG(stat_std) as avg_variability,
     AVG(transit_bls_power) as avg_transit_power,
     COUNT(*) as n_targets
   FROM features
   GROUP BY target_type;
   ```

2. **Check M-Dwarf representation:**
   ```sql
   -- Verify we have M-Dwarfs in the quiet stars
   -- (Need to cross-reference with metadata)
   ```

3. **Physical plausibility check:**
   ```sql
   SELECT
     transit_physically_plausible,
     COUNT(*) as count
   FROM features
   WHERE transit_physically_plausible IS NOT NULL
   GROUP BY transit_physically_plausible;
   ```

---

## Expected Output During Run

Every 50 targets you'll see:
```
================================================================================
[PROGRESS] 500/1000 targets processed (50.0%)
           Success rate: 97.2%
           Speed: 0.85 tgt/s
           Est. time remaining: 7.5h
================================================================================
```

Every target:
```
Processing KIC 12345678...
  Downloaded 15234 points
  Extracted 62 features
  Uploaded to Supabase
```

---

## If Something Goes Wrong

### Rate Limiting (429 errors)
- Script has exponential backoff built in
- Will retry automatically up to 3 times
- If persistent, reduce worker count

### Database Timeouts (504/544 errors)
- Batch sleep every 50 uploads prevents this
- If occurs, the script will retry

### Missing Quarters
- Some targets have incomplete data
- Script handles gracefully, continues with available quarters
- Features may be NULL for very short light curves

### Memory Issues
- Script downloads quarters one at a time
- Should not run out of memory
- If occurs, restart and it will skip completed targets

---

## After Validation Completes

### Step 1: Quick Sanity Check
Run the SQL queries above to verify completion rate and feature coverage.

### Step 2: Export Results
```bash
python scripts/export_validation_results.py  # (create this if needed)
```

### Step 3: Statistical Analysis
Compare quiet stars vs planet hosts across all 62 features.

### Step 4: Identify Anomalies
Look for quiet stars that have high transit power (potential undiscovered planets).

### Step 5: Document Findings
Update this document with actual results for publication.

---

## Files Generated

| File | Description |
|------|-------------|
| `data/quiet_stars_900.txt` | List of quiet star target IDs |
| `data/quiet_stars_900_metadata.csv` | Stellar parameters for quiet stars |
| `data/known_planets_100.txt` | List of planet host target IDs |
| `data/known_planets_100_metadata.csv` | Planet parameters |
| `data/provenance_*.json` | Run configuration (created at end) |

---

## Contact Points

- **Supabase Dashboard:** Check `features` table for results
- **Progress:** Watch terminal output
- **Errors:** Check terminal for error messages

---

**Ready to start:** `python scripts/test_validation_1000.py`
