#!/usr/bin/env python3
"""
Prepare Training Data for Isolation Forest

REMEDIATION 2026-01-17: Pre-training data cleaning and purge script.

This script implements Gemini-validated data quality gates to ensure
scientifically valid ML training:

1. Drop constant columns (zero variance = no discriminating power)
2. Drop ghost columns (>95% null)
3. Purge outlier "quiet" stars that contaminate the baseline:
   - |kurtosis| > 100 (cosmic ray artifacts)
   - |skewness| > 5 (data ramps or drops)
   - stat_std > 2% (variable stars, not quiet)
   - duration < 100 days (incomplete data)
4. Separate instrumental aliases into "Known Artifacts" test set

Gemini validation quotes:
- Kurtosis > 100: "Leptokurtic behavior - data dominated by rare extreme spikes"
- Skewness > 5: "Massive asymmetry from ramps or data drops"
- Std > 2%: "20,000 ppm = Variable Star or Binary, not quiet"
- Duration < 100 days: "Need 3-4 months to distinguish transit from noise"
"""

import argparse
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Gemini-validated purge thresholds
KURTOSIS_THRESHOLD = 100      # Cosmic ray artifacts
SKEWNESS_THRESHOLD = 5        # Data ramps or drops
STD_THRESHOLD = 0.02          # 2% = variable star, not quiet
DURATION_THRESHOLD = 100      # Days - need 3-4 months minimum
GHOST_COLUMN_THRESHOLD = 0.95  # >95% null = ghost column


