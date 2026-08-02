#!/usr/bin/env python3
"""
The reverse proxy page doesn't seem to render components (headless/sandbox issue).
Let's enumerate all possible rule-create endpoints with POST/PUT/DELETE and use the
validation error messages to figure out the expected body shape.
Use iterative approach: try many small bodies until we get validation errors instead of 404/500.
"""
import json
import time
import urllib.request
import urllib.parse
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

    if not TOKEN:
        return 1

    # Auth check
    info = api(TOKEN, "GET", "info")
    if isinstance(info.get("json"), dict) and info["json"].get("ret") != 0:
        print(f"[!] Auth failed: {info}")
        return 2
    print("[+] Authenticated.")

    # Step 1: Enumerate ALL rule endpoints by trying common patterns with different HTTP methods.
    # Also include path variants with id appended (for PUT/DELETE)
    module_name = "webservice"
    actions = ["", "list", "List", "rules", "rule", "rules_lite", "status", "add", "create", "new", "save", "update", "edit", "modify", "delete", "remove", "set", "get", "detail", "info"]
    methods = ["GET", "POST", "PUT", "DELETE"]
    endpoints_200 = []
    print(f"\n[+] Enumerating /api/{module_name}/<action> x methods...")
    for action in actions:
        for method in methods:
            path = f"{module_name}" + (f"/{action}" if action else "")
            body = {} if method in ("POST", "PUT") else None
            r = api(TOKEN, method, path, body=body)
            status = r.get("status")
            txt = r.get("text", "")
            j = r.get("json") if isinstance(r.get("json"), dict) else {}
            if status == 404:
                continue
            endpoints_200.append((method, path, status, j.get("ret") if j else None, str(j.get("msg",""))[:100] if j else txt[:100]))
            msg = f"ret={j.get('ret') if j else None} msg={str(j.get('msg',''))[:100] if j else txt[:100]}"
            print(f"  {method:>6} /api/{path:<30} -> HTTP {status} {msg}")
            # If validation error, also print missing fields hint if any
            if j and "data" in j and j["data"]:
                print(f"       data: {str(j['data'])[:300]}")

    # Also try /api/<module>/rule/<id> patterns
    print(f"\n[+] Enumerating /api/{module_name}/rule/<id> variants...")
    for action in ["get", "update", "save", "delete", "set", "status"]:
        for method in ["GET", "POST", "PUT", "DELETE"]:
            path = f"{module_name}/rule/{action}"
            body = {"id": 0, "listenPort": 8081} if method in ("POST","PUT") else None
            r = api(TOKEN, method, path, body=body)
            status = r.get("status")
            j = r.get("json") if isinstance(r.get("json"), dict) else {}
            if status == 404:
                continue
            msg = f"ret={j.get('ret') if j else None} msg={str(j.get('msg',''))[:100] if j else r.get('text','')[:100]}"
            print(f"  {method:>6} /api/{path:<30} -> HTTP {status} {msg}")
            if j and "data" in j and j["data"]:
                print(f"       data: {str(j['data'])[:300]}")

    # Step 2: Try GET with query params on rules to discover pagination pattern
    print(f"\n[+] GET /api/{module_name}/rules with pagination params...")
    for qs in [
        {"page": 1, "pageSize": 10},
        {"page": 1, "size": 10},
        {"pageNo": 1, "pageSize": 10},
    ]:
        r = api(TOKEN, "GET", f"{module_name}/rules", qs=qs)
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        print(f"  qs={qs} -> HTTP {r.get('status')} ret={j.get('ret') if j else None} keys={list(j.keys()) if j else None}")
        if isinstance(j, dict) and "data" in j:
            print(f"       data: {str(j['data'])[:300]}")

    # Step 3: Read the actual JS bundle for this module more carefully
    # Download lucky_reverseproxy-*.js and look at function bodies
    import re
    js_text = urllib.request.urlopen("http://localhost:16601/static/js/lucky_reverseproxy-Do5lv6LM.js", timeout=10).read().decode("utf-8", errors="replace")
    print(f"\n[+] Reverse proxy JS size: {len(js_text)}")
    # De-obfuscate by listing all strings in the file, including non-ASCII
    all_strings = re.findall(r'"([^"\\]{1,80})"', js_text) + re.findall(r"'([^'\\]{1,80})'", js_text)
    api_sorted = sorted(set(s for s in all_strings if "/" in s or re.search(r'[A-Z]', s)))
    # Filter for interesting form key names and API names
    interesting = sorted(set(
        s for s in api_sorted
        if re.search(r'(?i)listen|port|addr|host|domain|sub|back|forward|rule|type|status|save|delete|get|set|update|create|add|modify|detail|client|real|ip|protocol|http|tcp|ssl|path|balance|weight|remark|name|comment|server|upstream|proxy|pass|rewrite|redirect', s)
        and len(s) < 50
    ))
    print(f"[+] Interesting strings ({len(interesting)}):")
    for s in interesting:
        print(f"    {s}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
