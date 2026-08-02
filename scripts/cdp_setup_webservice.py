#!/usr/bin/env python3
"""
Login to Lucky, extract JWT token, then use HTTP requests directly (no chrome needed)
to configure the webservice (reverse proxy) rule.

Auth header: Lucky-Admin-Token: <JWT>
"""
import json
import time
import base64
import urllib.request
import urllib.parse
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

    # Login via UI, extract token from localStorage.lucky JSON
    login_and_token = r"""
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
    const btns = Array.from(document.querySelectorAll('button'));
    const loginBtn = btns.find(b => /登录|Login/.test(b.textContent || ''));
    if (loginBtn) loginBtn.click();
    await new Promise(r => setTimeout(r, 3000));

    const lucky = JSON.parse(localStorage.getItem('lucky') || '{}');
    return {
        hash: window.location.hash,
        token: lucky.token || null,
    };
})()
"""
    r = cdp_call(ws, "Runtime.evaluate", {"expression": login_and_token, "returnByValue": True, "awaitPromise": True}, timeout=60)
    login_res = r.get('result', {}).get('result', {}).get('value', {}) if r else {}
    TOKEN = login_res.get("token")
    print(f"[+] Login hash={login_res.get('hash')}")
    print(f"[+] Token (preview): {TOKEN[:40] if TOKEN else None}...")
    ws.close()

    if not TOKEN:
        print("[!] No token, aborting")
        return 1

    # Now make API calls directly with Python urllib using Lucky-Admin-Token header
    BASE = "http://localhost:16601"

    def api(method, path, body=None):
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
                    return {"status": resp.status, "text": text[:500]}
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")[:500]
            return {"status": e.code, "text": text}
        except Exception as e:
            return {"error": str(e)}

    # Test auth
    info = api("GET", "info")
    print(f"\n[+] Test auth GET /api/info -> HTTP {info.get('status')} json={info.get('json', {}).get('ret') if isinstance(info.get('json'), dict) else info.get('text')[:80]}")
    if isinstance(info.get('json'), dict) and info['json'].get('ret') != 0:
        print("[!] Auth failed!")
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 2

    # Step 1: Enumerate webservice API by trying common patterns with GET
    print("\n[+] === Enumerating WebService API GET endpoints ===")
    candidates = [
        "webservice/rules",
        "webservice/rules_lite",
        "webservice/rule",
        "webservice/logs",
        "webservice/lastlogs",
        "webservice",
        "webservice/status",
        "webservice/listenaddr",
    ]
    for p in candidates:
        r = api("GET", p)
        j = r.get("json", {})
        status = r.get("status")
        if status != 200:
            print(f"  GET /api/{p:<30} -> HTTP {status} text={r.get('text','')[:80]}")
            continue
        if isinstance(j, dict):
            keys = list(j.keys())[:10]
            ret = j.get("ret")
            # Summarize the data shape
            summary_parts = []
            if "data" in j and isinstance(j["data"], list):
                summary_parts.append(f"data_len={len(j['data'])}")
                if j["data"]:
                    first = j["data"][0]
                    if isinstance(first, dict):
                        summary_parts.append(f"sample_keys={list(first.keys())[:12]}")
            elif "data" in j and isinstance(j["data"], dict):
                summary_parts.append(f"data_keys={list(j['data'].keys())[:15]}")
            summary = ", ".join(summary_parts)
            print(f"  GET /api/{p:<30} -> HTTP {status} ret={ret} keys={keys} {summary}")
            # Print full-ish for rules
            if p == "webservice/rules":
                print(f"    Full json preview: {json.dumps(j, ensure_ascii=False)[:800]}")

    # Step 2: Figure out the rule structure by looking at lucky_reverseproxy.js
    js_text = urllib.request.urlopen("http://localhost:16601/static/js/lucky_reverseproxy-Do5lv6LM.js", timeout=10).read().decode("utf-8", errors="replace")
    import re
    print("\n[+] === Reverse proxy JS interesting strings (form keys) ===")
    # Extract identifier-looking strings with common form field names
    interesting = sorted(set(re.findall(r'["\']([A-Za-z_][A-Za-z0-9_]{1,40})["\']', js_text)))
    filtered = [s for s in interesting if re.search(r'(?i)listen|addr|port|host|domain|sub|rule|back|forward|type|status|name|comment|http|tcp|ssl|tls|cert|balance|load|server|path', s)]
    for s in filtered:
        print(f"  {s}")
    print(f"  (total {len(filtered)} filtered / {len(interesting)} raw)")

    # Step 3: Try creating a rule using the common webservice pattern:
    # Based on lucky convention, likely:
    # POST /api/webservice/rule  { ...rule fields... }
    # or PUT /api/webservice/rule/{id} or /api/webservice/rule
    print("\n[+] === Attempting to create WebService rule ===")
    rule_template = {
        # Common fields from similar tools
        "name": "NEXA",
        "comment": "NEXA Trading Platform",
        "listenAddr": "0.0.0.0",
        "listenPort": 8081,
        "listenType": "tcp",
        "domain": "canival.fyi",
        "domains": ["canival.fyi"],
        "serverName": "canival.fyi",
        "status": "enable",
        "type": "http",
        # Backend
        "proxyPass": "http://127.0.0.1:8080",
        "backendAddr": "127.0.0.1:8080",
        "backends": [{"host": "127.0.0.1", "port": 8080, "status": "enable"}],
        "subRules": [
            {"remark": "main", "domain": "", "path": "/", "backends": [{"addr": "127.0.0.1:8080", "status": "enable"}]}
        ],
    }
    for (method, path, body_desc) in [
        ("POST", "webservice/rule", "full template"),
        ("PUT", "webservice/rule", "full template"),
        ("POST", "webservice/rules", "full template"),
        ("POST", "webservice/rule/create", "full template"),
        ("POST", "webservice", "full template"),
    ]:
        body = {k: v for k, v in rule_template.items()}
        r = api(method, path, body=body)
        status = r.get("status")
        j = r.get("json", {}) if isinstance(r.get("json"), dict) else {}
        if status == 404:
            continue
        ret = j.get("ret", None)
        msg = j.get("msg", None) or r.get("text", "")
        print(f"  {method:>5} /api/{path:<25} [{body_desc}] -> HTTP {status} ret={ret} msg={str(msg)[:200]}")
        # Also print any data errors with missing fields hints
        if isinstance(j, dict) and "data" in j and j["data"]:
            print(f"       data: {str(j['data'])[:300]}")

    # Step 4: If list endpoint worked but none of create did, inspect the JS more carefully
    # Try reading the lucky_WebService or lucky_ form definition file
    print("\n[+] === Downloading other WebService-related JS chunks for form definition ===")
    index_text = urllib.request.urlopen("http://localhost:16601/static/js/lucky_index-DyslG9Ot.js", timeout=15).read().decode("utf-8", errors="replace")
    # Find the webservice-related file names
    ws_chunks = sorted(set(re.findall(r'lucky_[A-Za-z_]*[Ww]eb[Ss]ervice[A-Za-z0-9_-]*\.js', index_text)))
    print(f"  Candidates: {ws_chunks}")
    if not ws_chunks:
        ws_chunks = sorted(set(re.findall(r'lucky_[A-Za-z_]*[Rr]everse[Pp]roxy[A-Za-z0-9_-]*\.js', index_text)))
        print(f"  Reverse proxy chunks: {ws_chunks}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
