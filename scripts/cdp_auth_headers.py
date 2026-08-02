#!/usr/bin/env python3
"""
Login to Lucky (XHR-based), get JWT token from localStorage, then use XHR with proper headers/token
to enumerate and call webservice/reverse proxy APIs.

The token is stored as part of `localStorage.lucky` JSON object.
Lucky's XHR client likely adds Authorization: Bearer or x-token header.
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

    # Login and then call webservice APIs using the same HTTP client pattern as Lucky UI
    master_script = r"""
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

    // Step 2: Get the request helper (R function) — the same helper that Login.js uses.
    // We can't import directly but we can use the page's axios/fetch wrappers or look at how Lucky's XHR is configured.
    // First observe one successful API call /api/modules/list — then replicate it.
    const results = {};

    // Observation: XHR client passes `?_=<timestamp>` query parameter. Token header name unknown.
    // Try: capture any XHR request to see headers by making one manually
    // First use fetch directly with localStorage token by trying common header patterns
    const luckyStorage = JSON.parse(localStorage.getItem('lucky') || '{}');
    const TOKEN = luckyStorage.token;
    results.token = TOKEN ? TOKEN.substring(0, 40) + "..." : null;
    results.storageKeys = Object.keys(luckyStorage);

    // Test GET /api/info with various auth headers using raw XHR
    function tryRequest(url, opts={}) {
        return new Promise((resolve) => {
            const xhr = new XMLHttpRequest();
            const qs = (url.includes('?') ? '&' : '?') + '_=' + Date.now();
            xhr.open(opts.method || 'GET', url + qs);
            xhr.withCredentials = true;
            if (TOKEN) {
                if (opts.tokenHeader) {
                    xhr.setRequestHeader(opts.tokenHeader, TOKEN);
                }
                if (opts.authHeader) {
                    xhr.setRequestHeader('Authorization', 'Bearer ' + TOKEN);
                }
                if (opts.setAllCandidates) {
                    xhr.setRequestHeader('Token', TOKEN);
                    xhr.setRequestHeader('X-Token', TOKEN);
                    xhr.setRequestHeader('Lucky-Token', TOKEN);
                    xhr.setRequestHeader('token', TOKEN);
                    xhr.setRequestHeader('x-token', TOKEN);
                    xhr.setRequestHeader('Authorization', 'Bearer ' + TOKEN);
                }
            }
            if (opts.body) {
                xhr.setRequestHeader('Content-Type', 'application/json');
            }
            xhr.onload = () => resolve({status: xhr.status, body: xhr.responseText.substring(0, 2000)});
            xhr.onerror = () => resolve({status: -1, error: 'network'});
            xhr.send(opts.body ? JSON.stringify(opts.body) : null);
        });
    }

    // Find correct token header by brute-force on /api/info endpoint
    const tests = [
        {name:'no auth header'},
        {name:'Authorization Bearer', authHeader:true},
        {name:'Token header', tokenHeader:'Token'},
        {name:'X-Token header', tokenHeader:'X-Token'},
        {name:'token lowercase', tokenHeader:'token'},
        {name:'setAllCandidates', setAllCandidates:true},
    ];
    results.infoTests = [];
    for (const t of tests) {
        const r = await tryRequest('./api/info', t);
        results.infoTests.push({name:t.name, status:r.status, body: r.body && r.body.length < 100 ? r.body : r.body.substring(0,150)});
    }

    // Also use Luckys own request client if possible: find the global $http or axios
    const possibleGlobals = Object.keys(window).filter(k => /axios|http|request|\$http/i.test(k));
    results.interestingGlobals = possibleGlobals;

    return results;
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": master_script, "returnByValue": True, "awaitPromise": True})
    results = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"=== RESULTS ===")
    print(json.dumps(results, indent=2, ensure_ascii=False))

    ws.close()


if __name__ == "__main__":
    main()
