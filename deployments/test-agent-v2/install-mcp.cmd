@echo off
setlocal EnableDelayedExpansion
rem ===========================================================================
rem  install-mcp.cmd - register the v2 (ADK) Testing-Agent MCP servers with Claude Code.
rem
rem    knowledge-gathering   (Steps 1-2: gather + refine)
rem    test-plan-definition  (Steps 3-4: define + implement)
rem    test-evaluation       (Step 5: pack/plan scorer - app-ungated)
rem
rem  "Deployed only": points Claude Code at the DEPLOYED Cloud Run bridge URLs. Run deploy.sh
rem  first - the /mcp URLs come from `terraform output` in THIS directory. ADK has no native
rem  MCP server, so the A2A->MCP bridge is Claude Code's native channel to the agents.
rem
rem  Reads bearer tokens from ..\..\test-agent-v2\.env (never hard-coded / echoed).
rem
rem  Usage:
rem    install-mcp.cmd                 :: scope local (current project)
rem    install-mcp.cmd --scope user    :: available in every project
rem  Override via env: KGA_MCP_URL TPD_MCP_URL TEV_MCP_URL
rem                    KGA_BRIDGE_BEARER_TOKEN TPD_BRIDGE_BEARER_TOKEN
rem ===========================================================================

rem --- paths -----------------------------------------------------------------
rem  The script lives IN the terraform dir (deployments\test-agent-v2).
set "TF_DIR=%~dp0"
for %%I in ("%TF_DIR%..\..") do set "REPO_DIR=%%~fI"
set "ENV_FILE=%REPO_DIR%\test-agent-v2\.env"

set "SCOPE=local"
if /I "%~1"=="--scope" set "SCOPE=%~2"

rem --- preflight -------------------------------------------------------------
where claude >nul 2>&1 || (
  echo ERROR: the 'claude' CLI is not on PATH. Install Claude Code first.>&2
  exit /b 1
)

rem --- load the two bearer keys from .env (already-set env vars win) ----------
if not defined KGA_BRIDGE_BEARER_TOKEN call :read_env KGA_BRIDGE_BEARER_TOKEN
if not defined TPD_BRIDGE_BEARER_TOKEN call :read_env TPD_BRIDGE_BEARER_TOKEN

rem --- resolve URLs: env override > terraform output (no hard-coded fallback) -
if not defined KGA_MCP_URL call :tf_out bridge_url     KGA_MCP_URL
if not defined TPD_MCP_URL call :tf_out tpd_bridge_url TPD_MCP_URL
if not defined TEV_MCP_URL call :tf_out tev_bridge_url TEV_MCP_URL

echo Registering v2 Testing-Agent MCP servers (scope: %SCOPE%)
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
rem  %1 = terraform output name   %2 = target var
set "%~2="
where terraform >nul 2>&1 || goto :eof
for /f "usebackq delims=" %%U in (`terraform -chdir^="%TF_DIR%." output -raw %~1 2^>nul`) do set "%~2=%%U"
goto :eof

:add_server
rem  %1 = server name   %2 = url   %3 = name of the token env var
set "NAME=%~1"
set "URL=%~2"
call set "TOKEN=%%%~3%%"
if "%URL%"=="" (
  echo ERROR: no URL for %NAME% - deploy first ^(deploy.sh^) or set the *_MCP_URL env var.>&2
  set "RC=1"
  goto :eof
)
if "%URL%"=="null" (
  echo ERROR: no URL for %NAME% - deploy first ^(deploy.sh^) or set the *_MCP_URL env var.>&2
  set "RC=1"
  goto :eof
)
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
if "%URL%"=="" (
  echo ERROR: no URL for %NAME% - deploy first ^(deploy.sh^) or set TEV_MCP_URL.>&2
  set "RC=1"
  goto :eof
)
if "%URL%"=="null" (
  echo ERROR: no URL for %NAME% - deploy first ^(deploy.sh^) or set TEV_MCP_URL.>&2
  set "RC=1"
  goto :eof
)
echo ==^> %NAME% ^(no app bearer^)
echo     url:   %URL%
call claude mcp remove "%NAME%" -s "%SCOPE%" >nul 2>&1
call claude mcp add --transport http "%NAME%" "%URL%" --scope "%SCOPE%"
if errorlevel 1 set "RC=1"
goto :eof
