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

A única interface do sistema é o frontend React. Os extratores de PDF/DOCX fazem parte do
backend e os dados operacionais ficam exclusivamente na API/PostgreSQL; não há mais telas
Streamlit nem persistência paralela em JSON.

- [Frontend: desenvolvimento e testes](frontend/README.md)
- [API e migração dos JSON existentes](backend/README.md)

O processamento OCR baixa modelos no primeiro uso e fica habilitado por padrão. Para uma imagem
Docker menor quando só houver PDF com texto nativo e DOCX, use `INSTALL_OCR=false`. O Docling é
um fallback opcional para PDFs complexos e pode ser ativado com `INSTALL_DOCLING=true`.
