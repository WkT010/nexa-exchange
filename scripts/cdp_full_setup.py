#!/usr/bin/env python3
"""
Re-login to Lucky (fetch says login invalid - lost session).
Then use API to configure web service / reverse proxy rule.

Found API endpoints:
- GET /api/webservice/rules
- GET /api/webservice/rules_lite
- GET /api/webservice/rule/
- GET /api/webservice/ruleorderadjustment
- GET /api/webservice/logs, lastlogs
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


def ensure_chrome():
    try:
        get_pages(9333)
        return
    except Exception:
        subprocess.Popen([
            "google-chrome", "--no-sandbox", "--headless=new", "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=9333",
            "--user-data-dir=/tmp/chrome-cdp-profile",
            "about:blank",
        ], stdout=open("/tmp/chrome-cdp.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(8)


class LuckyAPI:
    def __init__(self, ws):
        self.ws = ws

    def call(self, method, url_path, body=None, query=None):
        url = f"./api/{url_path}"
        if query:
            from urllib.parse import urlencode
            url += "?" + urlencode(query)
        expr = f"""
(async () => {{
    try {{
        const init = {{
            method: {json.dumps(method)},
            credentials: 'same-origin',
        }};
        {f"init.headers = {{'Content-Type': 'application/json'}}; init.body = JSON.stringify({json.dumps(body)});" if body else ""}
        const resp = await fetch({json.dumps(url)}, init);
        const text = await resp.text();
        return {{status: resp.status, body: text.substring(0, 20000)}};
    }} catch(e) {{ return {{error: String(e)}}; }}
}})()
"""
        r = cdp_call(self.ws, "Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if not r:
            return {}
        val = r.get("result", {}).get("result", {}).get("value", {})
        if isinstance(val, dict) and "body" in val:
            try:
                val["json"] = json.loads(val["body"])
            except Exception:
                pass
        return val


def main():
    restart_lucky()
    ensure_chrome()
    # Open login page, log in
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(4)

    # Fill form and submit (XHR login)
    login = r"""
(async () => {
    const inputs = Array.from(document.querySelectorAll('input'));
    const ai = inputs.find(i => i.placeholder === '默认666' && i.type === 'text');
    const pi = inputs.find(i => i.placeholder === '默认666' && i.type === 'password');
    const setValue = (el, val) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles:true}));
    };
    setValue(ai, '666'); setValue(pi, '666');
    await new Promise(r => setTimeout(r, 300));
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => /登录|Login/.test(b.textContent || ''));
    if (loginBtn) loginBtn.click();
    await new Promise(r => setTimeout(r, 3000));
    return {hash: window.location.hash, title: document.title};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login, "returnByValue": True, "awaitPromise": True})
    login_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"[+] Login result: {login_res}")
    api = LuckyAPI(ws)

    # Check session via /api/info
    info = api.call("GET", "info")
    print(f"[+] GET /api/info -> status={info.get('status')} json={info.get('json')}")

    # Now call webservice endpoints
    print("\n[+] === WebService API endpoints ===")
    for ep in ["webservice/rules", "webservice/rules_lite"]:
        r = api.call("GET", ep)
        j = r.get("json", {})
        print(f"  GET /api/{ep} -> HTTP {r.get('status')} ret={j.get('ret') if isinstance(j, dict) else 'N/A'} keys={list(j.keys())[:10] if isinstance(j, dict) else 'N/A'}")
        if isinstance(j, dict):
            preview = json.dumps(j, ensure_ascii=False)
            if len(preview) > 300:
                preview = preview[:300] + "..."
            print(f"       preview: {preview}")

    # Try to find the rule creation endpoint - likely POST webservice/rule or webservice/rule/create or /add
    print("\n[+] === Testing rule creation endpoints ===")
    # First let's also look deeper into the webservice JS file for actions
    js_text = urllib.request.urlopen("http://localhost:16601/static/js/lucky_reverseproxy-Do5lv6LM.js", timeout=10).read().decode("utf-8", errors="replace")
    # Extract POST paths (patterns with rule/ + maybe delete/post)
    import re
    post_patterns = sorted(set(re.findall(r'["\']([^"\']*webservice[^"\']{0,80})["\']', js_text)))
    print(f"[+] All webservice refs in JS: {post_patterns}")

    # Now test common POST patterns for create/update/delete
    test_endpoints = [
        ("POST", "webservice/rule", {"comment": "test-rule", "listenAddr": "0.0.0.0", "listenPort": 8081, "domains": ["canival.fyi"], "subRules": [{"hosts": ["127.0.0.1:8080"]}], "status": "enable"}),
        ("POST", "webservice/rule/create", {}),
        ("POST", "webservice/rule/add", {}),
        ("POST", "webservice/rules", {}),
        ("POST", "webservice", {}),
        ("DELETE", "webservice/rule/0", None),
    ]
    for method, path, body in test_endpoints:
        r = api.call(method, path, body=body)
        j = r.get("json", {})
        status = r.get("status")
        if status == 404:
            continue
        ret = j.get("ret") if isinstance(j, dict) else None
        msg = j.get("msg") if isinstance(j, dict) else None
        print(f"  {method:>6} /api/{path:<30} -> HTTP {status} ret={ret} msg={msg}")

    ws.close()


if __name__ == "__main__":
    main()
