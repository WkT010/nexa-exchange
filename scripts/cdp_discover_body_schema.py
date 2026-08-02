#!/usr/bin/env python3
"""
Storage is encrypted binary (lkcf). We need to figure out the rule body via the
HTTP API only. Let's use a different approach:

1. Use Chrome CDP to navigate to the reverse-proxy Add page directly via URL hash,
   then take screenshots incrementally to understand the DOM state,
   then use JS to find the form fields (even if they don't render visually,
   the DOM tree might have the inputs), and then submit the form and capture XHR.

Alternative: Use DevTools MCP to get a screenshot of the full rendered page
(rendering works in the DevTools MCP browser even if headless=true). But we can
achieve the same effect using the MCP via run_mcp. Let's try the simpler path:
capture XHR when submitting with filled values, using the CDP browser (not
headless new mode? Or headless=true with the chrome window we launched?)

We'll also make the test slower to avoid 429, and carefully inspect what field
names would be expected by probing PUT /api/webservice/rule/0 with different
bodies. Since PUT returned HTTP 500 (not 404!) the endpoint exists but body
shape is wrong - we need to try simpler/fewer fields to get from 500 (panic) to
a validation error with message.
"""
import json
import time
import urllib.request
import urllib.parse
import subprocess
import os
import sys
import base64

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
    time.sleep(8)


