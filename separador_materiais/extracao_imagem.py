"""
extracao_imagem.py
==================

Extração da tabela "Lista de equipamentos / Material utilizado" dos PSC/PS.

O Docling não reconhece esse bloco como tabela (vê a região como figura). Aqui
a tabela é reconstruída a partir das **coordenadas** do conteúdo, ancorando na
LINHA do cabeçalho (Destino | Equipamento | Origem | Responsável | Ação) e na
regra "o Equipamento começa com a quantidade".

Dois caminhos, do mais rápido/preciso ao mais robusto:

1. :func:`extrair_tabela_texto` — usa o **texto nativo** do PDF (pypdfium2).
   Instantâneo, sem OCR, sem modelos de ML na memória e sem erros de leitura.
   É o caminho principal (a tabela dos PSC/PS atuais é texto selecionável).
2. :func:`extrair_tabela_imagem` — **OCR** (EasyOCR) sobre o recorte da imagem
   da tabela. Fallback para PDFs escaneados / tabela realmente em imagem.

Ambos devolvem um DataFrame com as colunas do cabeçalho esperado, pronto para
``normalizacao.normalizar_tabela``.
"""

from __future__ import annotations

import io
import re
from typing import Optional

import numpy as np
import pandas as pd
import pypdfium2 as pdfium
from PIL import Image

from extracao import ErroExtracao, ResultadoExtracao
from normalizacao import CABECALHO_ESPERADO, normalizar_texto

# Campos do cabeçalho em forma normalizada e mapa de volta para o nome original.
_ORIG_POR_NORM = {normalizar_texto(c): c for c in CABECALHO_ESPERADO}
_CAMPOS_CABECALHO = set(_ORIG_POR_NORM)  # {destino, equipamento, origem, responsavel, acao}

# Texto que indica FIM da tabela (legenda abaixo dela ou início da próxima seção).
_SENTINELAS = (
    "material utilizado",
    "descricao das atividades",
    "tabela 1",
    "diagrama",
)

# Texto-âncora para localizar a página da tabela.
_ANCORAS_PAGINA = ("lista de equipamentos", "material utilizado")

_ESCALA_OCR = 4         # ~288 dpi: bom para texto pequeno em imagem
_FRACAO_MIN_IMAGEM = 0.3  # imagem precisa ocupar >30% da largura p/ ser "a tabela"
_LARGURA_PREVIEW = 1100   # px máximos do preview exibido na UI


# ---------------------------------------------------------------------------
# EasyOCR (pesado — cachear no chamador)
# ---------------------------------------------------------------------------

def criar_leitor():
    """Cria o leitor EasyOCR (pt+en). Baixa modelos no 1º uso."""
    import easyocr

    return easyocr.Reader(["pt", "en"], gpu=False, verbose=False)


# ---------------------------------------------------------------------------
# Helpers de geometria/OCR
# ---------------------------------------------------------------------------

def _caixa(bbox) -> tuple[float, float, float, float]:
    """Converte os 4 cantos do EasyOCR em (x_esq, x_dir, y_topo, y_base)."""
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return min(xs), max(xs), min(ys), max(ys)


def _ocr_array(leitor, img: np.ndarray) -> list[tuple]:
    """Roda OCR em um array de imagem. Retorna regiões
    (txt, x_esq, x_dir, y_topo, y_base, x_centro, y_centro)."""
    resultado = leitor.readtext(img, detail=1, paragraph=False, width_ths=0.15)
    regioes = []
    for bbox, txt, _conf in resultado:
        xl, xr, yt, yb = _caixa(bbox)
        regioes.append((txt, xl, xr, yt, yb, (xl + xr) / 2, (yt + yb) / 2))
    return regioes


def _maior_imagem_px(pagina, escala: int) -> Optional[tuple[int, int, int, int, float]]:
    """(x0, y0, x1, y1, fracao_largura) da maior imagem embutida na página, em
    pixels (na escala dada). Permite OCR só na região da tabela. ``None`` se a
    API falhar ou não houver imagem — o chamador cai para OCR de página inteira."""
    try:
        import pypdfium2.raw as pdfium_c

        larg_pt, alt_pt = pagina.get_size()
        melhor, melhor_area = None, 0.0
        for obj in pagina.get_objects():
            if getattr(obj, "type", None) != pdfium_c.FPDF_PAGEOBJ_IMAGE:
                continue
            try:
                bnd = obj.get_bounds()
            except Exception:  # noqa: BLE001
                continue
            l, b, r, t = (
                (bnd.left, bnd.bottom, bnd.right, bnd.top)
                if hasattr(bnd, "left")
                else tuple(bnd)
            )
            area = abs((r - l) * (t - b))
            if area > melhor_area:
                melhor_area, melhor = area, (l, b, r, t)
        if not melhor or not larg_pt:
            return None
        l, b, r, t = melhor
        x0, x1 = int(l * escala), int(r * escala)
        y0, y1 = int((alt_pt - t) * escala), int((alt_pt - b) * escala)
        return x0, y0, x1, y1, (r - l) / larg_pt
    except Exception:  # noqa: BLE001
        return None


