"""
dashboard/app.py
==============================
Clean, robust, user-friendly dashboard for Socket File Transfer System.
Supports local and multi-device LAN access across Wi-Fi networks.
"""

import collections
import io
import json
import logging
import mimetypes
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    jsonify,
    render_template_string,
    request,
    send_file,
    stream_with_context,
)

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT  = os.path.dirname(DASHBOARD_DIR)
sys.path.insert(0, PROJECT_ROOT)

from shared.protocol import (
    CHUNK_SIZE,
    HOST,
    PORT,
    recv_json,
    sanitize_filename,
    send_json,
    sha256_of_file,
)

SERVER_SCRIPT = os.path.join(PROJECT_ROOT, "server", "server.py")
UPLOAD_DIR    = os.path.join(PROJECT_ROOT, "server", "received_files")
DOWNLOAD_DIR  = os.path.join(PROJECT_ROOT, "client", "downloaded_files")
LOG_FILE      = os.path.join(PROJECT_ROOT, "logs", "server.log")

os.makedirs(UPLOAD_DIR,   exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "logs"), exist_ok=True)

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_server_proc       = None
_server_lock       = threading.Lock()
_server_start_time = None
_log_queue         = queue.Queue(maxsize=500)   # legacy; kept for _tail_server_log
_clients_lock      = threading.Lock()
_clients           = set()   # set of per-client queues (one per SSE connection)
_recent_logs       = collections.deque(maxlen=500)  # Persistent log history buffer


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


LOCAL_LAN_IP = get_local_ip()


def _broadcast(payload: dict):
    """Send a payload dict to every connected SSE client (non-blocking)."""
    with _clients_lock:
        dead = set()
        for q in _clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.add(q)
        _clients.difference_update(dead)


def _push_log(msg: str):
    """Broadcast a log-line event to all clients AND store in memory buffer."""
    _recent_logs.append(msg)
    _broadcast({"type": "log", "msg": msg})
    try:
        _log_queue.put_nowait(msg)
    except queue.Full:
        pass


def _broadcast_file_changed():
    """Tell every connected browser to refresh the file list immediately."""
    _broadcast({"type": "file_changed"})


def _tail_server_log():
    if not os.path.exists(LOG_FILE):
        open(LOG_FILE, "w").close()
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        # Load up to the last 50 lines into history on startup
        try:
            initial_lines = f.readlines()
            for line in initial_lines[-50:]:
                cleaned = line.rstrip()
                if cleaned and not any(x in cleaned for x in [
                    "Command 'STATUS'",
                    "STATUS served",
                    "Connection closed while reading message header",
                    "Failed to read command",
                    "Client connected: 127.0.0.1",
                    "Client disconnected: 127.0.0.1",
                ]):
                    _recent_logs.append(cleaned)
        except Exception:
            pass

        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                cleaned = line.rstrip()
                # Filter repetitive internal ping and status healthcheck logs
                if any(x in cleaned for x in [
                    "Command 'STATUS'",
                    "STATUS served",
                    "Connection closed while reading message header",
                    "Failed to read command",
                    "Client connected: 127.0.0.1",
                    "Client disconnected: 127.0.0.1",
                ]):
                    time.sleep(0.01)
                    continue
                _push_log(cleaned)
            else:
                time.sleep(0.1)


threading.Thread(target=_tail_server_log, daemon=True).start()


def _is_port_in_use():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.8)
        s.connect((HOST, PORT))
        s.close()
        return True
    except Exception:
        return False


def _kill_server_processes():
    global _server_proc, _server_start_time
    with _server_lock:
        if _server_proc:
            try:
                _server_proc.terminate()
                _server_proc.wait(timeout=1)
            except Exception:
                try:
                    _server_proc.kill()
                except Exception:
                    pass
            _server_proc = None
        _server_start_time = None

    if sys.platform == "win32":
        try:
            out = subprocess.check_output("netstat -ano", shell=True).decode('utf-8', errors='ignore')
            for line in out.splitlines():
                if ":5000 " in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    if pid.isdigit() and int(pid) != os.getpid():
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def _ensure_server_running():
    global _server_proc, _server_start_time
    if _is_port_in_use():
        return True
    with _server_lock:
        try:
            _server_proc = subprocess.Popen(
                [sys.executable, SERVER_SCRIPT],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _server_start_time = time.time()
            time.sleep(1.0)
            _push_log(f"[INFO] Server listening on 0.0.0.0:{PORT} (LAN IP: {LOCAL_LAN_IP}).")
            return True
        except Exception as exc:
            _push_log(f"[ERROR] Failed to start server: {exc}")
            return False


META_FILE = os.path.join(PROJECT_ROOT, "server", "file_meta.json")
_meta_lock = threading.Lock()


def _is_local_admin():
    """Returns True if the current request originates from the main server host machine."""
    try:
        remote = request.remote_addr
        # Local loopback or the machine's own LAN IP
        return remote in ("127.0.0.1", "::1", "localhost", LOCAL_LAN_IP)
    except Exception:
        return False


def _load_meta() -> dict:
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_meta(meta: dict):
    try:
        tmp = META_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, META_FILE)
    except Exception as e:
        _push_log(f"[WARN] Failed to save metadata: {e}")


def _set_file_owner(relpath: str, client_id: str, ip: str):
    clean = relpath.replace("\\", "/")
    with _meta_lock:
        meta = _load_meta()
        meta[clean] = {
            "client_id": client_id,
            "ip": ip,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        _save_meta(meta)


def _remove_file_owner(relpath: str):
    clean = relpath.replace("\\", "/")
    with _meta_lock:
        meta = _load_meta()
        to_del = [k for k in meta if k == clean or k.startswith(clean + "/")]
        for k in to_del:
            meta.pop(k, None)
        _save_meta(meta)


@app.route("/favicon.ico")
def favicon():
    return Response("", status=204)


# ── API: Server control ──────────────────────────────────────────────────────

@app.route("/api/server/start", methods=["POST"])
def api_server_start():
    if not _is_local_admin():
        return jsonify({"ok": False, "error": "Access denied: Server control is restricted to the main server machine."}), 403
    if _is_port_in_use():
        return jsonify({"ok": True, "message": "Server is already running on port 5000."})
    if _ensure_server_running():
        return jsonify({"ok": True, "message": "Server started successfully on port 5000."})
    else:
        return jsonify({"ok": False, "message": "Failed to start server."}), 500


@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    if not _is_local_admin():
        return jsonify({"ok": False, "error": "Access denied: Server control is restricted to the main server machine."}), 403
    _kill_server_processes()
    time.sleep(0.4)
    _push_log("[INFO] Server stopped completely.")
    return jsonify({"ok": True, "message": "Server stopped successfully."})


@app.route("/api/server/ping")
def api_server_ping():
    running = _is_port_in_use()
    proc_alive = bool(_server_proc and _server_proc.poll() is None)
    files_count = len(os.listdir(UPLOAD_DIR)) if os.path.exists(UPLOAD_DIR) else 0

    if running:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.2)
            s.connect((HOST, PORT))
            send_json(s, {"command": "STATUS"})
            status = recv_json(s)
            s.close()
            d = {
                "ok": True,
                "running": True,
                "proc_alive": proc_alive,
                "files_stored": files_count,
                "lan_ip": LOCAL_LAN_IP,
            }
            d.update(status)
            return jsonify(d)
        except Exception:
            pass
    return jsonify({
        "ok": True,
        "running": running,
        "proc_alive": proc_alive,
        "files_stored": files_count,
        "active_clients": 0,
        "uptime_seconds": 0,
        "lan_ip": LOCAL_LAN_IP,
    })


def _safe_upload_path(relpath: str):
    """Resolve a relative path safely inside UPLOAD_DIR, preventing traversal."""
    if not relpath:
        return None
    # Normalize slashes and strip leading/trailing slashes
    clean = relpath.replace("\\", "/").strip("/")
    parts = [p for p in clean.split("/") if p and p != "." and p != ".."]
    if not parts:
        return None
    full_path = os.path.abspath(os.path.join(UPLOAD_DIR, *parts))
    upload_root = os.path.abspath(UPLOAD_DIR)
    if os.path.commonpath([upload_root, full_path]) != upload_root:
        return None
    return full_path


# ── API: File operations ─────────────────────────────────────────────────────

