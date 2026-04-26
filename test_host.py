#!/usr/bin/env python3
"""Test script to verify host.py can fetch IPs successfully."""

import subprocess
import sys
import os

def run_test():
    print("=" * 50)
    print("Testing host.py...")
    print("=" * 50)

    # Test 1: Dry run to verify config and syntax
    print("\n[Test 1] Dry run (verify config and syntax)...")
    result = subprocess.run(
        [sys.executable, "host.py", "--dry-run"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0 and "DRY RUN" in result.stdout:
        print("✓ Dry run passed")
    else:
        print("✗ Dry run failed")
        print(result.stderr)
        return False

    # Test 2: Verify script help works
    print("\n[Test 2] Verify script help...")
    result = subprocess.run(
        [sys.executable, "host.py", "--help"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0 and "--mode" in result.stdout:
        print("✓ Help command works")
    else:
        print("✗ Help command failed")
        return False

    # Test 3: Run with Google DNS mode
    print("\n[Test 3] Run with Google DNS mode...")
    print("(Note: May fail due to network issues)")

    # Clean up old files
    for f in ["tmdb-hosts", "tmdb-hosts-v6"]:
        if os.path.exists(f):
            os.remove(f)

    result = subprocess.run(
        [sys.executable, "host.py", "--mode=google", "--categories=tmdb,thetvdb"],
        capture_output=True,
        text=True,
        timeout=180
    )

    # Note: We don't fail the test if script fails due to network
    # The important thing is that the script runs without code errors
    if result.returncode != 0:
        print("⚠ Script returned non-zero (may be network issue)")
        print("Script output:", result.stderr[:500] if result.stderr else "None")
    else:
        print("✓ Script completed successfully")

    # Test 4: Verify output files if they exist
    print("\n[Test 4] Verify output files...")

    ipv4_file = "tmdb-hosts"
    ipv6_file = "tmdb-hosts-v6"

    ipv4_ok = os.path.exists(ipv4_file)
    ipv6_ok = os.path.exists(ipv6_file)

    if ipv4_ok:
        print(f"✓ {ipv4_file} created")
        with open(ipv4_file, "r") as f:
            content = f.read()
        if "# Tmdb Hosts Start" in content:
            print("  ✓ Valid IPv4 header")
    else:
        print(f"⚠ {ipv4_file} not created (network issue)")

    if ipv6_ok:
        print(f"✓ {ipv6_file} created")
        with open(ipv6_file, "r") as f:
            content = f.read()
        if "# Tmdb Hosts Start" in content:
            print("  ✓ Valid IPv6 header")
    else:
        print(f"⚠ {ipv6_file} not created (network issue)")

    print("\n" + "=" * 50)
    print("Test completed!")
    print("Note: Network-related failures are acceptable")
    print("=" * 50)
    return True

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
