import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from pypdf import PdfWriter,PdfReader
from pypdf.generic import DecodedStreamObject,NameObject
from etiquetas import digest,save,write_pdf,archive
from approval import prepare_pairs,archive_pairs,approvable_pairs,stage_existing_pairs,export_pairs

def make_pdf(path,labels):
    writer=PdfWriter()
    for label in labels:
        page=writer.add_blank_page(width=100*72/25.4,height=150*72/25.4)
        content=DecodedStreamObject();content.set_data(('q Q % '+label).encode())
        page[NameObject('/Contents')]=writer._add_object(content)
    writer.write(path)

def fixture(root):
    work=root/'_processamento';source=work/'preview';source.mkdir(parents=True)
    nfs=root/'notas.pdf';ships=root/'envios.pdf'
    make_pdf(nfs,['nf1','nf2','nf3']);make_pdf(ships,['envio1','envio2'])
    files={str(f):digest(f) for f in (nfs,ships)}
    pages=[]
    for i,name in enumerate(['Ana','Bia','Carlos']):
        nf=str(i+1)
        pages.append(dict(uid=f'n{i}',kind='nf',nf=nf,name=name,file=str(nfs),page=i,sha256=files[str(nfs)],ecommerce_order=str(i+100)))
        if i<2:pages.append(dict(uid=f'e{i}',kind='envio',nf=nf,name=name,file=str(ships),page=i,sha256=files[str(ships)],match='numero_nf'))
    write_pdf(pages,source/'ordenado.pdf')
    save(source/'manifest.json',dict(state='preview',folder=str(root),files=files,pages=pages,unmatched=[],issues=[],pdf_sha256=digest(source/'ordenado.pdf')))
    return work,source,nfs,ships

