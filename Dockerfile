# syntax=docker/dockerfile:1
# CMCC 账号工作台（qwhdsso 会话票据服务）
# 基础镜像用 debian slim：curl_cffi 提供 manylinux wheel，musl(Alpine) 上装不稳
#
# 国内构建建议（拉不到 Docker Hub / PyPI 慢时）：
#   docker build \
#     --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim \
#     --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#     -t cmcc-workbench:1.2.0 .
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PORT=8767 \
    HOST=0.0.0.0

WORKDIR /app

# ca-certificates: 访问移动网关的 TLS 校验
# curl: 运行时兜底传输通道（curl_cffi 不可用时） + HEALTHCHECK 探活
# tzdata: 日志/票据时间戳按东八区
# util-linux: 提供 setpriv，供 entrypoint 从 root 降权到 appuser
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl tzdata util-linux \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
# pycryptodome 必需（缺失则短信登录不可用）；curl_cffi 装不上不阻断构建——
# 程序本身会回退到系统 curl，只是 TLS 指纹可能被 WAF 拦
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" "pycryptodome>=3.19" \
 && (pip install --no-cache-dir -i "$PIP_INDEX_URL" "curl_cffi>=0.6" \
     || echo "[warn] curl_cffi 安装失败，运行时将回退系统 curl")

# 业务代码 + 前端页面（.dockerignore 已排除数据文件与文档）
COPY . /app

# 数据文件（账号库 / 票据 / 设备档案）落 /data 卷，用软链接回脚本目录：
# 代码里路径是 os.path.dirname(__file__)，只能这样把写操作重定向到卷上
RUN rm -f /app/cmcc_accounts.json /app/app_token.json /app/cmcc_web_store.json \
 && mkdir -p /data \
 && ln -sf /data/cmcc_accounts.json /app/cmcc_accounts.json \
 && ln -sf /data/app_token.json       /app/app_token.json \
 && ln -sf /data/cmcc_web_store.json  /app/cmcc_web_store.json \
 && chmod +x /app/entrypoint.sh \
 && useradd -m -u 1000 -s /bin/sh appuser \
 && chown -R appuser:appuser /app /data \
 && test -L /app/cmcc_accounts.json && test -L /app/app_token.json \
 && test -L /app/cmcc_web_store.json \
 && python -c "import Crypto, sys; sys.exit(0)"

USER root

VOLUME ["/data"]
EXPOSE 8767

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/stats" >/dev/null || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
