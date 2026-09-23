import { useCallback, useEffect, useRef, useState } from 'react'
import { Boxes, CheckCircle2, ChevronRight, FileText, Menu, PackageCheck, RefreshCw, Truck, X } from 'lucide-react'
import { api } from './api'
import type { Group, Project, Shipment } from './types'
import { ErrorBox } from './components/UI'
import { Projects } from './pages/Projects'
import { Separation } from './pages/Separation'
import { Shipments } from './pages/Shipments'
type Page = 'projects' | 'separation' | 'shipments'
const labels = { projects: 'Projetos', separation: 'Separação', shipments: 'Remessas e NFs' }
export default function App() {
  const [page, setPage] = useState<Page>('separation'), [mobileMenu, setMobileMenu] = useState(false), [projectId, setProjectId] = useState('')
  const [data, setData] = useState<{projects: Project[]; groups: Group[]; shipments: Shipment[]}>({projects: [], groups: [], shipments: []})
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const controller = useRef<AbortController | null>(null)
  const reload = useCallback(async () => {
    controller.current?.abort(); const current = new AbortController(); controller.current = current; setLoading(true); setError('')
    try { const [projects, groups, shipments] = await Promise.all([api.projects(current.signal), api.groups(current.signal), api.shipments(current.signal)]); if (!current.signal.aborted) setData({ projects, groups, shipments }) }
    catch (e) { if (!current.signal.aborted) setError(e instanceof Error ? e.message : 'Não foi possível atualizar os dados.') }
    finally { if (!current.signal.aborted) setLoading(false) }
  }, [])
  useEffect(() => { void reload(); return () => controller.current?.abort() }, [reload])
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 6500); return () => clearTimeout(timer) }, [notice])
  function navigate(p: Page) { setPage(p); setMobileMenu(false) }
  return <div className="app-shell">
    <aside className={`sidebar ${mobileMenu ? 'mobile-open' : ''}`}><div className="brand"><div className="brand-symbol"><Boxes size={27}/></div><div><strong>eletronet<span> / materiais</span></strong><small>ENGENHARIA DE IMPLANTAÇÃO</small></div><button aria-label="Fechar menu" className="mobile-close icon-button" onClick={() => setMobileMenu(false)}><X size={20}/></button></div><div className="sidebar-section">GESTÃO OPERACIONAL</div><nav aria-label="Navegação principal"><button className={page === 'projects' ? 'active' : ''} onClick={() => navigate('projects')}><FileText size={19}/>Projetos<span>{data.projects.length}</span></button><button className={page === 'separation' ? 'active' : ''} onClick={() => navigate('separation')}><PackageCheck size={19}/>Separação</button><button className={page === 'shipments' ? 'active' : ''} onClick={() => navigate('shipments')}><Truck size={19}/>Remessas e NFs</button></nav><div className="sidebar-bottom"><div className="sidebar-monogram">EI</div><div><strong>Controle de materiais</strong><small>Projetos, localidades e envios</small></div></div></aside>
    <div className="main-shell"><header className="topbar"><button className="icon-button mobile-menu" aria-label="Abrir menu" onClick={() => setMobileMenu(true)}><Menu size={22}/></button><div className="breadcrumb"><span>Implantação</span><ChevronRight size={14}/><strong>{labels[page]}</strong></div><button className="button refresh-button" disabled={loading} onClick={() => void reload()}><RefreshCw size={15} className={loading ? 'spin' : ''}/>{loading ? 'Atualizando…' : 'Atualizar dados'}</button></header>
      <main><ErrorBox message={error}/>{loading && !data.projects.length ? <div className="loading" role="status"><RefreshCw size={24} className="spin"/><h2>Carregando seus materiais…</h2></div> : <>{page === 'projects' && <Projects projects={data.projects} reload={reload} notify={setNotice} openProject={id => { setProjectId(id); navigate('separation') }}/>} {page === 'separation' && <Separation initialProjectId={projectId} projects={data.projects} groups={data.groups} reload={reload} notify={setNotice} goShipments={() => navigate('shipments')}/>} {page === 'shipments' && <Shipments shipments={data.shipments} reload={reload} notify={setNotice}/>}</>}</main>
      <footer className="app-footer"><span>Materiais • Engenharia de Implantação</span><span>PS / PSC</span></footer>
    </div>{notice && <div role="status" className="toast"><CheckCircle2 size={20}/>{notice}<button aria-label="Fechar aviso" className="icon-button" onClick={() => setNotice('')}><X size={16}/></button></div>}
  </div>
}