@app.route("/api/list")
def api_list():
    try:
        files = []
        meta = _load_meta()
        if os.path.exists(UPLOAD_DIR):
            for root, dirs, fnames in os.walk(UPLOAD_DIR):
                for fname in sorted(fnames):
                    fpath = os.path.join(root, fname)
                    if os.path.isfile(fpath):
                        st = os.stat(fpath)
                        relpath = os.path.relpath(fpath, UPLOAD_DIR).replace("\\", "/")
                        dir_part = os.path.dirname(relpath).replace("\\", "/")
                        folder_name = dir_part if dir_part and dir_part != "." else ""
                        file_meta = meta.get(relpath, {})
                        files.append({
                            "name": relpath,
                            "filename": fname,
                            "folder": folder_name,
                            "size": st.st_size,
                            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                            "uploader_id": file_meta.get("client_id", ""),
                            "uploader_ip": file_meta.get("ip", ""),
                        })
        # Folders first alphabetically, then root files
        files.sort(key=lambda x: (x["folder"] == "", x["folder"].lower(), x["filename"].lower()))
        return jsonify({
            "status": "OK",
            "count": len(files),
            "files": files,
            "is_admin": _is_local_admin()
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "files": []}), 500


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. Uploads are disabled until the server is started."}), 503
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file selected."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename."}), 400

    client_id = request.headers.get("X-Client-Id") or request.form.get("client_id", "").strip()

    raw_relpath = request.form.get("relpath", "").strip() or f.filename
    clean = raw_relpath.replace("\\", "/").strip("/")
    parts = [p for p in clean.split("/") if p and p != "." and p != ".."]
    if not parts:
        parts = [sanitize_filename(os.path.basename(f.filename)) or "file"]

    safe_parts = [sanitize_filename(p) or p for p in parts]
    safe_relpath = os.path.join(*safe_parts)

    dest_path = os.path.abspath(os.path.join(UPLOAD_DIR, safe_relpath))
    upload_root = os.path.abspath(UPLOAD_DIR)

    if os.path.commonpath([upload_root, dest_path]) != upload_root:
        return jsonify({"ok": False, "error": "Invalid file path."}), 400

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    if os.path.exists(dest_path):
        base, ext = os.path.splitext(safe_parts[-1])
        counter = 1
        while os.path.exists(dest_path):
            safe_parts[-1] = f"{base}_{counter}{ext}"
            safe_relpath = os.path.join(*safe_parts)
            dest_path = os.path.join(UPLOAD_DIR, safe_relpath)
            counter += 1

    try:
        f.save(dest_path)
        filesize = os.path.getsize(dest_path)
        checksum = sha256_of_file(dest_path)
        display_name = safe_relpath.replace("\\", "/")

        if client_id:
            _set_file_owner(display_name, client_id, request.remote_addr)

        _push_log(f"[SUCCESS] Uploaded '{display_name}' ({filesize} bytes) [SHA-256: {checksum[:12]}...]")
        _broadcast_file_changed()

        return jsonify({
            "ok": True,
            "status": "UPLOAD_SUCCESS",
            "stored_as": display_name,
            "bytes": filesize,
            "elapsed": 0.05,
            "speed_mbs": round((filesize / (1024 * 1024)) / 0.05, 2),
        })
    except Exception as exc:
        _push_log(f"[ERROR] Upload error: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/download/<path:filename>")
def api_download(filename):
    if not _is_port_in_use():
        return Response("Socket server is OFFLINE. Downloads are disabled until the server is started.", status=503, mimetype="text/plain")
    fpath = _safe_upload_path(filename)
    if not fpath or not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": f"'{filename}' not found on server."}), 404

    target_name = os.path.basename(fpath)
    filesize = os.path.getsize(fpath)

    mime_type, _ = mimetypes.guess_type(target_name)
    if not mime_type:
        ext = os.path.splitext(target_name)[1].lower()
        ext_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".txt": "text/plain",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".json": "application/json",
            ".zip": "application/zip",
            ".bin": "application/octet-stream",
        }
        mime_type = ext_map.get(ext, "application/octet-stream")

    _push_log(f"[INFO] Downloaded '{target_name}' ({filesize} bytes, type={mime_type})")

    encoded_name = quote(target_name)
    response = send_file(
        fpath,
        mimetype=mime_type,
        as_attachment=True,
        download_name=target_name,
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{target_name}"; filename*=UTF-8\'\'{encoded_name}'
    response.headers["Content-Type"] = mime_type
    response.headers["Content-Length"] = str(filesize)
    return response


@app.route("/api/download-to-client", methods=["POST"])
def api_download_to_client():
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. File saving is disabled until the server is started."}), 503
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    fpath = _safe_upload_path(filename)
    if not fpath or not os.path.isfile(fpath):
        return jsonify({"ok": False, "error": f"'{filename}' not found on server."}), 404

    rel = os.path.relpath(fpath, UPLOAD_DIR)
    dest_path = os.path.join(DOWNLOAD_DIR, rel)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    if os.path.exists(dest_path):
        base, ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = f"{base}_{counter}{ext}"
            counter += 1

    filesize = os.path.getsize(fpath)
    shutil.copy2(fpath, dest_path)
    rel_saved = os.path.relpath(dest_path, DOWNLOAD_DIR).replace("\\", "/")
    _push_log(f"[SUCCESS] Saved '{rel.replace(chr(92), '/')}' to client/downloaded_files/{rel_saved}")
    return jsonify({
        "ok": True,
        "saved_as": rel_saved,
        "dest_path": dest_path,
        "bytes": filesize,
    })


@app.route("/api/delete", methods=["POST", "DELETE"])
@app.route("/api/delete/<path:filename>", methods=["DELETE", "POST"])
def api_delete(filename=None):
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. File deletion is disabled until the server is started."}), 503
    if not filename:
        data = request.get_json(silent=True) or {}
        filename = data.get("filename", "")

    if not filename:
        return jsonify({"ok": False, "error": "No filename provided."}), 400

    fpath = _safe_upload_path(filename)
    if not fpath or not os.path.exists(fpath):
        return jsonify({"ok": False, "error": f"Item '{filename}' not found."}), 404

    # Permission verification:
    # If not main server host, check that the client uploaded this item
    if not _is_local_admin():
        client_id = request.headers.get("X-Client-Id") or (request.get_json(silent=True) or {}).get("client_id") or request.form.get("client_id", "")
        meta = _load_meta()
        if os.path.isdir(fpath):
            owned_count = 0
            for root, _, fnames in os.walk(fpath):
                for fn in fnames:
                    child_rel = os.path.relpath(os.path.join(root, fn), UPLOAD_DIR).replace("\\", "/")
                    owner_id = meta.get(child_rel, {}).get("client_id", "")
                    if not owner_id or owner_id != client_id:
                        return jsonify({
                            "ok": False,
                            "error": "Permission denied: You can only delete folders/files that you uploaded from your device."
                        }), 403
                    owned_count += 1
            if owned_count == 0:
                return jsonify({"ok": False, "error": "Permission denied: You cannot delete server data."}), 403
        else:
            clean_rel = os.path.relpath(fpath, UPLOAD_DIR).replace("\\", "/")
            owner_id = meta.get(clean_rel, {}).get("client_id", "")
            if not owner_id or owner_id != client_id:
                return jsonify({
                    "ok": False,
                    "error": "Permission denied: You can only delete files that you uploaded from your device."
                }), 403

    try:
        import gc
        clean_rel = os.path.relpath(fpath, UPLOAD_DIR).replace("\\", "/")
        if os.path.isdir(fpath):
            gc.collect()
            for _ in range(3):
                try:
                    shutil.rmtree(fpath)
                    break
                except Exception:
                    time.sleep(0.15)
                    gc.collect()
            else:
                shutil.rmtree(fpath)
            display = clean_rel + "/"
            _remove_file_owner(clean_rel)
            _push_log(f"[INFO] Deleted folder '{display}' from server storage.")
        else:
            gc.collect()
            for _ in range(3):
                try:
                    os.remove(fpath)
                    break
                except Exception:
                    time.sleep(0.15)
                    gc.collect()
            else:
                os.remove(fpath)
            display = clean_rel
            _remove_file_owner(clean_rel)
            _push_log(f"[INFO] Deleted '{display}' from server storage.")
            # Clean up empty parent directories up to UPLOAD_DIR
            parent = os.path.dirname(fpath)
            upload_root = os.path.abspath(UPLOAD_DIR)
            while parent and parent != upload_root and os.path.commonpath([upload_root, parent]) == upload_root:
                if not os.listdir(parent):
                    os.rmdir(parent)
                    parent = os.path.dirname(parent)
                else:
                    break

        _broadcast_file_changed()
        return jsonify({"ok": True, "deleted": display})
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/delete-all", methods=["POST"])
def api_delete_all():
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. Purge is disabled until the server is started."}), 503
    if not _is_local_admin():
        return jsonify({"ok": False, "error": "Access denied: Purge is restricted to the main server machine."}), 403
    deleted = []
    try:
        if os.path.exists(UPLOAD_DIR):
            for item in os.listdir(UPLOAD_DIR):
                ipath = os.path.join(UPLOAD_DIR, item)
                if os.path.isfile(ipath):
                    os.remove(ipath)
                    deleted.append(item)
                elif os.path.isdir(ipath):
                    shutil.rmtree(ipath)
                    deleted.append(item + "/")
        # Clear metadata
        with _meta_lock:
            _save_meta({})
        _push_log(f"[INFO] Deleted all {len(deleted)} items from server storage.")
        _broadcast_file_changed()
        return jsonify({"ok": True, "deleted_count": len(deleted)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── API: ZIP downloads ───────────────────────────────────────────────────────

@app.route("/api/download-folder-zip/<path:foldername>", methods=["GET"])
def api_download_folder_zip(foldername):
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. ZIP downloads are disabled until the server is started."}), 503
    """Download a single folder category as a ZIP archive."""
    fpath = _safe_upload_path(foldername)
    if not fpath or not os.path.isdir(fpath):
        return jsonify({"ok": False, "error": f"Folder '{foldername}' not found."}), 404

    buf = io.BytesIO()
    added = 0
    safe_name = sanitize_filename(os.path.basename(fpath)) or "folder"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(fpath):
            for file in sorted(files):
                full = os.path.join(root, file)
                rel = os.path.relpath(full, fpath).replace("\\", "/")
                zf.write(full, rel)
                added += 1

    if added == 0:
        return jsonify({"ok": False, "error": "Folder is empty."}), 400

    buf.seek(0)
    _push_log(f"[INFO] ZIP downloaded: folder '{foldername}' ({added} file(s) bundled).")
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.zip"',
            "Content-Type": "application/zip",
        },
    )


@app.route("/api/download-zip", methods=["POST"])
def api_download_zip():
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. ZIP downloads are disabled until the server is started."}), 503
    """Return selected files as a single ZIP archive (streamed to browser)."""
    data  = request.get_json(silent=True) or {}
    names = data.get("filenames", [])
    if not names:
        return jsonify({"ok": False, "error": "No files specified."}), 400

    buf = io.BytesIO()
    added = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for raw in names:
            fpath = _safe_upload_path(raw)
            if fpath and os.path.isfile(fpath):
                rel = os.path.relpath(fpath, UPLOAD_DIR).replace("\\", "/")
                zf.write(fpath, rel)
                added.append(rel)

    if not added:
        return jsonify({"ok": False, "error": "None of the requested files found."}), 404

    buf.seek(0)
    _push_log(f"[INFO] ZIP downloaded: {len(added)} file(s) bundled.")
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="transfer_files.zip"',
            "Content-Type": "application/zip",
        },
    )


