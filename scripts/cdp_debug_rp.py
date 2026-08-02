#!/usr/bin/env python3
"""
Load lucky reverseproxy JS module and extract its API routes.
"""
import json
import time
import base64
import urllib.request
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def find_logged_in_page():
    pages = get_pages(9333)
    for p in pages:
        if p['type'] == 'page' and 'localhost:16601' in p['url'] and 'login' not in p['url'].lower():
            return p
    return None


def main():
    page = find_logged_in_page()
    if not page:
        print("Need logged-in page")
        return
    ws = SimpleWS(page["webSocketDebuggerUrl"])

    # 1. Load reverseproxy module by navigating to its hash and wait + check errors
    cdp_call(ws, "Runtime.evaluate", {"expression": "window.__errs=[]; window.addEventListener('error', e=>window.__errs.push(e.message||String(e.error)));", "returnByValue": True})

    nav_script = r"""
(async () => {
    // First make sure module is loaded
    try {
        // Force route
        window.location.hash = '#/reverseproxy';
        await new Promise(r => setTimeout(r, 5000));
        // Check for module by looking at loaded scripts
        const scripts = Array.from(document.querySelectorAll('script')).map(s => s.src).filter(Boolean);
        const moduleScripts = scripts.filter(s => s.includes('reverseproxy'));
        // Check console errors via our listener
        // Try clicking the sidebar menu item 反向代理 or 内网穿透 or Web服务
        const menuItems = Array.from(document.querySelectorAll('.el-menu-item, .menu-item, [role="menuitem"], a')).map(el => ({
            text: (el.textContent||'').trim().replace(/\s+/g,' ').substring(0,60),
            tag: el.tagName,
            id: el.id || '',
            cls: el.className || '',
        })).filter(m => m.text);
        const pageText = (document.body?.innerText || '').substring(0, 3000);
        const routes = window.__errs || [];
        return {
            scripts: scripts.filter(s => '/static/js/' in s).map(s => s.substring(s.lastIndexOf('/static/js/')+11, s.length > 60 ? 60 : s.length)),
            revproxy_scripts: moduleScripts,
            menu: menuItems.slice(0, 40),
            pageText,
            errs: routes.slice(0, 5),
            currentHash: window.location.hash,
        };
    } catch(e) { return {err: String(e)}; }
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": nav_script, "returnByValue": True, "awaitPromise": True})
    res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Hash={res.get('currentHash')}")
    print(f"[+] Errors={res.get('errs')}")
    print(f"[+] Scripts loaded: {json.dumps(res.get('scripts'), indent=2, ensure_ascii=False)}")
    print(f"[+] Reverse proxy scripts: {json.dumps(res.get('revproxy_scripts'), indent=2, ensure_ascii=False)}")
    print(f"[+] Menu items ({len(res.get('menu', []))} total):")
    for m in res.get('menu', []):
        print(f"    [{m['tag']}] {m['text']}")
    print(f"\n[+] Page text preview (page={res.get('pageText','')[:800]})")

    # 2. Screenshot
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-rp-full.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("\n[+] Screenshot: lucky-rp-full.png")

    ws.close()


if __name__ == "__main__":
    main()
