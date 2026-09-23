from contextlib import asynccontextmanager
from datetime import date
import os

from fastapi import Depends, FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from .db import make_engine, session_factory
from .models import Localidade, now
from .schemas import (CORES, EntregaEntrada, ItemEntrada, NFEntrada, ProjetoEdicao,
                      ProjetoEntrada, RemessaEntrada, StatusItem, ReconciliacaoEntrada)
from . import services as s


def create_app(engine=None):
    @asynccontextmanager
    async def lifespan(app):
        owned = engine is None
        app.state.engine = engine if engine is not None else make_engine()
        app.state.sessions = session_factory(app.state.engine)
        yield
        if owned:
            app.state.engine.dispose()

    app = FastAPI(title="Separador de Materiais", version="0.1.0", lifespan=lifespan,
                  description="PS/PSC, status dos materiais e remessas consolidadas por destino.")
    app.add_middleware(CORSMiddleware,
                       allow_origins=[v.strip() for v in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if v.strip()],
                       allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Content-Type"])

    def session():
        with app.state.sessions() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    @app.exception_handler(IntegrityError)
    async def conflict(_request, _exc):
        return JSONResponse(status_code=409, content={"detail": "Conflito de dados. Atualize e tente novamente; a operação não foi gravada."})

    @app.exception_handler(OperationalError)
    async def unavailable(_request, _exc):
        return JSONResponse(status_code=503, content={"detail": "Banco de dados indisponível."})

    @app.get("/health")
    def health(db=Depends(session, scope="function")):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/documentos/extrair")
    def preview_document(arquivo: UploadFile = File(...)):
        from .documents import extrair_documento
        limite = 30 * 1024 * 1024
        try:
            conteudo = arquivo.file.read(limite + 1)
            if len(conteudo) > limite:
                raise HTTPException(413, "O documento deve ter no máximo 30 MB.")
            return extrair_documento(arquivo.filename or "documento.pdf", conteudo)
        finally:
            arquivo.file.close()

    @app.get("/status-materiais")
    def statuses():
        return [{"status": k, "cor": v} for k, v in CORES.items()]

    @app.post("/projetos", status_code=201)
    def create_project(data: ProjetoEntrada, db=Depends(session, scope="function")):
        projeto = s.criar_projeto(db, data)
        return s.projetos_saida(db, [s.carregar_projeto(db, projeto.id)])[0]

    @app.get("/projetos")
    def projects(db=Depends(session, scope="function")):
        return s.projetos_saida(db, s.carregar_projetos(db))

    @app.get("/projetos/{id}")
    def project(id: str, db=Depends(session, scope="function")):
        return s.projetos_saida(db, [s.carregar_projeto(db, id)])[0]

    @app.patch("/projetos/{id}")
    def edit_project(id: str, data: ProjetoEdicao, db=Depends(session, scope="function")):
        p = s.carregar_projeto(db, id, lock=True)
        p.projetista = data.projetista
        p.responsavel_implantacao = data.responsavel_implantacao
        db.flush()
        return s.projetos_saida(db, [p])[0]

    @app.post("/projetos/{id}/itens", status_code=201)
    def add_item(id: str, data: ItemEntrada, db=Depends(session, scope="function")):
        p = s.carregar_projeto(db, id, lock=True)
        i = s.criar_item(db, p, data, len(p.itens))
        return s.item_saida(i, s.quantidades(db, [i.id]), p.codigo)

    @app.put("/itens/{id}")
    def edit_item(id: str, data: ItemEntrada, db=Depends(session, scope="function")):
        item = s.editar_item(db, id, data)
        return s.item_saida(item, s.quantidades(db, [item.id]))

    @app.post("/itens/{id}/conferir")
    def review_item(id: str, db=Depends(session, scope="function")):
        i = s.carregar_item(db, id, lock=True)
        if not i.localidade_id or not i.descricao.strip() or i.quantidade is None:
            raise HTTPException(409, "Corrija destino, descrição e quantidade antes de confirmar.")
        i.revisao = ""
        return s.item_saida(i, s.quantidades(db, [i.id]))

    @app.get("/localidades")
    def locations(db=Depends(session, scope="function")):
        return [{"id": l.id, "nome": l.nome} for l in db.scalars(select(Localidade).order_by(Localidade.chave))]

    @app.get("/consolidado")
    def consolidated(localidade_id: str | None = None, projeto_id: str | None = None,
                     status: StatusItem | None = None, somente_pendentes: bool = True, db=Depends(session, scope="function")):
        return s.consolidado(db, localidade_id, projeto_id, status.value if status else None, somente_pendentes)

    @app.post("/remessas", status_code=201)
    def create_shipment(data: RemessaEntrada, db=Depends(session, scope="function")):
        remessa = s.criar_remessa(db, data)
        return s.remessa_saida(s.carregar_remessa(db, remessa.id))

    @app.get("/remessas")
    def shipments(localidade_id: str | None = None, db=Depends(session, scope="function")):
        return [s.remessa_saida(r) for r in s.carregar_remessas(db, localidade_id)]

    @app.get("/remessas/{id}")
    def shipment(id: str, db=Depends(session, scope="function")):
        return s.remessa_saida(s.carregar_remessa(db, id))

    @app.post("/remessas/{id}/solicitar-nf")
    def request_nf(id: str, db=Depends(session, scope="function")):
        r = s.carregar_remessa(db, id, lock=True)
        if r.status not in ("rascunho", "nf_solicitada"):
            raise HTTPException(409, "NF só pode ser solicitada para um rascunho.")
        r.status = "nf_solicitada"
        r.nf_solicitada_em = r.nf_solicitada_em or now()
        return s.remessa_saida(r)

    @app.put("/remessas/{id}/nf")
    def invoice(id: str, data: NFEntrada, db=Depends(session, scope="function")):
        r = s.carregar_remessa(db, id, lock=True)
        if r.status not in ("rascunho", "nf_solicitada", "nf_registrada"):
            raise HTTPException(409, "Esta remessa não permite alteração da NF.")
        r.nf, r.status = data.nf, "nf_registrada"
        return s.remessa_saida(r)

    @app.post("/remessas/{id}/entregar-logistica")
    def deliver(id: str, data: EntregaEntrada, db=Depends(session, scope="function")):
        r = s.carregar_remessa(db, id, lock=True)
        if r.status != "nf_registrada" or not r.nf:
            raise HTTPException(409, "Registre a NF antes de entregar à logística.")
        if data.data_entrega_logistica > date.today():
            raise HTTPException(422, "A entrega à logística não pode ter data futura.")
        r.data_entrega_logistica = data.data_entrega_logistica
        r.status = "entregue_logistica"
        return s.remessa_saida(r)

    @app.post("/remessas/{id}/reconciliar-legado")
    def reconcile(id: str, data: ReconciliacaoEntrada, db=Depends(session, scope="function")):
        if data.data_entrega_logistica and data.data_entrega_logistica > date.today():
            raise HTTPException(422, "A entrega à logística não pode ter data futura.")
        remessa = s.reconciliar_legado(db, id, data)
        return s.remessa_saida(s.carregar_remessa(db, remessa.id))

    @app.post("/remessas/{id}/cancelar")
    def cancel(id: str, db=Depends(session, scope="function")):
        r = s.carregar_remessa(db, id, lock=True)
        if r.status in ("entregue_logistica", "legado_revisar"):
            raise HTTPException(409, "Histórico de envio não pode ser cancelado por esta operação.")
        r.status = "cancelada"
        return s.remessa_saida(r)

    return app


app = create_app()