@app.route("/api/download-all-zip", methods=["GET"])
def api_download_all_zip():
    if not _is_port_in_use():
        return jsonify({"ok": False, "error": "Socket server is OFFLINE. ZIP downloads are disabled until the server is started."}), 503
    """Return ALL stored files and folders as a single ZIP archive."""
    buf = io.BytesIO()
    added = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(UPLOAD_DIR):
            for root, _, fnames in os.walk(UPLOAD_DIR):
                for fname in sorted(fnames):
                    fpath = os.path.join(root, fname)
                    if os.path.isfile(fpath):
                        rel = os.path.relpath(fpath, UPLOAD_DIR).replace("\\", "/")
                        zf.write(fpath, rel)
                        added.append(rel)

    if not added:
        return jsonify({"ok": False, "error": "No files on server."}), 404

    buf.seek(0)
    _push_log(f"[INFO] ZIP downloaded: all {len(added)} file(s) bundled.")
    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="all_files.zip"',
            "Content-Type": "application/zip",
        },
    )

# ── API: SSE log stream ──────────────────────────────────────────────────────

@app.route("/api/logs/stream")
def api_logs_stream():
    """Per-client SSE stream. Each connected browser gets its own queue.
    Payload format:
      {"type": "history",      "logs": [...]} – Initial recent log history
      {"type": "log",          "msg": "..."}   – Activity-log line
      {"type": "file_changed"}                  – Refresh file list now
    """
    client_q = queue.Queue(maxsize=300)
    with _clients_lock:
        _clients.add(client_q)

    def event_stream():
        try:
            # Send initial log history on connection
            history = list(_recent_logs)
            if history:
                yield f"data: {json.dumps({'type': 'history', 'logs': history})}\n\n"

            while True:
                try:
                    payload = client_q.get(timeout=20)
                    yield f"data: {json.dumps(payload)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _clients_lock:
                _clients.discard(client_q)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Frontend ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML, lan_ip=LOCAL_LAN_IP, is_admin=_is_local_admin())


# ─────────────────────────────────────────────────────────────────────────────
# HTML — Clean, Intuitive Interface
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Socket File Transfer System</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=VT323&display=swap" rel="stylesheet"/>
<style>
/* ── Reset ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:         #000a00;
  --panel:      #001200;
  --border:     #00ff41;
  --border-dim: #004010;
  --text:       #00ff41;
  --text-dim:   #00a828;
  --text-bright:#afffaf;
  --danger:     #ff3131;
  --warn:       #ffb300;
  --info:       #00e5ff;
  --mono: 'Share Tech Mono', 'Courier New', monospace;
  --title:'VT323', monospace;
}

html { overflow-x: hidden; width: 100%; font-size: 16px; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--mono);
  min-height: 100vh;
  padding: 8px;
  overflow-x: hidden;
  width: 100%;
  max-width: 100vw;
  position: relative;
  -webkit-text-size-adjust: 100%;
}
body::before {
  content: '';
  position: fixed; inset: 0;
  background: repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.18) 2px,rgba(0,0,0,0.18) 4px);
  pointer-events: none; z-index: 9999;
}
body::after {
  content: '';
  position: fixed; inset: 0;
  background: radial-gradient(ellipse at 50% 40%, rgba(0,255,65,0.04) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
}

.container {
  width: 100%; max-width: 100%; margin: 0;
  display: flex; flex-direction: column; gap: 8px;
  position: relative; z-index: 1; overflow: hidden;
}

/* ── Header ── */
.term-header {
  width: 100%; border: 1px solid var(--border); background: var(--panel);
  padding: 8px 10px; display: flex; flex-direction: row;
  align-items: flex-start; justify-content: space-between;
  flex-wrap: wrap; gap: 8px;
  box-shadow: 0 0 18px rgba(0,255,65,0.15), inset 0 0 24px rgba(0,255,65,0.03);
  overflow: hidden;
}
.brand-ascii { min-width: 0; flex: 1; overflow: hidden; }
.brand-ascii .title-line {
  font-family: var(--title); font-size: clamp(0.9rem,5vw,1.9rem);
  color: var(--text-bright); text-shadow: 0 0 10px rgba(0,255,65,0.8);
  white-space: normal; word-break: break-word; line-height: 1.2;
}
.brand-ascii .sub-line {
  font-size: clamp(0.55rem,2.2vw,0.72rem); color: var(--text-dim);
  text-transform: uppercase; word-break: break-word; margin-top: 2px;
}
.server-controls { display: flex; align-items: center; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }

.badge {
  font-family: var(--mono); font-size: clamp(0.6rem,2.5vw,0.78rem);
  padding: 4px 8px; border: 1px solid var(--border-dim);
  display: inline-flex; align-items: center; gap: 5px;
  letter-spacing: 1px; white-space: nowrap;
}
.badge.on  { border-color: var(--text);   color: var(--text-bright); box-shadow: 0 0 8px rgba(0,255,65,0.35); }
.badge.off { border-color: var(--danger); color: var(--danger);      box-shadow: 0 0 8px rgba(255,49,49,0.25); }
.badge.role-server { border-color: var(--info); color: var(--info); box-shadow: 0 0 6px rgba(0,229,255,0.3); }
.badge.role-client { border-color: var(--border-dim); color: var(--text-dim); }
.blink { animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

.btn {
  font-family: var(--mono); font-size: clamp(0.58rem,2.5vw,0.78rem);
  padding: 6px 10px; border: 1px solid currentColor;
  background: transparent; cursor: pointer; letter-spacing: 0.5px;
  text-transform: uppercase; transition: background 0.12s, box-shadow 0.12s;
  white-space: nowrap; touch-action: manipulation;
  -webkit-tap-highlight-color: transparent; min-height: 34px;
}
.btn-start { color: var(--text); }
.btn-start:hover, .btn-start:active { background: rgba(0,255,65,0.12); box-shadow: 0 0 10px rgba(0,255,65,0.4); }
.btn-stop  { color: var(--danger); }
.btn-stop:hover, .btn-stop:active   { background: rgba(255,49,49,0.12); box-shadow: 0 0 10px rgba(255,49,49,0.4); }
.btn-sec   { color: var(--text-dim); border-color: var(--border-dim); }
.btn-sec:hover, .btn-sec:active { color: var(--text); border-color: var(--text); }
.btn-warn  { color: var(--warn); border-color: var(--warn); }
.btn-warn:hover, .btn-warn:active { background: rgba(255,179,0,0.1); }
.btn-info  { color: var(--info); border-color: var(--info); }
.btn-info:hover, .btn-info:active { background: rgba(0,229,255,0.1); }

.lan-banner {
  width: 100%; border: 1px solid var(--border-dim);
  background: rgba(0,255,65,0.03); padding: 7px 10px;
  font-size: clamp(0.58rem,2.4vw,0.76rem); color: var(--text-dim);
  word-break: break-all; line-height: 1.6;
}
.lan-banner strong { color: var(--text-bright); }
.lan-banner .ip    { color: var(--info); }

.grid {
  display: grid;
  grid-template-columns: 1fr 1.45fr;
  gap: 8px;
  width: 100%;
  align-items: start;
}
.left-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  width: 100%;
}
.upload-panel {
  width: 100%;
  flex-shrink: 0;
}
.log-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  width: 100%;
  flex-shrink: 0;
}
.file-panel {
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
}

