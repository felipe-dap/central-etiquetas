"""Dear Friends | Central de etiquetas. Interface local para o motor etiquetas.py."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from folder_monitor import FolderMonitor,StableChanges,signature
from list_data import enrich,effective_states,grouped_rows,detail_text
from pdf_preview import PdfPreview
from approval import approvable_pairs,export_pairs
from config import HERE,SETTINGS,DEFAULT_FOLDER,DEFAULT_PRINTER,DATA_DIR,PYTHON

BG='#F4F6F8'; INK='#1C3034'; MUTED='#60747A'; TEAL='#006D66'; WHITE='#FFFFFF'
STATES={'preview':'Prévia pronta','submitting':'Envio em andamento','sent':'Enviado · conferir',
        'uncertain':'Envio incerto','archiving':'Arquivando','archived':'Arquivado','completed':'Concluído na fila'}

def read_history(folder):
    results=[]
    work=Path(folder)/'_processamento'
    if not work.is_dir(): return results
    for file in work.glob('*/manifest.json'):
        try:
            data=json.loads(file.read_text(encoding='utf-8'))
            results.append((file.parent,data,file.stat().st_mtime))
        except (OSError,ValueError):
            continue
    return sorted(results,key=lambda row:row[2],reverse=True)

def ready_to_print(data):
    return bool(data and data.get('state')=='preview' and not data.get('reprint_of') and
                data.get('pages') and not data.get('issues') and not data.get('unmatched'))

def printer_snapshot(name):
    import win32print
    handle=win32print.OpenPrinter(name)
    try:
        data=win32print.GetPrinter(handle,2)
        jobs=win32print.EnumJobs(handle,0,9999,1)
        flags=data['Status']
        blocked=flags & (win32print.PRINTER_STATUS_PAUSED|win32print.PRINTER_STATUS_OFFLINE|
                       win32print.PRINTER_STATUS_ERROR|win32print.PRINTER_STATUS_PAPER_OUT)
        status=('Pausada' if flags & win32print.PRINTER_STATUS_PAUSED else
                'Offline' if flags & win32print.PRINTER_STATUS_OFFLINE else
                'Verificar impressora' if blocked else 'Fila pronta' if not jobs else 'Trabalho na fila')
        return dict(text=status,port=data['pPortName'],jobs=[{'id':j['JobId'],'name':j['pDocument'],
                    'status':j['Status']} for j in jobs],ready=not blocked and not jobs)
    finally:
        win32print.ClosePrinter(handle)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Dear Friends | Central de etiquetas')
        self.geometry('1420x940'); self.minsize(1180,800); self.configure(bg=BG)
        self.events=queue.Queue(); self.busy=False; self.process=None
        self.batch=None; self.data=None; self.history=[]; self.history_paths={}
        self.printer_ready=False; self.polling=False; self.folder_count=0
        self.monitor=None;self.stable=StableChanges();self.rows={};self.ocr_cache={}
        self.auto_operation=False;self.inputs_dirty=False;self.analysis_snapshot=None
        self.order_attempts=set()
        self.monitor_enabled=tk.BooleanVar(value=True)
        self.row_filter=tk.StringVar(value='Pendentes')
        self.folder=tk.StringVar(value=str(DEFAULT_FOLDER)); self.printer=tk.StringVar(value=DEFAULT_PRINTER)
        try:
            saved=json.loads(SETTINGS.read_text(encoding='utf-8'))
            self.folder.set(str(DEFAULT_FOLDER) if os.environ.get('ETIQUETAS_INPUT_DIR') else saved.get('folder',str(DEFAULT_FOLDER)))
            self.monitor_enabled.set(saved.get('monitor',True))
        except (OSError,ValueError): pass
        self.setup_styles(); self.build()
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.after(100,self.refresh_files); self.after(200,self.refresh_history)
        self.after(400,self.poll_printer); self.after(100,self.drain)
        self.after(600,self.start_monitor);self.after(900,self.check_folder)

    def setup_styles(self):
        style=ttk.Style(self); style.theme_use('clam')
        self.option_add('*Font',('Segoe UI',10))
        style.configure('.',font=('Segoe UI',10),background=BG,foreground=INK)
        style.configure('TFrame',background=BG)
        style.configure('Card.TFrame',background=WHITE)
        style.configure('Card.TLabel',background=WHITE,foreground=INK)
        style.configure('Muted.TLabel',foreground=MUTED)
        style.configure('Title.TLabel',font=('Segoe UI Semibold',26))
        style.configure('TButton',padding=(13,9),background='#E6ECEE',borderwidth=0)
        style.map('TButton',background=[('active','#D8E2E4')])
        style.configure('Primary.TButton',background=TEAL,foreground=WHITE,font=('Segoe UI Semibold',10))
        style.map('Primary.TButton',background=[('disabled','#B6C8C6'),('active','#00544F')],foreground=[('disabled',WHITE)])
        style.configure('TEntry',padding=7,fieldbackground=WHITE)
        style.configure('TCombobox',padding=7,fieldbackground=WHITE)
        style.configure('Treeview',rowheight=33,fieldbackground=WHITE,background=WHITE,borderwidth=0)
        style.configure('Treeview.Heading',background='#EAF0F1',font=('Segoe UI Semibold',10),padding=8)
        style.map('Treeview',background=[('selected','#CFEAE5')],foreground=[('selected',INK)])
        style.configure('TNotebook',background=BG,borderwidth=0)
        style.configure('TNotebook.Tab',padding=(18,9))
        style.configure('Horizontal.TProgressbar',background=TEAL,troughcolor='#E3EBEC',borderwidth=0)

    def build(self):
        outer=ttk.Frame(self,padding=(26,20)); outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='dear friends,',font=('Georgia',15,'italic'),foreground=TEAL).pack(anchor='w')
        title=ttk.Frame(outer); title.pack(fill='x',pady=(6,2))
        ttk.Label(title,text='Central de etiquetas',style='Title.TLabel').pack(side='left')
        self.printer_badge=ttk.Label(title,text='Conferindo impressora…',foreground=MUTED)
        self.printer_badge.pack(side='right')
        ttk.Label(outer,text='Organize por cliente. Confira os pares. Imprima em sequência.',style='Muted.TLabel').pack(anchor='w',pady=(0,16))
        settings=ttk.Frame(outer,style='Card.TFrame',padding=14); settings.pack(fill='x')
        ttk.Label(settings,text='PASTA DE ENTRADA',style='Card.TLabel',font=('Segoe UI Semibold',9)).grid(row=0,column=0,sticky='w')
        ttk.Label(settings,text='IMPRESSORA',style='Card.TLabel',font=('Segoe UI Semibold',9)).grid(row=0,column=3,sticky='w',padx=(18,0))
        self.folder_entry=ttk.Entry(settings,textvariable=self.folder,state='readonly'); self.folder_entry.grid(row=1,column=0,sticky='ew',pady=(5,0))
        self.browse_button=ttk.Button(settings,text='Escolher pasta',command=self.choose_folder); self.browse_button.grid(row=1,column=1,padx=(8,0),pady=(5,0))
        self.open_folder_button=ttk.Button(settings,text='Abrir pasta',command=lambda:self.open_path(self.folder.get()))
        self.open_folder_button.grid(row=1,column=2,padx=(8,0),pady=(5,0))
        ttk.Label(settings,text=f'{DEFAULT_PRINTER} · 100 × 150 mm',style='Card.TLabel',font=('Segoe UI Semibold',11)).grid(row=1,column=3,sticky='w',padx=(18,0),pady=(5,0))
        settings.columnconfigure(0,weight=1)
        toolbar=ttk.Frame(outer); toolbar.pack(fill='x',pady=14)
        self.analyze_button=ttk.Button(toolbar,text='1. Analisar PDFs',style='Primary.TButton',command=self.analyze)
        self.analyze_button.pack(side='left')
        self.print_button=ttk.Button(toolbar,text='Aprovar e imprimir pares',style='Primary.TButton',command=self.print_selected,state='disabled')
        self.print_button.pack(side='left',padx=8)
        self.export_button=ttk.Button(toolbar,text='Gerar PDF dos pares',command=self.export_selected,state='disabled')
        self.export_button.pack(side='left',padx=(0,8))
        self.open_button=ttk.Button(toolbar,text='Abrir PDF',command=self.open_pdf,state='disabled'); self.open_button.pack(side='left')
        self.refresh_button=ttk.Button(toolbar,text='Atualizar',command=self.refresh_all); self.refresh_button.pack(side='right')
        self.summary=ttk.Label(toolbar,text='',style='Muted.TLabel'); self.summary.pack(side='right',padx=14)
        watchbar=ttk.Frame(outer);watchbar.pack(fill='x',pady=(0,10))
        ttk.Checkbutton(watchbar,text='Monitorar pasta automaticamente',variable=self.monitor_enabled,command=self.toggle_monitor).pack(side='left')
        self.watch_label=ttk.Label(watchbar,text='Monitor iniciando…',style='Muted.TLabel');self.watch_label.pack(side='left',padx=14)
        self.tabs=ttk.Notebook(outer); self.tabs.pack(fill='both',expand=True)
        self.current_tab=ttk.Frame(self.tabs,padding=(0,12)); self.history_tab=ttk.Frame(self.tabs,padding=(0,12)); self.details_tab=ttk.Frame(self.tabs,padding=(0,12));self.results_tab=ttk.Frame(self.tabs,padding=(0,12))
        self.tabs.add(self.current_tab,text='Conferir lote');self.tabs.add(self.results_tab,text='Resultados'); self.tabs.add(self.history_tab,text='Histórico e reimpressão'); self.tabs.add(self.details_tab,text='Arquivos e atividade')
        self.build_current(); self.build_history(); self.build_details();self.build_results()
        bottom=ttk.Frame(outer); bottom.pack(fill='x',pady=(10,0))
        self.status=ttk.Label(bottom,text='Salve os PDFs na pasta de entrada e clique em Analisar.',style='Muted.TLabel'); self.status.pack(side='left')
        self.progress=ttk.Progressbar(bottom,mode='indeterminate',length=120); self.progress.pack(side='right')
        ttk.Label(outer,text='100 × 150 mm  •  DANFE simplificado  •  NF → envio  •  Leitura local',font=('Segoe UI',9),foreground=MUTED).pack(anchor='w',pady=(8,0))

    def make_tree(self,parent,columns,widths):
        frame=ttk.Frame(parent); frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
        for col,width in zip(columns,widths):
            tree.heading(col,text=col); tree.column(col,width=width,minwidth=45,stretch=True)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        tree.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        return tree

    def build_current(self):
        pane=ttk.Panedwindow(self.current_tab,orient='horizontal'); pane.pack(fill='both',expand=True)
        self.current_split=pane
        top=ttk.Frame(pane);right=ttk.Frame(pane,style='Card.TFrame',padding=8)
        pane.add(top,weight=3);pane.add(right,weight=2)
        self.after(200,lambda:pane.sashpos(0,int(pane.winfo_width()*.58)) if pane.winfo_width()>1 else None)
        heading=ttk.Frame(top);heading.pack(fill='x',pady=(0,8))
        self.batch_label=ttk.Label(heading,text='Nenhum lote selecionado',font=('Segoe UI Semibold',12)); self.batch_label.pack(side='left')
        filters=ttk.Combobox(heading,textvariable=self.row_filter,values=['Todos','Pendentes','Impressos'],state='readonly',width=13)
        filters.pack(side='right');filters.bind('<<ComboboxSelected>>',lambda e:self.refresh_rows())
        self.page_tree=self.make_tree(top,['Cliente de entrega','NF','Pedido e-commerce','Envio','Transportadora','Rastreio','Status','Alertas NF'],[180,70,110,90,110,150,130,125])
        self.page_tree.configure(height=18)
        self.page_tree.tag_configure('pending',foreground='#A43F2D');self.page_tree.tag_configure('printed',foreground='#22685E')
        self.page_tree.bind('<<TreeviewSelect>>',self.select_page)
        self.page_tree.bind('<Double-1>',self.show_alerts)
        self.issues=tk.Text(top,height=2,wrap='word',bg='#FFF4DF',fg='#775224',relief='flat',font=('Segoe UI',10),padx=10,pady=8,state='disabled')
        right.columnconfigure(0,weight=1,uniform='pdf');right.columnconfigure(1,weight=1,uniform='pdf');right.rowconfigure(0,weight=1)
        self.nf_preview=PdfPreview(right,'NOTA FISCAL',self.log_line)
        self.shipping_preview=PdfPreview(right,'ETIQUETA DE ENVIO',self.log_line)
        self.nf_preview.canvas.configure(height=220)
        self.shipping_preview.canvas.configure(height=220)
        self.nf_preview.grid(row=0,column=0,sticky='nsew',padx=(0,5))
        self.shipping_preview.grid(row=0,column=1,sticky='nsew',padx=(5,0))

    def build_history(self):
        row=ttk.Frame(self.history_tab); row.pack(fill='x',pady=(0,10))
        ttk.Label(row,text='Selecione um lote para conferir ou reenviar.',style='Muted.TLabel').pack(side='left')
        self.confirm_button=ttk.Button(row,text='Confirmar impresso',command=self.confirm_selected,state='disabled');self.confirm_button.pack(side='right',padx=8)
        self.reprint_button=ttk.Button(row,text='Reimprimir selecionado',command=self.reprint_selected,state='disabled'); self.reprint_button.pack(side='right')
        self.remove_history_button=ttk.Button(row,text='Remover do histórico',command=self.remove_history_selected,state='disabled')
        self.remove_history_button.pack(side='right',padx=8)
        self.history_tree=self.make_tree(self.history_tab,['Lote','Situação','Páginas','Pendências'],[430,210,80,90])
        self.history_tree.bind('<<TreeviewSelect>>',self.select_history)
        self.history_tree.bind('<Double-1>',lambda e:self.tabs.select(self.current_tab))

    def build_details(self):
        row=ttk.Frame(self.details_tab); row.pack(fill='x',pady=(0,10))
        ttk.Button(row,text='Abrir pasta de entrada',command=lambda:self.open_path(Path(self.folder.get()))).pack(side='left')
        ttk.Button(row,text='Abrir pasta do lote',command=lambda:self.open_path(self.batch) if self.batch else None).pack(side='left',padx=8)
        ttk.Button(row,text='Conferir impressora',command=self.poll_printer).pack(side='right')
        self.file_label=ttk.Label(self.details_tab,text='',style='Muted.TLabel'); self.file_label.pack(anchor='w',pady=(0,8))
        self.log=tk.Text(self.details_tab,wrap='word',bg=WHITE,fg=INK,relief='flat',font=('Consolas',10),padx=14,pady=14,state='disabled')
        self.log.pack(fill='both',expand=True)

    def build_results(self):
        actions=ttk.Frame(self.results_tab);actions.pack(fill='x',pady=(0,10))
        ttk.Label(actions,text='Um PDF por par, com a NF seguida da etiqueta de envio.',style='Muted.TLabel').pack(side='left')
        ttk.Button(actions,text='Abrir PDF do par',command=self.open_result).pack(side='right')
        ttk.Button(actions,text='Abrir pasta de resultados',command=lambda:self.open_path(Path(self.folder.get())/'resultados')).pack(side='right',padx=8)
        self.results_tree=self.make_tree(self.results_tab,['Cliente','NF','Pedido e-commerce','Status','Lote'],[280,90,140,200,350])
        self.results_tree.bind('<Double-1>',lambda e:self.open_result())
        self.result_paths={}

    def refresh_results(self):
        self.results_tree.delete(*self.results_tree.get_children());self.result_paths={}
        for batch,data,_ in self.history:
            if data.get('state') not in ('archived','completed'):continue
            for record in data.get('result_files',[]):
                path=Path(record.get('path',''))
                if not path.is_file():continue
                iid=str(len(self.result_paths));self.result_paths[iid]=path
                status='Impresso confirmado' if data.get('physical_output_verified') else 'Concluído na fila'
                self.results_tree.insert('','end',iid=iid,values=(record['name'],record['nf'],record.get('ecommerce_order') or '—',status,batch.name))

    def open_result(self):
        selected=self.results_tree.selection()
        if selected:self.open_path(self.result_paths.get(selected[0]))

    def log_line(self,text):
        self.log.configure(state='normal'); self.log.insert('end',text.rstrip()+'\n'); self.log.see('end'); self.log.configure(state='disabled')

    def remember(self):
        try:
            SETTINGS.parent.mkdir(parents=True,exist_ok=True)
            SETTINGS.write_text(json.dumps(dict(folder=self.folder.get(),printer=self.printer.get(),monitor=self.monitor_enabled.get()),ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError as exc: self.log_line(f'Não foi possível salvar preferências: {exc}')

    def choose_folder(self):
        chosen=filedialog.askdirectory(initialdir=self.folder.get(),title='Pasta com os PDFs de entrada')
        if chosen:
            self.folder.set(chosen); self.remember(); self.batch=None; self.data=None; self.clear_preview()
            self.page_tree.delete(*self.page_tree.get_children()); self.batch_label.configure(text='Nenhum lote selecionado')
            self.set_issues([]);self.ocr_cache={};self.rows={}; self.refresh_all();self.start_monitor()

    def refresh_files(self):
        folder=Path(self.folder.get())
        files=sorted(folder.glob('*.pdf')) if folder.is_dir() else []
        self.folder_count=len(files)
        self.file_label.configure(text=f'{len(files)} PDFs na entrada: '+(', '.join(p.name for p in files) or 'pasta vazia'))
        self.summary.configure(text=f'{len(files)} PDFs na entrada')
        self.update_actions()

    def ensure_orders(self):
        if self.busy or not self.batch or not self.data:return
        key=str(self.batch)
        if key in self.order_attempts:return
        if any(p['kind']=='nf' and not p.get('ecommerce_order') and not p.get('order_ocr_attempted') for p in self.data.get('pages',[])):
            self.order_attempts.add(key)
            self.run_engine(['--read-orders',str(self.batch)],'Lendo números dos pedidos no rodapé…',automatic=True)

    def refresh_all(self):
        self.refresh_files(); self.refresh_history(); self.poll_printer()

    def refresh_history(self,preferred=None):
        selected=preferred or self.batch
        self.history=read_history(self.folder.get()); self.history_paths={}
        self.history_tree.delete(*self.history_tree.get_children())
        for i,(path,data,_) in enumerate(self.history):
            if data.get('hidden_from_history'):continue
            iid=str(i); self.history_paths[iid]=(path,data)
            count=len(data.get('issues',[]))+len(data.get('unmatched',[]))
            label=STATES.get(data.get('state'),data.get('state','Desconhecido'))
            if data.get('physical_output_verified'):label='Impresso confirmado'
            if data.get('state')=='preview' and count: label='Revisar pendências'
            self.history_tree.insert('','end',iid=iid,values=(path.name,label,len(data.get('pages',[])),count))
            if selected and path==selected:
                self.history_tree.selection_set(iid); self.history_tree.see(iid)
        if not selected and self.history_paths:
            self.history_tree.selection_set(next(iter(self.history_paths)))
        self.refresh_results()
        self.update_actions()

    def select_history(self,event=None):
        selection=self.history_tree.selection()
        if not selection or selection[0] not in self.history_paths:return
        self.batch,self.data=self.history_paths[selection[0]]
        self.data=enrich(self.data,Path(self.folder.get())/'_processamento',self.ocr_cache)
        self.refresh_rows()
        self.set_issues(self.data.get('issues',[]))
        self.update_actions()
        if any(p['kind']=='nf' and not p.get('ecommerce_order') and not p.get('order_ocr_attempted') for p in self.data.get('pages',[])):
            self.after(300,self.ensure_orders)

    def refresh_rows(self):
        self.page_tree.delete(*self.page_tree.get_children())
        self.rows={}
        if not self.data:return
        groups=grouped_rows(self.data,effective_states(self.history))
        printed=sum(g['status'].startswith('Impresso') for g in groups)
        self.batch_label.configure(text=f'{len(groups)} clientes/pedidos · {len(groups)-printed} pendentes · {printed} impressos')
        for i,g in enumerate(groups):
            if self.row_filter.get()=='Pendentes' and g['status'].startswith('Impresso'):continue
            if self.row_filter.get()=='Impressos' and not g['status'].startswith('Impresso'):continue
            iid=str(i);self.rows[iid]=g
            nf=(g['nf'] or '—')+('  ⚠' if g['alerts'] else '') if g['nfs'] else 'Ausente'
            shipping=f"{len(g['ships'])} etiqueta(s)" if g['ships'] else 'Ausente'
            tag='printed' if g['status'].startswith('Impresso') else 'pending' if g['status']=='Revisar' else ''
            self.page_tree.insert('','end',iid=iid,values=(g['name'] or 'Nome não reconhecido',nf,g.get('ecommerce_order') or 'Não identificado',shipping,g['carrier'] or '—',g['tracking'] or '—',g['status'],' · '.join(g['alerts']) or '—'),tags=(tag,))
        if self.rows:self.page_tree.selection_set(next(iter(self.rows)))
        else:
            self.clear_preview()
            if self.row_filter.get()=='Pendentes':self.batch_label.configure(text=f'Nenhum item pendente · {printed} concluídos no histórico')

    def set_issues(self,issues):
        self.issues.configure(state='normal'); self.issues.delete('1.0','end')
        self.issues.insert('end','\n'.join(issues) if issues else 'Sem pendências de associação. Confira a prévia antes de imprimir.')
        self.issues.configure(state='disabled')
        if issues:self.issues.pack(fill='x',pady=(6,0))
        else:self.issues.pack_forget()

    def clear_preview(self):
        self.nf_preview.clear();self.shipping_preview.clear()

    def select_page(self,event=None):
        selected=self.page_tree.selection()
        if not selected or not self.batch:return
        group=self.rows.get(selected[0])
        if not group:return
        self.nf_preview.set_documents(self.batch,group['nfs'])
        self.shipping_preview.set_documents(self.batch,group['ships'])

    def show_alerts(self,event=None):
        selected=self.page_tree.selection();group=self.rows.get(selected[0]) if selected else None
        if group and group['alerts']:
            messagebox.showinfo('Alertas da NF '+group['nf'],detail_text(group),parent=self)

    def copy_tracking(self):
        selected=self.page_tree.selection()
        group=self.rows.get(selected[0]) if selected else None
        if group and group['tracking']:
            self.clipboard_clear();self.clipboard_append(group['tracking']);self.status.configure(text='Rastreio copiado.')

    def open_path(self,path):
        try:
            if path and Path(path).exists():os.startfile(str(path))
            else:messagebox.showinfo('Pasta não encontrada','A pasta será criada ao analisar o primeiro lote.',parent=self)
        except OSError as exc:messagebox.showerror('Não foi possível abrir',str(exc),parent=self)

    def open_pdf(self):
        if self.batch:self.open_path(self.batch/'ordenado.pdf')

    def update_actions(self):
        self.analyze_button.configure(state='normal' if not self.busy and self.folder_count else 'disabled')
        pairs=approvable_pairs(self.data,effective_states(self.history))
        self.export_button.configure(state='normal' if not self.busy and not self.inputs_dirty and pairs else 'disabled')
        self.print_button.configure(state='normal' if not self.busy and not self.inputs_dirty and self.printer_ready and pairs else 'disabled')
        self.open_button.configure(state='normal' if self.batch and (self.batch/'ordenado.pdf').is_file() else 'disabled')
        can_reprint=bool(self.data and self.data.get('pages') and not self.data.get('issues') and not self.data.get('unmatched'))
        self.reprint_button.configure(state='normal' if not self.busy and self.printer_ready and can_reprint else 'disabled')
        can_confirm=self.data and self.data.get('state') in ('sent','archiving','archived','completed') and not self.data.get('physical_output_verified')
        self.confirm_button.configure(state='normal' if not self.busy and can_confirm else 'disabled')
        self.browse_button.configure(state='disabled' if self.busy else 'normal')
        self.remove_history_button.configure(state='normal' if not self.busy and self.batch and self.data else 'disabled')

    def analyze(self,automatic=False):
        if self.busy:return
        self.tabs.select(self.current_tab)
        self.run_engine(['--pending-only'], 'Lendo PDFs e montando os pares…',automatic=automatic)

    def print_selected(self):
        pairs=approvable_pairs(self.data,effective_states(self.history))
        if not pairs or self.busy:return
        count=sum(len(g['nfs'])+len(g['ships']) for g in pairs)
        alerts=[g for g in pairs if g['alerts']]
        caution=f'\n\nHá alertas de expedição em {len(alerts)} NF(s). Confira os detalhes antes de continuar.' if alerts else ''
        if messagebox.askyesno('Aprovar e imprimir pares',f'Aprovar {len(pairs)} pares completos e enviar {count} páginas à Zebra?\n\nDocumentos sem par ficam pendentes. Depois da conclusão, os originais serão arquivados e cada par será salvo em resultados. O filtro da lista não altera os pares aprovados.'+caution,parent=self):
            self.run_engine(['--approve-pairs',str(self.batch)],'Aprovando pares e preparando impressão…')

    def export_selected(self):
        if self.busy or self.inputs_dirty or not self.batch:return
        destination=Path(self.folder.get())/'pdfs-gerados'
        destination.mkdir(exist_ok=True)
        target=filedialog.asksaveasfilename(parent=self,title='Salvar PDF dos pares',initialdir=str(destination),
                                          initialfile=f'Pares-{self.batch.name}.pdf',defaultextension='.pdf',filetypes=[('PDF','*.pdf')])
        if not target:return
        try:
            count,pages=export_pairs(self.batch,target,effective_states(self.history))
            self.status.configure(text=f'PDF gerado: {count} pares · {pages} páginas. Itens continuam pendentes.')
            self.log_line(f'PDF gerado: {target}')
            self.open_path(target)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Não foi possível gerar PDF',str(exc),parent=self)

    def reprint_selected(self):
        if not self.batch or self.busy:return
        if messagebox.askyesno('Reimprimir lote inteiro',f"Enviar novamente todas as {len(self.data.get('pages',[]))} páginas?\n\nPáginas que já saíram serão impressas outra vez. A tentativa anterior permanece no histórico.",parent=self):
            self.run_engine(['--reprint',str(self.batch)],'Preparando uma nova tentativa…')

    def remove_history_selected(self):
        if self.busy or not self.batch or not self.data:return
        if not messagebox.askyesno('Remover do histórico',f'Remover o lote {self.batch.name} da lista?\n\nOs PDFs de entrada, resultados e registros de impressão serão preservados. Isso não cancela trabalhos na fila da Zebra.',parent=self):return
        try:
            from etiquetas import save
            path=self.batch/'manifest.json'
            data=json.loads(path.read_text(encoding='utf-8'))
            data['hidden_from_history']=True
            save(path,data)
            self.batch=None;self.data=None;self.rows={}
            self.page_tree.delete(*self.page_tree.get_children());self.clear_preview()
            self.batch_label.configure(text='Nenhum lote selecionado');self.set_issues([])
            self.refresh_history();self.update_actions()
            self.status.configure(text='Lote removido do histórico. Arquivos preservados.')
        except (OSError,ValueError) as exc:
            messagebox.showerror('Não foi possível remover',str(exc),parent=self)

    def confirm_selected(self):
        if not self.batch or self.busy:return
        if messagebox.askyesno('Confirmar saída física',f"Todas as {len(self.data.get('pages',[]))} páginas deste lote saíram corretamente?\n\nA confirmação marca como impresso e arquiva os originais, se ainda estiverem pendentes. Não envia outra impressão.",parent=self):
            self.run_engine(['--confirm-printed',str(self.batch)],'Confirmando impressão e arquivando…')

    def run_engine(self,args,status,automatic=False):
        if self.busy:return
        self.busy=True; self.status.configure(text=status); self.progress.start(12); self.update_actions()
        self.auto_operation=automatic
        self.operation=list(args)
        self.analysis_snapshot=signature(self.folder.get())
        if '--pending-only' in args:
            self.stable.handled=self.analysis_snapshot;self.stable.candidate=self.analysis_snapshot
            self.stable.dirty=False
        self.remember()
        folder=self.folder.get(); printer=self.printer.get()
        self.log_line('\n'+status)
        def worker():
            try:
                env=os.environ.copy(); env['PYTHONUTF8']='1'; env['PYTHONUNBUFFERED']='1'
                python=PYTHON
                command=[str(python),'-u',str(HERE/'etiquetas.py'),'--folder',folder,'--printer',printer,*args]
                process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,cwd=HERE,creationflags=subprocess.CREATE_NO_WINDOW)
                self.process=process
                for line in process.stdout:self.events.put(('line',line))
                self.events.put(('done',process.wait()))
            except Exception as exc:self.events.put(('failed',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def poll_printer(self):
        if self.polling:return
        self.polling=True; name=self.printer.get()
        def worker():
            try:
                self.events.put(('printer',(name,printer_snapshot(name))))
            except Exception as exc:self.events.put(('printer',(name,dict(text='Indisponível',ready=False,port='',jobs=[],error=str(exc)))))
        threading.Thread(target=worker,daemon=True).start()

    def drain(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=='line':
                    self.log_line(payload)
                    line=payload.strip()
                    if line.startswith(('Previa: ','Nova tentativa: ')):
                        self.batch=Path(line.split(': ',1)[1])
                    if line.startswith('OCR:'):self.status.configure(text='Lendo: '+line[5:])
                    elif line.startswith('Trabalho '):self.status.configure(text=line)
                elif kind in ('done','failed'):
                    self.busy=False; self.process=None; self.progress.stop()
                    if kind=='failed':self.log_line(payload)
                    success=kind=='done' and payload==0
                    self.status.configure(text='Processo concluído. Confira o lote e seu status.' if success else 'O processo parou. Veja a mensagem em Arquivos e atividade.')
                    if not success and not self.auto_operation:
                        self.tabs.select(self.details_tab)
                        messagebox.showerror('Processo interrompido','Os detalhes estão na aba Arquivos e atividade. Não reenvie um trabalho que ainda estiver na fila.',parent=self)
                    self.inputs_dirty=signature(self.folder.get())!=self.analysis_snapshot
                    self.ocr_cache={}
                    self.refresh_files(); self.refresh_history(self.batch); self.poll_printer(); self.update_actions()
                    if success and any(flag in self.operation for flag in ('--confirm-printed','--approve-pairs')):
                        self.row_filter.set('Pendentes');self.refresh_rows()
                        self.tabs.select(self.results_tab)
                elif kind=='folder':
                    if Path(payload)==Path(self.folder.get()).resolve():
                        self.stable.touch(time.monotonic());self.inputs_dirty=True
                        self.watch_label.configure(text='Alteração detectada · aguardando os arquivos…');self.update_actions()
                elif kind=='printer':
                    self.polling=False; name,result=payload
                    if name!=self.printer.get():continue
                    self.printer_ready=result['ready']
                    self.printer_badge.configure(text=f"{result['text']} · {result['port']} · {len(result['jobs'])} na fila",foreground=TEAL if self.printer_ready else '#9A5C22')
                    self.update_actions()
        except queue.Empty:pass
        self.after(100,self.drain)
        # Queue checks run separately; never block the UI with printer RPCs.
        if not hasattr(self,'next_poll'):self.next_poll=self.after(6000,self.auto_poll)

    def auto_poll(self):
        self.next_poll=self.after(6000,self.auto_poll); self.poll_printer()

    def start_monitor(self):
        if self.monitor:self.monitor.stop();self.monitor=None
        self.stable=StableChanges()
        if not self.monitor_enabled.get():
            self.watch_label.configure(text='Monitor pausado · use Analisar PDFs');return
        folder=Path(self.folder.get())
        if not folder.is_dir():
            self.watch_label.configure(text='Escolha uma pasta existente');return
        try:
            self.monitor=FolderMonitor(folder,lambda path:self.events.put(('folder',path)))
            self.watch_label.configure(text='Monitor ativo · sem impressão automática')
        except Exception as exc:
            self.watch_label.configure(text='Não foi possível iniciar o monitor');self.log_line(str(exc))

    def toggle_monitor(self):
        self.remember();self.start_monitor()

    def check_folder(self):
        try:
            if self.monitor_enabled.get() and self.monitor and not self.busy:
                snapshot=signature(self.folder.get())
                if self.stable.poll(snapshot,time.monotonic()):
                    self.refresh_files()
                    if self.folder_count:
                        self.analyze(automatic=True)
                        self.watch_label.configure(text='Arquivos estáveis · atualizando a análise…')
                    else:
                        self.inputs_dirty=False;self.refresh_history();self.update_actions()
                        self.watch_label.configure(text='Monitor ativo · aguardando novos PDFs')
                elif not self.stable.dirty:
                    self.watch_label.configure(text='Monitor ativo · atualizado')
        except OSError:
            self.watch_label.configure(text='Aguardando acesso à pasta…')
        self.after(750,self.check_folder)

    def close(self):
        if self.busy:
            messagebox.showinfo('Processo em andamento','Aguarde a análise ou o envio terminar antes de fechar. Fechar a janela não cancela um trabalho na impressora.',parent=self)
            return
        if self.monitor:self.monitor.stop();self.monitor=None
        self.remember(); self.clear_preview(); self.destroy()

if __name__=='__main__':
    try:App().mainloop()
    except Exception:
        import traceback
        DATA_DIR.mkdir(parents=True,exist_ok=True)
        (DATA_DIR/'erro-app.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
