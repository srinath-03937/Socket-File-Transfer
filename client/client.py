"""
client/client.py
================
Interactive CLI client for the Multi-Threaded File Transfer System.

Design decisions:
  • A fresh TCP connection is opened for each operation (UPLOAD, DOWNLOAD, etc.)
    and closed when that operation completes.  This "connect-per-operation" model
    is simpler and more resilient to server restarts than keeping a persistent
    connection — and it directly exercises the server's multi-threading, because
    each operation is a brand-new thread on the server side.
    FUTURE ENHANCEMENT: persist the connection across multiple operations by
    running a command loop without closing the socket between commands.

  • Progress bars are printed using sys.stdout.write('\r...') so the project has
    zero external dependencies.  If tqdm IS installed, it is used instead for a
    cleaner experience.

  • All errors are caught and displayed as friendly messages — no raw tracebacks
    reach the user.

Author : B.Tech CSE Networking Project
"""

import json
import logging
import os
import sys
import time

# ── Make sure the shared module is importable when running client.py directly.
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import socket

from shared.protocol import (
    CHUNK_SIZE,
    CMD_DOWNLOAD,
    CMD_EXIT,
    CMD_LIST,
    CMD_STATUS,
    CMD_UPLOAD,
    PORT,
    HOST,
    recv_json,
    send_json,
    sha256_of_file,
)

# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL DEPENDENCY: tqdm
# ─────────────────────────────────────────────────────────────────────────────

try:
    from tqdm import tqdm as _tqdm_class
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORIES & LOGGING
# ─────────────────────────────────────────────────────────────────────────────

DOWNLOADED_FILES_DIR = os.path.join(SCRIPT_DIR, "downloaded_files")
LOGS_DIR             = os.path.join(PROJECT_ROOT, "logs")

os.makedirs(DOWNLOADED_FILES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

log_path = os.path.join(LOGS_DIR, "client.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        # We do NOT add a StreamHandler here because the CLI menu uses
        # print() for UX output; mixing logging into stdout looks messy.
    ],
)
logger = logging.getLogger("client")


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESS BAR UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _format_size(num_bytes: float) -> str:
    """Return a human-readable byte size string (KB / MB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"


class StdlibProgressBar:
    """
    A minimal terminal progress bar implemented with sys.stdout.write('\r...')
    — no external libraries needed.

    Usage:
        bar = StdlibProgressBar(total_bytes, label="Uploading")
        bar.update(bytes_just_transferred)
        bar.close()
    """

    BAR_WIDTH = 30  # Width of the [=====>   ] block in characters.

    def __init__(self, total: int, label: str = "Transfer") -> None:
        self.total     = total
        self.label     = label
        self.current   = 0
        self.start     = time.time()
        self._last_print = 0.0

    def update(self, n: int) -> None:
        """
        Advance the progress bar by *n* bytes and redraw if enough time has
        passed (throttled to ~20 fps to avoid excessive I/O).
        """
        self.current += n
        now = time.time()
        # Throttle redraws: update at most every 0.05 s (~20 fps).
        if now - self._last_print < 0.05 and self.current < self.total:
            return
        self._last_print = now
        self._draw()

    def _draw(self) -> None:
        """Render one progress line and move the cursor to the beginning."""
        elapsed  = max(time.time() - self.start, 0.001)
        speed    = self.current / elapsed          # bytes/s
        pct      = self.current / max(self.total, 1)
        filled   = int(self.BAR_WIDTH * pct)
        bar      = "=" * filled + ">" + " " * (self.BAR_WIDTH - filled)
        line = (
            f"\r{self.label}: [{bar}] "
            f"{pct * 100:5.1f}%  "
            f"{_format_size(self.current)}/{_format_size(self.total)}  "
            f"{_format_size(speed)}/s   "
        )
        sys.stdout.write(line)
        sys.stdout.flush()

    def close(self) -> None:
        """Print a newline so the next output starts on a fresh line."""
        sys.stdout.write("\n")
        sys.stdout.flush()


def make_progress_bar(total: int, label: str):
    """
    Factory function: return a tqdm progress bar if tqdm is installed,
    otherwise return our stdlib fallback.

    Both objects expose the same .update(n) and .close() interface, making
    the calling code identical regardless of which implementation is used.
    """
    if TQDM_AVAILABLE:
        return _tqdm_class(
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=label,
            ncols=80,
        )
    return StdlibProgressBar(total=total, label=label)


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _connect(server_ip: str, server_port: int) -> socket.socket:
    """
    Create a fresh TCP socket and connect to the server.

    Raises ConnectionRefusedError / OSError if the server is not reachable,
    which the caller catches and converts to a friendly message.

    Parameters
    ----------
    server_ip   : str — e.g. "127.0.0.1"
    server_port : int — e.g. 5000

    Returns
    -------
    socket.socket — connected socket, ready for send/recv.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_ip, server_port))
    return sock