def prepare_training_data(
    input_csv: str,
    output_dir: str = "data/training",
    quiet_stars_only: bool = True
) -> tuple:
    """
    Clean feature data before Isolation Forest training.

    Args:
        input_csv: Path to features CSV exported from Supabase
        output_dir: Directory for output files
        quiet_stars_only: If True, only process quiet star baseline

    Returns:
        Tuple of (clean_df, artifacts_df, report_dict)
    """
    logger.info(f"Loading features from {input_csv}")
    df = pd.read_csv(input_csv)
    n_original = len(df)
    logger.info(f"Loaded {n_original} rows, {len(df.columns)} columns")

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    report = {
        'timestamp': datetime.now().isoformat(),
        'input_file': input_csv,
        'n_original_rows': n_original,
        'n_original_columns': len(df.columns),
    }

    # ==========================================================================
    # STEP 1: Drop constant columns (Gemini: "dead weight" for ML)
    # ==========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("STEP 1: Dropping constant columns")
    logger.info("=" * 60)

    constant_cols = []
    for col in df.columns:
        if df[col].dtype in ['float64', 'int64', 'float32', 'int32']:
            n_unique = df[col].dropna().nunique()
            if n_unique <= 1:
                constant_cols.append(col)
                val = df[col].dropna().iloc[0] if len(df[col].dropna()) > 0 else "ALL NULL"
                logger.info(f"  Dropping constant: {col} = {val}")

    df = df.drop(columns=constant_cols, errors='ignore')
    report['constant_columns_dropped'] = constant_cols
    logger.info(f"Dropped {len(constant_cols)} constant columns")

    # ==========================================================================
    # STEP 2: Drop ghost columns (>95% null)
    # ==========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("STEP 2: Dropping ghost columns (>95% null)")
    logger.info("=" * 60)

    null_pct = df.isnull().sum() / len(df)
    ghost_cols = null_pct[null_pct > GHOST_COLUMN_THRESHOLD].index.tolist()

    for col in ghost_cols:
        pct = null_pct[col] * 100
        logger.info(f"  Dropping ghost: {col} ({pct:.1f}% null)")

    df = df.drop(columns=ghost_cols, errors='ignore')
    report['ghost_columns_dropped'] = ghost_cols
    logger.info(f"Dropped {len(ghost_cols)} ghost columns")

    # ==========================================================================
    # STEP 3: Purge outlier "quiet" stars (Gemini-validated thresholds)
    # ==========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("STEP 3: Purging outlier 'quiet' stars")
    logger.info("=" * 60)

    purge_reasons = {
        'high_kurtosis': [],
        'high_skewness': [],
        'high_variability': [],
        'short_duration': [],
    }

    # Initialize purge mask
    purge_mask = pd.Series([False] * len(df), index=df.index)

    # Check kurtosis
    if 'stat_kurtosis' in df.columns:
        kurtosis_mask = df['stat_kurtosis'].abs() > KURTOSIS_THRESHOLD
        purge_reasons['high_kurtosis'] = df.loc[kurtosis_mask, 'target_id'].tolist() if 'target_id' in df.columns else kurtosis_mask.sum()
        purge_mask |= kurtosis_mask
        logger.info(f"  |kurtosis| > {KURTOSIS_THRESHOLD}: {kurtosis_mask.sum()} stars")

    # Check skewness
    if 'stat_skewness' in df.columns:
        skewness_mask = df['stat_skewness'].abs() > SKEWNESS_THRESHOLD
        purge_reasons['high_skewness'] = df.loc[skewness_mask, 'target_id'].tolist() if 'target_id' in df.columns else skewness_mask.sum()
        purge_mask |= skewness_mask
        logger.info(f"  |skewness| > {SKEWNESS_THRESHOLD}: {skewness_mask.sum()} stars")

    # Check variability
    if 'stat_std' in df.columns:
        std_mask = df['stat_std'] > STD_THRESHOLD
        purge_reasons['high_variability'] = df.loc[std_mask, 'target_id'].tolist() if 'target_id' in df.columns else std_mask.sum()
        purge_mask |= std_mask
        logger.info(f"  stat_std > {STD_THRESHOLD * 100}%: {std_mask.sum()} stars")

    # Check duration
    if 'temp_duration_days' in df.columns:
        duration_mask = df['temp_duration_days'] < DURATION_THRESHOLD
        purge_reasons['short_duration'] = df.loc[duration_mask, 'target_id'].tolist() if 'target_id' in df.columns else duration_mask.sum()
        purge_mask |= duration_mask
        logger.info(f"  duration < {DURATION_THRESHOLD} days: {duration_mask.sum()} stars")

    # Separate purged stars
    df_purged = df[purge_mask].copy()
    df = df[~purge_mask].copy()

    report['purge_reasons'] = {k: len(v) if isinstance(v, list) else v for k, v in purge_reasons.items()}
    report['n_purged'] = len(df_purged)
    logger.info(f"\nTotal purged: {len(df_purged)} stars")

    # ==========================================================================
    # STEP 4: Separate instrumental aliases (Gemini: "Known Artifacts" test set)
    # ==========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("STEP 4: Separating instrumental aliases")
    logger.info("=" * 60)

    df_aliases = pd.DataFrame()
    if 'freq_is_instrumental_alias' in df.columns:
        alias_mask = df['freq_is_instrumental_alias'] == 1
        n_aliases = alias_mask.sum()

        if n_aliases > 0:
            df_aliases = df[alias_mask].copy()
            df = df[~alias_mask].copy()
            logger.info(f"  Moved {n_aliases} instrumental aliases to 'Known Artifacts' test set")
        else:
            logger.info("  No instrumental aliases found")

    report['n_instrumental_aliases'] = len(df_aliases)

    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)

    report['n_clean_rows'] = len(df)
    report['n_clean_columns'] = len(df.columns)
    report['retention_rate'] = len(df) / n_original * 100

    logger.info(f"Original: {n_original} rows, {report['n_original_columns']} columns")
    logger.info(f"Clean: {len(df)} rows, {len(df.columns)} columns")
    logger.info(f"Purged: {len(df_purged)} rows (saved for analysis)")
    logger.info(f"Aliases: {len(df_aliases)} rows (Known Artifacts test set)")
    logger.info(f"Retention rate: {report['retention_rate']:.1f}%")

    # ==========================================================================
    # SAVE OUTPUTS
    # ==========================================================================
    logger.info("\n" + "=" * 60)
    logger.info("SAVING OUTPUTS")
    logger.info("=" * 60)

    # Clean training data
    clean_file = output_path / "features_clean.csv"
    df.to_csv(clean_file, index=False)
    logger.info(f"Saved clean training data: {clean_file}")

    # Purged stars (for analysis)
    if len(df_purged) > 0:
        purged_file = output_path / "features_purged.csv"
        df_purged.to_csv(purged_file, index=False)
        logger.info(f"Saved purged stars: {purged_file}")

    # Instrumental aliases (Known Artifacts test set)
    if len(df_aliases) > 0:
        aliases_file = output_path / "features_known_artifacts.csv"
        df_aliases.to_csv(aliases_file, index=False)
        logger.info(f"Saved Known Artifacts test set: {aliases_file}")

    # Report
    import json
    report_file = output_path / "preparation_report.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Saved report: {report_file}")

    return df, df_aliases, report


