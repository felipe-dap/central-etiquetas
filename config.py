"""Per-computer configuration; environment variables override the local .env."""
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent
load_dotenv(HERE/'.env')

def configured_path(name,default):
    path=Path(os.path.expandvars(os.environ.get(name) or str(default))).expanduser()
    return (HERE/path).resolve() if not path.is_absolute() else path

DEFAULT_FOLDER=configured_path('ETIQUETAS_INPUT_DIR',Path.home()/'Desktop'/'Impressões')
DATA_DIR=configured_path('ETIQUETAS_DATA_DIR',Path(os.environ.get('LOCALAPPDATA',Path.home()))/'DearFriends'/'CentralEtiquetas')
SETTINGS=DATA_DIR/'preferencias.json'
DEFAULT_PRINTER=os.environ.get('ETIQUETAS_PRINTER') or 'ZDesigner ZD220-203dpi ZPL'
PYTHON=configured_path('ETIQUETAS_PYTHON',sys.executable)
if PYTHON.name.lower()=='pythonw.exe':PYTHON=PYTHON.with_name('python.exe')
