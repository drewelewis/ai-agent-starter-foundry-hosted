@echo off
REM Push AI Agent Starter Docker image to Docker Hub
if "%DOCKER_REPO_NAME%"=="" (
    echo Set DOCKER_REPO_NAME to your own Docker Hub repository before pushing.
    exit /b 1
)
echo 🚀 Pushing AI Agent Starter to Docker Hub...
echo.

REM Check if logged into Docker Hub
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker is not running!
    exit /b 1
)

REM Optional: Tag with version
set /p version="Enter version tag (or press Enter for 'latest'): "
if "%version%"=="" set version=latest

if not "%version%"=="latest" (
    echo Tagging image with version: %version%
    docker tag %DOCKER_REPO_NAME%:latest %DOCKER_REPO_NAME%:%version%
)

echo Pushing %DOCKER_REPO_NAME%:latest...
docker push %DOCKER_REPO_NAME%:latest

if %errorlevel% neq 0 (
    echo ❌ Docker push failed!
    echo Make sure you're logged in with: docker login
    exit /b 1
)

if not "%version%"=="latest" (
    echo Pushing %DOCKER_REPO_NAME%:%version%...
    docker push %DOCKER_REPO_NAME%:%version%
)

echo.
echo ✅ Successfully pushed to Docker Hub!
echo 📦 Image: %DOCKER_REPO_NAME%:latest
if not "%version%"=="latest" echo 📦 Image: %DOCKER_REPO_NAME%:%version%
echo.
echo 💡 Pull with: docker pull %DOCKER_REPO_NAME%:latest
