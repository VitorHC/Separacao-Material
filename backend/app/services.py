from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from .models import Item, Localidade, Projeto, Remessa, RemessaItem, uid
from .schemas import CORES, ItemEntrada, ProjetoEntrada, RemessaEntrada, texto_chave


RESERVAM = ("rascunho", "nf_solicitada", "nf_registrada", "entregue_logistica")


def obter(db: Session, model, id: str, lock=False):
    query = select(model).where(model.id == id)
    if lock:
        query = query.with_for_update()
    value = db.scalar(query)
    if value is None:
        raise HTTPException(404, "Registro não encontrado.")
    return value


def carregar_projeto(db: Session, id: str, lock: bool = False):
    query = (select(Projeto)
             .options(selectinload(Projeto.itens).selectinload(Item.localidade))
             .where(Projeto.id == id))
    if lock:
        query = query.with_for_update()
    projeto = db.scalar(query.execution_options(populate_existing=True))
    if projeto is None:
        raise HTTPException(404, "Registro não encontrado.")
    return projeto


def carregar_projetos(db: Session):
    query = (select(Projeto)
             .options(selectinload(Projeto.itens).selectinload(Item.localidade))
             .order_by(Projeto.codigo))
    return list(db.scalars(query))


def carregar_item(db: Session, id: str, lock: bool = False):
    query = (select(Item)
             .options(selectinload(Item.projeto), selectinload(Item.localidade))
             .where(Item.id == id))
    if lock:
        query = query.with_for_update()
    item = db.scalar(query.execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(404, "Registro não encontrado.")
    return item


def _opcoes_remessa():
    return (
        selectinload(Remessa.localidade),
        selectinload(Remessa.itens).selectinload(RemessaItem.item).selectinload(Item.projeto),
    )


def carregar_remessa(db: Session, id: str, lock: bool = False):
    query = select(Remessa).options(*_opcoes_remessa()).where(Remessa.id == id)
    if lock:
        query = query.with_for_update()
    remessa = db.scalar(query.execution_options(populate_existing=True))
    if remessa is None:
        raise HTTPException(404, "Registro não encontrado.")
    return remessa


def carregar_remessas(db: Session, localidade_id: str | None = None):
    query = select(Remessa).options(*_opcoes_remessa()).order_by(Remessa.criado_em.desc())
    if localidade_id:
        query = query.where(Remessa.localidade_id == localidade_id)
    return list(db.scalars(query))


def localidade(db: Session, nome: str):
    nome = " ".join(nome.split())
    chave = texto_chave(nome)
    if not chave:
        return None
    # ON CONFLICT evita duplicar localidades em importações simultâneas.
    if db.bind.dialect.name == "postgresql":
        db.execute(pg_insert(Localidade).values(id=uid(), nome=nome, chave=chave)
                   .on_conflict_do_nothing(index_elements=[Localidade.chave]))
    else:  # SQLite é usado somente em testes unitários.
        value = db.scalar(select(Localidade).where(Localidade.chave == chave))
        if not value:
            db.add(Localidade(nome=nome, chave=chave))
            db.flush()
    return db.scalar(select(Localidade).where(Localidade.chave == chave))


def criar_item(db: Session, projeto: Projeto, entrada: ItemEntrada, ordem=0):
    data = entrada.model_dump(mode="json")
    loc = localidade(db, data.pop("destino"))
    item = Item(projeto=projeto, localidade=loc, ordem=ordem, **data)
    db.add(item)
    db.flush()
    return item


def criar_projeto(db: Session, entrada: ProjetoEntrada):
    if db.scalar(select(Projeto.id).where(Projeto.codigo == entrada.codigo)):
        raise HTTPException(409, "PS/PSC já cadastrado. Nenhum dado foi substituído.")
    p = Projeto(**entrada.model_dump(exclude={"itens"}))
    db.add(p)
    db.flush()
    for n, i in enumerate(entrada.itens):
        criar_item(db, p, i, n)
    return p


def quantidades(db: Session, item_ids=None):
    query = (select(RemessaItem.item_id, Remessa.status, func.sum(RemessaItem.quantidade))
             .join(Remessa, Remessa.id == RemessaItem.remessa_id)
             .where(Remessa.status.in_(RESERVAM)))
    if item_ids is not None:
        item_ids = list(item_ids)
        if not item_ids:
            return defaultdict(lambda: {"reservada": 0, "entregue_logistica": 0})
        query = query.where(RemessaItem.item_id.in_(item_ids))
    rows = db.execute(query.group_by(RemessaItem.item_id, Remessa.status))
    totals = defaultdict(lambda: {"reservada": 0, "entregue_logistica": 0})
    for item_id, status, qtd in rows:
        key = "entregue_logistica" if status == "entregue_logistica" else "reservada"
        totals[item_id][key] += qtd
    return totals


def _saldos(i: Item, totals):
    t = totals.get(i.id, {"reservada": 0, "entregue_logistica": 0})
    pendente = max(0, i.quantidade - t["entregue_logistica"]) if i.quantidade is not None else None
    disponivel = max(0, pendente - t["reservada"]) if pendente is not None else None
    return t, pendente, disponivel


def item_saida(i: Item, totals, codigo_projeto: str | None = None):
    t, pendente, disponivel = _saldos(i, totals)
    return {"id": i.id, "projeto_id": i.projeto_id,
            "codigo_projeto": codigo_projeto if codigo_projeto is not None else i.projeto.codigo,
            "localidade_id": i.localidade_id, "destino": i.localidade.nome if i.localidade else "",
            "descricao": i.descricao, "quantidade": i.quantidade, "status": i.status,
            "cor": CORES[i.status], "local_origem": i.local_origem, "tipo": i.tipo,
            "serial": i.serial, "origem": i.origem, "responsavel": i.responsavel,
            "acao": i.acao, "observacoes": i.observacoes, "revisao": i.revisao,
            "quantidade_reservada": t["reservada"], "quantidade_entregue_logistica": t["entregue_logistica"],
            "quantidade_pendente": pendente, "quantidade_disponivel_remessa": disponivel}


def projeto_saida(p: Projeto, totals):
    return {"id": p.id, "codigo": p.codigo, "arquivo": p.arquivo, "paginas": p.paginas,
            "metodo": p.metodo, "projetista": p.projetista,
            "responsavel_implantacao": p.responsavel_implantacao,
            "criado_em": p.criado_em, "atualizado_em": p.atualizado_em,
            "itens": [item_saida(i, totals, p.codigo) for i in p.itens]}


def projetos_saida(db: Session, projetos):
    projetos = list(projetos)
    totals = quantidades(db, (item.id for projeto in projetos for item in projeto.itens))
    return [projeto_saida(projeto, totals) for projeto in projetos]


def editar_item(db: Session, id: str, entrada: ItemEntrada):
    i = carregar_item(db, id, lock=True)
    # IDs estáveis: uma remessa nunca muda silenciosamente após sua criação.
    ligado = db.scalar(select(RemessaItem.id).join(Remessa)
                       .where(RemessaItem.item_id == id, Remessa.status != "cancelada").limit(1))
    if ligado:
        raise HTTPException(409, "Item vinculado a remessa. Cancele o rascunho antes de editar; histórico enviado é imutável.")
    data = entrada.model_dump(mode="json")
    i.localidade = localidade(db, data.pop("destino"))
    for key, value in data.items():
        setattr(i, key, value)
    i.revisao = ""  # PUT representa conferência explícita de todos os campos.
    db.flush()
    return i


def consolidado(db: Session, localidade_id=None, projeto_id=None, status=None, somente_pendentes=True):
    query = select(Item).options(selectinload(Item.projeto), selectinload(Item.localidade)).order_by(Item.projeto_id, Item.ordem)
    if localidade_id:
        query = query.where(Item.localidade_id == localidade_id)
    if projeto_id:
        query = query.where(Item.projeto_id == projeto_id)
    if status:
        query = query.where(Item.status == status)
    items = list(db.scalars(query))
    totals = quantidades(db, (item.id for item in items))
    grupos = {}
    for item in items:
        row = item_saida(item, totals)
        if somente_pendentes and row["quantidade_pendente"] == 0:
            continue
        key = item.localidade_id or "sem_localidade"
        group = grupos.setdefault(key, {"localidade_id": item.localidade_id, "destino": row["destino"], "itens": []})
        group["itens"].append(row)
    return list(grupos.values())


def criar_remessa(db: Session, entrada: RemessaEntrada):
    obter(db, Localidade, entrada.localidade_id)
    ids = [x.item_id for x in entrada.itens]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Selecione cada item uma única vez.")
    # Mesmo ordenamento evita deadlocks; o lock protege o saldo contra reservas concorrentes.
    items = list(db.scalars(select(Item).where(Item.id.in_(ids)).order_by(Item.id).with_for_update()))
    if len(items) != len(ids):
        raise HTTPException(404, "Um dos materiais não foi encontrado.")
    totais = quantidades(db, ids)
    quant = {x.item_id: x.quantidade for x in entrada.itens}
    origem = texto_chave(entrada.origem_expedicao)
    for item in items:
        if item.localidade_id != entrada.localidade_id:
            raise HTTPException(422, "Uma remessa deve ter apenas uma localidade de destino.")
        if item.revisao or item.quantidade is None:
            raise HTTPException(409, "Confira os itens com revisão pendente antes de criar a remessa.")
        if origem == "LOCAL":
            apto = item.status == "separado"
        else:
            apto = item.status == "outro_local" and texto_chave(item.local_origem) == origem
        if not apto:
            raise HTTPException(409, "Material não separado ou origem incompatível com a remessa.")
        saldo = _saldos(item, totais)[2]
        if quant[item.id] > saldo:
            raise HTTPException(409, "Quantidade excede o saldo disponível; parte pode estar em outra remessa.")
    r = Remessa(localidade_id=entrada.localidade_id, origem_expedicao=origem, observacoes=entrada.observacoes)
    db.add(r)
    db.flush()
    for item in items:
        db.add(RemessaItem(remessa_id=r.id, item_id=item.id, quantidade=quant[item.id]))
    db.flush()
    return r


def remessa_saida(r: Remessa):
    return {"id": r.id, "localidade_id": r.localidade_id, "destino": r.localidade.nome,
            "origem_expedicao": r.origem_expedicao, "status": r.status, "nf": r.nf,
            "nf_solicitada_em": r.nf_solicitada_em, "data_entrega_logistica": r.data_entrega_logistica,
            "observacoes": r.observacoes, "criado_em": r.criado_em,
            "itens": [{"item_id": ri.item_id, "projeto_id": ri.item.projeto_id,
                       "codigo_projeto": ri.item.projeto.codigo, "descricao": ri.item.descricao,
                       "serial": ri.item.serial, "quantidade": ri.quantidade} for ri in r.itens]}


def reconciliar_legado(db: Session, id: str, entrada):
    r = carregar_remessa(db, id, lock=True)
    if r.status != "legado_revisar":
        raise HTTPException(409, "Somente envios legados pendentes podem ser reconciliados.")
    ids = [x.item_id for x in entrada.itens]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Selecione cada item uma única vez.")
    items = list(db.scalars(select(Item).where(Item.id.in_(ids)).order_by(Item.id).with_for_update()))
    if len(items) != len(ids):
        raise HTTPException(404, "Um dos materiais não foi encontrado.")
    totais = quantidades(db, ids)
    quant = {x.item_id: x.quantidade for x in entrada.itens}
    for item in items:
        if item.localidade_id != r.localidade_id or item.quantidade is None:
            raise HTTPException(422, "Confira o destino e a quantidade do material.")
        if quant[item.id] > _saldos(item, totais)[2]:
            raise HTTPException(409, "Quantidade excede saldo disponível.")
    for item in items:
        db.add(RemessaItem(remessa_id=r.id, item_id=item.id, quantidade=quant[item.id]))
    r.nf = entrada.nf
    r.data_entrega_logistica = entrada.data_entrega_logistica
    r.status = "entregue_logistica" if entrada.data_entrega_logistica else "nf_registrada"
    r.observacoes += " Quantidades conferidas explicitamente pela API."
    db.flush()
    return r
