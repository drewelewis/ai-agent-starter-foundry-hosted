@echo off
REM Build Docker image for AI Agent Starter
echo 🐳 Building AI Agent Starter Docker image...
echo.

if "%DOCKER_REPO_NAME%"=="" set DOCKER_REPO_NAME=math-tutor-api
docker build --platform linux/amd64 -t %DOCKER_REPO_NAME%:latest -f dockerfile .

if %errorlevel% neq 0 (
    echo ❌ Docker build failed!
    exit /b 1
)

echo.
echo ✅ Build completed!
echo 📦 Image: %DOCKER_REPO_NAME%:latest
echo.
echo 💡 Next steps:
echo    - Run: docker-compose up -d
echo    - Or: _up.bat
echo    - Push to Docker Hub: docker push %DOCKER_REPO_NAME%:latest
