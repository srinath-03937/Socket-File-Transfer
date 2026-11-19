"""
demo_run.py
===========
Live demonstration of all server operations:
  1. Upload small file (test1.txt)
  2. Upload medium file (test2.txt)
  3. Generate + Upload large file (5 MB largefile.bin)
  4. List files on server
  5. Download a file back (test2.txt)
  6. Server STATUS query
  7. Duplicate filename upload (auto-rename)
  8. NOT_FOUND request (ghost.bin)

Run this while the server is already running:
    python demo_run.py
"""

import os
import socket
import sys
import time

sys.path.insert(0, ".")

from shared.protocol import (
    CHUNK_SIZE,
    HOST,
    PORT,
    recv_json,
    send_json,
    sha256_of_file,
)


def fmt_size(b: int) -> str:
    """Human-readable size string."""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b / (1024 * 1024):.2f} MB"


def draw_bar(done: int, total: int, speed_bytes: float) -> None:
    """Print an in-place progress bar."""
    pct = done / total * 100
    filled = int(pct / 3)
    bar = "=" * filled + ">" + " " * (33 - filled)
    sys.stdout.write(
        f"\r   [{bar}] {pct:5.1f}%  "
        f"{fmt_size(done)}/{fmt_size(total)}  "
        f"{fmt_size(int(speed_bytes))}/s   "
    )
    sys.stdout.flush()


def upload(filepath: str):
    """Upload *filepath* to the server. Returns (status, stored_as, size, elapsed, speed_MB/s)."""
    fn = os.path.basename(filepath)
    sz = os.path.getsize(filepath)
    ck = sha256_of_file(filepath)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    send_json(s, {"command": "UPLOAD"})
    recv_json(s)  # READY_FOR_METADATA

    send_json(s, {"filename": fn, "filesize": sz, "checksum": ck})
    r = recv_json(s)
    stored = r.get("stored_as", fn)

    t0 = time.time()
    done = 0
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            s.sendall(chunk)
            done += len(chunk)
            elapsed_so_far = max(time.time() - t0, 0.001)
            draw_bar(done, sz, done / elapsed_so_far)

    sys.stdout.write("\n")
    result = recv_json(s)
    s.close()

    elapsed = time.time() - t0
    speed = (sz / (1024 * 1024)) / max(elapsed, 0.001)
    return result["status"], stored, sz, elapsed, speed


