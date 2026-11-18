#!/bin/sh
# 容器入口：修复 /data 属主 → 补齐数据文件 → 降权拉起服务
#
# 为什么要修属主：NAS 上通常把 ./data 目录 bind mount 进来，目录属主是
# root 或 NAS 的管理员账号，容器内的 appuser(1000) 写不进去，一保存账号就报
# PermissionError。所以这里允许容器以 root 启动，先 chown 再降权到 appuser。
set -e

DATA_DIR="${DATA_DIR:-/data}"
APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R "$APP_UID:$APP_GID" "$DATA_DIR" 2>/dev/null \
        || echo "[entrypoint] 警告：$DATA_DIR 属主修复失败，写入可能报 PermissionError"
fi

for f in cmcc_accounts.json app_token.json cmcc_web_store.json; do
    [ -f "$DATA_DIR/$f" ] || : > "$DATA_DIR/$f"
    if [ "$(id -u)" = "0" ]; then
        chown "$APP_UID:$APP_GID" "$DATA_DIR/$f" 2>/dev/null || true
    fi
done

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8767}"

echo "[entrypoint] 监听 ${HOST}:${PORT}  数据目录 ${DATA_DIR}"
echo "[entrypoint] 账号库 $(wc -c < "$DATA_DIR/cmcc_accounts.json" 2>/dev/null || echo 0) bytes"

run_py() {
    # --no-browser：容器里没有浏览器，必须关掉自动打开
    exec python -u /app/cmcc_web.py --host "$HOST" --port "$PORT" --no-browser "$@"
}

# 已是非 root（compose 里指定 user: 时）直接跑
if [ "$(id -u)" != "0" ]; then
    run_py "$@"
fi

# root 启动 → 用 setpriv 降权，python 进程始终以 appuser 运行
if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups \
        python -u /app/cmcc_web.py --host "$HOST" --port "$PORT" --no-browser "$@"
fi

echo "[entrypoint] 警告：未找到 setpriv，将以 root 运行"
run_py "$@"