def ensure_chrome():
    try:
        get_pages(9333)
    except Exception:
        subprocess.Popen([
            "google-chrome", "--no-sandbox", "--headless", "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--user-data-dir=/tmp/chrome-cdp-profile",
            "about:blank",
        ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(8)


def api(TOKEN, method, path, body=None, qs=None):
    BASE = "http://localhost:16601"
    url = BASE + "/api/" + path
    q = {}
    if qs:
        q.update(qs)
    if method == "GET":
        q["_"] = str(int(time.time() * 1000))
    if q:
        url += "?" + urllib.parse.urlencode(q)
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
                return {"status": resp.status, "json": j, "text": text[:2000]}
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
    time.sleep(5)
    # Login
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
    await new Promise(r => setTimeout(r, 3000));
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    return {token: lucky.token || null};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_script, "returnByValue": True, "awaitPromise": True}, timeout=60)
    login_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    TOKEN = login_res.get("token")
    print(f"[+] Token: {'ok' if TOKEN else 'NONE'}")
    ws.close()

    # Strategy: Try PUT /api/webservice/rule/0 with progressively SMALLER bodies
    # until we see a validation error (not 500). 500 means panic in Go.
    # So body must have a specific structure.
    print("\n=== Strategy: Find simplest body that produces non-500 on PUT /api/webservice/rule/0 ===")
    def try_put(path, body, desc):
        time.sleep(0.5)  # avoid 429
        r = api(TOKEN, "PUT", path, body=body)
        status = r.get("status")
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        txt = r.get("text", "")
        if j:
            msg = f"ret={j.get('ret')} msg={str(j.get('msg',''))[:300]}"
            if "data" in j:
                msg += f" data={str(j['data'])[:200]}"
        else:
            msg = f"text={txt[:300]}"
        if status != 404:
            print(f"  PUT {path:<26} [{desc:60}] -> HTTP {status} {msg}")
        return (status, j, txt)

    # Extremely minimal bodies: try {id:X} with various types, then add one field at a time
    for path, body, desc in [
        # Rule structure with ONLY required fields for unmarshalling (what Go needs without panic)
        ("webservice/rule/0", {}, "empty"),
        ("webservice/rule/0", {"id": 0}, "id=0"),
        ("webservice/rule/0", {"id": 1}, "id=1"),
        ("webservice/rule/0", {"ID": 0}, "ID=0 (uppercase)"),
        ("webservice/rule/0", {"id": "0"}, "id=string0"),
        # Fields that might be arrays - wrong types often cause panics
        ("webservice/rule/0", {"id": 0, "listenAddr": "0.0.0.0"}, "id+listenAddr"),
        ("webservice/rule/0", {"id": 0, "listenPort": 8081}, "id+listenPort"),
        ("webservice/rule/0", {"id": 0, "listenPort": "8081"}, "id+listenPort(string)"),
        ("webservice/rule/0", {"id": 0, "listenAddr": "0.0.0.0", "listenPort": 8081}, "addr+port+id"),
        ("webservice/rule/0", {"id": 0, "status": "enable"}, "id+status"),
        ("webservice/rule/0", {"id": 0, "Status": "enable"}, "id+Status(uppercase)"),
        ("webservice/rule/0", {"id": 0, "status": 1}, "id+status(int)"),
        ("webservice/rule/0", {"id": 0, "listenType": "tcp"}, "id+listenType"),
        ("webservice/rule/0", {"id": 0, "listenType": "http"}, "id+listenType=http"),
        ("webservice/rule/0", {"id": 0, "listenType": "HTTPS"}, "id+listenType=HTTPS"),
        ("webservice/rule/0", {"id": 0, "type": "tcp"}, "id+type=tcp"),
        ("webservice/rule/0", {"id": 0, "domains": []}, "id+empty domains []"),
        ("webservice/rule/0", {"id": 0, "Domains": []}, "id+empty Domains (up)"),
        ("webservice/rule/0", {"id": 0, "DomainList": []}, "id+empty DomainList"),
        ("webservice/rule/0", {"id": 0, "domains": None}, "id+domains=null"),
        ("webservice/rule/0", {"id": 0, "subRules": None}, "id+subRules=null"),
        ("webservice/rule/0", {"id": 0, "subRules": []}, "id+empty subRules []"),
        ("webservice/rule/0", {"id": 0, "SubRules": []}, "id+SubRules (up)"),
        ("webservice/rule/0", {"id": 0, "SubRuleList": []}, "id+SubRuleList"),
        ("webservice/rule/0", {"id": 0, "RuleList": []}, "id+RuleList"),
        ("webservice/rule/0", {"id": 0, "domains": ["a.com"], "subRules": []}, "domains+subRulesEmpty"),
        # Fields for stcp?
        ("webservice/rule/0", {"id": 0, "listenAddr": "0.0.0.0", "listenPort": 8081,
                               "listenType": "tcp", "status": "enable",
                               "targetAddr": "127.0.0.1:8080"}, "TCP forward with targetAddr"),
        ("webservice/rule/0", {"id": 0, "listenAddr": "0.0.0.0", "listenPort": 8081,
                               "listenType": "tcp", "status": "enable",
                               "backend": "127.0.0.1:8080"}, "TCP backend field"),
        ("webservice/rule/0", {"id": 0, "listenAddr": "0.0.0.0", "listenPort": 8081,
                               "listenType": "tcp", "status": "enable",
                               "upstream": "127.0.0.1:8080"}, "TCP upstream field"),
    ]:
        try_put(path, body, desc)

    # Also check rules API with minimal body (avoid 429 with delay)
    print("\n=== POST /api/webservice/rules - simple bodies ===")
    for body, desc in [
        ({"id": 0}, "id only"),
        ({"id": 0, "listenAddr": "0.0.0.0", "listenPort": 8081, "listenType": "tcp",
          "status": "enable", "domains": ["canival.fyi"], "subRules": [{}]},
         "all but empty subRule"),
        ({"id": 0, "listenAddr": "0.0.0.0", "listenPort": 8081, "listenType": "tcp",
          "status": "enable", "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "remark": "main", "domain": "", "path": "/",
                        "status": "enable", "backends": None}]},
         "backends=null"),
    ]:
        time.sleep(0.8)
        r = api(TOKEN, "POST", "webservice/rules", body=body)
        status = r.get("status")
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        txt = r.get("text", "")
        if j:
            msg = f"ret={j.get('ret')} msg={str(j.get('msg',''))[:300]}"
            if "data" in j:
                msg += f" data={str(j['data'])[:200]}"
        else:
            msg = f"text={txt[:300]}"
        print(f"  POST rules [{desc:60}] -> HTTP {status} {msg}")

    # Finally, do a visual screenshot of the actual form page by navigating explicitly
    print("\n=== Try to render reverseproxy form via DOM scripting and screenshot ===")
    page2 = new_page(9333, "http://localhost:16601/#/reverseproxy")
    ws2 = SimpleWS(page2["webSocketDebuggerUrl"])
    time.sleep(6)
    # Force login via localStorage token
    inject = r"""
(async () => {
    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    lucky.token = arguments[0];
    localStorage.setItem('lucky', JSON.stringify(lucky));
    // Try to get form fields by simulating click on "新增"
    document.body.focus();
    // Render a second time
    location.reload();
    return {ok: true};
})()
"""
    cdp_call(ws2, "Runtime.evaluate", {"expression": f"((t) => {inject})(`{TOKEN}`)", "returnByValue": True, "awaitPromise": True}, timeout=30)
    time.sleep(6)

    # Try to find and click Add/New button via DOM - iterate all clickable elements
    click_all = r"""
(() => {
    const results = [];
    const all = Array.from(document.querySelectorAll('button, [class*="btn"], [class*="button"], a, span, div, [role="button"], [class*="click"]'));
    let clicked = 0;
    for (const el of all) {
        const txt = (el.textContent || '').trim();
        if (el.offsetParent !== null && /新增|添加|Add|Create|New|新建|^\+$/.test(txt) && txt.length < 15) {
            try {
                el.click();
                clicked++;
                results.push(txt.substring(0, 50));
            } catch(e) {}
        }
    }
    return {total_checked: all.length, clicked, labels: results, bodyText: (document.body?.innerText || '').substring(0, 3000)};
})()
"""
    r = cdp_call(ws2, "Runtime.evaluate", {"expression": click_all, "returnByValue": True, "awaitPromise": True}, timeout=30)
    res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"  Clicked {res.get('clicked')} buttons: {res.get('labels')}")
    print(f"  Body text (first 1500): {res.get('bodyText','')[:1500]}")
    time.sleep(3)
    r = cdp_call(ws2, "Page.captureScreenshot", {"format": "png"})
    if r and r.get("result", {}).get("data"):
        with open("/workspace/lucky-rp-form.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("  Screenshot: lucky-rp-form.png")
    ws2.close()

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
