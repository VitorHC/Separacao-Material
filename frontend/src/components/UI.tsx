import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { AlertCircle, Inbox, LoaderCircle, X } from 'lucide-react'
import { statusLabels, type Status } from '../types'

export function StatusBadge({ status }: { status: Status }) { return <span className={`badge ${status}`}><span className="status-dot"/>{statusLabels[status]}</span> }
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><Inbox size={32}/><h3>{title}</h3><p>{children}</p></div> }
export function ErrorBox({ message }: { message: string }) { return message ? <div role="alert" className="error-box"><AlertCircle size={18}/><span>{message}</span></div> : null }
export function Modal({ title, subtitle, onClose, children, busy = false, wide = false }: { title: string; subtitle?: string; onClose: () => void; children: ReactNode; busy?: boolean; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close() }, [])
  return <dialog ref={ref} className={wide ? 'modal wide' : 'modal'} onCancel={e => { e.preventDefault(); if (!busy) onClose() }} aria-label={title}>
    <div className="modal-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" aria-label="Fechar" onClick={onClose} disabled={busy}><X size={20}/></button></div>{children}
  </dialog>
}
export function AsyncForm({ children, onSubmit, label, onCancel }: { children: ReactNode; onSubmit: () => Promise<void>; label: string; onCancel?: () => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  async function submit(e: FormEvent) { e.preventDefault(); if (busy) return; setBusy(true); setError(''); try { await onSubmit() } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao salvar.') } finally { setBusy(false) } }
  return <form onSubmit={submit}><fieldset disabled={busy}>{children}<ErrorBox message={error}/><div className="form-footer">{onCancel && <button type="button" className="button secondary" onClick={onCancel}>Cancelar</button>}<button className="button primary" type="submit">{busy && <LoaderCircle size={16} className="spin"/>}{busy ? 'Salvando…' : label}</button></div></fieldset></form>
}
