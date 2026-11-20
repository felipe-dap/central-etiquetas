from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from batch_names import create_batch

class BatchNameTests(unittest.TestCase):
    def test_requested_format(self):
        with TemporaryDirectory() as temp:
            path=create_batch(temp,datetime(2026,11,17,17,46,27))
            self.assertEqual(path.name,'2026-11-17-17h46m27s')
            self.assertTrue(path.is_dir())

    def test_uses_sao_paulo_time(self):
        with TemporaryDirectory() as temp:
            path=create_batch(temp,datetime(2026,11,17,20,46,27,tzinfo=timezone.utc))
            self.assertEqual(path.name,'2026-11-17-17h46m27s')

    def test_simultaneous_batches_never_share_a_directory(self):
        with TemporaryDirectory() as temp:
            fixed=datetime(2026,11,17,17,46,27)
            with ThreadPoolExecutor(max_workers=5) as pool:
                paths=list(pool.map(lambda _:create_batch(temp,fixed),range(5)))
            self.assertEqual(len(set(paths)),5)
            self.assertEqual({p.name for p in paths},{'2026-11-17-17h46m27s',*{f'2026-11-17-17h46m27s-{i:02d}' for i in range(2,6)}})
            self.assertEqual(len(list(Path(temp).iterdir())),5)

if __name__=='__main__':unittest.main()
