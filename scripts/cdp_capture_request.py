#!/usr/bin/env python3
"""
Check XMLHttpRequest too (not just fetch), find what value of Password is being sent.
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
    urllib.request.urlopen("http://localhost:16601/", timeout=5).read()


def main():
    restart_lucky()
    try:
        get_pages(9333)
    except Exception:
        subprocess.Popen([
            "google-chrome",
            "--no-sandbox",
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--user-data-dir=/tmp/chrome-cdp-profile",
            "about:blank",
        ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(8)

    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(4)

    # Hook both XHR and fetch and also inspect the password field value and Vue o.value
    hook_script = r"""
(() => {
    window.__captures = [];
    // Hook Fetch
    const origFetch = window.fetch;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
        if (url.includes('/api/')) {
            const opts = args[1] || {};
            window.__captures.push({
                type: 'fetch',
                url,
                method: opts.method || 'GET',
                body: typeof opts.body === 'string' ? opts.body : null,
            });
        }
        return origFetch.apply(this, args);
    };
    // Hook XHR
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
                window.__captures.push({
                    type: 'xhr',
                    url: lastUrl,
                    method: lastMethod,
                    body: typeof body === 'string' ? body : null,
                });
            }
            return origSend.apply(this, arguments);
        };
        return xhr;
    };
    // Also capture the o.value right before sending: walk Vue component up to find setupState
    window.__inspectLogin = function() {
        const inputs = Array.from(document.querySelectorAll('input'));
        const pw = inputs.find(i => i.type === 'password');
        if (!pw) return {err:'no pw input'};
        let node = null;
        for (const k of Object.keys(pw)) {
            if (k.startsWith('__vueParentComponent')) {
                node = pw[k];
                break;
            }
        }
        let depth = 0;
        while (node && depth < 15) {
            const ss = node.setupState;
            if (ss) {
                // Look for the function R or the o ref
                for (const [k,v] of Object.entries(ss)) {
                    if (typeof v === 'object' && v && 'value' in v) {
                        const val = v.value;
                        if (val && typeof val === 'object') {
                            const str = JSON.stringify(val);
                            if (str.includes('Account')) {
                                return {found_o_key: k, o_value: str.substring(0, 1000)};
                            }
                        }
                    }
                    if (k === 'o' || k.toLowerCase().includes('form') || k.toLowerCase().includes('login')) {
                        if (typeof v === 'object' && v && 'value' in v) {
                            return {key: k, value_json: JSON.stringify(v.value).substring(0,2000)};
                        }
                    }
                }
            }
            node = node.parent;
            depth++;
        }
        return {err: 'not found'};
    };
    return {ok: true};
})()
"""
    cdp_call(ws, "Runtime.evaluate", {"expression": hook_script, "returnByValue": True})
    time.sleep(0.5)

    # Now fill form, click, inspect
    script = r"""
(async () => {
    const inputs = Array.from(document.querySelectorAll('input'));
    const accountInput = inputs.find(i => i.placeholder === '默认666' && i.type === 'text');
    const passwordInput = inputs.find(i => i.placeholder === '默认666' && i.type === 'password');
    const setValue = (el, val) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    setValue(accountInput, '666');
    setValue(passwordInput, '666');
    await new Promise(r => setTimeout(r, 400));
    // Check what Vue o.value contains
    const step1 = window.__inspectLogin();
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => b.textContent && (b.textContent.includes('登录') || b.textContent.includes('Login')));
    if (loginBtn) loginBtn.click();
    await new Promise(r => setTimeout(r, 2500));
    const step2 = window.__inspectLogin();
    return {step1, step2, captures: window.__captures};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": script, "returnByValue": True, "awaitPromise": True})
    result = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Screenshot
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-login-capture.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("[+] Screenshot saved: lucky-login-capture.png")

    ws.close()


if __name__ == "__main__":
    main()
