"""
app.py
======

Interface web local (Streamlit) do **Separador de Materiais por Local**.

Telas (navegação na barra lateral):
    1. 📤 Projetos — subir PDF(s), extrair a tabela e conferir; ficam salvos
       em disco (persistência), aparecendo nas próximas vezes sem reenviar.
    2. 📦 Separação — tabela de itens TOTALMENTE EDITÁVEL (editar/criar/remover
       item, mudar nome/quantidade/tipo...), marcação de "separado" e, por
       local (destino), os campos NF de envio e Data de envio.
    3. 📊 Consolidado — itens de todos os projetos, por local e PSC.

Tudo é persistido automaticamente em ``dados/projetos/`` (ver persistencia.py).

Execução:  streamlit run app.py
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import persistencia as ps
import relatorio
from extracao import ErroExtracao, criar_conversor, extrair
from extracao_docx import extrair_tabela_doc, extrair_tabela_docx
from extracao_imagem import (
    criar_leitor,
    extrair_tabela_imagem,
    extrair_tabela_texto,
)
from normalizacao import normalizar_tabela

#: Formatos aceitos no upload.
FORMATOS = ["pdf", "docx", "doc"]

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Recursos cacheados (leitores pesados criados só quando usados)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def obter_conversor():
    return criar_conversor()


@st.cache_resource(show_spinner=False)
def obter_leitor():
    return criar_leitor()


def _extrair_pdf(conteudo: bytes, nome: str):
    """Cadeia de extração de PDF: texto nativo -> OCR -> Docling."""
    try:
        return extrair_tabela_texto(conteudo, nome)
    except ErroExtracao:
        try:
            return extrair_tabela_imagem(conteudo, nome, obter_leitor())
        except ErroExtracao:
            return extrair(conteudo, nome, obter_conversor())  # pode levantar ErroExtracao


@st.cache_data(show_spinner=False)
def processar(nome: str, conteudo: bytes) -> dict:
    """Extrai e normaliza um documento (PDF/DOCX/DOC), cacheado pelos bytes."""
    ext = Path(nome).suffix.lower()
    try:
        if ext == ".pdf":
            extr = _extrair_pdf(conteudo, nome)
        elif ext == ".docx":
            extr = extrair_tabela_docx(conteudo, nome)
        elif ext == ".doc":
            extr = extrair_tabela_doc(conteudo, nome)
        else:
            return {"ok": False, "erro": f"Formato não suportado: {ext or '?'}"}
    except ErroExtracao as erro:
        return {"ok": False, "erro": str(erro)}

    norm = normalizar_tabela(extr.df)
    return {
        "ok": True,
        "numero_psc": extr.numero_psc,
        "paginas": extr.paginas,
        "metodo": extr.metodo,
        "aviso": extr.aviso,
        "imagem_png": extr.imagem_png,
        "itens": norm.itens,
        "revisar": norm.revisar,
    }


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def _nome_aba(nome: str, usados: set[str]) -> str:
    limpo = re.sub(r"[:\\/?*\[\]]", " ", str(nome)).strip() or "Destino"
    base = limpo[:31]
    cand, i = base, 2
    while cand in usados:
        sufixo = f" ({i})"
        cand = base[: 31 - len(sufixo)] + sufixo
        i += 1
    usados.add(cand)
    return cand


_COLS_EXPORT = ["quantidade", "item", "tipo", "serial", "origem", "responsavel", "acao", "separado", "sem_estoque", "nf_envio", "data_envio"]


def _df_export(projeto: dict) -> pd.DataFrame:
    """DataFrame de exportação com NF/data por destino preenchidas em cada linha."""
    itens = projeto.get("itens", [])
    envios = projeto.get("envios", {})
    df = pd.DataFrame(itens) if itens else pd.DataFrame(columns=ps.COLUNAS_ITEM)
    df["nf_envio"] = df["destino"].map(lambda d: envios.get(d, {}).get("nf", ""))
    df["data_envio"] = df["destino"].map(lambda d: envios.get(d, {}).get("data_envio", ""))
    return df


def gerar_excel_projeto(projeto: dict, somente_pendentes: bool = False) -> bytes:
    df = _df_export(projeto)
    if somente_pendentes and not df.empty:
        df = df[~df["separado"].fillna(False).astype(bool)]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if df.empty:
            pd.DataFrame(columns=_COLS_EXPORT).to_excel(writer, sheet_name="Separacao", index=False)
        else:
            usados: set[str] = set()
            for destino, grupo in df.groupby("destino", sort=True):
                grupo[_COLS_EXPORT].to_excel(writer, sheet_name=_nome_aba(destino, usados), index=False)
    return buffer.getvalue()


def gerar_excel_consolidado(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    cols = ["psc", *_COLS_EXPORT]
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if df.empty:
            pd.DataFrame(columns=cols).to_excel(writer, sheet_name="Consolidado", index=False)
        else:
            usados: set[str] = set()
            for destino, grupo in df.groupby("destino", sort=True):
                grupo[cols].to_excel(writer, sheet_name=_nome_aba(destino, usados), index=False)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Configuração da tabela editável
# ---------------------------------------------------------------------------

def _config_colunas() -> dict:
    return {
        "separado": st.column_config.CheckboxColumn("✔ Separado", default=False),
        "sem_estoque": st.column_config.CheckboxColumn("⛔ Sem estoque", default=False, help="Marque os itens que NÃO há em estoque (em falta)"),
        "destino": st.column_config.TextColumn("Destino"),
        "quantidade": st.column_config.NumberColumn("Qtd", min_value=0, step=1),
        "item": st.column_config.TextColumn("Item", width="large"),
        "tipo": st.column_config.TextColumn("Tipo"),
        "serial": st.column_config.TextColumn("Serial / Tamanho", help="Nº de série do equipamento ou tamanho do cordão"),
        "origem": st.column_config.TextColumn("Origem"),
        "responsavel": st.column_config.TextColumn("Responsável"),
        "acao": st.column_config.TextColumn("Ação"),
    }


def _parse_data(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# TELA 1 — Projetos (subir e conferir)
# ---------------------------------------------------------------------------

def tela_projetos() -> None:
    st.header("📤 Projetos — subir e conferir")
    st.caption(
        "Envie os arquivos dos PSC/PS (**PDF, DOCX ou DOC**). A tabela é extraída "
        "e **salva em disco** — nas próximas vezes os projetos já aparecem aqui e "
        "na tela de Separação."
    )

    arquivos = st.file_uploader(
        "Enviar PSC/PS (PDF, DOCX ou DOC)", type=FORMATOS, accept_multiple_files=True
    )

    if arquivos:
        st.markdown("#### Resultado da importação")
        for arq in arquivos:
            with st.spinner(f"Lendo '{arq.name}'..."):
                res = processar(arq.name, arq.getvalue())

            if not res["ok"]:
                st.error(f"❌ {arq.name}: {res['erro']}")
                continue

            psc = res["numero_psc"] or Path(arq.name).stem
            if ps.existe(psc):
                st.info(f"↩️ **{psc}** já está salvo ({arq.name}). Edite na tela de Separação.")
                continue

            projeto = ps.projeto_de_extracao(
                psc, arq.name, res["paginas"], res["metodo"], res["itens"]
            )
            ps.salvar(projeto)
            extra = " (lido por OCR — confira na Separação)" if res["metodo"] == "ocr" else ""
            st.success(f"✅ **{psc}** importado: {len(projeto['itens'])} item(ns){extra}.")
            if res["metodo"] == "ocr" and res.get("imagem_png"):
                with st.expander(f"Prévia da página lida — {psc}"):
                    st.image(res["imagem_png"], use_container_width=True)

    st.divider()
    st.markdown("#### Projetos salvos")
    projetos = ps.listar()
    if not projetos:
        st.info("Nenhum projeto salvo ainda. Envie um PDF acima.")
        return

    for projeto in projetos:
        itens = projeto.get("itens", [])
        n = len(itens)
        sep = sum(1 for i in itens if i.get("separado"))
        psc = projeto["psc"]
        with st.expander(
            f"📁 {psc} — {n} item(ns), {sep} separado(s)  ·  {projeto.get('arquivo', '')}"
        ):
            st.caption(
                f"Páginas: {projeto.get('paginas', '?')}  ·  método: {projeto.get('metodo', '?')}"
                f"  ·  atualizado: {projeto.get('atualizado_em', '?')}"
            )
            if itens:
                st.dataframe(
                    ps.itens_df(projeto).drop(columns=["separado"]),
                    use_container_width=True,
                    hide_index=True,
                )
            col_a, col_b = st.columns([3, 1])
            col_a.caption("Para editar itens, NF e data de envio, use a tela **Separação**.")
            if col_b.button("🗑️ Excluir", key=f"del_{psc}", use_container_width=True):
                ps.excluir(psc)
                st.session_state.pop(f"base_{psc}", None)
                st.rerun()


# ---------------------------------------------------------------------------
# TELA 2 — Separação (editar itens + NF/data por local)
# ---------------------------------------------------------------------------

def tela_separacao() -> None:
    st.header("📦 Separação de materiais")
    projetos = ps.listar()
    if not projetos:
        st.info("Nenhum projeto salvo. Vá em **Projetos** e envie um PDF.")
        return

    pscs = [p["psc"] for p in projetos]
    psc = st.selectbox("Projeto (PSC)", pscs, key="sep_psc")
    projeto = ps.carregar(psc)
    if projeto is None:
        st.error("Projeto não encontrado.")
        return

    # ---- Tabela editável (fonte: snapshot na sessão; salva em disco ao mudar)
    st.markdown("#### Itens — edite, adicione (➕ no fim) ou remova (selecione a linha)")
    base_key = f"base_{psc}"
    if base_key not in st.session_state:
        st.session_state[base_key] = ps.itens_df(projeto)

    editado = st.data_editor(
        st.session_state[base_key],
        key=f"editor_{psc}",
        num_rows="dynamic",
        use_container_width=True,
        column_config=_config_colunas(),
    )
    novos = ps.df_para_itens(editado)
    if novos != projeto.get("itens"):
        projeto["itens"] = novos
        ps.salvar(projeto)

    # ---- Métricas
    total = len(novos)
    feitos = sum(1 for i in novos if i["separado"])
    faltam = sum(1 for i in novos if i.get("sem_estoque"))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Itens", total)
    m2.metric("Separados", feitos)
    m3.metric("Pendentes", total - feitos)
    m4.metric("⛔ Sem estoque", faltam)
    st.progress(feitos / total if total else 0.0)

    # ---- Envio por local (NF + data)
    st.markdown("#### 🚚 Envio por local (NF e data)")
    destinos = sorted({i["destino"] for i in novos if i["destino"]})
    envios = dict(projeto.get("envios", {}))
    if not destinos:
        st.caption("Sem destinos ainda — adicione itens acima.")
    else:
        for d in destinos:
            atual = envios.get(d, {})
            itens_d = [i for i in novos if i["destino"] == d]
            sep_d = sum(1 for i in itens_d if i["separado"])
            c0, c1, c2 = st.columns([3, 2, 2])
            c0.markdown(f"**📍 {d}**  \n<small>{sep_d}/{len(itens_d)} separados</small>", unsafe_allow_html=True)
            nf = c1.text_input("NF de envio", value=atual.get("nf", ""), key=f"nf_{psc}_{d}")
            data = c2.date_input(
                "Data de envio",
                value=_parse_data(atual.get("data_envio")),
                key=f"dt_{psc}_{d}",
                format="DD/MM/YYYY",
            )
            envios[d] = {"nf": nf.strip(), "data_envio": data.isoformat() if data else ""}
        # remove envios de destinos que não existem mais
        envios = {d: v for d, v in envios.items() if d in destinos}
        if envios != projeto.get("envios"):
            projeto["envios"] = envios
            ps.salvar(projeto)

    # ---- Exportação
    st.divider()
    st.markdown("#### 💾 Exportar")
    base = ps._slug(psc)
    e1, e2, e3 = st.columns(3)
    e1.download_button(
        "⬇️ Excel (todos)", data=gerar_excel_projeto(projeto),
        file_name=f"separacao_{base}.xlsx", mime=MIME_XLSX, use_container_width=True,
    )
    e2.download_button(
        "⬇️ Excel (pendentes)", data=gerar_excel_projeto(projeto, somente_pendentes=True),
        file_name=f"separacao_{base}_pendentes.xlsx", mime=MIME_XLSX, use_container_width=True,
    )
    e3.download_button(
        "⬇️ CSV (todos)",
        data=_df_export(projeto)[["destino", *_COLS_EXPORT]].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"separacao_{base}.csv", mime="text/csv", use_container_width=True,
    )

    r1, r2 = st.columns(2)
    r1.download_button(
        "📄 Relatório de envio (PDF)",
        data=relatorio.gerar_relatorio_envio([projeto], titulo=f"Relatorio de Envio - PSC {psc}"),
        file_name=f"relatorio_envio_{base}.pdf",
        mime="application/pdf",
        use_container_width=True,
        help="Locais com NF ou data de envio preenchida.",
    )
    r2.download_button(
        "📄 Relatório de itens em falta (PDF)",
        data=relatorio.gerar_relatorio_sem_estoque([projeto], titulo=f"Itens em Falta - PSC {psc}"),
        file_name=f"itens_falta_{base}.pdf",
        mime="application/pdf",
        use_container_width=True,
        help="Itens marcados como 'Sem estoque'.",
    )

    st.caption("As alterações são salvas automaticamente em disco.")

    # ---- Consolidado (todos os projetos) embutido nesta tela
    st.divider()
    with st.expander("📊 Consolidado — todos os projetos (por local e PSC)", expanded=False):
        secao_consolidado()


# ---------------------------------------------------------------------------
# Consolidado (seção usada dentro da tela de Separação)
# ---------------------------------------------------------------------------

def secao_consolidado() -> None:
    """Visão consolidada de todos os projetos (dentro da tela de Separação)."""
    projetos = ps.listar()

    linhas = []
    for projeto in projetos:
        envios = projeto.get("envios", {})
        for i in projeto.get("itens", []):
            d = i.get("destino", "")
            env = envios.get(d, {})
            linhas.append(
                {
                    "psc": projeto["psc"],
                    "destino": d,
                    "quantidade": i.get("quantidade"),
                    "item": i.get("item", ""),
                    "tipo": i.get("tipo", ""),
                    "serial": i.get("serial", ""),
                    "origem": i.get("origem", ""),
                    "responsavel": i.get("responsavel", ""),
                    "acao": i.get("acao", ""),
                    "separado": bool(i.get("separado", False)),
                    "sem_estoque": bool(i.get("sem_estoque", False)),
                    "nf_envio": env.get("nf", ""),
                    "data_envio": env.get("data_envio", ""),
                }
            )

    if not linhas:
        st.info("Nenhum item salvo. Envie projetos na tela **Projetos**.")
        return

    df = pd.DataFrame(linhas)

    c1, c2, c3 = st.columns(3)
    f_destino = c1.multiselect("Destino", sorted(df["destino"].unique()), key="cons_dest")
    f_psc = c2.multiselect("PSC", sorted(df["psc"].unique()), key="cons_psc")
    f_status = c3.selectbox("Status", ["Todos", "Pendentes", "Separados"], key="cons_status")

    view = df.copy()
    if f_destino:
        view = view[view["destino"].isin(f_destino)]
    if f_psc:
        view = view[view["psc"].isin(f_psc)]
    if f_status == "Pendentes":
        view = view[~view["separado"]]
    elif f_status == "Separados":
        view = view[view["separado"]]

    total = len(df)
    feitos = int(df["separado"].sum())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Projetos", df["psc"].nunique())
    m2.metric("Itens (total)", total)
    m3.metric("Separados", feitos)
    m4.metric("Pendentes", total - feitos)
    st.progress(feitos / total if total else 0.0)

    st.markdown("#### Materiais por local")
    rotulos = {
        "psc": "PSC", "quantidade": "Qtd", "item": "Item", "tipo": "Tipo",
        "serial": "Serial/Tam.", "origem": "Origem", "responsavel": "Responsável",
        "acao": "Ação", "separado": "Separado", "sem_estoque": "Sem estoque",
        "nf_envio": "NF", "data_envio": "Data envio",
    }
    if view.empty:
        st.info("Nenhum item para os filtros selecionados.")
    else:
        for destino in sorted(view["destino"].unique()):
            g = view[view["destino"] == destino]
            fdone = int(g["separado"].sum())
            with st.expander(
                f"📍 {destino} — {fdone}/{len(g)} separados  ·  {g['psc'].nunique()} PSC(s)"
            ):
                tabela = g[
                    ["psc", "quantidade", "item", "tipo", "serial", "origem", "responsavel",
                     "acao", "separado", "sem_estoque", "nf_envio", "data_envio"]
                ].rename(columns=rotulos)
                st.dataframe(
                    tabela, use_container_width=True, hide_index=True,
                    column_config={
                        "Separado": st.column_config.CheckboxColumn(disabled=True),
                        "Sem estoque": st.column_config.CheckboxColumn(disabled=True),
                    },
                )

    st.divider()
    st.markdown("#### 💾 Exportar consolidado")
    cc1, cc2 = st.columns(2)
    cc1.download_button(
        "⬇️ Excel consolidado (por local)", data=gerar_excel_consolidado(df),
        file_name="consolidado_materiais.xlsx", mime=MIME_XLSX, use_container_width=True,
    )
    cc2.download_button(
        "⬇️ CSV consolidado",
        data=df.rename(columns=rotulos).to_csv(index=False).encode("utf-8-sig"),
        file_name="consolidado_materiais.csv", mime="text/csv", use_container_width=True,
    )

    # ---- Relatório de envio em PDF (todos os projetos), com logo
    st.divider()
    st.markdown("#### 📄 Relatório de envio (PDF) — todos os projetos")
    up = st.file_uploader("Logo da empresa (PNG/JPG)", type=["png", "jpg", "jpeg"], key="logo_upload")
    if up is not None:
        sig = (up.name, up.size)
        if st.session_state.get("logo_sig") != sig:
            relatorio.salvar_logo(up.getvalue())
            st.session_state["logo_sig"] = sig
            st.success("Logo salva — será usada nos relatórios.")
    logo = relatorio.caminho_logo()
    rc1, rc2 = st.columns([1, 2])
    if logo:
        rc1.image(str(logo), width=160, caption="Logo do relatório")
    else:
        rc1.caption("Sem logo definida (relatório sai com título em texto). Envie acima.")
    with rc2:
        st.download_button(
            "📄 Relatório de envio (todos os projetos)",
            data=relatorio.gerar_relatorio_envio(projetos),
            file_name="relatorio_envio_geral.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
        st.download_button(
            "📄 Relatório de itens em falta (todos os projetos)",
            data=relatorio.gerar_relatorio_sem_estoque(projetos),
            file_name="itens_falta_geral.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
        st.caption("Envio: locais com NF/data. Itens em falta: marcados como 'Sem estoque'.")


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Separador de Materiais — PSC/PS",
        page_icon="📦",
        layout="wide",
    )
    st.sidebar.title("📦 Separador de Materiais")
    st.sidebar.caption("PSC/PS Eletronet")
    tela = st.sidebar.radio(
        "Tela",
        ["📤 Projetos (subir e conferir)", "📦 Separação"],
        label_visibility="collapsed",
    )

    if tela.startswith("📤"):
        tela_projetos()
    else:
        tela_separacao()


def _rodar() -> None:
    """Permite executar tanto via ``streamlit run app.py`` quanto ``python app.py``."""
    try:
        from streamlit.runtime import exists as _runtime_exists

        em_runtime = _runtime_exists()
    except Exception:  # noqa: BLE001
        em_runtime = False

    if em_runtime:
        main()
        return

    import sys

    from streamlit.web import cli as stcli

    print("Iniciando o servidor do Streamlit...")
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    sys.exit(stcli.main())


if __name__ == "__main__":
    _rodar()
