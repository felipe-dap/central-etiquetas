import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import etiquetas as e

def page(uid, kind, name, nf='', cep=''):
    return dict(uid=uid, kind=kind, name=name, nf=nf, cep=cep, file='sample.pdf', page=0)

class MatchingTests(unittest.TestCase):
    def test_disappeared_queue_job_preserves_sources_until_confirmed(self):
        import win32print
        with TemporaryDirectory() as temp:
            root=Path(temp);batch=root/'batch';batch.mkdir()
            source=root/'a.pdf';source.write_bytes(b'pdf')
            manifest=dict(state='preview',folder=str(root),files={str(source):e.digest(source)})
            with patch.object(e,'zpl_pages',return_value=iter([b'^XA^XZ'])), \
                 patch.object(win32print,'OpenPrinter',return_value=1), \
                 patch.object(win32print,'GetPrinter',return_value=dict(pDriverName='ZD220 ZPL',Status=0)), \
                 patch.object(win32print,'StartDocPrinter',return_value=42), \
                 patch.object(win32print,'WritePrinter',side_effect=lambda h,b:len(b)), \
                 patch.object(win32print,'EndDocPrinter'),patch.object(win32print,'ClosePrinter'), \
                 patch.object(e,'wait_for_spool',return_value='removed_from_queue'),patch.object(e,'archive') as archive:
                e.submit(batch,manifest,'mock');archive.assert_not_called()
            self.assertTrue(source.exists())
            self.assertEqual(manifest['state'],'sent')

    def test_manual_confirmation_archives_without_reprinting(self):
        with TemporaryDirectory() as temp:
            work=Path(temp);batch=work/'batch';batch.mkdir()
            source=work/'a.pdf';source.write_bytes(b'pdf')
            e.save(batch/'manifest.json',dict(state='sent',folder=str(work),files={str(source):e.digest(source)}))
            with patch.object(e,'submit') as submit:
                e.confirm_printed(batch,work)
                submit.assert_not_called()
            manifest=__import__('json').loads((batch/'manifest.json').read_text())
            self.assertTrue(manifest['physical_output_verified'])
            self.assertEqual(manifest['state'],'archived')
            self.assertFalse(source.exists())

    def test_prepared_preview_prints_selected_pdf_and_not_a_new_batch(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as temp:
            work=Path(temp); batch=work/'preview'; batch.mkdir()
            original=work/'entrada.pdf'; original.write_bytes(b'original')
            pdf=batch/'ordenado.pdf'; pdf.write_bytes(b'preview-pdf')
            e.save(batch/'manifest.json',dict(state='preview',files={str(original):e.digest(original)},pages=[{}],issues=[],unmatched=[],pdf_sha256=e.digest(pdf)))
            with patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[None])),patch.object(e,'submit') as submit:
                e.print_prepared(batch,work,'mock')
            self.assertEqual(submit.call_args.args[0],batch)
            self.assertTrue(submit.call_args.args[1]['reviewed_preview'])

    def test_prepared_preview_refuses_changed_pdf(self):
        with TemporaryDirectory() as temp:
            work=Path(temp); batch=work/'preview'; batch.mkdir()
            original=work/'entrada.pdf'; original.write_bytes(b'original')
            pdf=batch/'ordenado.pdf'; pdf.write_bytes(b'preview-pdf')
            e.save(batch/'manifest.json',dict(state='preview',files={str(original):e.digest(original)},pages=[{}],issues=[],unmatched=[],pdf_sha256=e.digest(pdf)))
            pdf.write_bytes(b'alterado')
            with patch.object(e,'submit') as submit:
                with self.assertRaisesRegex(ValueError,'alterada'):e.print_prepared(batch,work,'mock')
                submit.assert_not_called()

    def test_prepared_preview_refuses_files_already_sent_in_another_batch(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as temp:
            work=Path(temp); batch=work/'preview'; batch.mkdir()
            original=work/'entrada.pdf'; original.write_bytes(b'original')
            pdf=batch/'ordenado.pdf'; pdf.write_bytes(b'preview-pdf')
            files={str(original):e.digest(original)}
            e.save(batch/'manifest.json',dict(state='preview',files=files,pages=[{}],issues=[],unmatched=[],pdf_sha256=e.digest(pdf)))
            previous=work/'sent'; previous.mkdir()
            e.save(previous/'manifest.json',dict(state='sent',files=files))
            with patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[None])),patch.object(e,'submit') as submit:
                with self.assertRaisesRegex(ValueError,'ja enviados'):e.print_prepared(batch,work,'mock')
                submit.assert_not_called()

    def test_zpl_graphic_fields_respect_byte_limit_and_preserve_bitmap(self):
        import re
        bits=bytes(range(256))*468+bytes(range(192))
        self.assertEqual(len(bits),120000)
        zpl=e.bitmap_zpl(bits)
        fields=re.findall(rb'\^FO0,(\d+)\^GFA,(\d+),(\d+),(\d+),([A-F0-9]+)\^FS',zpl)
        self.assertEqual(len(fields),2)
        reconstructed=bytearray(120000)
        for y,b,c,stride,data in fields:
            self.assertLessEqual(int(b),99999)
            band=bytes.fromhex(data.decode())
            self.assertEqual(len(band),int(b))
            self.assertEqual(b,c)
            offset=int(y)*int(stride)
            reconstructed[offset:offset+len(band)]=band
        self.assertEqual(bytes(reconstructed),bits)
        self.assertEqual(zpl.count(b'^XA'),1)
        self.assertEqual(zpl.count(b'^XZ'),1)

    def test_reprint_creates_new_attempt_without_changing_old_manifest(self):
        import win32print
        with TemporaryDirectory() as temp:
            work=Path(temp); source=work/'original'; source.mkdir()
            (source/'ordenado.pdf').write_bytes(b'pdf-test')
            e.save(source/'manifest.json',dict(state='sent',folder=str(work),files={},pages=[{}],issues=[],unmatched=[],job_id=9))
            before=(source/'manifest.json').read_bytes()
            from types import SimpleNamespace
            with patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[None])), \
                 patch.object(win32print,'OpenPrinter',return_value=1), \
                 patch.object(win32print,'ClosePrinter'), \
                 patch.object(win32print,'EnumJobs',return_value=[]), \
                 patch.object(e,'submit') as submit:
                e.reprint_batch(source,work,'mock')
            self.assertEqual((source/'manifest.json').read_bytes(),before)
            batch,manifest,_=submit.call_args.args
            self.assertNotEqual(batch,source)
            self.assertEqual(manifest['previous_job_id'],9)
            self.assertEqual(manifest['reprint_of'],str(source))
            self.assertEqual((batch/'ordenado.pdf').read_bytes(),b'pdf-test')

    def test_reprint_refuses_nonempty_queue(self):
        import win32print
        with TemporaryDirectory() as temp:
            work=Path(temp); source=work/'original'; source.mkdir()
            (source/'ordenado.pdf').write_bytes(b'pdf-test')
            e.save(source/'manifest.json',dict(state='sent',folder=str(work),files={},pages=[{}],issues=[],unmatched=[]))
            from types import SimpleNamespace
            with patch('pypdf.PdfReader',return_value=SimpleNamespace(pages=[None])), \
                 patch.object(win32print,'OpenPrinter',return_value=1), \
                 patch.object(win32print,'ClosePrinter'), \
                 patch.object(win32print,'EnumJobs',return_value=[{'JobId':9}]), \
                 patch.object(e,'submit') as submit:
                with self.assertRaisesRegex(ValueError,'vazia'): e.reprint_batch(source,work,'mock')
                submit.assert_not_called()
            self.assertEqual(len(list(work.iterdir())),1)

    def test_olist_shipping_embedded_danfe_and_nf_before_name(self):
        result=e.identify(['olist','Magalog','1/1 volumes','DESTINATÁRIO','NF 11794',
                           'Juliana Kaminaga','05642-010 - Sao Paulo-SP','REMETENTE',
                           'Empresa','DANFE SIMPLIFICADA','NF 11794'])
        self.assertEqual((result['kind'],result['name'],result['nf'],result['cep']),
                         ('envio','Juliana Kaminaga','11794','05642010'))

    def test_cep_split_over_lines(self):
        result=e.identify(['DANFE SIMPLIFICADO','DESTINATÁRIO','Lilian Rosário',
                           'Rua Um. 07.865-','028 Franco da Rocha','TOTAL'])
        self.assertEqual(result['cep'],'07865028')

    def test_simplificado_prefers_delivery_name_and_cep(self):
        result=e.identify(['DANFE SIMPLIFICADO','NÚMERO 011787','DESTINATÁRIO',
                           'Empresa Fiscal Ltda','Rua Fiscal, 10','88040-002 Florianopolis',
                           'INFORMAÇÕES DO LOCAL DE ENTREGA','NOME / RAZÃO SOCIAL',
                           'Fernanda Sodré','Rua Maranhao, 227','01.240-001 Sao Paulo',
                           'DADOS DOS PRODUTOS','TOTAL'])
        self.assertEqual((result['kind'],result['layout'],result['name'],result['cep']),
                         ('nf','simplificado','Fernanda Sodré','01240001'))
        self.assertEqual(result['fiscal_name'],'Empresa Fiscal Ltda')
        envio=page('envio','envio','Fernanda Sodré','11787','01240001')
        nf=dict(result,uid='nf',file='test.pdf',page=0)
        ordered, unmatched, issues=e.arrange([envio,nf])
        self.assertEqual([p['uid'] for p in ordered],['nf','envio'])
        self.assertFalse(unmatched or issues)

    def test_delivery_block_takes_precedence_even_if_first(self):
        result=e.identify(['DANFE SIMPLIFICADO','LOCAL DE ENTREGA','Ana Silva',
                           '12345-678','DESTINATÁRIO / REMETENTE','Empresa Fiscal','88040-002'])
        self.assertEqual((result['name'],result['cep']),('Ana Silva','12345678'))

    def test_unreadable_delivery_does_not_fall_back_to_fiscal(self):
        result=e.identify(['DANFE SIMPLIFICADO','DESTINATÁRIO','Empresa Fiscal',
                           'LOCAL DE ENTREGA','ENDEREÇO','Rua Um, 10','12345-678'])
        self.assertEqual(result['name'],'')
        self.assertEqual(result['name_source'],'delivery')

    def test_without_delivery_uses_fiscal_recipient(self):
        result=e.identify(['DANFE SIMPLIFICADO','DESTINATÁRIO','Ana Silva','12345-678',
                           'REMETENTE','Empresa','88040-002'])
        self.assertEqual((result['name'],result['cep']),('Ana Silva','12345678'))

    def test_sample_carrier_logo_and_phone(self):
        self.assertEqual(e.identify(['NF: 011787','DESTINATÁRIO','Correios','Fernanda Sodré','01.240-001 São Paulo/SP'])['name'], 'Fernanda Sodré')
        result = e.identify(['NF 11785','DESTINATÁRIO','Ivan Mumic Silva, Tel: (19) 99305-4970','13023-191 Campinas/SP'])
        self.assertEqual((result['name'], result['nf'], result['cep']), ('Ivan Mumic Silva','11785','13023191'))

    def test_pair_and_alphabetize(self):
        data=[page('1','nf','Zélia','2'),page('2','envio','Ána','1'),page('3','nf','Ana','1')]
        ordered, unmatched, issues=e.arrange(data)
        self.assertEqual([p['uid'] for p in ordered], ['3','2','1'])
        self.assertEqual((unmatched,issues),([],[]))

    def test_different_invoice_never_falls_back_to_name(self):
        data=[page('1','nf','Ana','1','12345678'),page('2','envio','Ana','2','12345678')]
        _, unmatched, issues=e.arrange(data)
        self.assertEqual(len(unmatched),1)
        self.assertTrue(issues)

    def test_ambiguous_duplicate_invoices(self):
        data=[page('1','nf','Ana','1'),page('2','nf','Ana','1'),page('3','envio','Ana','1')]
        _, unmatched, issues=e.arrange(data)
        self.assertEqual(len(unmatched),1)
        self.assertTrue(issues)

    def test_same_customer_different_invoices_stays_with_correct_invoice(self):
        data=[page('n2','nf','Ana','2'),page('e1','envio','Ana','1'),page('n1','nf','Ana','1'),page('e2','envio','Ana','2')]
        ordered, unmatched, issues=e.arrange(data)
        self.assertEqual([p['uid'] for p in ordered],['n1','e1','n2','e2'])
        self.assertFalse(unmatched or issues)

    def test_name_cep_unique_fallback(self):
        data=[page('1','nf','Ana','1','12345678'),page('2','envio','Ana','','12345678')]
        ordered, unmatched, issues=e.arrange(data)
        self.assertEqual(len(ordered),2)
        self.assertFalse(unmatched or issues)

    def test_archive_changed_file_moves_nothing(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); batch=root/'batch'; batch.mkdir()
            source=root/'a.pdf'; source.write_bytes(b'changed')
            e.save(batch/'manifest.json',dict(state='sent',folder=str(root),files={str(source):'wronghash'}))
            with self.assertRaises(ValueError): e.archive(batch)
            self.assertTrue(source.exists())

    def test_archive_is_recoverable(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); batch=root/'batch'; batch.mkdir()
            source=root/'a.pdf'; source.write_bytes(b'pdf')
            e.save(batch/'manifest.json',dict(state='sent',folder=str(root),files={str(source):e.digest(source)}))
            e.archive(batch)
            self.assertFalse(source.exists())
            self.assertEqual((root/'impressos'/'batch'/'a.pdf').read_bytes(),b'pdf')

    def test_spool_error_does_not_report_success(self):
        import win32print
        with patch.object(win32print,'EnumJobs',return_value=[dict(JobId=7,Status=win32print.JOB_STATUS_ERROR)]):
            with self.assertRaises(ValueError): e.wait_for_spool(None,7)

    def test_submit_success_archives_and_records_job(self):
        import win32print
        with TemporaryDirectory() as temp:
            root=Path(temp); batch=root/'batch'; batch.mkdir()
            source=root/'a.pdf'; source.write_bytes(b'pdf')
            manifest=dict(state='preview',folder=str(root),files={str(source):e.digest(source)})
            with patch.object(e,'zpl_pages',return_value=iter([b'^XA^XZ'])), \
                 patch.object(win32print,'OpenPrinter',return_value=1), \
                 patch.object(win32print,'GetPrinter',return_value=dict(pDriverName='ZD220 ZPL',Status=0)), \
                 patch.object(win32print,'StartDocPrinter',return_value=42), \
                 patch.object(win32print,'WritePrinter',side_effect=lambda h,b:len(b)), \
                 patch.object(win32print,'EndDocPrinter'), \
                 patch.object(win32print,'ClosePrinter'), \
                 patch.object(e,'wait_for_spool',return_value='spooler_completed'):
                e.submit(batch,manifest,'mock')
            self.assertFalse(source.exists())
            self.assertEqual(__import__('json').loads((batch/'manifest.json').read_text())['state'],'archived')

    def test_partial_submission_preserves_sources_and_blocks_retry(self):
        import win32print
        with TemporaryDirectory() as temp:
            root=Path(temp); batch=root/'batch'; batch.mkdir()
            source=root/'a.pdf'; source.write_bytes(b'pdf')
            manifest=dict(state='preview',folder=str(root),files={str(source):e.digest(source)})
            with patch.object(e,'zpl_pages',return_value=iter([b'^XA^XZ'])), \
                 patch.object(win32print,'OpenPrinter',return_value=1), \
                 patch.object(win32print,'GetPrinter',return_value=dict(pDriverName='ZD220 ZPL',Status=0)), \
                 patch.object(win32print,'StartDocPrinter',return_value=42), \
                 patch.object(win32print,'WritePrinter',return_value=1), \
                 patch.object(win32print,'ClosePrinter'):
                with self.assertRaises(IOError): e.submit(batch,manifest,'mock')
            self.assertTrue(source.exists())
            self.assertEqual(__import__('json').loads((batch/'manifest.json').read_text())['state'],'uncertain')

if __name__=='__main__': unittest.main()
