-- XENOSCAN Database Cleanup Script
-- Date: 2026-01-16
-- Purpose: Fix duplicate entries, add ground truth columns, clean test data
--
-- INSTRUCTIONS:
-- 1. Open Supabase Dashboard → SQL Editor
-- 2. Run each section separately and verify before proceeding
-- 3. Keep this order - some steps depend on previous ones

-- ============================================================
-- STEP 1: Check current state (READ ONLY - just for reference)
-- ============================================================

-- Count current rows
SELECT 'targets' as table_name, COUNT(*) as row_count FROM targets
UNION ALL
SELECT 'features' as table_name, COUNT(*) as row_count FROM features;

-- Check for duplicates
SELECT
    LPAD(REGEXP_REPLACE(target_id, '[^0-9]', '', 'g'), 9, '0') as normalized_kic,
    COUNT(*) as occurrences
FROM targets
WHERE target_id LIKE 'KIC %'
GROUP BY normalized_kic
HAVING COUNT(*) > 1
LIMIT 10;

-- ============================================================
-- STEP 2: Remove old Kepler- test entries
-- ============================================================

-- Delete from features first (due to foreign key)
DELETE FROM features WHERE target_id LIKE 'Kepler-%';

-- Then delete from targets
DELETE FROM targets WHERE target_id LIKE 'Kepler-%';

-- Verify deletion
SELECT COUNT(*) as remaining_kepler_entries
FROM targets
WHERE target_id LIKE 'Kepler-%';
-- Should be 0

-- ============================================================
-- STEP 3: Add ground truth columns
-- ============================================================

-- Add is_anomaly column (ground truth label)
ALTER TABLE targets ADD COLUMN IF NOT EXISTS is_anomaly BOOLEAN DEFAULT NULL;

-- Add flag_reason column (for flagging outliers, etc.)
ALTER TABLE targets ADD COLUMN IF NOT EXISTS flag_reason TEXT DEFAULT NULL;

-- ============================================================
-- STEP 4: Mark all existing KIC entries as quiet stars
-- ============================================================

UPDATE targets
SET is_anomaly = FALSE
WHERE target_id LIKE 'KIC %'
  AND is_anomaly IS NULL;

-- Verify
SELECT is_anomaly, COUNT(*) as count
FROM targets
GROUP BY is_anomaly;

-- ============================================================
-- STEP 5: Flag high-variability outliers
-- ============================================================

-- These 12 stars have stat_std > 0.03 (vs median 0.00015)
-- They may be eclipsing binaries, flare stars, or mislabeled

UPDATE targets t
SET flag_reason = 'high_variability'
WHERE t.target_id IN (
    SELECT f.target_id
    FROM features f
    WHERE f.stat_std > 0.03
);

-- Verify flagged targets
SELECT target_id, flag_reason
FROM targets
WHERE flag_reason IS NOT NULL;

-- ============================================================
-- STEP 6: Deduplicate entries (keep zero-padded versions)
-- ============================================================

-- The issue: Same star uploaded as both "KIC 7584294" and "KIC 007584294"
-- Strategy: Keep the zero-padded version for ID consistency
--
-- NOTE: Non-padded versions have 48/63 features, padded have 38/63.
-- The 38/63 count is CORRECT for quiet stars because:
--   - Transit features (9) should be NULL (no transits in quiet stars)
--   - Centroid features (4) may not be available
--   - Some residual/temporal features require specific conditions
-- The 48/63 may have had bugs filling in values that should be NULL.

-- First, find the duplicates to delete from features
-- These are the non-padded versions where a padded version exists
DELETE FROM features
WHERE target_id IN (
    SELECT target_id
    FROM features
    WHERE target_id LIKE 'KIC %'
    AND LENGTH(REGEXP_REPLACE(target_id, 'KIC ', '')) < 9
    AND EXISTS (
        SELECT 1 FROM features f2
        WHERE f2.target_id = 'KIC ' || LPAD(REGEXP_REPLACE(features.target_id, 'KIC ', ''), 9, '0')
    )
);

-- Then delete from targets
DELETE FROM targets
WHERE target_id IN (
    SELECT target_id
    FROM targets
    WHERE target_id LIKE 'KIC %'
    AND LENGTH(REGEXP_REPLACE(target_id, 'KIC ', '')) < 9
    AND EXISTS (
        SELECT 1 FROM targets t2
        WHERE t2.target_id = 'KIC ' || LPAD(REGEXP_REPLACE(targets.target_id, 'KIC ', ''), 9, '0')
    )
);

-- ============================================================
-- STEP 7: Verify final state
-- ============================================================

-- Count final rows
SELECT 'targets' as table_name, COUNT(*) as row_count FROM targets
UNION ALL
SELECT 'features' as table_name, COUNT(*) as row_count FROM features;
-- Expected: ~486 rows in each table

-- Check no remaining duplicates
SELECT
    LPAD(REGEXP_REPLACE(target_id, '[^0-9]', '', 'g'), 9, '0') as normalized_kic,
    COUNT(*) as occurrences
FROM targets
WHERE target_id LIKE 'KIC %'
GROUP BY normalized_kic
HAVING COUNT(*) > 1;
-- Should return 0 rows

-- Check ground truth distribution
SELECT
    is_anomaly,
    flag_reason,
    COUNT(*) as count
FROM targets
GROUP BY is_anomaly, flag_reason;
-- Expected: ~474 quiet stars (is_anomaly=FALSE, flag_reason=NULL)
--           ~12 flagged (is_anomaly=FALSE, flag_reason='high_variability')

-- Sample of standardized IDs
SELECT target_id
FROM targets
WHERE target_id LIKE 'KIC %'
ORDER BY target_id
LIMIT 5;
-- Should all be 9-digit padded: KIC 007584294, KIC 008694381, etc.

-- ============================================================
-- DONE! Database is now ready for:
-- 1. Processing 99 planet hosts with is_anomaly=TRUE
-- 2. Training Isolation Forest on quiet star baseline
-- ============================================================
