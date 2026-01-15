# XENOSCAN: Kepler Light Curve Feature Extraction Pipeline

**A Scientifically Rigorous Pipeline for Automated Exoplanet Candidate Validation**

---

## Abstract

We present XENOSCAN, a 62-feature classification pipeline for NASA Kepler photometry designed to discriminate astrophysical signals from instrumental artifacts at scale. The pipeline processes ~199,000 Kepler targets through seven feature domains (statistical, temporal, frequency, residual, shape, transit, centroid), implementing false-positive rejection logic derived from the Kepler Data Validation pipeline and contemporary exoplanet vetting literature.

Critical design choices address systematic errors identified in prior transit searches: we exclusively use Pre-search Data Conditioning (PDCSAP) flux to remove telescope systematics, filter Rolling Band electronic artifacts (Quality Bit 17), and implement physical plausibility checks that reject signals implying planet radii > 2 R_Jupiter. Target selection maintains an 80/20 Sun-like to M-Dwarf ratio, calibrated for the upcoming Pandora mission (2026) and representative of galactic stellar populations.

This document serves as both technical documentation and a living scientific record of methodology decisions. Each section explains not just *what* we do, but *why*—anticipating the questions a skeptical reviewer would ask.

**Current Phase:** Validation (1000-target test in progress)

---

## Table of Contents

