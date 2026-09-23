# API de materiais, projetos e remessas

Backend FastAPI + SQLAlchemy + PostgreSQL conectado à interface React em `frontend/`.
Documentação interativa em `/docs` e contrato OpenAPI em `/openapi.json`.
`POST /documentos/extrair` recebe PDF/DOCX/DOC de até 30 MB e devolve uma prévia para
conferência, preservando também linhas incompletas. A leitura não grava projetos;
a interface só confirma a importação após o usuário conferir e preencher campos obrigatórios.
Os extratores ficam em `backend/app/extraction`; suas heurísticas de localização/reconstrução
continuam exigindo conferência do documento real, especialmente em tabelas multipágina.

PDF nativo e DOCX usam as dependências básicas. Para tabelas em imagens, instale também
`pip install -r backend/requirements-ocr.txt`. Docker habilita EasyOCR por padrão; o primeiro uso
baixa os modelos. O fallback Docling é opcional (`backend/requirements-docling.txt` ou
`INSTALL_DOCLING=true`). DOC antigo exige Windows e Microsoft Word instalado, portanto não é
suportado no contêiner Linux: converta para DOCX ou PDF nesse caso.

## Regras implementadas

| Status do material | Cor | Significado |
|---|---|---|
| `nao_separado` | Branco | Item ainda não separado |
| `separado` | Verde | Item separado |
| `outro_local` | Amarelo | Item sairá de outro local; informar `local_origem` |
| `sem_estoque` | Vermelho | Item indisponível no estoque |

- `PS 100` e `PSC 100` são códigos distintos. Variações como `ps-00100` viram `PS 100`.
- Uma remessa tem um destino, uma origem de expedição, uma NF e vários itens de vários projetos.
- `origem_expedicao=LOCAL` aceita apenas itens verdes. Outra origem aceita apenas itens
  amarelos com `local_origem` correspondente. Não agrupa automaticamente origens diferentes.
- Quantidades de remessas podem ser parciais. Rascunhos reservam o saldo; cancelar libera.
- Branco/vermelho e itens com revisão pendente aparecem no consolidado, mas não podem ser expedidos.
- `data_entrega_logistica` é o dia em que o material foi deixado com a logística. Não é data
  de chegada ao site nem confirmação de recebimento.
- Solicitar NF apenas registra a solicitação no controle: não emite NF nem envia mensagem.
- A NF deve ser informada antes da entrega à logística. Datas futuras são rejeitadas.
- O consolidado preserva cada material e seu PS/PSC; não soma descrições parecidas como se fossem iguais.
- Localidades iguais após normalização de caixa/espaços são reutilizadas. Apelidos/abreviações
  diferentes não são fundidos automaticamente.
- IDs de itens permanecem estáveis; itens vinculados a remessas ativas/enviadas não podem ter
  descrição/destino/quantidade substituídos. Cancele um rascunho para editar e recrie a remessa.
- Cada linha tem um único status; para partes com situações diferentes, separe em linhas antes de reservar.
- PostgreSQL usa locks nas linhas de materiais para impedir reserva concorrente acima do saldo.

## Executar com Docker (raiz do repositório)

1. Copie `.env.example` para `.env` e altere `POSTGRES_PASSWORD`.
2. Execute:

```sh
docker compose up --build -d
```

Abra http://localhost:8080 para a interface ou http://localhost:8000/docs para a API. A API aplica a migração Alembic ao iniciar.
`GET /health` testa a conexão ao banco. API e banco ficam publicados apenas em localhost.
Esta etapa não tem autenticação; a disponibilização para outros usuários exige essa etapa adicional.

## Executar sem Docker

Requer um servidor PostgreSQL. A partir da raiz:

```powershell
python -m venv .venv-api
.\.venv-api\Scripts\Activate.ps1
pip install -r backend/requirements.txt
$env:DATABASE_URL="postgresql+psycopg://usuario:senha@localhost:5432/separador_materiais"
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Alternativamente use `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` e `PGDATABASE` para evitar
codificação de caracteres especiais na senha da URL. `CORS_ORIGINS` aceita uma lista
separada por vírgulas e tem `http://localhost:5173` como padrão.

As tabelas novas têm prefixo `api_` para não colidir com a versão PostgreSQL experimental.
Não existe migração automática das tabelas daquela branch: o migrador desta entrega lê JSON.

## Migrar os JSON existentes

Coloque uma cópia dos JSON antigos em `dados-legados/`. O migrador nunca exclui nem modifica
esses arquivos; o diretório é montado como somente leitura em `/legacy` no contêiner.

Primeiro simule:

```sh
docker compose exec api python -m backend.app.migrate_json /legacy
```

Depois aplique:

```sh
docker compose exec api python -m backend.app.migrate_json /legacy --apply
```

Sem Docker (com a conexão configurada):

```powershell
python -m backend.app.migrate_json dados-legados
python -m backend.app.migrate_json dados-legados --apply
```

