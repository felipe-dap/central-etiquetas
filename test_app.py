import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from app import read_history,ready_to_print

class AppModelTests(unittest.TestCase):
    def test_print_button_only_accepts_clean_unsubmitted_preview(self):
        data=dict(state='preview',pages=[{}],issues=[],unmatched=[])
        self.assertTrue(ready_to_print(data))
        for change in [dict(state='sent'),dict(issues=['revisar']),dict(unmatched=[{}]),dict(pages=[]),dict(reprint_of='old')]:
            self.assertFalse(ready_to_print(dict(data,**change)))
        self.assertFalse(ready_to_print(None))

    def test_history_skips_broken_records(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)/'_processamento'
            good=root/'good';good.mkdir(parents=True)
            (good/'manifest.json').write_text(json.dumps(dict(state='preview')),encoding='utf-8')
            bad=root/'bad';bad.mkdir()
            (bad/'manifest.json').write_text('{',encoding='utf-8')
            history=read_history(temp)
            self.assertEqual(len(history),1)
            self.assertEqual(history[0][0],good)

if __name__=='__main__':unittest.main()
