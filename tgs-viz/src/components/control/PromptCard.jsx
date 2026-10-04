import React, { useEffect, useState } from 'react';

/** A plain message box in the Control page style. tone: info | warn | error | ok. */
export function Notice({ tone = 'info', title, children }) {
  const tones = {
    info: 'ns-box ns-text-2',
    warn: 'ns-alert-warn',
    error: 'ns-alert-bad',
    ok: 'ns-box ns-good',
  };
  return (
    <div className={`p-4 text-sm ${tones[tone] || tones.info}`}>
      {title && <p className="font-semibold mb-1">{title}</p>}
      <div className="space-y-1">{children}</div>
    </div>
  );
}

/** A centered dialog over the page. Esc and the close mark close it. */
export function Modal({ title, onClose, children, wide = false }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 ns-scrim flex items-start justify-center overflow-auto p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={`ns-box w-full ${wide ? 'max-w-3xl' : 'max-w-xl'} mt-10`}>
        <div className="ns-strip flex items-center justify-between px-4 py-3">
          <h2>{title}</h2>
          <button onClick={onClose} className="ns-icon-btn" aria-label="Close">×</button>
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
      <p className="text-sm ns-text-2 leading-relaxed">{text}</p>
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={onCancel} className="ns-btn ns-btn-sm">
          {cancelLabel}
        </button>
        <button onClick={onConfirm}
          className={`ns-btn ns-btn-sm ns-btn-primary ${danger ? 'ns-bad' : ''}`}>
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
    <div className="ns-alert-warn p-4 space-y-3">
      <div className="flex items-start gap-2">
        <span className="ns-warn font-bold shrink-0" aria-hidden="true">!</span>
        <div>
          {prompt.title && <p className="text-xs ns-warn font-semibold">{prompt.title}</p>}
          <p className="text-sm ns-text font-semibold whitespace-pre-wrap">{prompt.text}</p>
        </div>
      </div>
      {details.length > 0 && (
        <pre className="text-xs ns-box ns-box-body bg-[var(--bg)] max-h-64 overflow-auto ns-text whitespace-pre-wrap">
          {details.join('\n')}
        </pre>
      )}
      <div className="flex flex-wrap gap-2">
        {choices.map(c => (
          <button key={c.id} disabled={!!busy} onClick={() => click(c.id)}
            className={`ns-btn ${PRIMARY.has(String(c.id).toLowerCase()) ? 'ns-btn-primary' : ''}`}>
            {busy === c.id ? 'Sending...' : c.label}
          </button>
        ))}
      </div>
      {err && <p className="text-xs ns-bad">{err}</p>}
    </div>
  );
}
