# 📦 Separador de Materiais por Local — PSC/PS (Eletronet)

Aplicação web **local** que lê PDFs de **Projeto de Serviço de Cliente (PSC)** /
**Projeto de Serviço (PS)**, extrai a tabela da seção **"Lista de equipamentos a
Adquirir / Instalar"** (legenda "Tabela 1 – Material utilizado"), agrupa os
materiais por **destino** e ajuda na separação física, com marcação de itens
"separados", barra de progresso e exportação para Excel/CSV.

Todos os projetos seguem o **mesmo modelo** (layout fixo); a única variação é a
quantidade de páginas. A tabela alvo é identificada pelo cabeçalho:

```
Destino | Equipamento | Origem | Responsável | Ação
```

Todas as outras tabelas/textos do documento são **ignorados**.

### Como a tabela é lida

O Docling **não** reconhece esse bloco como tabela (vê a região como figura), então
o app reconstrói as colunas a partir das **coordenadas** do conteúdo, ancorando na
linha do cabeçalho e na regra "o Equipamento começa com a quantidade". Há três
caminhos, do mais rápido ao mais robusto (acionados nessa ordem, sob demanda):

1. **Texto nativo** (`extrair_tabela_texto`, via pypdfium2) — caso dos PSC/PS
   atuais. É **instantâneo**, não usa OCR/modelos de ML (RAM mínima) e **não tem
   erros de leitura**. Esse é o caminho normal.
2. **OCR** (`extrair_tabela_imagem`, EasyOCR) — fallback para PDF escaneado ou
   tabela realmente em imagem. Recorta só a região da tabela e mostra um preview
   + tabela editável para conferência.
3. **Docling** — último fallback, para tabela já reconhecida como tabela em texto.

**DOCX / DOC:** além de PDF, o app lê Word. O **DOCX** é lido com `python-docx`
(a tabela de materiais é uma tabela real do Word — não precisa do Word instalado).
O **DOC** (formato antigo) é convertido para DOCX automaticamente via **Microsoft
Word** (requer o Word instalado no Windows).

Em todos os casos os itens entram numa **tabela editável** na tela de Separação,
para ajustes antes de separar.

---

## Estrutura de pastas

```
separador_materiais/
├── app.py                 # Interface Streamlit — 3 telas (Projetos/Separação/Consolidado)
├── persistencia.py        # Armazenamento dos projetos em disco (fonte da verdade)
├── extracao_imagem.py     # Extração de PDF: texto nativo + OCR (fallback)
├── extracao_docx.py       # Extração de DOCX (python-docx) e DOC (via Word/COM)
├── extracao.py            # Docling: leitura de tabela em texto (último fallback)
├── normalizacao.py        # De-para, parse de quantidade e regras de negócio
├── relatorio.py           # Relatório de envio em PDF (com logo)
├── requirements.txt       # Dependências
├── README.md              # Este arquivo
├── .gitignore
├── assets/
│   └── logo_eletronet.png # Logo usada no PDF (definida pela interface)
├── dados/
│   └── projetos/          # 1 JSON por projeto (itens, separação, NF/data) — persistido
└── tests/
    └── test_normalizacao.py
```

## Telas e persistência

A navegação fica na barra lateral, com **2 telas**:

1. **📤 Projetos (subir e conferir)** — envie os arquivos (**PDF, DOCX ou DOC**);
   a tabela é extraída e **salva em disco**. Os projetos salvos ficam listados
   aqui (com prévia dos itens) e podem ser excluídos. Reabrir o app mostra tudo
   de novo, sem reenviar.
2. **📦 Separação** — escolha um projeto e trabalhe numa **tabela totalmente
   editável**: alterar nome/quantidade/tipo, o campo **Serial / Tamanho**
   (nº de série do equipamento ou tamanho do cordão), **criar** (➕) ou
   **remover** itens, marcar `separado` e marcar **⛔ Sem estoque** (itens em
   falta). Por **local (destino)** há os campos **NF de envio** e **Data de
   envio**. Tudo é **salvo automaticamente**. No fim da tela há o
   **📊 Consolidado** (todos os projetos, por local e PSC) e os **relatórios PDF**.

