
import argparse
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cmcc_apptoken_sim import (  
    ACCOUNTS_FILE, APP_TOKEN_FILE, BASE, CRYPT, DEFAULT_ACT_URL, SSO_LOGIN, UA_NATIVE, UA_WEB,
    ERR_NET, aes_cbc_decrypt, build_autologin, get_setcookies, http_req, load_accounts, mask,
    refresh_one_account, save_accounts, upsert_account, write_app_token_file,
)

try:
    from cmcc_sms import (  
        act_send_code_real, act_login_real, act_three_network,
    )
    _SMS_OK = True
except Exception as _e:  
    act_send_code_real = act_login_real = act_three_network = None
    _SMS_OK = False
    sys.stderr.write("[sms] 短信登录模块未加载（%r），相关接口将返回提示\n" % _e)

HERE = os.path.dirname(os.path.abspath(__file__))
UI_FILE = os.path.join(HERE, "cmcc_web_ui.html")
STORE_FILE = os.path.join(HERE, "cmcc_web_store.json")
PORT = 8767            
ACCOUNTS_PATH = os.path.join(HERE, ACCOUNTS_FILE)
APP_TOKEN_PATH = os.path.join(HERE, APP_TOKEN_FILE)
_lock = threading.Lock()

HIDE_FIELDS = ("cellNum", "verifyCode", "devToken")


def load_store() -> dict:
    if not os.path.exists(STORE_FILE):
        return {"profile": {}, "last": {}, "history": []}
    try:
        with open(STORE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"profile": {}, "last": {}, "history": []}


def save_store(store: dict):
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
    except Exception as ex:
        sys.stderr.write("[store] 保存失败: %r\n" % ex)


def account_stats() -> dict:
    accs = load_accounts(ACCOUNTS_PATH)
    counts = {"ok": 0, "pending": 0, "invalid": 0}
    for a in accs:
        st = a.get("status") or ("ok" if a.get("app_token_at") else "pending")
        counts[st] = counts.get(st, 0) + 1
    return {"total": len(accs), "ok": counts["ok"], "pending": counts["pending"],
            "invalid": counts["invalid"]}


def accounts_view() -> list:
    out = []
    for a in load_accounts(ACCOUNTS_PATH):
        phone = str(a.get("phone") or "")
        st = a.get("status") or ("ok" if a.get("app_token_at") else "pending")
        out.append({
            "phone": phone,
            "phone_masked": (phone[:3] + "****" + phone[-4:]) if len(phone) >= 7 else phone,
            "name": a.get("name") or ("账号 %s" % (phone[-4:] if phone else "?")),
            "note": a.get("note", ""),
            "province_code": a.get("province_code", ""),
            "city_code": a.get("city_code", ""),
            "xk": a.get("xk", ""),
            "has_xk": bool(a.get("xk")),
            "app_token": a.get("app_token", ""),
            "app_token_at": a.get("app_token_at", ""),
            "session_token": a.get("session_token", ""),
            "status": st,
            "status_text": a.get("status_text", ""),
            "last_error": a.get("last_error", ""),
            "refresh_count": a.get("refresh_count", 0),
            "first_seen": a.get("first_seen", ""),
            "last_seen": a.get("last_seen", ""),
            "updated_at": a.get("updated_at", ""),
            "device_fields": len(a.get("device") or {}),
        })
    return out


def import_account(device: dict, phone: str, province: str, city: str,
                   app_token: str = "", source: str = "", name: str = "",
                   note: str = "") -> dict:
    accs = load_accounts(ACCOUNTS_PATH)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    existing = next((a for a in accs if str(a.get("phone")) == str(phone)), None)
    acct = {
        "phone": phone, "province_code": province, "city_code": city,
        "xk": device.get("xk", ""),
        "device": {k: v for k, v in device.items() if not k.startswith("_")},
        "app_token": app_token or (existing or {}).get("app_token", ""),
        "app_token_at": time.strftime("%Y-%m-%d %H:%M:%S") if app_token else (existing or {}).get("app_token_at", ""),
        "status": (existing or {}).get("status") or ("ok" if app_token else "pending"),
        "status_text": (existing or {}).get("status_text", ""),
        "refresh_count": (existing or {}).get("refresh_count", 0),
        "first_seen": (existing or {}).get("first_seen", now),
        "last_seen": now,
        "note": note or (existing or {}).get("note", ""),
        "name": name or (existing or {}).get("name", "") or ("账号 %s" % (phone[-4:] if phone else "?")),
        "source": source,
    }
    accs = upsert_account(accs, acct)
    save_accounts(accs, ACCOUNTS_PATH)
    write_app_token_file(accs, APP_TOKEN_PATH)
    return acct


