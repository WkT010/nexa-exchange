#!/usr/bin/env python3
"""
Download the lucky_reverseproxy-*.js chunk to enumerate API endpoints used,
then call them directly via the browser's fetch (in logged-in context).
"""
import json
import time
import base64
import urllib.request
import os
import sys
import subprocess
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def find_logged_in_page():
    pages = get_pages(9333)
    for p in pages:
        if p['type'] == 'page' and 'localhost:16601' in p['url'] and 'login' not in p['url'].lower():
            return p
    return None


def main():
    # 1. Download the reverseproxy JS module
    print("[+] Downloading reverse proxy JS chunk...")
    resp = urllib.request.urlopen("http://localhost:16601/static/js/lucky_reverseproxy-Do5lv6LM.js", timeout=10)
    js_text = resp.read().decode("utf-8", errors="replace")
    print(f"    Size: {len(js_text)} bytes")

    # Extract quoted strings that look like API paths (/api/...)
    api_paths = re.findall(r'["\'](/api/[^"\']{1,80})["\']', js_text)
    api_paths = sorted(set(api_paths))
    print(f"\n[+] API endpoints found in reverseproxy module ({len(api_paths)}):")
    for p in api_paths:
        print(f"    {p}")

    # Also extract any non-API action/parameter strings that look important
    important_strs = re.findall(r'["\']([A-Za-z_/][A-Za-z0-9_/\-]{2,40})["\']', js_text)
    filtered = [s for s in important_strs if re.search(r'(?i)list|add|delete|update|save|rule|proxy|status|domain|host|port|listen|backend|forward|sub|create|get|set|enable|type', s)]
    filtered = sorted(set(filtered))
    print(f"\n[+] Important strings ({len(filtered)}):")
    for s in filtered[:60]:
        print(f"    {s}")

    # 2. Now use a logged-in browser context to try each endpoint
    page = find_logged_in_page()
    if not page:
        print("\n[!] No logged-in page found, skipping API test.")
        return

    ws = SimpleWS(page["webSocketDebuggerUrl"])

    # Test all reverseproxy API endpoints with fetch in browser
    test_script = r"""
(async () => {
    const paths = APIPATHS_PLACEHOLDER;
    const results = [];
    for (const path of paths) {
        try {
            // Try GET first
            const r = await fetch(path, {credentials: 'same-origin'});
            const text = await r.text();
            let json;
            try { json = JSON.parse(text); } catch(e){}
            results.push({
                method: 'GET',
                path,
                status: r.status,
                ret: typeof json === 'object' && json ? (json.ret ?? null) : null,
                keys: typeof json === 'object' && json ? Object.keys(json).slice(0,10) : null,
                preview: typeof json === 'object' && json ? JSON.stringify(json).substring(0,200) : text.substring(0,200),
            });
        } catch(e) {
            results.push({method:'GET', path, error: String(e).substring(0,200)});
        }
    }
    return results;
})()
""".replace("APIPATHS_PLACEHOLDER", json.dumps(api_paths))

    print("\n[+] Testing each API endpoint via browser fetch...")
    r = cdp_call(ws, "Runtime.evaluate", {
        "expression": test_script,
        "returnByValue": True,
        "awaitPromise": True,
    })
    results = r.get('result', {}).get('result', {}).get('value', []) if r else []
    for res in results:
        if res.get('status') == 404 or res.get('status') is None:
            continue  # Skip 404s
        status = res.get('status')
        path = res.get('path')
        method = res.get('method')
        ret = res.get('ret')
        preview = res.get('preview', '')
        if len(preview) > 180:
            preview = preview[:180] + "..."
        print(f"    {method:>4} {path:<50} -> HTTP {status} ret={ret} preview={preview}")

    ws.close()


if __name__ == "__main__":
    main()