### Relatórios em PDF

Por projeto (na Separação) e geral (no Consolidado):

- **Relatório de envio** — itens **enviados** (locais com **NF ou data de envio**),
  agrupados por PSC e local, com NF, data, serial/tamanho e status.
- **Relatório de itens em falta** — itens marcados como **⛔ Sem estoque**,
  agrupados por PSC e local (lista de compra/aquisição).

A **logo da empresa** aparece no cabeçalho: defina-a uma vez no Consolidado em
*"Logo da empresa (PNG/JPG)"* (fica salva em `assets/logo_eletronet.png`).

> Os dados ficam em `dados/projetos/*.json` (um arquivo por PSC). É o que torna
> tudo persistente entre sessões. Faça backup dessa pasta se quiser preservar o
> histórico.

---

## Instalação

Pré-requisito: **Python 3.11+**.

> 🐍 **Compatibilidade de versão:** o Docling depende de bibliotecas de ML
> (PyTorch etc.) cujos *wheels* costumam demorar a ser publicados para versões
> muito recentes do Python. Se a instalação do `docling` falhar (ex.: em
> **Python 3.14**), use **Python 3.11 ou 3.12** no ambiente virtual — é a faixa
> mais estável para esse ecossistema.

```powershell
# 1) Entrar na pasta do projeto
cd "separador_materiais"

# 2) (Recomendado) criar e ativar um ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Windows PowerShell
# source .venv/bin/activate       # Linux/macOS

# 3) Instalar as dependências
pip install -r requirements.txt
```

> ⚠️ **Download inicial dos modelos do Docling:** na **primeira** execução, o
> Docling baixa os modelos de leitura/layout (pode levar alguns minutos e exige
> internet). Depois disso fica em cache e o processamento é rápido. O app exibe
> um *spinner* enquanto lê cada PDF.

---

## Execução

```powershell
streamlit run app.py
```

O Streamlit abre o navegador automaticamente (geralmente em
`http://localhost:8501`).

### Como usar

1. Na tela **📤 Projetos**, **envie os PDF(s)**. Cada projeto é extraído e
   **salvo em disco** (aparece na lista de projetos salvos).
2. Vá para **📦 Separação**, escolha o projeto e trabalhe na **tabela editável**:
   marque `separado`, edite nome/quantidade/tipo, **adicione/remova** itens.
3. Preencha **NF de envio** e **Data de envio** por **local (destino)**.
4. Acompanhe os totais/progresso e **exporte** (Excel por local ou CSV).
5. Use **📊 Consolidado** para ver todos os projetos juntos, por local e PSC.

Tudo é **salvo automaticamente** em `dados/projetos/<PSC>.json` a cada
alteração e recarregado ao reabrir o app.

---

## Testes

### 1) Teste automatizado do parsing (dados de referência)

Valida a separação de quantidade/item e o de-para usando linhas reais de um PSC
de exemplo (`EQUINIX SP4`, `FURNAS`, `BANDEIRANTES`):

```powershell
pip install pytest      # caso ainda não tenha
pytest                  # a partir da pasta do projeto
# ou, sem pytest:
python tests\test_normalizacao.py
```

Casos cobertos, entre outros:
- `01 QSFP56 DR4+ MPO` → quantidade **1**, item **"QSFP56 DR4+ MPO"**
- `08 cordões ópticos ... (Verificar com a regional)` → quantidade **8**, nota
  mantida no item
- linha sem número inicial → vai para **"Revisar"** (não é descartada)
- cabeçalho repetido (tabela multipágina) e linhas vazias → descartados

### 2) Teste com um PDF real do modelo PSC

1. Rode `streamlit run app.py`.
2. Faça upload de um PSC real (1 a N páginas).
3. Confira que aparecem os destinos esperados (ex.: `EQUINIX SP4`, `FURNAS`,
   `BANDEIRANTES`) com quantidade e item separados corretamente.
4. Marque alguns itens, interaja com filtros e confirme que o progresso **não
   se perde**.