# ─────────────────────────────────────────────────────────────────────────────
# OPERATION: UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

def do_upload(server_ip: str, server_port: int) -> None:
    """
    Prompt the user for a local file path, then upload it to the server.

    Validates that the file exists locally before opening a socket, so the
    user gets an immediate error message rather than connecting and then failing.

    Parameters
    ----------
    server_ip   : str
    server_port : int
    """
    # ── Prompt and validate ──────────────────────────────────────────────────
    file_path = input("Enter path to file to upload: ").strip().strip('"')
    if not file_path:
        print("[!] No path entered.")
        return
    if not os.path.isfile(file_path):
        print(f"[!] File not found: {file_path!r}")
        logger.warning("Upload aborted — file not found: %s", file_path)
        return

    filename  = os.path.basename(file_path)
    filesize  = os.path.getsize(file_path)

    print(f"[*] Computing SHA-256 checksum of '{filename}' ...")
    checksum = sha256_of_file(file_path)
    print(f"[*] Checksum: {checksum[:16]}...  Size: {_format_size(filesize)}")

    # ── Connect and start the upload sequence ────────────────────────────────
    try:
        sock = _connect(server_ip, server_port)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"[!] Cannot connect to server at {server_ip}:{server_port} — {exc}")
        logger.error("Upload connect failed: %s", exc)
        return

    try:
        # Step 1 — send UPLOAD command.
        send_json(sock, {"command": CMD_UPLOAD})

        # Step 2 — wait for READY_FOR_METADATA.
        resp = recv_json(sock)
        if resp.get("status") != "READY_FOR_METADATA":
            print(f"[!] Unexpected server response: {resp}")
            return

        # Step 3 — send file metadata.
        send_json(sock, {
            "filename": filename,
            "filesize": filesize,
            "checksum": checksum,
        })

        # Step 4 — wait for server to confirm it's ready to receive bytes.
        resp = recv_json(sock)
        if resp.get("status") != "READY":
            print(f"[!] Server rejected the upload: {resp.get('message', resp)}")
            return

        stored_as = resp.get("stored_as", filename)
        if stored_as != filename:
            print(f"[*] Server will store file as '{stored_as}' (duplicate rename).")

        # Step 5 — stream the file in CHUNK_SIZE blocks with a progress bar.
        print(f"\n[*] Uploading '{filename}' ...")
        bar        = make_progress_bar(filesize, label="Uploading")
        start_time = time.time()

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                bar.update(len(chunk))

        bar.close()

        # Step 6 — wait for the server's final verdict.
        result  = recv_json(sock)
        elapsed = time.time() - start_time
        status  = result.get("status")

        if status == "UPLOAD_SUCCESS":
            speed_mbs = (filesize / (1024 * 1024)) / max(elapsed, 0.001)
            print(
                f"\n[✓] Upload successful!\n"
                f"    File stored as : {result.get('stored_as', stored_as)}\n"
                f"    Bytes          : {result.get('bytes', filesize):,}\n"
                f"    Elapsed        : {elapsed:.2f} s\n"
                f"    Speed          : {speed_mbs:.2f} MB/s\n"
                f"    Integrity      : SHA-256 verified ✓"
            )
            logger.info("Upload OK: %s → %s  %.2f s  %.2f MB/s",
                        filename, stored_as, elapsed, speed_mbs)
        elif status == "CHECKSUM_MISMATCH":
            print("[✗] Upload failed: checksum mismatch! The file may be corrupted.")
            logger.error("Checksum mismatch uploading %s", filename)
        else:
            print(f"[!] Unexpected server response: {result}")

    except ConnectionError as exc:
        print(f"[!] Connection lost during upload: {exc}")
        logger.error("Upload connection error: %s", exc)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[!] Upload error: {exc}")
        logger.error("Upload error: %s", exc)
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
# OPERATION: DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────