def _recortar(img: np.ndarray, box, margem: int = 14) -> np.ndarray:
    """Recorta o array na caixa (+margem), com proteção de limites."""
    h, w = img.shape[:2]
    x0 = max(0, box[0] - margem)
    y0 = max(0, box[1] - margem)
    x1 = min(w, box[2] + margem)
    y1 = min(h, box[3] + margem)
    if x1 - x0 < 20 or y1 - y0 < 20:
        return img
    return img[y0:y1, x0:x1]


def _png_de_array(img: np.ndarray) -> bytes:
    """Codifica o array como PNG para exibição (reduz largura se for grande)."""
    pil = Image.fromarray(img)
    if pil.width > _LARGURA_PREVIEW:
        altura = int(pil.height * _LARGURA_PREVIEW / pil.width)
        pil = pil.resize((_LARGURA_PREVIEW, altura))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Reconstrução da tabela a partir das regiões OCR
# ---------------------------------------------------------------------------

def _detectar_cabecalho(regioes: list[tuple]) -> Optional[tuple[dict, float]]:
    """Acha a linha do cabeçalho (faixa de y com as palavras-chave juntas).

    Retorna ``(anchors, header_yb)`` onde ``anchors`` é ``{campo: x_centro}``,
    ou ``None`` se não houver cabeçalho plausível.
    """
    cand = [(normalizar_texto(r[0]), r) for r in regioes if normalizar_texto(r[0]) in _CAMPOS_CABECALHO]
    if len({c for c, _ in cand}) < 4:
        return None

    cand.sort(key=lambda cr: cr[1][6])  # por y_centro
    altura = np.median([cr[1][4] - cr[1][3] for cr in cand])
    tol = max(altura * 0.8, 15)

    grupos, atual = [], [cand[0]]
    for cr in cand[1:]:
        if abs(cr[1][6] - atual[-1][1][6]) <= tol:
            atual.append(cr)
        else:
            grupos.append(atual)
            atual = [cr]
    grupos.append(atual)

    melhor = max(grupos, key=lambda g: len({c for c, _ in g}))
    if len({c for c, _ in melhor}) < 4:
        return None

    anchors: dict[str, float] = {}
    header_yb = 0.0
    for campo, r in melhor:
        anchors[campo] = r[5]
        header_yb = max(header_yb, r[4])
    return anchors, header_yb


def _agrupar_linhas(dados: list[tuple]) -> list[list[tuple]]:
    """Agrupa regiões em linhas pela proximidade do y_centro."""
    dados = sorted(dados, key=lambda r: r[6])
    alturas = [r[4] - r[3] for r in dados]
    tol = (np.median(alturas) if alturas else 10) * 0.6
    linhas, atual = [], [dados[0]]
    for r in dados[1:]:
        if abs(r[6] - atual[-1][6]) <= tol:
            atual.append(r)
        else:
            linhas.append(atual)
            atual = [r]
    linhas.append(atual)
    return linhas


