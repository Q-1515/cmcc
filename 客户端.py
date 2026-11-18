#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMCC 工作台 · 换票客户端模板
"""
import json
import os
import re
import socket
import urllib.error
import urllib.request

# ==================== 配置区（改这里） ====================
CMCODE = os.environ.get("CMCC_CMCODE", "127.0.0.1:8767")   # 工作台服务地址
REFS = [
    "18788605001",  # 5001
    # "13800138000",  # 8000
]
# ========================================================
TIMEOUT = 180          # 换票：工作台内部要串行 5 个上游请求
PROBE_TIMEOUT = 1.2    # 探活：短超时
VERIFY = not re.match(r"^(off|disabled|0|false|no)$",
                      (os.environ.get("CMCC_WB_VERIFY") or "true").strip(), re.I)
_RESOLVED = None       # None=没探过 / ""=探过全失败 / 字符串=可用地址
_PROBE_LOG = []


def _opener():
    """绕过环境里的 HTTP_PROXY（本机代理会劫持对 127.0.0.1 的请求）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _normalize(raw):
    """CMCC_CMCODE → host:port，兼容 http:// 前缀 / 尾斜杠 / 路径 / 省略端口。"""
    s = str(raw or "").strip().strip('"').strip("'")
    s = re.sub(r"^https?://", "", s, flags=re.I)
    s = re.split(r"[/?#]", s, maxsplit=1)[0].strip().rstrip("/")
    if not s:
        return "127.0.0.1:8767"
    if s.startswith("["):
        if "]" in s and ":" not in s.split("]", 1)[1]:
            s += ":8767"
    elif ":" not in s:
        s += ":8767"
    return s


def _gateway():
    """读 /proc/net/route 拿容器默认网关，青龙里 127.0.0.1 指不到宿主机。"""
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                p = line.split()
                if len(p) > 2 and p[1] == "00000000" and p[2] != "00000000":
                    return socket.inet_ntoa(bytes.fromhex(p[2])[::-1])
    except Exception:
        pass
    return ""


def _hosts():
    addr = _normalize(CMCODE)
    host, sep, port_s = addr.rpartition(":")
    if not sep or not host:
        host, port_s = addr, "8767"
    try:
        port = int(port_s)
    except ValueError:
        port = 8767
    gw = _gateway()
    cands = [host, "127.0.0.1", "localhost"]
    if gw:
        cands.append(gw)
    cands += ["host.docker.internal", "172.17.0.1"]
    seen, out = set(), []
    for h in cands:
        h = (h or "").strip()
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out, port


def _url(host, port):
    if ":" in host and not host.startswith("["):
        return "http://[%s]:%d" % (host, port)
    return "http://%s:%d" % (host, port)


def _probe(base):
    """探活 /api/state，返回 (是否命中, 说明)。"""
    try:
        req = urllib.request.Request(base + "/api/state", method="GET")
        with _opener().open(req, timeout=PROBE_TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        if isinstance(d, dict) and ("accounts" in d or "stats" in d):
            return True, "✔ /api/state 正常"
        return False, "/api/state 返回格式不符"
    except urllib.error.HTTPError as ex:
        return False, "HTTP %s" % ex.code
    except Exception as ex:
        return False, "%s: %s" % (type(ex).__name__, ex)


def _resolve():
    """固定端口，逐个候选主机探一次；结果（含失败）缓存，避免每个账号重探。"""
    global _RESOLVED
    if _RESOLVED is not None:
        return _RESOLVED
    hosts, port = _hosts()
    log = []
    for h in hosts:
        base = _url(h, port)
        hit, info = _probe(base)
        log.append((base, info))
        if hit:
            _PROBE_LOG[:] = log
            _RESOLVED = base
            return base
    # /api/state 不存在但端口 TCP 通（新版工作台）→ 仍尝试换票
    for h in hosts:
        try:
            with socket.create_connection((h.strip("[]"), port), timeout=0.6):
                base = _url(h, port)
                log.append((base, "TCP 可达但 /api/state 不匹配，仍尝试换票"))
                _PROBE_LOG[:] = log
                _RESOLVED = base
                return base
        except Exception:
            pass
    _PROBE_LOG[:] = log
    _RESOLVED = ""
    return ""


def _call(path, payload=None):
    """调用工作台接口，返回解析后的 JSON（异常转结构化错误，不抛 traceback）。"""
    base = _resolve()
    if not base:
        return {"ok": False, "error": "工作台不可达（固定端口 %s）" % _normalize(CMCODE)}
    if payload is None:
        req = urllib.request.Request(base + path, method="GET")
    else:
        req = urllib.request.Request(base + path,
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    try:
        with _opener().open(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        try:
            detail = ex.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        return {"ok": False, "error": "HTTP %s %s" % (ex.code, detail)}
    except Exception as ex:
        return {"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}
    try:
        d = json.loads(raw)
    except Exception:
        return {"ok": False, "error": "响应不是 JSON: %s" % raw[:200]}
    if not isinstance(d, dict):
        return {"ok": False, "error": "响应格式异常: %s" % str(d)[:200]}
    d["_base"] = base
    return d


def run_one(phone, act_url=""):
    """执行单账号换票，返回结果 dict。"""
    return _call("/api/accounts/run",
                 {"phone": phone, "act_url": act_url, "verify": bool(VERIFY)})


def main():
    print("CMCC 工作台 · 换票  →  %s（固定端口，主机自动探测）" % _normalize(CMCODE))
    targets = [p.strip() for p in REFS if p.strip()]
    if not targets:
        print("REFS 为空，无账号可换")
        return
    base = _resolve()
    if not base:
        print("✘ 找不到工作台，逐条探测结果：")
        for b, info in _PROBE_LOG:
            print("    %-42s %s" % (b, info))
        return
    print("已定位工作台: %s   verify=%s" % (base, bool(VERIFY)))
    ok = 0
    for phone in targets:
        r = run_one(phone)
        if r.get("ok") and r.get("app_token"):
            ok += 1
            print("✔ %s  换票成功" % phone)
            print("    app_token : %s" % (r.get("app_token") or ""))
            if r.get("session_token"):
                print("    会话票据 : %s   (30 分钟滑动)" % r.get("session_token"))
        else:
            print("✘ %s  失败: %s" % (phone, r.get("error") or "无 app_token / 未知错误"))
    print("\n完成：%d/%d 成功" % (ok, len(targets)))


if __name__ == "__main__":
    main()