.panel {
  width: 100%; border: 1px solid var(--border-dim);
  background: var(--panel); overflow: hidden; min-width: 0;
  box-shadow: inset 0 0 20px rgba(0,0,0,0.5);
}
.panel-hdr {
  border-bottom: 1px solid var(--border-dim); padding: 6px 10px;
  display: flex; justify-content: space-between; align-items: center;
  gap: 6px; background: rgba(0,255,65,0.04); flex-wrap: wrap; width: 100%;
}
.panel-title {
  font-family: var(--title); font-size: clamp(0.85rem,3.5vw,1.1rem);
  color: var(--text-bright); letter-spacing: 2px;
  text-shadow: 0 0 6px rgba(0,255,65,0.4);
}
.panel-hdr-btns { display: flex; gap: 4px; flex-wrap: wrap; }
.panel-body { padding: 10px; }

.prompt {
  font-size: clamp(0.6rem,2.2vw,0.72rem); color: var(--text-dim);
  margin-bottom: 8px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; width: 100%;
}
.prompt span { color: var(--text); }
.cursor::after { content: '_'; animation: blink 1s step-end infinite; }

/* ── Upload zone ── */
.upload-zone {
  width: 100%; border: 1px dashed var(--border-dim);
  padding: 16px 8px; text-align: center; cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  background: rgba(0,0,0,0.3); touch-action: manipulation;
  -webkit-tap-highlight-color: transparent; user-select: none; overflow: hidden;
}
.upload-zone.disabled-offline {
  border-color: rgba(255,49,49,0.45) !important;
  background: rgba(255,49,49,0.05) !important;
  cursor: not-allowed !important;
}
.upload-zone.disabled-offline .hint {
  color: var(--danger) !important;
}
.upload-zone:hover, .upload-zone.over, .upload-zone:active {
  border-color: var(--text); background: rgba(0,255,65,0.05);
  box-shadow: inset 0 0 16px rgba(0,255,65,0.06);
}
.upload-zone .icon { font-size: 1.6rem; margin-bottom: 6px; display: block; }
.upload-zone .hint { font-size: clamp(0.62rem,2.5vw,0.8rem); color: var(--text); margin-bottom: 4px; word-break: break-word; }
.upload-zone .sub  { font-size: clamp(0.55rem,2vw,0.68rem); color: var(--text-dim); word-break: break-word; }

/* ── Upload trigger buttons row ── */
.upload-triggers {
  display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap;
}
.upload-triggers .btn { flex: 1; text-align: center; font-size: clamp(0.58rem,2.3vw,0.72rem); padding: 7px 6px; }

