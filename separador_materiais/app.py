"""
app.py
======

Interface web local (Streamlit) do **Separador de Materiais por Local**.

Telas (barra lateral):
    1. 📤 Projetos    — subir PDF/DOCX/DOC (informando as duas pessoas do
       projeto), extrair a tabela e conferir. Fica salvo no PostgreSQL.
    2. 📦 Separação   — tabela de itens editável, NF/data por local e o botão
       **Concluir projeto** (que o oculta das telas de trabalho).
    3. 📊 Consolidado — itens de todos os projetos, com filtros (entregue/falta)
       e os relatórios em PDF.
    4. ✅ Concluídos  — projetos concluídos (só leitura), com reabertura.

Os dados ficam no PostgreSQL (ver persistencia.py / db.py).

Execução:  streamlit run app.py
"""

from __future__ import annotations

import io
import os
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import persistencia as ps
import relatorio
from extracao import ErroExtracao, criar_conversor, extrair
from extracao_docx import extrair_tabela_doc, extrair_tabela_docx
from extracao_imagem import criar_leitor, extrair_tabela_imagem, extrair_tabela_texto
from normalizacao import normalizar_tabela

#: Formatos aceitos no upload.
FORMATOS = ["pdf", "docx", "doc"]
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Colunas exportadas dos itens (Excel/CSV), na ordem.
_COLS_EXPORT = ["quantidade", "item", "tipo", "serial", "origem", "responsavel",
                "acao", "separado", "sem_estoque", "nf_envio", "data_envio"]


# ---------------------------------------------------------------------------
# Banco de dados + recursos cacheados
# ---------------------------------------------------------------------------

def _secrets_para_ambiente() -> None:
    """Copia credenciais de .streamlit/secrets.toml para variáveis de ambiente
    (sem sobrescrever as já definidas). Opcional — o default é o docker-compose."""
    try:
        seg = st.secrets
        if "DATABASE_URL" in seg:
            os.environ.setdefault("DATABASE_URL", str(seg["DATABASE_URL"]))
        pg = seg["postgres"] if "postgres" in seg else {}
        for chave, env in {"host": "PGHOST", "port": "PGPORT", "user": "PGUSER",
                           "password": "PGPASSWORD", "dbname": "PGDATABASE",
                           "database": "PGDATABASE"}.items():
            if chave in pg:
                os.environ.setdefault(env, str(pg[chave]))
    except Exception:  # noqa: BLE001 - sem secrets.toml é o caso normal
        pass


@st.cache_resource(show_spinner="Conectando ao banco de dados...")
def _init_db() -> bool:
    _secrets_para_ambiente()
    ps.inicializar()
    return True


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
        "ok": True, "numero_psc": extr.numero_psc, "paginas": extr.paginas,
        "metodo": extr.metodo, "imagem_png": extr.imagem_png, "itens": norm.itens,
    }


# ---------------------------------------------------------------------------
# Helpers de UI / formatação
# ---------------------------------------------------------------------------

