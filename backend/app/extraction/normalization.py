"""
normalizacao.py
===============

Lógica de negócio para transformar a tabela bruta "Logística de Materiais"
(extraída do PDF) no schema interno usado pelo aplicativo.

Responsabilidades:
    * Guardar o DE-PARA das colunas (fácil de ajustar se o modelo do PDF mudar).
    * Separar a quantidade embutida na descrição do equipamento.
    * Encaminhar linhas problemáticas para uma seção "Revisar" em vez de
      descartá-las silenciosamente.
    * Gerar um identificador estável por item (para persistir o progresso).

Esta camada não conhece a interface nem o leitor de documentos — é puro pandas/Python e,
portanto, fácil de testar.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO (DE-PARA)  —  AJUSTE AQUI SE O MODELO DO PDF MUDAR
# ---------------------------------------------------------------------------

#: Assinatura do cabeçalho usada para localizar a tabela certa entre todas as
#: tabelas do documento. A comparação é feita de forma tolerante (sem acento,
#: sem diferença de caixa e ignorando espaços extras).
CABECALHO_ESPERADO: list[str] = [
    "Destino",
    "Equipamento",
    "Origem",
    "Responsável",
    "Ação",
]

#: De-para: nome da coluna no PDF  ->  nome do campo no schema interno.
MAPEAMENTO_COLUNAS: dict[str, str] = {
    "Destino": "destino",
    "Equipamento": "equipamento",
    "Origem": "origem",
    "Responsável": "responsavel",
    "Ação": "acao",
}

#: Ordem final das colunas (após separar quantidade/item de "equipamento").
COLUNAS_SAIDA: list[str] = [
    "destino",
    "quantidade",
    "item",
    "origem",
    "responsavel",
    "acao",
]

#: Regex que separa a quantidade (número inteiro inicial, com ou sem zero à
#: esquerda — "01", "04", "10") do restante da descrição do equipamento.
_RE_QUANTIDADE = re.compile(r"^\s*(\d+)\s+(.*)$", re.DOTALL)


# ---------------------------------------------------------------------------
# Utilitários de texto
# ---------------------------------------------------------------------------

def normalizar_texto(valor: object) -> str:
    """Remove acentos, baixa a caixa e colapsa espaços. Usado em comparações.

    >>> normalizar_texto("  Responsável ")
    'responsavel'
    """
    if valor is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def _eh_vazio(valor: object) -> bool:
    """True para None, NaN/NA ou string em branco."""
    if valor is None:
        return True
    try:
        if pd.isna(valor):
            return True
    except (TypeError, ValueError):
        pass
    return str(valor).strip() == ""


def _limpar_texto(valor: object) -> str:
    """Converte para string limpa (sem espaços extras); vazio para nulos."""
    if _eh_vazio(valor):
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


# ---------------------------------------------------------------------------
# Regra especial: separar quantidade da descrição
# ---------------------------------------------------------------------------

def separar_quantidade(equipamento: object) -> tuple[Optional[int], str]:
    """Separa a quantidade embutida no início da descrição do equipamento.

    Retorna ``(quantidade, item)``. Se não houver número no início,
    ``quantidade`` é ``None`` (a linha será marcada para revisão) e ``item``
    recebe o texto original.

    >>> separar_quantidade("01 QSFP56 DR4+ MPO")
    (1, 'QSFP56 DR4+ MPO')
    >>> separar_quantidade("08 cordões ópticos (Verificar com a regional)")
    (8, 'cordões ópticos (Verificar com a regional)')
    >>> separar_quantidade("WL5e")
    (None, 'WL5e')
    """
    if _eh_vazio(equipamento):
        return None, ""
    texto = re.sub(r"\s+", " ", str(equipamento)).strip()
    m = _RE_QUANTIDADE.match(texto)
    if not m:
        return None, texto
    quantidade = int(m.group(1))  # int() já remove zeros à esquerda
    item = m.group(2).strip()
    return quantidade, item


# ---------------------------------------------------------------------------
# Normalização da tabela
# ---------------------------------------------------------------------------

@dataclass
class ResultadoNormalizacao:
    """Saída da normalização."""

    itens: pd.DataFrame          # linhas OK, com coluna extra ``id_item``
    revisar: pd.DataFrame        # linhas sem quantidade / com campos faltando
    colunas_faltantes: list[str]  # campos do de-para que não foram encontrados


def _resolver_colunas(df: pd.DataFrame) -> dict[str, str]:
    """Mapeia ``coluna_real_do_df -> campo_interno`` casando por texto
    normalizado (tolerante a acentos/caixa/espaços)."""
    col_por_norm = {normalizar_texto(c): c for c in df.columns}
    resolucao: dict[str, str] = {}
    for nome_pdf, campo in MAPEAMENTO_COLUNAS.items():
        chave = normalizar_texto(nome_pdf)
        if chave in col_por_norm:
            resolucao[col_por_norm[chave]] = campo
    return resolucao


def _remover_linhas_invalidas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove linhas totalmente vazias e repetições do cabeçalho que
    aparecem quando a tabela se estende por várias páginas."""
    colunas = list(MAPEAMENTO_COLUNAS.values())

    # 1) linhas em que todas as colunas relevantes estão vazias
    mask_vazia = pd.Series(True, index=df.index)
    for c in colunas:
        mask_vazia &= df[c].map(_eh_vazio)
    df = df[~mask_vazia]

    # 2) repetição do cabeçalho dentro do corpo
    def eh_cabecalho(row: pd.Series) -> bool:
        return (
            normalizar_texto(row.get("destino")) == "destino"
            and normalizar_texto(row.get("equipamento")) == "equipamento"
        )

    if not df.empty:
        df = df[~df.apply(eh_cabecalho, axis=1)]
    return df


