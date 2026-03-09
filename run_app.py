import os
import sys

# Jawne importy wszystkich używanych modułów, aby PyInstaller zorientował się w ich obecności
import sqlite3
import pandas
import openpyxl
import ortools
import streamlit
import sqlalchemy
import holidays

import app
import db
import scheduler
import exporter

import streamlit.web.cli as stcli

if __name__ == '__main__':
    # Pobieramy ścieżkę do folderu, w którym znajduje się skompilowany plik
    if getattr(sys, 'frozen', False):
        bundle_dir = sys._MEIPASS
    else:
        bundle_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Ustawiamy katalog roboczy z powrotem na folder aplikacji,
    # aby Streamlit mógł zlokalizować app.py oraz by baza SQLite tworzyła się w odpowiednim miejscu.
    os.chdir(bundle_dir)
    
    sys.argv = [
        "streamlit",
        "run",
        "app.py",
        "--server.headless=false",
        "--server.port=8501",
        "--browser.gatherUsageStats=false",
    ]
    sys.exit(stcli.main())
