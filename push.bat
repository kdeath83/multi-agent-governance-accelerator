@echo off
echo =========================================
echo Git Push Script - Agent Registry
echo =========================================
echo.

REM Check if already a git repo
if not exist .git (
    echo [1/6] Initializing git repository...
    git init
) else (
    echo [1/6] Git repository already initialized
)

echo [2/6] Configuring git user...
git config user.email "krishde@gmail.com"
git config user.name "Krish"

echo [3/6] Adding all files...
git add .

echo [4/6] Committing...
git commit -m "Initial commit: Agent Registry Governance Dashboard

- FastAPI backend with aioboto3, JWT auth, rate limiting
- React frontend with Tailwind, Recharts  
- AWS CDK infrastructure (Lambda, API GW, WAF, CloudFront, DynamoDB)
- Production security hardening
- One-click deploy scripts

Built on the day OpenAI launched on AWS Bedrock."

echo [5/6] Setting up remote...
git branch -M main

REM Check if remote already exists
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo Setting remote to kdeath83/agent-registry-governance...
    git remote add origin https://github.com/kdeath83/agent-registry-governance.git
) else (
    echo Remote already configured
)

echo [6/6] Pushing to GitHub...
git push -u origin main

if errorlevel 1 (
    echo.
    echo =========================================
    echo PUSH FAILED
    echo =========================================
    echo.
    echo Common issues:
    echo 1. Repo doesn't exist on GitHub yet
    echo    - Go to https://github.com/new
    echo    - Name: agent-registry-governance
    echo    - Create, then run this script again
    echo.
    echo 2. Authentication required
    echo    - Use: git credential-manager configure
    echo    - Or set GH_TOKEN environment variable
    echo.
    echo 3. Remote URL wrong
    echo    - Fix: git remote set-url origin https://github.com/YOURNAME/repo.git
    echo.
    pause
    exit /b 1
)

echo.
echo =========================================
echo SUCCESS! Code pushed to GitHub
echo =========================================
echo.
echo https://github.com/kdeath83/agent-registry-governance
echo.
pause