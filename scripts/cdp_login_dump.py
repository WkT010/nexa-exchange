#!/usr/bin/env python3
"""
Login failed via fetch (session not shared between fetch API and XHR due to Vue router state).
Let's use XHR like the Lucky UI does, AND ensure we set the token correctly.
First verify if we actually got token after login - check localStorage/cookies.
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

    # Login and dump session state
    login_dump = r"""
(async () => {
    // Fill form
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

    // Hook XHR to observe /api/login response and headers/token
    window.__loginResp = null;
    const OrigXHR = window.XMLHttpRequest;
    window.XMLHttpRequest = function() {
        const xhr = new OrigXHR();
        const origOpen = xhr.open;
        const origSend = xhr.send;
        let lastUrl;
        xhr.open = function(method, url) {
            lastUrl = url;
            return origOpen.apply(this, arguments);
        };
        xhr.addEventListener('load', function() {
            if (lastUrl && lastUrl.includes('/api/login')) {
                window.__loginResp = {
                    status: xhr.status,
                    statusText: xhr.statusText,
                    responseText: xhr.responseText?.substring(0,2000),
                    responseHeaders: xhr.getAllResponseHeaders(),
                    cookies: document.cookie,
                    storageToken: localStorage.getItem('token'),
                    storageRaw: JSON.stringify(Object.fromEntries(Object.entries(localStorage))),
                };
            }
        });
        return xhr;
    };

    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => /登录|Login/.test(b.textContent || ''));
    if (loginBtn) loginBtn.click();

    await new Promise(r => setTimeout(r, 3000));
    return {
        loginResp: window.__loginResp,
        finalHash: window.location.hash,
        finalStorage: JSON.stringify(Object.fromEntries(Object.entries(localStorage))),
        finalCookies: document.cookie,
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_dump, "returnByValue": True, "awaitPromise": True})
    dump = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print("=== LOGIN DUMP ===")
    print(json.dumps(dump, indent=2, ensure_ascii=False))

    ws.close()


if __name__ == "__main__":
    main()
