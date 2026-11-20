"""A single dispatch row per invoice, with separate NF and shipping cells."""
import json
from pathlib import Path
from document_data import dispatch_metadata,ecommerce_order,supplement_items

FINISHED={'archived','completed','confirmed'}

def enrich(data,work,cache):
    # Enrich old history from OCR without rewriting its audit record or pairing.
    data=dict(data)
    for collection in ('pages','unmatched'):
        entries=[]
        for original in data.get(collection,[]):
            page=dict(original);sha=page.get('sha256')
            if sha:
                if sha not in cache:
                    try:cache[sha]=json.loads((Path(work)/'ocr'/(sha+'.json')).read_text(encoding='utf-8'))
                    except (OSError,ValueError):cache[sha]=[]
                raw=cache[sha]
                if page.get('page',0)<len(raw):
                    kind=page['kind'];lines=raw[page['page']]['lines']
                    layout=page.get('layout','simplificado')
                    if kind=='nf' and any(s.strip().upper()=='DANFE SIMPLIFICADO' for s in lines):layout='simplificado'
                    page.update(dispatch_metadata(lines,kind,layout))
                    supplement_items(page,raw[page.get('page',0)].get('items_ocr_lines',[]))
                    if kind=='nf':
                        page['ecommerce_order']=ecommerce_order(lines+raw[page.get('page',0)].get('order_ocr_lines',[]))
                        page['order_ocr_attempted']=raw[page.get('page',0)].get('order_ocr_attempted',False)
            entries.append(page)
        data[collection]=entries
    return data

def effective_states(history):
    states={}
    for _,data,_ in history: # newest first
        for page in data.get('pages',[]):
            if data['state']!='preview':states.setdefault(page['uid'],'confirmed' if data.get('physical_output_verified') else data['state'])
    return states

def doc_status(page,batch_state,states,pending=False):
    if pending:return 'Revisar'
    state=states.get(page['uid'],batch_state)
    if state=='confirmed':return 'Impresso'
    if state in FINISHED:return 'Impresso (fila)'
    if state in ('sent','submitting'):return 'Enviado · conferir'
    if state in ('uncertain','archiving'):return 'Conferir'
    return 'Pendente'

def grouped_rows(data,states=None):
    states=states or {};groups={}
    for collection,filename in [('pages','ordenado.pdf'),('unmatched','sem-correspondencia.pdf')]:
        for i,page in enumerate(data.get(collection,[])):
            key=page.get('nf') or page['uid']
            if key not in groups:
                groups[key]=dict(name=page.get('name',''),nf=page.get('nf',''),ecommerce_order='',nfs=[],ships=[],unknown=[],alerts=[],observations=[],items=[])
            group=groups[key]
            ref=dict(page=page,file=filename,index=i,status=doc_status(page,data['state'],states,collection=='unmatched'))
            if page['kind']=='nf':
                group['name']=page.get('name') or group['name'];group['nfs'].append(ref)
                group['ecommerce_order']=page.get('ecommerce_order') or group['ecommerce_order']
                if page.get('observations'):
                    group['alerts'].append('Observações');group['observations'].append(page['observations'])
                if page.get('observation_review'):group['alerts'].append('Conferir observações')
                group['items'].extend(page.get('items',[]))
            elif page['kind']=='envio':group['ships'].append(ref)
            else:group['unknown'].append(ref)
    result=[]
    for group in groups.values():
        refs=group['nfs']+group['ships']+group['unknown']
        statuses={r['status'] for r in refs}
        if group['unknown'] or 'Revisar' in statuses:status='Revisar'
        elif statuses=={'Impresso'}:status='Impresso'
        elif statuses <= {'Impresso','Impresso (fila)'}:status='Impresso (fila)'
        elif statuses & {'Conferir','Enviado · conferir'}:status='Enviado · conferir'
        else:status='Pendente'
        group['status']=status
        group['alerts']=list(dict.fromkeys(group['alerts']))
        group['carrier']=' / '.join(dict.fromkeys(r['page'].get('carrier','') for r in group['ships'] if r['page'].get('carrier')))
        if not group['carrier']:
            group['carrier']=' / '.join(dict.fromkeys(r['page'].get('carrier','') for r in group['nfs'] if r['page'].get('carrier')))
        group['tracking']=' / '.join(dict.fromkeys(r['page'].get('tracking','') for r in group['ships'] if r['page'].get('tracking')))
        result.append(group)
    from etiquetas import normal
    return sorted(result,key=lambda g:(normal(g['name']),g['nf']))

def detail_text(group):
    lines=[f"{group['name']} · NF {group['nf']} · Pedido e-commerce {group.get('ecommerce_order') or 'não identificado'} · {group['status']}",
           f"Transportadora: {group['carrier'] or 'não identificada'}  |  Rastreio: {group['tracking'] or 'não identificado'}"]
    for ref in group['nfs']:
        page=ref['page']
        if page.get('fiscal_name') and page.get('delivery_name'):
            lines.append(f"Destinatário fiscal: {page['fiscal_name']} | Entrega: {page['delivery_name']}")
        if page.get('observations'):lines.append('OBSERVAÇÕES: '+page['observations'])
        if page.get('observation_review'):lines.append('ATENÇÃO: não foi possível delimitar as observações. Confira o final da NF.')
    return '\n'.join(lines)
