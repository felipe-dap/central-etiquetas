"""Independent PDF preview for the selected customer's documents only."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path

class PdfPreview(ttk.Frame):
    def __init__(self,parent,title,on_error):
        super().__init__(parent,style='Card.TFrame',padding=8)
        self.on_error=on_error;self.document=None;self.path=None;self.image=None
        self.refs=[];self.position=0;self.render_after=None;self.empty_text='Selecione um cliente/pedido'
        header=ttk.Frame(self,style='Card.TFrame');header.pack(fill='x')
        ttk.Label(header,text=title,style='Card.TLabel',font=('Segoe UI Semibold',10)).pack(side='left')
        self.counter=ttk.Label(header,text='—',style='Card.TLabel');self.counter.pack(side='right',padx=5)
        self.canvas=tk.Canvas(self,bg='#E7EDEF',highlightthickness=0,width=280,height=330)
        self.canvas.pack(fill='both',expand=True,pady=(8,0));self.canvas.bind('<Configure>',lambda e:self.schedule_render())
        self.set_documents(None,[])

    def set_documents(self,batch,refs):
        self.total_documents=len(refs)
        self.refs=[dict(ref,path=Path(batch)/ref['file']) for ref in refs[:1]] if batch else []
        self.position=0;self.show_current()

    def show_current(self):
        if not self.refs:
            self.release_document();self.empty_text='Documento não disponível';self.render();return
        ref=self.refs[self.position]
        try:
            if self.path!=ref['path']:
                self.release_document()
                import pypdfium2
                self.document=pypdfium2.PdfDocument(str(ref['path']));self.path=ref['path']
            if not 0<=ref['index']<len(self.document):raise ValueError('Página fora do PDF')
            self.render()
        except Exception as exc:
            self.release_document();self.empty_text='Não foi possível abrir este documento';self.render();self.on_error(str(exc))

    def release_document(self):
        if self.document:self.document.close()
        self.document=None;self.path=None;self.image=None

    def clear(self):
        if self.render_after:self.after_cancel(self.render_after);self.render_after=None
        self.refs=[];self.release_document();self.empty_text='Selecione um cliente/pedido';self.render()

    def schedule_render(self):
        if self.render_after:self.after_cancel(self.render_after)
        self.render_after=self.after(100,self.render)

    def render(self):
        self.render_after=None
        self.canvas.delete('all')
        width=max(80,self.canvas.winfo_width());height=max(120,self.canvas.winfo_height())
        if not self.document:
            self.counter.configure(text='—');self.canvas.create_text(width/2,height/2,text=self.empty_text,width=max(70,width-20),fill='#60747A',font=('Segoe UI',10));return
        page=bitmap=None
        try:
            from PIL import ImageTk
            page=self.document[self.refs[self.position]['index']]
            scale=min((width-16)/page.get_width(),(height-16)/page.get_height())
            bitmap=page.render(scale=max(.1,scale))
            self.image=ImageTk.PhotoImage(bitmap.to_pil())
            self.canvas.create_image(width/2,height/2,image=self.image)
            self.counter.configure(text=f'Primeira de {self.total_documents}' if self.total_documents>1 else '')
        except Exception as exc:self.on_error(f'Erro na prévia: {exc}')
        finally:
            if bitmap:bitmap.close()
            if page:page.close()
