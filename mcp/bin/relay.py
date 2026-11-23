#!/usr/bin/env python3
"""Local CONNECT relay for the Xiaohongshu MCP's bundled Chrome.

Why this exists (2026-11-23, verified in this sandbox):
- The VM has no direct internet; curl reaches the web only through the
  egress proxy, and curl to xiaohongshu.com via that proxy works (302).
- The bundled Chrome, pointed at the same egress proxy, gets
  ERR_TUNNEL_CONNECTION_FAILED for every site, while curl and a raw
  socket CONNECT with the same bytes get 200. A localhost relay that
  forwards Chrome's exact CONNECT bytes to the egress proxy gets 200,
  and Chrome then loads example.com fine.
- The egress proxy MITMs TLS, so Chrome also needs
  --ignore-certificate-errors (added by the chrome wrapper, see below).

This relay only forwards CONNECT tunnels to the upstream proxy given
by the XHS_UPSTREAM_PROXY environment variable ("host:port", no auth).
It never sees plaintext: after CONNECT, bytes are relayed blindly in
both directions. It binds only
127.0.0.1:8888, so only local processes can use it. No credentials,
cookies or page content are logged - only the CONNECT line and the
proxy's first response line.

Usage: XHS_UPSTREAM_PROXY=<host:port> python3 bin/relay.py
(runs in foreground, log to stdout). If your network needs no proxy,
you do not need this relay at all -- point XHS_PROXY at nothing and
let Chrome connect directly.
"""
import os
import socket
import threading

LISTEN = ("127.0.0.1", 8888)
UPSTREAM_HOST, UPSTREAM_PORT = os.environ["XHS_UPSTREAM_PROXY"].split(":")
UPSTREAM = (UPSTREAM_HOST, int(UPSTREAM_PORT))


def pump(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client):
    upstream = None
    try:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = client.recv(4096)
            if not chunk:
                return
            data += chunk
            if len(data) > 65536:
                return
        print("CONNECT:", data.split(b"\r\n")[0].decode("utf-8", "replace"), flush=True)
        upstream = socket.create_connection(UPSTREAM, timeout=15)
        upstream.sendall(data)
        resp = upstream.recv(4096)
        print("PROXY:", resp.split(b"\r\n")[0].decode("utf-8", "replace"), flush=True)
        client.sendall(resp)
        if not resp.startswith(b"HTTP/1.1 200"):
            return
        threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
        pump(upstream, client)
    except OSError as exc:
        print("relay error:", exc, flush=True)
    finally:
        for sock in (client, upstream):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


def main():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(LISTEN)
    server.listen(16)
    print(f"relay listening on 127.0.0.1:8888 -> {UPSTREAM[0]}:{UPSTREAM[1]}", flush=True)
    while True:
        client, _ = server.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