/* ── Queue progress ── */
.queue-wrap { margin-top: 10px; display: none; }
.queue-overall {
  display: flex; justify-content: space-between;
  font-size: 0.7rem; color: var(--text-dim); margin-bottom: 4px;
}
.prog-track { height: 6px; background: #001a00; border: 1px solid var(--border-dim); width: 100%; }
.prog-fill  { height: 100%; background: var(--text); width: 0%; transition: width 0.15s; box-shadow: 0 0 6px rgba(0,255,65,0.6); }
.queue-list {
  margin-top: 8px; max-height: 120px; overflow-y: auto;
  scrollbar-width: thin; scrollbar-color: var(--border-dim) transparent;
}
.queue-list::-webkit-scrollbar { width: 4px; }
.queue-list::-webkit-scrollbar-thumb { background: var(--border-dim); }
.q-item {
  display: flex; align-items: center; gap: 6px;
  font-size: 0.68rem; padding: 3px 0;
  border-bottom: 1px solid rgba(0,64,16,0.4); color: var(--text-dim);
  overflow: hidden;
}
.q-item .q-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-item .q-status { flex-shrink: 0; }
.q-item.done   .q-status { color: var(--text); }
.q-item.error  .q-status { color: var(--danger); }
.q-item.active .q-status { color: var(--warn); }

/* ── File table ── */
.table-wrap { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.file-table { width: 100%; border-collapse: collapse; font-size: clamp(0.6rem,2.3vw,0.76rem); table-layout: fixed; }
.file-table th {
  padding: 5px 6px; border-bottom: 1px solid var(--border-dim);
  color: var(--text-dim); text-align: left; font-weight: normal;
  letter-spacing: 0.5px; text-transform: uppercase;
  font-size: clamp(0.55rem,1.9vw,0.68rem); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.file-table td {
  padding: 7px 6px; border-bottom: 1px solid rgba(0,64,16,0.5);
  color: var(--text); overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; vertical-align: middle;
}
.file-table tr:hover td { background: rgba(0,255,65,0.04); }
.file-table tr.selected td { background: rgba(0,255,65,0.08); }
.file-table .empty-row td { color: var(--text-dim); text-align: center; padding: 18px 6px; white-space: normal; }

/* ── Folder categorization styling ── */
.folder-header-row {
  background: rgba(0, 255, 65, 0.08) !important;
  border-top: 1px solid var(--border-dim);
  border-bottom: 1px solid var(--border-dim);
}
.folder-header-row:hover td {
  background: rgba(0, 255, 65, 0.12) !important;
}
.folder-header-row td {
  padding: 5px 6px !important;
}
.folder-title-td {
  vertical-align: middle;
}
.folder-title-wrap {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 100%;
}
.folder-icon {
  font-size: 0.95rem;
  color: var(--warn);
  flex-shrink: 0;
}
.folder-name {
  font-weight: bold;
  color: var(--text-bright);
  font-size: clamp(0.65rem, 2.3vw, 0.8rem);
  text-shadow: 0 0 6px rgba(0,255,65,0.4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.folder-badge {
  font-size: clamp(0.55rem, 1.8vw, 0.65rem);
  color: var(--text-dim);
  font-weight: normal;
  white-space: nowrap;
}
.tree-branch {
  color: var(--border-dim);
  font-family: monospace;
  margin-right: 3px;
  user-select: none;
}
.file-icon {
  font-size: 0.8rem;
  opacity: 0.85;
  margin-right: 3px;
}
.folder-child-row td:nth-child(2) {
  padding-left: 10px;
}

/* User tags */
.tag-you {
  font-size: 0.54rem; color: var(--info); border: 1px solid rgba(0,229,255,0.4);
  padding: 0 3px; border-radius: 2px; margin-left: 5px; vertical-align: middle;
}
.tag-server {
  font-size: 0.54rem; color: var(--text-dim); border: 1px solid rgba(0,64,16,0.8);
  padding: 0 3px; border-radius: 2px; margin-left: 5px; vertical-align: middle;
}

/* Checkbox column */
.col-chk { width: 30px; text-align: center !important; }
input[type=checkbox] {
  accent-color: var(--text); width: 14px; height: 14px; cursor: pointer;
}

/* Size column (hidden on small screens) */
.col-size { width: 14%; }
/* Actions column */
.col-act  { width: 38%; text-align: right !important; }

.act-btns { display: flex; gap: 3px; justify-content: flex-end; flex-wrap: wrap; }
.act-btn {
  font-family: var(--mono); font-size: clamp(0.52rem,1.8vw,0.65rem);
  padding: 4px 6px; border: 1px solid var(--border-dim);
  background: transparent; color: var(--text-dim); cursor: pointer;
  letter-spacing: 0; text-decoration: none; display: inline-flex;
  align-items: center; justify-content: center; gap: 2px;
  transition: all 0.12s; touch-action: manipulation;
  -webkit-tap-highlight-color: transparent; min-height: 28px; white-space: nowrap;
}
.act-btn:hover, .act-btn:active { border-color: var(--text); color: var(--text); background: rgba(0,255,65,0.06); }
.act-btn.del { color: rgba(255,49,49,0.7); border-color: rgba(255,49,49,0.3); }
.act-btn.del:hover, .act-btn.del:active { background: rgba(255,49,49,0.12); color: var(--danger); border-color: var(--danger); }

/* Bulk action bar */
.bulk-bar {
  display: none; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 6px 10px; border-bottom: 1px solid var(--border-dim);
  background: rgba(0,255,65,0.04); font-size: 0.72rem; color: var(--text-dim);
}
.bulk-bar.visible { display: flex; }
.bulk-count { flex: 1; }

/* Log box */
.log-box {
  background: #000800; padding: 8px 10px; font-family: var(--mono);
  font-size: clamp(0.6rem,2.2vw,0.74rem);
  height: 220px;
  min-height: 220px;
  max-height: 220px;
  overflow-y: auto; overflow-x: hidden; color: var(--text-dim);
  line-height: 1.6; white-space: pre-wrap; word-break: break-all;
  width: 100%; box-sizing: border-box;
  scrollbar-width: thin; scrollbar-color: var(--border-dim) transparent;
  -webkit-overflow-scrolling: touch;
}
.log-box::-webkit-scrollbar { width: 4px; }
.log-box::-webkit-scrollbar-thumb { background: var(--border-dim); }

/* ══ Responsive ══ */
@media (max-width: 768px) {
  body { padding: 6px; }
  .grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .left-col {
    display: flex;
    flex-direction: column;
    height: auto;
  }
  .upload-panel { order: 1; flex-shrink: 0; }
  .file-panel   { order: 2; }
  .log-panel    { order: 3; flex-shrink: 0; }
  .log-box      { height: 160px; min-height: 130px; max-height: 160px; }
}
@media (max-width: 520px) {
  body { padding: 5px; }
  .col-size { display: none !important; }
  .panel-hdr { flex-direction: row; }
  .panel-hdr-btns .btn { font-size: 0.58rem; padding: 5px 7px; }
  .act-btn { padding: 4px 5px; font-size: 0.55rem; }
  .upload-zone { padding: 14px 8px; }
  .log-box { height: 140px; min-height: 120px; max-height: 140px; }
}
@media (max-width: 380px) {
  .brand-ascii .title-line { font-size: 0.82rem; }
  .btn { font-size: 0.55rem; padding: 5px 8px; }
  .act-btn { font-size: 0.52rem; padding: 3px 4px; }
}
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="term-header">
    <div class="brand-ascii">
      <div class="title-line">[ SOCKET FILE TRANSFER SYSTEM ]</div>
      <div class="sub-line">TCP/IP Server &bull; Port 5000 &bull; Multi-Device LAN</div>
    </div>
    <div class="server-controls">
      <div class="badge off" id="badge">
        <span class="blink">&#9679;</span>
        <span id="badge-text">OFFLINE</span>
      </div>
      {% if is_admin %}
      <span class="badge role-server" title="You are on the Host Machine">[ MAIN SERVER HOST ]</span>
      <button class="btn btn-start" id="btn-toggle" onclick="toggleServer()">[ START SERVER ]</button>
      {% else %}
      <span class="badge role-client" title="Connected via LAN">[ LAN CLIENT ]</span>
      {% endif %}
    </div>
  </div>

  <!-- LAN Banner -->
  <div class="lan-banner">
    {% if is_admin %}
    <strong>// NETWORK ACCESS</strong> &nbsp;|&nbsp;
    Connect any device on same Wi-Fi &rarr; open browser &rarr;
    <span class="ip">http://{{ lan_ip }}:8080</span>
    {% else %}
    <strong>// CLIENT ACCESS</strong> &nbsp;|&nbsp;
    Connected to Main Server Host &bull; Uploaded files are associated with your device
    {% endif %}
  </div>

  <div class="grid">

    <!-- Left Column: Upload + Activity Log -->
    <div class="left-col">

      <!-- Upload Panel -->
      <div class="panel upload-panel">
        <div class="panel-hdr">
          <span class="panel-title">UPLOAD</span>
          <span style="font-size:0.65rem;color:var(--text-dim)">SHA-256</span>
        </div>
        <div class="panel-body">
          <div class="prompt">root@server:<span>~/received_files$</span> <span class="cursor"></span></div>

          <!-- Drop zone -->
          <div class="upload-zone" id="drop-box"
               onclick="if(!serverOnline){alert('Socket Server is OFFLINE.\nPlease start the server first.');log('[WARN] Upload blocked: Server is OFFLINE.');}else{document.getElementById('file-inp').click()}">
            <span class="icon">[ &#8679; ]</span>
            <div class="hint">CLICK / DRAG &amp; DROP FILES HERE</div>
            <div class="sub">Multiple files &amp; folders supported &mdash; SHA-256 verified</div>
          </div>

          <!-- Hidden file inputs -->
          <input type="file" id="file-inp"    style="display:none" multiple
                 onchange="enqueueFiles(this.files)"/>
          <input type="file" id="folder-inp"  style="display:none" multiple
                 webkitdirectory mozdirectory
                 onchange="enqueueFiles(this.files)"/>

          <!-- Trigger buttons -->
          <div class="upload-triggers">
            <button class="btn btn-start"
                    onclick="if(!serverOnline){alert('Socket Server is OFFLINE.\nPlease start the server first.');log('[WARN] Upload blocked: Server is OFFLINE.');}else{document.getElementById('file-inp').click()}">[ + FILES ]</button>
            <button class="btn btn-sec"
                    onclick="if(!serverOnline){alert('Socket Server is OFFLINE.\nPlease start the server first.');log('[WARN] Upload blocked: Server is OFFLINE.');}else{document.getElementById('folder-inp').click()}">[ + FOLDER ]</button>
          </div>

          <!-- Upload queue progress -->
          <div class="queue-wrap" id="queue-wrap">
            <div class="queue-overall">
              <span id="q-label">Uploading...</span>
              <span id="q-pct">0%</span>
            </div>
            <div class="prog-track"><div class="prog-fill" id="q-fill"></div></div>
            <div class="queue-list" id="q-list"></div>
          </div>
        </div>
      </div>

      <!-- Activity Log Panel (Seamlessly fills remaining height below Upload) -->
      <div class="panel log-panel">
        <div class="panel-hdr">
          <span class="panel-title">ACTIVITY LOG</span>
          <div class="panel-hdr-btns">
            <button class="btn btn-sec" onclick="clearLogs()">[ CLEAR ]</button>
          </div>
        </div>
        <div class="log-box" id="logs"></div>
      </div>

    </div><!-- /left-col -->

    <!-- Right Column: File Manager Panel -->
    <div class="panel file-panel">
      <div class="panel-hdr">
        <span class="panel-title">FILE INDEX</span>
        <div class="panel-hdr-btns">
          <button class="btn btn-sec"  onclick="loadFiles(true)">[ REFRESH ]</button>
          <button class="btn btn-info" onclick="downloadAllZip()">[ ALL ZIP ]</button>
          {% if is_admin %}
          <button class="btn btn-stop" onclick="deleteAllFiles()">[ PURGE ]</button>
          {% endif %}
        </div>
      </div>

      <!-- Bulk action bar (shown when ≥1 file selected) -->
      <div class="bulk-bar" id="bulk-bar">
        <span class="bulk-count" id="bulk-count">0 selected</span>
        <button class="btn btn-info" onclick="downloadSelectedZip()">[ DL SELECTED ZIP ]</button>
        <button class="btn btn-stop" onclick="deleteSelected()">[ DEL SELECTED ]</button>
        <button class="btn btn-sec"  onclick="clearSelection()">[ CLEAR ]</button>
      </div>

      <div class="table-wrap">
        <table class="file-table">
          <colgroup>
            <col style="width:30px"/>          <!-- checkbox -->
            <col style="width:auto"/>           <!-- filename / folder -->
            <col class="col-size" style="width:14%"/> <!-- size -->
            <col class="col-act"  style="width:38%"/> <!-- actions -->
          </colgroup>
          <thead>
            <tr>
              <th class="col-chk">
                <input type="checkbox" id="chk-all" onchange="toggleSelectAll(this.checked)"
                       title="Select all"/>
              </th>
              <th>Name / Folder</th>
              <th class="col-size">Size</th>
              <th style="text-align:right">Actions</th>
            </tr>
          </thead>
          <tbody id="file-list">
            <tr class="empty-row"><td colspan="4">Initializing...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </div><!-- /grid -->

</div><!-- /container -->

<script>
const IS_ADMIN = {{ 'true' if is_admin else 'false' }};
let serverOnline = false;

// ── Persistent Client ID for Device Ownership ─────────────────────
let myClientId = localStorage.getItem('sft_client_id');
if (!myClientId) {
  myClientId = 'c_' + Math.random().toString(36).substring(2, 11) + Date.now().toString(36);
  localStorage.setItem('sft_client_id', myClientId);
}

// ── Server control (Only available on Main Server) ────────────────
async function checkServer() {
  try {
    const res  = await fetch('/api/server/ping');
    const data = await res.json();
    serverOnline = data.running;
    const badge = document.getElementById('badge');
    const text  = document.getElementById('badge-text');
    const btn   = document.getElementById('btn-toggle');
    const dropBox = document.getElementById('drop-box');
    const dropHint = dropBox ? dropBox.querySelector('.hint') : null;
    const dropSub  = dropBox ? dropBox.querySelector('.sub') : null;
    if (data.running) {
      badge.className = 'badge on';
      text.textContent = 'ONLINE';
      if (btn) {
        btn.className = 'btn btn-stop';
        btn.textContent = '[ STOP SERVER ]';
      }
      if (dropBox) dropBox.classList.remove('disabled-offline');
      if (dropHint) dropHint.textContent = 'CLICK / DRAG & DROP FILES HERE';
      if (dropSub)  dropSub.textContent = 'Multiple files & folders supported — SHA-256 verified';
    } else {
      badge.className = 'badge off';
      text.textContent = 'OFFLINE';
      if (btn) {
        btn.className = 'btn btn-start';
        btn.textContent = '[ START SERVER ]';
      }
      if (dropBox) dropBox.classList.add('disabled-offline');
      if (dropHint) dropHint.textContent = '[ SERVER OFFLINE — TRANSFERS DISABLED ]';
      if (dropSub)  dropSub.textContent = 'Start the socket server from top-right to enable file transfers';
    }
  } catch(e) {}
}

async function toggleServer() {
  if (!IS_ADMIN) {
    alert("Server ON/OFF control can only be performed on the main server machine.");
    return;
  }
  const url = serverOnline ? '/api/server/stop' : '/api/server/start';
  try {
    const res  = await fetch(url, {method:'POST'});
    const data = await res.json();
    if (!res.ok) {
      log('ERR: ' + (data.error || 'Server operation rejected'));
      return;
    }
    log(data.message || 'Server state updated');
    checkServer();
  } catch(e) { log('Error: ' + e); }
}

// ── Multi-file upload queue ───────────────────────────────────────
let _uploadQueue   = [];
let _uploading     = false;

function enqueueFiles(fileList) {
  if (!serverOnline) {
    alert("Socket Server is OFFLINE.\nUploads and file transfers are disabled until the server is started.");
    log('[WARN] Upload blocked: Server is OFFLINE.');
    return;
  }
  if (!fileList || !fileList.length) return;
  const files = Array.from(fileList);
  _uploadQueue.push(...files);
  log('Queued ' + files.length + ' file(s) for upload. Total pending: ' + _uploadQueue.length);
  if (!_uploading) processQueue();
}

async function processQueue() {
  if (!_uploadQueue.length) {
    _uploading = false;
    const wrap = document.getElementById('queue-wrap');
    document.getElementById('q-label').textContent = 'All done!';
    document.getElementById('q-pct').textContent   = '100%';
    document.getElementById('q-fill').style.width  = '100%';
    setTimeout(() => { wrap.style.display = 'none'; }, 2500);
    loadFiles(); checkServer();
    return;
  }

  _uploading = true;
  const wrap  = document.getElementById('queue-wrap');
  const qlist = document.getElementById('q-list');
  wrap.style.display = 'block';

  const file = _uploadQueue.shift();
  const relPath = file.customRelativePath || file.webkitRelativePath || file.name;
  const itemId = 'qi-' + Date.now() + '-' + Math.floor(Math.random()*1000);

  // Add item to visual list
  const div = document.createElement('div');
  div.className = 'q-item active';
  div.id = itemId;
  div.innerHTML = '<span class="q-name">' + esc(relPath) + '</span><span class="q-status">uploading...</span>';
  qlist.appendChild(div);
  qlist.scrollTop = qlist.scrollHeight;

  try {
    const form = new FormData();
    form.append('file', file, relPath);
    form.append('relpath', relPath);
    form.append('client_id', myClientId);
    const res  = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'X-Client-Id': myClientId },
      body: form
    });
    const data = await res.json();
    const el   = document.getElementById(itemId);
    if (data.ok) {
      el.className = 'q-item done';
      el.querySelector('.q-status').textContent = 'OK ' + fmtBytes(data.bytes);
      log('OK Uploaded "' + data.stored_as + '" (' + fmtBytes(data.bytes) + ')');
    } else {
      el.className = 'q-item error';
      el.querySelector('.q-status').textContent = 'ERR';
      log('ERR ' + relPath + ': ' + (data.error||'upload failed'));
    }
  } catch(e) {
    const el = document.getElementById(itemId);
    if (el) { el.className='q-item error'; el.querySelector('.q-status').textContent='ERR'; }
    log('ERR ' + relPath + ': ' + e);
  }

  // Update overall progress
  const done  = qlist.querySelectorAll('.q-item.done, .q-item.error').length;
  const total = done + _uploadQueue.length;
  const pct   = total ? Math.round((done / total) * 100) : 100;
  document.getElementById('q-fill').style.width = pct + '%';
  document.getElementById('q-pct').textContent  = pct + '%';
  document.getElementById('q-label').textContent = done + ' / ' + total + ' uploaded';

  // Reset file inputs so same files/folders can be re-selected
  document.getElementById('file-inp').value   = '';
  document.getElementById('folder-inp').value = '';

  await processQueue();
}

// Drag-and-drop (supports dropping folders & nested folders)
const drop = document.getElementById('drop-box');
['dragenter','dragover'].forEach(n => drop.addEventListener(n, e => {
  e.preventDefault(); drop.classList.add('over');
}));
['dragleave','drop'].forEach(n => drop.addEventListener(n, e => {
  e.preventDefault(); drop.classList.remove('over');
}));
drop.addEventListener('drop', async e => {
  e.preventDefault(); drop.classList.remove('over');
  if (!serverOnline) {
    alert("Socket Server is OFFLINE.\nUploads are disabled until the server is started.");
    log('[WARN] Upload blocked: Server is OFFLINE.');
    return;
  }
  const items = e.dataTransfer.items;
  if (items && items.length) {
    const files = [];
    const queue = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === 'file') {
        const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
        if (entry) {
          queue.push(traverseEntry(entry, ''));
        } else {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
    }
    if (queue.length) await Promise.all(queue);

    function traverseEntry(entry, path) {
      return new Promise(resolve => {
        if (entry.isFile) {
          entry.file(f => {
            const rel = path ? path + '/' + entry.name : entry.name;
            try {
              Object.defineProperty(f, 'customRelativePath', { value: rel, writable: true, configurable: true });
            } catch(_) { f.customRelativePath = rel; }
            files.push(f);
            resolve();
          }, () => resolve());
        } else if (entry.isDirectory) {
          const dirReader = entry.createReader();
          const dirPath = path ? path + '/' + entry.name : entry.name;
          const readBatch = () => {
            dirReader.readEntries(async entries => {
              if (!entries.length) {
                resolve();
              } else {
                await Promise.all(entries.map(e => traverseEntry(e, dirPath)));
                readBatch();
              }
            }, () => resolve());
          };
          readBatch();
        } else {
          resolve();
        }
      });
    }

    if (files.length) enqueueFiles(files);
  } else if (e.dataTransfer.files && e.dataTransfer.files.length) {
    enqueueFiles(e.dataTransfer.files);
  }
});

// ── File list & Categorization ────────────────────────────────────
let _selectedFiles = new Set();
let _allLoadedFiles = [];

async function loadFiles(manual = false) {
  const tbody = document.getElementById('file-list');
  try {
    const res  = await fetch('/api/list');
    const data = await res.json();
    const files = data.files || [];
    _allLoadedFiles = files;

    if (manual) {
      log('File index refreshed (' + files.length + ' item(s) found)');
    }

    // Remove any selected file that no longer exists
    const validNames = new Set(files.map(f => f.name));
    for (const name of _selectedFiles) {
      if (!validNames.has(name)) _selectedFiles.delete(name);
    }
    updateBulkBar();

    if (!files.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="4">No files stored. Upload above.</td></tr>';
      document.getElementById('chk-all').checked = false;
      return;
    }

    // Group files by folder
    const groups = {};
    const folderOrder = [];
    files.forEach(f => {
      const fldr = f.folder || '';
      if (!groups[fldr]) {
        groups[fldr] = [];
        folderOrder.push(fldr);
      }
      groups[fldr].push(f);
    });

    let html = '';
    folderOrder.forEach(fldr => {
      const grp = groups[fldr];
      const totalBytes = grp.reduce((acc, curr) => acc + (curr.size || 0), 0);
      const isFolder = fldr !== '';

      // Check if current user can delete this whole folder:
      // Admin can delete any folder; normal user can delete only if ALL files inside belong to this device
      const canDeleteFolder = IS_ADMIN || (grp.length > 0 && grp.every(f => f.uploader_id && f.uploader_id === myClientId));

      if (isFolder) {
        const folderDelBtn = canDeleteFolder
          ? `<button class="act-btn del" onclick="deleteFolder('${esc(fldr)}')" title="Delete entire folder">DEL</button>`
          : '';

        // Folder category header row
        html += `<tr class="folder-header-row" data-folder="${esc(fldr)}">
          <td class="col-chk">
            <input type="checkbox" class="folder-chk" data-folder="${esc(fldr)}"
                   onchange="toggleFolderSelect('${esc(fldr)}', this.checked)"
                   title="Select all in ${esc(fldr)}/"/>
          </td>
          <td class="folder-title-td" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            <div class="folder-title-wrap">
              <span class="folder-icon">&#128193;</span>
              <span class="folder-name">${esc(fldr)}/</span>
              <span class="folder-badge">[${grp.length} file${grp.length > 1 ? 's' : ''} &bull; ${fmtBytes(totalBytes)}]</span>
            </div>
          </td>
          <td class="col-size" style="color:var(--text-dim)">${fmtBytes(totalBytes)}</td>
          <td style="text-align:right;padding-right:4px">
            <div class="act-btns">
              <button class="act-btn btn-info" onclick="downloadFolderZip('${esc(fldr)}')" title="Download folder as ZIP">&#8595;ZIP</button>
              ${folderDelBtn}
            </div>
          </td>
        </tr>`;
      } else if (folderOrder.length > 1) {
        // Standalone files header row (only show if there are also folders present)
        html += `<tr class="folder-header-row" data-folder="">
          <td class="col-chk">
            <input type="checkbox" class="folder-chk" data-folder=""
                   onchange="toggleFolderSelect('', this.checked)"
                   title="Select all standalone files"/>
          </td>
          <td class="folder-title-td" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
            <div class="folder-title-wrap">
              <span class="folder-icon" style="color:var(--text-dim)">&#128196;</span>
              <span class="folder-name">[ STANDALONE FILES ]</span>
              <span class="folder-badge">[${grp.length} file${grp.length > 1 ? 's' : ''} &bull; ${fmtBytes(totalBytes)}]</span>
            </div>
          </td>
          <td class="col-size" style="color:var(--text-dim)">${fmtBytes(totalBytes)}</td>
          <td style="text-align:right;padding-right:4px"></td>
        </tr>`;
      }

      // Render files in this group
      grp.forEach(f => {
        const sn = esc(f.name);
        const displayName = esc(f.filename || f.name);
        const dlUrl = '/api/download/' + encodeURIComponent(f.name).replace(/%2F/g, '/');
        const childClass = isFolder ? 'folder-child-row' : '';
        const branchHtml = isFolder ? '<span class="tree-branch">&#9492;&#9472;</span>' : '';
        const isChecked = _selectedFiles.has(f.name) ? 'checked' : '';
        const rowSelected = isChecked ? 'selected' : '';

        // Device ownership logic:
        const isMyUpload = Boolean(f.uploader_id && f.uploader_id === myClientId);
        const canDeleteFile = IS_ADMIN || isMyUpload;

        let tagHtml = '';
        if (isMyUpload) {
          tagHtml = '<span class="tag-you">[YOU]</span>';
        } else if (!IS_ADMIN && f.uploader_id) {
          tagHtml = '<span class="tag-server">[SHARED]</span>';
        } else if (!IS_ADMIN) {
          tagHtml = '<span class="tag-server">[SERVER]</span>';
        }

        const delButtonHtml = canDeleteFile
          ? `<button class="act-btn del" data-name="${sn}" title="Delete file">DEL</button>`
          : '';

        html += `<tr class="${childClass} ${rowSelected}" data-name="${sn}" data-folder="${esc(fldr)}">
          <td class="col-chk">
            <input type="checkbox" class="row-chk" value="${sn}" data-folder="${esc(fldr)}" ${isChecked}
                   onchange="onRowCheck(this)"/>
          </td>
          <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${sn}">
            ${branchHtml}<span class="file-icon">&#128196;</span><span>${displayName}</span>${tagHtml}
          </td>
          <td class="col-size" style="color:var(--text-dim)">${fmtBytes(f.size)}</td>
          <td style="text-align:right;padding-right:4px">
            <div class="act-btns">
              <a class="act-btn btn-dl" href="${dlUrl}" download="${displayName}" title="Download">&#8595;DL</a>
              <button class="act-btn btn-sync" data-name="${sn}" title="Save to client">SAVE</button>
              ${delButtonHtml}
            </div>
          </td>
        </tr>`;
      });
    });

    tbody.innerHTML = html;
    syncCheckboxesState();
  } catch(e) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="4" style="color:var(--danger)">ERROR loading files.</td></tr>';
  }
}

function onRowCheck(cb) {
  if (cb.checked) _selectedFiles.add(cb.value);
  else            _selectedFiles.delete(cb.value);
  const row = cb.closest('tr');
  if (row) row.classList.toggle('selected', cb.checked);
  syncCheckboxesState();
}

function toggleFolderSelect(fldr, checked) {
  const cbs = document.querySelectorAll(`.row-chk[data-folder="${CSS.escape(fldr)}"]`);
  cbs.forEach(cb => {
    cb.checked = checked;
    const row = cb.closest('tr');
    if (row) row.classList.toggle('selected', checked);
    if (checked) _selectedFiles.add(cb.value);
    else         _selectedFiles.delete(cb.value);
  });
  syncCheckboxesState();
}

function toggleSelectAll(checked) {
  _selectedFiles.clear();
  document.querySelectorAll('.row-chk').forEach(cb => {
    cb.checked = checked;
    const row = cb.closest('tr');
    if (row) row.classList.toggle('selected', checked);
    if (checked) _selectedFiles.add(cb.value);
  });
  document.querySelectorAll('.folder-chk').forEach(fcb => {
    fcb.checked = checked;
  });
  updateBulkBar();
}

function syncCheckboxesState() {
  // Update each folder checkbox
  document.querySelectorAll('.folder-chk').forEach(fcb => {
    const fldr = fcb.getAttribute('data-folder');
    const childCbs = document.querySelectorAll(`.row-chk[data-folder="${CSS.escape(fldr)}"]`);
    if (childCbs.length > 0) {
      const allChecked = Array.from(childCbs).every(cb => cb.checked);
      fcb.checked = allChecked;
    }
  });

  // Update table header master checkbox
  const allRowCbs = document.querySelectorAll('.row-chk');
  const master = document.getElementById('chk-all');
  if (master) {
    master.checked = allRowCbs.length > 0 && Array.from(allRowCbs).every(cb => cb.checked);
  }

  updateBulkBar();
}

function clearSelection() {
  toggleSelectAll(false);
  const master = document.getElementById('chk-all');
  if (master) master.checked = false;
}

function updateBulkBar() {
  const bar   = document.getElementById('bulk-bar');
  const count = document.getElementById('bulk-count');
  const n     = _selectedFiles.size;
  if (count) count.textContent = n + ' selected';
  if (bar) bar.classList.toggle('visible', n > 0);
}

// ── Event delegation (DL / SAVE / DEL buttons) ───────────────────
document.getElementById('file-list').addEventListener('click', function(e) {
  const btn = e.target.closest('.act-btn');
  if (!btn) return;
  if (!serverOnline) {
    e.preventDefault();
    alert("Socket Server is OFFLINE.\nFile operations (download, save, delete) are disabled until the server is started.");
    log('[WARN] Operation blocked: Server is OFFLINE.');
    return;
  }
  if (btn.classList.contains('btn-dl')) {
    log('Downloading "' + (btn.getAttribute('download')||'?') + '"...');
  } else if (btn.classList.contains('btn-sync')) {
    dlClient(btn.getAttribute('data-name'));
  } else if (btn.classList.contains('del') && !btn.hasAttribute('onclick')) {
    performDelete(btn.getAttribute('data-name'));
  }
});

// ── ZIP downloads ─────────────────────────────────────────────────
async function downloadFolderZip(foldername) {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nZIP download disabled.'); log('[WARN] ZIP blocked: Server OFFLINE.'); return; }
  log('Preparing ZIP for folder "' + foldername + '"...');
  const safeUrl = '/api/download-folder-zip/' + encodeURIComponent(foldername).replace(/%2F/g, '/');
  try {
    const res = await fetch(safeUrl);
    if (!res.ok) {
      const d = await res.json();
      log('ERR Folder ZIP: ' + (d.error || 'Failed to download'));
      return;
    }
    const blob = await res.blob();
    const cleanName = foldername.split('/').filter(Boolean).pop() || 'folder';
    triggerDownload(blob, cleanName + '.zip');
    log('OK Folder ZIP downloaded: ' + foldername + '.zip');
  } catch(e) {
    log('ERR Folder ZIP: ' + e);
  }
}

async function downloadSelectedZip() {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nZIP download disabled.'); log('[WARN] ZIP blocked: Server OFFLINE.'); return; }
  if (!_selectedFiles.size) { log('ERR No files selected.'); return; }
  const names = Array.from(_selectedFiles);
  log('Building ZIP for ' + names.length + ' file(s)...');
  try {
    const res = await fetch('/api/download-zip', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({filenames: names})
    });
    if (!res.ok) { const d=await res.json(); log('ERR '+d.error); return; }
    const blob = await res.blob();
    triggerDownload(blob, 'transfer_files.zip');
    log('OK ZIP downloaded: ' + names.length + ' file(s)');
  } catch(e) { log('ERR ZIP: ' + e); }
}

async function downloadAllZip() {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nZIP download disabled.'); log('[WARN] ZIP blocked: Server OFFLINE.'); return; }
  log('Building ZIP of all files and folders...');
  try {
    const res = await fetch('/api/download-all-zip');
    if (!res.ok) { const d=await res.json(); log('ERR '+d.error); return; }
    const blob = await res.blob();
    triggerDownload(blob, 'all_files.zip');
    log('OK All-files ZIP downloaded');
  } catch(e) { log('ERR ZIP: ' + e); }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ── Single file & folder actions ──────────────────────────────────
async function dlClient(name) {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nSaving files disabled.'); log('[WARN] Save blocked: Server OFFLINE.'); return; }
  log('Saving "' + name + '" to client/downloaded_files/...');
  try {
    const res  = await fetch('/api/download-to-client', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({filename: name})
    });
    const data = await res.json();
    if (data.ok) {
      log('OK Saved to client/downloaded_files/' + data.saved_as);
      alert('File saved to:\n' + data.dest_path);
    } else { log('ERR ' + data.error); }
  } catch(e) { log('ERR ' + e); }
}

async function performDelete(name) {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nFile deletion disabled.'); log('[WARN] Delete blocked: Server OFFLINE.'); return; }
  log('Deleting "' + name + '"...');
  try {
    const res  = await fetch('/api/delete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-Id': myClientId
      },
      body: JSON.stringify({filename: name, client_id: myClientId})
    });
    const data = await res.json();
    if (data.ok) {
      log('OK Deleted "' + name + '"');
      loadFiles();
      checkServer();
    } else {
      log('ERR ' + (data.error || 'delete failed'));
      alert(data.error || 'Delete failed: permission denied.');
    }
  } catch(e) { log('ERR ' + e); }
}

