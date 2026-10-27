// Harness Web Worker: Process traces and compute statistics off the main thread
// This keeps the UI responsive while analyzing large trace datasets

self.onmessage = (e) => {
  const { type, traces } = e.data;

  if (type === 'process') {
    try {
      const processed = traces.map((t, idx) => ({
        ...t,
        idx,
        heard: (t.context?.heard || '').slice(0, 200),
        intent: t.output?.intent || 'unknown',
        confidence: t.output?.intent_confidence,
        isAmbiguous: (t.output?.intent_confidence || 1) < 0.75,
        summary: buildSummary(t)
      }));

      const tokenStats = computeTokenStats(processed);
      const metrics = computeMetrics(processed);

      self.postMessage({
        type: 'traces-processed',
        traces: processed,
        tokenStats,
        metrics
      });
    } catch (err) {
      self.postMessage({ type: 'error', message: err.message });
    }
  }
};

function buildSummary(trace) {
  const output = trace.output || {};
  const parts = [];
  if (output.reply) parts.push(`→ "${output.reply.slice(0, 50)}"`);
  if (output.intent) parts.push(`intent: ${output.intent}`);
  if (output.understood !== undefined) parts.push(output.understood ? '✓ understood' : '✗ not understood');
  return parts.join(' · ');
}

function computeTokenStats(traces) {
  const stats = {
    input: 0,
    output: 0,
    total: 0,
    avg: 0,
    max: 0,
    percent: 0
  };

  traces.forEach(t => {
    const in_t = t.input_tokens || 0;
    const out_t = t.output_tokens || 0;
    const total_t = in_t + out_t;
    stats.input += in_t;
    stats.output += out_t;
    stats.total += total_t;
    stats.max = Math.max(stats.max, total_t);
  });

  stats.avg = traces.length ? Math.round(stats.total / traces.length) : 0;
  stats.percent = Math.round((stats.total / 200000) * 100); // Assume 200k context window

  return stats;
}

function computeMetrics(traces) {
  return {
    totalTraces: traces.length,
    avgLatency: traces.length ? Math.round(traces.reduce((a, t) => a + (t.latency_ms || 0), 0) / traces.length) : 0,
    ambiguousCount: traces.filter(t => t.isAmbiguous).length,
    engineMix: traces.reduce((a, t) => {
      a[t.engine] = (a[t.engine] || 0) + 1;
      return a;
    }, {}),
    errorCount: traces.filter(t => t.error).length
  };
}
