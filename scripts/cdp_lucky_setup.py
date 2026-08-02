#!/usr/bin/env python3
"""
Login to Lucky and configure reverse proxy using CDP (Chrome DevTools Protocol)
via raw HTTP websocket connection. No external dependencies beyond stdlib.
"""
import json
import time
import base64
import urllib.request
import hashlib
import struct
import socket
import ssl
from urllib.parse import urlparse


def get_pages(port=9333):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list")
    return json.loads(resp.read().decode())


def new_page(port=9333, url="about:blank"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?{urllib.request.quote(url)}",
        method="PUT",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode())


# Minimal WebSocket client
class SimpleWS:
    def __init__(self, url):
        u = urlparse(url)
        host = u.hostname
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query

        self.sock = socket.create_connection((host, port), timeout=30)
        # Perform HTTP upgrade handshake
        key = base64.b64encode(hashlib.sha1(os.urandom(16) if False else b"0123456789012345").digest()).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.sock.sendall(handshake.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            data = self.sock.recv(4096)
            if not data:
                raise Exception("WS handshake failed")
            buf += data
        header_end = buf.index(b"\r\n\r\n")
        headers = buf[:header_end].decode()
        print(f"[WS] Handshake response: {headers.splitlines()[0]}")
        self._leftover = buf[header_end + 4:]

    def _recv_exact(self, n):
        data = self._leftover
        self._leftover = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise Exception("WS closed")
            data += chunk
        return data

    def send_text(self, msg):
        payload = msg.encode()
        # Build frame: FIN + opcode TEXT (1), no mask (we're client but skip mask for simple; need mask)
        # Client MUST mask
        mask_key = b"\x01\x02\x03\x04"
        masked = bytes([b ^ mask_key[i % 4] for i, b in enumerate(payload)])
        header = bytearray()
        header.append(0x81)  # FIN + text
        plen = len(masked)
        if plen < 126:
            header.append(0x80 | plen)
        elif plen < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", plen))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", plen))
        header.extend(mask_key)
        frame = bytes(header) + masked
        self.sock.sendall(frame)

    def recv_text(self, timeout=15):
        self.sock.settimeout(timeout)
        while True:
            first = self._recv_exact(1)[0]
            fin = (first & 0x80) != 0
            opcode = first & 0x0F
            if opcode == 0x08:  # close
                return None
            second = self._recv_exact(1)[0]
            masked = (second & 0x80) != 0
            plen = second & 0x7F
            if plen == 126:
                plen = struct.unpack(">H", self._recv_exact(2))[0]
            elif plen == 127:
                plen = struct.unpack(">Q", self._recv_exact(8))[0]
            if masked:
                mask_key = self._recv_exact(4)
            else:
                mask_key = None
            payload = self._recv_exact(plen) if plen > 0 else b""
            if mask_key:
                payload = bytes([b ^ mask_key[i % 4] for i, b in enumerate(payload)])
            if opcode == 0x01:  # text
                return payload.decode()
            if opcode == 0x02:  # binary, ignore
                continue
            if opcode == 0x09:  # ping, pong
                continue

    def close(self):
        try:
            self.sock.close()
        except:
            pass


import os


def cdp_call(ws, method, params=None, wait_for_response=True, timeout=15):
    cdp_id = int(time.time() * 1000) & 0xFFFFFF
    msg = json.dumps({"id": cdp_id, "method": method, "params": params or {}})
    ws.send_text(msg)
    if not wait_for_response:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = ws.recv_text(timeout=max(1, int(deadline - time.time()) + 1))
        if resp is None:
            return None
        try:
            data = json.loads(resp)
        except:
            continue
        if data.get("id") == cdp_id:
            return data
    return None


def main():
    # 1. Start chrome headless if not running
    import subprocess
    # check if chrome running
    pages = []
    try:
        pages = get_pages(9333)
        print(f"[+] Found chrome with {len([p for p in pages if p['type']=='page'])} pages")
    except Exception as e:
        print(f"[+] Chrome not running ({e}), starting...")
        subprocess.Popen([
            "google-chrome",
            "--no-sandbox",
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=/tmp/chrome-cdp-profile",
            "about:blank",
        ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(8)
        pages = get_pages(9333)

    # 2. Navigate to Lucky login page
    print("[+] Opening Lucky login page...")
    page = new_page(9333, "http://localhost:16601/")
    print(f"    page id={page.get('id')} url={page.get('url')}")
    ws_url = page["webSocketDebuggerUrl"]
    ws = SimpleWS(ws_url)
    time.sleep(3)

    # 3. Take DOM snapshot (just print title and some elements)
    r = cdp_call(ws, "Runtime.evaluate", {"expression": "document.title"})
    title = r.get("result", {}).get("result", {}).get("value", "") if r else ""
    print(f"[+] Page title: {title}")

    # 4. Fill login form: need to find Account and Password inputs, then submit
    # First check the page, look for the login form fields by placeholder
    r = cdp_call(ws, "Runtime.evaluate", {
        "expression": """
(() => {
    // Get all inputs on page
    const inputs = Array.from(document.querySelectorAll('input'));
    return inputs.map(i => ({
        tag: i.tagName,
        name: i.name || '',
        type: i.type || '',
        placeholder: i.placeholder || '',
        model: Object.keys(i).filter(k => k.startsWith('_')).length ? 'vue' : '',
        outerHTML: i.outerHTML.substring(0,200)
    }));
})()
""",
        "returnByValue": True,
    })
    print(f"[+] Inputs on page: {json.dumps(r, indent=2, ensure_ascii=False) if r else 'N/A'}")

    # 5. Take screenshot to show user
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        img_data = base64.b64decode(r["result"]["data"])
        with open("/workspace/lucky-login-page.png", "wb") as f:
            f.write(img_data)
        print(f"[+] Screenshot saved: lucky-login-page.png ({len(img_data)} bytes)")

    ws.close()


if __name__ == "__main__":
    main()