def _reconstruir(regioes: list[tuple]) -> Optional[list[dict]]:
    """Reconstrói as linhas da tabela a partir das regiões OCR."""
    cab = _detectar_cabecalho(regioes)
    if cab is None:
        return None
    anchors, header_yb = cab

    campos = sorted(anchors, key=lambda k: anchors[k])  # ordem por x
    centros = [anchors[k] for k in campos]
    fronteiras = [(centros[i] + centros[i + 1]) / 2 for i in range(len(centros) - 1)]

    def coluna_de(x_centro: float) -> int:
        i = 0
        while i < len(fronteiras) and x_centro > fronteiras[i]:
            i += 1
        return i

    dados = [r for r in regioes if r[3] > header_yb + 2]
    if not dados:
        return []
    linhas = _agrupar_linhas(dados)

    saida: list[dict] = []
    ultimo_destino = ""
    for linha in linhas:
        cells = {c: "" for c in campos}
        for regiao in sorted(linha, key=lambda r: r[1]):
            col = campos[coluna_de(regiao[5])]
            cells[col] = (cells[col] + " " + regiao[0]).strip()

        if any(s in normalizar_texto(" ".join(cells.values())) for s in _SENTINELAS):
            break  # fim da tabela (legenda / próxima seção)

        # "Equipamento" começa com a quantidade (número): se o número caiu na
        # coluna destino (conteúdo alinhado à esquerda), move dali em diante.
        if "equipamento" in cells:
            toks = cells.get("destino", "").split()
            for k, t in enumerate(toks):
                if re.fullmatch(r"\d{1,4}", t):
                    cells["destino"] = " ".join(toks[:k]).strip()
                    cells["equipamento"] = (" ".join(toks[k:]) + " " + cells["equipamento"]).strip()
                    break

        destino = cells.get("destino", "").strip()
        acao = cells.get("acao", "").strip()
        equip = cells.get("equipamento", "").strip()
        tem_outros = any(cells.get(c, "").strip() for c in ("origem", "responsavel", "acao"))

        if destino:
            ultimo_destino = destino
        elif acao:
            cells["destino"] = ultimo_destino           # destino mesclado (repetido)
        elif equip and not tem_outros and saida:
            saida[-1]["equipamento"] = (saida[-1]["equipamento"] + " " + equip).strip()
            continue                                    # quebra de linha do item
        else:
            break                                       # linha sem dados -> fim

        saida.append(cells)
    return saida


# ---------------------------------------------------------------------------
# Localização da página e PSC
# ---------------------------------------------------------------------------

def _texto_pagina(pagina) -> str:
    try:
        return pagina.get_textpage().get_text_range()
    except Exception:  # noqa: BLE001
        return ""


def _paginas_candidatas(pdf) -> list[int]:
    """Páginas cujo texto cita o título da seção (e a seguinte)."""
    cands: list[int] = []
    for i in range(len(pdf)):
        txt = normalizar_texto(_texto_pagina(pdf[i]))
        if any(a in txt for a in _ANCORAS_PAGINA):
            cands.append(i)
            if i + 1 < len(pdf):
                cands.append(i + 1)
    vistos: list[int] = []
    for i in cands:
        if i not in vistos:
            vistos.append(i)
    # se nada casar, varre todas as páginas como rede de segurança
    return vistos or list(range(len(pdf)))


_PADROES_PSC = [
    ("PSC", re.compile(r"PSC[\s:_/#.\-]*(\d{2,6})", re.IGNORECASE)),
    ("PS", re.compile(r"\bPS[\s:_/#.\-]*(\d{2,6})", re.IGNORECASE)),
]


def _detectar_psc(pdf) -> Optional[str]:
    texto = " ".join(_texto_pagina(pdf[i]) for i in range(min(len(pdf), 2)))
    for prefixo, padrao in _PADROES_PSC:
        m = padrao.search(texto)
        if m:
            return f"{prefixo} {m.group(1)}"
    return None


# ---------------------------------------------------------------------------
# Extração por TEXTO NATIVO (rápida, sem OCR — caminho principal)
# ---------------------------------------------------------------------------

def _palavras_pagina(pagina) -> list[tuple]:
    """Extrai as palavras nativas da página com coordenadas, no mesmo formato
    das regiões de OCR: (txt, x_esq, x_dir, y_topo, y_base, x_centro, y_centro).

    As coordenadas do pdfium têm origem embaixo-esquerda (y para cima); aqui são
    convertidas para y crescente para baixo (como no OCR) para reusar a mesma
    lógica de reconstrução de tabela."""
    _, altura = pagina.get_size()
    tp = pagina.get_textpage()
    total = tp.count_chars()

    palavras: list[tuple] = []
    atual = ""
    l = b = r = t = None

    def fechar():
        nonlocal atual, l, b, r, t
        if atual.strip() and l is not None:
            yt, yb = altura - t, altura - b
            palavras.append((atual, l, r, yt, yb, (l + r) / 2, (yt + yb) / 2))
        atual, l, b, r, t = "", None, None, None, None

    for i in range(total):
        ch = tp.get_text_range(i, 1)
        if not ch or ch.isspace():
            fechar()
            continue
        try:
            cl, cb, cr, ct = tp.get_charbox(i)
        except Exception:  # noqa: BLE001
            continue
        if l is None:
            l, b, r, t = cl, cb, cr, ct
        else:
            l, b, r, t = min(l, cl), min(b, cb), max(r, cr), max(t, ct)
        atual += ch
    fechar()
    return palavras


