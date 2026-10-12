import socket
import threading
import base64
import urllib.parse
from typing import Dict, Optional, Tuple

class ProxyAuthBridge:
    """
    Transparent local loopback forwarder that injects Proxy-Authorization credentials
    so Chromium browsers can use authenticated HTTP proxies without prompting the user.
    """

    def __init__(self, upstream_host: str, upstream_port: int, username: str, password: str, local_port: int):
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.username = username
        self.password = password
        self.local_port = local_port
        self.auth_header = base64.b64encode(f"{username}:{password}".encode("utf-8"))
        self._running = False
        self._server_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.local_port))
        self._server_sock.listen(64)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self):
        while self._running:
            try:
                client_sock, _ = self._server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception:
                break

    def _pipe(self, src: socket.socket, dst: socket.socket):
        try:
            while self._running:
                data = src.recv(8192)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            try:
                src.close()
            except Exception:
                pass
            try:
                dst.close()
            except Exception:
                pass

    def _handle_client(self, client_sock: socket.socket):
        try:
            req = client_sock.recv(4096)
            if not req:
                client_sock.close()
                return

            up_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            up_sock.settimeout(12.0)
            up_sock.connect((self.upstream_host, self.upstream_port))

            # Inject Proxy-Authorization header
            lines = req.split(b"\r\n")
            new_lines = [lines[0], b"Proxy-Authorization: Basic " + self.auth_header]
            for l in lines[1:]:
                if not l.lower().startswith(b"proxy-authorization:"):
                    new_lines.append(l)
            new_req = b"\r\n".join(new_lines)
            up_sock.sendall(new_req)

            threading.Thread(target=self._pipe, args=(client_sock, up_sock), daemon=True).start()
            self._pipe(up_sock, client_sock)
        except Exception:
            try:
                client_sock.close()
            except Exception:
                pass

    def stop(self):
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass

class ProxyManager:
    """
    Manages active proxy bridges for multi-instance runner.
    """
    _instance: Optional["ProxyManager"] = None
    _bridges: Dict[str, ProxyAuthBridge] = {}
    _next_port = 19000

    @classmethod
    def get_instance(cls) -> "ProxyManager":
        if cls._instance is None:
            cls._instance = ProxyManager()
        return cls._instance

    @classmethod
    def setup_proxy_for_browser(cls, proxy_str: Optional[str]) -> Tuple[Optional[str], Optional[ProxyAuthBridge]]:
        """
        Parses proxy string. If it contains credentials (user:pass@host:port),
        spawns a local loopback forwarder and returns the local unauthenticated proxy URL.
        """
        if not proxy_str or not isinstance(proxy_str, str) or not proxy_str.strip():
            return None, None

        proxy_clean = proxy_str.strip()
        parsed = urllib.parse.urlparse(proxy_clean)

        # If no credentials, standard proxy string is returned as-is
        if not parsed.username or not parsed.password:
            return proxy_clean, None

        # Contains credentials: spin up local loopback bridge
        mgr = cls.get_instance()
        host = parsed.hostname
        port = parsed.port or 80
        user = parsed.username
        passwd = parsed.password

        bridge_key = f"{host}:{port}:{user}"
        if bridge_key in mgr._bridges:
            bridge = mgr._bridges[bridge_key]
            return f"http://127.0.0.1:{bridge.local_port}", bridge

        mgr._next_port += 1
        local_port = mgr._next_port
        bridge = ProxyAuthBridge(host, port, user, passwd, local_port)
        bridge.start()
        mgr._bridges[bridge_key] = bridge
        return f"http://127.0.0.1:{local_port}", bridge

    @classmethod
    def shutdown_all(cls):
        mgr = cls.get_instance()
        for bridge in mgr._bridges.values():
            bridge.stop()
        mgr._bridges.clear()
