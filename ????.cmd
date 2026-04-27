@echo off
setlocal

set CONDA_BAT=D:\MiniConda\condabin\conda.bat
set ENV_DIR=D:\Desktop\HexInfinite\hexsolver_cn_py\.conda_env
set REQ_FILE=D:\Desktop\HexInfinite\hexsolver_cn_py\requirements.txt

if not exist "%CONDA_BAT%" (
    echo 没有找到 conda.bat：%CONDA_BAT%
    exit /b 1
)

call "%CONDA_BAT%" create -y -p "%ENV_DIR%" python=3.11
if errorlevel 1 exit /b 1

call "%CONDA_BAT%" activate "%ENV_DIR%"
if errorlevel 1 exit /b 1

python -m pip install --disable-pip-version-check -r "%REQ_FILE%"
if errorlevel 1 exit /b 1

echo.
echo 环境已经创建完成：
echo %ENV_DIR%
