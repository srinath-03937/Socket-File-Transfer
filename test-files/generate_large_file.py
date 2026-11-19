"""
test-files/generate_large_file.py
==================================
Utility script to generate a large binary test file for stress-testing the
Multi-Threaded File Transfer System.

The file is filled with cryptographically random bytes (os.urandom) written
in 1 MB blocks, so it exercises the chunked streaming logic in both the client
and server.  Random bytes also resist compression, giving a more honest measure
of raw transfer throughput.

Usage:
    python generate_large_file.py

Output:
    test-files/largefile.bin   (SIZE_MB megabytes)

Adjust SIZE_MB below to create a larger/smaller file as needed.
"""

import os
import sys
import time

# ── Configuration ────────────────────────────────────────────────────────────

SIZE_MB    = 5          # Target file size in megabytes — change as needed.
BLOCK_SIZE = 1024 * 1024  # Write 1 MB at a time to keep memory usage flat.

# Output path is always relative to this script's directory (test-files/).
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "largefile.bin")


def generate_large_file(path: str, size_mb: int) -> None:
    """
    Write *size_mb* megabytes of random bytes to *path*, one MB at a time.

    Using os.urandom (backed by the OS CSPRNG) produces incompressible data,
    which gives a realistic benchmark of raw TCP transfer throughput.

    Parameters
    ----------
    path    : str — destination file path.
    size_mb : int — number of megabytes to write.
    """
    target_bytes = size_mb * 1024 * 1024
    written      = 0
    start        = time.time()

    print(f"Generating {size_mb} MB binary file → {path}")
    print(f"Writing in {BLOCK_SIZE // (1024 * 1024)} MB blocks ...")

    with open(path, "wb") as f:
        while written < target_bytes:
            remaining  = target_bytes - written
            block_size = min(BLOCK_SIZE, remaining)
            f.write(os.urandom(block_size))
            written   += block_size

            # Show a simple percentage progress in-place.
            pct = written / target_bytes * 100
            sys.stdout.write(f"\r  Progress: {pct:5.1f}%  ({written // (1024*1024)} / {size_mb} MB)")
            sys.stdout.flush()

    elapsed = time.time() - start
    size_on_disk = os.path.getsize(path)
    sys.stdout.write("\n")
    print(
        f"\n  Done!\n"
        f"  File      : {path}\n"
        f"  Size      : {size_on_disk / (1024 * 1024):.2f} MB\n"
        f"  Generated : {elapsed:.2f} s\n"
        f"\nYou can now upload this file with the client:\n"
        f"  Copy it to  client/files_to_send/  and use option 1 (Upload).\n"
        f"  Or provide the full path when the client prompts you.\n"
    )


if __name__ == "__main__":
    generate_large_file(OUTPUT_PATH, SIZE_MB)