def _parse_data(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def _fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(s)


def _config_colunas(somente_leitura: bool = False) -> dict:
    cb = lambda rot, ajuda="": st.column_config.CheckboxColumn(  # noqa: E731
        rot, default=False, help=ajuda, disabled=somente_leitura)
    return {
        "separado": cb("✔ Separado"),
        "sem_estoque": cb("⛔ Sem estoque", "Itens que NÃO há em estoque (em falta)"),
        "destino": st.column_config.TextColumn("Destino"),
        "quantidade": st.column_config.NumberColumn("Qtd", min_value=0, step=1),
        "item": st.column_config.TextColumn("Item", width="large"),
        "tipo": st.column_config.TextColumn("Tipo"),
        "serial": st.column_config.TextColumn("Serial / Tamanho",
                                              help="Nº de série do equipamento ou tamanho do cordão"),
        "origem": st.column_config.TextColumn("Origem"),
        "responsavel": st.column_config.TextColumn("Responsável"),
        "acao": st.column_config.TextColumn("Ação"),
    }


def _entregue(item: dict, envios: dict) -> bool:
    """Regra de negócio: 'entregue' = item separado E destino com NF ou data de envio."""
    env = envios.get(item.get("destino", ""), {})
    return bool(item.get("separado")) and bool(env.get("nf") or env.get("data_envio"))


def _linhas_consolidado(projetos: list[dict]) -> pd.DataFrame:
    """Achata os itens de vários projetos numa tabela, com a coluna ``entregue``."""
    linhas = []
    for p in projetos:
        envios = p.get("envios", {})
        for i in p.get("itens", []):
            d = i.get("destino", "")
            env = envios.get(d, {})
            linhas.append({
                "psc": p["psc"], "destino": d, "quantidade": i.get("quantidade"),
                "item": i.get("item", ""), "tipo": i.get("tipo", ""),
                "serial": i.get("serial", ""), "origem": i.get("origem", ""),
                "responsavel": i.get("responsavel", ""), "acao": i.get("acao", ""),
                "separado": bool(i.get("separado")), "sem_estoque": bool(i.get("sem_estoque")),
                "entregue": _entregue(i, envios),
                "nf_envio": env.get("nf", ""), "data_envio": env.get("data_envio", ""),
            })
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def _nome_aba(nome: str, usados: set[str]) -> str:
    base = (re.sub(r"[:\\/?*\[\]]", " ", str(nome)).strip() or "Destino")[:31]
    cand, i = base, 2
    while cand in usados:
        sufixo = f" ({i})"
        cand = base[: 31 - len(sufixo)] + sufixo
        i += 1
    usados.add(cand)
    return cand


def _excel_por_destino(df: pd.DataFrame, cols: list[str], nome_vazio: str) -> bytes:
    """Excel com uma aba por destino (ou uma aba vazia se não houver itens)."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if df.empty:
            pd.DataFrame(columns=cols).to_excel(writer, sheet_name=nome_vazio, index=False)
        else:
            usados: set[str] = set()
            for destino, grupo in df.groupby("destino", sort=True):
                grupo[cols].to_excel(writer, sheet_name=_nome_aba(destino, usados), index=False)
    return buffer.getvalue()


def _df_export(projeto: dict) -> pd.DataFrame:
    """DataFrame de exportação com NF/data por destino em cada linha."""
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
    return _excel_por_destino(df, _COLS_EXPORT, "Separacao")


def gerar_excel_consolidado(df: pd.DataFrame) -> bytes:
    return _excel_por_destino(df, ["psc", *_COLS_EXPORT], "Consolidado")


# ---------------------------------------------------------------------------
# TELA 1 — Projetos (subir e conferir)
# ---------------------------------------------------------------------------

def tela_projetos() -> None:
    st.header("📤 Projetos — subir e conferir")
    st.caption("Envie os arquivos (**PDF, DOCX ou DOC**). A tabela é extraída e salva no "
               "banco — nas próximas vezes os projetos já aparecem aqui e na Separação.")

    st.markdown("##### 👥 Pessoas do projeto (aplicadas aos arquivos enviados abaixo)")
    c1, c2 = st.columns(2)
    autor = c1.text_input("👤 Projetista (quem fez o projeto)", key="up_autor")
    resp = c2.text_input("🛠️ Responsável pela implantação (dá seguimento)", key="up_resp")

    arquivos = st.file_uploader(
        "Enviar PSC/PS (PDF, DOCX ou DOC)", type=FORMATOS, accept_multiple_files=True)

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
                psc, arq.name, res["paginas"], res["metodo"], res["itens"], autor, resp)
            ps.salvar(projeto)
            extra = " (lido por OCR — confira na Separação)" if res["metodo"] == "ocr" else ""
            st.success(f"✅ **{psc}** importado: {len(projeto['itens'])} item(ns){extra}.")
            if res["metodo"] == "ocr" and res.get("imagem_png"):
                with st.expander(f"Prévia da página lida — {psc}"):
                    st.image(res["imagem_png"], use_container_width=True)

    st.divider()
    st.markdown("#### Projetos salvos (ativos)")
    projetos = ps.listar()
    if not projetos:
        st.info("Nenhum projeto ativo. Envie um arquivo acima.")
        return

    for projeto in projetos:
        itens = projeto.get("itens", [])
        sep = sum(1 for i in itens if i.get("separado"))
        psc = projeto["psc"]
        with st.expander(f"📁 {psc} — {len(itens)} item(ns), {sep} separado(s)  ·  "
                         f"{projeto.get('arquivo', '')}"):
            st.caption(
                f"👤 {projeto.get('autor') or '—'}  ·  🛠️ {projeto.get('responsavel_impl') or '—'}"
                f"  ·  páginas: {projeto.get('paginas', '?')}  ·  método: {projeto.get('metodo', '?')}"
                f"  ·  atualizado: {_fmt_dt(projeto.get('atualizado_em'))}")
            if itens:
                st.dataframe(ps.itens_df(projeto).drop(columns=["separado"]),
                             use_container_width=True, hide_index=True)
            col_a, col_b = st.columns([3, 1])
            col_a.caption("Para editar itens, NF e data de envio, use a tela **Separação**.")
            if col_b.button("🗑️ Excluir", key=f"del_{psc}", use_container_width=True):
                ps.excluir(psc)
                st.session_state.pop(f"base_{psc}", None)
                st.rerun()


# ---------------------------------------------------------------------------
# TELA 2 — Separação (editar itens + NF/data + concluir)
# ---------------------------------------------------------------------------

def tela_separacao() -> None:
    st.header("📦 Separação de materiais")
    projetos = ps.listar()
    if not projetos:
        st.info("Nenhum projeto ativo. Vá em **Projetos** e envie um arquivo "
                "(ou reabra um em **Concluídos**).")
        return

    psc = st.selectbox("Projeto (PSC)", [p["psc"] for p in projetos], key="sep_psc")
    projeto = ps.carregar(psc)
    if projeto is None:
        st.error("Projeto não encontrado.")
        return

    # ---- Pessoas do projeto (editáveis)
    c1, c2 = st.columns(2)
    autor = c1.text_input("👤 Projetista", value=projeto.get("autor", ""), key=f"autor_{psc}")
    resp = c2.text_input("🛠️ Responsável pela implantação",
                         value=projeto.get("responsavel_impl", ""), key=f"resp_{psc}")
    if autor.strip() != projeto.get("autor", "") or resp.strip() != projeto.get("responsavel_impl", ""):
        ps.atualizar_pessoas(psc, autor, resp)
    # mantém o dict em memória coerente (um salvar posterior não reverte as pessoas)
    projeto["autor"], projeto["responsavel_impl"] = autor.strip(), resp.strip()

    # ---- Tabela editável (snapshot na sessão; salva ao mudar)
    st.markdown("#### Itens — edite, adicione (➕ no fim) ou remova (selecione a linha)")
    base_key = f"base_{psc}"
    if base_key not in st.session_state:
        st.session_state[base_key] = ps.itens_df(projeto)
    editado = st.data_editor(
        st.session_state[base_key], key=f"editor_{psc}", num_rows="dynamic",
        use_container_width=True, column_config=_config_colunas())
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
            c0.markdown(f"**📍 {d}**  \n<small>{sep_d}/{len(itens_d)} separados</small>",
                        unsafe_allow_html=True)
            nf = c1.text_input("NF de envio", value=atual.get("nf", ""), key=f"nf_{psc}_{d}")
            data = c2.date_input("Data de envio", value=_parse_data(atual.get("data_envio")),
                                 key=f"dt_{psc}_{d}", format="DD/MM/YYYY")
            envios[d] = {"nf": nf.strip(), "data_envio": data.isoformat() if data else ""}
        envios = {d: v for d, v in envios.items() if d in destinos}
        if envios != projeto.get("envios"):
            projeto["envios"] = envios
            ps.salvar(projeto)

    # ---- Exportação e relatórios
    st.divider()
    st.markdown("#### 💾 Exportar")
    base = ps._slug(psc)
    e1, e2, e3 = st.columns(3)
    e1.download_button("⬇️ Excel (todos)", data=gerar_excel_projeto(projeto),
                       file_name=f"separacao_{base}.xlsx", mime=MIME_XLSX, use_container_width=True)
    e2.download_button("⬇️ Excel (pendentes)", data=gerar_excel_projeto(projeto, somente_pendentes=True),
                       file_name=f"separacao_{base}_pendentes.xlsx", mime=MIME_XLSX, use_container_width=True)
    e3.download_button("⬇️ CSV (todos)",
                       data=_df_export(projeto)[["destino", *_COLS_EXPORT]].to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"separacao_{base}.csv", mime="text/csv", use_container_width=True)
    r1, r2 = st.columns(2)
    r1.download_button("📄 Relatório de envio (PDF)",
                       data=relatorio.gerar_relatorio_envio([projeto], titulo=f"Relatorio de Envio - PSC {psc}"),
                       file_name=f"relatorio_envio_{base}.pdf", mime="application/pdf",
                       use_container_width=True, help="Locais com NF ou data de envio preenchida.")
    r2.download_button("📄 Relatório de itens em falta (PDF)",
                       data=relatorio.gerar_relatorio_sem_estoque([projeto], titulo=f"Itens em Falta - PSC {psc}"),
                       file_name=f"itens_falta_{base}.pdf", mime="application/pdf",
                       use_container_width=True, help="Itens marcados como 'Sem estoque'.")
    st.caption("As alterações são salvas automaticamente no banco.")

    # ---- Concluir projeto
    st.divider()
    st.markdown("#### ✅ Conclusão do projeto")
    st.caption("Ao concluir, o projeto **sai** das telas de trabalho e passa a aparecer em "
               "**✅ Concluídos** (pode ser reaberto lá a qualquer momento).")
    if st.button("✅ Concluir projeto", type="primary", key=f"concluir_{psc}"):
        ps.definir_conclusao(psc, True)
        st.session_state.pop(base_key, None)
        st.success(f"Projeto {psc} concluído.")
        st.rerun()


# ---------------------------------------------------------------------------
# TELA 3 — Consolidado (todos os projetos, com filtros)
# ---------------------------------------------------------------------------

_ROTULOS = {
    "psc": "PSC", "quantidade": "Qtd", "item": "Item", "tipo": "Tipo", "serial": "Serial/Tam.",
    "origem": "Origem", "responsavel": "Responsável", "acao": "Ação", "separado": "Separado",
    "entregue": "Entregue", "sem_estoque": "Sem estoque", "nf_envio": "NF", "data_envio": "Data envio",
}
_COLS_VIEW = ["psc", "quantidade", "item", "tipo", "serial", "origem", "responsavel",
              "acao", "separado", "entregue", "sem_estoque", "nf_envio", "data_envio"]


def tela_consolidado() -> None:
    st.header("📊 Consolidado — todos os projetos")

    incluir = st.checkbox("Incluir projetos concluídos", value=False, key="cons_incluir")
    projetos = ps.listar(concluido=None) if incluir else ps.listar()
    df = _linhas_consolidado(projetos)
    if df.empty:
        st.info("Nenhum item para exibir. Envie projetos na tela **Projetos**.")
        return

    # ---- Filtros
    c1, c2, c3 = st.columns(3)
    f_destino = c1.multiselect("Destino", sorted(df["destino"].unique()), key="cons_dest")
    f_psc = c2.multiselect("PSC", sorted(df["psc"].unique()), key="cons_psc")
    f_status = c3.selectbox("Status", ["Todos", "✅ Entregue", "⏳ Falta entregar", "⛔ Sem estoque"],
                            key="cons_status")
    view = df.copy()
    if f_destino:
        view = view[view["destino"].isin(f_destino)]
    if f_psc:
        view = view[view["psc"].isin(f_psc)]
    if f_status == "✅ Entregue":
        view = view[view["entregue"]]
    elif f_status == "⏳ Falta entregar":
        view = view[~view["entregue"]]
    elif f_status == "⛔ Sem estoque":
        view = view[view["sem_estoque"]]

    # ---- Métricas (sobre o conjunto total, não filtrado)
    entregues = int(df["entregue"].sum())
    total = len(df)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Projetos", df["psc"].nunique())
    m2.metric("Itens", total)
    m3.metric("✅ Entregues", entregues)
    m4.metric("⏳ Falta entregar", total - entregues)
    m5.metric("⛔ Sem estoque", int(df["sem_estoque"].sum()))
    st.progress(entregues / total if total else 0.0)

    # ---- Tabela por local
    st.markdown("#### Materiais por local")
    if view.empty:
        st.info("Nenhum item para os filtros selecionados.")
    else:
        conf = {r: st.column_config.CheckboxColumn(disabled=True)
                for r in ("Separado", "Entregue", "Sem estoque")}
        for destino in sorted(view["destino"].unique()):
            g = view[view["destino"] == destino]
            entr = int(g["entregue"].sum())
            with st.expander(f"📍 {destino or '(sem destino)'} — {entr}/{len(g)} entregues  ·  "
                             f"{g['psc'].nunique()} PSC(s)"):
                st.dataframe(g[_COLS_VIEW].rename(columns=_ROTULOS), use_container_width=True,
                             hide_index=True, column_config=conf)

    # ---- Exportação
    st.divider()
    st.markdown("#### 💾 Exportar consolidado")
    cc1, cc2 = st.columns(2)
    cc1.download_button("⬇️ Excel consolidado (por local)", data=gerar_excel_consolidado(df),
                        file_name="consolidado_materiais.xlsx", mime=MIME_XLSX, use_container_width=True)
    cc2.download_button("⬇️ CSV consolidado",
                        data=df[_COLS_VIEW + ["destino"]].rename(columns=_ROTULOS).to_csv(index=False).encode("utf-8-sig"),
                        file_name="consolidado_materiais.csv", mime="text/csv", use_container_width=True)

    _secao_relatorios(projetos)


def _secao_relatorios(projetos: list[dict]) -> None:
    """Relatórios em PDF (envio e itens em falta) + definição da logo."""
    st.divider()
    st.markdown("#### 📄 Relatórios em PDF (todos os projetos exibidos)")
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
        rc1.caption("Sem logo definida (relatório sai só com título). Envie acima.")
    with rc2:
        st.download_button("📄 Relatório de envio", data=relatorio.gerar_relatorio_envio(projetos),
                           file_name="relatorio_envio_geral.pdf", mime="application/pdf",
                           use_container_width=True)
        st.download_button("📄 Relatório de itens em falta", data=relatorio.gerar_relatorio_sem_estoque(projetos),
                           file_name="itens_falta_geral.pdf", mime="application/pdf",
                           use_container_width=True)
        st.caption("Envio: locais com NF/data. Itens em falta: marcados como 'Sem estoque'.")


# ---------------------------------------------------------------------------
# TELA 4 — Concluídos (só leitura + reabrir)
# ---------------------------------------------------------------------------

def tela_concluidos() -> None:
    st.header("✅ Projetos concluídos")
    projetos = ps.listar(concluido=True)
    if not projetos:
        st.info("Nenhum projeto concluído ainda. Conclua um na tela **Separação**.")
        return
    st.caption(f"{len(projetos)} projeto(s) concluído(s) — só leitura. Reabra para voltar a editar.")

    conf = {"✔ Separado": st.column_config.CheckboxColumn(disabled=True),
            "⛔ Sem estoque": st.column_config.CheckboxColumn(disabled=True)}
    for projeto in projetos:
        psc = projeto["psc"]
        itens = projeto.get("itens", [])
        sep = sum(1 for i in itens if i.get("separado"))
        base = ps._slug(psc)
        with st.expander(f"✅ {psc} — {len(itens)} item(ns), {sep} separado(s)  ·  "
                         f"concluído em {_fmt_dt(projeto.get('concluido_em'))}"):
            st.caption(f"👤 {projeto.get('autor') or '—'}  ·  🛠️ {projeto.get('responsavel_impl') or '—'}"
                       f"  ·  {projeto.get('arquivo', '')}")
            if itens:
                st.dataframe(ps.itens_df(projeto), use_container_width=True, hide_index=True,
                             column_config=conf)
            b1, b2, b3 = st.columns(3)
            b1.download_button("📄 Relatório de envio",
                               data=relatorio.gerar_relatorio_envio([projeto], titulo=f"Relatorio de Envio - PSC {psc}"),
                               file_name=f"relatorio_envio_{base}.pdf", mime="application/pdf",
                               use_container_width=True, key=f"rel_env_{psc}")
            b2.download_button("📄 Itens em falta",
                               data=relatorio.gerar_relatorio_sem_estoque([projeto], titulo=f"Itens em Falta - PSC {psc}"),
                               file_name=f"itens_falta_{base}.pdf", mime="application/pdf",
                               use_container_width=True, key=f"rel_falta_{psc}")
            if b3.button("↩️ Reabrir projeto", key=f"reabrir_{psc}", use_container_width=True):
                ps.definir_conclusao(psc, False)
                st.rerun()


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

_TELAS = {
    "📤 Projetos": tela_projetos,
    "📦 Separação": tela_separacao,
    "📊 Consolidado": tela_consolidado,
    "✅ Concluídos": tela_concluidos,
}


def main() -> None:
    st.set_page_config(page_title="Separador de Materiais — PSC/PS", page_icon="📦", layout="wide")
    st.sidebar.title("📦 Separador de Materiais")
    st.sidebar.caption("PSC/PS Eletronet")

    try:
        _init_db()
    except Exception as erro:  # noqa: BLE001
        st.error("Não foi possível conectar ao PostgreSQL.")
        st.code(str(erro))
        st.info("Suba o banco com `docker compose up -d` (na pasta do projeto) ou defina "
                "`DATABASE_URL` / variáveis `PG*`. Veja o README.")
        st.stop()

    escolha = st.sidebar.radio("Tela", list(_TELAS), label_visibility="collapsed")
    _TELAS[escolha]()


def _rodar() -> None:
    """Permite executar via ``streamlit run app.py`` ou ``python app.py``."""
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
