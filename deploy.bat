@echo off
echo =========================================
echo Agent Registry Governance - AWS Deploy
echo =========================================
echo.

REM Check for JWT secret
if "%JWT_SECRET_KEY%"=="" (
    echo ERROR: JWT_SECRET_KEY environment variable not set!
    echo Generate one with: node -e "console.log(require('crypto').randomBytes(64).toString('hex'))"
    echo Then run: set JWT_SECRET_KEY=your-generated-key
    exit /b 1
)

cd infrastructure\cdk

echo [1/5] Setting up Python environment...
python -m venv venv
venv\Scripts\activate

echo [2/5] Installing dependencies...
pip install -r requirements.txt -q

echo [3/5] Bootstrapping CDK...
cdk bootstrap

echo [4/5] Deploying infrastructure...
cdk deploy --require-approval never

echo [5/5] Building frontend...
cd ..\..\frontend
call npm install
call npm run build

echo [6/6] Deploying frontend to S3...
for /f "tokens=*" %%a in ('aws cloudformation describe-stacks --stack-name AgentRegistryGovernanceStack --query "Stacks[0].Outputs[?OutputKey=='WebsiteBucket'].OutputValue" --output text') do set BUCKET=%%a
aws s3 sync dist s3://%BUCKET% --delete

echo.
echo =========================================
echo DEPLOYMENT COMPLETE!
echo =========================================
echo.
for /f "tokens=*" %%a in ('aws cloudformation describe-stacks --stack-name AgentRegistryGovernanceStack --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text') do echo Frontend URL: %%a
for /f "tokens=*" %%a in ('aws cloudformation describe-stacks --stack-name AgentRegistryGovernanceStack --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text') do echo API URL: %%a
echo.
pause