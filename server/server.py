"""
server/server.py
================
Multi-threaded TCP file-transfer server.

Architecture overview:
  • Main thread: binds the listening socket, runs the accept() loop.
  • Per-client thread: spawned for every accepted connection; handles the full
    lifecycle of one client session (UPLOAD / DOWNLOAD / LIST / STATUS / EXIT).
  • Thread-safe client registry: a dict protected by threading.Lock so that
    STATUS queries from any thread see a consistent count.

The server never blocks on a single client — while one thread is streaming a
5 MB file, the main thread is free to accept() another connection and spawn a
new thread for it.  This is the central multi-threading requirement of the spec.

Author : B.Tech CSE Networking Project
"""

import json
import logging
import os
import sys
import threading
import time

# ── Make sure the shared module is importable when running server.py directly
#    (i.e., from inside the server/ directory) by adding the project root to sys.path.
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import socket

from shared.protocol import (
    BACKLOG,
    CHUNK_SIZE,
    HOST,
    PORT,
    CMD_DOWNLOAD,
    CMD_EXIT,
    CMD_LIST,
    CMD_STATUS,
    CMD_UPLOAD,
    recv_json,
    sanitize_filename,
    send_json,
    sha256_of_file,
)

# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORY & LOG SETUP
# ─────────────────────────────────────────────────────────────────────────────

RECEIVED_FILES_DIR = os.path.join(SCRIPT_DIR, "received_files")
LOGS_DIR           = os.path.join(PROJECT_ROOT, "logs")

