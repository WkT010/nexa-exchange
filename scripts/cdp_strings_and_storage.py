#!/usr/bin/env python3
"""
PUT /api/webservice/rule/0 returned HTTP 500 (no 404, no 429) - so the endpoint exists!
POST /api/webservice/rules with certain bodies (wrap id+rule, wrap rules list, only id+port) returned HTTP 500 too.

Let's figure out the actual body schema by:
1. Looking at the Lucky binary's Go structs directly (strings binary)
2. Looking at lucky.conf on disk (JSON/SQLite?) 
3. Decoding the JWT to see login info (optional)
4. Getting lucky error messages from log files
"""
import json
import os
import subprocess
import sys
import re
import time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_lucky_setup import SimpleWS, cdp_call, get_pages, new_page


def restart_lucky():
    subprocess.run(["pkill", "-9", "-f", "lucky"], check=False)
    time.sleep(2)
    os.makedirs("/goodluck", exist_ok=True)
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
    # 1. Examine /goodluck/ to find storage mechanism
    print("=== /goodluck/ dir tree ===")
    os.makedirs("/goodluck", exist_ok=True)
    for root, dirs, files in os.walk("/goodluck"):
        level = root.replace("/goodluck", "").count(os.sep)
        indent = ' ' * 2 * level
        print(f'{indent}{os.path.basename(root)}/')
        subindent = ' ' * 2 * (level + 1)
        for fn in files:
            fpath = os.path.join(root, fn)
            sz = os.path.getsize(fpath)
            print(f'{subindent}{fn} ({sz} bytes)')

    # 2. Print the main lucky.conf if it's JSON/text
    if os.path.exists("/goodluck/lucky.conf"):
        print("\n=== lucky.conf (first 2000 bytes) ===")
        with open("/goodluck/lucky.conf", "rb") as f:
            data = f.read(2000)
        try:
            print(data.decode("utf-8"))
        except Exception:
            print(f"[binary, first bytes]: {data[:100]}")

    # 3. Look at the binary with strings for Go struct names / json tags / API URLs
    print("\n=== Strings from lucky binary (webservice rule related) ===")
    strings_cmd = "strings /opt/lucky_v2.13.4 2>/dev/null | grep -E -i '(webservice|reverse|proxy|WebService|ReverseProxy|subRules|SubRules|ruleList|RuleList|listenAddr|ListenAddr|listenPort|ListenPort|domains|Domains|backend|Backend|addr|Addr|host|Host)' | sort -u | head -120"
    result = subprocess.run(strings_cmd, shell=True, capture_output=True, text=True)
    print(result.stdout[:5000])
    print(result.stderr[:1000])

    # 4. Also look specifically for JSON tags / Go struct fields
    print("\n=== Strings: Go JSON tag fields (listen, backend, domain) ===")
    strings_cmd2 = "strings /opt/lucky_v2.13.4 2>/dev/null | grep -E '^[A-Za-z_][A-Za-z0-9_]*$' | grep -E -i '(^id$|^status$|listen|port$|addr$|host$|domain|backend|sub|rule$|proxy|remark|weight|path$|type$|enable|disable|cert|ssl|tls|client|real|ip$|header|balance|rewrite|redirect)' | sort -u | head -120"
    result = subprocess.run(strings_cmd2, shell=True, capture_output=True, text=True)
    print(result.stdout[:5000])

    # Now restart lucky and do real api tests (after inspecting strings)
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
    print(f"\n[+] Token: {'ok' if TOKEN else 'NONE'}")
    ws.close()

    # Now iterate: try PUT /api/webservice/rule/0 with many field variants based on strings
    # Read rule format from existing lucky.conf or other known files
    # Also try to GET /api/webservice/rule/0
    print("\n=== GET /api/webservice/rule/0 ===")
    r = api(TOKEN, "GET", "webservice/rule/0")
    print(f"  HTTP {r.get('status')}: {r.get('text','')[:300]}")
    # Check /tmp/lucky.log for any errors after 500s
    if os.path.exists("/tmp/lucky.log"):
        sz = os.path.getsize("/tmp/lucky.log")
        tail = sz - 4000 if sz > 4000 else 0
        with open("/tmp/lucky.log", "rb") as f:
            f.seek(tail)
            print(f"\n=== /tmp/lucky.log (last {sz-tail} bytes) ===")
            print(f.read().decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
