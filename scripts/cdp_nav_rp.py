#!/usr/bin/env python3
"""
Use the already-logged-in chrome session (port 9333) to:
1. Navigate to Reverse Proxy settings
2. Create rule: listen port 8081, domain canival.fyi, backend http://127.0.0.1:8080
3. Enable tcp4 + tcp6
"""
import json
import time
import base64
import urllib.request
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def find_logged_in_page():
    pages = get_pages(9333)
    # Find lucky page (already logged in - url contains #/about or #/xxx not #/login)
    for p in pages:
        if p['type'] == 'page' and 'localhost:16601' in p['url']:
            print(f"[+] Found lucky page: {p['url']}")
            return p
    return None


def main():
    page = find_logged_in_page()
    if not page:
        print("No lucky page found, opening new...")
        page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])

    # 1. Navigate to reverse proxy settings page
    print("[+] Navigate to reverse proxy page")
    nav_script = r"""
// Try to navigate by changing hash
(() => {
    const paths = [
        '#/reverseproxy',
        '#/menu/reverseproxy',
        '#/ReverseProxy',
    ];
    window.location.hash = paths[0];
    return {now: window.location.href};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": nav_script, "returnByValue": True})
    time.sleep(3)

    # Screenshot to confirm page
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-rp-page.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("[+] Screenshot: lucky-rp-page.png")

    # Try to find the reverse proxy UI by looking at text content
    scan_page = r"""
(() => {
    const body = document.body?.innerText || '';
    const text = body.substring(0, 2000);
    const buttons = Array.from(document.querySelectorAll('button')).map(b => ({text: b.textContent.trim(), cls: b.className}));
    const links = Array.from(document.querySelectorAll('a, [role="menuitem"]')).map(a => ({text: a.textContent.trim()?.substring(0,50) || ''})).filter(a => a.text);
    const sidebar = Array.from(document.querySelectorAll('.el-menu, .sidebar, .menu, nav')).map(n => n.innerText.substring(0,1000));
    return {
        page: text,
        buttons: buttons.slice(0,30),
        sidebarText: sidebar.join('\n\n---\n\n').substring(0,2000),
        hash: window.location.hash,
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": scan_page, "returnByValue": True})
    res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Page content hash={res.get('hash')}")
    print(f"[+] Sidebar/menu text: {json.dumps(res.get('sidebarText'), ensure_ascii=False)}")
    print(f"[+] Buttons: {json.dumps(res.get('buttons'), ensure_ascii=False, indent=2)}")

    ws.close()


if __name__ == "__main__":
    main()