async function deleteFolder(foldername) {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nFolder deletion disabled.'); log('[WARN] Delete blocked: Server OFFLINE.'); return; }
  if (!confirm('Are you sure you want to delete entire folder "' + foldername + '" and all its contents?')) return;
  log('Deleting folder "' + foldername + '"...');
  try {
    const safeUrl = '/api/delete/' + encodeURIComponent(foldername).replace(/%2F/g, '/');
    const res  = await fetch(safeUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-Id': myClientId
      },
      body: JSON.stringify({client_id: myClientId})
    });
    const data = await res.json();
    if (data.ok) {
      log('OK Deleted folder "' + foldername + '"');
      loadFiles();
      checkServer();
    } else {
      log('ERR Cannot delete folder: ' + (data.error || 'Failed'));
      alert(data.error || 'Cannot delete folder: permission denied.');
    }
  } catch(e) {
    log('ERR Folder delete: ' + e);
  }
}

async function deleteSelected() {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nDelete selected disabled.'); log('[WARN] Delete blocked: Server OFFLINE.'); return; }
  if (!_selectedFiles.size) return;
  const allNames = Array.from(_selectedFiles);

  // Normal users are restricted to deleting their own uploaded files
  const names = IS_ADMIN ? allNames : allNames.filter(n => {
    const fObj = _allLoadedFiles.find(x => x.name === n);
    return fObj && fObj.uploader_id === myClientId;
  });

  if (!names.length) {
    alert("Permission Notice: You can only delete files that you uploaded from this device. Main server data and files from other devices cannot be deleted.");
    return;
  }

  if (names.length < allNames.length) {
    if (!confirm('You have selected ' + allNames.length + ' item(s), but only ' + names.length + ' were uploaded by this device.\n\nProceed to delete your ' + names.length + ' uploaded file(s)?')) return;
  } else {
    if (!confirm('Delete ' + names.length + ' file(s) uploaded by your device?')) return;
  }

  log('Deleting ' + names.length + ' selected file(s)...');
  let ok = 0;
  for (const name of names) {
    try {
      const res  = await fetch('/api/delete', {
        method:'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Client-Id': myClientId
        },
        body: JSON.stringify({filename: name, client_id: myClientId})
      });
      const data = await res.json();
      if (data.ok) ok++;
      else log('ERR Cannot delete "' + name + '": ' + (data.error || 'Failed'));
    } catch(e) { log('ERR ' + name + ': ' + e); }
  }
  log('OK Deleted ' + ok + '/' + names.length + ' file(s)');
  loadFiles();
  checkServer();
}