def set_account_fields(phone: str, fields: dict) -> bool:
    accs = load_accounts(ACCOUNTS_PATH)
    hit = False
    for a in accs:
        if str(a.get("phone")) == str(phone):
            a.update({k: v for k, v in fields.items() if v is not None})
            a["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            hit = True
    if hit:
        save_accounts(accs, ACCOUNTS_PATH)
    return hit


def sync_account_token(phone: str, app_token: str, session_token: str = ""):
    accs = load_accounts(ACCOUNTS_PATH)
    hit = False
    for a in accs:
        if str(a.get("phone")) == str(phone):
            a["app_token"] = app_token
            a["app_token_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if session_token:
                a["session_token"] = session_token
            a["status"] = "ok"
            a["status_text"] = ""
            a["last_error"] = ""
            a["refresh_count"] = int(a.get("refresh_count", 0)) + 1
            a["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            a["updated_at"] = a["last_seen"]
            hit = True
    if hit:
        save_accounts(accs, ACCOUNTS_PATH)
        write_app_token_file(accs, APP_TOKEN_PATH)
    return hit


def refresh_all_accounts(act_url: str = "", verify: bool = False) -> dict:
    accs = load_accounts(ACCOUNTS_PATH)
    results = []
    for a in accs:
        phone = a.get("phone", "")
        tok, sess, err = refresh_one_account(a, act_url, verify)
        a["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if tok:
            a["app_token"] = tok
            a["app_token_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if sess:
                a["session_token"] = sess
            a["status"] = "ok"
            a["status_text"] = ""
            a["last_error"] = ""
            a["refresh_count"] = int(a.get("refresh_count", 0)) + 1
            a["updated_at"] = a["last_seen"]
            results.append({"phone": phone, "ok": True, "app_token": tok,
                            "session_token": sess, "error": ""})
        else:
            if not str(err).startswith(ERR_NET):
                a["status"] = "invalid"
                a["status_text"] = err
            else:
                a["status_text"] = "（网络/环境问题，未判失效）"
            a["last_error"] = err
            a["updated_at"] = a["last_seen"]
            results.append({"phone": phone, "ok": False, "app_token": "", "error": err})
        save_accounts(accs, ACCOUNTS_PATH)
    write_app_token_file(accs, APP_TOKEN_PATH)
    ok = sum(1 for r in results if r["ok"])
    return {"ok": True, "total": len(results), "success": ok, "results": results,
            "out_file": APP_TOKEN_FILE}


OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "中国移动 qwhdsso 会话票据服务", "version": "1.2.0",
             "description": "多账号管理 / 一键换票 / 30 分钟活动会话票据"},
    "servers": [{"url": "/"}],
    "paths": {
        "/api/state": {"get": {"summary": "全局状态（档案+账号库+历史）"}},
        "/api/stats": {"get": {"summary": "账号统计（总数/可用/待确认/已失效）"}},
        "/api/accounts": {"get": {"summary": "账号列表"}},
        "/api/accounts/import": {"post": {"summary": "导入账号（HAR / 加密体 / 档案+xk）"}},
        "/api/accounts/refresh": {"post": {"summary": "一键换票（全部账号）"}},
        "/api/accounts/remove": {"post": {"summary": "删除账号"}},
        "/api/accounts/note": {"post": {"summary": "保存账号备注/名称"}},
        "/api/accounts/run": {"post": {"summary": "执行单账号换票并返回票据"}},
        "/api/sms/send-code": {"post": {"summary": "短信登录：发送验证码（真实加密通道）"}},
        "/api/sms/login": {"post": {"summary": "短信登录：提交验证码登录，成功后自动喂请求体原文完成账号入库"}},
        "/api/sms/three-network": {"post": {"summary": "短信登录：三网（号码认证）登录，成功后自动入库"}},
        "/api/app-token-file": {"get": {"summary": "读取 app_token.json"}},
        "/api/openapi.json": {"get": {"summary": "本 OpenAPI 描述"}},
    },
}


def _lan_ips() -> list:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            ips.append(ip)
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def parse_har(har_text: str):
    har_text = (har_text or "").lstrip("\ufeff").strip()
    if not har_text:
        raise ValueError("HAR 内容为空，请重新选择文件或粘贴 HAR 全文")
    try:
        har = json.loads(har_text)
    except Exception as ex:
        raise ValueError("HAR 解析失败（文件可能不完整或不是有效 JSON）：%r" % ex)
    entries = ((har.get("log") or {}).get("entries") or []) if isinstance(har, dict) else []
    cands = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        req = e.get("request") or {}
        u = req.get("url", "") or ""
        pd = req.get("postData") or {}
        if re.search(r"/uam\w*login/", u) and pd.get("text"):
            cands.append((e.get("startedDateTime", ""), e, pd["text"], urllib.parse.urlsplit(u).path))
    if not cands:
        raise ValueError("HAR 里没有找到 uam*login 登录请求（需要它的加密 request body）")
    cands.sort(key=lambda x: x[0], reverse=True)
    for ts, e, txt, path in cands:
        try:
            plain = aes_cbc_decrypt(txt, CRYPT["KEY_14"], CRYPT["CRYPT_14_IV"])
            obj = json.loads(plain)
        except Exception:
            continue
        if not obj.get("xk"):
            continue
        phone = ""
        try:
            rplain = aes_cbc_decrypt(e["response"]["content"].get("text", ""),
                                     CRYPT["RESPONSE_KEY_14"], CRYPT["CRYPT_14_IV"])
            rbody = json.loads(rplain).get("rspBody") or {}
            phone = rbody.get("userName", "")
        except Exception:
            pass
        obj["_har_path"] = path
        obj["_har_time"] = ts
        obj["_har_phone"] = phone
        return obj
    raise ValueError("HAR 里的登录请求体解密失败或不含 xk")


def decrypt_body(body_b64: str):
    body_b64 = (body_b64 or "").strip()
    if not body_b64:
        raise ValueError("加密请求体为空")
    plain = aes_cbc_decrypt(body_b64, CRYPT["KEY_14"], CRYPT["CRYPT_14_IV"])
    try:
        return json.loads(plain)
    except Exception as ex:
        raise ValueError("解密结果不是合法 JSON：%r" % ex)


def summarize_device(device: dict) -> list:
    rows = []
    for k in sorted(device.keys()):
        if k.startswith("_"):
            continue
        v = device.get(k)
        if isinstance(v, dict):
            rows.append({"k": k, "v": "{%d 个字段}" % len(v), "kind": "obj"})
        elif k in HIDE_FIELDS:
            rows.append({"k": k, "v": "<一次性字段, len=%d>" % len(str(v)), "kind": "hide"})
        elif k == "xk":
            rows.append({"k": k, "v": mask(str(v), 16), "kind": "secret"})
        elif k in ("tel", "phone"):
            s = str(v)
            rows.append({"k": k, "v": (s[:3] + "****" + s[-4:]) if len(s) == 11 else s, "kind": "secret"})
        else:
            s = str(v)
            rows.append({"k": k, "v": s if len(s) <= 40 else s[:37] + "...", "kind": "text"})
    return rows


def run_flow(payload: dict) -> dict:
    log = []
    steps = []

    def add(text, level="info"):
        log.append({"level": level, "text": text})

    def fail(text, hint=""):
        add(text, "error")
        return {"ok": False, "log": log, "error": text, "hint": hint}

    phone = (payload.get("phone") or "").strip()
    province = (payload.get("province") or "").strip()
    city = (payload.get("city") or "").strip()
    xk_in = (payload.get("xk") or "").strip()
    body_b64 = (payload.get("body_b64") or "").strip()
    har_text = (payload.get("har_text") or "").strip()
    act_url = (payload.get("act_url") or "").strip() or DEFAULT_ACT_URL
    do_verify = bool(payload.get("verify"))

    store = load_store()
    profile = store.get("profile") or {}
    device = {}

    if har_text:
        try:
            device = parse_har(har_text)
            add("[解密] 已解析 HAR：%s（%s）" % (device.get("_har_path", "?"), device.get("_har_time", "")))
            if not phone:
                phone = device.get("_har_phone", "") or ""
        except ValueError as ex:
            return fail("HAR 解析失败：%s" % ex, "请确认导出的是完整 HAR（含 request body），或改用粘贴加密请求体 / 直接填 xk。")

    if not device and body_b64:
        try:
            device = decrypt_body(body_b64)
            add("[解密] 加密请求体解密成功，共 %d 个字段" % len(device))
        except ValueError as ex:
            return fail("解密失败：%s" % ex, "确认粘贴的是 request body 原文（base64 密文），不是响应体。")

    if not device and profile.get("device"):
        device = dict(profile["device"])
        add("[解密] 使用已存设备档案（%d 字段）+ 你填的 xk" % len(device))

    xk = xk_in or (device.get("xk") or "")
    if xk:
        device["xk"] = xk
    if not xk:
        return fail("没有可用的 xk",
                    "三种填法任选其一：① 把抓包登录请求体的加密串粘进「加密请求体」；"
                    "② 直接粘贴 xk（需先在本机跑过一次以存下设备档案）；③ 上传/粘贴整个 HAR。")

    def _pick_phone(*cands):
        for c in cands:
            s = str(c or "").strip()
            if re.match(r"^1\d{10}$", s):
                return s
        return ""

    phone = _pick_phone(phone, device.get("_har_phone"), device.get("phone"),
                        device.get("tel"), profile.get("phone"))
    province = province or device.get("province_code") or device.get("prov") or profile.get("province", "")
    city = city or device.get("city_code") or device.get("city") or profile.get("city", "")
    if phone:
        device["phone"] = phone
    if not province:
        province = "851"
    if not city:
        city = "0852"

    if device.get("xk"):
        store["profile"] = {
            "phone": phone or profile.get("phone", ""),
            "province": province, "city": city, "xk": xk,
            "device": {k: v for k, v in device.items() if not k.startswith("_")},
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_store(store)
        add("[存档] 设备档案已保存（%d 字段），下次只需换 xk" % len(store["profile"]["device"]))

    if not re.match(r"^1\d{10}$", str(phone)):
        return fail("缺少有效手机号（当前 %r）" % phone,
                    "appTokenLogin 需要真实手机号（用于 userCheckId 与 cellNum 签名）。"
                    "请在左上「手机号」框填 11 位号码；若 HAR 里带有真实号码也会自动带出。")
    add("[输入] 手机号 %s | 省/市 %s/%s | xk %s" % (
        phone[:3] + "****" + phone[-4:], province, city, mask(xk, 16)))

    try:
        req = build_autologin(device, phone)
    except Exception as ex:
        return fail("构造 autoLogin 请求失败：%r" % ex, "设备参数可能不完整，建议改用「加密请求体」或 HAR 方式。")
    status, headers, body = http_req("POST", req["url"], req["headers"], req["body"].encode())
    sc = get_setcookies(headers)
    jsid = (re.search(r"JSESSIONID=([^;,]+)", sc) or [None, ""])[1]
    uid = (re.search(r"(?:^|[;,]\s*)UID=([^;,]+)", sc) or [None, ""])[1]
    ticket = (re.search(r"ticketID=([^;,]+)", sc) or [None, "POD9"])[1]
    if not (jsid and uid):
        desc, rcode = "", ""
        try:
            plain = aes_cbc_decrypt(body, CRYPT["RESPONSE_KEY_14"], CRYPT["CRYPT_14_IV"])
            o = json.loads(plain)
            desc = o.get("retDesc", "")
            rcode = str(o.get("retCode", ""))
        except Exception:
            pass
        add("[1] autoLogin 失败：retCode=%s %s" % (rcode, desc), "error")
        hint = ""
        if rcode == "420000" or "其他设备" in desc:
            hint = ("xk 已失效：同一号码在更晚的一次登录后旧 xk 作废（单端登录策略）。"
                    "请在当前持有登录态的设备上强杀 App 重开，重新抓一条 uam*login/autoLogin，"
                    "把它的 request body 粘进「加密请求体」再执行。")
        return fail("autoLogin 未拿到会话：%s" % (desc or ("HTTP %s" % status)), hint)
    app_token = ("JSESSIONID=%s; UID=%s; Comment=SessionServer-unity; "
                 "Path=/;HTTPOnly; ticketID=%s; Secure" % (jsid, uid, ticket))
    add("[1] autoLogin 成功 → 新 app_token %s" % mask(app_token, 30))

    u1 = SSO_LOGIN + "?dlwmh=true&actUrl=" + urllib.parse.quote(act_url, safe="")
    s1, h1, b1 = http_req("GET", u1, {"User-Agent": UA_WEB, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    m = re.search(r"loginPath\s*=\s*'([^']+)'", b1 or "")
    if not m:
        return fail("SSO 未返回 loginPath（HTTP %s）" % s1, "活动页地址可能已失效，请检查 act_url。")
    login_url = BASE + "/qwhdsso" + m.group(1)
    add("[2] 取到一次性 sid：%s" % mask(m.group(1), 30))

    payload_body = {"jwtToken": None, "token": app_token, "provinceCode": province,
                     "cityCode": city, "userCheckId": format(int(phone), "x"),
                     "carrierOperator": "002", "appVersionCode": "12.5.6", "took": 150}
    s2, h2, b2 = http_req("POST", login_url, {
        "Content-Type": "application/json;charset=UTF-8", "User-Agent": UA_WEB,
        "Origin": BASE, "Referer": u1, "Accept": "*/*",
        "X-Requested-With": "com.greenpoint.android.mc10086.activity",
    }, json.dumps(payload_body, ensure_ascii=False, separators=(",", ":")).encode())
    try:
        d2 = json.loads(b2)
    except Exception:
        return fail("appTokenLogin 响应异常（HTTP %s）" % s2, mask(b2, 120))
    if d2.get("code") != "SUCCESS":
        msg = "%s %s" % (d2.get("code"), d2.get("msg"))
        add("[3] appTokenLogin 失败：%s" % msg, "error")
        return fail("appTokenLogin 失败：%s" % msg,
                    "若提示登录状态已过期，说明 app_token 太老；重新执行一次（脚本会用新 xk 重铸）。")
    jwt = (d2.get("data") or {}).get("jwt", "")
    jump = (d2.get("data") or {}).get("url", "")
    add("[3] appTokenLogin SUCCESS，jwt %s" % mask(jwt, 24))

    s3, h3, b3 = http_req("GET", jump, {"User-Agent": UA_WEB, "Accept": "text/html,*/*;q=0.8"})
    sc3 = get_setcookies(h3)
    mt = re.search(r"QWHD_SESSION_TOKEN=([^;]+)", sc3)
    ma = (re.search(r"QWHD_SESSION_TOKEN=[^;]+;Max-Age=(\d+)", sc3) or [None, ""])[1]
    if not mt:
        return fail("活动页未下发 QWHD_SESSION_TOKEN（HTTP %s）" % s3, "检查 act_url 是否为有效活动页。")
    session_token = mt.group(1)
    add("[4] 活动页签发 QWHD_SESSION_TOKEN %s（Max-Age=%s 秒）" % (mask(session_token, 18), ma))

    result = {"session_token": session_token, "max_age": ma, "jump": jump,
              "app_token": app_token, "jwt": jwt, "device": summarize_device(device)}

    if do_verify:
        api_h = {"Content-Type": "application/json;charset=UTF-8", "Accept": "*/*",
                 "Origin": BASE, "Referer": jump, "login-check": "1",
                 "x-requested-with": "XMLHttpRequest",
                 "Cookie": "QWHD_SESSION_TOKEN=" + session_token, "User-Agent": UA_WEB}
        s5, h5, b5 = http_req("POST", BASE + "/qwhdhub/api/mark/user/info", api_h, b"{}")
        sc5 = get_setcookies(h5)
        mt5 = re.search(r"QWHD_SESSION_TOKEN=([^;]+)", sc5)
        ma5 = (re.search(r"Max-Age=(\d+)", sc5) or [None, ""])[1] if mt5 else ""
        same = bool(mt5) and mt5.group(1) == session_token
        add("[5] 业务 API user/info：HTTP %s，resp %s" % (s5, mask(b5, 90)),
            "ok" if s5 == 200 else "warn")
        if mt5:
            add("[5] Set-Cookie 重发：%s，Max-Age=%s → 滑动续期%s" % (
                "同值" if same else "新值", ma5, "生效" if same else "（值变化）"))
        result["api_status"] = s5
        result["api_resp"] = mask(b5, 300)
        result["sliding_same"] = same
        result["api_max_age"] = ma5

    store["profile"].update({"phone": phone, "province": province, "city": city, "xk": xk})
    store["last"] = {"app_token": app_token, "session_token": session_token,
                     "max_age": ma, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    hist = store.get("history") or []
    hist.insert(0, {"at": store["last"]["at"], "ok": True,
                    "session": mask(session_token, 18), "max_age": ma})
    store["history"] = hist[:20]
    save_store(store)
    add("[存档] 已写入 %s（设备档案 + 最新票据）" % os.path.basename(STORE_FILE), "ok")

    try:
        if sync_account_token(phone, app_token, session_token):
            add("[账号库] 已更新账号 %s 的票据，并写入 %s" % (phone, APP_TOKEN_FILE), "ok")
        else:
            import_account(device, phone, province, city, app_token=app_token, source="run")
            add("[账号库] 已自动入库账号 %s，并写入 %s" % (phone, APP_TOKEN_FILE), "ok")
    except Exception as ex:
        add("[账号库] 同步失败：%r" % ex, "warn")

    return {"ok": True, "log": log, "result": result,
            "device": summarize_device(device)}


class Handler(BaseHTTPRequestHandler):
    server_version = "CMCCTokenService/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + fmt % args + "\n")

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        try:
            self._handle_get()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._send(500, json.dumps({"ok": False, "error": "服务端异常: %s: %s" % (type(ex).__name__, ex)},
                                       ensure_ascii=False).encode("utf-8"))

    def _handle_get(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(UI_FILE, encoding="utf-8") as f:
                    html = f.read()
            except Exception:
                html = "<h1>缺少 UI 文件 cmcc_web_ui.html</h1>"
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            store = load_store()
            prof = store.get("profile") or {}
            dev = prof.get("device") or {}
            return self._send(200, json.dumps({
                "has_profile": bool(dev),
                "phone": prof.get("phone", ""),
                "province": prof.get("province", ""),
                "city": prof.get("city", ""),
                "xk": prof.get("xk", ""),
                "device_fields": len(dev),
                "last": store.get("last") or {},
                "history": (store.get("history") or [])[:10],
                "accounts": accounts_view(),
                "stats": account_stats(),
                "accounts_file": ACCOUNTS_FILE,
                "app_token_file": APP_TOKEN_FILE,
            }, ensure_ascii=False).encode("utf-8"))
        if path == "/api/diag":
            from cmcc_apptoken_sim import http_selftest
            dep, gw_st, gw_body = http_selftest()
            py = sys.executable
            try:
                import curl_cffi
                cver = getattr(curl_cffi, "__version__", "?")
            except Exception:
                cver = "未安装"
            try:
                import Crypto
                pver = "已安装"
            except Exception:
                pver = "未安装"
            return self._send(200, json.dumps({
                "ok": True, "dep": dep, "gw_status": gw_st, "gw_body": gw_body[:200],
                "host": socket.gethostname(), "port": PORT,
                "python": py, "python_ver": sys.version.split()[0],
                "curl_cffi": cver, "pycryptodome": pver,
                "has_system_curl": bool(shutil.which("curl")),
            }, ensure_ascii=False).encode("utf-8"))
        if path == "/api/accounts":
            return self._send(200, json.dumps({"ok": True, "accounts": accounts_view(),
                                              "stats": account_stats()},
                                              ensure_ascii=False).encode("utf-8"))
        if path == "/api/stats":
            return self._send(200, json.dumps(account_stats(), ensure_ascii=False).encode("utf-8"))
        if path == "/api/openapi.json":
            return self._send(200, json.dumps(OPENAPI, ensure_ascii=False, indent=1).encode("utf-8"))
        if path == "/api/docs":
            rows = "".join(
                '<tr><td class="mono">%s</td><td>%s</td><td>%s</td></tr>' % (
                    p, list(v.keys())[0].upper(),
                    (list(v.values())[0] or {}).get("summary", ""))
                for p, v in OPENAPI["paths"].items())
            html = ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
                    "<title>接口文档</title><style>"
                    "body{font:14px/1.7 -apple-system,'Microsoft YaHei',sans-serif;background:#f6f7f9;"
                    "margin:0;padding:32px;color:#1c1f23}main{max-width:880px;margin:0 auto;background:#fff;"
                    "border:1px solid #e4e6ea;border-radius:12px;padding:24px 28px}"
                    "h1{font-size:17px;font-weight:500;margin:0 0 4px}"
                    "p.sub{color:#8b9099;font-size:12px;margin:0 0 18px}"
                    "table{width:100%;border-collapse:collapse}"
                    "th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eef0f3;font-size:13px}"
                    "th{color:#8b9099;font-weight:400}"
                    ".mono{font-family:ui-monospace,Consolas,monospace}"
                    "</style></head><body><main>"
                    "<h1>中国移动 qwhdsso 会话票据服务 · 接口文档</h1>"
                    "<p class='sub'>Swagger 风格说明 · OpenAPI: <a href='/api/openapi.json'>/api/openapi.json</a></p>"
                    "<table><tr><th>路径</th><th>方法</th><th>说明</th></tr>__ROWS__</table>"
                    "</main></body></html>").replace("__ROWS__", rows)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/app-token-file":
            try:
                with open(APP_TOKEN_PATH, encoding="utf-8") as f:
                    txt = f.read()
            except Exception:
                txt = ""
            return self._send(200, json.dumps({"ok": True, "file": APP_TOKEN_FILE, "content": txt},
                                              ensure_ascii=False).encode("utf-8"))
        return self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        try:
            self._handle_post()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            try:
                self._send(500, json.dumps({"ok": False,
                                           "error": "服务端异常: %s: %s" % (type(ex).__name__, ex)},
                                          ensure_ascii=False).encode("utf-8"))
            except Exception:
                pass

    def _handle_post(self):
        path = urllib.parse.urlsplit(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception as ex:
            return self._send(400, json.dumps({"ok": False, "error": "bad request: %r" % ex},                                              ensure_ascii=False).encode("utf-8"))
        if path == "/api/decrypt":
            try:
                if (data.get("har_text") or "").strip():
                    obj = parse_har(data["har_text"])
                elif (data.get("body_b64") or "").strip():
                    obj = decrypt_body(data["body_b64"])
                else:
                    return self._send(200, json.dumps({"ok": False, "error": "请先填加密请求体或 HAR"},
                                                      ensure_ascii=False).encode("utf-8"))
                out = {k: v for k, v in obj.items() if k not in HIDE_FIELDS}
                return self._send(200, json.dumps({
                    "ok": True, "plain": json.dumps(out, ensure_ascii=False, indent=1),
                    "rows": summarize_device(obj), "xk": obj.get("xk", ""),
                    "phone": obj.get("_har_phone") or obj.get("phone") or obj.get("tel") or "",
                }, ensure_ascii=False).encode("utf-8"))
            except ValueError as ex:
                return self._send(200, json.dumps({"ok": False, "error": str(ex)},
                                                  ensure_ascii=False).encode("utf-8"))
        if path == "/api/accounts/import":
            with _lock:
                try:
                    phone_in = (data.get("phone") or "").strip()
                    accs = load_accounts(ACCOUNTS_PATH)
                    old = next((a for a in accs if str(a.get("phone")) == phone_in), None)
                    if (data.get("har_text") or "").strip():
                        obj = parse_har(data["har_text"])
                        src = "har"
                    elif (data.get("body_b64") or "").strip():
                        obj = decrypt_body(data["body_b64"])
                        src = "body"
                    elif old and (old.get("device") or {}):
                        obj = dict(old.get("device") or {})
                        src = "device"
                    else:
                        prof = (load_store().get("profile") or {})
                        if not prof.get("device"):
                            return self._send(200, json.dumps({"ok": False, "error": "没有可用来源：需 HAR、加密请求体，或先跑一次建立档案"},
                                                              ensure_ascii=False).encode("utf-8"))
                        obj = dict(prof["device"])
                        src = "profile"
                    xk_in = (data.get("xk") or "").strip()
                    if xk_in:
                        obj["xk"] = xk_in
                    phone = phone_in or obj.get("_har_phone") or obj.get("phone") or obj.get("tel") or ""
                    if not re.match(r"^1\d{10}$", str(phone)):
                        phone = ""
                    province = (data.get("province") or "").strip() or obj.get("province_code") or obj.get("prov") or "851"
                    city = (data.get("city") or "").strip() or obj.get("city_code") or obj.get("city") or "0852"
                    acct = import_account(obj, phone, province, city,
                                          app_token=(data.get("app_token") or "").strip(), source=src)
                    return self._send(200, json.dumps({"ok": True, "account": acct,
                                                      "accounts": accounts_view()},
                                                      ensure_ascii=False).encode("utf-8"))
                except ValueError as ex:
                    return self._send(200, json.dumps({"ok": False, "error": str(ex)},
                                                      ensure_ascii=False).encode("utf-8"))
        if path == "/api/accounts/remove":
            with _lock:
                phone = str(data.get("phone") or "")
                accs = load_accounts(ACCOUNTS_PATH)
                left = [a for a in accs if str(a.get("phone")) != phone]
                save_accounts(left, ACCOUNTS_PATH)
                write_app_token_file(left, APP_TOKEN_PATH)
                return self._send(200, json.dumps({"ok": True, "removed": phone, "accounts": accounts_view()},
                                                  ensure_ascii=False).encode("utf-8"))
        if path == "/api/accounts/note":
            with _lock:
                ok = set_account_fields(str(data.get("phone") or ""), {
                    "note": data.get("note"), "name": data.get("name")})
                return self._send(200, json.dumps({"ok": ok, "accounts": accounts_view()},
                                                  ensure_ascii=False).encode("utf-8"))
        if path == "/api/accounts/run":
            with _lock:
                phone = str(data.get("phone") or "")
                accs = load_accounts(ACCOUNTS_PATH)
                acct = next((a for a in accs if str(a.get("phone")) == phone), None)
                if not acct:
                    return self._send(200, json.dumps({"ok": False, "error": "账号库中没有 %s" % phone},
                                                      ensure_ascii=False).encode("utf-8"))
                act = (data.get("act_url") or "").strip() or DEFAULT_ACT_URL
                tok, sess, err = refresh_one_account(acct, act, bool(data.get("verify")))
                if tok:
                    acct["app_token"] = tok
                    acct["app_token_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    acct["session_token"] = sess
                    acct["status"] = "ok"
                    acct["status_text"] = ""
                    acct["last_error"] = ""
                    acct["refresh_count"] = int(acct.get("refresh_count", 0)) + 1
                    acct["last_seen"] = acct["app_token_at"]
                    acct["updated_at"] = acct["last_seen"]
                    save_accounts(accs, ACCOUNTS_PATH)
                    write_app_token_file(accs, APP_TOKEN_PATH)
                    out = {
                        "ok": True, "phone": phone, "app_token": tok, "session_token": sess,
                        "app_token_at": acct["app_token_at"],
                        "lines": ["✔ 换票成功 · %s" % phone,
                                  "app_token: %s" % tok,
                                  "会话票据: %s" % (sess or "(未签发)"),
                                  "换票时间: %s" % acct["app_token_at"]],
                    }
                else:
                    if not str(err).startswith(ERR_NET):
                        acct["status"] = "invalid"
                        acct["status_text"] = err
                    else:
                        acct["status_text"] = "（网络/环境问题，未判失效）"
                    acct["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    acct["updated_at"] = acct["last_seen"]
                    save_accounts(accs, ACCOUNTS_PATH)
                    out = {"ok": False, "phone": phone, "error": err,
                           "lines": ["✘ 换票失败 · %s" % phone, "原因: %s" % err,
                                     "提示: %s" % ("服务端连不上移动网关，请检查出网/依赖（curl_cffi）"
                                                   if str(err).startswith(ERR_NET)
                                                   else "xk 需在当前登录设备上重新抓取")]}
                out["accounts"] = accounts_view()
                out["stats"] = account_stats()
                return self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))
        if path == "/api/accounts/refresh":
            with _lock:
                res = refresh_all_accounts((data.get("act_url") or "").strip(),
                                           bool(data.get("verify")))
                res["accounts"] = accounts_view()
                return self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"))
        if path == "/api/run":
            with _lock:
                res = run_flow(data)
            return self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"))

        if path in ("/api/sms/send-code", "/api/sms/login", "/api/sms/three-network"):
            if not _SMS_OK:
                return self._send(200, json.dumps(
                    {"ok": False, "error": "短信登录模块未加载：请确认 cmcc_sms.py / cmcc_crypto.py / "
                                           "builtin_templates.py / crypto_engine.py 与本文件同目录，"
                                           "且已安装 pycryptodome / curl_cffi"},
                    ensure_ascii=False).encode("utf-8"))

        if path == "/api/sms/send-code":
            with _lock:
                r = act_send_code_real((data.get("phone") or "").strip())
            return self._send(200, json.dumps(r, ensure_ascii=False, indent=2).encode("utf-8"))

        if path == "/api/sms/login":
            with _lock:
                r = act_login_real((data.get("code") or "").strip(),
                                   (data.get("phone") or "").strip(),
                                   (data.get("dev_token") or "").strip() or None)
                if r.get("ok") and r.get("body_b64"):
                    try:
                        r["cmcc"] = run_flow({
                            "body_b64": r["body_b64"],
                            "phone": (data.get("phone") or "").strip(),
                            "province": (data.get("province") or "").strip(),
                            "city": (data.get("city") or "").strip(),
                            "act_url": (data.get("act_url") or "").strip(),
                            "verify": True,
                        })
                    except Exception as ex:
                        r["cmcc"] = {"ok": False, "error": repr(ex)}
            return self._send(200, json.dumps(r, ensure_ascii=False, indent=2).encode("utf-8"))

        if path == "/api/sms/three-network":
            with _lock:
                r = act_three_network((data.get("phone") or "").strip(),
                                      (data.get("code") or "").strip(),
                                      (data.get("dev_token") or "").strip() or None)
                if r.get("ok") and r.get("body_b64"):
                    try:
                        r["cmcc"] = run_flow({
                            "body_b64": r["body_b64"],
                            "phone": (data.get("phone") or "").strip(),
                            "province": (data.get("province") or "").strip(),
                            "city": (data.get("city") or "").strip(),
                            "act_url": (data.get("act_url") or "").strip(),
                            "verify": True,
                        })
                    except Exception as ex:
                        r["cmcc"] = {"ok": False, "error": repr(ex)}
            return self._send(200, json.dumps(r, ensure_ascii=False, indent=2).encode("utf-8"))

        return self._send(404, b'{"error":"not found"}')


def main():
    ap = argparse.ArgumentParser(description="移动 qwhdsso 会话票据 · 本地 Web 服务")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--shift-port", action="store_true",
                    help="端口被占用时顺延到下一个（默认直接报错退出，避免服务活着却连不上）")
    args = ap.parse_args()

    if not os.path.exists(UI_FILE):
        sys.stderr.write("[warn] 找不到 UI 文件: %s\n" % UI_FILE)

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False
        daemon_threads = True

    ports = range(args.port, args.port + 20) if args.shift_port else [args.port]
    last_err = ""
    for p in ports:
        try:
            srv = Server((args.host, p), Handler)
            port = p
            break
        except OSError as ex:
            last_err = str(ex)
    else:
        msg = ("端口 %s:%d 已被占用：%s" % (args.host, args.port, last_err))
        if not args.shift_port:
            msg += ("\n    处理办法："
                    "\n      ① 停掉占用进程： ss -lntp | grep %d   然后 kill -9 <PID>"
                    "\n      ② 换端口启动  ： --port %d"
                    "\n      ③ 或允许顺延  ： --shift-port（客户端会自动扫描发现）" % (args.port, args.port + 1))
        raise SystemExit(msg)

    url = "http://%s:%d/" % (args.host, port)
    print("=" * 60)
    print("  中国移动 qwhdsso 会话票据服务已启动")
    print("  访问地址: %s" % url)
    print("  存档文件: %s" % STORE_FILE)
    if args.host in ("0.0.0.0", "::", ""):
        print("  监听模式: 所有网卡（0.0.0.0 = 局域网内其它设备可直接访问）")
        print("  本机访问: http://127.0.0.1:%d/" % port)
        for ip in _lan_ips():
            print("  局域网:   http://%s:%d/" % (ip, port))
    else:
        print("  监听模式: 仅 %s" % args.host)
    print("  按 Ctrl+C 退出")
    print("=" * 60)
    sys.stdout.flush()

    try:
        from cmcc_apptoken_sim import http_selftest
        dep, st, body = http_selftest()
        print("[自检] 依赖: %s" % dep)
        print("[自检] 移动网关 client.app.coc.10086.cn -> HTTP %s %s" % (st, body[:100]))
        if st == 0:
            print("[自检] ⚠ 连不上移动网关，换票会失败。常见原因："
                  "① 没装 curl_cffi（pip install curl_cffi）② 服务器出网受限")
        sys.stdout.flush()
    except Exception as ex:
        print("[自检] 执行失败: %r" % ex)
        sys.stdout.flush()
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
