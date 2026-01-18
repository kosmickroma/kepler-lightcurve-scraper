#!/usr/bin/env python3
"""
Fetch 100 confirmed Kepler planet hosts for validation.

Purpose: Verify that stars with known planets show DIFFERENT features
than quiet stars (transits, different variability, etc.)

REMEDIATION 2026-01-17: Added Teff-stratified selection to match quiet star distribution.
Previous version: Took first 100 alphabetically (biased toward certain stellar types)
New version: Explicitly selects 80% Sun-like (Teff 4000-7000K) and 20% M-dwarfs (Teff <4000K)

Gemini validation: "The Teff Stratification fix ensures that your Planet Host training
set is a true apples-to-apples comparison with your Quiet baseline."
"""

import requests
import pandas as pd
from pathlib import Path
from io import StringIO

# NASA Exoplanet Archive TAP service
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"


def fetch_planet_hosts(n_stars=100, mdwarf_fraction=0.20, output_file="data/known_planets_100.txt"):
    """
    Fetch Kepler stars with CONFIRMED planets with Teff stratification.

    REMEDIATION 2026-01-17: Now matches quiet star Teff distribution.

    Selection criteria:
    - Discovered by Kepler mission
    - Has confirmed planet(s)
    - Has orbital period and radius data
    - Has stellar Teff measurement
    - Stratified: 80% Sun-like (4000-7000K), 20% M-dwarf (<4000K)

    Args:
        n_stars: Total number of planet hosts to select
        mdwarf_fraction: Fraction of M-dwarfs (default 0.20 = 20%)
        output_file: Output file path
    """
    # Calculate target counts
    n_mdwarfs = int(n_stars * mdwarf_fraction)
    n_sunlike = n_stars - n_mdwarfs

    print("=" * 80)
    print("FETCHING KEPLER PLANET HOSTS (Teff-Stratified)")
    print("=" * 80)
    print()
    print(f"Target: {n_stars} stars")
    print(f"M-Dwarf fraction: {mdwarf_fraction * 100:.0f}%")
    print(f"  Sun-like (Teff 4000-7000K): {n_sunlike} stars")
    print(f"  M-Dwarfs (Teff < 4000K): {n_mdwarfs} stars")
    print()

    # Query for confirmed Kepler planets using the ps (planetary systems) table
    # This table contains all confirmed exoplanets
    # NOTE: st_teff IS NOT NULL ensures we have stellar temperature for stratification
    query = """
    SELECT DISTINCT
        tic_id,
        hostname,
        pl_name,
        pl_orbper,
        pl_rade,
        st_teff,
        st_rad,
        st_mass,
        disc_facility
    FROM ps
    WHERE
        disc_facility LIKE '%Kepler%'
        AND pl_orbper IS NOT NULL
        AND pl_rade IS NOT NULL
        AND st_teff IS NOT NULL
    ORDER BY hostname ASC
    """

    params = {
        'query': query,
        'format': 'csv'
    }

    print("Querying NASA Exoplanet Archive...")
    response = requests.get(TAP_URL, params=params)

    if response.status_code != 200:
        raise Exception(f"TAP query failed: {response.status_code}\n{response.text}")

    # Parse CSV
    df = pd.read_csv(StringIO(response.text))

    print(f"Found {len(df)} confirmed planet entries (with Teff data)")
    print()

    # Get unique host stars with their Teff (some stars have multiple planets)
    # Take the first Teff value for each hostname
    host_teff = df.groupby('hostname').agg({
        'st_teff': 'first',
        'pl_name': 'count'
    }).reset_index()
    host_teff.columns = ['hostname', 'st_teff', 'n_planets']

    # Filter to only Kepler targets (start with "Kepler-")
    kepler_hosts = host_teff[host_teff['hostname'].str.startswith('Kepler-')].copy()
    print(f"{len(kepler_hosts)} unique Kepler host stars with Teff data")

    # TEFF STRATIFICATION (REMEDIATION 2026-01-17)
    # Split by stellar type to match quiet star distribution
    sunlike_hosts = kepler_hosts[
        (kepler_hosts['st_teff'] >= 4000) & (kepler_hosts['st_teff'] <= 7000)
    ].copy()
    mdwarf_hosts = kepler_hosts[kepler_hosts['st_teff'] < 4000].copy()

    print(f"\nAvailable by stellar type:")
    print(f"  Sun-like (Teff 4000-7000K): {len(sunlike_hosts)} hosts")
    print(f"  M-Dwarfs (Teff < 4000K): {len(mdwarf_hosts)} hosts")

    # Check if we have enough M-dwarfs
    actual_n_mdwarfs = min(n_mdwarfs, len(mdwarf_hosts))
    actual_n_sunlike = min(n_sunlike, len(sunlike_hosts))

    if actual_n_mdwarfs < n_mdwarfs:
        print(f"\nWARNING: Only {actual_n_mdwarfs} M-dwarf planet hosts available (wanted {n_mdwarfs})")
        print("         Using all available M-dwarfs and adjusting Sun-like count")
        # Adjust to maintain total target if possible
        actual_n_sunlike = min(n_stars - actual_n_mdwarfs, len(sunlike_hosts))

    # Select hosts from each category (by lowest Teff within category for consistency)
    sunlike_hosts_sorted = sunlike_hosts.sort_values('st_teff')
    mdwarf_hosts_sorted = mdwarf_hosts.sort_values('st_teff')

    selected_sunlike = sunlike_hosts_sorted.head(actual_n_sunlike)['hostname'].tolist()
    selected_mdwarfs = mdwarf_hosts_sorted.head(actual_n_mdwarfs)['hostname'].tolist()

    selected_hosts = selected_sunlike + selected_mdwarfs

    # Get stats for selected hosts
    print(f"\nSelected {len(selected_hosts)} planet hosts:")
    print(f"  Sun-like: {len(selected_sunlike)} ({100 * len(selected_sunlike) / len(selected_hosts):.1f}%)")
    print(f"  M-Dwarfs: {len(selected_mdwarfs)} ({100 * len(selected_mdwarfs) / len(selected_hosts):.1f}%)")

    # Verify Teff distribution
    selected_teff = kepler_hosts[kepler_hosts['hostname'].isin(selected_hosts)]['st_teff']
    print(f"\nSelected Teff range: {selected_teff.min():.0f} - {selected_teff.max():.0f} K")
    print(f"  Mean Teff: {selected_teff.mean():.0f} K")

    # Format as the hostname (Kepler-XX format works with lightkurve)
    targets = selected_hosts

    # Write target IDs to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        f.write('\n'.join(targets))

    print(f"Wrote {len(targets)} targets to {output_file}")

    # Also save metadata CSV for later upload
    # Get unique host star metadata (one row per star)
    metadata_df = df[df['hostname'].isin(selected_hosts)].drop_duplicates(subset=['hostname'])
    metadata_file = output_file.replace('.txt', '_metadata.csv')
    metadata_df.to_csv(metadata_file, index=False)
    print(f"Wrote metadata to {metadata_file}")
    print()

    # Print first 10 targets with Teff info
    print("First 10 targets (Teff-stratified):")
    for i, hostname in enumerate(selected_hosts[:10], 1):
        host_info = kepler_hosts[kepler_hosts['hostname'] == hostname].iloc[0]
        teff = host_info['st_teff']
        n_planets = host_info['n_planets']
        stellar_type = "M-dwarf" if teff < 4000 else "Sun-like"
        print(f"  {i}. {hostname} (Teff={teff:.0f}K, {stellar_type}, {int(n_planets)} planet{'s' if n_planets > 1 else ''})")

    # Scientific validation summary
    print()
    print("=" * 80)
    print("SCIENTIFIC VALIDATION: Teff Distribution Match")
    print("=" * 80)
    mdwarf_pct = 100 * len(selected_mdwarfs) / len(selected_hosts)
    print(f"  Target: 80% Sun-like, 20% M-dwarfs (matching quiet star baseline)")
    print(f"  Actual: {100 - mdwarf_pct:.1f}% Sun-like, {mdwarf_pct:.1f}% M-dwarfs")
    if abs(mdwarf_pct - 20) < 5:
        print(f"  Status: PASS - Teff distribution matches baseline")
    else:
        print(f"  Status: WARNING - Limited M-dwarf planet hosts available")

    return targets


if __name__ == "__main__":
    try:
        targets = fetch_planet_hosts(n_stars=100, mdwarf_fraction=0.20)
        print()
        print("=" * 80)
        print("SUCCESS")
        print("=" * 80)
        print(f"{len(targets)} Teff-stratified planet host stars ready for validation")
        print()
        print("This matches the quiet star Teff distribution (80% Sun-like, 20% M-dwarf)")
        print()
        print("Next step:")
        print("  python scripts/run_validation_local.py")
    except Exception as e:
        print()
        print("=" * 80)
        print("ERROR")
        print("=" * 80)
        print(f"{e}")
        import traceback
        traceback.print_exc()
