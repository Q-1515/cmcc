#!/usr/bin/env bash
# ============================================
#  CMCC 账号工作台 · 安装 / 启动 / 管理
#  参考 install.sh 的结构：环境检查 → 端口检查 → 目录权限
#                        → 依赖检查 → 启动服务 → 部署自检 → 输出访问信息
#
#  运行后进入**交互式菜单**，自行选择要执行的功能：
#     1) 启动服务        2) 重启服务        3) 停止服务
#     4) 查看状态        5) 查看日志        6) 健康检查
#     7) 依赖说明/安装   8) 部署为开机自启   0) 退出
#
#  用法：
#     bash install.sh              # 交互菜单（默认）
#     bash install.sh start        # 免交互，直接执行某项
#     bash install.sh restart|stop|status|logs|health|deps|install
#
#  可选环境变量：
#     HOST=0.0.0.0              监听地址（默认全部网卡）
#     PORT=8767                 监听端口
#     SERVICE_NAME=cmcc-token   systemd 服务名
#     INSTALL_DIR=…             程序目录（默认脚本所在目录）
#     SKIP_PIP=1                跳过依赖安装
# ============================================
set -euo pipefail

APP_DIR="${INSTALL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8767}"
SERVICE_NAME="${SERVICE_NAME:-cmcc-token}"
LOG_DIR="${LOG_DIR:-${APP_DIR}/logs}"
LOG_FILE="${LOG_DIR}/service.log"
PID_FILE="${LOG_DIR}/service.pid"
SKIP_PIP="${SKIP_PIP:-0}"
USE_SYSTEMD=0
PYBIN=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${BLUE}[信息]${NC} $1"; }
ok()    { echo -e "${GREEN}[成功]${NC} $1"; }
warn()  { echo -e "${YELLOW}[警告]${NC} $1"; }
fail()  { echo -e "${RED}[错误]${NC} $1"; exit 1; }
step()  { echo -e "${CYAN}==>${NC} $1"; }

# ==================== 工具函数 ====================
# 找到可用的 Python 解释器
find_python() {
  if [ -n "${PYTHON_BIN:-}" ] && command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "${PYTHON_BIN}"; return 0
  fi
  # Windows：优先用 D://Program Files\python.exe（用户实际在用的那个解释器）
  for w in "/d/Program Files/python.exe" "/c/Program Files/python.exe"; do
    if [ -x "$w" ]; then echo "$w"; return 0; fi
  done
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}

# 列出监听指定端口的行（兼容 Linux ss/netstat 与 Windows netstat -ano）
port_lines() {
  if command -v ss >/dev/null 2>&1; then
    ss -lntp 2>/dev/null | grep -E ":${1}[[:space:]]" || true
  elif command -v netstat >/dev/null 2>&1; then
    # Linux: netstat -lntp；Windows: netstat -ano（-t/-p 不被支持）
    netstat -lntp 2>/dev/null | grep -E ":${1}[[:space:]]" \
      || netstat -ano 2>/dev/null | grep -E ":${1}[[:space:]].*LISTENING" || true
  fi
}

# 端口是否被占用（返回 0=占用）
port_busy() { [ -n "$(port_lines "$1")" ]; }

# 列出本机局域网 IPv4
lan_ips() {
  local out=""
  if command -v hostname >/dev/null 2>&1; then
    out="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' || true)"
  fi
  if [ -z "$out" ] && command -v ipconfig >/dev/null 2>&1; then
    out="$(ipconfig 2>/dev/null | tr -d '\r' | grep -i 'IPv4' \
      | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
      | grep -v '^127\.' | grep -v '^169\.254\.' | sort -u || true)"
    if [ -z "$out" ]; then   # 少数系统没有 IPv4 行，退回全量提取并排除掩码
      out="$(ipconfig 2>/dev/null | tr -d '\r' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
        | grep -v '^127\.' | grep -v '^169\.254\.' | grep -v '^255\.' | sort -u || true)"
    fi
  fi
  echo "$out"
}

pause() { echo ""; read -r -p "按回车键继续…" _ || true; }

