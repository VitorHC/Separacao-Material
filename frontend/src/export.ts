import type { Item } from './types'
import { statusLabels } from './types'
export function exportItems(items: Item[]) {
  const rows = [['Projeto', 'Localidade', 'Material', 'Qtd. necessária', 'Qtd. pendente', 'Qtd. reservada', 'Qtd. entregue à logística', 'Situação', 'Origem', 'Serial / tamanho'], ...items.map(i => [i.codigo_projeto, i.destino, i.descricao, i.quantidade, i.quantidade_pendente, i.quantidade_reservada, i.quantidade_entregue_logistica, statusLabels[i.status], i.local_origem || i.origem, i.serial])]
  const escape = (v: unknown) => { let text = String(v ?? ''); if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`; return `"${text.replaceAll('"', '""')}"` }
  const blob = new Blob(['\ufeff' + rows.map(r => r.map(escape).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'materiais-filtrados.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
