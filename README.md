# Separação de Materiais — PS/PSC

Interface web em **React + TypeScript**, API FastAPI e banco PostgreSQL.

## Iniciar

Copie `.env.example` para `.env`, configure a senha do PostgreSQL e execute na raiz:

```sh
docker compose up --build -d
```

Abra **http://localhost:8080**. A documentação da API fica em http://localhost:8000/docs.

- **Projetos:** cadastro manual ou importação de PDF/DOCX/DOC com conferência antes de salvar.
- **Separação → Por projeto:** materiais do PS/PSC selecionado, edição e cadastro de itens.
- **Separação → Consolidado por localidade:** todos os projetos agrupados por destino, com PS/PSC
  identificado em cada linha, filtros e exportação CSV da visualização.
- **Remessas e NFs:** uma remessa reúne itens de vários projetos com o mesmo destino e origem;
  registro de solicitação de NF, número da NF e data de entrega à logística.

Os quatro status são branco (não separado), verde (separado), amarelo (outro local) e vermelho
(sem estoque). A seleção de materiais respeita origem, destino, saldo e pendências de revisão.

O antigo aplicativo Streamlit em `separador_materiais/` é mantido como referência e fornece
os extratores. A nova interface usa exclusivamente a API/PostgreSQL para dados operacionais.

- [Frontend: desenvolvimento e testes](frontend/README.md)
- [API e migração dos JSON existentes](backend/README.md)

O processamento OCR baixa modelos no primeiro uso. A construção Docker habilita seus componentes
por padrão. Para desenvolvimento sem OCR, use `INSTALL_OCR=false` no `.env`; tabelas em imagens
exigem habilitá-lo novamente. PDF com texto nativo e DOCX não precisam dos modelos.
