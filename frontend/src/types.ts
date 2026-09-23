export type Status = 'nao_separado' | 'separado' | 'outro_local' | 'sem_estoque'
export const statusLabels: Record<Status, string> = { nao_separado: 'Não separado', separado: 'Separado', outro_local: 'Outro local', sem_estoque: 'Sem estoque' }
export interface ItemInput { destino: string; descricao: string; quantidade: number; status: Status; local_origem: string; tipo: string; serial: string; origem: string; responsavel: string; acao: string; observacoes: string }
export interface Item extends Omit<ItemInput, 'quantidade'> { id: string; projeto_id: string; codigo_projeto: string; localidade_id: string | null; quantidade: number | null; revisao: string; quantidade_reservada: number; quantidade_entregue_logistica: number; quantidade_pendente: number | null; quantidade_disponivel_remessa: number | null }
export interface Project { id: string; codigo: string; arquivo: string; paginas: number; metodo: string; projetista: string; responsavel_implantacao: string; criado_em: string; atualizado_em: string; itens: Item[] }
export interface Group { localidade_id: string | null; destino: string; itens: Item[] }
export type ShipmentStatus = 'rascunho' | 'nf_solicitada' | 'nf_registrada' | 'entregue_logistica' | 'cancelada' | 'legado_revisar'
export const shipmentLabels: Record<ShipmentStatus, string> = { rascunho: 'Rascunho', nf_solicitada: 'NF solicitada', nf_registrada: 'NF registrada', entregue_logistica: 'Entregue à logística', cancelada: 'Cancelada', legado_revisar: 'Conferir legado' }
export interface Shipment { id: string; localidade_id: string; destino: string; origem_expedicao: string; status: ShipmentStatus; nf: string; data_entrega_logistica: string | null; criado_em: string; observacoes: string; itens: { item_id: string; codigo_projeto: string; descricao: string; quantidade: number; serial: string }[] }
export interface DraftItem extends Omit<ItemInput, 'quantidade'> { quantidade: number | null; revisao?: string }
export interface Extraction { codigo: string; arquivo: string; paginas: number; metodo: string; aviso: string; itens: DraftItem[]; imagem_png: string | null }
export const emptyItem = (): ItemInput => ({ destino: '', descricao: '', quantidade: 1, status: 'nao_separado', local_origem: '', tipo: '', serial: '', origem: '', responsavel: '', acao: '', observacoes: '' })
export function itemInput(item: Item): ItemInput {
  return { destino: item.destino, descricao: item.descricao, quantidade: item.quantidade ?? 1, status: item.status, local_origem: item.local_origem, tipo: item.tipo, serial: item.serial, origem: item.origem, responsavel: item.responsavel, acao: item.acao, observacoes: item.observacoes }
}
export function normalize(value: string) { return value.normalize('NFKC').trim().replace(/\s+/g, ' ').toUpperCase() }
export function expedition(item: Item): string | null {
  if (item.revisao || !item.localidade_id || !item.quantidade_disponivel_remessa) return null
  if (item.status === 'separado') return 'LOCAL'
  if (item.status === 'outro_local' && item.local_origem.trim() && normalize(item.local_origem) !== 'LOCAL') return normalize(item.local_origem)
  return null
}
export function localDate() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