1. [The Scientific Problem We're Solving](#1-the-scientific-problem-were-solving)
2. [Why Our Approach Works](#2-why-our-approach-works)
3. [Data Quality: The Foundation of Everything](#3-data-quality-the-foundation-of-everything)
4. [The 62 Features: What They Are and Why They Matter](#4-the-62-features-what-they-are-and-why-they-matter)
5. [Defending Against False Positives](#5-defending-against-false-positives)
6. [The Skeptic's Questions (And Our Answers)](#6-the-skeptics-questions-and-our-answers)
7. [What We Expect to See in Validation](#7-what-we-expect-to-see-in-validation)
8. [Running the Pipeline](#8-running-the-pipeline)
9. [Project Status and Next Steps](#9-project-status-and-next-steps)
10. [References](#10-references)

---

## 1. The Scientific Problem We're Solving

### 1.1 The Kepler Gold Mine

The Kepler mission stared at ~200,000 stars for four years, measuring their brightness every 30 minutes. When a planet crosses in front of its star (a "transit"), the star dims by a tiny amount—typically 0.01% to 1%. The official Kepler pipeline found ~2,700 confirmed planets this way.

**But here's the thing:** The official pipeline was optimized for *periodic* transits. It looks for the same dip happening over and over at regular intervals. This means it potentially missed:

- **Single-transit events** — A planet with a 5-year orbit might only transit once in the 4-year Kepler dataset
- **Weird signals** — Anything that doesn't look like a textbook transit gets ignored
- **Signals in noisy stars** — M-dwarfs are intrinsically variable (flares, starspots), which can mask weak planet signals
- **Signals the pipeline flagged as "probably not a planet"** — Some of these rejections might be wrong

### 1.2 What We're Actually Doing

Instead of looking for transits directly, we're building a **statistical fingerprint** of each light curve. We extract 62 numbers that describe:

- How variable is this star?
- Is there periodic behavior? At what timescales?
- Are there sudden dips? How deep? How often?
- Does the star's position shift when it dims? (This would indicate a background object)
- Is there anything *weird* about this light curve compared to "quiet" stars?

Then we can use machine learning to find anomalies—stars whose fingerprints look different from the baseline. Some of those anomalies will be planets. Some will be eclipsing binaries. Some will be instrumental artifacts. But the key is: **we'll find things the original pipeline missed.**

### 1.3 Why This Matters Now

Two reasons:

1. **Computational power** — In 2009, processing 200,000 stars with 62 features each was expensive. Now it's trivial.

2. **The Pandora Mission (2026)** — NASA's upcoming Pandora mission specifically targets M-dwarf stars for atmospheric characterization. M-dwarfs are ~75% of all stars, but they're noisy and underrepresented in current exoplanet catalogs. Our pipeline explicitly includes M-dwarfs in the baseline, so we can find planets around them.

---

## 2. Why Our Approach Works

### 2.1 The Baseline Concept

The core idea is simple: **Define what a "boring" star looks like, then find stars that don't match.**

A "quiet" star has:
- No known planets
- Low photometric noise (CDPP < 200 ppm)
- No dramatic variability
- Normal statistical properties

We process 900 of these quiet stars to establish the baseline. Then we process 100 stars with *confirmed* planets to verify our features can distinguish them. If the planet hosts look statistically different from the quiet stars, our features are working.

### 2.2 Why 62 Features?

We didn't pick 62 arbitrarily. Each feature captures a different aspect of the light curve:

| Domain | Count | What It Captures |
|--------|-------|------------------|
| Statistical | 12 | Basic properties: mean brightness, how much it varies, whether the distribution is skewed |
| Temporal | 10 | Time-domain behavior: does it trend up/down? Is tomorrow's brightness correlated with today's? |
| Frequency | 11 | Periodic signals: is there a dominant period? How strong? Is it a known instrumental frequency? |
| Residual | 8 | What's left after removing trends: is there structure in the noise? |
| Shape | 8 | Dip/peak morphology: are the dips symmetric? How fast do they happen? |
| Transit | 10 | Box Least Squares detection: if there IS a periodic dip, how deep? What period? Is it physically plausible? |
| Centroid | 3 | Pixel position: does the star's apparent position shift when it dims? |

The idea is that a real planet transit will show up across *multiple* domains—it affects the variance, creates periodic signal, shows specific dip shapes, AND doesn't cause centroid motion. An eclipsing binary might affect variance and periodicity but *will* cause centroid motion (because the binary is a background star). Instrumental artifacts might show periodicity at 24 hours but won't show the characteristic transit shape.

### 2.3 The 80/20 Sun-like to M-Dwarf Split

This is crucial and often overlooked. If we only trained on Sun-like stars, **every M-dwarf would look anomalous** because M-dwarfs are intrinsically more variable.

Our baseline includes:
- **720 Sun-like stars** (Teff 4000-7000 K) — The "standard" exoplanet host population
- **180 M-dwarfs** (Teff 2500-4000 K) — Smaller, cooler, more variable stars

The 20% M-dwarf fraction means:
1. The model learns that M-dwarf variability is *normal*, not anomalous
2. We can find planets around M-dwarfs without false-flagging every M-dwarf as "weird"
3. We're ready for Pandora, which specifically targets M-dwarfs

---

## 3. Data Quality: The Foundation of Everything

This is where most amateur pipelines fail. **If you start with bad data, your features are garbage.**

### 3.1 PDCSAP vs SAP Flux: Why This Matters Enormously

Kepler provides two flux measurements:

| Flux Type | What It Is | What's In It |
|-----------|------------|--------------|
| **SAP_FLUX** | Simple Aperture Photometry | Raw pixel counts. Contains: stellar signal + thermal drift + focus changes + pointing jitter + differential velocity aberration + everything else |
| **PDCSAP_FLUX** | Pre-search Data Conditioning SAP | Stellar signal only (mostly). Systematics removed algorithmically |

**If you use SAP flux, your "quiet" stars will look noisy as hell** because SAP includes all the telescope's bad behavior. Your classifier will learn to flag "telescope having a bad day" as anomalous, not "star with a planet."

We explicitly use PDCSAP:

```python
lc_quarter = res.download(
    flux_column='pdcsap_flux',
    quality_bitmask='default'
)
```

This is specified in every download call and recorded in our provenance tracking.

### 3.2 The Rolling Band Problem (Quality Bit 17)

This is subtle but critical. Kepler's CCDs have an electronic artifact called "Rolling Band" that creates **fake periodic signals** at specific frequencies. If you don't filter it, you'll find "planets" that are actually electronic noise.

The Rolling Band artifact:
- Appears as periodic brightness variations
- Occurs at specific CCD row frequencies
- Can mimic planet transits if you're not careful
- Is flagged by Quality Bit 17 (value 131072)

Our `quality_bitmask='default'` setting automatically excludes data points affected by Rolling Band. This is the Kepler team's recommended approach (Van Cleve & Caldwell 2016).

### 3.3 What the Quality Bitmask Actually Filters

When we set `quality_bitmask='default'`, we exclude data affected by:

| Bit | Problem | Why It Matters |
|-----|---------|----------------|
| 0 | Attitude tweak | Spacecraft adjusted pointing; data unreliable |
| 3 | Coarse point | Spacecraft in coarse pointing mode; precision degraded |
| 5 | Reaction wheel desaturation | Momentum dump; systematic trends introduced |
| 6 | Argabrightening | Mysterious brightening events; contamination |
| **17** | **Rolling Band** | **Electronic artifact; fake periodic signals** |

We're not being paranoid—this is standard practice for any serious Kepler analysis.

---

## 4. The 62 Features: What They Are and Why They Matter

### 4.1 Statistical Features (12)

These capture the basic "shape" of the brightness distribution:

| Feature | What It Measures | Why It Matters |
|---------|------------------|----------------|
| `stat_mean` | Average brightness | Baseline flux level |
| `stat_std` | Standard deviation | How much the star varies—planets increase this |
| `stat_skewness` | Asymmetry of distribution | Transits cause negative skew (more dips than peaks) |
| `stat_kurtosis` | "Peakedness" | Transits cause excess kurtosis (outliers from dips) |
| `stat_min`, `stat_max` | Extremes | Transit depth shows up in min |
| `stat_range` | Max - Min | Total variation range |
| `stat_median` | Middle value | Robust central tendency |
| `stat_p05`, `stat_p95` | 5th/95th percentiles | Robust extremes |
| `stat_iqr` | Interquartile range | Robust spread measure |
| `stat_mad` | Median absolute deviation | Robust variability |

**Expected behavior:** Planet hosts should have slightly higher `stat_std` and negative `stat_skewness` compared to quiet stars, because transits add dips.

### 4.2 Temporal Features (10)

These capture how brightness changes over time:

| Feature | What It Measures | Why It Matters |
|---------|------------------|----------------|
| `temp_n_points` | Number of data points | Data quality indicator |
| `temp_duration_days` | Observation span | Coverage indicator |
| `temp_autocorr_1` | Correlation with 1-lag | Short-term predictability |
| `temp_autocorr_10` | Correlation with 10-lag | Medium-term structure |
| `temp_trend_slope` | Linear trend | Long-term drift |
| `temp_trend_strength` | R² of linear fit | How trendy is it? |
| `temp_n_zero_crossings` | Mean crossings | Oscillation frequency |
| `temp_stationarity` | ADF test statistic | Is the signal stable? |
| `temp_chunk_variance_ratio` | Early vs late variance | Does variability change? |
| `temp_max_consecutive_increase` | Longest upward run | Burst detection |

### 4.3 Frequency Features (11) — Including Alias Detection

These capture periodic behavior using Lomb-Scargle periodograms:

| Feature | What It Measures | Why It Matters |
|---------|------------------|----------------|
| `freq_dominant_period` | Strongest periodic signal | Planet orbital period candidate |
| `freq_dominant_power` | Strength of that signal | Signal-to-noise of periodicity |
| `freq_secondary_period` | Second-strongest period | Multiple planets? Harmonics? |
| `freq_secondary_power` | Strength of secondary | Multi-signal detection |
| `freq_period_ratio` | Dominant/secondary | Harmonic relationship? |
| `freq_power_ratio` | Dominant/secondary power | How dominant is the main signal? |
| `freq_n_significant_peaks` | Peaks above threshold | Complexity of periodic structure |
| `freq_spectral_entropy` | Spread of power | Concentrated vs distributed |
| `freq_low_freq_power` | Power at long periods | Stellar rotation? |
| `freq_high_freq_power` | Power at short periods | Short-period planets? Artifacts? |
| **`freq_is_instrumental_alias`** | **Matches known artifact frequencies** | **CRITICAL: Rejects fake signals** |

#### The Instrumental Alias Problem

This is one of our key scientific validation features. Certain periods are **almost always instrumental artifacts**, not real astrophysical signals:

| Period | Why It's Probably Fake |
|--------|------------------------|
| 12 hours | Earth's day/night (solar heating on spacecraft) |
| 24 hours | Same, fundamental frequency |
| ~4 hours | Reaction wheel frequency |
| 6, 8 hours | Orbital harmonics |
| 48 hours | Two-day alias |
| ~29.4 minutes | Kepler long-cadence sampling (Nyquist issues) |

When our feature extractor finds a dominant period, it checks: **Is this within 5% of a known instrumental frequency?** If yes, `freq_is_instrumental_alias = 1.0`. If no, `freq_is_instrumental_alias = 0.0`.

This prevents us from flagging a spacecraft artifact as "possible planet."

### 4.4 Transit Features (10) — Including Physical Validation

These use the Box Least Squares (BLS) algorithm specifically designed for transit detection:

| Feature | What It Measures | Why It Matters |
|---------|------------------|----------------|
| `transit_bls_power` | BLS signal strength | How "transit-like" is the best periodic signal? |
| `transit_bls_period` | Best-fit period | Orbital period if it's a planet |
| `transit_bls_depth` | Best-fit depth | (R_planet/R_star)² |
| `transit_bls_duration` | Transit duration | Constrains orbital geometry |
| `transit_n_transits` | Number of events | More transits = more confidence |
| `transit_depth_std` | Depth consistency | Real planets have consistent depths |
| **`transit_implied_r_planet_rjup`** | **Calculated planet radius** | **Physics check** |
| **`transit_physically_plausible`** | **Is R_planet ≤ 2 R_Jupiter?** | **Rejects brown dwarfs/binaries** |
| **`transit_odd_even_consistent`** | **Are odd/even transits the same depth?** | **Rejects eclipsing binaries** |
| `transit_snr` | Signal-to-noise ratio | Detection confidence |

#### The Physical Plausibility Check

This is crucial. Transit depth tells us:

```
(R_planet / R_star)² = transit_depth
```

If we know the stellar radius from the Kepler Input Catalog, we can calculate the implied planet radius:

```
R_planet = sqrt(transit_depth) × R_star × (R_Sun / R_Jupiter)
```

**Here's the key insight:** Planets max out at about 2 Jupiter radii. Beyond that, you're looking at a brown dwarf or a star. If our calculation implies R_planet > 2 R_Jupiter, the signal is almost certainly NOT a planet—it's an eclipsing binary or a brown dwarf companion.

- `transit_physically_plausible = 1.0` → R_planet ≤ 2 R_Jup → Could be a planet
- `transit_physically_plausible = 0.0` → R_planet > 2 R_Jup → Probably NOT a planet

#### The Odd-Even Consistency Check

Eclipsing binaries are a major source of false positives. Here's how they differ from planets:

**Planet transit:** Same depth every time (the planet is the same size on orbit 1, 2, 3, ...)

**Eclipsing binary:** ALTERNATING depths!
- Orbit 1: Small star blocks big star → moderate dip
- Orbit 2: Big star blocks small star → different dip
- Orbit 3: Same as orbit 1
- ...

We calculate:
- Mean depth of odd-numbered transits
- Mean depth of even-numbered transits
- If they differ by > 3σ → It's a binary, not a planet

- `transit_odd_even_consistent = 1.0` → Depths match → Consistent with planet
- `transit_odd_even_consistent = 0.0` → Depths alternate → Eclipsing binary

### 4.5 Centroid Features (3)

These track the star's apparent position:

| Feature | What It Measures | Why It Matters |
|---------|------------------|----------------|
| `centroid_jitter_mean` | Average position shift | Baseline motion |
| `centroid_jitter_std` | Position variability | How stable is the star? |
| `centroid_jitter_max` | Maximum shift | Biggest excursion |

**Why this matters:** If a background eclipsing binary is contaminating the aperture, the center of light shifts toward that binary during its eclipse. A true planet transit on the target star causes NO centroid motion.

Large `centroid_jitter_max` during flux dips = probably NOT a transit on the target star.

---

## 5. Defending Against False Positives

### 5.1 The False Positive Problem

In transit surveys, false positives outnumber true planets by ~10:1 or worse. The main culprits:

| False Positive Type | What It Is | How We Detect It |
|---------------------|------------|------------------|
| **Eclipsing Binary (EB)** | Two stars orbiting each other | Odd-even check, physical plausibility, centroid motion |
| **Background EB** | EB in the same pixel but far away | Centroid motion during dips |
| **Brown Dwarf** | Too big to be a planet, too small to be a star | Physical plausibility (R > 2 R_Jup) |
| **Instrumental** | Spacecraft artifacts | Alias detection, quality filtering |
| **Stellar Variability** | Starspots, flares | Shape features, transit consistency |

### 5.2 Our Multi-Layer Defense

We don't rely on any single check. Our features provide **independent evidence**:

1. **Layer 1: Data Quality** — PDCSAP flux, quality bitmask, Rolling Band filter
2. **Layer 2: Instrumental Alias** — Reject 12h/24h/etc periods
3. **Layer 3: Physical Plausibility** — Reject R > 2 R_Jupiter
4. **Layer 4: Odd-Even Consistency** — Reject alternating depths
5. **Layer 5: Centroid Motion** — Reject position shifts during dips

A real planet should pass ALL these checks. False positives typically fail at least one.

---

## 6. The Skeptic's Questions (And Our Answers)

This section anticipates what a peer reviewer or experienced astronomer would ask. These are the questions Gemini raised during code review.

### Q: "How do I know your 'quiet' star isn't just a crowded pixel?"

**A:** We select targets from the Kepler Input Catalog with criteria that minimize crowding. Additionally, our centroid features (59-62) quantify position shifts during flux excursions. If a "quiet" star shows centroid motion correlated with brightness changes, that's a red flag we can detect.

### Q: "Are you using cleaned flux?"

**A:** Yes. We explicitly specify `flux_column='pdcsap_flux'` in every download call. PDCSAP removes spacecraft systematics (thermal drift, pointing jitter, focus changes) while preserving astrophysical signals. This is documented in our provenance tracking, which records the exact parameters used for every processing run.

### Q: "Did you filter electronic noise?"

**A:** Yes. We use `quality_bitmask='default'`, which includes Rolling Band filtering (bit 17). Rolling Band is an electronic artifact that creates fake periodic signals. Without this filter, we'd find "planets" that are actually CCD noise.

### Q: "Is that transit depth physically possible?"

**A:** We check this explicitly. The `transit_physically_plausible` feature calculates the implied planet radius from the transit depth and stellar radius. If R_planet > 2 R_Jupiter, the feature returns 0.0 (not plausible). Objects larger than ~2 R_Jupiter are brown dwarfs or stars, not planets. This is based on planetary structure models (Fortney et al. 2007).

### Q: "Could this be an eclipsing binary?"

**A:** We check for this two ways:

1. **Physical plausibility** — EBs typically produce deeper eclipses implying R > 2 R_Jup
2. **Odd-even consistency** — EBs produce alternating eclipse depths; planets don't

If `transit_odd_even_consistent = 0.0`, we're likely looking at an EB, not a planet.

### Q: "Is this period real or a spacecraft artifact?"

**A:** The `freq_is_instrumental_alias` feature checks whether the dominant period matches known instrumental frequencies (12h, 24h, reaction wheel frequencies, etc.) within 5% tolerance. If it matches, the feature returns 1.0 (probably artifact). If not, 0.0 (probably real).

### Q: "Can I reproduce your results?"

**A:** Yes. Every processing run generates a `provenance.json` file recording:
- Library versions (lightkurve, astropy, numpy, scipy)
- Pipeline parameters (flux_column, quality_bitmask, feature_count)
- Timestamp and target count
- Python version and platform

This enables exact reproduction of any analysis.

### Q: "Why include M-dwarfs in the baseline? They're more variable."

**A:** Precisely BECAUSE they're more variable. If we only trained on Sun-like stars, the classifier would flag every M-dwarf as "anomalous" simply because M-dwarfs have more flares and starspots. By including 20% M-dwarfs in the baseline, we teach the model that M-dwarf variability is NORMAL. This lets us find actual anomalies (like planets) around M-dwarfs without drowning in false positives.

Additionally, the Pandora mission (2026) specifically targets M-dwarfs. We want to be ready.

### Q: "What if there's a real planet but your physical plausibility check rejects it?"

**A:** The 2 R_Jupiter threshold is conservative. The largest known planets are ~2 R_Jupiter (inflated hot Jupiters). Anything larger is, by definition, not a planet—it's a brown dwarf or star. We're not rejecting planets; we're rejecting non-planets that mimic planet signals.

### Q: "What about planets with only one transit?"

**A:** Single-transit events are challenging because BLS needs multiple transits to detect periodicity. However, our statistical and shape features can still flag single deep dips. A star with one deep dip will have anomalous `stat_skewness`, `stat_min`, and shape features compared to quiet stars. We won't get an orbital period, but we can identify the star as "worth investigating."

---

## 7. What We Expect to See in Validation

We're currently running a 1000-target validation (900 quiet stars + 100 planet hosts). Here's what success looks like:

### 7.1 Completion Rate

- **Target:** ≥95% success (950+/1000)
- **Acceptable:** ≥90% (900+/1000)
- **Failure:** <90%

Some targets will fail due to missing data, archive issues, or insufficient observations. That's expected.

### 7.2 Feature Discrimination

If our features work, planet hosts should look DIFFERENT from quiet stars:

| Feature | Quiet Stars | Planet Hosts | Why |
|---------|-------------|--------------|-----|
| `stat_std` | Lower | Higher | Transits increase variance |
| `stat_skewness` | ~0 | Negative | Transits add dips (negative outliers) |
| `transit_bls_power` | Low/NULL | High | Planet hosts have detectable transits |
| `transit_n_transits` | 0/NULL | >0 | Planet hosts have actual transits |
| `freq_dominant_power` | Lower | Higher | Transits create periodicity |
| `transit_physically_plausible` | N/A | ~1.0 | Real planets pass the size check |
| `transit_odd_even_consistent` | N/A | ~1.0 | Real planets aren't EBs |

### 7.3 Validation SQL Queries

After the run completes, check results in Supabase:

```sql
-- Check completion rate
SELECT COUNT(*) as total,
       COUNT(CASE WHEN stat_mean IS NOT NULL THEN 1 END) as successful
FROM features;

-- Compare quiet vs planet hosts
SELECT
  CASE WHEN target_id LIKE 'Kepler-%' THEN 'planet_host' ELSE 'quiet_star' END as type,
  AVG(stat_std) as avg_variability,
  AVG(transit_bls_power) as avg_transit_power,
  COUNT(*) as n_targets
FROM features
GROUP BY type;

-- Check physical plausibility
SELECT transit_physically_plausible, COUNT(*)
FROM features
WHERE transit_physically_plausible IS NOT NULL
GROUP BY transit_physically_plausible;
```

---

## 8. Running the Pipeline

### 8.1 Environment Setup

```bash
# Clone repository
git clone https://github.com/yourusername/kepler-lightcurve-scraper.git
cd kepler-lightcurve-scraper

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# OR: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 8.2 Database Setup (Supabase)

1. Create a Supabase project at https://supabase.com
2. Run the schema scripts in SQL Editor:
   - `scripts/add_metadata_columns.sql`
   - `scripts/add_scientific_validation_columns.sql`
3. Create `.env` file:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   ```

### 8.3 Fetch Target Lists

```bash
python scripts/fetch_quiet_stars.py      # 900 quiet stars (80% Sun-like, 20% M-Dwarf)
python scripts/fetch_planet_hosts.py     # 100 confirmed planet hosts
```

### 8.4 Run Validation

```bash
python scripts/test_validation_1000.py   # ~10-15 hours
```

### 8.5 Save Provenance

```bash
python scripts/save_provenance.py --run-type validation --n-targets 1000
```

---

## 9. Project Status and Next Steps

### Current Status (2026-01-15)

| Milestone | Status |
|-----------|--------|
| Core pipeline (62 features) | COMPLETE |
| PDCSAP flux implementation | COMPLETE |
| Rolling Band filtering | COMPLETE |
| M-Dwarf representation (20%) | COMPLETE |
| Physical plausibility check | COMPLETE |
| Odd-even transit consistency | COMPLETE |
| Instrumental alias detection | COMPLETE |
| Provenance tracking | COMPLETE |
| 1000-target validation | IN PROGRESS |

### Next Steps

1. **Complete validation run** — Verify features discriminate populations
2. **Statistical analysis** — Compare feature distributions, calculate effect sizes
3. **Anomaly detection** — Find quiet stars with planet-like features (potential discoveries)
4. **Scale to full catalog** — Process all ~199,000 Kepler targets
5. **Machine learning** — Train classifiers on validated feature set
6. **Publication** — Document methodology and any discoveries

---

## 10. References

1. **Jenkins, J. M., et al. (2010).** "Overview of the Kepler Science Processing Pipeline." *ApJ Letters*, 713, L87. — The original Kepler pipeline paper.

2. **Stumpe, M. C., et al. (2012).** "Kepler Presearch Data Conditioning I—Architecture and Algorithms for Error Correction in Kepler Light Curves." *PASP*, 124, 985. — Why PDCSAP is better than SAP.

3. **Van Cleve, J. E., & Caldwell, D. A. (2016).** "Kepler Instrument Handbook." *KSCI-19033-002*. — Technical details on quality flags including Rolling Band.

4. **Fortney, J. J., Marley, M. S., & Barnes, J. W. (2007).** "Planetary Radii across Five Orders of Magnitude in Mass and Stellar Insolation." *ApJ*, 659, 1661. — Why planets max out at ~2 R_Jupiter.

5. **NASA Exoplanet Archive.** https://exoplanetarchive.ipac.caltech.edu/ — Source for target selection and stellar parameters.

6. **Lightkurve Collaboration (2018).** "Lightkurve: Kepler and TESS time series analysis in Python." *Astrophysics Source Code Library*, ascl:1812.013.

---

## Citation

```bibtex
@software{xenoscan2026,
  title = {XENOSCAN: Kepler Light Curve Feature Extraction Pipeline},
  author = {{XENOSCAN Collaboration}},
  year = {2026},
  url = {https://github.com/yourusername/kepler-lightcurve-scraper}
}
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

This work uses data from the Kepler mission, funded by NASA's Science Mission Directorate. Data accessed via the Mikulski Archive for Space Telescopes (MAST).

We thank the Lightkurve, Astropy, and NASA Exoplanet Archive teams for their excellent tools and data services.

---

*Last updated: 2026-01-15 — Validation run in progress*
