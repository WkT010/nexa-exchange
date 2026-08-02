#!/usr/bin/env python3
"""
- GET /api/webservice/rules returns ret=0 with ruleList=null (no rules)
- GET /api/webservice/rules_lite returns ret=0
- POST /api/webservice/rules returned HTTP 500 (likely our rule structure is wrong)

We need to figure out the exact rule structure expected by Lucky for the
webservice/reverse proxy rule. Let's:
1. Try to enumerate form field names from the UI by navigating to the add-rule page
2. Or try with minimal rule and iteratively add fields based on 500 error feedback
   (if any validation error messages are returned)
"""
import json
import time
import urllib.request
import subprocess
import os
import sys

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


def api(TOKEN, method, path, body=None):
    BASE = "http://localhost:16601"
    url = BASE + "/api/" + path
    if method == "GET":
        url += "?_=" + str(int(time.time() * 1000))
    req = urllib.request.Request(url, method=method)
    req.add_header("Lucky-Admin-Token", TOKEN)
    req.add_header("Accept", "application/json, text/plain, */*")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                j = json.loads(text)
                return {"status": resp.status, "json": j, "text": text[:500]}
            except Exception:
                return {"status": resp.status, "text": text[:2000]}
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")[:2000]
        return {"status": e.code, "text": text}
    except Exception as e:
        return {"error": str(e)}


def main():
    restart_lucky()
    ensure_chrome()
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(4)

    # Login
    login_and_token = r"""
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
    await new Promise(r => setTimeout(r, 3000));
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    return {token: lucky.token || null, hash: window.location.hash};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_and_token, "returnByValue": True, "awaitPromise": True}, timeout=60)
    login_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    TOKEN = login_res.get("token")
    print(f"[+] Token: {TOKEN[:40]+'...' if TOKEN else 'NONE'}")
    ws.close()

    if not TOKEN:
        return 1

    # Use browser to navigate to the add-rule page for Web Service / Reverse Proxy
    # and capture the XHR that contains the full rule structure when submitting.
    print("\n[+] Navigating to WebService page and clicking 'Add' rule...")
    # Open new tab with already-logged-in context
    page2 = new_page(9333, "http://localhost:16601/#/about")
    ws2 = SimpleWS(page2["webSocketDebuggerUrl"])
    time.sleep(3)

    capture_script = r"""
