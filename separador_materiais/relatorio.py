"""
relatorio.py
============

Relatório em **PDF** do que foi **enviado** (itens, por projeto/PSC e por local),
com a **logo da empresa** no cabeçalho.

Um local (destino) é considerado "enviado" quando tem **NF de envio** ou
**Data de envio** preenchida na tela de Separação.

A logo é procurada em ``assets/logo_eletronet.png``. Ela pode ser definida pela
interface (upload) — ver :func:`salvar_logo`.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fpdf import FPDF
from PIL import Image

PASTA_ASSETS = Path(__file__).parent / "assets"
LOGO_PATH = PASTA_ASSETS / "logo_eletronet.png"


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

def caminho_logo() -> Optional[Path]:
    return LOGO_PATH if LOGO_PATH.exists() else None


def salvar_logo(conteudo: bytes) -> None:
    """Salva a logo (qualquer formato de imagem) como PNG em assets/."""
    PASTA_ASSETS.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(conteudo)).convert("RGB")
    img.save(LOGO_PATH, format="PNG")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lat(valor: object) -> str:
    """Texto seguro para as fontes core do PDF (latin-1)."""
    return str("" if valor is None else valor).encode("latin-1", "replace").decode("latin-1")


def _fmt_data(s: Optional[str]) -> str:
    if not s:
        return "-"
    try:
        return date.fromisoformat(s).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(s)


def _locais_enviados(projeto: dict) -> set[str]:
    envios = projeto.get("envios", {})
    return {d for d, v in envios.items() if (v.get("nf") or v.get("data_envio"))}


class _Relatorio(FPDF):
    titulo = "Relatório de Envio de Materiais"

    def header(self) -> None:
        logo = caminho_logo()
        if logo:
            try:
                self.image(str(logo), x=10, y=8, h=12)
            except Exception:  # noqa: BLE001
                pass
        self.set_y(9)
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 9, text=_lat(self.titulo), align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(170, 170, 170)
        self.line(10, self.get_y() + 1, 200, self.get_y() + 1)
        self.set_y(self.get_y() + 4)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 8, text=_lat(f"Página {self.page_no()}/{{nb}}"), align="C")


# ---------------------------------------------------------------------------
# Geração do relatório
# ---------------------------------------------------------------------------

def _novo_pdf(titulo: str) -> "_Relatorio":
    pdf = _Relatorio(orientation="P", unit="mm", format="A4")
    pdf.titulo = titulo
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, text=_lat(f"Gerado em {datetime.now():%d/%m/%Y %H:%M}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    return pdf


def _cabecalho_projeto(pdf, projeto: dict) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(228, 230, 245)
    pdf.cell(0, 7, text=_lat(f"PSC {projeto.get('psc', '')}"),
             fill=True, new_x="LMARGIN", new_y="NEXT")
    if projeto.get("arquivo"):
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, text=_lat(f"Arquivo: {projeto['arquivo']}"),
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _tabela_itens(pdf, itens: list[dict], mostrar_sep: bool = True) -> None:
    if mostrar_sep:
        widths = (12, 52, 22, 32, 22, 16)
        heads = ("Qtd", "Item", "Tipo", "Serial/Tamanho", "Ação", "Sep.")
        aligns = ("CENTER", "LEFT", "LEFT", "LEFT", "LEFT", "CENTER")
    else:
        widths = (14, 62, 26, 40, 24)
        heads = ("Qtd", "Item", "Tipo", "Serial/Tamanho", "Ação")
        aligns = ("CENTER", "LEFT", "LEFT", "LEFT", "LEFT")
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(col_widths=widths, text_align=aligns, first_row_as_headings=True) as table:
        linha = table.row()
        for h in heads:
            linha.cell(_lat(h))
        for i in itens:
            r = table.row()
            r.cell(_lat(i.get("quantidade") if i.get("quantidade") is not None else ""))
            r.cell(_lat(i.get("item", "")))
            r.cell(_lat(i.get("tipo", "")))
            r.cell(_lat(i.get("serial", "")))
            r.cell(_lat(i.get("acao", "")))
            if mostrar_sep:
                r.cell(_lat("Sim" if i.get("separado") else "Não"))


def _rodape_total(pdf, algum: bool, total: int, rotulo: str, msg_vazio: str) -> None:
    if not algum:
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, text=_lat(msg_vazio), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, text=_lat(f"Total de itens {rotulo}: {total}"),
                 new_x="LMARGIN", new_y="NEXT")


def gerar_relatorio_envio(projetos: list[dict], titulo: Optional[str] = None) -> bytes:
    """PDF do que foi ENVIADO (locais com NF ou data de envio)."""
    pdf = _novo_pdf(titulo or "Relatório de Envio de Materiais")
    total, algum = 0, False
    for projeto in projetos:
        locais = _locais_enviados(projeto)
        itens_proj = [i for i in projeto.get("itens", []) if i.get("destino") in locais]
        if not itens_proj:
            continue
        algum = True
        _cabecalho_projeto(pdf, projeto)
        envios = projeto.get("envios", {})
        for local in sorted(locais):
            itens_local = [i for i in itens_proj if i.get("destino") == local]
            if not itens_local:
                continue
            env = envios.get(local, {})
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(
                0, 6,
                text=_lat(f"Local: {local}    |    NF: {env.get('nf') or '-'}"
                          f"    |    Data: {_fmt_data(env.get('data_envio'))}"),
                new_x="LMARGIN", new_y="NEXT",
            )
            _tabela_itens(pdf, itens_local, mostrar_sep=True)
            total += len(itens_local)
            pdf.ln(3)
        pdf.ln(2)
    _rodape_total(pdf, algum, total, "enviados",
                  "Nenhum local com envio registrado. Preencha NF e/ou Data de envio.")
    return bytes(pdf.output())


def gerar_relatorio_sem_estoque(projetos: list[dict], titulo: Optional[str] = None) -> bytes:
    """PDF dos itens marcados como SEM ESTOQUE (em falta), por projeto e local."""
    pdf = _novo_pdf(titulo or "Relatório de Itens em Falta (Sem Estoque)")
    total, algum = 0, False
    for projeto in projetos:
        faltam = [i for i in projeto.get("itens", []) if i.get("sem_estoque")]
        if not faltam:
            continue
        algum = True
        _cabecalho_projeto(pdf, projeto)
        for local in sorted({i.get("destino", "") for i in faltam}):
            itens_local = [i for i in faltam if i.get("destino", "") == local]
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, text=_lat(f"Local: {local or '(sem destino)'}"),
                     new_x="LMARGIN", new_y="NEXT")
            _tabela_itens(pdf, itens_local, mostrar_sep=False)
            total += len(itens_local)
            pdf.ln(3)
        pdf.ln(2)
    _rodape_total(pdf, algum, total, "em falta",
                  "Nenhum item marcado como 'Sem estoque'.")
    return bytes(pdf.output())
