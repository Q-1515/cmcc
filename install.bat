@echo off
chcp 936 >nul
cd /d "%~dp0"
setlocal

rem ============================================================
rem  CMCC 账号工作台 . 一键安装 / 启动 / 管理（Windows）
rem  交互式菜单，功能与 Linux 的 install.sh 一致
rem
rem  编码说明：本文件为 GBK(ANSI) + CRLF，控制台已由 chcp 936
rem  统一为 GBK，两者一致，中文才不会乱码。
rem  请勿改成 UTF-8 保存，也请勿改 chcp 65001。
rem ============================================================

rem ---------- 定位 Python ----------
rem 优先用 py -3（Windows 标准启动器，会指向用户实际在用的解释器）
set "PY=py -3"
py -3 -c "import sys" >nul 2>&1
if errorlevel 1 set "PY=python"

rem 统一 Python 输出编码为 GBK，与控制台代码页一致
set "PYTHONIOENCODING=gbk"

set "HOST=127.0.0.1"
set "PORT=8767"

:menu
echo.
echo ============================================================
echo       CMCC 账号工作台 . 主菜单
echo ============================================================
echo   1^) 启动服务        2^) 重启服务        3^) 停止服务
echo   4^) 查看状态        5^) 查看日志        6^) 健康检查
echo   7^) 依赖说明/安装   8^) 部署为开机自启   0^) 退出
echo ============================================================
echo   监听 %HOST%:%PORT%    程序目录 %CD%
echo.

set "choice="
set /p choice="请输入编号（回车=退出）："
if "%choice%"=="" goto :bye

if "%choice%"=="1" goto :start
if "%choice%"=="2" goto :restart
if "%choice%"=="3" goto :stop
if "%choice%"=="4" goto :status
if "%choice%"=="5" goto :logs
if "%choice%"=="6" goto :health
if "%choice%"=="7" goto :deps
if "%choice%"=="8" goto :install
if "%choice%"=="0" goto :bye

echo [警告] 无效选项：%choice%
goto :pause

rem ==================== 1. 启动服务 ====================
:start
echo.
echo ============================================================
echo         CMCC 账号工作台 . 启动程序
echo ============================================================
call :check_python
if errorlevel 1 goto :pause
call :check_port
if errorlevel 1 goto :pause
call :check_deps
echo.
echo [信息] 启动服务 ...
echo [信息] 监听地址：%HOST%:%PORT%   (0.0.0.0 = 所有网卡可访问)
echo [信息] 本机访问：http://127.0.0.1:%PORT%
echo [信息] 局域网访问：http://本机IP:%PORT%  (手机同网段可直接打开)
echo.
%PY% cmcc_web.py --host %HOST% --port %PORT%
echo.
echo Server stopped.
goto :pause

rem ==================== 2. 重启服务 ====================
:restart
echo.
echo ============================================================
echo         CMCC 账号工作台 . 重启程序
echo ============================================================
call :stop_svc
call :check_python
if errorlevel 1 goto :pause
call :check_port
if errorlevel 1 goto :pause
echo [信息] 启动服务 ...
%PY% cmcc_web.py --host %HOST% --port %PORT%
echo.
echo Server stopped.
goto :pause

rem ==================== 3. 停止服务 ====================
:stop
echo.
echo [信息] 停止服务 ...
call :stop_svc
goto :pause

:stop_svc
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo    停止 PID %%p
  taskkill /F /PID %%p >nul 2>&1
)
exit /b 0

rem ==================== 4. 查看状态 ====================
:status
echo.
echo ============================================================
echo   CMCC 账号工作台 . 运行状态
echo ============================================================
echo --- 监听端口 ---
netstat -ano | findstr /R /C:":%PORT% .*LISTENING"
if errorlevel 1 echo   端口 %PORT% 未监听
echo.
echo --- 接口自检 ---
%PY% -c "import json,urllib.request as u;op=u.build_opener(u.ProxyHandler({}));d=json.load(op.open('http://127.0.0.1:%PORT%/api/state',timeout=5));s=d['stats'];print('   账号总数 : %%s    可用 %%s    待确认 %%s    已失效 %%s'%%(s['total'],s['ok'],s['pending'],s['invalid']))" 2>nul
if errorlevel 1 echo   [警告] 接口无响应，服务可能没启动
echo.
echo --- 账号列表 ---
%PY% -c "import json,urllib.request as u;op=u.build_opener(u.ProxyHandler({}));d=json.load(op.open('http://127.0.0.1:%PORT%/api/state',timeout=5));[print('   %%-13s %%-14s %%s'%%(a['phone'],a['name'],{'ok':'可用','pending':'待确认','invalid':'已失效'}.get(a['status'],a['status']))) for a in d['accounts']]" 2>nul
echo.
goto :pause

rem ==================== 5. 查看日志 ====================
:logs
if exist logs\service.log (
  echo （Ctrl+C 退出日志跟踪）
  powershell -NoProfile -Command "Get-Content -Path 'logs\service.log' -Tail 100 -Wait"
) else (
  echo [警告] 日志文件不存在：logs\service.log
)
goto :pause

rem ==================== 6. 健康检查 ====================
:health
echo.
echo [信息] 健康检查 http://127.0.0.1:%PORT%/api/state ...
curl -s --noproxy * --max-time 8 -o nul -w "  HTTP %%{http_code}\n" http://127.0.0.1:%PORT%/api/state
goto :pause

