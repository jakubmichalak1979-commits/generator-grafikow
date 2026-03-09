@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Przygotowanie Srodowiska ===
if not exist "venv" (
    echo [ERROR] Srodowisko wirtualne nie istnieje.
    echo Uruchamiam naprawe...
    py -m venv venv
)

echo.
echo === Instalacja/Weryfikacja bibliotek ===
.\venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo === Uruchamianie aplikacji ===
echo W przegladarce za chwile otworzy sie Generator Grafikow.
.\venv\Scripts\streamlit.exe run app.py

pause
