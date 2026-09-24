import type { RunExplanation as Explanation } from './api';

const names: Record<string, string> = {
  completed: 'Completed', failure: 'Stopped', business_outcome: 'Expected outcome',
  business: 'Expected outcome', recover: 'Recovery needed', intervene: 'Human help needed',
  running: 'In progress', attempted: 'Attempt recorded', completion_unknown: 'Completion not recorded',
};
const duration = (ms: number) => `${(ms / 1000).toFixed(2)} s`;

export default function RunExplanation({ value }: { value?: Explanation | null }) {
  if (!value) return <p>A readable explanation will appear when execution evidence is available.</p>;
  const routineChecks = value.timeline.filter(entry => entry.operation === 'page.check' && entry.state === 'completed');
  const visibleSteps = value.timeline.filter(entry => entry.operation !== 'page.check' || entry.state !== 'completed');
  return <section className="run-explanation" aria-label="Run explanation">
    <p className="eyebrow">WHAT HAPPENED</p>
    <h3>{value.task}</h3>
    <p className="run-summary">{value.summary}</p>
    {value.stopped_at && <p><strong>Stopped during:</strong> {value.stopped_at}</p>}
    {value.last_completed_action && <p><strong>Last completed action:</strong> {value.last_completed_action}</p>}
    {value.status !== 'success' && <p>{value.write_note}</p>}
    <dl className="run-facts">
      <div><dt>Actions completed</dt><dd>{value.completed_actions ?? 'Not recorded'} / {value.attempted_actions} attempted</dd></div>
      <div><dt>AI calls</dt><dd>{value.model_calls}{value.mode === 'replay' ? ' during replay' : ''}</dd></div>
      <div><dt>Elapsed time</dt><dd>{value.elapsed_ms === null ? 'In progress or unavailable' : duration(value.elapsed_ms)}</dd></div>
      <div><dt>Human control</dt><dd>{value.human_assisted ? 'Used' : 'Not used'}</dd></div>
      <div><dt>Result checks</dt><dd>{value.verification_passed === true ? 'Passed' : value.verification_passed === false ? 'Not completed successfully' : 'See recorded result'}</dd></div>
      <div><dt>Result values</dt><dd>{value.outputs_count} collected</dd></div>
    </dl>
    <p className="run-next-step"><strong>Next step:</strong> {value.next_step}</p>
    <details open={value.status === 'failure'}>
      <summary>See what the browser did ({visibleSteps.length} entries)</summary>
      <p className="muted">A completed click means the browser performed the click. The following page and result checks decide whether the task succeeded.</p>
      <ol className="run-timeline">
        {visibleSteps.map((entry, index) => <li key={index} className={`run-step run-step-${entry.state}`}>
          <div className="run-step-heading"><strong>{entry.title}</strong><span>{names[entry.state] || 'Recorded'}{entry.duration_ms !== undefined ? ` · ${duration(entry.duration_ms)}` : ''}</span></div>
          {entry.purpose && <p>{entry.purpose}</p>}
          {entry.explanation && <p>{entry.explanation}</p>}
          {entry.next_step && <p>{entry.next_step}</p>}
        </li>)}
      </ol>
      {routineChecks.length > 0 && <details><summary>Routine page checks ({routineChecks.length})</summary><ul>{routineChecks.map((entry,index) => <li key={index}>{entry.title}: completed{entry.duration_ms !== undefined ? ` in ${duration(entry.duration_ms)}` : ''}</li>)}</ul></details>}
    </details>
    <details>
      <summary>Technical details and privacy</summary>
      <p>{value.input_tokens} reported input tokens and {value.output_tokens} output tokens. Model count basis: {value.model_calls_basis}.</p>
      {value.error_code && <p>Error code: <code>{value.error_code}</code></p>}
      <p>{value.write_note}</p>
      <p>{value.limitations}</p>
    </details>
  </section>;
}
