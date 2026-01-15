#!/usr/bin/env python3
"""
Fetch 100 confirmed Kepler planet hosts for validation.

Purpose: Verify that stars with known planets show DIFFERENT features
than quiet stars (transits, different variability, etc.)
"""

import requests
import pandas as pd
from pathlib import Path

# NASA Exoplanet Archive TAP service
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

def fetch_planet_hosts(n_stars=100, output_file="data/known_planets_100.txt"):
    """
    Fetch Kepler stars with CONFIRMED planets.

    Selection criteria:
    - Discovered by Kepler mission
    - Has confirmed planet(s)
    - Has orbital period and radius data
    """

    print("Fetching confirmed Kepler planet hosts from NASA Exoplanet Archive...")
    print(f"Target: {n_stars} stars")
    print()

    # Query for confirmed Kepler planets using the ps (planetary systems) table
    # This table contains all confirmed exoplanets
    query = f"""
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
    from io import StringIO
    df = pd.read_csv(StringIO(response.text))

    print(f"Found {len(df)} confirmed planet entries")
    print()

    # Get unique host stars (some stars have multiple planets)
    unique_hosts = df['hostname'].unique()
    print(f"{len(unique_hosts)} unique host stars")
    print()

    # Get stats for each unique host
    host_stats = df.groupby('hostname').agg({
        'pl_name': 'count',  # number of planets
        'pl_orbper': ['min', 'max'],
        'pl_rade': ['min', 'max']
    }).reset_index()

    host_stats.columns = ['hostname', 'n_planets', 'period_min', 'period_max',
                          'prad_min', 'prad_max']

    print("Sample statistics:")
    print(f"  Stars with 1 planet: {(host_stats['n_planets'] == 1).sum()}")
    print(f"  Stars with 2+ planets: {(host_stats['n_planets'] >= 2).sum()}")
    print(f"  Period range: {host_stats['period_min'].min():.2f} - {host_stats['period_max'].max():.1f} days")
    print(f"  Planet radius range: {host_stats['prad_min'].min():.2f} - {host_stats['prad_max'].max():.1f} R_Earth")
    print()

    # Take first n_stars unique hosts
    # Filter to only Kepler targets (start with "Kepler-" or "K2-")
    kepler_hosts = [h for h in unique_hosts if h.startswith('Kepler-')]
    selected_hosts = kepler_hosts[:n_stars]

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
    print("First 10 targets:")
    for i, hostname in enumerate(selected_hosts[:10], 1):
        host_info = host_stats[host_stats['hostname'] == hostname].iloc[0]
        print(f"  {i}. {hostname} ({int(host_info['n_planets'])} planet{'s' if host_info['n_planets'] > 1 else ''})")

    return targets

if __name__ == "__main__":
    try:
        targets = fetch_planet_hosts(n_stars=100)
        print()
        print("=" * 80)
        print("SUCCESS")
        print("=" * 80)
        print(f"{len(targets)} planet host stars ready for validation")
        print()
        print("Next step:")
        print("  python scripts/test_validation_1000.py")
    except Exception as e:
        print()
        print("=" * 80)
        print("ERROR")
        print("=" * 80)
        print(f"{e}")
        import traceback
        traceback.print_exc()
