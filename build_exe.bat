@echo off
setlocal

echo Weryfikacja instalacji Python i aktywacja srodowiska...
call venv\Scripts\activate.bat

echo Instalowanie narzedzia PyInstaller...
pip install pyinstaller

echo.
echo ==========================================================
echo Rozpoczynam budowanie ukrytej paczki z grafikiem (.exe)
echo PROSZE CZEKAC... Proces ten moze potrwac nawet kilka minut!
echo Nic sie nie zawiesilo - po prostu uzyciem duzo plikow.
echo ==========================================================
pyinstaller --noconfirm --onedir --console ^
  --name "GeneratorGrafikow" ^
  --add-data "app.py;." ^
  --add-data "db.py;." ^
  --add-data "scheduler.py;." ^
  --add-data "exporter.py;." ^
  --collect-data streamlit ^
  --copy-metadata streamlit ^
  --hidden-import sqlite3 ^
  --hidden-import pandas ^
  --hidden-import openpyxl ^
  --hidden-import ortools ^
  --hidden-import sqlalchemy ^
  --hidden-import holidays ^
  --hidden-import reportlab ^
  run_app.py

echo.
echo === ZAKONCZONO KOMPILACJE ===
echo.
echo Pomyslnie zbudowano aplikacje przenosna!
echo ----------------------------------------------------
echo Zobaczysz teraz dwa nowe foldery 'build' i 'dist'.
echo 
echo KROK 1: Wejdz do folderu 'dist'.
echo KROK 2: W srodku znajdziesz folder 'GeneratorGrafikow'.
echo KROK 3: Skopiuj ten CAŁY folder z zawartoscia np. na Pendrive.
echo KROK 4: Na dowolnym innym komputerze z systemem Windows przejdz do
echo        skopiowanego folderu i uruchom plik 'GeneratorGrafikow.exe'.
echo.
echo Mozesz juz zamknac to okno.
pause
