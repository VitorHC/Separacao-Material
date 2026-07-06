"""
extracao.py
===========

Camada de extração: lê o PDF do PSC/PS com **Docling**, percorre todas as
tabelas do documento e seleciona apenas a tabela "Logística de Materiais"
(cabeçalho ``Destino | Equipamento | Origem | Responsável | Ação``).

Como a tabela pode se estender por várias páginas, todos os fragmentos que
casam com a assinatura são concatenados.

Não depende de Streamlit. O import do Docling é feito de forma preguiçosa
(dentro de :func:`criar_conversor`) para que a importação deste módulo seja
leve e para isolar o download inicial dos modelos.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from normalizacao import CABECALHO_ESPERADO, normalizar_texto


class ErroExtracao(Exception):
    """Erro de negócio durante a extração (PDF sem a tabela, arquivo
    corrompido, PDF escaneado sem texto, etc.)."""


@dataclass
class ResultadoExtracao:
    """Resultado bruto da extração (antes da normalização)."""

    df: pd.DataFrame              # fragmentos da tabela alvo já concatenados
    numero_psc: Optional[str]    # número do PSC/PS detectado (pode ser None)
    paginas: int                 # quantidade de páginas do PDF
    aviso: Optional[str] = None  # mensagem não fatal (ex.: possível OCR)
    metodo: str = "docling"      # "docling" (tabela em texto) ou "ocr" (imagem)
    imagem_png: Optional[bytes] = None  # preview da página (quando via OCR)


# ---------------------------------------------------------------------------
# Conversor Docling
# ---------------------------------------------------------------------------

def criar_conversor():
    """Cria o ``DocumentConverter`` do Docling com OCR DESLIGADO.

    Operação pesada (carrega/baixa modelos) — deve ser cacheada pelo chamador.
    O import fica aqui dentro para não pagar o custo na importação do módulo.

    Por que OCR desligado:
        * Os PDFs de PSC/PS são digitais (têm texto selecionável), então o OCR
          é desnecessário.
        * Com OCR ligado, o Docling tenta baixar os modelos do RapidOCR de
          ``modelscope.cn``, o que falha em redes corporativas com proxy/TLS.

    Modelos offline:
        Defina a variável de ambiente ``DOCLING_ARTIFACTS_PATH`` apontando para
        uma pasta com os modelos do Docling já baixados (útil quando a rede
        bloqueia o download automático). Veja o README.
    """
    import os

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError:
        # Versão antiga/diferente do Docling: cai no conversor padrão.
        from docling.document_converter import DocumentConverter

        return DocumentConverter()

    opcoes = PdfPipelineOptions()
    opcoes.do_ocr = False              # <- evita o download do RapidOCR
    opcoes.do_table_structure = True   # <- mantém o reconhecimento de tabelas

    artifacts = os.environ.get("DOCLING_ARTIFACTS_PATH")
    if artifacts:
        opcoes.artifacts_path = artifacts

    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opcoes)}
    )


def _converter(conversor, caminho: Path):
    """Executa a conversão tratando exceções variadas do Docling."""
    try:
        return conversor.convert(str(caminho))
    except Exception as exc:  # noqa: BLE001 - Docling levanta tipos diversos
        raise ErroExtracao(
            f"Não foi possível ler o PDF (arquivo corrompido ou formato inválido): {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Seleção da tabela alvo
# ---------------------------------------------------------------------------

def _cabecalho_casa(colunas) -> bool:
    """True se o conjunto de colunas contém a assinatura esperada."""
    atuais = {normalizar_texto(c) for c in colunas}
    esperado = {normalizar_texto(c) for c in CABECALHO_ESPERADO}
    return esperado.issubset(atuais)


def _ajustar_tabela(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Retorna o DataFrame da tabela se ela casar com a assinatura.

    Trata o caso em que o Docling devolve o cabeçalho como primeira linha de
    dados em vez de usá-lo como nome das colunas.
    """
    if df is None or df.empty:
        return None

    # caso 1: o cabeçalho já está nos nomes das colunas
    if _cabecalho_casa(df.columns):
        return df

    # caso 2: o cabeçalho está na primeira linha
    primeira = df.iloc[0].tolist()
    if _cabecalho_casa(primeira):
        novo = df.copy()
        novo.columns = [str(c) for c in primeira]
        return novo.iloc[1:].reset_index(drop=True)

    return None


