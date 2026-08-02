#!/usr/bin/env python3
"""
Configure Lucky reverse proxy via API calls directly (since we're logged in).
First check API endpoints for reverseproxy, then make calls.
"""
import json
import time
import base64
import urllib.request
import urllib.parse
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def restart_lucky():
    subprocess.run(["pkill", "-9", "-f", "lucky"], check=False)
    time.sleep(2)
    subprocess.Popen(
        ["nohup", "/opt/lucky_v2.13.4", "-c", "/goodluck/lucky.conf"],
        cwd="/goodluck",
        stdout=open("/tmp/lucky.log", "w"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(7)


def find_logged_in_page():
    pages = get_pages(9333)
    for p in pages:
        if p['type'] == 'page' and 'localhost:16601' in p['url'] and 'login' not in p['url'].lower():
            return p
    return None


class LuckyAPI:
    """Calls Lucky API by executing fetch() inside the logged-in browser context."""
    def __init__(self, ws):
        self.ws = ws
        self._req_id = 0

    def call(self, method, url_path, body=None, query=None):
        self._req_id += 1
        expr = f"""
(async () => {{
    try {{
        const url = {'"./api/" + json.dumps(url_path)[1:-1]' if not query else f'"./api/{url_path}?" + new URLSearchParams({json.dumps(query)}).toString()'};
        const init = {{
            method: {json.dumps(method)},
            credentials: 'same-origin',
        }};
        {f"init.headers = {{'Content-Type': 'application/json'}}; init.body = JSON.stringify({json.dumps(body)});" if body else ""}
        const resp = await fetch(url, init);
        const text = await resp.text();
        return {{status: resp.status, body: text.substring(0, 10000)}};
    }} catch(e) {{
        return {{error: String(e)}};
    }}
}})()
"""
        r = cdp_call(self.ws, "Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if not r or "error" in r:
            return {"error": str(r)}
        val = r.get("result", {}).get("result", {}).get("value", {})
        # Parse JSON body if possible
        if isinstance(val, dict) and "body" in val:
            try:
                val["json"] = json.loads(val["body"])
            except Exception:
                pass
        return val


def main():
    page = find_logged_in_page()
    if not page:
        restart_lucky()
        # Start chrome if not running
        try:
            get_pages(9333)
        except Exception:
            subprocess.Popen([
                "google-chrome", "--no-sandbox", "--headless=new", "--disable-gpu",
                "--disable-dev-shm-usage",
                "--remote-debugging-port=9333",
                "--user-data-dir=/tmp/chrome-cdp-profile",
                "http://localhost:16601/",
            ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
            time.sleep(10)
        # Login via CDP to be safe (auto login)
        print("[+] Need to re-login")
        return

    ws = SimpleWS(page["webSocketDebuggerUrl"])
    api = LuckyAPI(ws)

    # Step 1: Navigate to reverse proxy to ensure its Vue route is loaded
    nav = cdp_call(ws, "Runtime.evaluate", {
        "expression": "window.location.hash='#/reverseproxy'",
        "returnByValue": True,
    })
    time.sleep(3)

    # Step 2: Explore the reverseproxy API by trying common endpoints
    print("[+] Exploring reverse proxy API...")
    # Based on lucky pattern: /api/<module>/<action>
    for endpoint in [
        # Listing endpoints
        ("GET", "reverseproxy", None),
        ("GET", "reverseproxy/list", None),
        ("GET", "reverseproxy/List", None),
        ("GET", "reverseproxy/Get", None),
        ("GET", "reverseproxy/get", None),
        ("GET", "ReverseProxy/List", None),
        ("GET", "reverseproxy/rules", None),
        # Status endpoints
        ("GET", "reverseproxy/Status", None),
        ("GET", "reverseproxy/status", None),
    ]:
        method, path, body = endpoint
        r = api.call(method, path, body=body)
        status = r.get("status")
        json_body = r.get("json", None)
        summary = f"status={status}"
        if json_body is not None:
            summary += f" json_keys={list(json_body.keys()) if isinstance(json_body, dict) else type(json_body).__name__}"
        elif r.get("body"):
            summary += f" body_preview={str(r.get('body'))[:80]}"
        print(f"  {method:>4} /api/{path:<25} -> {summary}")

    # Step 3: Now look at what API endpoints the page actually fetches when loaded
    # Hook fetch/XHR to capture
    capture_and_reload = r"""
(async () => {
    window.__rp_cap = [];
    // Hook XHR (which lucky uses based on earlier capture)
    const OrigXHR = window.XMLHttpRequest;
    window.XMLHttpRequest = function() {
        const xhr = new OrigXHR();
        const origOpen = xhr.open;
        const origSend = xhr.send;
        let lastMethod, lastUrl;
        xhr.open = function(method, url) {
            lastMethod = method;
            lastUrl = url;
            return origOpen.apply(this, arguments);
        };
        xhr.send = function(body) {
            if (lastUrl && lastUrl.includes('/api/')) {
                window.__rp_cap.push({
                    type: 'xhr',
                    method: lastMethod,
                    url: lastUrl,
                    body: typeof body === 'string' ? body.substring(0,2000) : null,
                });
            }
            return origSend.apply(this, arguments);
        };
        return xhr;
    };
    // Trigger navigation by changing hash back and forth
    window.location.hash = '#/about';
    await new Promise(r => setTimeout(r, 500));
    window.location.hash = '#/reverseproxy';
    await new Promise(r => setTimeout(r, 3500));
    return {captured: window.__rp_cap};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {
        "expression": capture_and_reload,
        "returnByValue": True,
        "awaitPromise": True,
    })
    cap = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"\n[+] Captured XHR when loading reverse proxy page:")
    for c in cap.get("captured", []):
        print(f"  {c['method']:>4} {c['url']}")
        if c.get("body"):
            b_preview = c["body"]
            if len(b_preview) > 200:
                b_preview = b_preview[:200] + "...(trunc)"
            print(f"       body={b_preview}")

    # Step 4: Try to actually CREATE a reverse proxy rule by clicking the "add" button
    click_add = r"""
(() => {
    const bts = Array.from(document.querySelectorAll('button'));
    // Look for button with "Add", "Create", "New", or the Chinese equivalents 新增/添加
    const addBtn = bts.find(b => {
        const t = (b.textContent || '').trim();
        return /新增|添加|Add|Create|New|新建/.test(t);
    });
    if (!addBtn) {
        // Look for any primary buttons and describe all buttons
        return {all: bts.map(b => ({t: (b.textContent||'').trim().substring(0,30), cls: (b.className||'').substring(0,100)}))};
    }
    addBtn.click();
    return {clicked: (addBtn.textContent || '').trim()};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": click_add, "returnByValue": True})
    add_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"\n[+] Click add button result: {json.dumps(add_res, ensure_ascii=False, indent=2)}")
    time.sleep(1)

    # Screenshot
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-rp-after.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("\n[+] Screenshot: lucky-rp-after.png")

    ws.close()


if __name__ == "__main__":
    main()
