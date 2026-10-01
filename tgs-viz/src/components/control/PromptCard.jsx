import React, { useEffect, useState } from 'react';
import { CircleAlert, X } from 'lucide-react';

/** A plain message box in the Control page style. tone: info | warn | error | ok. */
export function Notice({ tone = 'info', title, children }) {
  const tones = {
    info: 'border-slate-700 bg-slate-900/60 text-slate-300',
    warn: 'border-amber-600/50 bg-amber-950/30 text-amber-200',
    error: 'border-red-600/50 bg-red-950/30 text-red-200',
    ok: 'border-green-600/40 bg-green-950/20 text-green-200',
  };
  return (
    <div className={`border rounded-xl p-4 text-sm ${tones[tone] || tones.info}`}>
      {title && <p className="font-semibold mb-1">{title}</p>}
      <div className="space-y-1">{children}</div>
    </div>
  );
}

/** A centered dialog over the page. Esc and the X close it. */
export function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center overflow-auto p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={`bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full ${wide ? 'max-w-3xl' : 'max-w-xl'} mt-10`}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h2 className="text-sm font-bold text-white">{title}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200" aria-label="Close"><X size={16} /></button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

/** Yes/no dialog. onConfirm runs on the confirm button. */
export function ConfirmDialog({ title, text, confirmLabel, cancelLabel = 'Cancel', danger = false, onConfirm, onCancel }) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p className="text-sm text-slate-300 leading-relaxed">{text}</p>
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={onCancel} className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700">
          {cancelLabel}
        </button>
        <button onClick={onConfirm}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg text-white ${danger ? 'bg-red-600 hover:bg-red-500' : 'bg-blue-600 hover:bg-blue-500'}`}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

const PRIMARY = new Set(['yes', 'continue', 'apply', 'ok']);

/**
 * A question from a running task (7.4): the text, the preview lines in a log
 * box, and one button per choice. onAnswer(value) returns a promise.
 */
export default function PromptCard({ prompt, onAnswer }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { setBusy(null); setErr(null); }, [prompt?.prompt_id]);
  if (!prompt) return null;
  const details = Array.isArray(prompt.details) ? prompt.details : [];
  const choices = Array.isArray(prompt.choices) && prompt.choices.length
    ? prompt.choices
    : [{ id: 'yes', label: 'Yes' }, { id: 'no', label: 'No' }];

  const click = async (value) => {
    setBusy(value);
    setErr(null);
    try {
      await onAnswer(value);
    } catch (e) {
      setErr(e.message || String(e));
      setBusy(null);
    }
  };

  return (
    <div className="border border-amber-500/60 bg-amber-950/20 rounded-xl p-4 space-y-3">
      <div className="flex items-start gap-2">
        <CircleAlert size={18} className="text-amber-400 shrink-0 mt-0.5" />
        <div>
          {prompt.title && <p className="text-xs text-amber-300/80 uppercase tracking-wide font-semibold">{prompt.title}</p>}
          <p className="text-sm text-amber-100 font-semibold whitespace-pre-wrap">{prompt.text}</p>
        </div>
      </div>
      {details.length > 0 && (
        <pre className="font-mono text-xs bg-slate-950 border border-slate-800 rounded-lg p-3 max-h-64 overflow-auto text-slate-300 whitespace-pre-wrap">
          {details.join('\n')}
        </pre>
      )}
      <div className="flex flex-wrap gap-2">
        {choices.map(c => (
          <button key={c.id} disabled={!!busy} onClick={() => click(c.id)}
            className={`px-4 py-1.5 text-sm font-semibold rounded-lg disabled:opacity-50 ${PRIMARY.has(String(c.id).toLowerCase())
              ? 'bg-blue-600 text-white hover:bg-blue-500'
              : 'bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700'}`}>
            {busy === c.id ? 'Sending...' : c.label}
          </button>
        ))}
      </div>
      {err && <p className="text-xs text-red-400">{err}</p>}
    </div>
  );
}
