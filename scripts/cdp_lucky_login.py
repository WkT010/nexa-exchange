#!/usr/bin/env python3
"""
Use Python CDP to fill login form, submit, then check if login page encrypts password.
If login fails with plain 666/666, we'll investigate the encryption step.
"""
import json
import time
import base64
import urllib.request
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def main():
    # Reuse existing chrome on 9333 or start it
    pages = []
    try:
        pages = get_pages(9333)
    except Exception as e:
        import subprocess
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
        pages = get_pages(9333)

    # Open Lucky login page (new tab)
    print("[+] Opening Lucky login")
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(4)

    # 1. Enable Network tracking to inspect the login request
    cdp_call(ws, "Network.enable", {}, wait_for_response=True)
    # Listen for requestWillBeSent

    # 2. Fill Account and Password using placeholder "默认666" inputs
    fill_script = r"""
(async () => {
    const inputs = Array.from(document.querySelectorAll('input'));
    const accountInput = inputs.find(i => i.placeholder === '默认666' && i.type === 'text');
    const passwordInput = inputs.find(i => i.placeholder === '默认666' && i.type === 'password');
    if (!accountInput || !passwordInput) return {ok:false, found_account:!!accountInput, found_password:!!passwordInput};

    // For Vue reactive inputs, we need to set value and dispatch events
    const setValue = (el, val) => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    setValue(accountInput, '666');
    setValue(passwordInput, '666');

    return {ok:true};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": fill_script, "returnByValue": True, "awaitPromise": True})
    fill_result = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Fill form: {json.dumps(fill_result)}")
    time.sleep(0.5)

    # 3. Capture the request payload
    # Get current Network log
    # Clear existing
    cdp_call(ws, "Network.clearBrowserCache", {})

    # 4. Click the Login button (blue primary button)
    click_script = r"""
(() => {
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => b.textContent && (b.textContent.includes('Login') || b.textContent.includes('登录')));
    if (!loginBtn) {
        // Try any button with type=primary or blue
        const allBtns = document.querySelectorAll('button, [role="button"]');
        for (const b of allBtns) if (b.textContent && b.textContent.trim()) return b.textContent.trim() + ' clicked';
        return {err:'no button'};
    }
    loginBtn.click();
    return {ok:true, btnText: loginBtn.textContent.trim()};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": click_script, "returnByValue": True})
    click_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Click login: {json.dumps(click_res)}")

    # 5. Wait for login request and response
    time.sleep(3)
    # Get all network entries via Performance or directly evaluate fetch of /api/login
    check_script = r"""
(async () => {
    // Try the actual login via API call manually to see expected request
    try {
        const resp = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({Account:'666', Password:'666', TwoFA:''})
        });
        const text = await resp.text();
        return {status: resp.status, body: text.substring(0,500)};
    } catch(e) { return {err: String(e)}; }
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": check_script, "returnByValue": True, "awaitPromise": True})
    api_check_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Manual API check: {json.dumps(api_check_res, indent=2, ensure_ascii=False)}")

    # 6. Now look at what the actual Vue data structure stores for password (to check if it's been encrypted)
    state_script = r"""
(() => {
    // Find the Vue app instance on inputs via __vueParentComponent etc
    const inputs = Array.from(document.querySelectorAll('input'));
    const pw = inputs.find(i => i.type === 'password');
    if (!pw) return {err:'no password input'};
    // Walk the Vue internals
    let el = pw;
    let vueInstance = null;
    for (const k of Object.keys(el)) {
        if (k.startsWith('__vueParentComponent')) {
            vueInstance = el[k];
            break;
        }
    }
    // Walk up looking for login form data
    let depth = 0;
    let node = vueInstance;
    const results = [];
    while (node && depth < 15) {
        if (node.setupState) {
            for (const [k,v] of Object.entries(node.setupState)) {
                if (typeof v === 'object' && v) {
                    try {
                        const str = JSON.stringify(v);
                        if (str.includes('Account') || str.includes('Password') || str.includes('666')) {
                            results.push(`${k}: ${str.substring(0,300)}`);
                        }
                    } catch(e){}
                } else if (typeof v === 'function') {
                    // ok
                } else {
                    if (String(v).includes('666')) results.push(`${k}: ${v}`);
                }
            }
        }
        node = node.parent;
        depth++;
    }
    return {results};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": state_script, "returnByValue": True})
    vue_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Vue state check: {json.dumps(vue_res, indent=2, ensure_ascii=False)}")

    # 7. Capture screenshot after login attempt
    r = cdp_call(ws, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-after-login.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("[+] Screenshot saved: lucky-after-login.png")

    ws.close()


if __name__ == "__main__":
    main()
