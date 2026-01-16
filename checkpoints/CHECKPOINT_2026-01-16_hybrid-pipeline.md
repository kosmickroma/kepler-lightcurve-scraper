# Checkpoint: Hybrid Pipeline Architecture
**Date:** 2026-01-16 09:15 UTC
**Status:** Local validation pipeline RUNNING (486 targets, ~10-15 hours estimated)

---

## Summary

We pivoted from an API-only approach to a **hybrid pipeline architecture** that supports both:
1. **Local processing** for bulk historical data (Kepler full catalog)
2. **API processing** for fresh/streaming data (Pandora 2026, new discoveries)

This change eliminates API rate limiting issues and enables processing of the full ~160,000 Kepler catalog on any computer.

---

## Current Run Status

### Validation In Progress
- **Started:** 2026-01-16 ~09:00 UTC
- **Targets:** 486 quiet stars (from 900 list, subset with downloaded data)
- **Progress:** First targets uploading successfully
- **Rate:** ~2 targets per 4 minutes (2 workers)
- **Estimated completion:** 10-15 hours from start

### Confirmed Working
- FITS file loading and stitching: **YES**
- Feature extraction (38-63/63 features): **YES**
- Supabase upload (HTTP 201/200): **YES**
- No API rate limiting: **YES**

---

## HANDOFF INSTRUCTIONS FOR SONNET

### Monitoring the Run

The validation script is running in the user's terminal:
```bash
python scripts/run_validation_local.py
```

**Good signs to look for:**
- `KIC XXXXXXX: Extracted XX/63 valid features`
- `HTTP/2 201 Created` - new records
- `HTTP/2 200 OK` - updates
- `KIC XXXXXXX: Uploaded to database`
- Progress messages: `Processing batch X/10`

**Warning signs:**
- Repeated errors for same target
- `HTTP 401` or `HTTP 403` - Supabase auth issue
- Python exceptions/tracebacks
- No output for >15 minutes (check CPU usage)

### When Run Completes

The script will output:
```
================================================================================
VALIDATION COMPLETE
================================================================================
Targets processed: XXX
Successful: XXX (XX.X%)
Failed: XXX
```

**Success criteria:** >=90% success rate (438+ of 486 targets)

### Validation Queries for Supabase

Run these in Supabase SQL Editor to validate:

```sql
-- 1. Count total features
SELECT COUNT(*) as total_features FROM features;
-- Expected: 486+ rows (one per target)

-- 2. Check feature completeness
SELECT
    AVG(CASE WHEN stat_mean IS NOT NULL THEN 1 ELSE 0 END) as stat_completeness,
    AVG(CASE WHEN freq_dominant_period IS NOT NULL THEN 1 ELSE 0 END) as freq_completeness,
    AVG(CASE WHEN transit_bls_power IS NOT NULL THEN 1 ELSE 0 END) as transit_completeness
FROM features;
-- Expected: >0.9 for stat, >0.8 for freq/transit

-- 3. Check value distributions (sanity check)
SELECT
    MIN(stat_mean) as min_mean,
    MAX(stat_mean) as max_mean,
    AVG(stat_mean) as avg_mean,
    STDDEV(stat_mean) as std_mean
FROM features WHERE stat_mean IS NOT NULL;
-- Expected: mean ~1.0 (normalized flux), std small

-- 4. Find potential anomalies (high skewness = asymmetric dips)
SELECT target_id, stat_skewness, stat_kurtosis, transit_bls_power
FROM features
WHERE stat_skewness IS NOT NULL
ORDER BY ABS(stat_skewness) DESC
LIMIT 10;
-- Large negative skewness = transit-like dips

-- 5. Run simple anomaly detection
SELECT target_id,
       stat_skewness,
       stat_std,
       shape_max_excursion_down,
       transit_bls_power
FROM features
WHERE stat_std > (SELECT AVG(stat_std) + 2*STDDEV(stat_std) FROM features)
   OR ABS(stat_skewness) > (SELECT AVG(ABS(stat_skewness)) + 2*STDDEV(ABS(stat_skewness)) FROM features)
ORDER BY stat_std DESC;
-- These are statistical outliers worth investigating
```

### Scientific Validation Checklist

After run completes, verify:

1. **Feature distributions are physical:**
   - `stat_mean` should be ~1.0 (normalized flux)
   - `stat_std` should be small (0.001-0.01 typical)
   - `freq_dominant_period` should show reasonable periods (0.1-100 days)
   - `transit_bls_depth` should be small (<0.1 for most, planets are 0.001-0.01)