async function deleteAllFiles() {
  if (!serverOnline) { alert('Socket Server is OFFLINE.\nPurge disabled.'); log('[WARN] Purge blocked: Server OFFLINE.'); return; }
  if (!IS_ADMIN) {
    alert("Purge is only available on the main server host.");
    return;
  }
  if (!confirm('Are you sure you want to PURGE all files and folders from the server?')) return;
  log('Purging all files and folders...');
  try {
    const res  = await fetch('/api/delete-all', {method:'POST'});
    const data = await res.json();
    if (data.ok) { log('OK Purged ' + data.deleted_count + ' items'); loadFiles(); checkServer(); }
    else { alert(data.error || 'Purge failed'); }
  } catch(e) { log('ERR ' + e); }
}

// ── Helpers ───────────────────────────────────────────────────────
const MAX_LOG_LINES = 1000;
let _logLines = [];

try {
  const saved = localStorage.getItem('sft_activity_logs');
  if (saved) {
    const parsed = JSON.parse(saved);
    if (Array.isArray(parsed)) _logLines = parsed;
  }
} catch(_) {}

function renderLogs() {
  const box = document.getElementById('logs');
  if (!box) return;
  // Show newest at top — reverse display order
  box.textContent = _logLines.slice().reverse().join('\n');
  box.scrollTop = 0;
}