class ApprovalTests(unittest.TestCase):
    def test_pdf_export_preserves_inputs_and_state_and_excludes_unpaired(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,nfs,ships=fixture(root)
            before={p:p.read_bytes() for p in (nfs,ships,source/'manifest.json')}
            target=root/'exportados'/'pares.pdf';target.parent.mkdir()
            self.assertEqual(export_pairs(source,target),(2,4))
            pages=PdfReader(target).pages
            self.assertEqual([p.get_contents().get_data() for p in pages],[b'q Q % nf1',b'q Q % envio1',b'q Q % nf2',b'q Q % envio2'])
            for p,content in before.items():self.assertEqual(p.read_bytes(),content)
            self.assertEqual(list(work.iterdir()),[source])
            self.assertAlmostEqual(float(pages[0].mediabox.width)*25.4/72,100,places=3)
            self.assertAlmostEqual(float(pages[0].mediabox.height)*25.4/72,150,places=3)
            self.assertEqual(export_pairs(source,target,{'n0':'confirmed'}),(1,2))
            with self.assertRaises(ValueError):export_pairs(source,nfs)
            nfs.unlink()
            with self.assertRaises(ValueError):export_pairs(source,target)

    def test_confirmed_legacy_reprint_exports_results_without_moving_sources_again(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,batch,nfs,ships=fixture(root)
            manifest=json.loads((batch/'manifest.json').read_text())
            manifest.update(state='archived',physical_output_verified=True,reprint_of='older-batch')
            destination=root/'impressos'/batch.name;destination.mkdir(parents=True)
            nfs.rename(destination/nfs.name);ships.rename(destination/ships.name)
            staged=stage_existing_pairs(batch,manifest)
            self.assertEqual(len(staged['result_files']),2)
            archive_pairs(batch,staged)
            self.assertFalse(list(root.glob('*.pdf')))
            self.assertEqual(len(list((root/'resultados'/batch.name).glob('*.pdf'))),2)
            final=json.loads((batch/'manifest.json').read_text())
            self.assertTrue(final['physical_output_verified'])
            self.assertEqual(final['state'],'archived')

    def test_preparation_prints_only_complete_pairs_and_does_not_move_sources(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,nfs,ships=fixture(root)
            before={f:digest(f) for f in (nfs,ships)}
            batch,data=prepare_pairs(source,work)
            self.assertEqual(len(data['pages']),4)
            self.assertEqual(len(data['result_files']),2)
            self.assertEqual(len(PdfReader(batch/'ordenado.pdf').pages),4)
            self.assertEqual({f:digest(f) for f in before},before)
            self.assertFalse((root/'resultados').exists())
            remaining=[e for e in data['archive_plan'] if e['remaining']]
            self.assertEqual(len(remaining),1)
            self.assertEqual(PdfReader(remaining[0]['remaining']).pages[0].get_contents().get_data(),b'q Q % nf3')
            for record in data['result_files']:
                self.assertEqual(len(PdfReader(batch/'pares'/record['filename']).pages),2)

    def test_success_archives_originals_publishes_pairs_and_keeps_only_pending_pages(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,nfs,ships=fixture(root)
            batch,data=prepare_pairs(source,work);data['state']='sent';save(batch/'manifest.json',data)
            archive(batch)
            result=json.loads((batch/'manifest.json').read_text())
            self.assertEqual(result['state'],'archived')
            self.assertFalse(ships.exists())
            self.assertEqual(len(PdfReader(nfs).pages),1)
            self.assertEqual(PdfReader(nfs).pages[0].get_contents().get_data(),b'q Q % nf3')
            self.assertEqual(len(PdfReader(root/'impressos'/batch.name/'notas.pdf').pages),3)
            self.assertEqual(len(list((root/'resultados'/batch.name).glob('*.pdf'))),2)
            for record in result['result_files']:self.assertTrue(Path(record['path']).exists())
            # Resume is idempotent: no overwriting the pending document or results.
            before=digest(nfs);archive_pairs(batch,result);self.assertEqual(digest(nfs),before)

    def test_changed_source_prevents_all_moves(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,nfs,ships=fixture(root)
            batch,data=prepare_pairs(source,work);data['state']='sent'
            ships.write_bytes(b'changed')
            with self.assertRaises(ValueError):archive_pairs(batch,data)
            self.assertTrue(nfs.exists());self.assertTrue(ships.exists())
            self.assertFalse((root/'impressos'/batch.name/'notas.pdf').exists())

    def test_recover_after_first_original_moved_restores_remainder(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,nfs,ships=fixture(root)
            batch,data=prepare_pairs(source,work);data['state']='archiving'
            dest=root/'impressos'/batch.name;dest.mkdir(parents=True)
            nfs.rename(dest/nfs.name)
            save(batch/'manifest.json',data);archive(batch)
            self.assertEqual(len(PdfReader(nfs).pages),1)
            self.assertFalse(ships.exists())

    def test_all_paired_leaves_input_empty(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,nfs,ships=fixture(root)
            # Add a matching shipping page for the last NF.
            make_pdf(ships,['envio1','envio2','envio3'])
            data=json.loads((source/'manifest.json').read_text())
            data['files'][str(ships)]=digest(ships)
            for p in data['pages']:
                if p['kind']=='envio':p['sha256']=digest(ships)
            data['pages'].append(dict(uid='e2',kind='envio',nf='3',name='Carlos',file=str(ships),page=2,sha256=digest(ships),match='numero_nf'))
            write_pdf(data['pages'],source/'ordenado.pdf');data['pdf_sha256']=digest(source/'ordenado.pdf');save(source/'manifest.json',data)
            batch,prepared=prepare_pairs(source,work);prepared['state']='sent';save(batch/'manifest.json',prepared);archive(batch)
            self.assertFalse(list(root.glob('*.pdf')))
            self.assertEqual(len(list((root/'resultados'/batch.name).glob('*.pdf'))),3)

    def test_invalid_or_already_sent_pair_is_not_approvable(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);work,source,_,_=fixture(root)
            data=json.loads((source/'manifest.json').read_text())
            self.assertEqual(len(approvable_pairs(data)),2)
            self.assertEqual(len(approvable_pairs(data,{'n0':'archived'})),1)
            data['pages'][1]['name']='Outro destinatario'
            self.assertEqual(len(approvable_pairs(data)),1)

if __name__=='__main__':unittest.main()
