import re

with open('sabari_project/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove sidebar demo entries
# We look for lines like: { separator: true, label: 'Demo' }, and { id: 'n_demo_replay', label: 'Patient Arc Replay' },
content = re.sub(r'\s*\{\s*separator:\s*true,\s*label:\s*\'(?:Demo|Simulation)\'\s*\},', '', content)
content = re.sub(r'\s*\{\s*id:\s*\'n_demo_replay\',\s*label:\s*\'Patient Arc Replay\'\s*\},', '', content)

# 2. Fix the AI demo tag (line 498 area)
content = content.replace(
    '`<div class="ews-ai" title="Illustrative deterioration risk — predictive model in training (Sprint 4)">AI ${p.mlRisk}% <span class="demo-tag">demo</span></div>`',
    '`<div class="ews-ai" title="AI predictive deterioration risk">AI ${p.mlRisk}%</div>`'
)

# 3. Fix the ML Insights panel (Sprint 4 text)
old_ml_insights = """  // ── ML Insights (DEMO placeholder — predictive model in training) ──
  const mlContribs = (p.mlContributors || []).map(c =>
    `<div class="ml-bar-row"><div class="ml-bar-lbl">${c.label}</div><div class="ml-bar"><div class="ml-bar-fill" style="width:${c.pct}%"></div></div><div class="ml-bar-pct">${c.pct}%</div></div>`
  ).join('') || '<div class="muted small">No abnormal signals contributing.</div>';
  const mlRiskCol = score >= 7 ? 'var(--t1)' : score >= 5 ? 'var(--t2)' : 'var(--t3)';
  const mlInsights = `
    <div class="alert al-info">🧪 <b>Illustrative</b> deterioration risk — the predictive model is in training (Sprint 4). These values are placeholders for demonstration and will be replaced by the trained model's output.</div>
    <div class="grid2">
      <div class="card">
        <div class="card-title">Deterioration Risk — Demo Prediction</div>
        <div style="display:flex;align-items:center;gap:18px;margin-bottom:12px">
          <div class="ml-risk-num" style="color:${mlRiskCol}">${p.mlRisk != null ? p.mlRisk + '%' : '—'}</div>
          <div><div style="font-size:12.5px;font-weight:600">${p.mlWindow || '6-12 hour'} deterioration window</div>
          <div class="muted small">Heuristic demo · recomputed on each vitals entry</div></div>
        </div>
        <b class="small">Top contributing signals (from NEWS2):</b>"""

new_ml_insights = """  // ── ML Insights ──
  const mlContribs = (p.mlContributors || []).map(c =>
    `<div class="ml-bar-row"><div class="ml-bar-lbl">${c.label}</div><div class="ml-bar"><div class="ml-bar-fill" style="width:${c.pct}%"></div></div><div class="ml-bar-pct">${c.pct}%</div></div>`
  ).join('') || '<div class="muted small">No abnormal signals contributing.</div>';
  const mlRiskCol = score >= 7 ? 'var(--t1)' : score >= 5 ? 'var(--t2)' : 'var(--t3)';
  const mlInsights = `
    <div class="grid2">
      <div class="card">
        <div class="card-title">Deterioration Risk Prediction</div>
        <div style="display:flex;align-items:center;gap:18px;margin-bottom:12px">
          <div class="ml-risk-num" style="color:${mlRiskCol}">${p.mlRisk != null ? p.mlRisk + '%' : '—'}</div>
          <div><div style="font-size:12.5px;font-weight:600">${p.mlWindow || '6-12 hour'} deterioration window</div>
          <div class="muted small">Recomputed on each vitals entry</div></div>
        </div>
        <b class="small">Top contributing signals:</b>"""

content = content.replace(old_ml_insights, new_ml_insights)

# 4. Fix AI risk demo tag in detail view
content = content.replace(
    '<div><span class="dx-lbl">AI risk <span class="demo-tag">demo</span></span><b style="color:var(--p)">${p.mlRisk != null ? p.mlRisk + \'%\' : \'—\'}</b></div>',
    '<div><span class="dx-lbl">AI risk</span><b style="color:var(--p)">${p.mlRisk != null ? p.mlRisk + \'%\' : \'—\'}</b></div>'
)

# 5. Remove the entire PATIENT ARC REPLAY DEMO section
# It starts at:
# /* ─────────────────────────────────────────────────────────────────────────────
#    PATIENT ARC REPLAY DEMO  (n_demo_replay)
# ...
# And ends at the end of the file. Wait, is it the very last thing in app.js?
# Let's check if there's anything after SCREENS['n_demo_replay']
import sys
# Just use regex to remove from /* ───... PATIENT ARC REPLAY to the end of the file or next section
content = re.sub(r'/\*\s*─+\s*\n\s*PATIENT ARC REPLAY DEMO[\s\S]+?SCREENS\[\'n_demo_replay\'\][\s\S]+?};\s*\n', '', content)

# Also remove the `} else if (id === 'n_demo_replay') { ... }` block in `nav()`
# It looks like:
# } else if (id === 'n_demo_replay') {
#   APP.data.n_demo_replay = null;
#   renderAll();
# }
content = re.sub(r'\}\s*else\s*if\s*\(\s*id\s*===\s*\'n_demo_replay\'\s*\)\s*\{[\s\S]*?renderAll\(\);\s*\}', '} ', content)

with open('sabari_project/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
