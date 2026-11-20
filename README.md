# Central de etiquetas — Dear Friends

Aplicativo local Windows para parear DANFE simplificado e etiquetas de envio,
ordenar por cliente e gerar PDF ou imprimir na Zebra ZD220 (100 × 150 mm).
Interface em português, OCR local e monitoramento da pasta de entrada.

## Instalar em cada computador

Instale Python **3.14 de 64 bits**, com Tcl/Tk, e Git. Clone este repositório
em uma pasta de sua escolha. No PowerShell, dentro dela:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Configure os caminhos desse computador no `.env`, por exemplo:

```dotenv
ETIQUETAS_INPUT_DIR=C:/Operacao/Impressoes
ETIQUETAS_DATA_DIR=C:/Operacao/CentralEtiquetas
ETIQUETAS_PRINTER=ZDesigner ZD220-203dpi ZPL
```

Crie a pasta de entrada escolhida e execute **Abrir Central de etiquetas.cmd**
ou `.\.venv\Scripts\pythonw.exe app.py`.
O primeiro OCR pode precisar de internet para obter os modelos.
Para impressão, instale o driver Zebra ZPL e configure seu nome exato no `.env`.
Gerar PDF funciona sem impressora disponível.

## Configuração por computador

Variáveis do ambiente do Windows têm prioridade sobre `.env`.
Caminhos relativos são resolvidos a partir da pasta do aplicativo.

| Variável | Padrão quando vazia |
| --- | --- |
| `ETIQUETAS_INPUT_DIR` | `Desktop/Impressões` do usuário atual; sem variável definida, também pode ser escolhida pela interface |
| `ETIQUETAS_DATA_DIR` | `%LOCALAPPDATA%/DearFriends/CentralEtiquetas` para preferências e log de erro |
| `ETIQUETAS_PRINTER` | `ZDesigner ZD220-203dpi ZPL` |
| `ETIQUETAS_PYTHON` | Interpretador que iniciou o aplicativo; não é preciso preencher ao usar a `.venv` |

As opções de linha de comando `--folder` e `--printer` têm prioridade no motor.
Pastas `_processamento`, `impressos`, `resultados` e `pdfs-gerados` ficam dentro
da pasta de entrada. Elas não são versionadas. Mantenha-as juntas para preservar
os registros; manifests existentes contêm caminhos absolutos e não devem ser
copiados entre computadores como se fossem portáveis.

## Atualizar nos dois computadores

Com a central fechada, execute em cada computador:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

O Git sincroniza código, não pedidos, PDFs, fila da Zebra ou histórico.
Cada computador tem configuração e operação independentes. Evite imprimir o
mesmo pedido em ambos: a proteção contra duplicação usa o histórico local.
Nunca copie a `.venv` de um computador para outro; recrie-a.

## Uso e validação

Consulte [LEIA-ME.md](LEIA-ME.md) para o fluxo de expedição e recuperação.
Alertas de quantidade estão desativados. Observações permanecem consultáveis,
sem destaque amarelo. A geração de PDF não imprime nem arquiva as entradas.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s . -p 'test_*.py'
```

O repositório não inclui `.env`, preferências, documentos fiscais, modelos OCR,
arquivos de impressão nem dados de clientes.