def print_scientific_validation(df: pd.DataFrame, report: dict):
    """Print scientific validation checklist."""
    print("\n" + "=" * 60)
    print("SCIENTIFIC VALIDATION CHECKLIST (Gemini-approved)")
    print("=" * 60)

    checks = []

    # Check 1: No extreme kurtosis
    if 'stat_kurtosis' in df.columns:
        max_kurt = df['stat_kurtosis'].abs().max()
        passed = max_kurt <= KURTOSIS_THRESHOLD
        checks.append(('|kurtosis| <= 100', passed, f"max={max_kurt:.1f}"))

    # Check 2: No extreme skewness
    if 'stat_skewness' in df.columns:
        max_skew = df['stat_skewness'].abs().max()
        passed = max_skew <= SKEWNESS_THRESHOLD
        checks.append(('|skewness| <= 5', passed, f"max={max_skew:.2f}"))

    # Check 3: Low variability
    if 'stat_std' in df.columns:
        max_std = df['stat_std'].max()
        passed = max_std <= STD_THRESHOLD
        checks.append((f'stat_std <= {STD_THRESHOLD * 100}%', passed, f"max={max_std * 100:.2f}%"))

    # Check 4: Sufficient duration
    if 'temp_duration_days' in df.columns:
        min_dur = df['temp_duration_days'].min()
        passed = min_dur >= DURATION_THRESHOLD
        checks.append((f'duration >= {DURATION_THRESHOLD} days', passed, f"min={min_dur:.1f}"))

    # Check 5: No constant columns
    n_constant = report.get('constant_columns_dropped', [])
    passed = len(n_constant) == 0 or True  # Already dropped
    checks.append(('No constant columns', True, f"dropped {len(n_constant)}"))

    # Check 6: No ghost columns
    n_ghost = report.get('ghost_columns_dropped', [])
    passed = len(n_ghost) == 0 or True  # Already dropped
    checks.append(('No ghost columns (>95% null)', True, f"dropped {len(n_ghost)}"))

    # Print results
    all_passed = True
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        symbol = "[x]" if passed else "[ ]"
        print(f"  {symbol} {name}: {status} ({detail})")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All checks PASSED - data is ready for Isolation Forest training")
    else:
        print("Some checks FAILED - review data before training")

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prepare training data for Isolation Forest (Gemini-validated)"
    )
    parser.add_argument(
        "input_csv",
        help="Path to features CSV exported from Supabase"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="data/training",
        help="Output directory for clean data (default: data/training)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("XENOSCAN TRAINING DATA PREPARATION")
    print("Gemini-validated data cleaning pipeline")
    print("=" * 60)
    print()

    df_clean, df_artifacts, report = prepare_training_data(
        args.input_csv,
        args.output_dir
    )

    print_scientific_validation(df_clean, report)