# 打印访问信息横幅
print_access() {
  echo ""
  echo "============================================"
  echo -e "${GREEN}  服务已就绪${NC}"
  echo "============================================"
  echo "  本机访问：  http://127.0.0.1:${PORT}"
  local ips; ips="$(lan_ips)"
  if [ -n "$ips" ]; then
    while read -r ip; do
      [ -z "$ip" ] && continue
      echo "  局域网：    http://${ip}:${PORT}"
    done <<< "$ips"
  else
    echo "  局域网：    (未检测到局域网 IP)"
  fi
  echo "  监听地址：  ${HOST}:${PORT}  (0.0.0.0 = 所有网卡可访问)"
  echo ""
  echo "  数据目录：  ${APP_DIR}"
  echo "    账号库：  cmcc_accounts.json"
  echo "    票据文件：app_token.json"
  echo ""
  echo "  常用命令：  bash install.sh status | logs | health | restart | stop"
  echo "  手机使用：与服务器连同一局域网，浏览器打开上面的局域网地址"
  echo "============================================"
}

# ==================== 1. 环境检查 ====================
check_python() {
  info "检查 Python 环境..."
  local py; py="$(find_python)" || fail "未找到 Python，请先安装：https://www.python.org/downloads/ （需 >= 3.8）"
  local ver; ver="$("$py" -V 2>&1 | awk '{print $2}')"
  "$py" - <<'EOF' || fail "需要 Python 3.8 及以上"
import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)
EOF
  PYBIN="$py"
  ok "Python $ver（${PYBIN}）"
  echo "        解释器路径：$(command -v "$py")"
  echo "        包安装位置：$("$py" -c 'import site,sys;print(sys.prefix)')/Lib/site-packages"
}

# ==================== 2. 端口检查 ====================
check_port() {
  info "检查端口 ${HOST}:${PORT} ..."
  if port_busy "$PORT"; then
    warn "端口 ${PORT} 已被占用："
    port_lines "$PORT" | sed 's/^/    /' || true
    warn "若是本服务自身占用，请先执行：bash install.sh stop"
    warn "若被其它程序占用，换端口启动： PORT=8768 bash install.sh start"
    return 1
  fi
  ok "端口 ${PORT} 可用"
}

# ==================== 3. 目录与权限 ====================
check_dirs() {
  info "准备目录..."
  mkdir -p "$LOG_DIR"
  chmod 755 "$LOG_DIR" 2>/dev/null || true
  [ -f "${APP_DIR}/cmcc_web.py" ] || fail "在 ${APP_DIR} 下找不到 cmcc_web.py"
  [ -f "${APP_DIR}/cmcc_web_ui.html" ] || warn "找不到 cmcc_web_ui.html，页面可能无法打开"
  ok "程序目录：${APP_DIR}"
  ok "日志目录：${LOG_DIR}"
}

# ==================== 4. 依赖检查与安装 ====================
# 安装单个 pip 包（依次尝试普通 / break-system-packages / 国内镜像）
pip_install() {
  local pkg="$1"
  "$PYBIN" -m pip install --quiet "$pkg" >/dev/null 2>&1 && return 0
  "$PYBIN" -m pip install --quiet --break-system-packages "$pkg" >/dev/null 2>&1 && return 0
  "$PYBIN" -m pip install --quiet -i https://pypi.tuna.tsinghua.edu.cn/simple "$pkg" >/dev/null 2>&1 && return 0
  "$PYBIN" -m pip install --quiet --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple "$pkg" >/dev/null 2>&1 && return 0
  "$PYBIN" -m pip install --quiet -i https://mirrors.aliyun.com/pypi/simple/ "$pkg" >/dev/null 2>&1 && return 0
  "$PYBIN" -m pip install --quiet --break-system-packages -i https://mirrors.aliyun.com/pypi/simple/ "$pkg" >/dev/null 2>&1 && return 0
  return 1
}

check_deps() {
  info "检查依赖（curl_cffi / pycryptodome）..."
  if [ "${SKIP_PIP}" = "1" ]; then
    warn "已按要求跳过依赖安装"
    return 0
  fi
  if "$PYBIN" -c "import curl_cffi" >/dev/null 2>&1; then
    ok "curl_cffi 已安装"
  else
    info "安装 curl_cffi ..."
    pip_install curl_cffi && ok "curl_cffi 安装完成" \
      || warn "curl_cffi 安装失败（将回退系统 curl / urllib）"
  fi
  if "$PYBIN" -c "import Crypto" >/dev/null 2>&1; then
    ok "pycryptodome 已安装"
  else
    info "安装 pycryptodome ..."
    pip_install pycryptodome && ok "pycryptodome 安装完成" \
      || warn "pycryptodome 安装失败（短信登录功能将不可用，加解密仍走内置纯 Python 兜底）"
  fi
}

