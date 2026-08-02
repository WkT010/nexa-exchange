#!/usr/bin/env python3
"""
We now know:
- DELETE /api/webservice/rule/<id> works (deletes by id)
- GET /api/webservice/rule/<id> returns ret=12 (not found) when we pass garbage as <id>
- This means the router is: /api/webservice/rule/{id_param} - id is part of URL path

Lucky conventions typically use:
- GET    /api/webservice/rule/{id}   -> get rule detail
- PUT    /api/webservice/rule/{id}   -> update existing rule
- POST   /api/webservice/rule          -> create new rule (id auto-assigned)
- DELETE /api/webservice/rule/{id}   -> delete rule

Also:
- POST /api/webservice/rules returned 500 - maybe ruleList field required?
- There's also /api/webservice/ruleorderadjustment

The reverse-proxy JS file is only 1788 bytes! That's tiny - let's look at every byte of it.
The real rule form fields might be in a different JS bundle (e.g. lucky_index or another chunk).

Let's now do:
1. Inspect ALL JS chunks on the page (especially index and reverseproxy) fully
2. Look at lucky's actual rule storage by reading lucky.conf
3. Try create via POST /api/webservice/rule with empty body and iteratively add fields based on validation errors
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
    # 1. First, read the tiny reverse proxy JS to see all strings
    js_text = urllib.request.urlopen("http://localhost:16601/static/js/lucky_reverseproxy-Do5lv6LM.js", timeout=10).read().decode("utf-8", errors="replace")
    print(f"\n=== reverseproxy JS ({len(js_text)} bytes) FULL DUMP ===")
    print(js_text)

    # 2. Try to download the index JS too - it's likely where the actual rules form is
    print("\n=== downloading lucky_index-DyslG9Ot.js... ===")
    index_text = urllib.request.urlopen("http://localhost:16601/static/js/lucky_index-DyslG9Ot.js", timeout=15).read().decode("utf-8", errors="replace")
    print(f"[+] index size: {len(index_text)} bytes")

    # Find all chunks referenced in index
    js_refs = sorted(set(re.findall(r'lucky_[A-Za-z0-9_-]+\.js', index_text)))
    print(f"[+] Referenced chunks: {js_refs}")
    # Try to find the webservice-specific chunk by content in index (maybe the chunk has webservice in it)
    # Instead let's list ALL js files under static/ from browser
    restart_lucky()
    ensure_chrome()
    page = new_page(9333, "http://localhost:16601/")
    ws = SimpleWS(page["webSocketDebuggerUrl"])
    time.sleep(5)
    # Login first
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

    # Navigate to reverseproxy, then intercept Performance to get all loaded scripts
    perf_script = r"""
