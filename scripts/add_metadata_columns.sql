-- ============================================================================
-- Add CDPP and Crowding Metadata to targets table
-- ============================================================================
-- Purpose: Store NASA catalog metadata for scientific validation
-- Run this in Supabase SQL Editor before validation run
-- ============================================================================

-- Add CDPP (Combined Differential Photometric Precision) columns
-- CDPP is the "gold standard" metric for photometric noise
ALTER TABLE targets
ADD COLUMN IF NOT EXISTS st_cdpp3_0 FLOAT,  -- CDPP at 3-hour timescale (ppm)
ADD COLUMN IF NOT EXISTS st_cdpp6_0 FLOAT,  -- CDPP at 6-hour timescale (ppm)
ADD COLUMN IF NOT EXISTS st_cdpp12_0 FLOAT; -- CDPP at 12-hour timescale (ppm)

-- Add Crowding metric
-- Crowding = fraction of flux in aperture from target star (vs neighbors)
-- Range: 0-1, where 1 = no crowding, <0.9 = significant crowding
ALTER TABLE targets
ADD COLUMN IF NOT EXISTS st_crowding FLOAT;

-- Add Stellar Parameters (useful for stratification)
ALTER TABLE targets
ADD COLUMN IF NOT EXISTS st_teff FLOAT,   -- Effective temperature (K)
ADD COLUMN IF NOT EXISTS st_rad FLOAT,    -- Stellar radius (Rsun)
ADD COLUMN IF NOT EXISTS st_mass FLOAT;   -- Stellar mass (Msun)

-- Add Planet Flag (for validation control groups)
ALTER TABLE targets
ADD COLUMN IF NOT EXISTS koi_count INTEGER DEFAULT 0;  -- Number of planet candidates

-- Add Centroid Features (for "fake quiet" detection)
-- Centroid jitter helps distinguish truly quiet stars from stars with tracking issues
ALTER TABLE features
ADD COLUMN IF NOT EXISTS centroid_x_std FLOAT,      -- Centroid X variance (pixels)
ADD COLUMN IF NOT EXISTS centroid_y_std FLOAT,      -- Centroid Y variance (pixels)
ADD COLUMN IF NOT EXISTS centroid_rms_motion FLOAT; -- RMS centroid motion (pixels)

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_targets_cdpp ON targets(st_cdpp3_0);
CREATE INDEX IF NOT EXISTS idx_targets_crowding ON targets(st_crowding);
CREATE INDEX IF NOT EXISTS idx_targets_koi_count ON targets(koi_count);

-- Add comments for documentation
COMMENT ON COLUMN targets.st_cdpp3_0 IS 'Combined Differential Photometric Precision at 3-hour timescale (ppm)';
COMMENT ON COLUMN targets.st_cdpp6_0 IS 'Combined Differential Photometric Precision at 6-hour timescale (ppm)';
COMMENT ON COLUMN targets.st_cdpp12_0 IS 'Combined Differential Photometric Precision at 12-hour timescale (ppm)';
COMMENT ON COLUMN targets.st_crowding IS 'Crowding metric: fraction of flux from target star (0-1)';
COMMENT ON COLUMN targets.st_teff IS 'Effective temperature (K)';
COMMENT ON COLUMN targets.st_rad IS 'Stellar radius (solar radii)';
COMMENT ON COLUMN targets.st_mass IS 'Stellar mass (solar masses)';
COMMENT ON COLUMN targets.koi_count IS 'Number of planet candidates (0 = quiet star)';
COMMENT ON COLUMN features.centroid_x_std IS 'Standard deviation of X centroid position (pixels)';
COMMENT ON COLUMN features.centroid_y_std IS 'Standard deviation of Y centroid position (pixels)';
COMMENT ON COLUMN features.centroid_rms_motion IS 'RMS centroid motion from mean position (pixels)';

-- ============================================================================
-- Validation Queries
-- ============================================================================

-- Query 1: Find quietest stars (CDPP < 20ppm)
-- SELECT target_id, st_cdpp3_0, st_crowding
-- FROM targets
-- WHERE st_cdpp3_0 < 20 AND st_crowding > 0.95
-- ORDER BY st_cdpp3_0 ASC
-- LIMIT 100;

-- Query 2: Stars with planets vs quiet stars
-- SELECT
--   koi_count > 0 AS has_planets,
--   COUNT(*) AS count,
--   AVG(st_cdpp3_0) AS avg_cdpp
-- FROM targets
-- GROUP BY koi_count > 0;

-- Query 3: Crowding analysis
-- SELECT
--   CASE
--     WHEN st_crowding > 0.95 THEN 'Low crowding'
--     WHEN st_crowding > 0.90 THEN 'Medium crowding'
--     ELSE 'High crowding'
--   END AS crowding_category,
--   COUNT(*) AS count
-- FROM targets
-- WHERE st_crowding IS NOT NULL
-- GROUP BY crowding_category;