# 依赖说明：告诉用户「在哪里加载、在哪里安装」
show_deps() {
  # 解析当前解释器的 site-packages 位置
  PYPREFIX="$("$PYBIN" -c 'import sys;print(sys.prefix)' 2>/dev/null || echo '')"
  PYSITE="$("$PYBIN" -c 'import site;ps=[p for p in (site.getsitepackages() or []) if "site-packages" in p];print((ps or site.getsitepackages() or [""])[0])' 2>/dev/null || echo '')"
  cat <<EOF

$(ok "环境依赖说明")

  【A. 代码怎么加载依赖】
    入口文件  cmcc_web.py
      ├─ 顶部 sys.path.insert(0, 脚本所在目录)
      │    → 同目录的 .py 文件（cmcc_apptoken_sim.py / cmcc_sms.py / cmcc_crypto.py
      │      / builtin_templates.py / crypto_engine.py）直接从本地加载，不走 pip
      ├─ import cmcc_apptoken_sim   ← 必需，缺了整个服务起不来
      │    · Crypto.Cipher.AES (pycryptodome)  ← 有纯 Python 兜底 _aes_cbc_decrypt_pp
      │    · curl_cffi               ← 有兜底：系统 curl 命令 → urllib
      └─ import cmcc_sms             ← 可选，try/except 包裹
           · 缺 pycryptodome 时该模块导入失败 → 只影响「短信登录」，换票不受影响

  【B. 依赖装到哪里】
    运行时用的是「当前解释器」的 site-packages：
      解释器      : ${PYBIN:-<未检测>}
      前缀        : ${PYPREFIX:-<未检测>}
      安装目录    : ${PYSITE:-<未检测>}
    查看实际路径： ${PYBIN:-python} -c "import site;print(site.getsitepackages())"

  【C. 依赖清单】
    ┌──────────────────┬────────────┬────────────────────────────────┐
    │ 包                │ 是否必需   │ 缺失时的表现                  │
    ├──────────────────┼────────────┼────────────────────────────────┤
    │ curl_cffi        │ 建议装     │ 回退系统 curl → urllib，       │
    │                  │            │ TLS 指纹可能被 WAF 拦截        │
    │ pycryptodome     │ 建议装     │ 加解密走内置纯 Python 兜底；   │
    │                  │            │ 短信登录不可用                 │
    └──────────────────┴────────────┴────────────────────────────────┘
    其它全部是 Python 标准库，无需安装。

  【D. 手动安装命令】
    ${PYBIN:-python} -m pip install curl_cffi pycryptodome
    # Debian 12+ 若报 externally-managed-environment：
    ${PYBIN:-python} -m pip install --break-system-packages curl_cffi pycryptodome
    # 走国内镜像：
    ${PYBIN:-python} -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple curl_cffi pycryptodome

EOF
}

# 依赖体检（只看不装）
deps_check() {
  check_python
  echo ""
  info "依赖体检："
  if "$PYBIN" -c "import curl_cffi;print(curl_cffi.__version__)" >/dev/null 2>&1; then
    ok "  curl_cffi      $( "$PYBIN" -c 'import curl_cffi;print(curl_cffi.__version__)' 2>/dev/null )"
  else
    warn "  curl_cffi      未安装 → 将用系统 curl / urllib 兜底"
  fi
  if "$PYBIN" -c "import Crypto;print(Crypto.__version__)" >/dev/null 2>&1; then
    ok "  pycryptodome   $( "$PYBIN" -c 'import Crypto;print(Crypto.__version__)' 2>/dev/null )"
  else
    warn "  pycryptodome   未安装 → 加解密走内置纯 Python，短信登录不可用"
  fi
  if "$PYBIN" -c "import cmcc_sms" >/dev/null 2>&1; then
    ok "  cmcc_sms 模块  加载正常（短信登录可用）"
  else
    warn "  cmcc_sms 模块  加载失败 → 短信登录接口会返回提示，换票不受影响"
  fi
  echo ""
  info "本地模块文件："
  for f in cmcc_web.py cmcc_web_ui.html cmcc_apptoken_sim.py cmcc_sms.py cmcc_crypto.py builtin_templates.py crypto_engine.py; do
    if [ -f "${APP_DIR}/${f}" ]; then echo "    ✔ ${f}"; else echo "    ✘ ${f}（缺失）"; fi
  done
  echo ""
  info "数据文件："
  for f in cmcc_accounts.json app_token.json cmcc_web_store.json; do
    if [ -f "${APP_DIR}/${f}" ]; then echo "    ✔ ${f}"; else echo "    - ${f}（首次运行自动生成）"; fi
  done
}

