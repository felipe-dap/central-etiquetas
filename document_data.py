"""Metadata for dispatch review, extracted from local OCR text (no cloud)."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata

def folded(text):
    return unicodedata.normalize('NFKD',text.upper()).encode('ascii','ignore').decode()

def number(text):
    return Decimal(text.replace('.','').replace(',','.'))

def ecommerce_order(lines):
    text=folded(' '.join(lines))
    match=re.search(r'REFERENTE\s+AO\s+PEDIDO\s+DE\s+(?:NUMERO|N[Oº°])\s*[:#]?\s*(\d+(?:\.\d{3})*)\b',text)
    if match:return match[1].replace('.','')
    # OCR may damage the small word NUMERO. The exact AO PEDIDO DE phrase
    # and the following GUARDE instruction still delimit this same field.
    match=re.search(r'AO\s+PEDIDO\s+DE\s+[A-Z]{3,10}\s*[:#]?\s*(\d+(?:\.\d{3})*)[.,]?\s+GUARDE\b',text)
    return match[1].replace('.','') if match else ''

def order_footer_ocr(page,engine=None):
    from rapidocr import RapidOCR
    if engine is None:engine=RapidOCR()
    bitmap=None
    try:
        bitmap=page.render(scale=7)
        image=bitmap.to_pil();image=image.crop((0,int(image.height*.55),image.width,image.height))
        result=engine(image)
        return list(result.txts or []),engine
    finally:
        if bitmap:bitmap.close()

def shipping_data(lines,kind):
    text='\n'.join(lines); upper=folded(text)
    provider='Olist' if any(folded(s).strip()=='OLIST' for s in lines) else 'Melhor Envio' if 'MELHOR' in upper else ''
    carrier=''
    for token,label in [('MAGALOG','Magalog (GFL)'),('JADLOG','Jadlog'),('LOGGI','Loggi'),('GFL','GFL'),('CORREIOS','Correios'),('SEDEX','Correios')]:
        if token in upper:
            carrier=label;break
    if carrier=='Correios':
        if 'SEDEX' in upper:carrier+=' · SEDEX'
        elif re.search(r'\bPAC\b',upper):carrier+=' · PAC'
        if not provider:provider='Correios'
    tracking=''
    if kind=='envio':
        # Exclude recipient/address and the embedded NFe from tracking candidates.
        header=re.split(r'DESTINAT[AÁ]RIO',upper,maxsplit=1)[0]
        patterns=[r'\b[A-Z]{2}\s*\d{3}\s*\d{3}\s*\d{3}\s*BR\b',
                  r'\bME[A-Z0-9]{7,20}BR\b',r'\bGFL[A-Z0-9]{6,24}\b',r'(?m)^\s*\d{14}\s*$']
        for pattern in patterns:
            match=re.search(pattern,header)
            if match:
                tracking=re.sub(r'\s','',match[0]);break
    return dict(carrier=carrier,tracking=tracking,shipping_provider=provider)

def item_table_ocr(page,engine=None):
    from rapidocr import RapidOCR
    if engine is None:engine=RapidOCR()
    bitmap=None
    try:
        bitmap=page.render(scale=7)
        image=bitmap.to_pil()
        image=image.crop((0,int(image.height*.4),image.width,image.height))
        result=engine(image)
        return list(result.txts or []),engine
    finally:
        if bitmap:bitmap.close()

def supplement_items(data,lines):
    """Accept a second reading only when it resolves the same item codes."""
    if not data.get('quantity_review') or not lines:return
    items,review=nf_items(lines)
    old=data.get('items',[])
    if not old or [i['code'] for i in old]!=[i['code'] for i in items] or review:return
    # An already validated quantity must agree between readings.
    if any(a['quantity'] is not None and Decimal(a['quantity'])!=Decimal(b['quantity']) for a,b in zip(old,items)):return
    data['items']=items;data['quantity_review']=[]
    data['quantity_alerts']=[f"{i['code']} · {i['quantity']} un. · {i['description']}" for i in items if Decimal(i['quantity'])!=1]

def nf_notes(lines):
    text='\n'.join(lines)
    marker=re.search(r'contato\s+conosco[\s\S]{0,120}?\bvenda[.!:]?',text,re.I)
    if marker:
        tail=text[marker.end():].strip().lstrip('.;:').lstrip()
        # Remove only known generated footer, not arbitrary customer text.
        tail=re.split(r'Obtenha o arquivo XML|https?://olist\.com/nfe',tail,flags=re.I)[0].strip()
        if re.fullmatch(r'(?:OBS(?:ERVA[ÇC][ÕO]ES)?\s*:?)?',tail,re.I):tail=''
        return tail,False
    return '',any('DADOS ADICIONAIS' in folded(s) for s in lines)

def nf_items(lines):
    start=next((i for i,s in enumerate(lines) if 'DESCRICAO' in folded(s) and ('COD' in folded(s) or 'PRODUTO' in folded(s))),None)
    if start is None:return [],['Tabela de produtos não identificada']
    end=next((i for i in range(start+1,len(lines)) if re.search(r'TOTAL (?:DA )?NFE|TRANSPORTADOR|DADOS ADICIONAIS',folded(lines[i]))),len(lines))
    section=lines[start+1:end]
    starts=[i for i,s in enumerate(section) if re.match(r'^[A-Z]{1,5}\d{2,}[A-Z0-9-]*\b',folded(s))]
    if not starts:return [],['Itens não identificados na tabela de produtos']
    items=[];review=[]
    for pos,index in enumerate(starts):
        row=section[index:starts[pos+1] if pos+1<len(starts) else len(section)]
        code=re.match(r'^([A-Z]{1,5}\d{2,}[A-Z0-9-]*)\s*(.*)',row[0],re.I)
        if not code:continue
        unit=next((i for i,s in enumerate(row) if folded(s).strip().strip('.') in ('PECA','PC','UN','UND','UNID','UNIDADE','KIT','CJ','PAR')),None)
        description=' '.join([code[2],*(row[1:unit] if unit is not None else [])]).strip()
        quantity=None;source='';unit_price=None;total=None
        if unit is not None:
            tokens=re.findall(r'(?<!\w)\d+(?:\.\d{3})*(?:,\d+)?(?!\w)',' '.join(row[unit+1:]))
            try:
                if len(tokens)==3:
                    quantity,unit_price,total=map(number,tokens);source='lida'
                    if unit_price<=0 or abs(quantity*unit_price-total)>Decimal('0.02'):
                        quantity=None
                elif len(tokens)==2:
                    unit_price,total=map(number,tokens)
                    if unit_price>0:
                        ratio=total/unit_price
                        candidate=ratio.quantize(Decimal('0.0001'))
                        if abs(candidate*unit_price-total)<=Decimal('0.005'):
                            quantity=candidate;source='calculada pelos valores'
            except (InvalidOperation,ValueError):quantity=None
        if unit is None:
            # Narrow columns wrap PEÇA into PEÇ / A. OCR can read price before
            # quantity, followed by the SKU's final digit and description.
            text='\n'.join(row)
            fragment=re.search(r'\bpe[çc]\s*(?:\n|$)',text,re.I)
            if fragment:
                tail=text[fragment.end():]
                prices=list(re.finditer(r'(?<!\w)\d+(?:\.\d{3})*,\d{2,}(?!\w)',tail))
                if len(prices)==2 and len(prices[0][0].split(',')[1])>=3 and len(prices[1][0].split(',')[1])==2:
                    # Only inspect the numeric columns, before description/SKU
                    # continuation. Never count the trailing SKU digit as QTD.
                    columns=tail[:prices[-1].end()]
                    columns=re.sub(r'(?<!\w)\d+(?:\.\d{3})*,\d{2,}(?!\w)',' ',columns)
                    quantities=re.findall(r'(?<!\w)\d+(?!\w)',columns)
                    residue=re.sub(r'(?<!\w)\d+(?!\w)','',columns).strip()
                    if len(quantities)==1 and not residue:
                        candidate=number(quantities[0]);unit_price,total=(number(p[0]) for p in prices)
                        if unit_price>0 and abs(candidate*unit_price-total)<=Decimal('0.02'):
                            quantity=candidate;source='lida em colunas quebradas e validada pelos valores'
        if quantity is None:
            review.append(f"{code[1]}: conferir quantidade na NF")
        items.append(dict(code=code[1],description=description,quantity=str(quantity.normalize()) if quantity is not None else None,quantity_source=source))
    return items,review

def dispatch_metadata(lines,kind,layout):
    data=shipping_data(lines,kind)
    data.update(observations='',observation_review=False,items=[],quantity_alerts=[],quantity_review=[],
                ecommerce_order=ecommerce_order(lines) if kind=='nf' else '')
    if kind=='nf' and layout=='simplificado':
        data['observations'],data['observation_review']=nf_notes(lines)
        data['items'],data['quantity_review']=nf_items(lines)
        data['quantity_alerts']=[f"{item['code']} · {item['quantity']} un. · {item['description']}" for item in data['items']
                                 if item['quantity'] is not None and Decimal(item['quantity'])!=1]
    return data