def extrair_tabela_texto(conteudo: bytes, nome_arquivo: str) -> ResultadoExtracao:
    """Extrai a tabela a partir do TEXTO NATIVO do PDF (sem OCR).

    É rápido, não usa memória de modelos de ML e não tem erros de leitura.
    Funciona quando a tabela é texto selecionável (caso dos PSC/PS atuais).

    Raises
    ------
    ErroExtracao
        Se o PDF for inválido ou a tabela não for reconstruída a partir do texto.
    """
    if not conteudo:
        raise ErroExtracao("Arquivo vazio.")
    try:
        pdf = pdfium.PdfDocument(conteudo)
    except Exception as exc:  # noqa: BLE001
        raise ErroExtracao(f"Não foi possível abrir o PDF: {exc}") from exc

    paginas = len(pdf)
    numero_psc = _detectar_psc(pdf)

    for idx in _paginas_candidatas(pdf):
        linhas = _reconstruir(_palavras_pagina(pdf[idx]))
        if linhas:
            df = pd.DataFrame(
                [{_ORIG_POR_NORM[c]: linha.get(c, "") for c in _ORIG_POR_NORM} for linha in linhas]
            )
            return ResultadoExtracao(
                df=df,
                numero_psc=numero_psc,
                paginas=paginas,
                metodo="texto",
            )

    raise ErroExtracao("Tabela de materiais não encontrada no texto nativo do PDF.")


# ---------------------------------------------------------------------------
# Função principal (OCR — usada como fallback p/ PDF escaneado/imagem)
# ---------------------------------------------------------------------------

def _ordem_de_tentativas(pdf, candidatas: list[int]) -> list[tuple[int, Optional[tuple]]]:
    """Ordena as páginas a tentar: primeiro as que têm uma imagem grande (a
    tabela), recortando-a; depois as demais, em página inteira."""
    com_imagem, sem_imagem = [], []
    for idx in candidatas:
        box = _maior_imagem_px(pdf[idx], _ESCALA_OCR)
        if box and box[4] >= _FRACAO_MIN_IMAGEM:
            com_imagem.append((idx, box))
        else:
            sem_imagem.append((idx, None))
    return com_imagem + sem_imagem


def extrair_tabela_imagem(conteudo: bytes, nome_arquivo: str, leitor) -> ResultadoExtracao:
    """Extrai a tabela de materiais que está como imagem no PDF, via OCR.

    Otimizações: localiza a página pelo título, prioriza a página que contém a
    imagem da tabela e roda OCR apenas no recorte dessa imagem (mais rápido e
    com menor uso de memória). Cai para OCR de página inteira só se necessário.

    Raises
    ------
    ErroExtracao
        Se o PDF for inválido ou a tabela não for localizada por OCR.
    """
    if not conteudo:
        raise ErroExtracao("Arquivo vazio.")
    try:
        pdf = pdfium.PdfDocument(conteudo)
    except Exception as exc:  # noqa: BLE001
        raise ErroExtracao(f"Não foi possível abrir o PDF: {exc}") from exc

    paginas = len(pdf)
    numero_psc = _detectar_psc(pdf)

    for idx, box in _ordem_de_tentativas(pdf, _paginas_candidatas(pdf)):
        bmp = pdf[idx].render(scale=_ESCALA_OCR)
        img = np.array(bmp.to_pil().convert("RGB"))
        sub = _recortar(img, box) if box else img

        regioes = _ocr_array(leitor, sub)
        linhas = _reconstruir(regioes)
        if linhas:
            df = pd.DataFrame(
                [{_ORIG_POR_NORM[c]: linha.get(c, "") for c in _ORIG_POR_NORM} for linha in linhas]
            )
            preview = _png_de_array(sub)
            del img, sub, bmp
            return ResultadoExtracao(
                df=df,
                numero_psc=numero_psc,
                paginas=paginas,
                aviso=(
                    "Tabela lida por OCR (a lista vem como imagem no PDF). "
                    "Confira/edite os dados antes de separar — pode haver erros de leitura."
                ),
                metodo="ocr",
                imagem_png=preview,
            )
        del img, sub, bmp  # libera antes da próxima tentativa

    raise ErroExtracao(
        "Não foi possível localizar a tabela de materiais por OCR. "
        "Verifique se o PDF contém a seção 'Lista de equipamentos / Material utilizado'."
    )
