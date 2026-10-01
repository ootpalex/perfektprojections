import React from 'react';
import { Play, Clock } from 'lucide-react';

/** Plain-words notes for a task's flags (DESIGN 10.3). */
export function flagNotes(task) {
  const f = task?.flags || {};
  const notes = [];
  if (f.drives_ootp) {
    notes.push('Takes over your mouse and keyboard. OOTP must be open inside a league. Hands off until it finishes. '
      + 'To abort, slam the mouse into a screen corner. If OOTP runs as administrator, use the .bat with Run as administrator '
      + 'instead: the app cannot click an OOTP that runs as administrator.');
  }
  if (f.endless) notes.push('Runs until you stop it.');
  if (f.heavy) notes.push('Takes hours and a lot of memory.');
  else if (f.long) notes.push('Takes a long time.');
  if (f.needs_excel_closed) {
    notes.push("Close Excel on the league's sheets first. If a sheet is open, the task waits and asks you to close it.");
  }
  if (f.network) notes.push('Needs internet (statsplus.net).');
  if (f.writes_app_data) {
    notes.push("Updates the app's data. The open app updates each league when the task finishes that league's steps.");
  }
  if (f.read_only) notes.push('Changes nothing. Can run while other tasks run.');
  return notes;
}

/** One task: title, description, time, flag notes and the Run button. */
export default function TaskCard({ task, onRun }) {
  const notes = flagNotes(task);
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col gap-2" data-task={task.id}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-white">{task.title}</h3>
          {task.time && (
            <p className="text-[11px] text-slate-500 flex items-center gap-1 mt-0.5">
              <Clock size={11} /> {task.time}
            </p>
          )}
        </div>
        <button onClick={onRun}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500">
          <Play size={12} /> Run
        </button>
      </div>
      {task.description && <p className="text-xs text-slate-400 leading-relaxed">{task.description}</p>}
      {notes.length > 0 && (
        <ul className="text-[11px] text-slate-500 space-y-0.5 list-disc pl-4">
          {notes.map(n => <li key={n}>{n}</li>)}
        </ul>
      )}
      {task.bat && <p className="text-[10px] text-slate-600">Same as {task.bat}</p>}
    </div>
  );
}
