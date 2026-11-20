"""PDFs Olist: OCR local, pareamento conservador e impressao ZPL 100x150 mm."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import unicodedata
from datetime import datetime
from document_data import dispatch_metadata,ecommerce_order,order_footer_ocr
from batch_names import create_batch
from config import DEFAULT_FOLDER,DEFAULT_PRINTER

def normal(s):
    return ' '.join(re.sub(r'[^A-Z0-9 ]', '', unicodedata.normalize('NFKD', s.upper()).encode('ascii', 'ignore').decode()).split())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)

def address_blocks(lines):
    """Keep fiscal recipient and delivery identity separate, including their CEPs."""
    headings = []
    for i, line in enumerate(lines):
        label = normal(line)
        if re.fullmatch(r'(?:INFORMACOES D[OA] )?LOCAL DE ENTREGA', label):
            headings.append((i, 'delivery'))
        elif re.fullmatch(r'DESTINATARIO(?:\s+REMETENTE)?', label):
            headings.append((i, 'fiscal'))
        elif re.match(r'^(?:EMITENTE|REMETENTE|TRANSPORTADOR|DADOS D[OA]S? PRODUTO|CALCULO DO IMPOSTO|DADOS ADICIONAIS|INFORMACOES COMPLEMENTARES|TOTAL)(?: |$)', label):
            headings.append((i, 'end'))
    blocks = {}
    ignored = {'CORREIOS','LOGGI','JADLOG','MELHOR ENVIO','NOME RAZAO SOCIAL','NOME','RAZAO SOCIAL'}
    for pos, (start, kind) in enumerate(headings):
        if kind == 'end':
            continue
        end = headings[pos+1][0] if pos+1 < len(headings) else len(lines)
        section = lines[start+1:end]
        candidates = [s for s in section if normal(s) not in ignored and
                      not re.fullmatch(r'NF(?:E)?\s*\d+', normal(s))]
        name = re.split(r',?\s*Tel(?:efone)?\s*:', candidates[0], flags=re.I)[0].strip() if candidates else ''
        # A heading with no usable name must be reviewed, never substituted with fiscal identity.
        if name and (re.match(r'^(?:CPF|CNPJ|CEP|ENDERECO|BAIRRO)\b', normal(name)) or re.search(r'\d', name)):
            name = ''
        ceps = re.findall(r'\b\d{2}[.]?\d{3}(?:-\s*| )?\d{3}\b', '\n'.join(section))
        blocks[kind] = dict(name=name, cep=re.sub(r'\D', '', ceps[0]) if ceps else '')
    return blocks

def identify(lines):
    """lines: OCR texts in reading order. Never fuzzy-match customers."""
    text = '\n'.join(lines)
    folded = unicodedata.normalize('NFKD', text.upper()).encode('ascii', 'ignore').decode()
    # Olist shipping labels embed a small DANFE below the address. The volumes
    # and sender/recipient blocks identify the whole page as a shipping label.
    shipping_olist = ('OLIST' in folded and 'VOLUMES' in folded and
                      any(normal(s) == 'REMETENTE' for s in lines))
    kind = ('envio' if shipping_olist else
            'nf' if 'DANFE' in folded and 'SIMPLIFICADO' in folded else
            'envio' if any(s in folded for s in ('CORREIOS','LOGGI','JADLOG','MELHOR','ENVIO','SEDEX','PAC ')) else 'desconhecido')
    blocks = address_blocks(lines)
    source = 'delivery' if kind == 'nf' and 'delivery' in blocks else 'fiscal'
    selected = blocks.get(source, {})
    name = selected.get('name', '')
    # Tracking labels may have only DESTINATARIO above their address.
    match = re.search(r'(?:\bNF(?:-?E)?\s*[:#]?|\bNUMERO\s*[:#]?)\s*([0-9][0-9.]{2,12})', folded)
    nf = str(int(re.sub(r'\D', '', match[1]))) if match else ''
    # A 44-digit NFe key contains a 9-digit invoice number at positions 25..33.
    keys = re.findall(r'(?<!\d)(?:\d[ .]*){44}(?!\d)', folded)
    keys = [re.sub(r'\D', '', k) for k in keys]
    if keys:
        key_nf = str(int(keys[0][25:34]))
        if nf and nf != key_nf:
            raise ValueError('Numero da NF diverge da chave de acesso')
        nf = key_nf
    layout='simplificado' if kind == 'nf' and 'ETIQUETA' not in folded else 'etiqueta'
    return dict(kind=kind, name=name, nf=nf, cep=selected.get('cep', ''),
                name_source=source, fiscal_name=blocks.get('fiscal', {}).get('name', ''),
                delivery_name=blocks.get('delivery', {}).get('name', ''),
                layout=layout,**dispatch_metadata(lines,kind,layout))

def arrange(pages):
    nfs = [p for p in pages if p['kind'] == 'nf']
    envios = [p for p in pages if p['kind'] == 'envio']
    groups = {p['uid']: [p] for p in nfs}
    issues = []
    for p in pages:
        if p['kind'] == 'desconhecido':
            issues.append(f"Layout desconhecido: {p['file']} pagina {p['page']+1}")
        if not p['name']:
            issues.append(f"Nome nao identificado: {p['file']} pagina {p['page']+1}")
    for e in envios:
        candidates = [p for p in nfs if e['nf'] and p['nf'] == e['nf']]
        reason = 'numero_nf'
        if not candidates and not e['nf']:
            candidates = [p for p in nfs if e['cep'] and e['cep'] == p['cep'] and normal(e['name']) == normal(p['name'])]
            reason = 'nome_e_cep'
        if len(candidates) == 1:
            n = candidates[0]
            # n['name'] is the delivery name when the NF contains that block.
            if normal(n['name']) != normal(e['name']):
                issues.append(f"Nomes divergentes na NF {e['nf']}: {n['name']} / {e['name']}")
                continue
            e['match'] = reason
            groups[n['uid']].append(e)
        else:
            issues.append(f"Envio sem NF unica: {e['name']} / NF {e['nf'] or '?'}")
    # Duplicate invoice numbers and repeated shipping pages require review.
    seen = set()
    for p in nfs:
        if not p['nf'] or p['nf'] in seen:
            issues.append(f"NF ausente ou duplicada: {p['nf']} ({p['name']})")
        seen.add(p['nf'])
    ordered = []
    for n in sorted(nfs, key=lambda p: (normal(p['name']), p['nf'])):
        ordered.extend(groups[n['uid']])
    matched = {p['uid'] for p in ordered}
    unmatched = sorted([p for p in pages if p['uid'] not in matched], key=lambda p: normal(p['name']))
    return ordered, unmatched, issues

def scan(files, work):
    import pypdfium2 as pdfium
    from pypdf import PdfReader
    from rapidocr import RapidOCR
    engine = None
    pages = []
    seen_pages = set()
    for file in files:
        sha = digest(file)
        cache = work / 'ocr' / (sha + '.json')
        reader = PdfReader(file)
        cached = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else None
        doc = pdfium.PdfDocument(str(file))
        result = []
        for i, page in enumerate(reader.pages):
            w, h = float(page.mediabox.width)*25.4/72, float(page.mediabox.height)*25.4/72
            if page.rotation or abs(w-100)>1 or abs(h-150)>1:
                raise ValueError(f'{file.name}, pagina {i+1}: esperado 100x150 mm retrato, recebido {w:.2f}x{h:.2f}, rotacao {page.rotation}')
            if cached is not None:
                lines = cached[i]['lines']
                scores = cached[i]['scores']
            else:
                print(f'OCR: {file.name}, pagina {i+1}', flush=True)
                if engine is None:
                    engine = RapidOCR()
                bitmap = doc[i].render(scale=3)
                ocr = engine(bitmap.to_pil())
                if ocr.txts is None:
                    raise ValueError('OCR nao encontrou texto')
                lines = list(ocr.txts)
                scores = [float(x) for x in ocr.scores]
                bitmap.close()
            record=dict(cached[i]) if cached is not None else dict(lines=lines,scores=scores)
            result.append(record)
            fingerprint = hashlib.sha256('\n'.join(normal(s) for s in lines).encode()).hexdigest()
            if fingerprint in seen_pages:
                raise ValueError(f'Pagina repetida detectada: {file.name}, pagina {i+1}')
            seen_pages.add(fingerprint)
            info = identify(lines)
            if info['kind']=='nf' and not info.get('ecommerce_order'):
                if not record.get('order_ocr_attempted'):
                    pdf_page=doc[i]
                    try:record['order_ocr_lines'],engine=order_footer_ocr(pdf_page,engine)
                    finally:pdf_page.close()
                    record['order_ocr_attempted']=True
                info['ecommerce_order']=ecommerce_order(lines+record.get('order_ocr_lines',[]))
            if info['name']:
                ix = next((j for j,s in enumerate(lines) if info['name'] in s), -1)
                if ix >= 0 and scores[ix] < .90:
                    raise ValueError(f'Nome com baixa confianca: {file.name}, pagina {i+1}')
            pages.append(dict(**info, file=str(file), page=i, sha256=sha, uid=f'{sha}:{i}'))
        if cached is None or result!=cached:save(cache, result)
        doc.close()
    return pages

def write_pdf(pages, target):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    readers = {}
    for p in pages:
        if p['file'] not in readers:
            readers[p['file']] = PdfReader(p['file'])
        writer.add_page(readers[p['file']].pages[p['page']])
    writer.write(target)
    check = PdfReader(target)
    assert len(check.pages) == len(pages)
    for output, source in zip(check.pages, pages):
        original = readers[source['file']].pages[source['page']]
        assert output.get_contents().get_data() == original.get_contents().get_data()

def bitmap_zpl(bits, width=800, height=1200):
    """Split graphic fields below ZPL ^GF's 99,999-byte parameter limit."""
    stride = (width + 7)//8
    if len(bits) != stride*height:
        raise ValueError('Tamanho do bitmap inconsistente')
    rows_per_band = min(600, 99999//stride)
    fields = [f'^XA^PW{width}^LL{height}^LH0,0']
    for y in range(0,height,rows_per_band):
        band=bits[y*stride:min(y+rows_per_band,height)*stride]
        fields.append(f'^FO0,{y}^GFA,{len(band)},{len(band)},{stride},{band.hex().upper()}^FS')
    fields.append('^PQ1^XZ\n')
    return ''.join(fields).encode('ascii')

def zpl_pages(pdf):
    """Render locally at native ZD220 resolution; never transmit PDFs to cloud."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageOps
    import zxingcpp
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for page in doc:
            bitmap = page.render(scale=203.2/72)
            image = bitmap.to_pil().convert('L')
            image = ImageOps.contain(image, (800, 1200), Image.Resampling.LANCZOS)
            canvas = Image.new('L', (800, 1200), 255)
            canvas.paste(image, ((800-image.width)//2, (1200-image.height)//2))
            # ZPL uses 1 for black; threshold avoids dithering barcode edges.
            bits = canvas.point(lambda v: 255 if v < 128 else 0).convert('1', dither=Image.Dither.NONE).tobytes()
            reconstructed = ImageOps.invert(Image.frombytes('1',(800,1200),bits).convert('L'))
            if not zxingcpp.read_barcodes(reconstructed):
                raise ValueError('Codigo de barras nao decodificavel no raster de impressao; lote nao enviado')
            yield bitmap_zpl(bits)
            bitmap.close()
            page.close()
    finally:
        doc.close()

def wait_for_spool(handle, job, timeout=120):
    """Spool completion is NOT proof of physical output; record that distinction."""
    import win32print
    deadline = time.monotonic() + timeout
    faults = (win32print.JOB_STATUS_ERROR | win32print.JOB_STATUS_OFFLINE |
              win32print.JOB_STATUS_PAPEROUT | win32print.JOB_STATUS_BLOCKED_DEVQ |
              win32print.JOB_STATUS_DELETING | win32print.JOB_STATUS_DELETED)
    while time.monotonic() < deadline:
        jobs = win32print.EnumJobs(handle, 0, 9999, 1)
        current = next((j for j in jobs if j['JobId'] == job), None)
        if current is None:
            # Windows commonly removes completed jobs immediately. Cancellation
            # outside this process cannot always be distinguished from delivery.
            return 'removed_from_queue'
        if current['Status'] & faults:
            raise ValueError(f"Trabalho {job} com erro na fila; originais preservados")
        if current['Status'] & (win32print.JOB_STATUS_PRINTED | win32print.JOB_STATUS_COMPLETE):
            return 'spooler_completed'
        time.sleep(1)
    raise TimeoutError(f'Trabalho {job} ainda na fila. Nao reenvie: confira o lote e a impressora.')

def submit(batch, manifest, printer):
    import win32print
    # Prepared payload exists before opening the spool job.
    payload = batch/'impressao.zpl'
    with payload.open('wb') as stream:
        for chunk in zpl_pages(batch/'ordenado.pdf'):
            stream.write(chunk)
    handle = win32print.OpenPrinter(printer)
    try:
        details = win32print.GetPrinter(handle, 2)
        if 'ZD220' not in details['pDriverName'] or 'ZPL' not in details['pDriverName']:
            raise ValueError('Este backend exige Zebra ZD220 ZPL 203 dpi')
        if details['Status'] & (win32print.PRINTER_STATUS_PAUSED | win32print.PRINTER_STATUS_OFFLINE):
            raise ValueError('Impressora pausada/offline. Nada foi enviado nem movido.')
        if (manifest.get('reprint_of') or manifest.get('reviewed_preview')) and win32print.EnumJobs(handle, 0, 9999, 1):
            raise ValueError('A fila precisa estar vazia antes de reimprimir. Nada foi enviado.')
        # Persist BEFORE submission: a crash cannot silently cause an automatic retry.
        manifest['state'] = 'submitting'
        manifest['printer'] = printer
        save(batch/'manifest.json', manifest)
        job = win32print.StartDocPrinter(handle, 1, (f'Etiquetas {batch.name}', None, 'RAW'))
        manifest['job_id'] = job
        save(batch/'manifest.json', manifest)
        try:
            with payload.open('rb') as stream:
                while chunk := stream.read(65536):
                    if win32print.WritePrinter(handle, chunk) != len(chunk):
                        raise IOError('Envio parcial ao spool')
            win32print.EndDocPrinter(handle)
        except BaseException:
            manifest['state'] = 'uncertain'
            save(batch/'manifest.json', manifest)
            raise
        manifest['state'] = 'sent'
        save(batch/'manifest.json', manifest)
        print(f'Trabalho {job} enviado; aguardando conclusao da fila...', flush=True)
        manifest['spool_result'] = wait_for_spool(handle, job)
        manifest['physical_output_verified'] = False
        save(batch/'manifest.json', manifest)
        if manifest['spool_result']=='removed_from_queue':
            print('O trabalho saiu da fila sem confirmacao explicita do driver. Confira a saida fisica e use Confirmar impresso no historico. Originais preservados.',flush=True)
            return
        if manifest.get('already_archived'):
            manifest['state'] = 'completed'
            save(batch/'manifest.json', manifest)
            print('Reimpressao concluida na fila. Originais mantidos no arquivo anterior.')
        else:
            archive(batch)
    finally:
        win32print.ClosePrinter(handle)

def archive(batch):
    manifest = json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    if manifest['state'] not in ('sent', 'archiving'):
        raise ValueError('Lote nao esta aguardando confirmacao de impressao')
    if not manifest.get('archive_plan') and manifest.get('pages'):
        from approval import stage_existing_pairs
        manifest=stage_existing_pairs(batch,manifest)
    if manifest.get('archive_plan'):
        from approval import archive_pairs
        archive_pairs(batch,manifest)
        return
    destination = Path(manifest['folder'])/'impressos'/batch.name
    destination.mkdir(parents=True, exist_ok=True)
    # Validate the whole transaction before moving anything.
    for source, sha in manifest['files'].items():
        src = Path(source)
        dest = destination/src.name
        if src.exists():
            if digest(src) != sha or dest.exists():
                raise ValueError(f'Arquivo alterado ou destino ja existe: {src.name}')
        elif not dest.exists() or digest(dest) != sha:
            raise ValueError(f'Arquivo nao localizado: {src.name}')
    manifest['state'] = 'archiving'
    save(batch/'manifest.json', manifest)
    for source in manifest['files']:
        src = Path(source)
        if src.exists():
            shutil.move(str(src), destination/src.name)
    manifest['state'] = 'archived'
    save(batch/'manifest.json', manifest)
    print(f'Arquivados em {destination}')

def reprint_batch(source, work, printer):
    """Explicit retry creates a new journal; never reset/delete the previous one."""
    import win32print
    source = source.resolve()
    if source.parent != work.resolve():
        raise ValueError('Selecione uma pasta de lote dentro de _processamento.')
    previous = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if previous.get('state')=='archiving':
        raise ValueError('Arquivamento incompleto: use Confirmar impresso para conclui-lo antes de reimprimir.')
    if previous.get('issues') or previous.get('unmatched') or not previous.get('pages'):
        raise ValueError('Lote com pendencias ou vazio: gere uma previa corrigida.')
    pdf = source/'ordenado.pdf'
    if not pdf.is_file():
        raise ValueError('PDF ordenado do lote nao encontrado.')
    if previous.get('pdf_sha256') and digest(pdf) != previous['pdf_sha256']:
        raise ValueError('PDF ordenado alterado desde a tentativa anterior.')
    from pypdf import PdfReader
    if len(PdfReader(pdf).pages) != len(previous['pages']):
        raise ValueError('Quantidade de paginas do PDF difere do manifesto.')
    # Validate existing source files, allowing already archived batches.
    for filename, sha in previous['files'].items():
        if previous.get('already_archived'):continue
        original = Path(filename)
        archived = Path(previous['folder'])/'impressos'/source.name/original.name
        if archived.is_file() and digest(archived)==sha:
            continue
        if original.exists():
            if digest(original) != sha:
                raise ValueError(f'Original alterado: {original.name}')
        elif not archived.is_file() or digest(archived) != sha:
            if not previous.get('already_archived'):
                raise ValueError(f'Original nao localizado: {original.name}')
    handle = win32print.OpenPrinter(printer)
    try:
        if win32print.EnumJobs(handle, 0, 9999, 1):
            raise ValueError('A fila precisa estar vazia antes de reimprimir. Nada foi enviado.')
    finally:
        win32print.ClosePrinter(handle)
    batch = create_batch(work)
    shutil.copy2(pdf, batch/'ordenado.pdf')
    manifest = dict(state='preview', batch_type='reprint',folder=previous['folder'], files=previous['files'],
                    pages=previous['pages'], unmatched=[], issues=[], reprint_of=str(source),
                    previous_job_id=previous.get('job_id'), pdf_sha256=digest(pdf),
                    already_archived=previous.get('already_archived',False) or previous['state'] in ('archived','completed'))
    if previous.get('archive_plan') and not manifest['already_archived']:
        manifest['archive_plan']=[];manifest['result_files']=previous['result_files']
        (batch/'remanescentes').mkdir();(batch/'pares').mkdir()
        for old_entry in previous['archive_plan']:
            entry=dict(old_entry)
            if entry['remaining']:
                target=batch/'remanescentes'/Path(entry['remaining']).name
                shutil.copy2(entry['remaining'],target);entry['remaining']=str(target)
            manifest['archive_plan'].append(entry)
        for record in manifest['result_files']:
            shutil.copy2(source/'pares'/record['filename'],batch/'pares'/record['filename'])
    save(batch/'manifest.json', manifest)
    print(f'Nova tentativa: {batch}', flush=True)
    submit(batch, manifest, printer)

def check_previously_sent(work, hashes):
    for previous in work.glob('*/manifest.json'):
        old = json.loads(previous.read_text(encoding='utf-8'))
        if old['state'] != 'preview' and set(old['files'].values()) & set(hashes):
            raise ValueError(f'Arquivos ja enviados ou envio incerto. Confira o lote: {previous.parent}')

def print_prepared(batch, work, printer):
    """Print exactly the reviewed preview, never silently rebuild it."""
    from pypdf import PdfReader
    batch=batch.resolve()
    if batch.parent != work.resolve():
        raise ValueError('Lote fora da pasta de processamento selecionada.')
    manifest=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    if manifest['state'] != 'preview':
        raise ValueError('Este lote ja teve uma tentativa. Use Reimprimir lote.')
    if manifest.get('reprint_of'):
        raise ValueError('Esta e uma tentativa de reimpressao. Use Reimprimir lote.')
    if manifest.get('issues') or manifest.get('unmatched') or not manifest.get('pages'):
        raise ValueError('O lote tem pendencias e nao pode ser impresso.')
    for filename, sha in manifest['files'].items():
        file=Path(filename)
        if not file.is_file() or digest(file)!=sha:
            raise ValueError(f'Arquivo alterado ou ausente: {file.name}. Gere outra previa.')
    pdf=batch/'ordenado.pdf'
    if manifest.get('pdf_sha256') and digest(pdf)!=manifest['pdf_sha256']:
        raise ValueError('A previa foi alterada. Gere outra previa.')
    if len(PdfReader(pdf).pages)!=len(manifest['pages']):
        raise ValueError('O PDF nao corresponde ao numero de paginas do lote.')
    check_previously_sent(work,manifest['files'].values())
    manifest['reviewed_preview']=True
    submit(batch,manifest,printer)

def confirm_printed(batch,work):
    batch=batch.resolve()
    if batch.parent!=work.resolve():raise ValueError('Lote fora da pasta de processamento.')
    manifest=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    if manifest['state'] not in ('sent','archiving','archived','completed'):
        raise ValueError('Este lote nao possui envio concluido para confirmar.')
    manifest['physical_output_verified']=True
    manifest['confirmed_at']=datetime.now().isoformat()
    save(batch/'manifest.json',manifest)
    if manifest['state'] in ('archived','completed'):return
    if manifest.get('already_archived'):
        manifest['state']='completed';save(batch/'manifest.json',manifest)
    else:archive(batch)

def read_orders(batch,work):
    """Supplement old OCR caches without changing the PDF or print history."""
    import pypdfium2
    batch=batch.resolve()
    if batch.parent!=work.resolve():raise ValueError('Lote fora da pasta de processamento.')
    manifest=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    doc=None;engine=None
    try:
        for index,page in enumerate(manifest.get('pages',[])):
            if page['kind']!='nf' or not page.get('sha256'):continue
            cache=work/'ocr'/(page['sha256']+'.json')
            if not cache.is_file():continue
            raw=json.loads(cache.read_text(encoding='utf-8'));entry=raw[page['page']]
            if not ecommerce_order(entry['lines']) and not entry.get('order_ocr_attempted'):
                print(f"Lendo pedido e-commerce da NF {page.get('nf','')}…",flush=True)
                if doc is None:doc=pypdfium2.PdfDocument(str(batch/'ordenado.pdf'))
                pdf_page=doc[index]
                try:entry['order_ocr_lines'],engine=order_footer_ocr(pdf_page,engine)
                finally:pdf_page.close()
                entry['order_ocr_attempted']=True;save(cache,raw)
            value=ecommerce_order(entry['lines']+entry.get('order_ocr_lines',[]))
            print(f"NF {page.get('nf','')} | Pedido e-commerce: {value or 'nao identificado'}",flush=True)
    finally:
        if doc:doc.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=DEFAULT_FOLDER)
    parser.add_argument('--print', dest='print_now', action='store_true')
    parser.add_argument('--confirm-printed', type=Path)
    parser.add_argument('--reprint', type=Path, help='Reenvia explicitamente um lote, preservando seu historico')
    parser.add_argument('--print-batch', type=Path, help='Imprime exatamente a previa selecionada')
    parser.add_argument('--pending-only',action='store_true',help='Analisa somente arquivos ainda nao enviados')
    parser.add_argument('--read-orders',type=Path,help='Atualiza leitura dos pedidos no rodape do lote')
    parser.add_argument('--approve-pairs',type=Path,help='Aprova e imprime somente pares completos')
    parser.add_argument('--printer', default=DEFAULT_PRINTER)
    args = parser.parse_args()
    if sum((bool(args.reprint),bool(args.confirm_printed),bool(args.print_batch),bool(args.read_orders),bool(args.approve_pairs),args.print_now)) > 1:
        parser.error('Use somente uma acao de impressao por vez')
    folder = args.folder.resolve()
    work = folder/'_processamento'
    (work/'ocr').mkdir(parents=True, exist_ok=True)
    lock = work/'execucao.lock'
    try:
        fd = os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'Outra execucao em andamento ou interrompida: {lock}')
    try:
        os.close(fd)
        if args.approve_pairs:
            from approval import prepare_pairs
            batch,manifest=prepare_pairs(args.approve_pairs,work)
            submit(batch,manifest,args.printer)
            return
        if args.read_orders:
            read_orders(args.read_orders,work)
            return
        if args.print_batch:
            print_prepared(args.print_batch,work,args.printer)
            return
        if args.reprint:
            source = args.reprint
            if not source.is_absolute():
                source = work/source
            reprint_batch(source, work, args.printer)
            return
        if args.confirm_printed:
            confirm_printed(args.confirm_printed,work)
            return
        files = sorted(folder.glob('*.pdf'))
        if not files:
            print('Nenhum PDF na pasta de entrada.')
            return
        snapshots = {str(f): digest(f) for f in files}
        if args.pending_only:
            sent=set()
            for previous in work.glob('*/manifest.json'):
                old=json.loads(previous.read_text(encoding='utf-8'))
                if old['state']!='preview':sent.update(old.get('files',{}).values())
            files=[f for f in files if snapshots[str(f)] not in sent]
            snapshots={str(f):snapshots[str(f)] for f in files}
            if not files:
                print('Nenhum PDF pendente: os arquivos presentes ja tiveram envio registrado.')
                return
        if len(set(snapshots.values())) != len(files):
            raise ValueError('PDFs identicos com nomes diferentes: remova a duplicata da entrada')
        # Block any files already submitted, even if copied back from impressos.
        check_previously_sent(work,snapshots.values())
        # Snapshot stability: reject active downloads instead of reading a moving input.
        time.sleep(1)
        if any(digest(Path(f)) != sha for f,sha in snapshots.items()):
            raise ValueError('Arquivos ainda sendo gravados. Tente novamente ao terminar o download.')
        pages = scan(files, work)
        ordered, unmatched, issues = arrange(pages)
        batch = create_batch(work)
        if ordered:
            write_pdf(ordered, batch/'ordenado.pdf')
        if unmatched:
            write_pdf(unmatched, batch/'sem-correspondencia.pdf')
        manifest = dict(state='preview', batch_type='preview',folder=str(folder), files=snapshots, pages=ordered, unmatched=unmatched, issues=issues,
                        pdf_sha256=digest(batch/'ordenado.pdf') if ordered else None)
        save(batch/'manifest.json', manifest)
        print(f'Previa: {batch}', flush=True)
        print(f'{len(ordered)} paginas ordenadas; {len(unmatched)} sem par; {len(issues)} pendencias.')
        for p in ordered:
            print(f"  {p['name']} | {p['kind']} | NF {p['nf']}")
        for issue in issues:
            print('REVISAR:', issue)
        if args.print_now:
            if issues or unmatched or not ordered:
                raise ValueError('Impressao bloqueada pelas pendencias; originais preservados.')
            if any(digest(Path(f)) != sha for f,sha in snapshots.items()):
                raise ValueError('Entrada mudou apos analise')
            submit(batch, manifest, args.printer)
    finally:
        lock.unlink(missing_ok=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERRO: {exc}', flush=True)
        raise SystemExit(1)
