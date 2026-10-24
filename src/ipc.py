"""
Single-Instance and IPC Coordinator for PDF Merger.
Guarantees that multiple files selected in Windows Explorer are handled by a SINGLE GUI window.
"""

import socket
import json
import threading
import time
import sys
import os
from typing import List, Callable, Optional, Tuple

DEFAULT_IPC_PORT = 52199


class MasterIPCServer:
    """Master instance listener socket that receives files from concurrent instances."""

    def __init__(self, port: int, initial_files: List[str]):
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.files_lock = threading.Lock()
        self.collected_files: List[str] = list(initial_files)
        self.on_files_received: Optional[Callable[[List[str]], None]] = None

    def start_listening(self, server_sock: socket.socket):
        self.server_socket = server_sock
        self.server_socket.listen(30)
        self.server_socket.settimeout(0.5)
        self.is_running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def set_callback(self, callback: Callable[[List[str]], None]):
        """Sets the GUI callback to be notified when new files arrive."""
        with self.files_lock:
            self.on_files_received = callback
            if self.collected_files and callback:
                pending = list(self.collected_files)
                callback(pending)

    def _listen_loop(self):
        while self.is_running and self.server_socket:
            try:
                conn, _ = self.server_socket.accept()
            except socket.timeout:
                continue
            except Exception:
                break

            try:
                conn.settimeout(1.5)
                data = b""
                while not data.endswith(b"\n") and len(data) < 2 * 1024 * 1024:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk

                if data:
                    try:
                        msg = json.loads(data.decode("utf-8").strip())
                        if msg.get("cmd") == "add_files":
                            incoming = msg.get("files", [])
                            if incoming:
                                with self.files_lock:
                                    for f in incoming:
                                        if f not in self.collected_files:
                                            self.collected_files.append(f)
                                    if self.on_files_received:
                                        self.on_files_received(incoming)
                        conn.sendall(b'{"status":"ok"}\n')
                    except Exception:
                        pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def stop(self):
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None


def send_files_to_master_with_retry(files: List[str], port: int = DEFAULT_IPC_PORT, max_wait_sec: float = 3.5) -> bool:
    """
    Attempts to connect to the master instance and deliver file paths.
    Retries for up to max_wait_sec to handle instances launching concurrently with the master.
    """
    payload = json.dumps({"cmd": "add_files", "files": files}).encode("utf-8") + b"\n"
    start_time = time.time()

    while time.time() - start_time < max_wait_sec:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            s.sendall(payload)
            resp = s.recv(1024)
            if b"ok" in resp:
                s.close()
                return True
        except (socket.error, OSError):
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        time.sleep(0.05)

    return False


def setup_single_instance(initial_files: List[str], port: int = DEFAULT_IPC_PORT) -> Tuple[bool, Optional[MasterIPCServer]]:
    """
    Guarantees single instance election atomically at startup without SO_REUSEADDR.
    Returns:
        (True, master_server) if this process is the MASTER.
        (False, None) if this process handed off its files to the MASTER and should exit.
    """
    # 1. Try atomic bind WITHOUT SO_REUSEADDR
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        s.bind(("127.0.0.1", port))
        # SUCCESS: We are the Master instance!
        master = MasterIPCServer(port, initial_files)
        master.start_listening(s)
        return True, master
    except (socket.error, OSError):
        # Port is already bound: Another master instance exists or is starting up
        try:
            s.close()
        except Exception:
            pass

    # 2. We are a secondary instance -> Send files to Master
    delivered = send_files_to_master_with_retry(initial_files, port=port)
    if delivered:
        return False, None

    # Fallback if previous master was killed unexpectedly
    try:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", port))
        master = MasterIPCServer(port, initial_files)
        master.start_listening(s2)
        return True, master
    except Exception:
        return True, None