2. **No systematic errors:**
   - Features shouldn't all be NULL for one domain
   - No extreme outliers that indicate calculation errors
   - Temporal features should reflect ~4 years of Kepler data

3. **Anomaly detection works:**
   - Running Isolation Forest or simple stats should find outliers
   - Known variable stars (if any in set) should score as anomalous
   - Distribution of anomaly scores should be mostly normal with tail

---

## Next Steps After Validation

### If Validation Passes (>=90% success)

1. **Add planet hosts for complete validation set:**
   ```bash
   # Create KIC lookup for known planets (manual or from NASA archive)
   # Add to data/known_planets_100.txt as KIC IDs
   python scripts/generate_download_urls.py data/known_planets_100.txt
   python scripts/bulk_downloader.py data/known_planets_100_urls.txt data/fits_cache/ 4
   python scripts/local_processor.py data/fits_cache/ --upload
   ```

2. **Verify planets detected as anomalies:**
   - Known transit hosts should have high `transit_bls_power`
   - Should appear in anomaly detection results

3. **Begin full catalog processing:**
   ```bash
   # Get full Kepler target list (~160,000 KICs)
   # Can be downloaded from MAST or NASA Exoplanet Archive

   # Generate URLs (will take time)
   python scripts/generate_download_urls.py data/full_kepler_catalog.txt

   # Download in background (days/weeks)
   nohup python scripts/bulk_downloader.py data/full_kepler_catalog_urls.txt data/fits_cache/ 4 &

   # Process as files download (can run concurrently)
   python scripts/local_processor.py data/fits_cache/ --upload --delete
   ```

### If Validation Fails

1. Check error logs for patterns
2. Common issues:
   - Supabase connection: Check `.env` credentials
   - FITS file corruption: Delete and re-download affected targets
   - Feature extraction errors: May need to handle edge cases
3. Fix issues and re-run on failed targets

---

## Architecture Reference

```
                    XENOSCAN Pipeline
================================================================================

   MODE A: LOCAL (Bulk Historical Data)
   ─────────────────────────────────────
   Input:  Direct MAST HTTP downloads
   Use:    Kepler/K2 full catalog (~160,000 targets)
   Speed:  ~4-8 files/sec (no rate limits)
   Disk:   Chunk & delete (needs only ~15-20GB at a time)

   MODE B: API (Fresh/Streaming Data)
   ─────────────────────────────────────
   Input:  lightkurve search & download API
   Use:    Pandora mission (2026), new discoveries
   Speed:  ~0.02 targets/sec (rate-limited)
   Disk:   Minimal (processes and deletes)

================================================================================
   SHARED: Feature extraction, database upload, ML pipeline
================================================================================
```

### Data Flow
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Target    │     │    FITS     │     │  Features   │     │  Supabase   │
│    List     │────▶│   Files     │────▶│ Extraction  │────▶│  Database   │
│  (KIC IDs)  │     │  (Local)    │     │ (63 values) │     │  (Cloud)    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

---

## Files Reference

### New Scripts (Local Processing)
| Script | Purpose |
|--------|---------|
| `scripts/generate_download_urls.py` | KIC IDs → MAST URLs |
| `scripts/bulk_downloader.py` | Parallel HTTP downloads |
| `scripts/local_processor.py` | FITS → features → Supabase |
| `scripts/run_validation_local.py` | Master validation script |

### Modified Files
| File | Change |
|------|--------|
| `preprocessing/downloader.py` | Added cache-clearing fix |
| `README.md` | Added hybrid architecture docs |

### Key Directories
- `data/fits_cache/` - Downloaded FITS files (deleted after processing)
- `data/quiet_stars_900_urls.txt` - URL list for quiet stars
- `checkpoints/` - Progress documentation

---

## Resource Requirements

### Minimum (Any Laptop)
- **Disk:** 15-20GB free
- **RAM:** 4GB
- **Network:** Any broadband
- **Time:** Days to weeks for full catalog

### The Point
**Any computer can process the full Kepler catalog.** Chunk-and-delete means you never need more than ~20GB regardless of total data size (~1.1TB).

---

**Checkpoint saved at:** 2026-01-16 09:15 UTC
**Validation running:** Yes (486 targets)
**Expected completion:** ~10-15 hours
**Next checkpoint:** After validation completes
