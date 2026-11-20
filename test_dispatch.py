import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from watchdog.events import FileCreatedEvent,FileModifiedEvent,FileMovedEvent
from folder_monitor import StableChanges,PdfHandler,FolderMonitor
from document_data import dispatch_metadata,shipping_data,ecommerce_order,supplement_items
from list_data import grouped_rows,effective_states

def invoice(*product_lines,tail=None):
    return ['DANFE SIMPLIFICADO','CÓD. DESCRIÇÃO','UN','QTD','V.UNIT V.TOTAL',
            *product_lines,'TOTAL DA NFE: 199,80','DADOS ADICIONAIS',
            'Nota fiscal referente ao pedido de número 11794. Guarde este número para o caso de precisar entrar em',
            'contato conosco a respeito desta venda.',*(tail or [])]

class MetadataTests(unittest.TestCase):
    def test_enlarged_reading_recovers_corrupted_price(self):
        data=dispatch_metadata(invoice('DF071 Jogo de Ludo','peça','1','00000666','99,90','DF021 Sudoku','peça','1','269,900000','269,90'),'nf','simplificado')
        self.assertTrue(data['quantity_review'])
        supplement_items(data,invoice('DF071 Jogo de Ludo','peça','1','99,900000','99,90','DF021 Sudoku','peça','1','269,900000','269,90'))
        self.assertEqual([i['quantity'] for i in data['items']],['1','1'])
        self.assertFalse(data['quantity_review'] or data['quantity_alerts'])

    def test_second_reading_cannot_replace_different_items_or_conflict(self):
        original=invoice('DF071 Ludo','peça','1','00000666','99,90','DF021 Sudoku','peça','1','269,900000','269,90')
        for second in [invoice('DF999 Outro','peça','1','99,900000','99,90'),
                       invoice('DF071 Ludo','peça','1','99,900000','99,90','DF021 Sudoku','peça','2','269,900000','539,80')]:
            data=dispatch_metadata(original,'nf','simplificado')
            supplement_items(data,second)
            self.assertTrue(data['quantity_review'])

    def test_wrapped_sku_unit_and_prices_from_helena_invoice(self):
        lines=invoice('DF09 Quebra-cabeca 1000 Pecas,','peç','189,9000','1','189,90','2','Pequenos Encontros','a','00',
                      'DF14 Quebra-cabeca 1000 Pecas,','peç','1','179,9000','179,90','4','Domingo no Parque','a','00')
        data=dispatch_metadata(lines,'nf','simplificado')
        self.assertEqual([item['quantity'] for item in data['items']],['1','1'])
        self.assertFalse(data['quantity_review'] or data['quantity_alerts'])

    def test_wrapped_inline_unit_still_alerts_for_two(self):
        data=dispatch_metadata(invoice('DF14 Quebra-cabeca 1000 Pecas, Lado peç','99,90000','2','199,80','3','A, Lado B','a','0'),'nf','simplificado')
        self.assertEqual(data['items'][0]['quantity'],'2')
        self.assertTrue(data['quantity_alerts'])
        self.assertFalse(data['quantity_review'])

    def test_wrapped_conflicting_or_missing_quantity_requires_review(self):
        for columns in [('99,9000','2','99,90'),('99,9000','99,90')]:
            with self.subTest(columns=columns):
                data=dispatch_metadata(invoice('DF14 Produto','peç',*columns,'3','Descricao','a','00'),'nf','simplificado')
                self.assertIsNone(data['items'][0]['quantity'])
                self.assertTrue(data['quantity_review'])

    def test_ecommerce_order_from_standard_sentence(self):
        self.assertEqual(ecommerce_order(['Nota fiscal referente ao pedido de número 11720. Guarde este número.']),'11720')
        self.assertEqual(ecommerce_order(['Nota fiscal referente ao pedido','de número 0011720. Guarde este número.']),'0011720')

    def test_order_from_enlarged_ocr_with_damaged_word_numero(self):
        self.assertEqual(ecommerce_order(['Nota fiscar relerente ao pedido de fumiero 11720. Guarde este furero']),'11720')

    def test_missing_order_never_uses_invoice_or_tracking(self):
        self.assertEqual(ecommerce_order(['NF 11794','AE172677258BR','Pedido não encontrado']), '')

    def test_two_identical_puzzles_alerts_by_item_quantity(self):
        lines=invoice('DF143 Quebra-cabeca 1000 Pecas','peça','2 99,900000','199,80')
        data=dispatch_metadata(lines,'nf','simplificado')
        self.assertEqual(data['items'][0]['quantity'],'2')
        self.assertEqual(len(data['quantity_alerts']),1)
        self.assertFalse(data['quantity_review'])

    def test_multiple_different_items_at_one_does_not_alert(self):
        lines=invoice('DF143 Quebra-cabeca 1000 Pecas','peça','1 99,900000','99,90',
                      'DF144 Quebra-cabeca 2000 Pecas','peça','1 99,900000','99,90')
        data=dispatch_metadata(lines,'nf','simplificado')
        self.assertEqual(len(data['items']),2)
        self.assertFalse(data['quantity_alerts'] or data['quantity_review'])

    def test_missing_quantity_recovered_by_prices(self):
        data=dispatch_metadata(invoice('DF143 Quebra-cabeca 1000 Pecas','peça','99,900000','199,80'),'nf','simplificado')
        self.assertEqual(data['items'][0]['quantity'],'2')
        self.assertTrue(data['quantity_alerts'])

    def test_malformed_quantity_requires_review_not_default_one(self):
        data=dispatch_metadata(invoice('DF143 Quebra-cabeca','peça','2 99,900000','99,90'),'nf','simplificado')
        self.assertIsNone(data['items'][0]['quantity'])
        self.assertTrue(data['quantity_review'])

    def test_decimal_quantity_not_equal_one_alerts(self):
        data=dispatch_metadata(invoice('DF143 Produto','peça','0,5 100,000000','50,00'),'nf','simplificado')
        self.assertTrue(data['quantity_alerts'])

    def test_notes_after_standard_sentence_only(self):
        data=dispatch_metadata(invoice('DF143 Produto','peça','1 99,900000','99,90',tail=['Embrulhar para presente.','Enviar sem preço.']),'nf','simplificado')
        self.assertEqual(data['observations'],'Embrulhar para presente.\nEnviar sem preço.')
        self.assertFalse(data['observation_review'])

    def test_normal_footer_is_not_customer_observation(self):
        data=dispatch_metadata(invoice('DF143 Produto','peça','1 99,900000','99,90'),'nf','simplificado')
        self.assertFalse(data['observations'] or data['observation_review'])

    def test_missing_observation_marker_needs_review(self):
        data=dispatch_metadata(['DANFE SIMPLIFICADO','DADOS ADICIONAIS','texto ilegivel'],'nf','simplificado')
        self.assertTrue(data['observation_review'])

    def test_tracking_formats(self):
        cases=[(['Correios','SEDEX','AE 172 677 258 BR','DESTINATÁRIO'],'AE172677258BR'),
               (['olist','Jadlog','10712103827886','DESTINATÁRIO'],'10712103827886'),
               (['olist','Magalog','GFL4MXZK9FRYKG','DESTINATÁRIO'],'GFL4MXZK9FRYKG'),
               (['Loggi','melhor envio','ME262G95U37BR','DESTINATÁRIO'],'ME262G95U37BR')]
        for lines,expected in cases:
            with self.subTest(expected=expected):
                data=shipping_data(lines,'envio')
                self.assertEqual(data['tracking'],expected)
                self.assertTrue(data['carrier'])

