import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

class ConfigTests(unittest.TestCase):
    def test_environment_overrides_local_defaults_and_worker_uses_current_python(self):
        with TemporaryDirectory() as temp:
            env=dict(os.environ,ETIQUETAS_INPUT_DIR=str(Path(temp)/'entrada'),ETIQUETAS_DATA_DIR=str(Path(temp)/'dados'),ETIQUETAS_PRINTER='Zebra teste',ETIQUETAS_PYTHON=sys.executable)
            code='import config,json;print(json.dumps([str(config.DEFAULT_FOLDER),str(config.SETTINGS),config.DEFAULT_PRINTER,str(config.PYTHON)]))'
            result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,env=env,capture_output=True,text=True,check=True)
            folder,settings,printer,python=json.loads(result.stdout)
            self.assertEqual(Path(folder),Path(temp)/'entrada')
            self.assertEqual(Path(settings),Path(temp)/'dados'/'preferencias.json')
            self.assertEqual(printer,'Zebra teste')
            self.assertEqual(Path(python),Path(sys.executable))
