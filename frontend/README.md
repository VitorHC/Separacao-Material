# Interface React + TypeScript

React, TypeScript e Vite. Interface conectada aos dados reais da API: não carrega exemplos
nem usa JSON/localStorage como banco operacional. Estados vazios e falhas de conexão são explícitos.

## Desenvolvimento

Com API/PostgreSQL em execução na porta 8000:

```sh
cd frontend
npm ci
npm run dev
```

Abra http://localhost:5173. O Vite encaminha `/api` para `http://127.0.0.1:8000`.
Para outro endereço, defina `API_PROXY_TARGET` antes de iniciar o Vite.

Build: `npm run build`. O resultado fica em `frontend/dist`.
Para execução integrada use o Docker Compose da raiz: Nginx serve a interface em
http://localhost:8080 e encaminha `/api` ao backend. Não há credenciais de banco no navegador.

## Separação

- **Por projeto:** seleciona PS/PSC, edita materiais e adiciona linhas.
- **Consolidado por localidade:** reutiliza os materiais carregados em `/projetos` e os agrupa
  no navegador, evitando uma segunda transferência dos mesmos dados. A seleção da aba Por
  projeto não limita o consolidado. A rota `/consolidado` continua disponível para integrações.
- Busca por material, código, destino ou serial. Filtros por localidade/situação e pendências.
- Métricas representam linhas de materiais, não a soma de peças; a tabela mostra quantidades.
- CSV exporta apenas a visualização filtrada, com BOM UTF-8 e proteção de fórmulas.
- Seleciona materiais elegíveis de vários projetos e cria uma remessa para o mesmo destino/origem.
- Cada quantidade pode ser reduzida para envio parcial no modal da remessa.
- Itens brancos/vermelhos, sem saldo ou com revisão pendente não são selecionáveis para envio.
- Amarelos exigem `local_origem` e nunca são misturados aos itens do estoque local.
- Alterar filtros ou aba limpa a seleção para não enviar materiais ocultos inadvertidamente.

## Projetos e documentos

Importação de PDF/DOCX/DOC com prévia editável, PS/PSC editável e opção de visualizar o PDF
original ou o recorte de OCR. Campos ausentes são mantidos e precisam ser corrigidos antes de
confirmar. É possível cadastrar projetos manualmente e inserir materiais sem documentos.
Os documentos originais são usados para a conferência nesta sessão; o sistema ainda não os
arquiva de forma permanente. O nome do arquivo e os materiais ficam no banco.

## Remessas

Cadastro da solicitação de NF (controle manual, sem envio de mensagem), registro da NF,
registro da data em que o material foi entregue à logística e cancelamento de remessas ainda
não entregues. A API continua sendo a autoridade para validar saldo, bloqueios e transições.
NFs legadas são exibidas com aviso de conferência; a reconciliação detalhada continua pelo
endpoint `/remessas/{id}/reconciliar-legado`, documentado em `/docs`.

## Testes de navegação

Na raiz, prepare o ambiente Python de testes (o runner usa `.venv-api`):

```sh
python -m venv .venv-api
.venv-api/bin/pip install -r backend/requirements-dev.txt
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

No Windows, defina `E2E_PYTHON` com o caminho absoluto de `.venv-api/Scripts/python.exe`.
Os testes iniciam uma API separada em 8001 com **SQLite descartável e dados sintéticos**, e
Vite em 5173. Não usam o PostgreSQL do usuário. Cobrem consolidado, remessa com dois projetos,
NF/data, filtros/CSV, edição, cadastro e layout móvel. Locks PostgreSQL continuam cobertos
pelo teste específico do backend/CI.

Se Chromium já estiver instalado, defina `CHROMIUM_EXECUTABLE_PATH` para seu executável.
As fontes possuem fallback local para funcionamento sem conexão aos servidores de fontes.
