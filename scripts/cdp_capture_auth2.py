#!/usr/bin/env python3
"""
Capture authenticated XHR patterns but with longer timeout. Split into multiple steps to avoid timeout.
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


def ensure_chrome():
    try:
        get_pages(9333)
    except Exception:
        subprocess.Popen([
            "google-chrome", "--no-sandbox", "--headless=new", "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--user-data-dir=/tmp/chrome-cdp-profile",
            "about:blank",
        ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(8)


def main():
    restart_lucky()
    ensure_chrome()
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(4)

    # Step 1: Install hooks and login separately
    install_hooks = r"""
(() => {
    window.__captures = [];
    const OrigXHR = window.XMLHttpRequest;
    window.XMLHttpRequest = function() {
        const xhr = new OrigXHR();
        const req = {headers: {}};
        const origOpen = xhr.open;
        const origSend = xhr.send;
        const origSetHeader = xhr.setRequestHeader;
        xhr.open = function(method, url) {
            req.method = method;
            req.url = url;
            return origOpen.apply(this, arguments);
        };
        xhr.setRequestHeader = function(name, value) {
            req.headers[name] = value;
            return origSetHeader.apply(this, arguments);
        };
        xhr.addEventListener('loadend', function() {
            if (req.url && req.url.includes('/api/')) {
                window.__captures.push({
                    method: req.method,
                    url: req.url,
                    headers: req.headers,
                    status: xhr.status,
                    responsePreview: (xhr.responseText || '').substring(0, 300),
                });
            }
        });
        return xhr;
    };
    return {ok: true};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": install_hooks, "returnByValue": True}, timeout=10)
    print(f"[+] Hooks installed: {r}")

    # Step 2: Login - longer timeout
    login_script = r"""
(async () => {
    const inputs = Array.from(document.querySelectorAll('input'));
    const ai = inputs.find(i => i.placeholder === '默认666' && i.type === 'text');
    const pi = inputs.find(i => i.placeholder === '默认666' && i.type === 'password');
    const setValue = (el, val) => {
        const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        s.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles:true}));
    };
    setValue(ai, '666'); setValue(pi, '666');
    await new Promise(r => setTimeout(r, 400));
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => /登录|Login/.test(b.textContent || ''));
    if (loginBtn) loginBtn.click();
    await new Promise(r => setTimeout(r, 4000));
    return {hash: window.location.hash};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_script, "returnByValue": True, "awaitPromise": True}, timeout=60)
    print(f"[+] Login done: {r.get('result', {}).get('result', {}).get('value', {}) if r else 'error'}")

    # Step 3: Collect captures
    dump_script = r"""
(() => {
    // Filter out the login call itself from captures
    const authed = (window.__captures || []).filter(c => !c.url.includes('/api/login'));
    return {
        totalCaptures: (window.__captures || []).length,
        authedCount: authed.length,
        captures: authed.slice(0, 20),
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": dump_script, "returnByValue": True}, timeout=10)
    dump = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Captures: total={dump.get('totalCaptures')} authed={dump.get('authedCount')}")
    for c in dump.get("captures", []):
        print(f"\n  {c.get('method')} {c.get('url')}")
        print(f"    status={c.get('status')}")
        for h, v in (c.get('headers') or {}).items():
            if len(v) > 120:
                v = v[:120] + "..."
            print(f"    {h}: {v}")
        rp = c.get('responsePreview', '')
        if rp:
            try:
                j = json.loads(rp)
                print(f"    json: ret={j.get('ret')} msg={str(j.get('msg',''))[:80]}")
            except Exception:
                print(f"    resp: {rp[:200]}")

    ws.close()


if __name__ == "__main__":
    main()