# ---------------------------------------------------------------------------
# Texto e metadados do documento
# ---------------------------------------------------------------------------

def _contar_paginas(documento) -> int:
    try:
        return len(documento.pages)
    except Exception:  # noqa: BLE001
        return 0


def _texto_documento(documento) -> str:
    """Extrai o texto do documento (markdown) para detectar o número do PSC
    e diagnosticar PDFs escaneados."""
    for metodo in ("export_to_markdown", "export_to_text"):
        try:
            return getattr(documento, metodo)()
        except Exception:  # noqa: BLE001
            continue
    return ""


#: Padrões para localizar o número do PSC/PS no texto do documento.
#: A ordem importa: "PSC" tem prioridade sobre "PS".
_PADROES_PSC: list[tuple[str, "re.Pattern[str]"]] = [
    ("PSC", re.compile(r"PSC[\s:_/#.\-]*(\d{2,6})", re.IGNORECASE)),
    ("PS", re.compile(r"\bPS[\s:_/#.\-]*(\d{2,6})", re.IGNORECASE)),
]


def _extrair_numero_psc(texto: str) -> Optional[str]:
    """Tenta detectar o número do PSC/PS no texto do documento.

    Best-effort: o número pode ser confirmado/corrigido manualmente na UI.
    """
    if not texto:
        return None
    for prefixo, padrao in _PADROES_PSC:
        m = padrao.search(texto)
        if m:
            return f"{prefixo} {m.group(1)}"
    return None


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def extrair(conteudo: bytes, nome_arquivo: str, conversor) -> ResultadoExtracao:
    """Lê o PDF e devolve os fragmentos da tabela "Logística de Materiais".

    Parameters
    ----------
    conteudo:
        Bytes do PDF (vindos do upload do Streamlit).
    nome_arquivo:
        Nome original do arquivo (usado para preservar a extensão no temp).
    conversor:
        Instância de ``DocumentConverter`` (criada por :func:`criar_conversor`).

    Raises
    ------
    ErroExtracao
        Quando o PDF é inválido, não tem texto (provável escaneado) ou não
        contém a tabela de logística.
    """
    if not conteudo:
        raise ErroExtracao("Arquivo vazio.")

    # Docling trabalha melhor com um caminho de arquivo; usamos um temporário.
    nome_seguro = nome_arquivo or "documento.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        caminho = Path(tmp) / Path(nome_seguro).name
        caminho.write_bytes(conteudo)
        resultado = _converter(conversor, caminho)

    documento = resultado.document
    tabelas = getattr(documento, "tables", None) or []

    fragmentos: list[pd.DataFrame] = []
    for tabela in tabelas:
        try:
            df = tabela.export_to_dataframe()
        except Exception:  # noqa: BLE001 - ignora tabela problemática isolada
            continue
        ajustada = _ajustar_tabela(df)
        if ajustada is not None and not ajustada.empty:
            fragmentos.append(ajustada)

    paginas = _contar_paginas(documento)
    texto = _texto_documento(documento)
    numero_psc = _extrair_numero_psc(texto)

    if not fragmentos:
        if not texto.strip():
            raise ErroExtracao(
                "Nenhum texto foi extraído do PDF. Ele pode ser escaneado "
                "(imagem). Habilite o OCR do Docling ou use um PDF com texto."
            )
        raise ErroExtracao(
            "A tabela 'Logística de Materiais' não foi encontrada. "
            f"Cabeçalho esperado: {' | '.join(CABECALHO_ESPERADO)}."
        )

    df_final = pd.concat(fragmentos, ignore_index=True)
    return ResultadoExtracao(df=df_final, numero_psc=numero_psc, paginas=paginas)
