import { useState } from 'react'
import { request } from '../api'
import { emptyItem, itemInput, statusLabels, type Item, type ItemInput, type Status } from '../types'
import { AsyncForm, Modal } from './UI'
export function ItemEditor({ item, projectId, onClose, onSaved }: { item?: Item; projectId: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const [data, setData] = useState<ItemInput>(item ? itemInput(item) : emptyItem())
  function set<K extends keyof ItemInput>(key: K, value: ItemInput[K]) { setData(v => ({ ...v, [key]: value })) }
  return <Modal title={item ? 'Editar material' : 'Adicionar material'} subtitle={item?.codigo_projeto} onClose={onClose}>
    <AsyncForm label="Salvar material" onCancel={onClose} onSubmit={async () => { await request(item ? `/itens/${item.id}` : `/projetos/${projectId}/itens`, item ? 'PUT' : 'POST', data); await onSaved(); onClose() }}>
      {item?.revisao && <p className="notice">Conferência necessária: {item.revisao}</p>}
      <label>Descrição<input required value={data.descricao} onChange={e => set('descricao', e.target.value)}/></label>
      <div className="form-grid"><label>Localidade de destino<input required value={data.destino} onChange={e => set('destino', e.target.value)}/></label><label>Quantidade<input required type="number" min="1" step="1" value={data.quantidade} onChange={e => set('quantidade', Number(e.target.value))}/></label></div>
      <div className="form-grid"><label>Situação<select value={data.status} onChange={e => set('status', e.target.value as Status)}>{Object.entries(statusLabels).map(([s, l]) => <option key={s} value={s}>{l}</option>)}</select></label><label>Local de saída{data.status === 'outro_local' ? <input required placeholder="Ex.: Regional São Paulo" value={data.local_origem} onChange={e => set('local_origem', e.target.value)}/> : <input disabled value="Estoque local"/>}</label></div>
      <div className="form-grid"><label>Tipo<input value={data.tipo} onChange={e => set('tipo', e.target.value)}/></label><label>Serial / tamanho<input value={data.serial} onChange={e => set('serial', e.target.value)}/></label></div>
      <div className="form-grid"><label>Origem no projeto<input value={data.origem} onChange={e => set('origem', e.target.value)}/></label><label>Responsável<input value={data.responsavel} onChange={e => set('responsavel', e.target.value)}/></label></div>
      <label>Ação<input value={data.acao} onChange={e => set('acao', e.target.value)}/></label><label>Observações<textarea value={data.observacoes} onChange={e => set('observacoes', e.target.value)}/></label>
    </AsyncForm>
  </Modal>
}
