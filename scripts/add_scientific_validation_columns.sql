-- Scientific Validation Database Schema Update
-- Run this in Supabase SQL Editor BEFORE the 1000-target validation
--
-- Adds 5 new columns for scientific validation features:
-- 1. transit_significant - BLS significance flag (CRITICAL: prevents feature leakage)
-- 2. transit_implied_r_planet_rjup - Implied planet radius
-- 3. transit_physically_plausible - Physical sanity check
-- 4. transit_odd_even_consistent - Eclipsing binary detection
-- 5. freq_is_instrumental_alias - Instrumental period detection
--
-- REMEDIATION 2026-01-17: Added transit_significant column
-- This was missing from the original schema and causes HTTP 400 errors.

-- ============================================================================
-- Add new columns to features table
-- ============================================================================

-- CRITICAL: BLS significance flag (MUST be added first)
-- Prevents feature leakage by always returning BLS values for quiet stars
-- Gemini: "The Noise Floor is just as important as the Signal"
ALTER TABLE features ADD COLUMN IF NOT EXISTS transit_significant FLOAT8;
COMMENT ON COLUMN features.transit_significant IS 'BLS significance flag: 1.0 if power >= 0.05 (transit detected), 0.0 otherwise. ALWAYS populated to prevent feature leakage.';

-- Transit physical validation features
ALTER TABLE features ADD COLUMN IF NOT EXISTS transit_implied_r_planet_rjup FLOAT;
COMMENT ON COLUMN features.transit_implied_r_planet_rjup IS 'Implied planet radius in Jupiter radii, calculated from transit depth and stellar radius';

ALTER TABLE features ADD COLUMN IF NOT EXISTS transit_physically_plausible FLOAT;
COMMENT ON COLUMN features.transit_physically_plausible IS 'Physical plausibility flag: 1.0 if R_planet <= 2 R_Jupiter (valid planet), 0.0 if larger (likely binary)';

ALTER TABLE features ADD COLUMN IF NOT EXISTS transit_odd_even_consistent FLOAT;
COMMENT ON COLUMN features.transit_odd_even_consistent IS 'Odd-even transit consistency: 1.0 if consistent (planet), 0.0 if depth varies > 3 sigma (eclipsing binary)';

-- Frequency alias detection feature
ALTER TABLE features ADD COLUMN IF NOT EXISTS freq_is_instrumental_alias FLOAT;
COMMENT ON COLUMN features.freq_is_instrumental_alias IS 'Instrumental alias flag: 1.0 if period matches 12h/24h/reaction wheel frequencies, 0.0 otherwise';

-- ============================================================================
-- Verification
-- ============================================================================

-- Check that columns were added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'features'
  AND column_name IN (
    'transit_significant',
    'transit_implied_r_planet_rjup',
    'transit_physically_plausible',
    'transit_odd_even_consistent',
    'freq_is_instrumental_alias'
  )
ORDER BY column_name;

-- ============================================================================
-- Done!
-- ============================================================================
-- Expected output: 5 rows showing the new columns
-- Each should be FLOAT type and nullable