(async () => {
    // Wait for UI to render
    await new Promise(r => setTimeout(r, 1500));
    // Install XHR capture hook to record add-rule request
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
            if (req.url && req.url.includes('/api/') && !req.url.includes('/api/login') && !req.url.includes('/api/info') && !req.url.includes('/api/modules')) {
                window.__captures.push({
                    method: req.method,
                    url: req.url,
                    status: xhr.status,
                    requestBody: req.__body || null,
                    responseText: (xhr.responseText || '').substring(0, 800),
                });
            }
        });
        // Intercept send to capture request body
        xhr.send = function(body) {
            req.__body = typeof body === 'string' ? body : null;
            return origSend.apply(this, arguments);
        };
        return xhr;
    };

    // Now navigate to reverseproxy page
    window.location.hash = '#/reverseproxy';
    await new Promise(r => setTimeout(r, 3000));

    // Click Add/新增 button
    let addClicked = false;
    const clickAdd = () => {
        const bts = Array.from(document.querySelectorAll('button'));
        for (const b of bts) {
            const t = (b.textContent || '').trim();
            if (/新增|添加|Add|Create|New|新建/.test(t) && b.offsetParent !== null) {
                try { b.click(); addClicked = true; return true; } catch(e) {}
            }
        }
        // Also try span/div-based buttons
        const all = Array.from(document.querySelectorAll('[class*="button"], [class*="btn"], span, div'));
        for (const b of all) {
            const t = (b.textContent || '').trim();
            if (/^(新增|添加|Add|Create|New)$/.test(t) && b.offsetParent !== null && t.length < 10) {
                try { b.click(); addClicked = true; return true; } catch(e) {}
            }
        }
        return false;
    };

    if (!clickAdd()) {
        // Try to open by triggering menu expand first
        const menus = Array.from(document.querySelectorAll('.el-submenu, .menu-item, [class*="menu"]'));
        for (const m of menus) {
            const txt = (m.textContent || '').trim();
            if (/Web服务|反向代理|内网穿透/.test(txt) && m.offsetParent !== null) {
                try { m.click(); } catch(e) {}
                await new Promise(r => setTimeout(r, 800));
                if (clickAdd()) break;
            }
        }
    }
    await new Promise(r => setTimeout(r, 2500));

    // Now try to fill fields minimally and click submit to capture the shape
    // Try to find and fill common fields, then submit
    if (addClicked) {
        const inputs = Array.from(document.querySelectorAll('input.el-input__inner, input[type="text"], input[type="number"]'));
        // Find form fields by placeholder and try to fill meaningful values:
        const fills = {
            '监听端口': '8081', 'ListenPort': '8081', '端口': '8081', 'Port': '8081',
            '监听地址': '0.0.0.0', 'ListenAddr': '0.0.0.0',
            '域名': 'canival.fyi', 'Domain': 'canival.fyi', 'Host': 'canival.fyi',
            '名称': 'NEXA', 'Name': 'NEXA', '备注': 'NEXA',
        };
        for (const inp of inputs) {
            const ph = (inp.placeholder || '').trim();
            const match = fills[ph];
            if (match) {
                const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                s.call(inp, match);
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
            }
        }
        // Also find textareas or sub-rule fields
        await new Promise(r => setTimeout(r, 800));
        // Click submit / save / 确定
        const submits = Array.from(document.querySelectorAll('button, [class*="button"]'));
        for (const b of submits) {
            const t = (b.textContent || '').trim();
            if (/确定|保存|提交|Save|Submit|Confirm|OK/.test(t) && b.offsetParent !== null) {
                try { b.click(); break; } catch(e) {}
            }
        }
        await new Promise(r => setTimeout(r, 2500));
    }

    return {
        addClicked,
        pageText: (document.body?.innerText || '').substring(0, 1500),
        captures: window.__captures,
        hash: window.location.hash,
    };
})()
"""
    r = cdp_call(ws2, "Runtime.evaluate", {"expression": capture_script, "returnByValue": True, "awaitPromise": True}, timeout=120)
    res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] addClicked={res.get('addClicked')} hash={res.get('hash')}")
    captures = res.get("captures", [])
    print(f"[+] Captured {len(captures)} calls (excluding login/info/modules):")
    for c in captures:
        print(f"\n  [{c.get('status')}] {c.get('method')} {c.get('url')}")
        if c.get("requestBody"):
            print(f"    request body: {c['requestBody'][:500]}")
        if c.get("responseText"):
            try:
                j = json.loads(c["responseText"])
                print(f"    response: ret={j.get('ret')} msg={str(j.get('msg',''))[:200]} data_keys={list(j.keys())[:5]}")
            except Exception:
                print(f"    response: {c['responseText'][:300]}")

    # If we captured a webservice/rule POST, great. Otherwise fall back:
    # Try iteratively creating rules with minimal body and see validation errors
    if not captures:
        print("\n[+] No add-form captured. Trying incremental POST bodies...")
        # Minimal tests with various endpoint/body combos. Read error messages
        tests = [
            ("POST", "webservice/rule", {}),
            ("POST", "webservice/rule", {"listenPort": 8081}),
            ("POST", "webservice/rule", {"listenPort": 8081, "listenAddr": "0.0.0.0"}),
            ("POST", "webservice/rule", {"listenPort": 8081, "listenAddr": "0.0.0.0", "domains": ["canival.fyi"]}),
            ("POST", "webservice/rule", {"listenPort": 8081, "listenAddr": "0.0.0.0", "domains": ["canival.fyi"], "subRules": []}),
            ("POST", "webservice/rules", {"listenPort": 8081}),
            ("POST", "webservice", {"listenPort": 8081}),
        ]
        for method, path, body in tests:
            r = api(TOKEN, method, path, body=body)
            status = r.get("status")
            txt = r.get("text", "")
            j = r.get("json", {}) if isinstance(r.get("json"), dict) else None
            if status == 404:
                continue
            msg = ""
            if j:
                msg = f" ret={j.get('ret')} msg={str(j.get('msg',''))[:300]} data={str(j.get('data',''))[:200]}"
            else:
                msg = f" text={txt[:300]}"
            print(f"  {method:>5} /api/{path:<22} body_keys={list(body.keys())} -> HTTP {status}{msg}")

    # Also check current rules via GET /api/webservice/rules
    r = api(TOKEN, "GET", "webservice/rules")
    print(f"\n[+] Current rule list (after tests): {json.dumps(r.get('json'), ensure_ascii=False)[:500]}")

    # Take screenshot
    r2 = cdp_call(ws2, "Page.captureScreenshot", {"format": "png"})
    if r2 and r2.get("result", {}).get("data"):
        with open("/workspace/lucky-rp-setup.png", "wb") as f:
            f.write(base64.b64decode(r2["result"]["data"]))
        print("\n[+] Screenshot: lucky-rp-setup.png")

    ws2.close()
    return 0


if __name__ == "__main__":
    import base64
    sys.exit(main() or 0)