5. Exporte o Excel e verifique uma aba por destino e o número do PSC no nome do
   arquivo (`separacao_<PSC>.xlsx`).

---

## Ajustes de configuração (se o modelo do PDF mudar)

Toda a parametrização de negócio fica no topo de [`normalizacao.py`](normalizacao.py):

- `CABECALHO_ESPERADO` — assinatura usada para localizar a tabela.
- `MAPEAMENTO_COLUNAS` — de-para coluna do PDF → campo interno.
- `_RE_QUANTIDADE` — regex que separa a quantidade da descrição.

A detecção do número do PSC fica em [`extracao.py`](extracao.py) (`_PADROES_PSC`).

---

## Rede corporativa (proxy / interceptação de TLS) e modelos do Docling

O Docling baixa modelos na primeira execução (layout e estrutura de tabelas, do
HuggingFace). Em redes que interceptam HTTPS com um certificado raiz próprio
(comum em empresas), esse download falha com erros de SSL, por exemplo:

```
certificate verify failed: self-signed certificate in certificate chain
Download failed: https://www.modelscope.cn/.../ch_PP-OCRv4_det_mobile.pth
```

**Soluções (na ordem recomendada):**

1. **OCR já vem desligado** neste app (`extracao.py`), pois os PSC/PS são PDFs
   digitais. Isso elimina o download do RapidOCR (modelscope.cn).

2. **Confiar no certificado corporativo (resolve o SSL):**
   ```powershell
   .\.venv\Scripts\python.exe -m pip install pip-system-certs
   ```
   Esse pacote faz o Python usar a **loja de certificados do Windows** (que já
   contém o certificado raiz da empresa — por isso o navegador funciona). Não
   precisa importar nada no código; ele se ativa sozinho. Depois, rode o app
   novamente — os modelos do Docling serão baixados normalmente.

   *Alternativa manual:* exporte o certificado raiz corporativo em `.pem` e
   aponte as variáveis antes de rodar:
   ```powershell
   $env:REQUESTS_CA_BUNDLE = "C:\caminho\ca-empresa.pem"
   $env:SSL_CERT_FILE      = "C:\caminho\ca-empresa.pem"
   ```

3. **Modelos offline (rede totalmente bloqueada):** baixe os modelos em uma
   máquina com internet liberada e copie a pasta para este PC. Aponte a variável
   antes de rodar o app:
   ```powershell
   # na máquina com internet:
   docling-tools models download
   # copie a pasta de artefatos para este PC e aponte:
   $env:DOCLING_ARTIFACTS_PATH = "C:\caminho\modelos-docling"
   ```

> Dica para silenciar o aviso de telemetria do Streamlit (opcional): crie
> `%userprofile%\.streamlit\config.toml` com:
> ```toml
> [browser]
> gatherUsageStats = false
> ```

## Tratamento de erros

| Situação                                   | Comportamento                                              |
|--------------------------------------------|-----------------------------------------------------------|
| PDF sem a tabela de logística              | Mensagem clara indicando o cabeçalho esperado.            |
| Cabeçalho diferente do esperado            | Colunas não encontradas são listadas como aviso.          |
| PDF escaneado (imagem, sem texto)          | Aviso para habilitar OCR / usar PDF com texto.            |
| Arquivo corrompido / formato inválido      | Erro tratado, sem derrubar o app.                         |
| Linhas sem quantidade / campos faltando    | Vão para a seção **"Revisar"** (não são perdidas).        |

---

## Decisões de projeto

- **Vários PDFs**: todos são processados; você alterna entre eles por um seletor
  na barra lateral (1 projeto ativo por vez). O progresso é por PSC.
- **Número do PSC editável**: é detectado automaticamente, mas pode ser
  corrigido na UI — o número real costuma estar no cabeçalho do documento e pode
  haver ocorrências como `PS 2055` na própria coluna *Origem*.
- **Cache**: o conversor Docling usa `@st.cache_resource` (criado uma vez) e o
  processamento de cada PDF usa `@st.cache_data` (chaveado pelos bytes do
  arquivo), evitando reprocessar a cada clique.
