@echo off
setlocal EnableDelayedExpansion
rem ===========================================================================
rem  install-mcp.cmd - register the SINGLE v2 MCP gateway with Claude Code.
rem
rem  The gateway (mcp-gateway-v2) fronts all three agents over A2A, so Claude connects to ONE
rem  endpoint that exposes every tool. Reads GATEWAY_BEARER_TOKEN from ..\..\test-agent-v2\.env,
rem  resolves the /mcp URL from `terraform output gateway_url`, and registers it (idempotent).
rem
rem  Usage:
rem    install-mcp.cmd                 :: scope local (current project)
rem    install-mcp.cmd --scope user    :: available in every project
rem  Override via env: GATEWAY_MCP_URL  GATEWAY_BEARER_TOKEN
rem ===========================================================================

set "TF_DIR=%~dp0"
for %%I in ("%TF_DIR%..\..") do set "REPO_DIR=%%~fI"
set "ENV_FILE=%REPO_DIR%\test-agent-v2\.env"
set "NAME=testing-agent"

set "SCOPE=local"
if /I "%~1"=="--scope" set "SCOPE=%~2"

where claude >nul 2>&1 || (
  echo ERROR: the 'claude' CLI is not on PATH. Install Claude Code first.>&2
  exit /b 1
)

if not defined GATEWAY_BEARER_TOKEN call :read_env GATEWAY_BEARER_TOKEN
if not defined GATEWAY_MCP_URL call :tf_out gateway_url GATEWAY_MCP_URL

if "%GATEWAY_MCP_URL%"=="" goto :no_url
if "%GATEWAY_MCP_URL%"=="null" goto :no_url

echo ==^> %NAME% ^(single MCP gateway; fronts the 3 A2A agents^)
echo     url:   %GATEWAY_MCP_URL%
call claude mcp remove "%NAME%" -s "%SCOPE%" >nul 2>&1
if defined GATEWAY_BEARER_TOKEN (
  echo     token: [GATEWAY_BEARER_TOKEN present, hidden]
  call claude mcp add --transport http "%NAME%" "%GATEWAY_MCP_URL%" --scope "%SCOPE%" --header "Authorization: Bearer %GATEWAY_BEARER_TOKEN%"
) else (
  echo     ^(no bearer token set - the gateway is open^)
  call claude mcp add --transport http "%NAME%" "%GATEWAY_MCP_URL%" --scope "%SCOPE%"
)
echo.
echo Done. Restart Claude Code, then verify:  claude mcp get %NAME%
exit /b %ERRORLEVEL%

:no_url
echo ERROR: no gateway URL - deploy first ^(deploy.sh^) or set GATEWAY_MCP_URL.>&2
exit /b 1

rem ===========================================================================
:read_env
if not exist "%ENV_FILE%" goto :eof
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"%~1=" "%ENV_FILE%"`) do (
  set "%~1=%%B"
  goto :eof
)
goto :eof

:tf_out
set "%~2="
where terraform >nul 2>&1 || goto :eof
for /f "usebackq delims=" %%U in (`terraform -chdir^="%TF_DIR%." output -raw %~1 2^>nul`) do set "%~2=%%U"
goto :eof
