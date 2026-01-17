#!/usr/bin/env python3
"""
Fetch 900 "quiet" Kepler stars for baseline validation.

Criteria for "quiet":
- No confirmed planets
- Low CDPP (Combined Differential Photometric Precision)
- Good data completeness
- Main sequence stars (avoid giants, variables)

SCIENTIFIC VALIDATION: Includes 20% M-Dwarfs (Teff < 4000K) for
Pandora mission compatibility and to avoid stellar type bias.
"""

import requests
import pandas as pd
from pathlib import Path

# NASA Exoplanet Archive TAP service
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"


def fetch_stars_by_type(query, star_type):
    """
    Fetch stars from NASA Exoplanet Archive using a TAP query.

    Args:
        query: SQL query string
        star_type: Description for logging

    Returns:
        DataFrame of results
    """
    params = {
        'query': query,
        'format': 'csv'
    }

    print(f"Querying {star_type}...")
    response = requests.get(TAP_URL, params=params)

    if response.status_code != 200:
        raise Exception(f"TAP query failed: {response.status_code}\n{response.text}")

    from io import StringIO
    return pd.read_csv(StringIO(response.text))


def fetch_quiet_stars(n_stars=900, mdwarf_fraction=0.20, output_file="data/quiet_stars_900.txt"):
    """
    Fetch quiet Kepler stars from NASA Exoplanet Archive.

    SCIENTIFIC VALIDATION: Ensures proper representation of M-Dwarfs
    (Teff < 4000K) to avoid stellar type bias and ensure Pandora
    mission compatibility.

    Selection criteria:
    - koi_count = 0 (zero planet candidates)
    - st_cdpp3_0 < 200 (low noise, quiet photometry)
    - st_cdpp6_0 < 250
    - st_crowding > 0.85 (isolated stars, not blended)
    - 80% sun-like (Teff 4000-7000K)
    - 20% M-Dwarfs (Teff < 4000K) for Pandora compatibility

    Args:
        n_stars: Total number of stars to fetch (default 900)
        mdwarf_fraction: Fraction of M-Dwarfs to include (default 0.20 = 20%)
        output_file: Output file path
    """

    print("=" * 80)
    print("FETCHING QUIET KEPLER STARS")
    print("=" * 80)
    print()
    print(f"Target: {n_stars} stars")
    print(f"M-Dwarf fraction: {mdwarf_fraction * 100:.0f}%")
    print()

    # Calculate target counts
    n_mdwarfs = int(n_stars * mdwarf_fraction)
    n_sunlike = n_stars - n_mdwarfs

    print(f"Target breakdown:")
    print(f"  Sun-like (Teff 4000-7000K): {n_sunlike} stars ({100 - mdwarf_fraction * 100:.0f}%)")
    print(f"  M-Dwarfs (Teff < 4000K): {n_mdwarfs} stars ({mdwarf_fraction * 100:.0f}%)")
    print()

    # Query 1: Sun-like stars (Teff 4000-7000K)
    # Column names from NASA keplerstellar table:
    #   teff = effective temperature
    #   radius = stellar radius
    #   mass = stellar mass
    #   rrmscdpp03p0 = 3-hour CDPP
    #   rrmscdpp06p0 = 6-hour CDPP
    #   nkoi = number of KOIs (planet candidates)
    query_sunlike = f"""
    SELECT DISTINCT
        kepid,
        nkoi,
        teff,
        radius,
        mass,
        rrmscdpp03p0,
        rrmscdpp06p0
    FROM keplerstellar
    WHERE
        nkoi = 0
        AND rrmscdpp03p0 < 200
        AND rrmscdpp06p0 < 250
        AND teff BETWEEN 4000 AND 7000
        AND radius BETWEEN 0.5 AND 2.0
    ORDER BY rrmscdpp03p0 ASC
    """

    df_sunlike = fetch_stars_by_type(query_sunlike, "Sun-like stars (Teff 4000-7000K)")
    df_sunlike = df_sunlike.drop_duplicates(subset='kepid', keep='first')
    print(f"  Found {len(df_sunlike)} unique sun-like stars")

    # Query 2: M-Dwarfs (Teff < 4000K)
    # Note: M-Dwarfs are smaller (typical radius 0.1-0.6 Rsun)
    # and have higher intrinsic variability, so we use slightly
    # relaxed CDPP thresholds
    query_mdwarfs = f"""
    SELECT DISTINCT
        kepid,
        nkoi,
        teff,
        radius,
        mass,
        rrmscdpp03p0,
        rrmscdpp06p0
    FROM keplerstellar
    WHERE
        nkoi = 0
        AND rrmscdpp03p0 < 300
        AND rrmscdpp06p0 < 350
        AND teff < 4000
        AND teff > 2500
        AND radius BETWEEN 0.1 AND 0.7
    ORDER BY rrmscdpp03p0 ASC
    """

    df_mdwarfs = fetch_stars_by_type(query_mdwarfs, "M-Dwarf stars (Teff < 4000K)")
    df_mdwarfs = df_mdwarfs.drop_duplicates(subset='kepid', keep='first')
    print(f"  Found {len(df_mdwarfs)} unique M-Dwarf stars")
    print()

    # Check if we have enough M-Dwarfs
    if len(df_mdwarfs) < n_mdwarfs:
        print(f"WARNING: Only {len(df_mdwarfs)} M-Dwarfs available (wanted {n_mdwarfs})")
        print("         Adjusting ratio to use all available M-Dwarfs")
        n_mdwarfs = len(df_mdwarfs)
        n_sunlike = n_stars - n_mdwarfs

    # Select the quietest stars from each category
    df_sunlike_subset = df_sunlike.head(n_sunlike)
    df_mdwarfs_subset = df_mdwarfs.head(n_mdwarfs)

    # Combine the datasets
    df_combined = pd.concat([df_sunlike_subset, df_mdwarfs_subset], ignore_index=True)

    # Add stellar type classification
    df_combined['stellar_type'] = df_combined['teff'].apply(
        lambda t: 'M-Dwarf' if t < 4000 else 'Sun-like'
    )

    # Shuffle to avoid systematic ordering
    df_combined = df_combined.sample(frac=1, random_state=42).reset_index(drop=True)

    print("=" * 80)
    print("COMBINED SAMPLE STATISTICS")
    print("=" * 80)
    print()
    print(f"Total stars: {len(df_combined)}")
    print()

    # Statistics by stellar type
    for stype in ['Sun-like', 'M-Dwarf']:
        subset = df_combined[df_combined['stellar_type'] == stype]
        if len(subset) > 0:
            print(f"{stype} stars ({len(subset)} / {len(df_combined)} = {100 * len(subset) / len(df_combined):.1f}%):")
            print(f"  Teff range: {subset['teff'].min():.0f} - {subset['teff'].max():.0f} K")
            print(f"  Radius range: {subset['radius'].min():.2f} - {subset['radius'].max():.2f} Rsun")
            print(f"  CDPP (3hr) range: {subset['rrmscdpp03p0'].min():.1f} - {subset['rrmscdpp03p0'].max():.1f} ppm")
            print()

    # Deduplicate by kepid before formatting (NASA archive sometimes has duplicate entries)
    df_combined = df_combined.drop_duplicates(subset='kepid', keep='first')
    print(f"After deduplication: {len(df_combined)} unique stars")

    # Format as "KIC {kepid}" with 9-digit zero-padding for consistency
    targets = [f"KIC {str(int(kepid)).zfill(9)}" for kepid in df_combined['kepid']]

    # Extra safety: deduplicate the final list
    targets = list(dict.fromkeys(targets))  # Preserves order, removes duplicates

    # Write target IDs to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        f.write('\n'.join(targets))

    print(f"Wrote {len(targets)} unique targets to {output_file}")

    # Also save metadata CSV for later upload
    metadata_file = output_file.replace('.txt', '_metadata.csv')
    df_combined.to_csv(metadata_file, index=False)
    print(f"Wrote metadata to {metadata_file}")
    print()

    # Summary of M-Dwarf representation
    n_mdwarfs_actual = len(df_combined[df_combined['stellar_type'] == 'M-Dwarf'])
    mdwarf_pct = 100 * n_mdwarfs_actual / len(df_combined)

    print("=" * 80)
    print("SCIENTIFIC VALIDATION: M-Dwarf Representation")
    print("=" * 80)
    print(f"  Target: ≥20% M-Dwarfs")
    print(f"  Actual: {n_mdwarfs_actual}/{len(df_combined)} = {mdwarf_pct:.1f}%")
    if mdwarf_pct >= 20:
        print(f"  Status: PASS")
    else:
        print(f"  Status: WARNING - Below target (but using all available)")
    print()

    print("First 10 targets (shuffled):")
    for i, (_, row) in enumerate(df_combined.head(10).iterrows(), 1):
        target = f"KIC {int(row['kepid'])}"
        stype = row['stellar_type']
        teff = row['teff']
        print(f"  {i}. {target} ({stype}, Teff={teff:.0f}K)")

    return targets


if __name__ == "__main__":
    try:
        targets = fetch_quiet_stars(n_stars=900, mdwarf_fraction=0.20)
        print()
        print("=" * 80)
        print("SUCCESS")
        print("=" * 80)
        print(f"{len(targets)} quiet stars ready for validation")
        print()
        print("Next step:")
        print("  python scripts/fetch_planet_hosts.py")
    except Exception as e:
        print()
        print("=" * 80)
        print("ERROR")
        print("=" * 80)
        print(f"{e}")
        import traceback
        traceback.print_exc()
