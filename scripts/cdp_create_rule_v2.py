#!/usr/bin/env python3
"""
We found:
- POST /api/webservice/rule -> 404 (not correct path without id? needs diff HTTP method?)
- POST /api/webservice/rules -> 500 with empty body (so the endpoint EXISTS, but body shape wrong!)
- Then got 429 rate limited after many requests.

The correct pattern for Lucky might be:
- PUT /api/webservice/rule/{id} - with id=0 or id=xxxx? Let's try PUT with different path shapes
Wait: DELETE /api/webservice/rule/{id} exists, so router is /api/webservice/rule/<id:word> for DELETE
So PUT /api/webservice/rule/{id} should exist too!

Also: POST /api/webservice/rules 500 means we need a specific body structure.
Let's wait for rate limit to expire, then try PUT with various bodies.
"""
import json
import time
import urllib.request
import urllib.parse
import subprocess
import os
import sys
import re

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
            "google-chrome", "--no-sandbox", "--headless=new", "--disable-gpu",
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

    # Auth check
    info = api(TOKEN, "GET", "info")
    if isinstance(info.get("json"), dict) and info["json"].get("ret") != 0:
        print(f"[!] Auth failed: {info}")
        return 2
    print("[+] Authenticated.")

    # Also let's check the full index.js for reverseproxy save endpoints by searching for URL patterns
    import urllib.request as ureq
    index_text = ureq.urlopen("http://localhost:16601/static/js/lucky_index-DyslG9Ot.js", timeout=15).read().decode("utf-8", errors="replace")
    # Find all occurrences of "webservice/rule" in context
    print("\n=== Index JS: contexts with 'webservice/rule' / 'webservice/rules' ===")
    for m in re.finditer(r'.{0,80}webservice/rule[s]?.{0,80}', index_text):
        ctx = m.group(0).replace("\n", " ")
        if len(ctx) > 10:
            print(f"   ... {ctx} ...")

    # Also look for reverseproxy save function patterns - axios or fetch calls
    print("\n=== Index JS: contexts with HTTP calls including /api/.* reverseproxy related ===")
    for m in re.finditer(r'.{0,80}/api/[^"\'` ]{1,80}.{0,80}', index_text):
        ctx = m.group(0).replace("\n", " ")
        if re.search(r'(?i)rule|webservice|reverse|proxy|stcp|sudp|forward', ctx):
            print(f"   ... {ctx} ...")

    # Now systematically try:
    # 1. PUT /api/webservice/rule/{id_str} with body shapes
    # 2. Also try /api/webservice/rule/create / /api/webservice/rule/add as POST variants
    print("\n=== Try PUT /api/webservice/rule/<id> with various bodies ===")
    def try_(method, path, body, desc):
        # Add small delay to avoid 429
        time.sleep(0.3)
        r = api(TOKEN, method, path, body=body)
        status = r.get("status")
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        txt = r.get("text", "")
        msg = ""
        if j:
            msg = f" ret={j.get('ret')} msg={str(j.get('msg',''))[:400]}"
            if "data" in j:
                msg += f" data={str(j['data'])[:300]}"
        else:
            msg = f" text={txt[:400]}"
        if status == 404:
            return
        print(f"  {method:>5} /api/{path:<28} [{desc:55}] -> HTTP {status}{msg}")

    # A minimal rule body to try
    minimal = {"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable",
               "domains": ["canival.fyi"],
               "subRules": [{"id": 0, "remark": "main", "domain": "", "path": "/", "status": "enable",
                             "backends": [{"id": 0, "addr": "127.0.0.1:8080", "status": "enable", "weight": 1}]}]}

    # Try PUT to create endpoint - maybe id=0 means auto-create? Or id=NEW?
    for method, path_pat, ids in [
        ("PUT", "webservice/rule/{id}", ["0", "1", "new", "add", "create"]),
        ("POST", "webservice/rule/{id}", ["0", "1", "new", "add", "create"]),
        ("PATCH", "webservice/rule/{id}", ["0", "1"]),
        # Also try suffix variants like /save /create /update
        ("POST", "webservice/rule/save", [None]),
        ("POST", "webservice/rule/create", [None]),
        ("POST", "webservice/rule/add", [None]),
        ("POST", "webservice/rule/update", [None]),
        ("PUT", "webservice/rule/save", [None]),
        ("PUT", "webservice/rule/create", [None]),
    ]:
        for id_val in ids:
            if id_val is None:
                path = path_pat
            else:
                path = path_pat.format(id=id_val)
            try_(method, path, minimal, f"minimal rule (id_val={id_val})")

    # Also try POST /api/webservice/rules with wrapper variants
    print("\n=== Try POST /api/webservice/rules with various body shapes ===")
    rule = minimal
    variants = [
        ({"id": 0, "listenPort": 8081}, "only id+port"),
        ({"listenPort": 8081}, "only port"),
        ({"name": "test", "listenPort": 8081, "listenAddr": "0.0.0.0"}, "name+addr+port"),
        ({"rule": rule}, "wrap in rule key"),
        ({"data": rule}, "wrap in data key"),
        ({"item": rule}, "wrap in item key"),
        ({"id": 0, "rule": rule}, "wrap id+rule"),
        ({"items": [rule]}, "wrap in items list"),
        ({"RuleList": [rule]}, "wrap in RuleList (uppercase)"),
        ({"ruleList": [rule]}, "wrap in ruleList list"),
        ({"Rules": [rule]}, "wrap in Rules list"),
        ({"list": [rule]}, "wrap in list list"),
        ({"rules": [rule]}, "wrap in rules list"),
        # Also try with direct fields + ruleList nested for subrules
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable",
          "domains": ["canival.fyi"], "ruleList": [
              {"remark": "main", "domain": "", "path": "/", "backends": [{"addr": "127.0.0.1:8080"}]}]}, "direct+ruleList(sub)"),
        # Without sub-rules nested as arrays? Maybe subRules is dict?
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable",
          "domain": "canival.fyi", "proxyPass": "http://127.0.0.1:8080"}, "proxyPass style"),
        # Or maybe it's called backendAddr, upstreamAddr?
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "status": "enable",
          "host": "canival.fyi", "upstream": "127.0.0.1:8080"}, "host/upstream style"),
    ]
    for body, desc in variants:
        try_("POST", "webservice/rules", body, desc)
        try_("PUT", "webservice/rules", body, f"PUT-{desc}")

    # GET rules list
    print("\n=== GET /api/webservice/rules (current state) ===")
    r = api(TOKEN, "GET", "webservice/rules")
    print(json.dumps(r.get("json", {}), ensure_ascii=False, indent=2)[:800])

    # Also GET /api/webservice/rules_lite
    print("\n=== GET /api/webservice/rules_lite ===")
    r = api(TOKEN, "GET", "webservice/rules_lite")
    print(json.dumps(r.get("json", {}), ensure_ascii=False, indent=2)[:800])

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
