#!/usr/bin/env python3
"""
Let's capture an actual successful API call from the UI by watching XHR.
The UI successfully makes authenticated requests because it has a request client configured.
We'll trigger /api/modules/list by clicking a menu item or re-rendering a view,
and capture the exact request format (URL + headers).
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

    script = r"""
(async () => {
    // Step 1: Login
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
    await new Promise(r => setTimeout(r, 2500));

    // Step 2: Now observe any XHR/fetch call from the UI by hooking, then trigger navigation
    // by clicking a menu item.
    window.__captures = [];

    // Deep hook XHR open/send + setRequestHeader to capture EVERYTHING
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
            if (req.url && req.url.includes('/api/') && !req.url.includes('/api/login')) {
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

    // Step 3: Navigate to different pages via hash changes to trigger API calls
    const routes = ['#/about', '#/status', '#/reverseproxy', '#/stun', '#/ddns', '#/setting'];
    for (const route of routes) {
        window.location.hash = route;
        await new Promise(r => setTimeout(r, 2000));
    }

    // Step 4: Also click any menu items we can find for 反向代理 / 内网穿透 / Web服务
    try {
        const allClickable = Array.from(document.querySelectorAll('button, a, .el-menu-item, [role="menuitem"], [class*="menu"]'));
        for (const el of allClickable.slice(0, 30)) {
            const txt = (el.textContent || '').trim();
            if (/反向代理|Web服务|内网穿透|端口转发|概览|总览|设置/.test(txt)) {
                try { el.click(); } catch(e){}
                await new Promise(r => setTimeout(r, 1000));
            }
        }
    } catch(e) {}

    return {captures: window.__captures, finalHash: window.location.hash};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True})
    results = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    captures = results.get("captures", [])
    print(f"[+] Captured {len(captures)} authenticated API calls:")
    for c in captures:
        print(f"\n  {c.get('method')} {c.get('url')}")
        print(f"    status={c.get('status')}")
        for h, v in (c.get('headers') or {}).items():
            if len(v) > 80:
                v = v[:80] + "..."
            print(f"    header: {h}: {v}")
        rp = c.get('responsePreview', '')
        if rp:
            print(f"    response: {rp[:200]}")
        # check if ret==0
        try:
            j = json.loads(c.get('responsePreview','').split("}")[0] + "}")
            if j.get('ret') == 0:
                print(f"    *** AUTHENTICATED CALL SUCCESS (ret=0) ***")
        except Exception:
            pass

    # Save screenshot
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-authed-calls.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("\n[+] Screenshot: lucky-authed-calls.png")

    ws.close()


if __name__ == "__main__":
    main()