O resultado inclui projetos, quantidade de linhas, registros legados e avisos.
- Simulação exercita as gravações e faz rollback. Não grava dados.
- Lote aplicado é uma transação: um arquivo inválido reverte o lote completo.
- SHA-256 identifica arquivos já importados, mesmo que renomeados. Reexecutar não duplica.
- PS/PSC existente com outro conteúdo é conflito, nunca substituição automática.
- Linhas incompletas ficam no banco com `revisao`, sem inventar quantidade ou destino.
- `sem_estoque` tem precedência sobre `separado` quando ambos estão marcados; a contradição
  exige revisão. O amarelo não é deduzido de textos ambíguos de origem.
- O JSON original completo é preservado dentro do banco para rastreabilidade, inclusive
  campos desconhecidos e datas sem fuso. Não é usado como armazenamento operacional.
- NF/data antigas ficam como `legado_revisar`. Não é possível inferir quais quantidades
  foram enviadas a partir do JSON antigo. NFs iguais não são mescladas automaticamente.
- A API permite conferir os itens e reconciliar explicitamente as quantidades do legado.

O repositório não contém os JSON operacionais nem credenciais do banco do usuário.
Os testes usam exemplos sintéticos, não uma migração dos dados reais. A planilha SharePoint
não foi importada; sua leitura depende do acesso à conta e da análise das colunas/cores.

## Fluxo para o frontend React

1. `POST /projetos`: cadastra PS/PSC com seus materiais. Duplicado retorna 409.
2. `GET /consolidado?localidade_id=...`: lista necessidades de todos os projetos naquele destino.
3. `PUT /itens/{id}`: substitui os campos após conferência, incluindo o status.
4. `POST /remessas`: seleciona explicitamente itens/quantidades de um ou vários projetos.
5. `POST /remessas/{id}/solicitar-nf`: registra que a NF foi solicitada.
6. `PUT /remessas/{id}/nf`: informa a NF correspondente à remessa.
7. `POST /remessas/{id}/entregar-logistica`: informa a data real de entrega à logística.

Exemplo de projeto:

```json
{
  "codigo": "PSC 2103",
  "projetista": "Projetista",
  "responsavel_implantacao": "Responsável",
  "itens": [
    {"destino": "SITE A", "descricao": "Módulo óptico", "quantidade": 4, "status": "separado"}
  ]
}
```

A resposta traz IDs de projeto, localidade e materiais. Utilize-os para criar a remessa:

```json
{
  "localidade_id": "ID-DO-SITE-A",
  "origem_expedicao": "LOCAL",
  "itens": [
    {"item_id": "ID-DO-MATERIAL-PSC-2103", "quantidade": 2},
    {"item_id": "ID-DO-MATERIAL-OUTRO-PROJETO", "quantidade": 1}
  ]
}
```

Rotas adicionais:

| Método e rota | Uso |
|---|---|
| `GET /projetos`, `GET /projetos/{id}` | Consultar projetos e materiais |
| `PATCH /projetos/{id}` | Atualizar projetista/responsável |
| `POST /projetos/{id}/itens` | Adicionar material |
| `POST /itens/{id}/conferir` | Confirmar revisão do material sem alterar histórico |
| `GET /localidades` | Listar destinos |
| `GET /status-materiais` | Mapear status para cores |
| `GET /remessas`, `GET /remessas/{id}` | Consultar NF, destino, data e PS/PSC dos itens |
| `POST /remessas/{id}/cancelar` | Cancelar remessa não entregue e liberar saldo |
| `POST /remessas/{id}/reconciliar-legado` | Informar NF, data e quantidades realmente enviadas no legado |

Após reconciliar um envio legado, confirme a revisão dos itens com `/itens/{id}/conferir`
para permitir novas remessas do saldo. Itens com campos ausentes precisam primeiro ser
corrigidos com `PUT /itens/{id}`. A confirmação é uma ação explícita do usuário.

O consolidado aceita `localidade_id`, `projeto_id`, `status` e `somente_pendentes`.
Retorna quantidade necessária, reservada, entregue à logística, pendente e disponível
para nova remessa. Nenhuma quantidade enviada é derivada apenas da presença de NF.

## Testes

```sh
pip install -r backend/requirements-dev.txt
pytest backend/tests -q
```

Sem configuração extra, os testes rápidos usam SQLite em memória. Isso não substitui
PostgreSQL: o teste de concorrência só executa com o banco real.

Para incluir PostgreSQL, migrações upgrade/downgrade e reservas concorrentes nos testes,
defina `TEST_DATABASE_URL` apontando para um banco
**descartável com nome terminado em `_test`**. Os testes criam e removem tabelas nesse banco.

Não use `docker compose down -v` para parar o aplicativo: essa opção remove os volumes.
Use `docker compose down`; faça backup do banco antes de alterações operacionais.
