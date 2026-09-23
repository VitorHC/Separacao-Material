import { useState } from 'react'
import { ArrowRight, Download, Layers3, ListFilter, MapPin, Package, Pencil, Plus, Search, Truck, X } from 'lucide-react'
import { request } from '../api'
import { exportItems } from '../export'
import { expedition, statusLabels, type Group, type Item, type Project, type Status } from '../types'
import { AsyncForm, Empty, Modal, StatusBadge } from '../components/UI'
import { ItemEditor } from '../components/ItemEditor'

type Props = { initialProjectId?: string; projects: Project[]; groups: Group[]; reload: () => Promise<void>; notify: (text: string) => void; goShipments: () => void }
export function Separation({ initialProjectId = '', projects, groups, reload, notify, goShipments }: Props) {
  const [tab, setTab] = useState<'project' | 'consolidated'>('project')
  const [projectId, setProjectId] = useState(initialProjectId), [location, setLocation] = useState(''), [status, setStatus] = useState(''), [search, setSearch] = useState(''), [pending, setPending] = useState(false)
  const [selected, setSelected] = useState<string[]>([]), [editing, setEditing] = useState<Item | 'new' | null>(null), [shipmentOpen, setShipmentOpen] = useState(false)
  const activeProject = projects.find(p => p.id === projectId) ?? projects[0]
  const all = groups.flatMap(g => g.itens)
  const selection = all.filter(i => selected.includes(i.id))
  const first = selection[0]
  const filtered = groups.map(g => ({ ...g, itens: g.itens.filter(i => (tab === 'consolidated' || i.projeto_id === activeProject?.id) && (!location || (g.localidade_id ?? 'missing') === location) && (!status || i.status === status) && (!pending || i.quantidade_pendente !== 0) && `${i.descricao} ${i.codigo_projeto} ${i.destino} ${i.serial}`.toLowerCase().includes(search.toLowerCase())) })).filter(g => g.itens.length)
  const visible = filtered.flatMap(g => g.itens)
  function filter(action: () => void) { action(); setSelected([]) }
  function selectable(i: Item) { return !!expedition(i) && (!first || (i.localidade_id === first.localidade_id && expedition(i) === expedition(first))) }
  function toggle(i: Item, checked: boolean) { if (!checked) setSelected(v => v.filter(id => id !== i.id)); else if (selectable(i)) setSelected(v => [...v, i.id]) }
  const complete = visible.filter(i => i.status === 'separado').length
  const missing = visible.filter(i => i.status === 'sem_estoque').length
  const eligible = visible.filter(i => expedition(i)).length
  return <>
    <div className="page-heading"><div><div className="eyebrow">OPERAÇÃO • MATERIAIS</div><h1>Separação de materiais</h1><p>Do projeto ao envio, acompanhe cada material e seu destino.</p></div><button className="button secondary" disabled={!visible.length} onClick={() => exportItems(visible)}><Download size={17}/>Exportar seleção de filtros</button></div>
    <div className="metrics"><Metric title="Materiais na visualização" value={visible.length} detail="linhas de materiais" icon={<Package size={20}/>}/><Metric title="Separados" value={complete} detail="prontos para organizar" tone="green"/><Metric title="Sem estoque" value={missing} detail="aguardando disponibilidade" tone="red"/><Metric title="Localidades" value={filtered.length} detail={`${new Set(visible.map(i => i.projeto_id)).size} projetos na visualização`} icon={<MapPin size={20}/>}/></div>
    <section className="panel separation-panel">
      <div className="tabs" role="tablist" aria-label="Visão da separação"><button role="tab" aria-selected={tab === 'project'} aria-controls="materials-panel" onClick={() => filter(() => setTab('project'))}><Package size={17}/>Por projeto</button><button role="tab" aria-selected={tab === 'consolidated'} aria-controls="materials-panel" onClick={() => filter(() => setTab('consolidated'))}><Layers3 size={17}/>Consolidado por localidade<span className="count">{groups.length}</span></button></div>
      <div id="materials-panel" role="tabpanel" aria-label={tab === 'project' ? 'Por projeto' : 'Consolidado por localidade'}>
        <div className="view-intro"><div><h2>{tab === 'project' ? 'Materiais do projeto' : 'Todos os projetos. Um destino por vez.'}</h2><p>{tab === 'project' ? 'Confira os itens, atualize a situação e organize a separação.' : 'Reúna materiais de diferentes PS/PSC em uma única remessa por localidade e origem.'}</p></div>{tab === 'project' && activeProject && <button className="button secondary small" onClick={() => setEditing('new')}><Plus size={16}/>Adicionar material</button>}</div>
        <div className="filters">
          {tab === 'project' && <label>Projeto<select value={activeProject?.id ?? ''} onChange={e => filter(() => setProjectId(e.target.value))}><option value="" disabled>Selecione um projeto</option>{projects.map(p => <option value={p.id} key={p.id}>{p.codigo}</option>)}</select></label>}
          <label className="search-field">Buscar material<div className="input-icon"><Search size={17}/><input placeholder="Material, PS/PSC ou serial…" value={search} onChange={e => filter(() => setSearch(e.target.value))}/></div></label>
          <label>Localidade<select value={location} onChange={e => filter(() => setLocation(e.target.value))}><option value="">Todas as localidades</option>{groups.map(g => <option key={g.localidade_id ?? 'missing'} value={g.localidade_id ?? 'missing'}>{g.destino || 'Sem localidade'}</option>)}</select></label>
          <label>Situação<select value={status} onChange={e => filter(() => setStatus(e.target.value))}><option value="">Todas as situações</option>{Object.entries(statusLabels).map(([s,l]) => <option key={s} value={s}>{l}</option>)}</select></label>
        </div>
        <div className="filter-meta"><label className="checkbox-label"><input type="checkbox" checked={pending} onChange={e => filter(() => setPending(e.target.checked))}/>Somente pendentes de envio</label><span><ListFilter size={14}/>{visible.length} materiais · {eligible} com saldo apto para remessa</span></div>
        {!filtered.length ? <Empty title={projects.length ? 'Nenhum material para estes filtros' : 'Seus materiais aparecerão aqui'}>{projects.length ? 'Ajuste os filtros ou adicione materiais ao projeto.' : 'Cadastre ou importe um projeto para começar a separação.'}</Empty> : <div className="location-groups">{filtered.map(g => {
          const allowed = g.itens.filter(i => selectable(i) && (first || expedition(i) === 'LOCAL'))
          return <details open className="location-group" key={g.localidade_id ?? 'missing'}><summary><div className="destination-icon"><MapPin size={20}/></div><div className="destination-name"><h3>{g.destino || 'Sem localidade'}</h3><span>{new Set(g.itens.map(i => i.projeto_id)).size} projetos · {g.itens.length} materiais</span></div><span className="location-progress">{g.itens.filter(i => i.status === 'separado').length} separados</span><span className="chevron">⌄</span></summary>
            <div className="table-scroll"><table className="materials-table"><thead><tr><th className="check-cell"><input type="checkbox" aria-label={`Selecionar disponíveis de ${g.destino}`} disabled={!allowed.length} checked={!!allowed.length && allowed.every(i => selected.includes(i.id))} onChange={e => setSelected(v => e.target.checked ? [...new Set([...v, ...allowed.map(i => i.id)])] : v.filter(id => !g.itens.some(i => i.id === id)))}/></th><th>Projeto</th><th>Material</th><th className="number">Necessário</th><th className="number">Pendente</th><th>Situação</th><th>Origem de envio</th><th><span className="sr-only">Ações</span></th></tr></thead><tbody>{g.itens.map(i => <tr key={i.id} className={selected.includes(i.id) ? 'selected-row' : ''}><td className="check-cell"><input type="checkbox" aria-label={`Selecionar ${i.codigo_projeto} ${i.descricao}`} disabled={!selectable(i)} checked={selected.includes(i.id)} onChange={e => toggle(i, e.target.checked)}/></td><td><span className="project-tag">{i.codigo_projeto}</span></td><td className="material-name"><strong>{i.descricao || 'Descrição pendente'}</strong>{i.serial && <small>{i.serial}</small>}{i.revisao && <small className="review-text" title={i.revisao}>Conferência pendente</small>}{i.quantidade_reservada > 0 && <small>{i.quantidade_reservada} em remessa</small>}</td><td className="number">{i.quantidade ?? '—'}</td><td className="number">{i.quantidade_pendente ?? '—'}</td><td><StatusBadge status={i.status}/></td><td className="muted">{i.status === 'outro_local' ? (i.local_origem || 'Informar origem') : 'Estoque local'}</td><td><button className="icon-button" aria-label={`Editar ${i.codigo_projeto} ${i.descricao}`} onClick={() => setEditing(i)}><Pencil size={15}/></button></td></tr>)}</tbody></table></div>
          </details>
        })}</div>}
        <div className="legend">{(Object.keys(statusLabels) as Status[]).map(s => <StatusBadge status={s} key={s}/>)}</div>
      </div>
    </section>
    {selection.length > 0 && <div className="selection-bar" role="region" aria-label="Materiais selecionados"><div className="selection-count">{selection.length}</div><div><strong>materiais selecionados para {first.destino}</strong><span>{new Set(selection.map(i => i.projeto_id)).size} projetos · saída: {expedition(first) === 'LOCAL' ? 'Estoque local' : expedition(first)}</span></div><button className="button ghost" onClick={() => setSelected([])}><X size={16}/>Limpar</button><button className="button white" onClick={() => setShipmentOpen(true)}>Criar remessa<ArrowRight size={17}/></button></div>}
    {editing && <ItemEditor item={editing === 'new' ? undefined : editing} projectId={editing === 'new' ? activeProject.id : editing.projeto_id} onClose={() => setEditing(null)} onSaved={async () => { setSelected([]); await reload(); notify('Material salvo.') }}/>}
    {shipmentOpen && <ShipmentBuilder items={selection} onClose={() => setShipmentOpen(false)} onSaved={async () => { setShipmentOpen(false); setSelected([]); await reload(); notify('Remessa criada. Agora você pode registrar a solicitação de NF.'); goShipments() }}/>}
  </>
}
function Metric({ title, value, detail, tone = '', icon }: {title: string; value: number; detail: string; tone?: string; icon?: React.ReactNode}) { return <div className={`metric ${tone}`}><div className="metric-label">{title}{icon}</div><strong>{value.toLocaleString('pt-BR')}</strong><small>{detail}</small></div> }
function ShipmentBuilder({ items, onClose, onSaved }: {items: Item[]; onClose: () => void; onSaved: () => Promise<void>}) {
  const [quantities, setQuantities] = useState<Record<string, number>>(Object.fromEntries(items.map(i => [i.id, i.quantidade_disponivel_remessa ?? 0])))
  const [notes, setNotes] = useState('')
  return <Modal title="Nova remessa consolidada" subtitle={`${items[0]?.destino} · ${new Set(items.map(i => i.projeto_id)).size} projetos`} onClose={onClose} wide>
    <AsyncForm label="Criar remessa" onCancel={onClose} onSubmit={async () => { await request('/remessas', 'POST', { localidade_id: items[0].localidade_id, origem_expedicao: expedition(items[0]), observacoes: notes, itens: items.map(i => ({ item_id: i.id, quantidade: quantities[i.id] })) }); await onSaved() }}>
      <p className="info-strip"><Truck size={18}/>Uma NF para os materiais desta remessa. Confira as quantidades antes de continuar.</p>
      <div className="table-scroll"><table><thead><tr><th>Projeto</th><th>Material</th><th>Disponível</th><th>Quantidade nesta remessa</th></tr></thead><tbody>{items.map(i => <tr key={i.id}><td>{i.codigo_projeto}</td><td>{i.descricao}</td><td>{i.quantidade_disponivel_remessa}</td><td><input aria-label={`Quantidade de ${i.codigo_projeto} ${i.descricao}`} className="quantity-input" type="number" min="1" max={i.quantidade_disponivel_remessa ?? 0} step="1" required value={quantities[i.id]} onChange={e => setQuantities(v => ({ ...v, [i.id]: Number(e.target.value) }))}/></td></tr>)}</tbody></table></div><label>Observações<textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Informações para acompanhar a remessa"/></label>
    </AsyncForm>
  </Modal>
}
