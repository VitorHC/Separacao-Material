import { useState } from 'react'
import { request } from '../api'
import { itemInput, normalize, statusLabels, type Item, type Status } from '../types'

export function ItemStatusSelect({ item, onEdit, onSaved }: { item: Item; onEdit: (item: Item) => void; onSaved: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function change(status: Status) {
    if (busy || status === item.status) return
    setError('')
    if (item.revisao || !item.descricao.trim() || !item.destino.trim() || !item.quantidade
      || (status === 'outro_local' && (!item.local_origem.trim() || normalize(item.local_origem) === 'LOCAL'))) {
      onEdit({ ...item, status })
      return
    }
    setBusy(true)
    try {
      await request(`/itens/${item.id}`, 'PUT', { ...itemInput(item), status })
      await onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível salvar a situação.')
    } finally {
      setBusy(false)
    }
  }
  return <div className="item-status-control">
    <select className={`badge ${item.status}`} aria-label={`Situação de ${item.codigo_projeto} ${item.descricao}`} value={item.status} disabled={busy} onChange={e => void change(e.target.value as Status)}>
      {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select>
    {busy && <small role="status">Salvando…</small>}
    {error && <small role="alert">{error}</small>}
  </div>
}