os.makedirs(RECEIVED_FILES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Configure structured logging to both the console and a rotating log file.
log_path = os.path.join(LOGS_DIR, "server.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(threadName)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("server")


# ─────────────────────────────────────────────────────────────────────────────
# THREAD-SAFE CLIENT REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

# Maps client address tuple → connection start time.
# Protected by _registry_lock so concurrent threads can read/write safely.
_active_clients: dict = {}
_registry_lock  = threading.Lock()
_server_start_time = time.time()


def _register_client(addr: tuple) -> None:
    """Record a new client in the registry (called at thread start)."""
    with _registry_lock:
        _active_clients[addr] = time.time()
    logger.info("Client connected: %s:%d  |  total active: %d",
                addr[0], addr[1], len(_active_clients))


def _deregister_client(addr: tuple) -> None:
    """Remove a client from the registry (called when the thread exits)."""
    with _registry_lock:
        _active_clients.pop(addr, None)
    logger.info("Client disconnected: %s:%d  |  total active: %d",
                addr[0], addr[1], len(_active_clients))


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

def handle_upload(conn: socket.socket, addr: tuple) -> None:
    """
    Handle the UPLOAD command sequence as per Section 4.2 of the spec.

    Flow:
      1. Server → Client: READY_FOR_METADATA
      2. Client → Server: {filename, filesize, checksum}
      3. Server validates filename and disk space, responds READY or ERROR.
      4. Client streams raw bytes in CHUNK_SIZE blocks.
      5. Server verifies SHA-256 and responds UPLOAD_SUCCESS or CHECKSUM_MISMATCH.

    Parameters
    ----------
    conn : socket.socket — accepted client socket.
    addr : tuple         — (ip, port) of the client.
    """
    # Step 1 — tell the client we are ready to receive metadata.
    send_json(conn, {"status": "READY_FOR_METADATA"})

    # Step 2 — receive file metadata.
    try:
        meta = recv_json(conn)
    except (ConnectionError, json.JSONDecodeError) as exc:
        logger.error("Metadata receive failed from %s: %s", addr, exc)
        return

    raw_filename  = meta.get("filename", "")
    filesize      = meta.get("filesize", 0)
    client_chksum = meta.get("checksum", "")

    # Step 3a — sanitize the filename to prevent directory traversal.
    safe_name = sanitize_filename(raw_filename)
    if not safe_name:
        send_json(conn, {"status": "ERROR",
                          "message": f"Rejected filename: '{raw_filename}'"})
        logger.warning("Rejected unsafe filename '%s' from %s", raw_filename, addr)
        return

    # Step 3b — auto-rename if the file already exists (never silently overwrite).
    dest_path = os.path.join(RECEIVED_FILES_DIR, safe_name)
    if os.path.exists(dest_path):
        base, ext   = os.path.splitext(safe_name)
        counter     = 1
        while os.path.exists(dest_path):
            safe_name = f"{base}_{counter}{ext}"
            dest_path = os.path.join(RECEIVED_FILES_DIR, safe_name)
            counter  += 1
        logger.info("Duplicate filename — stored as '%s'", safe_name)

    # Step 3c — basic disk-space check (best-effort; statvfs not on Windows).
    try:
        stat = os.statvfs(RECEIVED_FILES_DIR)  # type: ignore[attr-defined]
        free = stat.f_bavail * stat.f_frsize
        if filesize > free:
            send_json(conn, {"status": "ERROR", "message": "Insufficient disk space."})
            return
    except AttributeError:
        # os.statvfs is not available on Windows — skip the check silently.
        pass

    send_json(conn, {
        "status": "READY",
        "message": f"Ready to receive '{safe_name}' ({filesize} bytes).",
        "stored_as": safe_name,
    })

    # Step 4 — receive raw file bytes chunk by chunk.
    logger.info("Receiving '%s' (%d bytes) from %s", safe_name, filesize, addr)
    bytes_received = 0
    transfer_start = time.time()

    try:
        with open(dest_path, "wb") as f:
            while bytes_received < filesize:
                remaining = filesize - bytes_received
                to_read   = min(CHUNK_SIZE, remaining)
                chunk     = conn.recv(to_read)
                if not chunk:
                    raise ConnectionError("Client disconnected mid-transfer.")
                f.write(chunk)
                bytes_received += len(chunk)
    except ConnectionError as exc:
        # Client vanished mid-transfer — rename the partial file so it doesn't
        # pollute received_files/ but is still available for debugging.
        partial_path = dest_path + ".partial"
        if os.path.exists(dest_path):
            os.rename(dest_path, partial_path)
        logger.warning("Upload aborted from %s: %s  |  partial saved as '%s'",
                       addr, exc, os.path.basename(partial_path))
        return
    except OSError as exc:
        logger.error("Filesystem error writing '%s': %s", dest_path, exc)
        send_json(conn, {"status": "ERROR", "message": "Server filesystem error."})
        return

    elapsed = time.time() - transfer_start

    # Step 5 — verify integrity with SHA-256.
    server_chksum = sha256_of_file(dest_path)
    if server_chksum == client_chksum:
        speed_mbs = (bytes_received / (1024 * 1024)) / max(elapsed, 0.001)
        send_json(conn, {
            "status": "UPLOAD_SUCCESS",
            "bytes": bytes_received,
            "stored_as": safe_name,
            "elapsed": round(elapsed, 3),
            "speed_mbs": round(speed_mbs, 3),
        })
        logger.info(
            "UPLOAD OK  '%s'  %d bytes  %.2f s  %.2f MB/s",
            safe_name, bytes_received, elapsed, speed_mbs,
        )
    else:
        send_json(conn, {"status": "CHECKSUM_MISMATCH",
                          "expected": client_chksum,
                          "received": server_chksum})
        logger.error("Checksum mismatch for '%s' from %s", safe_name, addr)


def handle_download(conn: socket.socket, addr: tuple, cmd: dict) -> None:
    """
    Handle the DOWNLOAD command sequence as per Section 4.3 of the spec.

    Flow:
      1. Server searches received_files/ for the requested filename.
      2. If not found: sends NOT_FOUND and returns.
      3. If found: sends {FOUND, filesize, checksum}.
      4. Client replies READY.
      5. Server streams raw bytes.

    Parameters
    ----------
    conn : socket.socket — accepted client socket.
    addr : tuple         — (ip, port) of the client.
    cmd  : dict          — the original command dict (contains "filename" key).
    """
    requested = cmd.get("filename", "").strip()
    safe_name = sanitize_filename(requested)
    if not safe_name:
        send_json(conn, {"status": "NOT_FOUND",
                          "message": "Invalid filename provided."})
        return

    filepath = os.path.join(RECEIVED_FILES_DIR, safe_name)
    if not os.path.isfile(filepath):
        send_json(conn, {"status": "NOT_FOUND",
                          "message": f"'{safe_name}' not found on server."})
        logger.info("DOWNLOAD request for '%s' from %s — NOT FOUND", safe_name, addr)
        return

    filesize = os.path.getsize(filepath)
    checksum = sha256_of_file(filepath)

    send_json(conn, {"status": "FOUND", "filesize": filesize, "checksum": checksum})

    # Wait for client's READY acknowledgement before streaming.
    try:
        ack = recv_json(conn)
    except ConnectionError as exc:
        logger.warning("Client %s disconnected before READY ack: %s", addr, exc)
        return

    if ack.get("status") != "READY":
        logger.warning("Expected READY from %s, got: %s", addr, ack)
        return

    logger.info("Sending '%s' (%d bytes) to %s", safe_name, filesize, addr)
    transfer_start = time.time()
    bytes_sent     = 0

    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.sendall(chunk)
                bytes_sent += len(chunk)
    except (OSError, ConnectionResetError) as exc:
        logger.error("Download error for '%s' to %s: %s", safe_name, addr, exc)
        return

    elapsed   = time.time() - transfer_start
    speed_mbs = (bytes_sent / (1024 * 1024)) / max(elapsed, 0.001)
    logger.info(
        "DOWNLOAD OK  '%s'  %d bytes  %.2f s  %.2f MB/s",
        safe_name, bytes_sent, elapsed, speed_mbs,
    )


def handle_list(conn: socket.socket, addr: tuple) -> None:
    """
    Handle the LIST command: enumerate received_files/ and send back the names,
    sizes, and modification times of every file stored on the server.

    Parameters
    ----------
    conn : socket.socket — accepted client socket.
    addr : tuple         — (ip, port) of the client.
    """
    files = []
    try:
        for entry in os.scandir(RECEIVED_FILES_DIR):
            if entry.is_file():
                stat = entry.stat()
                files.append({
                    "name": entry.name,
                    "size": stat.st_size,
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                    ),
                })
    except OSError as exc:
        logger.error("Cannot scan received_files/: %s", exc)
        send_json(conn, {"status": "ERROR", "message": "Cannot read file list."})
        return

    files.sort(key=lambda x: x["name"])
    send_json(conn, {"status": "OK", "files": files, "count": len(files)})
    logger.info("LIST served to %s  (%d files)", addr, len(files))


def handle_status(conn: socket.socket, addr: tuple) -> None:
    """
    Handle the STATUS command: report uptime, active client count, and
    the number of files stored on the server.

    Parameters
    ----------
    conn : socket.socket — accepted client socket.
    addr : tuple         — (ip, port) of the client.
    """
    with _registry_lock:
        active = len(_active_clients)

    uptime = time.time() - _server_start_time
    try:
        file_count = len([
            e for e in os.scandir(RECEIVED_FILES_DIR) if e.is_file()
        ])
    except OSError:
        file_count = -1

    send_json(conn, {
        "status": "OK",
        "uptime_seconds": round(uptime, 1),
        "active_clients": active,
        "files_stored": file_count,
        "host": HOST,
        "port": PORT,
    })
    logger.info("STATUS served to %s", addr)


# ─────────────────────────────────────────────────────────────────────────────
# PER-CLIENT THREAD ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr: tuple) -> None:
    """
    Entry point for each client-handling thread.

    Reads one command frame, dispatches to the appropriate handler, then closes
    the connection.  The client reconnects fresh for every operation — this
    stateless model is simpler and more robust for a demo, and is noted in the
    client code as a future enhancement point.

    Parameters
    ----------
    conn : socket.socket — the accepted socket for this client.
    addr : tuple         — (ip, port) of the remote client.
    """
    _register_client(addr)
    try:
        # Set a read timeout so a stalled client doesn't tie up a thread forever.
        conn.settimeout(120.0)

        try:
            cmd = recv_json(conn)
        except (ConnectionError, json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read command from %s: %s", addr, exc)
            return

        command = cmd.get("command", "").upper()
        logger.info("Command '%s' from %s", command, addr)

        if command == CMD_UPLOAD:
            handle_upload(conn, addr)
        elif command == CMD_DOWNLOAD:
            handle_download(conn, addr, cmd)
        elif command == CMD_LIST:
            handle_list(conn, addr)
        elif command == CMD_STATUS:
            handle_status(conn, addr)
        elif command == CMD_EXIT:
            send_json(conn, {"status": "BYE"})
            logger.info("Client %s sent EXIT — closing cleanly.", addr)
        else:
            send_json(conn, {"status": "ERROR",
                              "message": f"Unknown command '{command}'."})
            logger.warning("Unknown command '%s' from %s", command, addr)

    except OSError as exc:
        # Socket-level errors after the initial read (e.g., during transfers).
        logger.error("Socket error with %s: %s", addr, exc)
    finally:
        # Always close the socket and remove the client from the registry,
        # even if an unexpected exception slipped through.
        try:
            conn.close()
        except OSError:
            pass
        _deregister_client(addr)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — SERVER STARTUP
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Bind the listening socket, run the accept() loop, and spawn a new daemon
    thread per connected client.

    Daemon threads are used (daemon=True) so that when the main thread exits
    (e.g., on Ctrl+C), Python does not wait indefinitely for in-progress
    transfers to finish.  In production you would use non-daemon threads plus a
    threading.Event / join() with a timeout for a graceful drain.
    """
    # ── Create and configure the server socket ──────────────────────────────
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # SO_REUSEADDR lets us restart immediately after a crash without waiting for
    # the OS to release the port from the TIME_WAIT state (usually ~60 seconds).
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_sock.bind(("0.0.0.0", PORT))
    except OSError:
        # Provide a friendly, actionable error instead of a raw traceback.
        print(
            f"\n[ERROR] Port {PORT} is already in use.\n"
            "Close the other process or change SERVER_PORT in shared/protocol.py.\n"
        )
        sys.exit(1)

    server_sock.listen(BACKLOG)

    logger.info("=" * 60)
    logger.info("  Multi-Threaded File Transfer Server started")
    logger.info("  Listening on 0.0.0.0:%d  (connect via 127.0.0.1:%d)", PORT, PORT)
    logger.info("  Received files -> %s", RECEIVED_FILES_DIR)
    logger.info("  Press Ctrl+C to shut down.")
    logger.info("=" * 60)

    try:
        while True:
            try:
                conn, addr = server_sock.accept()
            except OSError:
                # accept() raises OSError when the server socket is closed
                # (e.g., after Ctrl+C sets server_sock to a closed state).
                break

            # Spawn a dedicated thread for this client so the main thread
            # returns to accept() immediately — the core of multi-threading.
            client_thread = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                name=f"Client-{addr[0]}:{addr[1]}",
                daemon=True,
            )
            client_thread.start()

    except KeyboardInterrupt:
        logger.info("\nCtrl+C received — shutting down server.")
    finally:
        with _registry_lock:
            active_count = len(_active_clients)
        logger.info(
            "Shutdown complete. %d client(s) may have been dropped.",
            active_count,
        )
        server_sock.close()
        logger.info("Server socket closed. Goodbye.")


if __name__ == "__main__":
    main()