def _gerar_ids(df: pd.DataFrame) -> list[str]:
    """Gera um id estável por linha (hash do conteúdo + contador de
    ocorrência) para chavear o progresso de separação de forma determinística."""
    ids: list[str] = []
    contador: dict[str, int] = {}
    for _, row in df.iterrows():
        base = "|".join(
            str(row[c]) for c in COLUNAS_SAIDA
        )
        n = contador.get(base, 0)
        contador[base] = n + 1
        digest = hashlib.md5(f"{base}|{n}".encode("utf-8")).hexdigest()
        ids.append(digest[:12])
    return ids


def gerar_ids(df: pd.DataFrame) -> list[str]:
    """Gera ids estáveis por linha (uso público, ex.: após edição na UI).

    O DataFrame precisa conter as colunas de :data:`COLUNAS_SAIDA`.
    """
    return _gerar_ids(df)


def normalizar_tabela(df_bruto: pd.DataFrame) -> ResultadoNormalizacao:
    """Aplica o de-para, separa quantidade/item e classifica as linhas.

    Linhas válidas vão para ``itens``; linhas sem quantidade ou sem
    destino/item vão para ``revisar``.
    """
    df = df_bruto.copy()

    # --- de-para das colunas -------------------------------------------------
    resolucao = _resolver_colunas(df)
    campos_encontrados = set(resolucao.values())
    faltantes = [c for c in MAPEAMENTO_COLUNAS.values() if c not in campos_encontrados]

    df = df.rename(columns=resolucao)
    # garante a existência de todas as colunas internas
    for campo in MAPEAMENTO_COLUNAS.values():
        if campo not in df.columns:
            df[campo] = pd.NA

    # --- limpeza de linhas ---------------------------------------------------
    df = _remover_linhas_invalidas(df)

    if df.empty:
        vazio = pd.DataFrame(columns=COLUNAS_SAIDA)
        return ResultadoNormalizacao(
            itens=vazio.assign(id_item=pd.Series(dtype="object")),
            revisar=vazio.copy(),
            colunas_faltantes=faltantes,
        )

    # --- separa quantidade / item -------------------------------------------
    pares = df["equipamento"].apply(separar_quantidade)
    df["quantidade"] = [q for q, _ in pares]
    df["item"] = [i for _, i in pares]

    # --- limpeza dos demais campos de texto ---------------------------------
    for campo in ["destino", "origem", "responsavel", "acao", "item"]:
        df[campo] = df[campo].map(_limpar_texto)

    df = df[COLUNAS_SAIDA].reset_index(drop=True)

    # --- classifica: OK x revisar -------------------------------------------
    precisa_revisar = (
        df["quantidade"].isna()
        | (df["destino"] == "")
        | (df["item"] == "")
    )
    itens = df[~precisa_revisar].copy().reset_index(drop=True)
    revisar = df[precisa_revisar].copy().reset_index(drop=True)

    # quantidade como inteiro (Int64 aceita valores ausentes)
    itens["quantidade"] = itens["quantidade"].astype("Int64")
    revisar["quantidade"] = revisar["quantidade"].astype("Int64")

    # id estável por item
    itens["id_item"] = _gerar_ids(itens)

    return ResultadoNormalizacao(
        itens=itens,
        revisar=revisar,
        colunas_faltantes=faltantes,
    )
