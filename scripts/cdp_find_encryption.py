#!/usr/bin/env python3
"""
Restart Lucky (to reset max attempts) and find the encryption method used by the login page.
Then perform login with encrypted password.
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
    print("[+] Restarting Lucky to reset rate limit...")
    subprocess.run(["pkill", "-9", "-f", "lucky"], check=False)
    time.sleep(2)
    subprocess.Popen(
        ["nohup", "/opt/lucky_v2.13.4", "-c", "/goodluck/lucky.conf"],
        cwd="/goodluck",
        stdout=open("/tmp/lucky.log", "w"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(7)
    r = urllib.request.urlopen("http://localhost:16601/", timeout=5)
    print(f"    Lucky HTTP: {r.status}")


def main():
    restart_lucky()

    # Open lucky login page in chrome
    try:
        pages = get_pages(9333)
    except Exception:
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

    print("[+] Opening Lucky login page")
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(4)

    # Step 1: Find how the password is encrypted. Search page for JSEncrypt, CryptoJS, or encrypt fn.
    scan_script = r"""
(() => {
    // Look for encryption libraries/functions in global scope
    const globalNames = Object.keys(window).filter(k => /encr|crypt|rsa|aes|md5|sha|key|pub|priv/i.test(k));
    // Check for JSEncrypt instance
    const hasJSEncrypt = typeof window.JSEncrypt !== 'undefined';
    const hasCryptoJS = typeof window.CryptoJS !== 'undefined';
    // Check Vue app's setupState for encrypt helper
    const inputs = Array.from(document.querySelectorAll('input'));
    const pw = inputs.find(i => i.type === 'password');
    let loginObj = null;
    if (pw) {
        let node = null;
        for (const k of Object.keys(pw)) {
            if (k.startsWith('__vueParentComponent')) {
                node = pw[k];
                break;
            }
        }
        let depth = 0;
        while (node && depth < 12) {
            if (node.setupState) {
                for (const [k,v] of Object.entries(node.setupState)) {
                    if (typeof v === 'function') {
                        try {
                            const name = v.name || String(k);
                            if (/encr|crypt|request|login|api/i.test(name)) {
                                // not all
                            }
                        } catch(e){}
                    } else if (typeof v === 'object' && v) {
                        try {
                            const s = JSON.stringify(v);
                            if (/encr|crypt|rsa|aes|md5|sha/i.test(s)) {
                                loginObj = {key: k, preview: s.substring(0,500)};
                            }
                        } catch(e){}
                    }
                }
            }
            node = node.parent;
            depth++;
        }
    }
    // Also check for request wrapper R and D from Login.js
    const req = typeof window.__v_app !== 'undefined' ? 'v_app' : null;
    return {
        globalNames,
        hasJSEncrypt,
        hasCryptoJS,
        loginObj,
        // Check for __v_app and its provides
        vueApp: !!document.querySelector('#app')?.__vue_app__,
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": scan_script, "returnByValue": True})
    res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Env scan: {json.dumps(res, indent=2, ensure_ascii=False)}")

    # Step 2: Find the actual encrypt function by looking at the request wrapper (R in Login.js)
    # Search for R function and check if it wraps Request with encryption
    find_request = r"""
(() => {
    // The Login component calls R(o.value) - R is an import.
    // Check network interceptor: what URL + body gets sent when we call the login function
    // Let's monkey-patch fetch and XMLHttpRequest to log the login request.
    window.__capturedLogin = null;
    const origFetch = window.fetch;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
        if (url.includes('/api/login')) {
            const opts = args[1] || {};
            window.__capturedLogin = {
                url,
                method: opts.method || 'GET',
                headers: opts.headers ? Object.fromEntries(Object.entries(opts.headers)) : null,
                body: typeof opts.body === 'string' ? opts.body : (opts.body ? '[object]' : null),
            };
        }
        return origFetch.apply(this, args);
    };
    return {patched: true};
})()
"""
    cdp_call(ws, "Runtime.evaluate", {"expression": find_request, "returnByValue": True})

    # Fill form and submit to capture actual request
    fill_and_submit = r"""
(async () => {
    const inputs = Array.from(document.querySelectorAll('input'));
    const accountInput = inputs.find(i => i.placeholder === '默认666' && i.type === 'text');
    const passwordInput = inputs.find(i => i.placeholder === '默认666' && i.type === 'password');
    const setValue = (el, val) => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    setValue(accountInput, '666');
    setValue(passwordInput, '666');
    await new Promise(r => setTimeout(r, 300));
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => b.textContent && (b.textContent.includes('Login') || b.textContent.includes('登录')));
    if (loginBtn) {
        loginBtn.click();
    }
    await new Promise(r => setTimeout(r, 2000));
    return {captured: window.__capturedLogin};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": fill_and_submit, "returnByValue": True, "awaitPromise": True})
    cap = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Captured login request: {json.dumps(cap, indent=2, ensure_ascii=False)}")

    # Step 3: Now also check the Vue state for encrypted Password right before send
    # By wrapping the request function
    ws.close()


if __name__ == "__main__":
    main()
