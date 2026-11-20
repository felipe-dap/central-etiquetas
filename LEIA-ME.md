# Central de etiquetas — Dear Friends

App local para a Zebra ZD220, com papel de 100 × 150 mm.

## Aprovar e imprimir

1. Salve os DANFEs em modo **Simplificado** e as etiquetas das transportadoras na pasta **Impressões**.
2. O monitor aguarda a gravação dos arquivos e atualiza a lista, sem imprimir sozinho.
3. A **lista ocupa a esquerda em toda a altura**, mostrando mais linhas. Selecione o cliente/pedido para conferir as **previas na coluna da direita: NF e envio lado a lado**. A divisoria pode ser arrastada para dar mais largura a lista ou as previas. Cada painel mostra apenas o primeiro documento, sem navegador. O lote inclui todos os documentos associados ao par.
4. Clique em **Aprovar e imprimir pares**. A confirmação informa quantos pares e páginas serão enviados à Zebra. Apenas pares completos e válidos entram. Documentos sem par ou com associação divergente continuam pendentes.
5. Depois de o driver confirmar a conclusão, o app arquiva os originais e publica um PDF por par na aba **Resultados**. O PDF contém a NF seguida da(s) etiqueta(s) de envio.

A lista abre em **Pendentes**. Ao concluir ou confirmar uma impressão, os itens impressos saem dessa visão, as prévias são limpas quando não houver mais pendências, e os PDFs concluídos ficam na aba Resultados. Os filtros Todos / Impressos permitem consultar os itens antigos sem apagar o histórico. Itens concluídos não ficam amarelos por alertas antigos. O filtro muda a lista, não os pares aprovados. Alertas de observações ou quantidade aparecem na confirmação; clique duas vezes numa linha com alerta para ler os detalhes. A impressora é fixa: Zebra ZD220.

## Onde ficam os arquivos

- **Impressões\resultados\2026-11-17-17h46m27s\**: um PDF por cliente/NF, com nome que inclui NF e pedido do e-commerce.
- **Impressões\impressos\2026-11-17-17h46m27s\**: os arquivos originais completos, preservados como cópia de segurança.
- **Impressões\_processamento\**: prévias, registro das aprovações e tentativas, OCR e arquivos preparados. Não é pasta de entrada.
- **Impressões\**: apenas PDFs novos e documentos ainda pendentes. Se o original tiver páginas impressas e não impressas, o app arquiva o original completo e recoloca na entrada um PDF de mesmo nome com **somente as páginas pendentes**. Arquivos que não participaram de nenhum par aprovado ficam intactos.

Exemplo: um PDF contém três NFs, mas só há etiquetas de envio para duas. O app imprime os dois pares, salva dois PDFs em resultados, guarda o PDF original de três NFs em impressos e deixa na entrada um PDF contendo somente a terceira NF.

As subpastas impressos, resultados e _processamento são ignoradas pelo monitor. Não misturam os pares concluídos com os próximos lotes.

## Conclusão, falhas e reimpressão

**Pendente**: ainda não enviado. **Enviado — conferir**: tentativa registrada, sem confirmação suficiente. **Impresso (fila)**: driver confirmou a conclusão. **Impresso**: usuário confirmou que todas as páginas saíram corretamente.

Se o trabalho apenas desaparecer da fila, o Windows pode não distinguir impressão de cancelamento. Nesse caso, os originais ficam na entrada e o app pede **Confirmar impresso** no histórico após conferir a saída física. A confirmação arquiva os originais e publica os resultados, sem reenviar nada. O mesmo botão permite terminar um arquivamento interrompido.

Falha de impressão não move os originais. A tentativa é preservada e bloqueia reenvio automático. Para outra cópia, use **Reimprimir selecionado** no histórico, com a fila vazia. Isso reenvia o lote inteiro e pode repetir páginas que já saíram. Não apague manifest.json nem o ZPL.

Arquivamento com pendências é retomável: os PDFs completos e os remanescentes são preparados e validados antes de mover os originais. Nenhum download novo é sobrescrito. Se houver divergência, o app para para revisão.

## Leitura e associação

- Uma linha por NF/pedido, em ordem alfabética pelo cliente de entrega.
- Local de entrega da NF tem prioridade sobre destinatário fiscal. Se o bloco existir mas não puder ser lido, exige revisão.
- Pareamento por número da NF; sem número na etiqueta, exige nome e CEP iguais e candidato único. Números divergentes nunca são substituídos por tentativa pelo nome.
- NF ou envio sem par não é aprovado sozinho. Nomes/CEPs divergentes ou NFs duplicadas são excluídos da aprovação.
- Pedido e-commerce é lido da frase “referente ao pedido de número…”, com segunda leitura ampliada do rodapé quando necessário. Nunca é deduzido pelo número da NF.
- Transportadora e rastreio são extraídos das etiquetas dos Correios, Olist/Jadlog/Magalog e Melhor Envio/Loggi. Novos layouts podem exigir ajustes.
- Texto extra depois de “contato conosco … esta venda” gera alerta de observações. Se o limite não for identificado, aparece “Conferir observações”.
- Cada item com quantidade diferente de 1 gera alerta. Vários produtos diferentes com quantidade 1 não geram esse alerta. Leitura incompleta usa os valores unitário e total quando consistentes; caso contrário, mostra “Conferir quantidade”.
- OCR é local e pode errar mesmo com confiança alta. Confira as prévias e alertas, especialmente em novos layouts.

## Monitor e ambiente

Watchdog funciona enquanto o app estiver aberto. Aguarda três segundos de estabilidade e não processa enquanto houver .crdownload, .part ou .tmp. Não imprime automaticamente.

Abra **Central de etiquetas** na Área de Trabalho ou **0 - Central de etiquetas.cmd** na entrada. O app usa Python/Tkinter e a pasta .venv; não é um executável independente para outro computador.

Para reinstalar as dependências:

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt

Para executar os testes sem imprimir:

    .venv\Scripts\python.exe -m unittest discover -s . -p test_*.py

Os atalhos antigos permanecem para compatibilidade. O fluxo recomendado é Aprovar e imprimir pares dentro do app.

Os novos lotes usam o formato ano-mês-dia-hora, como **2026-11-17-17h46m27s**, no horário de São Paulo. Se houver mais de um lote no mesmo segundo, acrescentamos **-02**, **-03** etc. As pastas antigas mantêm seus nomes para preservar as referências do histórico.


