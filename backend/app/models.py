from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Projeto(Base):
    __tablename__ = "api_projetos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    arquivo: Mapped[str] = mapped_column(Text, default="")
    paginas: Mapped[int] = mapped_column(Integer, default=0)
    metodo: Mapped[str] = mapped_column(String(40), default="manual")
    projetista: Mapped[str] = mapped_column(Text, default="")
    responsavel_implantacao: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    itens: Mapped[list["Item"]] = relationship(back_populates="projeto", order_by="Item.ordem")


class Localidade(Base):
    __tablename__ = "api_localidades"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    nome: Mapped[str] = mapped_column(Text)
    chave: Mapped[str] = mapped_column(Text, unique=True)


class Item(Base):
    __tablename__ = "api_itens"
    __table_args__ = (
        CheckConstraint("quantidade IS NULL OR quantidade > 0", name="item_quantidade_positiva"),
        CheckConstraint("status IN ('nao_separado','separado','outro_local','sem_estoque')", name="item_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("api_projetos.id"), index=True)
    localidade_id: Mapped[str | None] = mapped_column(ForeignKey("api_localidades.id"), index=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    descricao: Mapped[str] = mapped_column(Text, default="")
    quantidade: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="nao_separado")
    local_origem: Mapped[str] = mapped_column(Text, default="")
    tipo: Mapped[str] = mapped_column(Text, default="")
    serial: Mapped[str] = mapped_column(Text, default="")
    origem: Mapped[str] = mapped_column(Text, default="")
    responsavel: Mapped[str] = mapped_column(Text, default="")
    acao: Mapped[str] = mapped_column(Text, default="")
    observacoes: Mapped[str] = mapped_column(Text, default="")
    revisao: Mapped[str] = mapped_column(Text, default="")
    projeto: Mapped[Projeto] = relationship(back_populates="itens")
    localidade: Mapped[Localidade | None] = relationship()


class Remessa(Base):
    __tablename__ = "api_remessas"
    __table_args__ = (
        CheckConstraint("status IN ('rascunho','nf_solicitada','nf_registrada','entregue_logistica','cancelada','legado_revisar')", name="remessa_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    localidade_id: Mapped[str] = mapped_column(ForeignKey("api_localidades.id"), index=True)
    # Origens distintas nunca entram automaticamente na mesma remessa.
    origem_expedicao: Mapped[str] = mapped_column(Text, default="LOCAL")
    status: Mapped[str] = mapped_column(String(24), default="rascunho")
    nf: Mapped[str] = mapped_column(Text, default="")
    nf_solicitada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_entrega_logistica: Mapped[date | None] = mapped_column(Date)
    observacoes: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    localidade: Mapped[Localidade] = relationship()
    itens: Mapped[list["RemessaItem"]] = relationship(order_by="RemessaItem.item_id")


class RemessaItem(Base):
    __tablename__ = "api_remessa_itens"
    __table_args__ = (
        UniqueConstraint("remessa_id", "item_id"),
        CheckConstraint("quantidade > 0", name="remessa_item_quantidade_positiva"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    remessa_id: Mapped[str] = mapped_column(ForeignKey("api_remessas.id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("api_itens.id"), index=True)
    quantidade: Mapped[int] = mapped_column(Integer)
    item: Mapped[Item] = relationship()


class ImportacaoLegada(Base):
    __tablename__ = "api_importacoes_legadas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("api_projetos.id"), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    nome_arquivo: Mapped[str] = mapped_column(Text)
    original: Mapped[dict] = mapped_column(JSON)
    avisos: Mapped[list] = mapped_column(JSON)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
