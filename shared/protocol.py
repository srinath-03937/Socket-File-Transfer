"""
shared/protocol.py
==================
Centralized protocol constants and shared helper utilities for the
Socket-Based Multi-Threaded File Transfer System.

Both server.py and client.py import from this module so every
configurable value lives in exactly one place, keeping both sides
in sync automatically.

Author : B.Tech CSE Networking Project
Purpose: Educational demonstration of TCP/IP socket programming,
         length-prefixed framing, and SHA-256 integrity verification.
"""

import hashlib
import json
import os
import struct

# ─────────────────────────────────────────────────────────────────────────────
# NETWORK CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

HOST = "127.0.0.1"        # Loopback address — keeps everything on one machine.
                           # Change to "0.0.0.0" on the server side to allow
                           # remote connections (handled in server.py).
PORT = 5000               # Well above 1024 so no root/admin privileges needed.
BACKLOG = 5               # Max pending connections queued by the OS before
                           # accept() is called. Fine for demo workloads.
CHUNK_SIZE = 1024          # File data is streamed in 1 KB chunks.
                           # Larger chunks (e.g., 65536) speed up LAN transfers;
                           # 1024 is readable and matches the project spec exactly.

# ─────────────────────────────────────────────────────────────────────────────
# FRAMING CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Every JSON control message is preceded by a 4-byte big-endian integer that
# tells the receiver exactly how many bytes to read for the payload.
# This "length-prefix framing" is necessary because TCP is a *stream* protocol:
# it guarantees ordered byte delivery but does NOT preserve message boundaries.
# Without framing, two back-to-back sends may arrive as one chunk, or a single
# send may arrive in multiple recv() calls.
HEADER_FORMAT = ">I"      # '>' = big-endian, 'I' = unsigned 32-bit int
HEADER_SIZE   = struct.calcsize(HEADER_FORMAT)   # Always 4 bytes


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

CMD_UPLOAD   = "UPLOAD"
CMD_DOWNLOAD = "DOWNLOAD"
CMD_LIST     = "LIST"
CMD_STATUS   = "STATUS"
CMD_EXIT     = "EXIT"

# ─────────────────────────────────────────────────────────────────────────────
# FRAMING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def send_json(sock, payload: dict) -> None:
    """
    Serialise *payload* to UTF-8 JSON, prepend a 4-byte length header, and
    send the whole thing over *sock* in a single call to sock.sendall().

    Using sendall() (not send()) ensures the OS flushes every byte even if the
    kernel buffer is momentarily full — critical for correctness on slow paths.

    Parameters
    ----------
    sock    : socket.socket — an already-connected TCP socket.
    payload : dict          — any JSON-serialisable Python dictionary.

    Raises
    ------
    OSError            — if the socket is broken or the peer closed it.
    TypeError          — if *payload* contains non-serialisable objects.
    """
    encoded = json.dumps(payload).encode("utf-8")
    # Pack the length as a 4-byte big-endian unsigned int, then append payload.
    header = struct.pack(HEADER_FORMAT, len(encoded))
    sock.sendall(header + encoded)


def recv_json(sock) -> dict:
    """
    Block until a complete length-prefixed JSON frame arrives on *sock*,
    then decode and return it as a Python dict.

    The function first reads exactly HEADER_SIZE (4) bytes to learn the
    payload length, then reads exactly that many bytes for the JSON body.
    This guarantees we never read into the *next* message or block waiting
    for data that belongs to a different frame.

    Parameters
    ----------
    sock : socket.socket — an already-connected TCP socket.

    Returns
    -------
    dict — the decoded JSON object.

    Raises
    ------
    ConnectionError     — if the socket closes before a full frame arrives
                          (peer crashed / disconnected mid-transfer).
    json.JSONDecodeError — if the payload is not valid JSON (should never
                          happen in normal operation, but caught upstream).
    """
    # ── Step 1: read the 4-byte length header ──────────────────────────────
    raw_header = _recv_exact(sock, HEADER_SIZE)
    if raw_header is None:
        raise ConnectionError("Connection closed while reading message header.")

    (msg_len,) = struct.unpack(HEADER_FORMAT, raw_header)

    # ── Step 2: read exactly msg_len bytes of JSON payload ─────────────────
    raw_payload = _recv_exact(sock, msg_len)
    if raw_payload is None:
        raise ConnectionError("Connection closed while reading message body.")

    return json.loads(raw_payload.decode("utf-8"))


def _recv_exact(sock, num_bytes: int):
    """
    Read *num_bytes* bytes from *sock*, reassembling across multiple recv()
    calls if the OS delivers fewer bytes than requested (very common on
    loopback and absolutely expected on a real network).

    Returns None if the connection is closed before all bytes arrive
    (so callers can raise a descriptive ConnectionError instead of crashing
    on an unexpected empty bytes object).

    Parameters
    ----------
    sock      : socket.socket
    num_bytes : int — exact number of bytes to collect

    Returns
    -------
    bytes | None
    """
    buf = bytearray()
    while len(buf) < num_bytes:
        chunk = sock.recv(num_bytes - len(buf))
        if not chunk:
            # recv() returning empty bytes means the peer closed the connection.
            return None
        buf.extend(chunk)
    return bytes(buf)


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sha256_of_file(filepath: str) -> str:
    """
    Compute the SHA-256 digest of the file at *filepath* by reading it in
    CHUNK_SIZE blocks, avoiding loading the whole file into memory.

    SHA-256 is used (not MD5) because it is collision-resistant and is the
    modern standard for file integrity checks.  The digest is returned as a
    lowercase hex string (64 characters) suitable for JSON embedding.

    Parameters
    ----------
    filepath : str — absolute or relative path to the file.

    Returns
    -------
    str — 64-character lowercase hex digest.

    Raises
    ------
    FileNotFoundError — if *filepath* does not exist.
    OSError           — on any other I/O error.
    """
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            block = f.read(CHUNK_SIZE)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """
    Strip any directory components from *name* and reject filenames that
    could cause path-traversal attacks (e.g., '../../etc/passwd').

    This is a critical security measure: without it, a malicious client could
    upload a file with a path like '../server.py' and overwrite server code.

    Rules applied:
      1. Take only the final path component (os.path.basename).
      2. Replace any remaining path separators ('/', '\\') with underscores.
      3. Strip leading dots and spaces that hide files on Unix.
      4. Reject empty filenames (return None to signal rejection).

    Parameters
    ----------
    name : str — raw filename string received from the client.

    Returns
    -------
    str  — safe filename suitable for use directly under received_files/.
    None — if the name is empty or unacceptably dangerous after stripping.
    """
    # os.path.basename handles both '/' and '\\' separators.
    safe = os.path.basename(name)
    # Replace any stray separators that basename might not have caught on the
    # non-native OS (e.g., running the server on Linux, client sends Windows path).
    safe = safe.replace("/", "_").replace("\\", "_")
    # Disallow names that start with '..' explicitly.
    if safe.startswith(".."):
        return None
    # Strip surrounding whitespace and leading dots.
    safe = safe.strip().lstrip(".")
    if not safe:
        return None
    return safe
