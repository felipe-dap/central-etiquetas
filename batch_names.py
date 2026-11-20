"""Readable batch directories in the user's Sao Paulo timezone."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SAO_PAULO=ZoneInfo('America/Sao_Paulo')

def create_batch(work,now=None):
    work=Path(work)
    instant=now or datetime.now(SAO_PAULO)
    if instant.tzinfo is None:instant=instant.replace(tzinfo=SAO_PAULO)
    base=instant.astimezone(SAO_PAULO).strftime('%Y-%m-%d-%Hh%Mm%Ss')
    sequence=1
    while True:
        name=base if sequence==1 else f'{base}-{sequence:02d}'
        batch=work/name
        try:
            batch.mkdir()
            return batch
        except FileExistsError:
            sequence+=1