function log(m) {
  if (!m) return;
  let text = String(m).trim();
  if (!text) return;
  if (!text.startsWith('[')) {
    const ts = new Date().toLocaleTimeString();
    text = '[' + ts + '] ' + text;
  }
  // Deduplicate consecutive identical lines
  if (_logLines.length && _logLines[_logLines.length - 1] === text) return;
  _logLines.push(text);
  if (_logLines.length > MAX_LOG_LINES) {
    _logLines.shift();
  }
  renderLogs();
  try {
    localStorage.setItem('sft_activity_logs', JSON.stringify(_logLines.slice(-300)));
  } catch(_) {}
}

function clearLogs() {
  _logLines = [];
  try { localStorage.removeItem('sft_activity_logs'); } catch(_) {}
  renderLogs();
}

function fmtBytes(b) {
  if (!b) return '0 B';
  const k = 1024, sizes = ['B','KB','MB','GB'];
  const i = Math.floor(Math.log(b)/Math.log(k));
  return parseFloat((b/Math.pow(k,i)).toFixed(2)) + ' ' + sizes[i];
}

function esc(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Init ─────────────────────────────────────────────────────────
renderLogs();
checkServer();
loadFiles();
setInterval(checkServer, 3000);

const sse = new EventSource('/api/logs/stream');
sse.onmessage = e => {
  try {
    const payload = JSON.parse(e.data);
    if (payload.type === 'history' && Array.isArray(payload.logs)) {
      payload.logs.forEach(msg => {
        let text = String(msg).trim();
        if (text && !_logLines.includes(text) && !_logLines.some(l => l.endsWith(text) || text.endsWith(l))) {
          log(text);
        }
      });
    } else if (payload.type === 'file_changed') {
      loadFiles();                        // auto-sync: refresh file list on ALL browsers
    } else if (payload.type === 'log' && payload.msg) {
      log(payload.msg);                   // show in Activity Log
    } else if (typeof payload === 'string') {
      log(payload);                       // legacy plain string
    }
  } catch(_) {}
};
sse.onerror = () => {
  // SSE reconnects automatically; no action needed
};
</script>
</body>
</html>"""


if __name__ == "__main__":
    DASHBOARD_PORT = 8080
    print()
    print("=" * 58)
    print("  Socket File Transfer System — Web Dashboard")
    print("=" * 58)
    print("  Local URL: http://127.0.0.1:{}".format(DASHBOARD_PORT))
    print("  Wi-Fi LAN: http://{}:{}".format(LOCAL_LAN_IP, DASHBOARD_PORT))
    print("=" * 58)
    print()
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, threaded=True)