rem ==================== 7. 依赖说明/安装 ====================
:deps
echo.
echo ============================================================
echo         CMCC 账号工作台 . 环境依赖说明
echo ============================================================
echo.
echo 【A. 代码怎么加载依赖】
echo   入口文件 cmcc_web.py
echo     - 顶部 sys.path.insert(0, 脚本所在目录)
echo       同目录 .py 文件直接从本地加载，不走 pip：
echo       cmcc_apptoken_sim.py / cmcc_sms.py / cmcc_crypto.py
echo       builtin_templates.py / crypto_engine.py
echo     - import cmcc_apptoken_sim   [必需] 缺了整个服务起不来
echo         . Crypto.Cipher.AES (pycryptodome) [有内置纯 Python 兜底]
echo         . curl_cffi                        [有兜底：系统 curl 到 urllib]
echo     - import cmcc_sms         [可选] try/except 包裹
echo         . 缺 pycryptodome 时导入失败，只影响「短信登录」，换票不受影响
echo.
echo 【B. 依赖装到哪里】
%PY% -c "import sys;print('   解释器   :', sys.executable)"
%PY% -c "import sys;print('   前缀     :', sys.prefix)"
%PY% -c "import site;ps=[x for x in site.getsitepackages() if 'site-packages' in x];print('   安装目录 :', ps[0] if ps else '')"
echo   查看全部路径： %PY% -c "import site;print(site.getsitepackages())"
echo.
echo 【C. 依赖清单】
echo   curl_cffi      建议装   缺失时回退系统 curl 到 urllib，TLS 指纹可能被 WAF 拦截
echo   pycryptodome   建议装   缺失时加解密走内置纯 Python 兜底；短信登录不可用
echo   其余全部为 Python 标准库，无需安装。
echo.
echo 【D. 手动安装命令】
echo   %PY% -m pip install curl_cffi pycryptodome
echo   (Debian 12+ 若报 externally-managed-environment 加 --break-system-packages)
echo.
echo --- 依赖体检 ---
%PY% -c "import curl_cffi;print('   [OK] curl_cffi     ', curl_cffi.__version__)"
if errorlevel 1 echo   [警告] curl_cffi      未安装 (将用系统 curl / urllib 兜底)
%PY% -c "import Crypto;print('   [OK] pycryptodome  ', Crypto.__version__)"
if errorlevel 1 echo   [警告] pycryptodome   未安装 (加解密走内置纯 Python，短信登录不可用)
%PY% -c "import cmcc_sms" 2>nul
if errorlevel 1 echo   [警告] cmcc_sms 模块  加载失败 (短信登录不可用，换票不受影响)
if not errorlevel 1 echo   [OK] cmcc_sms 模块  加载正常 (短信登录可用)
echo.
echo --- 本地模块文件 ---
for %%f in (cmcc_web.py cmcc_web_ui.html cmcc_apptoken_sim.py cmcc_sms.py cmcc_crypto.py builtin_templates.py crypto_engine.py) do (
  if exist "%%f" (echo     [OK] %%f) else (echo     [X ] %%f ^(缺失^))
)
echo.
echo --- 数据文件 ---
for %%f in (cmcc_accounts.json app_token.json cmcc_web_store.json) do (
  if exist "%%f" (echo     [OK] %%f) else (echo     [ - ] %%f ^(首次运行自动生成^))
)
echo.
echo --- 安装缺失依赖 ---
%PY% -c "import curl_cffi" >nul 2>&1
if errorlevel 1 (
  echo [信息] 安装 curl_cffi ...
  %PY% -m pip install --quiet curl_cffi
)
%PY% -c "import Crypto" >nul 2>&1
if errorlevel 1 (
  echo [信息] 安装 pycryptodome ...
  %PY% -m pip install --quiet pycryptodome
)
goto :pause

rem ==================== 8. 部署为开机自启 ====================
:install
echo.
echo [警告] Windows 下没有 systemd。
echo        需要开机自启请用「任务计划程序」创建任务：
echo        触发器 = 计算机启动时
echo        操作   = 启动程序
echo           程序   = 你的 python.exe 完整路径
echo           参数   = "%CD%\cmcc_web.py --host %HOST% --port %PORT%"
echo.
echo 或改用 NSSM / WinSW 包装成 Windows 服务。
echo.
pause
goto :menu

rem ==================== 公共子过程 ====================
:check_python
echo [信息] 检查 Python 环境...
%PY% -V >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.8+
  exit /b 1
)
%PY% -V
echo [成功] Python 可用
exit /b 0

:check_port
echo [信息] 检查端口 %HOST%:%PORT% ...
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [警告] 端口 %PORT% 已被占用：
  netstat -ano | findstr /R /C:":%PORT% .*LISTENING"
  echo [警告] 请先停掉占用进程，或修改本脚本顶部的 PORT 变量后重试。
  exit /b 1
)
echo [成功] 端口 %PORT% 可用
exit /b 0

:check_deps
echo [信息] 检查依赖（curl_cffi / pycryptodome）...
%PY% -c "import curl_cffi" >nul 2>&1
if errorlevel 1 (
  echo [信息] 安装 curl_cffi ...
  %PY% -m pip install --quiet curl_cffi
) else (
  echo [成功] curl_cffi 已安装
)
%PY% -c "import Crypto" >nul 2>&1
if errorlevel 1 (
  echo [信息] 安装 pycryptodome ...
  %PY% -m pip install --quiet pycryptodome
) else (
  echo [成功] pycryptodome 已安装
)
exit /b 0

:pause
echo.
pause
goto :menu

:bye
echo.
echo 再见.
exit /b 0
