import React, { useLayoutEffect, useRef } from 'react';

/**
 * A job's output. It follows the bottom as lines arrive, unless the user has
 * scrolled up to read; scrolling back to the bottom turns following on again.
 */
export default function JobLog({ lines, partial, dropped = 0, version, empty = 'No output yet.', tall = false }) {
  const box = useRef(null);
  const follow = useRef(true);

  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    follow.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
  };

  useLayoutEffect(() => {
    const el = box.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [version, lines?.length, partial]);

  const text = (lines || []).join('\n') + (partial ? `${lines?.length ? '\n' : ''}${partial}` : '');

  return (
    <div ref={box} onScroll={onScroll}
      className={`font-mono text-xs bg-slate-950 border border-slate-800 rounded-lg p-3 overflow-auto ${tall ? 'h-[28rem]' : 'h-64'}`}>
      {dropped > 0 && <p className="text-slate-600 mb-1">({dropped} earlier lines not shown)</p>}
      {text
        ? <pre className="whitespace-pre-wrap break-words text-slate-300 m-0">{text}</pre>
        : <p className="text-slate-600">{empty}</p>}
    </div>
  );
}
