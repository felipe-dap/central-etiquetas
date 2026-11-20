"""Approve complete pairs and archive sources with resumable partial-file handling."""
import json
import os
from pathlib import Path
import re
import shutil
from datetime import datetime
from batch_names import create_batch

def approvable_pairs(data,states=None):
    from list_data import grouped_rows
    from etiquetas import normal
    if not data or data.get('state')!='preview' or data.get('reprint_of'):return []
    pairs=[]
    for group in grouped_rows(data):
        if len(group['nfs'])!=1 or not group['ships'] or group['unknown']:continue
        refs=group['nfs']+group['ships']
        if states and any(ref['page']['uid'] in states for ref in refs):continue
        if any(ref['file']!='ordenado.pdf' for ref in refs):continue
        nf=group['nfs'][0]['page']
        if not nf.get('nf') or not nf.get('name'):continue
        if any(not ref['page'].get('match') or normal(ref['page'].get('name',''))!=normal(nf['name']) for ref in group['ships']):continue
        if any(nf.get('cep') and ref['page'].get('cep') and nf['cep']!=ref['page']['cep'] for ref in group['ships']):continue
        pairs.append(group)
    return pairs

def export_pairs(source,target,states=None):
    """Export complete pending pairs without changing the batch or inputs."""
    from etiquetas import digest,write_pdf,normal
    from list_data import enrich
    import tempfile
    source=Path(source).resolve();target=Path(target).resolve()
    data=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    data=enrich(data,source.parent,{})
    pairs=sorted(approvable_pairs(data,states),key=lambda g:normal(g['name']))
    if not pairs:raise ValueError('Nenhum par completo e pendente para gerar PDF.')
    original=source/'ordenado.pdf'
    if data.get('pdf_sha256') and digest(original)!=data['pdf_sha256']:raise ValueError('A prévia foi alterada. Gere nova análise.')
    refs=[r for g in pairs for r in g['nfs']+g['ships']]
    protected={Path(f).resolve() for f in data['files']}
    if target in protected or source.parent==target or source.parent in target.parents:
        raise ValueError('Escolha um destino fora dos originais e da pasta de processamento.')
    for filename in {r['page']['file'] for r in refs}:
        path=Path(filename)
        if not path.is_file() or digest(path)!=data['files'][filename]:raise ValueError('Original alterado ou ausente. Gere nova análise.')
    fd,temp=tempfile.mkstemp(suffix='.pdf',dir=target.parent);os.close(fd)
    try:
        write_pdf([dict(file=str(original),page=r['index']) for r in refs],Path(temp))
        os.replace(temp,target)
    finally:
        if Path(temp).exists():Path(temp).unlink()
    return len(pairs),len(refs)

def stage_existing_pairs(batch,manifest):
    """Make results for older successfully sent batches before archiving them."""
    from etiquetas import digest,save,write_pdf
    from list_data import enrich
    data=enrich(dict(manifest,state='preview'),batch.parent,{})
    data.pop('reprint_of',None) # historical retries are eligible for result export, never a new send
    pairs=approvable_pairs(data)
    if not pairs:return manifest
    (batch/'pares').mkdir(exist_ok=True)
    records=[]
    for group in pairs:
        label=re.sub(r'[^A-Za-z0-9_-]+','_',group['name']).strip('_')[:70] or 'Cliente'
        name=f"NF-{group['nf']}_Pedido-{group.get('ecommerce_order') or 'NA'}_{label}.pdf"
        refs=group['nfs']+group['ships']
        target=batch/'pares'/name
        write_pdf([dict(file=str(batch/'ordenado.pdf'),page=r['index']) for r in refs],target)
        records.append(dict(name=group['name'],nf=group['nf'],ecommerce_order=group.get('ecommerce_order',''),filename=name,
                            sha256=digest(target),page_count=len(refs)))
    manifest['result_files']=records
    manifest['archive_plan']=[dict(source=f,sha256=sha,remaining=None,remaining_sha256=None) for f,sha in manifest['files'].items()]
    save(batch/'manifest.json',manifest)
    return manifest