# ==================== 5. 启动服务 ====================
start_service() {
  info "启动服务 ..."

  # 优先用 systemd（可开机自启、可托管）
  if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
    USE_SYSTEMD=1
    if [ ! -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
      info "注册 systemd 服务 ${SERVICE_NAME} ..."
      cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=CMCC qwhdsso 会话票据工作台 (qwhdsso token workbench)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=${APP_DIR}
ExecStart=${PYBIN} -u ${APP_DIR}/cmcc_web.py --host ${HOST} --port ${PORT} --no-browser
Restart=always
RestartSec=5
StartLimitIntervalSec=0
KillSignal=SIGTERM
TimeoutStopSec=10
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
      systemctl daemon-reload
      systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 || true
      ok "已注册并设置开机自启（systemctl enable ${SERVICE_NAME}）"
    else
      # 已存在则同步监听地址
      sed -i "s/--host [0-9.]*/--host ${HOST}/; s/--port [0-9]*/--port ${PORT}/" \
        "/etc/systemd/system/${SERVICE_NAME}.service"
      systemctl daemon-reload
    fi
    systemctl restart "${SERVICE_NAME}"
    sleep 3
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
      ok "服务已启动并设置为开机自启"
    else
      fail "服务启动失败，请查看日志：journalctl -u ${SERVICE_NAME} -n 50"
    fi
    return 0
  fi

  # 无 systemd（或非 root）→ 独立进程方式
  USE_SYSTEMD=0
  info "以独立进程方式启动（未检测到可用的 systemd 管理权限）"
  cd "$APP_DIR"
  nohup "$PYBIN" -u "${APP_DIR}/cmcc_web.py" --host "${HOST}" --port "${PORT}" --no-browser \
    >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  ok "进程已拉起（PID $(cat "$PID_FILE")），日志：${LOG_FILE}"
}

stop_service() {
  info "停止服务 ..."
  if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ] \
     && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}"; then
    systemctl stop "${SERVICE_NAME}" && ok "服务已停止"
    return 0
  fi
  if [ -f "$PID_FILE" ]; then
    local pid; pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      ok "已停止进程 ${pid}"
    else
      warn "进程 ${pid} 不存在"
    fi
    rm -f "$PID_FILE"
  else
    # 兜底：按端口找进程
    local pids
    pids="$(command -v lsof >/dev/null 2>&1 && lsof -ti tcp:"${PORT}" 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      ok "已停止占用端口 ${PORT} 的进程"
    else
      warn "没有找到正在运行的实例"
    fi
  fi
}

status_service() {
  echo "============================================"
  echo "  CMCC 账号工作台 · 运行状态"
  echo "============================================"
  if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ] \
     && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}"; then
    systemctl status "${SERVICE_NAME}" --no-pager || true
    echo ""
    echo "--- 开机自启 ---"
    systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || echo "未启用"
  elif [ -f "$PID_FILE" ]; then
    local pid; pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      echo -e "  进程运行中（PID ${pid}）"
    else
      echo "  进程未运行（残留 PID 文件：${PID_FILE}）"
    fi
  else
    echo "  未在运行"
  fi
  echo ""
  echo "--- 监听端口 ---"
  local lines; lines="$(port_lines "$PORT")"
  if [ -n "$lines" ]; then
    echo "$lines" | sed 's/^/  /'
  else
    echo "  端口 ${PORT} 未监听"
  fi
  echo ""
  echo "--- 接口自检 ---"
  if command -v curl >/dev/null 2>&1; then
    curl -s --noproxy "*" --max-time 5 "http://127.0.0.1:${PORT}/api/state" | head -c 200 || true
    echo ""
  fi
  echo ""
  echo "--- 最近日志 ---"
  tail -n 12 "$LOG_FILE" 2>/dev/null || echo "  (暂无日志)"
  echo "============================================"
}