class WatchTests(unittest.TestCase):
    def test_burst_waits_for_stability_and_runs_once(self):
        stable=StableChanges(delay=3);first=(('a.pdf',10,1),);second=(('a.pdf',20,2),)
        self.assertFalse(stable.poll(first,0))
        self.assertFalse(stable.poll(second,2))
        self.assertFalse(stable.poll(second,4))
        self.assertTrue(stable.poll(second,5))
        self.assertFalse(stable.poll(second,20))
        stable.touch(21)
        self.assertFalse(stable.poll(second,30))

    def test_partial_download_blocks_analysis(self):
        stable=StableChanges(delay=3);partial=(('a.pdf.crdownload',10,1),)
        stable.poll(partial,0)
        self.assertFalse(stable.poll(partial,20))
        complete=(('a.pdf',10,2),)
        self.assertFalse(stable.poll(complete,21))
        self.assertTrue(stable.poll(complete,24))

    def test_handler_ignores_outputs_and_recognizes_rename(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);received=[];handler=PdfHandler(root,received.append)
            handler.on_any_event(FileCreatedEvent(str(root/'_processamento'/'output.pdf')))
            handler.on_any_event(FileModifiedEvent(str(root/'impressos'/'input.pdf')))
            self.assertFalse(received)
            handler.on_any_event(FileMovedEvent(str(root/'a.tmp'),str(root/'a.pdf')))
            self.assertEqual(received,[str(root.resolve())])

    def test_real_watchdog_observes_file_creation(self):
        with TemporaryDirectory() as temp:
            event=threading.Event();monitor=FolderMonitor(temp,lambda _:event.set())
            try:
                (Path(temp)/'sample.pdf').write_bytes(b'test')
                self.assertTrue(event.wait(4),'Watchdog nao notificou a criacao')
            finally:monitor.stop()

class GroupTests(unittest.TestCase):
    def test_physical_confirmation_is_printed_not_just_sent(self):
        page=dict(uid='x',kind='nf',nf='1',name='Ana')
        states=effective_states([(None,dict(state='archived',physical_output_verified=True,pages=[page]),2)])
        self.assertEqual(grouped_rows(dict(state='preview',pages=[page]),states)[0]['status'],'Impresso')

    def test_one_row_has_two_document_refs_and_shipping_data(self):
        nf=dict(uid='n',kind='nf',nf='11794',name='Juliana Kaminaga',ecommerce_order='11720',observations='Presente',items=[],quantity_alerts=[])
        ship=dict(uid='s',kind='envio',nf='11794',name='Juliana Kaminaga',carrier='Jadlog',tracking='10712103827886')
        rows=grouped_rows(dict(state='preview',pages=[nf,ship],unmatched=[]))
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['nfs'][0]['index'],rows[0]['ships'][0]['index']),(0,1))
        self.assertEqual(rows[0]['tracking'],'10712103827886')
        self.assertEqual(rows[0]['ecommerce_order'],'11720')
        self.assertIn('Observações',rows[0]['alerts'])
        self.assertEqual(rows[0]['status'],'Pendente')

    def test_latest_sent_status_overrides_older_archived(self):
        page=dict(uid='x',kind='nf',nf='1',name='Ana')
        states=effective_states([(None,dict(state='sent',pages=[page]),2),(None,dict(state='archived',pages=[page]),1)])
        self.assertEqual(grouped_rows(dict(state='preview',pages=[page]),states)[0]['status'],'Enviado · conferir')

    def test_same_customer_different_orders_stays_in_two_rows(self):
        pages=[dict(uid='a',kind='nf',nf='1',name='Ana'),dict(uid='b',kind='nf',nf='2',name='Ana')]
        self.assertEqual(len(grouped_rows(dict(state='archived',pages=pages))),2)

if __name__=='__main__':unittest.main()