def prepare_pairs(source,work):
    from etiquetas import digest,save,write_pdf,check_previously_sent
    from list_data import enrich
    from pypdf import PdfReader
    source=source.resolve();work=work.resolve()
    if source.parent!=work:raise ValueError('Lote fora da pasta de processamento.')
    old=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if old.get('state')!='preview':raise ValueError('Lote ja enviado: use reimpressao, sem aprovar novamente.')
    folder=Path(old['folder']).resolve()
    if folder/'_processamento'!=work:raise ValueError('Pasta de entrada difere do lote.')
    pdf=source/'ordenado.pdf'
    if old.get('pdf_sha256') and digest(pdf)!=old['pdf_sha256']:raise ValueError('A previa foi alterada.')
    old=enrich(old,work,{})
    pairs=approvable_pairs(old)
    if not pairs:raise ValueError('Nenhum par completo e valido para aprovar.')
    pages=[ref['page'] for group in pairs for ref in group['nfs']+group['ships']]
    files={page['file']:old['files'][page['file']] for page in pages}
    for filename,sha in files.items():
        file=Path(filename).resolve()
        if file.parent!=folder:raise ValueError('Original fora da pasta de entrada.')
        if not file.is_file() or digest(file)!=sha:raise ValueError(f'Original alterado ou ausente: {file.name}. Gere nova analise.')
    check_previously_sent(work,files.values())
    batch=create_batch(work)
    write_pdf(pages,batch/'ordenado.pdf')
    plan=[]
    (batch/'remanescentes').mkdir();(batch/'pares').mkdir()
    for filename,sha in files.items():
        selected={page['page'] for page in pages if page['file']==filename}
        count=len(PdfReader(filename).pages)
        if not selected <= set(range(count)):raise ValueError('Indice de pagina fora do original.')
        remaining=[i for i in range(count) if i not in selected]
        prepared=None
        if remaining:
            prepared=batch/'remanescentes'/Path(filename).name
            write_pdf([dict(file=filename,page=i) for i in remaining],prepared)
        plan.append(dict(source=filename,sha256=sha,remaining=str(prepared) if prepared else None,
                         remaining_sha256=digest(prepared) if prepared else None))
    result_files=[]
    for group in pairs:
        label=re.sub(r'[^A-Za-z0-9_-]+','_',group['name']).strip('_')[:70] or 'Cliente'
        name=f"NF-{group['nf']}_Pedido-{group.get('ecommerce_order') or 'NA'}_{label}.pdf"
        pair_pages=[r['page'] for r in group['nfs']+group['ships']]
        target=batch/'pares'/name;write_pdf(pair_pages,target)
        result_files.append(dict(name=group['name'],nf=group['nf'],ecommerce_order=group.get('ecommerce_order',''),
                                 filename=name,sha256=digest(target),page_count=len(pair_pages)))
    manifest=dict(state='preview',batch_type='approval',folder=str(folder),files=files,pages=pages,issues=[],unmatched=[],
                  approved_from=str(source),approved_at=datetime.now().isoformat(),reviewed_preview=True,
                  pdf_sha256=digest(batch/'ordenado.pdf'),archive_plan=plan,result_files=result_files)
    save(batch/'manifest.json',manifest)
    print(f'Previa: {batch}',flush=True)
    print(f'{len(pairs)} pares aprovados; {len(pages)} paginas. Pendentes fora desta impressao.',flush=True)
    return batch,manifest

def archive_pairs(batch,manifest):
    from etiquetas import digest,save
    folder=Path(manifest['folder']).resolve();destination=folder/'impressos'/batch.name
    results=folder/'resultados'/batch.name
    destination.mkdir(parents=True,exist_ok=True);results.mkdir(parents=True,exist_ok=True)
    # Validate every source and prepared remainder before the first move.
    for entry in manifest['archive_plan']:
        src=Path(entry['source']).resolve();archived=destination/src.name
        if src.parent!=folder:raise ValueError('Origem fora da pasta de entrada.')
        if archived.exists():
            if digest(archived)!=entry['sha256']:raise ValueError('Original arquivado diverge do registro.')
            if entry['remaining'] and src.exists() and digest(src)!=entry['remaining_sha256']:
                raise ValueError('Pendencia alterada durante o arquivamento.')
        elif not src.is_file() or digest(src)!=entry['sha256']:
            raise ValueError(f'Original alterado: {src.name}. Arquivos preservados.')
        if entry['remaining']:
            remaining=Path(entry['remaining']).resolve()
            if remaining.parent!=batch.resolve()/'remanescentes' or digest(remaining)!=entry['remaining_sha256']:
                raise ValueError('PDF de pendencias alterado.')
    for record in manifest['result_files']:
        prepared=batch/'pares'/record['filename']
        if prepared.parent!=batch/'pares' or digest(prepared)!=record['sha256']:raise ValueError('Par preparado alterado.')
        target=results/record['filename']
        if target.exists() and digest(target)!=record['sha256']:raise ValueError('Resultado existente divergente.')
    manifest['state']='archiving';save(batch/'manifest.json',manifest)
    for entry in manifest['archive_plan']:
        src=Path(entry['source']);archived=destination/src.name
        if not archived.exists():
            # rename within this volume is atomic; no recursive moves/deletes.
            src.rename(archived)
        if entry['remaining'] and not src.exists():
            tmp=folder/('.etiquetas-'+batch.name+'-'+src.name+'.tmp')
            shutil.copy2(entry['remaining'],tmp)
            try:os.link(tmp,src) # exclusive creation: never overwrite a new download
            finally:tmp.unlink(missing_ok=True)
    for record in manifest['result_files']:
        target=results/record['filename']
        if not target.exists():
            temp=results/(record['filename']+'.tmp');shutil.copy2(batch/'pares'/record['filename'],temp)
            try:os.link(temp,target)
            finally:temp.unlink(missing_ok=True)
        record['path']=str(target)
    manifest['state']='archived';manifest['results_folder']=str(results)
    save(batch/'manifest.json',manifest)
    print(f'Originais arquivados em {destination}. Pares em {results}',flush=True)
