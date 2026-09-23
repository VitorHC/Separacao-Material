import { useMemo, useState } from 'react'
import { CalendarDays, FileCheck2, FileText, Search, Truck } from 'lucide-react'
import { request } from '../api'
import { localDate, shipmentLabels, type Shipment } from '../types'
import { AsyncForm, Empty, Modal } from '../components/UI'
export function Shipments({ shipments, reload, notify }: {shipments: Shipment[]; reload: () => Promise<void>; notify: (text: string) => void}) {
  const [search, setSearch] = useState(''), [status, setStatus] = useState(''), [action, setAction] = useState<{ r: Shipment; mode: 'nf' | 'date' | 'request' | 'cancel' } | null>(null)
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return shipments.filter(r => (!status || r.status === status) && `${r.destino} ${r.nf} ${r.itens.map(i => i.codigo_projeto).join(' ')}`.toLowerCase().includes(term))
  }, [search, shipments, status])
  return <><div className="page-heading"><div><div className="eyebrow">EXPEDIÇÃO • CONTROLE DE ENVIO</div><h1>Remessas e notas fiscais</h1><p>Uma remessa, vários projetos. Acompanhe a NF e a entrega à logística.</p></div></div><div className="shipment-toolbar"><div className="input-icon"><Search size={17}/><input aria-label="Buscar remessas" placeholder="Localidade, NF ou PS/PSC…" value={search} onChange={e => setSearch(e.target.value)}/></div><select aria-label="Situação da remessa" value={status} onChange={e => setStatus(e.target.value)}><option value="">Todas as situações</option>{Object.entries(shipmentLabels).map(([k,l]) => <option key={k} value={k}>{l}</option>)}</select></div>
    {!filtered.length ? <section className="panel"><Empty title="Nenhuma remessa encontrada">Na Separação, selecione os materiais de um destino e clique em Criar remessa.</Empty></section> : <div className="shipment-list">{filtered.map(r => <article className="panel shipment-card" key={r.id}><header><div className="destination-icon"><Truck size={21}/></div><div><h2>{r.destino}</h2><p>{r.itens.length} materiais · {new Set(r.itens.map(i => i.codigo_projeto)).size} projetos · saída: {r.origem_expedicao === 'LOCAL' ? 'Estoque local' : r.origem_expedicao}</p></div><span className={`shipment-status ${r.status}`}>{shipmentLabels[r.status]}</span></header><div className="shipment-meta"><span><FileText size={17}/>NF <strong>{r.nf || 'Não registrada'}</strong></span><span><CalendarDays size={17}/>Entrega à logística <strong>{r.data_entrega_logistica ? r.data_entrega_logistica.split('-').reverse().join('/') : 'Não registrada'}</strong></span></div>
      {r.status === 'legado_revisar' && <p className="notice">Envio importado do controle antigo. As quantidades precisam ser conferidas antes de contabilizar este envio. O histórico original foi preservado.</p>}
      <details><summary>Materiais desta remessa</summary><div className="table-scroll"><table><thead><tr><th>Projeto</th><th>Material</th><th>Serial / tamanho</th><th>Quantidade</th></tr></thead><tbody>{r.itens.map(i => <tr key={i.item_id}><td><span className="project-tag">{i.codigo_projeto}</span></td><td>{i.descricao}</td><td>{i.serial || '—'}</td><td>{i.quantidade}</td></tr>)}</tbody></table></div></details>{r.observacoes && <p className="muted">{r.observacoes}</p>}
      {['rascunho','nf_solicitada','nf_registrada'].includes(r.status) && <footer><button className="button text-button" onClick={() => setAction({r, mode:'cancel'})}>Cancelar remessa</button><div>{r.status === 'rascunho' && <button className="button secondary" onClick={() => setAction({r, mode:'request'})}>Registrar solicitação de NF</button>}<button className="button secondary" onClick={() => setAction({r, mode:'nf'})}><FileCheck2 size={16}/>{r.nf ? 'Editar NF' : 'Informar NF'}</button>{r.status === 'nf_registrada' && <button className="button primary" onClick={() => setAction({r, mode:'date'})}><Truck size={16}/>Entregar à logística</button>}</div></footer>}
    </article>)}</div>}
    {action && <ShipmentAction key={`${action.r.id}-${action.mode}`} {...action} onClose={() => setAction(null)} onSaved={async () => { await reload(); notify('Remessa atualizada.'); setAction(null) }}/>}
  </>
}
function ShipmentAction({ r, mode, onClose, onSaved }: {r: Shipment; mode: 'nf'|'date'|'request'|'cancel'; onClose: () => void; onSaved: () => Promise<void>}) {
  const [nf, setNf] = useState(r.nf), [date, setDate] = useState(localDate())
  const titles = {nf: 'Registrar nota fiscal', date: 'Entrega à logística', request: 'Registrar solicitação de NF', cancel: 'Cancelar remessa'}
  return <Modal title={titles[mode]} subtitle={r.destino} onClose={onClose}><AsyncForm label={mode === 'cancel' ? 'Confirmar cancelamento' : 'Salvar registro'} onCancel={onClose} onSubmit={async () => { if (mode === 'nf') await request(`/remessas/${r.id}/nf`, 'PUT', { nf }); else if (mode === 'date') await request(`/remessas/${r.id}/entregar-logistica`, 'POST', { data_entrega_logistica: date }); else await request(`/remessas/${r.id}/${mode === 'request' ? 'solicitar-nf' : 'cancelar'}`, 'POST'); await onSaved() }}>
    {mode === 'nf' && <label>Número da NF<input required value={nf} onChange={e => setNf(e.target.value)} placeholder="Ex.: 000123"/></label>}
    {mode === 'date' && <><p className="info-strip">Informe a data em que você deixou os materiais com a logística para envio.</p><label>Data de entrega à logística<input required type="date" max={localDate()} value={date} onChange={e => setDate(e.target.value)}/></label></>}
    {mode === 'request' && <p>Confirme que a NF desta remessa foi solicitada. Este registro não envia uma solicitação automaticamente.</p>}
    {mode === 'cancel' && <p>Os materiais desta remessa voltarão a ficar disponíveis para um novo envio. O registro da remessa será mantido como cancelado.</p>}
  </AsyncForm></Modal>
}
