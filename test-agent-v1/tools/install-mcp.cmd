@echo off
setlocal EnableDelayedExpansion
rem ===========================================================================
rem  install-mcp.cmd - register BOTH Testing-Agent MCP servers with Claude Code.
rem
rem    knowledge-gathering   (Steps 1-2: gather + refine)
rem    test-plan-definition  (Steps 3-4: define + implement)
rem
rem  Reads bearer tokens from test-agent\.env (never hard-coded / echoed),
rem  resolves each /mcp URL from `terraform output` (live source of truth),
rem  and registers each server via `claude mcp add --transport http` (idempotent).
rem
rem  Usage:
rem    install-mcp.cmd                 :: scope local (current project)
rem    install-mcp.cmd --scope user    :: available in every project
rem  Override via env: KGA_MCP_URL TPD_MCP_URL
rem                    KGA_BRIDGE_BEARER_TOKEN TPD_BRIDGE_BEARER_TOKEN
rem ===========================================================================

rem --- paths -----------------------------------------------------------------
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..")    do set "AGENT_DIR=%%~fI"
for %%I in ("%AGENT_DIR%\..")    do set "REPO_DIR=%%~fI"
set "DEPLOY_DIR=%REPO_DIR%\deployments"
set "ENV_FILE=%AGENT_DIR%\.env"

set "SCOPE=local"
if /I "%~1"=="--scope" set "SCOPE=%~2"

rem Documented fallbacks - used only if `terraform output` is unavailable.
set "KGA_MCP_URL_DEFAULT=https://knowledge-gathering-agent-q5rqhzn2uq-oa.a.run.app/mcp"
set "TPD_MCP_URL_DEFAULT=https://test-plan-definition-agent-q5rqhzn2uq-oa.a.run.app/mcp"
set "TEV_MCP_URL_DEFAULT=https://test-evaluation-agent-q5rqhzn2uq-oa.a.run.app/mcp"

rem --- preflight -------------------------------------------------------------
where claude >nul 2>&1 || (
  echo ERROR: the 'claude' CLI is not on PATH. Install Claude Code first.>&2
  exit /b 1
)

rem --- load the two bearer keys from .env (already-set env vars win) ----------
if not defined KGA_BRIDGE_BEARER_TOKEN call :read_env KGA_BRIDGE_BEARER_TOKEN
if not defined TPD_BRIDGE_BEARER_TOKEN call :read_env TPD_BRIDGE_BEARER_TOKEN

rem --- resolve URLs: env override > terraform output > documented default -----
if not defined KGA_MCP_URL call :tf_out bridge_url     KGA_MCP_URL "%KGA_MCP_URL_DEFAULT%"
if not defined TPD_MCP_URL call :tf_out tpd_bridge_url TPD_MCP_URL "%TPD_MCP_URL_DEFAULT%"
if not defined TEV_MCP_URL call :tf_out tev_bridge_url TEV_MCP_URL "%TEV_MCP_URL_DEFAULT%"

echo Registering Testing-Agent MCP servers (scope: %SCOPE%)
echo.
set "RC=0"
call :add_server knowledge-gathering  "%KGA_MCP_URL%" KGA_BRIDGE_BEARER_TOKEN
echo.
call :add_server test-plan-definition "%TPD_MCP_URL%" TPD_BRIDGE_BEARER_TOKEN
echo.
call :add_open_server test-evaluation "%TEV_MCP_URL%"

echo.
echo Done. Restart Claude Code, then verify:
echo   claude mcp get knowledge-gathering
echo   claude mcp get test-plan-definition
echo   claude mcp get test-evaluation
exit /b %RC%

rem ===========================================================================
rem  subroutines
rem ===========================================================================
:read_env
rem  %1 = key name -> sets that env var from the first matching line in .env
if not exist "%ENV_FILE%" goto :eof
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"%~1=" "%ENV_FILE%"`) do (
  set "%~1=%%B"
  goto :eof
)
goto :eof

:tf_out
rem  %1 = terraform output name   %2 = target var   %3 = fallback URL
set "%~2=%~3"
where terraform >nul 2>&1 || goto :eof
if not exist "%DEPLOY_DIR%" goto :eof
for /f "usebackq delims=" %%U in (`terraform -chdir^="%DEPLOY_DIR%" output -raw %~1 2^>nul`) do set "%~2=%%U"
goto :eof

:add_server
rem  %1 = server name   %2 = url   %3 = name of the token env var
set "NAME=%~1"
set "URL=%~2"
call set "TOKEN=%%%~3%%"
if not defined TOKEN (
  echo SKIP  %NAME% - no bearer token ^(set in %ENV_FILE% or export %~3^).>&2
  set "RC=1"
  goto :eof
)
echo ==^> %NAME%
echo     url:   %URL%
echo     token: [%~3 present, hidden]
call claude mcp remove "%NAME%" -s "%SCOPE%" >nul 2>&1
call claude mcp add --transport http "%NAME%" "%URL%" --scope "%SCOPE%" --header "Authorization: Bearer %TOKEN%"
if errorlevel 1 set "RC=1"
goto :eof

:add_open_server
rem  %1 = server name   %2 = url   (no bearer - app-ungated, nonprod read-only scorer)
set "NAME=%~1"
set "URL=%~2"
echo ==^> %NAME% ^(no app bearer^)
echo     url:   %URL%
call claude mcp remove "%NAME%" -s "%SCOPE%" >nul 2>&1
call claude mcp add --transport http "%NAME%" "%URL%" --scope "%SCOPE%"
if errorlevel 1 set "RC=1"
goto :eof