health_check() {
  info "健康检查 http://127.0.0.1:${PORT}/api/state ..."
  if command -v curl >/dev/null 2>&1; then
    if curl -s --noproxy "*" --max-time 8 "http://127.0.0.1:${PORT}/api/state" >/dev/null 2>&1; then
      ok "接口正常"
    else
      fail "接口无响应，请看日志：tail -f ${LOG_FILE}"
    fi
  else
    warn "未安装 curl，跳过接口自检"
  fi
}

# 部署为开机自启（Linux systemd）
install_systemd() {
  if ! command -v systemctl >/dev/null 2>&1; then
    fail "本机没有 systemd，该功能仅适用于 Linux"
  fi
  if [ "$(id -u)" -ne 0 ]; then
    fail "需要 root 权限，请用 sudo bash install.sh install"
  fi
  check_python
  check_dirs
  step "写入 systemd 单元 ${SERVICE_NAME} ..."
  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=CMCC qwhdsso 会话票据工作台 (qwhdsso token workbench)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=${APP_DIR}
ExecStart=${PYBIN} -u ${APP_DIR}/cmcc_web.py --host ${HOST} --port ${PORT} --no-browser
Restart=always
RestartSec=5
StartLimitIntervalSec=0
KillSignal=SIGTERM
TimeoutStopSec=10
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1 && ok "已设置开机自启"
  systemctl restart "${SERVICE_NAME}"
  sleep 3
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    ok "服务已启动"
  else
    fail "服务启动失败：journalctl -u ${SERVICE_NAME} -n 50"
  fi
  print_access
}

# ==================== 各项动作 ====================
do_start() {
  echo "============================================"
  echo "        CMCC 账号工作台 · 启动程序"
  echo "============================================"
  check_python
  check_port || return 1
  check_dirs
  check_deps
  start_service
  health_check
  print_access
}

do_restart() {
  echo "============================================"
  echo "        CMCC 账号工作台 · 重启程序"
  echo "============================================"
  stop_service
  sleep 1
  check_python
  check_port || return 1
  check_dirs
  start_service
  health_check
  print_access
}

# ==================== 交互式菜单 ====================
show_menu() {
  echo ""
  echo "============================================"
  echo "     CMCC 账号工作台 · 主菜单"
  echo "============================================"
  echo -e "  ${CYAN}1)${NC} 启动服务        ${CYAN}2)${NC} 重启服务        ${CYAN}3)${NC} 停止服务"
  echo -e "  ${CYAN}4)${NC} 查看状态        ${CYAN}5)${NC} 查看日志        ${CYAN}6)${NC} 健康检查"
  echo -e "  ${CYAN}7)${NC} 依赖说明/安装   ${CYAN}8)${NC} 部署为开机自启   ${CYAN}0)${NC} 退出"
  echo "============================================"
  echo "  监听 ${HOST}:${PORT}   程序目录 ${APP_DIR}"
  echo ""
}

main_menu() {
  while true; do
    show_menu
    local choice=""
    read -r -p "请输入编号（回车=退出）：" choice || choice="0"
    case "$choice" in
      1) do_start ;;
      2) do_restart ;;
      3) stop_service ;;
      4) status_service ;;
      5)
        if [ -f "$LOG_FILE" ]; then
          echo "（Ctrl+C 退出日志跟踪）"
          tail -n "${2:-100}" -f "$LOG_FILE"
        else
          warn "日志文件不存在：${LOG_FILE}"
        fi
        ;;
      6) health_check ;;
      7) deps_check; show_deps ;;
      8) install_systemd ;;
      0|"") echo "再见 👋"; exit 0 ;;
      *) warn "无效选项：$choice" ;;
    esac
    pause
  done
}

# ==================== 主流程 ====================
ACTION="${1:-}"
case "$ACTION" in
  "")            main_menu ;;
  start)         do_start ;;
  stop)          stop_service ;;
  restart)       do_restart ;;
  status)        status_service ;;
  logs)          tail -n "${2:-100}" -f "$LOG_FILE" ;;
  health)        health_check ;;
  deps)          deps_check; show_deps ;;
  install)       install_systemd ;;
  *)
    echo "用法: bash install.sh [菜单交互 | start|stop|restart|status|logs|health|deps|install]"
    exit 1
    ;;
esac