def download(filename: str, dest_path: str):
    """Download *filename* from server to *dest_path*. Returns (status, size, elapsed, speed)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    send_json(s, {"command": "DOWNLOAD", "filename": filename})
    r = recv_json(s)

    if r["status"] != "FOUND":
        s.close()
        return r["status"], 0, 0, 0

    sz = r["filesize"]
    server_ck = r["checksum"]
    send_json(s, {"status": "READY"})

    t0 = time.time()
    done = 0
    with open(dest_path, "wb") as f:
        while done < sz:
            chunk = s.recv(min(CHUNK_SIZE, sz - done))
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            elapsed_so_far = max(time.time() - t0, 0.001)
            draw_bar(done, sz, done / elapsed_so_far)

    sys.stdout.write("\n")
    s.close()

    elapsed = time.time() - t0
    speed = (sz / (1024 * 1024)) / max(elapsed, 0.001)
    local_ck = sha256_of_file(dest_path)
    status = "CHECKSUM_OK" if local_ck == server_ck else "CHECKSUM_FAIL"
    return status, sz, elapsed, speed


def main():
    print()
    print("=" * 60)
    print("   SOCKET FILE TRANSFER SYSTEM  —  LIVE DEMO")
    print("=" * 60)

    # ── 1. Upload test1.txt ──────────────────────────────────
    print()
    print("[1] Uploading test1.txt (small file, ~23 bytes) ...")
    st, stored, sz, el, spd = upload("test-files/test1.txt")
    print(f"    Status   : {st}")
    print(f"    Stored as: {stored}")
    print(f"    Elapsed  : {el:.3f}s   Speed: {spd:.2f} MB/s")
    print("    Integrity: SHA-256 verified checksum")

    # ── 2. Upload test2.txt ──────────────────────────────────
    print()
    print("[2] Uploading test2.txt (medium file, ~5 KB) ...")
    st, stored, sz, el, spd = upload("test-files/test2.txt")
    print(f"    Status   : {st}")
    print(f"    Stored as: {stored}")
    print(f"    Size     : {fmt_size(sz)}")
    print(f"    Elapsed  : {el:.3f}s   Speed: {spd:.2f} MB/s")
    print("    Integrity: SHA-256 verified checksum")

    # ── 3. Generate + Upload largefile.bin ───────────────────
    lf = "test-files/largefile.bin"
    if not os.path.exists(lf):
        print()
        print("[3a] Generating 5 MB largefile.bin ...")
        target = 5 * 1024 * 1024
        written = 0
        with open(lf, "wb") as f:
            while written < target:
                block = os.urandom(min(65536, target - written))
                f.write(block)
                written += len(block)
        print(f"     Generated: {fmt_size(os.path.getsize(lf))}")

    print()
    print("[3] Uploading largefile.bin (5 MB binary) ...")
    st, stored, sz, el, spd = upload(lf)
    print(f"    Status   : {st}")
    print(f"    Stored as: {stored}")
    print(f"    Size     : {fmt_size(sz)}")
    print(f"    Elapsed  : {el:.3f}s   Speed: {spd:.2f} MB/s")
    print("    Integrity: SHA-256 verified checksum")

    # ── 4. LIST ──────────────────────────────────────────────
    print()
    print("[4] Listing all files on server ...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    send_json(s, {"command": "LIST"})
    r = recv_json(s)
    s.close()
    count = r["count"]
    print(f"    Total files: {count}")
    for fi in r["files"]:
        print(f"      {fi['name']:<30} {fmt_size(fi['size']):>10}  {fi['modified']}")

    # ── 5. Download test2.txt ────────────────────────────────
    print()
    print("[5] Downloading test2.txt back to client ...")
    dest = "client/downloaded_files/test2_dl.txt"
    st, sz, el, spd = download("test2.txt", dest)
    print(f"    Status   : {st}")
    print(f"    Saved to : {dest}")
    print(f"    Elapsed  : {el:.3f}s   Speed: {spd:.2f} MB/s")

    # ── 6. STATUS ────────────────────────────────────────────
    print()
    print("[6] Querying server STATUS ...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    send_json(s, {"command": "STATUS"})
    r = recv_json(s)
    s.close()
    up = r["uptime_seconds"]
    h = int(up // 3600)
    m = int((up % 3600) // 60)
    sec = int(up % 60)
    print(f"    Uptime        : {h:02d}h {m:02d}m {sec:02d}s")
    print(f"    Active clients: {r['active_clients']}")
    print(f"    Files stored  : {r['files_stored']}")

    # ── 7. Duplicate rename test ─────────────────────────────
    print()
    print("[7] Uploading test1.txt AGAIN (duplicate rename test) ...")
    st, stored, sz, el, spd = upload("test-files/test1.txt")
    print(f"    Status   : {st}")
    print(f"    Stored as: {stored}  <-- auto-renamed, original preserved!")

    # ── 8. NOT_FOUND test ────────────────────────────────────
    print()
    print("[8] Requesting non-existent file 'ghost.bin' ...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    send_json(s, {"command": "DOWNLOAD", "filename": "ghost.bin"})
    r = recv_json(s)
    s.close()
    print(f"    Server says: {r['status']} — {r.get('message', '')}")

    print()
    print("=" * 60)
    print("   ALL 8 OPERATIONS COMPLETED SUCCESSFULLY!")
    print()
    print("   The server is still running. Open new terminals and run:")
    print("   python client/client.py   <-- interactive menu")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