def do_download(server_ip: str, server_port: int) -> None:
    """
    Show the server's file list first, then download the user-selected file
    to client/downloaded_files/.

    Showing the list first prevents the user from guessing filenames, and
    helps discover auto-renamed files (e.g., test1_1.txt).

    Parameters
    ----------
    server_ip   : str
    server_port : int
    """
    # ── Step A: fetch the file list first ────────────────────────────────────
    print("[*] Fetching file list from server ...")
    try:
        sock = _connect(server_ip, server_port)
        send_json(sock, {"command": CMD_LIST})
        list_resp = recv_json(sock)
        sock.close()
    except (ConnectionRefusedError, OSError, ConnectionError) as exc:
        print(f"[!] Cannot reach server: {exc}")
        return

    files = list_resp.get("files", [])
    if not files:
        print("[*] No files available on the server yet.")
        return

    print(f"\n{'#':<5} {'Filename':<35} {'Size':>12}  {'Modified'}")
    print("─" * 70)
    for idx, f in enumerate(files, 1):
        print(f"{idx:<5} {f['name']:<35} {_format_size(f['size']):>12}  {f['modified']}")
    print()

    # ── Prompt for filename ───────────────────────────────────────────────────
    filename = input("Enter filename to download (exact name): ").strip()
    if not filename:
        print("[!] No filename entered.")
        return

    # ── Connect for download ──────────────────────────────────────────────────
    try:
        sock = _connect(server_ip, server_port)
    except (ConnectionRefusedError, OSError) as exc:
        print(f"[!] Cannot connect to server: {exc}")
        return

    try:
        send_json(sock, {"command": CMD_DOWNLOAD, "filename": filename})

        resp = recv_json(sock)
        status = resp.get("status")

        if status == "NOT_FOUND":
            print(f"[!] Server: {resp.get('message', 'File not found.')}")
            return

        if status != "FOUND":
            print(f"[!] Unexpected response: {resp}")
            return

        filesize      = resp["filesize"]
        server_chksum = resp["checksum"]

        print(f"\n[*] File found: '{filename}'  Size: {_format_size(filesize)}")
        dest_path = os.path.join(DOWNLOADED_FILES_DIR, filename)

        # Auto-rename locally if the file already exists.
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(filename)
            counter   = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(
                    DOWNLOADED_FILES_DIR, f"{base}_{counter}{ext}"
                )
                counter += 1
            print(f"[*] Local file already exists — saving as '{os.path.basename(dest_path)}'")

        # Tell the server we are ready to receive bytes.
        send_json(sock, {"status": "READY"})

        # Stream bytes with a progress bar.
        print(f"[*] Downloading '{filename}' ...")
        bar            = make_progress_bar(filesize, label="Downloading")
        start_time     = time.time()
        bytes_received = 0

        with open(dest_path, "wb") as f:
            while bytes_received < filesize:
                remaining = filesize - bytes_received
                chunk     = sock.recv(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ConnectionError("Server closed connection mid-transfer.")
                f.write(chunk)
                bytes_received += len(chunk)
                bar.update(len(chunk))

        bar.close()
        elapsed = time.time() - start_time

        # Verify integrity.
        local_chksum = sha256_of_file(dest_path)
        speed_mbs    = (bytes_received / (1024 * 1024)) / max(elapsed, 0.001)

        if local_chksum == server_chksum:
            print(
                f"\n[✓] Download successful!\n"
                f"    Saved to   : {dest_path}\n"
                f"    Bytes      : {bytes_received:,}\n"
                f"    Elapsed    : {elapsed:.2f} s\n"
                f"    Speed      : {speed_mbs:.2f} MB/s\n"
                f"    Integrity  : SHA-256 verified ✓"
            )
            logger.info("Download OK: %s  %.2f s  %.2f MB/s",
                        filename, elapsed, speed_mbs)
        else:
            print("[✗] Checksum mismatch! Downloaded file may be corrupted.")
            logger.error("Checksum mismatch downloading %s", filename)

    except ConnectionError as exc:
        print(f"[!] Connection lost during download: {exc}")
        logger.error("Download connection error: %s", exc)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[!] Download error: {exc}")
        logger.error("Download error: %s", exc)
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
# OPERATION: LIST
# ─────────────────────────────────────────────────────────────────────────────

def do_list(server_ip: str, server_port: int) -> None:
    """
    Request and display the list of files stored on the server.

    Parameters
    ----------
    server_ip   : str
    server_port : int
    """
    try:
        sock = _connect(server_ip, server_port)
        send_json(sock, {"command": CMD_LIST})
        resp = recv_json(sock)
        sock.close()
    except (ConnectionRefusedError, OSError, ConnectionError) as exc:
        print(f"[!] Cannot reach server: {exc}")
        return

    files = resp.get("files", [])
    if not files:
        print("[*] No files are stored on the server yet.")
        return

    print(f"\n{'#':<5} {'Filename':<35} {'Size':>12}  {'Modified'}")
    print("─" * 70)
    for idx, f in enumerate(files, 1):
        print(f"{idx:<5} {f['name']:<35} {_format_size(f['size']):>12}  {f['modified']}")
    print(f"\nTotal: {resp.get('count', len(files))} file(s)\n")


# ─────────────────────────────────────────────────────────────────────────────
# OPERATION: STATUS
# ─────────────────────────────────────────────────────────────────────────────

def do_status(server_ip: str, server_port: int) -> None:
    """
    Query and display the server's health / uptime / client count.

    Parameters
    ----------
    server_ip   : str
    server_port : int
    """
    try:
        sock = _connect(server_ip, server_port)
        send_json(sock, {"command": CMD_STATUS})
        resp = recv_json(sock)
        sock.close()
    except (ConnectionRefusedError, OSError, ConnectionError) as exc:
        print(f"[!] Cannot reach server: {exc}")
        return

    uptime   = resp.get("uptime_seconds", 0)
    hours    = int(uptime // 3600)
    minutes  = int((uptime % 3600) // 60)
    seconds  = int(uptime % 60)

    print(
        f"\n╔══════════════════════════════════════╗\n"
        f"║          SERVER STATUS               ║\n"
        f"╠══════════════════════════════════════╣\n"
        f"║  Host          : {resp.get('host', '?'):<20}║\n"
        f"║  Port          : {resp.get('port', '?'):<20}║\n"
        f"║  Uptime        : {hours:02d}h {minutes:02d}m {seconds:02d}s            ║\n"
        f"║  Active clients: {resp.get('active_clients', '?'):<20}║\n"
        f"║  Files stored  : {resp.get('files_stored', '?'):<20}║\n"
        f"╚══════════════════════════════════════╝\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# OPERATION: EXIT (clean close)
# ─────────────────────────────────────────────────────────────────────────────

def do_exit(server_ip: str, server_port: int) -> None:
    """
    Send an EXIT command to the server so it can close its side cleanly,
    then terminate the client process.

    Parameters
    ----------
    server_ip   : str
    server_port : int
    """
    try:
        sock = _connect(server_ip, server_port)
        send_json(sock, {"command": CMD_EXIT})
        recv_json(sock)   # consume the BYE response
        sock.close()
    except (ConnectionRefusedError, OSError, ConnectionError):
        pass  # server may already be down; that's fine for an exit
    print("[*] Goodbye!")
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE CLI MENU
# ─────────────────────────────────────────────────────────────────────────────

MENU = """
╔══════════════════════════════════════════════╗
║      Socket File Transfer Client v1.0       ║
╠══════════════════════════════════════════════╣
║  1. Upload a file                           ║
║  2. Download a file                         ║
║  3. List files on server                    ║
║  4. Server status                           ║
║  5. Exit                                    ║
╚══════════════════════════════════════════════╝
"""

MENU_ACTIONS = {
    "1": do_upload,
    "2": do_download,
    "3": do_list,
    "4": do_status,
    "5": do_exit,
}


def main() -> None:
    """
    Entry point: prompt for server address once, then loop the menu
    until the user chooses Exit.
    """
    print("\n" + "=" * 50)
    print("  Multi-Threaded File Transfer Client")
    print("=" * 50)

    server_ip   = input(f"Server IP   [default: {HOST}]: ").strip() or HOST
    server_port_str = input(f"Server Port [default: {PORT}]: ").strip()
    try:
        server_port = int(server_port_str) if server_port_str else PORT
    except ValueError:
        print(f"[!] Invalid port '{server_port_str}' — using default {PORT}.")
        server_port = PORT

    print(f"\n[*] Targeting server at {server_ip}:{server_port}\n")

    while True:
        print(MENU)
        choice = input("Choose an option [1-5]: ").strip()

        if choice not in MENU_ACTIONS:
            print("[!] Invalid choice. Please enter a number from 1 to 5.")
            continue

        action = MENU_ACTIONS[choice]
        try:
            action(server_ip, server_port)
        except KeyboardInterrupt:
            print("\n[*] Operation cancelled by user.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Client exited.")