(async () => {
    // Get all scripts loaded via performance.getEntriesByType
    const entries = performance.getEntriesByType('resource').filter(e => e.name.includes('.js')).map(e => e.name.split('/').pop());
    // Also navigate to reverseproxy hash to trigger chunk loads
    window.location.hash = '#/reverseproxy';
    await new Promise(r => setTimeout(r, 5000));
    const entries_after = performance.getEntriesByType('resource').filter(e => e.name.includes('.js')).map(e => e.name.split('/').pop());
    return {before: entries, after: entries_after, newChunks: Array.from(new Set(entries_after.filter(e => !entries.includes(e))))};
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": perf_script, "returnByValue": True, "awaitPromise": True}, timeout=120)
    perf_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    print(f"\n[+] JS chunks on login: {perf_res.get('before')}")
    print(f"[+] JS chunks after reverseproxy nav: {perf_res.get('after')}")
    print(f"[+] NEW chunks after nav: {perf_res.get('newChunks')}")

    # Download each new chunk and extract strings
    new_chunks = perf_res.get('newChunks') or []
    ws.close()

    TOKEN = login_res.get("token")
    # Just use public URLs anyway (they're static files)
    # For each chunk, extract all interesting strings
    all_interesting = set()
    all_chunks = set(list(perf_res.get('before', [])) + list(perf_res.get('after', [])))
    print(f"\n[+] Analyzing ALL JS chunks for form-field names: {all_chunks}")
    import urllib.request as ureq
    for fname in sorted(all_chunks):
        url = f"http://localhost:16601/static/js/{fname}"
        try:
            text = ureq.urlopen(url, timeout=10).read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Skipping {fname}: {e}")
            continue
        # Find all strings
        strings = set(re.findall(r'"([^"\\]{1,100})"', text) + re.findall(r"'([^'\\]{1,100})'", text))
        interesting = sorted(set(
            s for s in strings
            if s and len(s) < 50 and re.search(r'(?i)listen|port|addr|host|domain|sub|back|forward|rule|type|status|save|delete|set|update|create|add|modify|detail|client|real|ip|protocol|http|tcp|ssl|path|balance|weight|remark|name|comment|server|upstream|proxy|pass|rewrite|redirect|stcp|sudp|http2https|https2http|websocket|http2|tls|cert|key|verify|enable|disable', s)
        ))
        if interesting:
            print(f"\n  --- {fname} ({len(text)} bytes, {len(interesting)} interesting) ---")
            for s in interesting:
                print(f"    {s}")
                all_interesting.add(s)

    # 3. Now try to create rule via POST /api/webservice/rule with empty body first
    print("\n=== Trying create rule via POST /api/webservice/rule with various bodies ===")
    # Start with empty body to see error
    def try_create(body, desc):
        r = api(TOKEN, "POST", "webservice/rule", body=body)
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
        print(f"  POST webservice/rule [{desc:50}] -> HTTP {status}{msg}")
        return (status, j, txt)

    # We know from DELETE /api/webservice/rule/<id> that id must be number. Lucky's convention for new rule bodies:
    # Based on typical lucky-storage format, try these variants:
    tries = [
        ({}, "empty body"),
        ({"id": 0}, "id=0"),
        ({"id": 0, "status": "enable"}, "basic id+status"),
        ({"id": 0, "listenPort": 8081}, "listenPort only"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0"}, "listen addr+port"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp"}, "listen tcp"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable"}, "listen tcp + status"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable", "domains": []}, "empty domains"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable", "domains": ["canival.fyi"]}, "domains set"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable", "domains": ["canival.fyi"], "subRules": []}, "+ empty subRules"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable", "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "remark": "main", "domain": "", "path": "/", "status": "enable",
                        "backends": [{"id": 0, "addr": "127.0.0.1:8080", "status": "enable", "weight": 1}]}]}, "full subRules (v1)"),
        # Alternative field names
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable", "domains": ["canival.fyi"],
          "subRules": [{"id": 0, "remark": "main", "domain": "", "path": "/", "status": "enable",
                        "backendList": [{"id": 0, "host": "127.0.0.1", "port": 8080, "status": "enable", "weight": 1}]}]}, "backendList field"),
        ({"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable", "domains": ["canival.fyi"],
          "ruleList": [{"id": 0, "remark": "main", "domain": "", "path": "/", "status": "enable",
                        "backends": [{"id": 0, "addr": "127.0.0.1:8080"}]}]}, "ruleList instead of subRules"),
        # Try /api/webservice/rules endpoint with array (list) body
    ]
    for body, desc in tries:
        try_create(body, desc)

    # Now try POST /api/webservice/rules with a ruleList wrapper
    print("\n=== Trying POST /api/webservice/rules with various bodies ===")
    def try_rules(body, desc):
        r = api(TOKEN, "POST", "webservice/rules", body=body)
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
        print(f"  POST webservice/rules [{desc:50}] -> HTTP {status}{msg}")
        return (status, j, txt)

    rule_body = {"id": 0, "listenPort": 8081, "listenAddr": "0.0.0.0", "listenType": "tcp", "status": "enable",
                 "domains": ["canival.fyi"],
                 "subRules": [{"id": 0, "remark": "main", "domain": "", "path": "/", "status": "enable",
                               "backends": [{"id": 0, "addr": "127.0.0.1:8080", "status": "enable", "weight": 1}]}]}

    try_rules({}, "empty")
    try_rules({"ruleList": []}, "empty ruleList")
    try_rules({"ruleList": [rule_body]}, "ruleList with one rule")
    try_rules({"list": [rule_body]}, "list field with one rule")
    try_rules(rule_body, "plain rule without wrapper")

    # Check rule list
    print("\n=== GET /api/webservice/rules (current state) ===")
    r = api(TOKEN, "GET", "webservice/rules")
    print(json.dumps(r.get("json", {}), ensure_ascii=False, indent=2)[:800])

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
