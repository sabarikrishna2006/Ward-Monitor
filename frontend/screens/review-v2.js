// Screen — Review V2 (clean document review, passage-level interactivity)

const _rv2OldRenderer = SCREEN_RENDERERS["review"];
const _rv2OldSetup    = SCREEN_SETUP["review"];

// ── NABH section metadata ─────────────────────────────────────────────────────
// Maps NABH section IDs to their number, display title, and icon.
const NABH_META = {
  "s1":  { num:"S1",  label:"Patient Demographics"          },
  "s2":  { num:"S2",  label:"Chief Complaint"               },
  "s3":  { num:"S3",  label:"History of Presenting Illness" },
  "s4":  { num:"S4",  label:"Significant Past History"      },
  "s5":  { num:"S5",  label:"Examination Findings"          },
  "s6":  { num:"S6",  label:"Laboratory Investigations"     },
  "s7":  { num:"S7",  label:"Imaging & Procedure Findings"  },
  "s8":  { num:"S8",  label:"Working Diagnosis"             },
  "s9":  { num:"S9",  label:"Hospital Course"               },
  "s10": { num:"S10", label:"Procedures Performed"          },
  "s11": { num:"S11", label:"Discharge Medications"         },
  "s12": { num:"S12", label:"Follow-up & Discharge Advice"  },
  "s13": { num:"S13", label:"Discharge Diagnosis"           },
  "s14": { num:"S14", label:"Condition at Discharge"        },
  "s15": { num:"S15", label:"Patient Acknowledgement"       },
};

// ── Summary markdown parser ───────────────────────────────────────────────────
// Converts the LLM markdown summary (NABH 15-section format) into passage objects.

// Map a section title (no "S# —" prefix) to its NABH id by keyword.
// Handles legacy summaries that use plain headers like "**Investigations:**".
function rv2InferNabhId(title) {
  const t = title.toLowerCase().replace(/[:.]+$/, "").trim();
  const rules = [
    ["s1",  /patient demographic|demographic/],
    ["s2",  /chief complaint/],
    ["s3",  /presenting illness|present illness|hpi|history of present/],
    ["s4",  /past (medical )?history|significant past/],
    ["s5",  /examination finding|physical exam/],
    ["s6",  /lab(oratory)? investigation|^investigation|lab result|laborator/],
    ["s7",  /imaging|radiolog|procedure finding/],
    ["s8",  /working diagnosis/],
    ["s9",  /hospital course|course in hospital/],
    ["s10", /procedure(s)? performed/],
    ["s11", /discharge medication|^medication/],
    ["s12", /follow.?up|discharge advice|discharge instruction/],
    ["s13", /discharge diagnosis|final diagnosis/],
    ["s14", /condition at discharge|discharge condition/],
    ["s15", /acknowledg/],
  ];
  for (const [id, re] of rules) if (re.test(t)) return id;
  return null;
}

function rv2ParseSummary(text) {
  const lines    = text.split("\n");
  const rawSects = [];
  let current    = null;

  for (const line of lines) {
    const hm = line.match(/^\*\*([^*]+)\*\*$/);
    if (hm) {
      if (current) rawSects.push(current);
      // Strip trailing colon legacy headers carry (e.g. "Investigations:")
      current = { title: hm[1].trim().replace(/:\s*$/, ""), body: "" };
    } else if (current) {
      current.body += (current.body ? "\n" : "") + line;
    }
  }
  if (current) rawSects.push(current);

  // Sections whose content is a list — split into individual passages
  const listSections = new Set([
    "S10 — Procedures Performed", "Procedures Performed",
    "S11 — Discharge Medications", "Discharge Medications",
    "S13 — Discharge Diagnosis",  "Discharge Diagnosis", "Final Diagnosis",
  ]);

  return rawSects
    .filter(s => s.title !== "DISCHARGE SUMMARY" && s.body.trim())
    .map(s => {
      const body = s.body.trim();
      // Parse NABH number from title like "S1 — Patient Demographics"
      const nabh = s.title.match(/^(S\d+)\s*[—–-]\s*(.+)$/i);
      const cleanTitle = nabh ? nabh[2].trim() : s.title;
      // Prefer explicit "S# —" prefix; otherwise infer from the section name
      // so legacy headers ("Investigations", "Condition at Discharge") still
      // map to s6/s14 and render their tables.
      const nabhNum  = nabh ? nabh[1].toLowerCase() : rv2InferNabhId(cleanTitle);
      const id = nabhNum || cleanTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      let passages = [];

      if (listSections.has(s.title) || listSections.has(cleanTitle)) {
        body.split("\n")
          .map(l => l.trim())
          .filter(Boolean)
          .forEach((line, i) => {
            passages.push({
              id:      `p-${id}-${i}`,
              text:    line.replace(/^\d+\.\s+/, ""),
              support: "strong",
            });
          });
      } else {
        passages.push({ id: `p-${id}-0`, text: body, support: "strong" });
      }

      const meta = nabhNum ? NABH_META[nabhNum] : null;
      return {
        id,
        title: cleanTitle,
        nabhNum: nabhNum ? nabhNum.toUpperCase() : null,
        nabhLabel: meta ? meta.label : cleanTitle,
        nabhIcon:  null,
        passages: passages.filter(p => p.text),
      };
    })
    .filter(s => s.passages.length > 0);
}

let _rv2 = {
  auditMode:       false,
  selectedId:      null,
  editingId:       null,
  editText:        "",
  edits:           {},
  comments:        {},
  commentingId:    null,
  commentText:     "",
  sourceId:        null,
  sourceTechOpen:  false,
  revisionId:      null,
  revisionText:    "",
  resolved:        new Set(),
  bannerDone:      false,
  clinicalCtx:     null,
  ctxLoading:      false,
  ctxError:        null,
  ctxHadmId:       null,
  activeSectionId: null,
  activeCtxTab:    null,       // null = no tab; else a key from _RV2_CTX_TABS
  mobileTab:       "summary",  // "summary" | "source"
  srcTabData:      {},         // tabKey → loaded data
  srcTabLoading:   {},         // tabKey → bool
  srcTabError:     {},         // tabKey → error string
  srcDisplayData:  null,       // shared /display endpoint result
  srcDispLoading:  false,
  srcPanelWidth:      400,
  aifixId:            null,
  aifixText:          "",
  aifixLoading:       false,
  aifixRecording:     false,
  aifixError:         null,
  revisionModalOpen:  false,
  revisionModalText:  "",
  s6EditItems:        null,
  s6EditPassageId:    null,
  fullscreen:         null,   // null | "summary" | "source"
  editTier:           1,      // 1 = Minor Edit, 2 = Medication Error (for error log)
  editOrigText:       "",     // original text before edit (captured on ✏ click)
  tierPanelId:        null,   // section id whose tier issues panel is currently expanded
  llmRevisions:       {},     // passageId → S4d revision object {status, original, revised, confidence, ...}
  // ── Version history drawer ─────────────────────────────────────────────────
  historyOpen:        false,
  historyVersions:    null,   // null = not fetched, [] = empty, [...] = loaded
  historyLoading:     false,
  historyError:       null,
  viewingVersionId:   null,   // UUID of version being viewed read-only
  viewingVersion:     null,   // full version object
  compareMode:        false,  // showing diff view inside drawer
  compareSelA:        null,   // version UUID selected for compare (older)
  compareSelB:        null,   // version UUID selected for compare (newer)
  comparePending:     false,
  compareDataA:       null,   // full version object A
  compareDataB:       null,   // full version object B
  // ── Per-section error reporting ────────────────────────────────────────────
  flagFormSectionId:       null,   // which section's ⚑ flag form is open
  pilotPauseBanner:        null,   // { rate_pct } if T3 gate >25%, else null
  resolvedTierSections:    new Set(), // section IDs (e.g. "s6") where doctor resolved tier errors
  esignOpen:               false,  // e-sign canvas modal open
};

// ── Data helpers ──────────────────────────────────────────────────────────────

function rv2BuildDocSections(claims) {
  function cp(id) {
    const c = claims.find(x => x.id === id);
    if (!c) return null;
    return {
      id:      c.id,
      text:    c.text,
      support: c.status === "v" ? "strong" : c.status === "a" ? "uncertain" : "conflict",
      chunkId: c.chunkId,
      edited:  c.edited || false,
    };
  }
  const mk = (nabhNum, passages) => {
    const meta = NABH_META[nabhNum];
    return { id: nabhNum, title: meta.label, nabhNum: nabhNum.toUpperCase(), nabhLabel: meta.label, nabhIcon: null, passages };
  };
  return [
    mk("s1", [
      { id:"s1-1", text:"Mr Rohan Patel, 52-year-old male. HADM 24181354. Admitted: 12 March 2026. Discharged: 16 March 2026.", support:"strong" },
      { id:"s1-2", text:"Consulting Cardiologist: Dr. A. Mehta. Ward: Cardiac. Foqal Hospital, Gurugram.", support:"strong" },
    ]),
    mk("s2", [
      { id:"s2-1", text:"The patient was admitted as an emergency with a primary documented diagnosis of Acute Anterior STEMI.", support:"strong" },
    ]),
    mk("s3", [
      { id:"s3-1", text:"Elective admission for symptomatic cholelithiasis presenting with recurrent right upper quadrant pain and nausea. Referred for surgical management.", support:"strong" },
    ]),
    mk("s4", [
      { id:"s4-1", text:"Hypertension — on treatment for 5 years.", support:"strong" },
      { id:"s4-2", text:"Type 2 Diabetes Mellitus — on treatment for 3 years.", support:"strong" },
      cp("c052") || { id:"s4-3", text:"No known drug allergies.", support:"strong" },
    ]),
    mk("s5", [
      { id:"s5-1", text:"BP 94/60 mmHg, HR 112 bpm (irregular), SpO₂ 94% on room air, RR 22/min. Patient diaphoretic on examination.", support:"strong" },
    ]),
    mk("s6", [
      { id:"s6-1", text:"Troponin I: 12.4 ng/mL (abnormal). HbA1c: 8.2%. Creatinine: 1.1 mg/dL. LDL: 168 mg/dL. CBC: Hb 12.1 g/dL.", support:"strong" },
    ]),
    mk("s7", [
      cp("c041") || { id:"s7-1", text:"2D Echo (13 March 2026): LVEF 38%, anterior wall motion abnormality. CXR (12 March 2026): cardiomegaly, bilateral basal haziness.", support:"strong" },
    ]),
    mk("s8", [
      { id:"s8-1", text:"Working diagnosis on admission: Acute Anterior ST-Elevation Myocardial Infarction (STEMI). GRACE score 148 (high risk). Primary PCI pathway activated.", support:"strong" },
    ]),
    mk("s9", [
      { id:"s9-1", text:"Admitted to CCU. Primary PCI performed to LAD on day 1. Patient transferred to cardiac ward on day 3. Vitals monitored continuously throughout stay.", support:"strong" },
      { id:"s9-2", text:"Medication administrations from eMAR: 18 administrations across 6 drug classes over 5-day stay.", support:"strong" },
    ]),
    mk("s10", [
      cp("c041") || { id:"s10-1", text:"Primary PCI — LAD (12 March 2026, Dr. A. Mehta). DES stent 3.0×28mm deployed. TIMI 3 flow achieved post-procedure.", support:"strong" },
    ]),
    mk("s11",
      ["c043","c047","c049","c055","c058"].map(cp).filter(Boolean).length > 0
        ? ["c043","c047","c049","c055","c058"].map(cp).filter(Boolean)
        : [
            { id:"s11-1", text:"Ecosprin 75mg – PO", support:"strong" },
            { id:"s11-2", text:"Clopivas 75mg – PO", support:"strong" },
            { id:"s11-3", text:"Atorva 80mg – PO", support:"strong" },
            { id:"s11-4", text:"Metolar XR 25mg – PO", support:"strong" },
            { id:"s11-5", text:"Ramipril 5mg – PO", support:"strong" },
          ]
    ),
    mk("s12", [
      { id:"s12-1", text:"Follow-up with Cardiology as arranged. OPD review in 4 weeks with Dr. Mehta. Repeat echo at 4 weeks. HbA1c at 3 months.", support:"strong" },
      { id:"s12-2", text:"Return to emergency immediately if chest pain, dyspnoea, or palpitations. Do not stop DAPT (aspirin + clopidogrel) without physician advice.", support:"strong" },
    ]),
    mk("s13", [
      { id:"s13-1", text:"Acute Anterior STEMI (I21.01)", support:"strong" },
      { id:"s13-2", text:"Hypertension (I10)", support:"strong" },
      { id:"s13-3", text:"Type 2 Diabetes Mellitus (E11.9)", support:"strong" },
    ]),
    mk("s14", [
      { id:"s14-1", text:"Discharge type: Standard. Discharge destination: Home. BP 118/74 mmHg, HR 68 bpm, SpO₂ 98% on room air. NYHA Class II at discharge.", support:"strong" },
    ]),
    mk("s15", [
      { id:"s15-1", text:"Patient acknowledgement to be confirmed by the resident prior to physician sign-off (NABH MN4 requirement). Signature and timestamp to be recorded in the physical file.", support:"uncertain" },
    ]),
  ];
}

function rv2GetCleanSource(chunkId) {
  const chunk = window.CHUNKS && window.CHUNKS[chunkId];
  if (!chunk) return null;
  return {
    text:       chunk.text,
    recordType: chunk.type,
    section:    chunk.section,
    timestamp:  chunk.timestamp,
    author:     chunk.author,
    chunkId,
    noteType:   chunk.type,
    rawNote:    chunk.note || null,
  };
}

function rv2AllPassages(docSections) {
  return docSections.reduce((a, s) => a.concat(s.passages), []);
}

// ── Render helpers ────────────────────────────────────────────────────────────

function rv2_sourcePanel(source, passageId) {
  return `
    <div style="margin-top:8px;border-radius:8px;overflow:hidden;border:1px solid #CBD5E1;background:var(--surface-1)">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--surface-0)">
        <div style="display:flex;align-items:center;gap:7px">
          ${iconSVG("doc",13)}
          <span style="font-size:12px;font-weight:700;color:var(--ink-2);letter-spacing:0.01em">Retrieved Evidence</span>
        </div>
        <button data-toggle-source-id="${passageId}" style="background:none;border:none;cursor:pointer;color:var(--ink-4);font-size:13px;padding:2px 6px;border-radius:4px;font-family:inherit">${iconSVG("x",12)}</button>
      </div>
      <div style="padding:14px 16px">
        <div style="font-family:Georgia,'Times New Roman',serif;font-size:15px;line-height:1.75;color:#1E293B;background:#F8FAFF;border:1px solid #BFDBFE;border-radius:6px;padding:12px 16px;margin-bottom:14px">
          ${source.text}
        </div>
        <div style="display:grid;grid-template-columns:88px 1fr;gap:5px 10px;font-size:12.5px;margin-bottom:14px">
          ${[["Note type",source.recordType],["Section",source.section],["Date / Time",source.timestamp],["Author",source.author]].map(([k,v])=>`
            <span style="color:var(--ink-4);font-weight:600">${k}</span>
            <span style="color:var(--ink-2)">${v||"—"}</span>
          `).join("")}
        </div>
        <div>
          <button id="rv2-tech-toggle" style="background:none;border:none;cursor:pointer;display:flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ink-4);padding:0;font-family:inherit">
            <span style="font-size:10px">${_rv2.sourceTechOpen?"▼":"▶"}</span> Technical retrieval details
          </button>
          ${_rv2.sourceTechOpen ? `
            <div style="margin-top:8px;padding:10px 12px;background:var(--surface-0);border:1px solid var(--line);border-radius:5px">
              <div style="display:grid;grid-template-columns:88px 1fr;gap:4px 10px;font-size:11.5px;font-family:var(--mono)">
                <span style="color:var(--ink-4)">chunk_id</span><span style="color:var(--ink-3);word-break:break-all">${source.chunkId||"—"}</span>
                <span style="color:var(--ink-4)">note_type</span><span style="color:var(--ink-3)">${source.noteType||"—"}</span>
                <span style="color:var(--ink-4)">section</span><span style="color:var(--ink-3)">${source.section||"—"}</span>
              </div>
              <div style="margin-top:8px;padding:6px 8px;background:var(--surface-1);border-radius:4px;font-size:10.5px;color:var(--ink-4);font-family:var(--mono);line-height:1.5">
                This section is intended for compliance and AI debugging only.
              </div>
            </div>
          ` : ""}
        </div>
      </div>
    </div>`;
}

// ── Shared lab group parser (handles both *CBC*: and CBC: formats) ────────────
function rv2ParseLabGroups(text) {
  const partsA = text.split(/\*([^*]+)\*:\s*/);
  if (partsA.length >= 3) {
    const g = {};
    for (let i = 1; i < partsA.length; i += 2) {
      g[partsA[i].trim()] = (partsA[i+1]||'').replace(/\.\s*$/,'').split(';').map(s=>s.trim()).filter(Boolean);
    }
    return g;
  }
  const partsB = text.split(/(?:^|\.\s*)([A-Z][A-Za-z\/&,() -]{1,40}):\s*/);
  if (partsB.length >= 3) {
    const g = {};
    for (let i = 1; i < partsB.length; i += 2) {
      const raw = (partsB[i+1]||'').replace(/\.\s*$/,'').trim();
      if (raw) g[partsB[i].trim()] = raw.split(';').map(s=>s.trim()).filter(Boolean);
    }
    return g;
  }
  return null;
}

// ── Inline table editor for S6 Labs ──────────────────────────────────────────
function rv2RenderS6Editor(passageId, groups) {
  const palette = ['#3B82F6','#8B5CF6','#10B981','#F59E0B','#EF4444','#EC4899','#14B8A6','#6366F1','#F97316','#64748B'];
  const btnBase = "display:inline-flex;align-items:center;gap:5px;padding:7px 16px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;font-family:inherit;";
  const inp = "width:100%;border:1px solid #E2E8F0;border-radius:4px;padding:4px 8px;font-size:12.5px;color:#1E293B;font-family:inherit;outline:none;background:white;box-sizing:border-box";

  const bodyRows = Object.entries(groups).flatMap(([name, items], gi) => {
    const color = palette[gi % palette.length];
    const header = `<tr><td colspan="4" style="padding:6px 12px;background:${color}12;border-top:2px solid ${color};border-bottom:1px solid ${color}30">
      <span style="font-size:11px;font-weight:700;color:${color};text-transform:uppercase;letter-spacing:.07em">${name.replace(/</g,'&lt;')}</span>
      <span style="margin-left:8px;font-size:10px;color:${color}80">${items.length} values</span>
    </td></tr>`;

    const dataRows = items.map((item, idx) => {
      const abn  = /\(abnormal\)/i.test(item);
      const clean = item.replace(/\s*\(abnormal\)\s*/gi,'').trim();
      const vm   = clean.match(/^(.+?)\s+([\d<>≤≥~][^\s]*)(\s+[^\d].+)?$/);
      const lbl  = (vm ? vm[1] : clean).replace(/"/g,'&quot;');
      const val  = (vm ? (vm[2]+(vm[3]||'')).trim() : '').replace(/"/g,'&quot;');
      return `<tr class="rv2-s6-row" data-group="${name.replace(/"/g,'&quot;')}" data-idx="${idx}" style="background:${idx%2?'#F9FAFB':'white'}">
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9"><input class="rv2-s6-name" type="text" value="${lbl}" style="${inp}"/></td>
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9"><input class="rv2-s6-val" type="text" value="${val}" style="${inp}"/></td>
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9;text-align:center">
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;justify-content:center">
            <input class="rv2-s6-abn" type="checkbox" ${abn?'checked':''} style="accent-color:#DC2626;width:13px;height:13px"/>
            <span class="rv2-s6-abn-lbl" style="font-size:11px;color:${abn?'#DC2626':'#94A3B8'}">${abn?'Abnormal':'Normal'}</span>
          </label>
        </td>
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9;text-align:center">
          <button class="rv2-s6-del" data-group="${name.replace(/"/g,'&quot;')}" data-idx="${idx}" style="border:none;background:none;color:#CBD5E1;cursor:pointer;font-size:17px;line-height:1;padding:0" title="Remove row">×</button>
        </td>
      </tr>`;
    }).join('');

    const addRow = `<tr><td colspan="4" style="padding:5px 12px;border-bottom:1px solid #F1F5F9">
      <button class="rv2-s6-add" data-group="${name.replace(/"/g,'&quot;')}" style="font-size:12px;color:${color};background:none;border:1px dashed ${color}60;border-radius:4px;padding:3px 10px;cursor:pointer;font-family:inherit">+ Add row</button>
    </td></tr>`;

    return [header, dataRows, addRow];
  }).join('');

  return `
    <table id="rv2-s6-table" style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:12px">
      <thead><tr style="background:#F8FAFC;border-bottom:1.5px solid #E2E8F0">
        <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;width:38%">Investigation</th>
        <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;width:37%">Result</th>
        <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:center;width:15%">Status</th>
        <th style="width:10%"></th>
      </tr></thead>
      <tbody id="rv2-s6-tbody">${bodyRows}</tbody>
    </table>
    <div style="display:flex;gap:8px;align-items:center">
      <button data-save-edit-id="${passageId}" style="${btnBase}border:1px solid #2A6F77;background:#2A6F77;color:white;">Save changes</button>
      <button id="rv2-cancel-edit" style="${btnBase}border:1px solid #E2E8F0;background:white;color:#475569;">Cancel</button>
      <div style="flex:1"></div>
      <button data-table-aifix-id="${passageId}" style="${btnBase}border:1px solid #7C3AED;background:white;color:#7C3AED;">✦ AI Fix</button>
    </div>`;
}

// ── S4d — LLM Revision helpers ────────────────────────────────────────────────

function rv2WordDiff(orig, revised) {
  const safe = s => s.replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const ow = orig.split(/\s+/).filter(Boolean);
  const rw = revised.split(/\s+/).filter(Boolean);
  const origSet = new Set(ow.map(w => w.toLowerCase().replace(/[^a-z0-9]/g,'')));
  const revSet  = new Set(rw.map(w => w.toLowerCase().replace(/[^a-z0-9]/g,'')));

  const removed = ow.filter(w => !revSet.has(w.toLowerCase().replace(/[^a-z0-9]/g,'')));
  const rmHtml  = removed.map(w =>
    `<span style="background:#FECACA;color:#7F1D1D;text-decoration:line-through;border-radius:2px;padding:0 2px">${safe(w)}</span>`
  ).join(' ');
  const addHtml = rw.map(w =>
    origSet.has(w.toLowerCase().replace(/[^a-z0-9]/g,''))
      ? safe(w)
      : `<span style="background:#BBF7D0;color:#14532D;border-radius:2px;padding:0 2px">${safe(w)}</span>`
  ).join(' ');

  return (rmHtml ? `<div style="margin-bottom:6px;line-height:1.9">${rmHtml}</div>` : '') +
         `<div style="line-height:1.9">${addHtml}</div>`;
}

function rv2MockRevision(id, text, sectionId) {
  const additions = {
    s1: "Admission via Emergency Cardiology. DPDPA consent obtained and documented.",
    s2: "Presenting symptom onset 4 hours prior to admission with associated diaphoresis.",
    s5: "12-lead ECG: new-onset LBBB — rate 72 bpm, QRS 142ms. URGENT cardiology review documented.",
    s6: "ABG: pH 7.34, pCO₂ 48 mmHg, pO₂ 68 mmHg on room air (Type 2 respiratory failure pattern).",
    s7: "Troponin trend: 12.4 → 18.7 → 9.2 ng/mL (peak at 6h). Dynamic ischaemic pattern confirmed.",
    s8: "GRACE score: 148 — high risk. Primary PCI pathway activated within 90-minute door-to-balloon target.",
    s9: "Dual antiplatelet therapy (DAPT) administered within 90-minute door-to-balloon target per protocol.",
    s11:"Bisoprolol 2.5mg OD added per cardiology discharge protocol. Potassium supplementation documented.",
    s13:"LBBB (I44.7) added to final discharge diagnoses as secondary finding.",
    s14:"Documented NYHA Class II functional status at time of discharge.",
  };
  const addition  = additions[sectionId] || "Additional clinical context verified from source records per NABH documentation requirements.";
  const revised   = text + " " + addition;
  const conf      = 88 + Math.floor(Math.random() * 10);
  const now       = new Date().toLocaleTimeString("en-IN", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
  const drName    = (typeof getUser === "function" && getUser()?.full_name) ? `Dr. ${getUser().full_name}` : "Dr. Anand Sharma";
  return {
    status:      "ready",
    original:    text,
    revised,
    confidence:  conf,
    source:      "Discharge Summary Draft.pdf",
    sourcePage:  "p. 1",
    sourceQuote: text.slice(0, 90) + (text.length > 90 ? "…" : ""),
    reasoning:   `The uploaded source document contains clinical data that was absent from the auto-generated section. Revision adds verified information to meet NABH documentation standards. Cross-referenced with uploaded clinical records and confirmed against patient data.`,
    diffMode:    false,
    auditItems:  [
      { icon:"💬", label:"Comment submitted", time:now, user:drName, text:"Verify and add missing clinical context" },
      { icon:"✨", label:"LLM revision generated", time:now, detail:`Confidence ${conf}%` },
    ],
  };
}

function rv2RenderLlmRevisionPanel(id, rev) {
  const safe    = s => s.replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const btnBase = "display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;font-family:inherit;";

  return `
    <div style="margin-top:8px;border-radius:8px;overflow:hidden;border:1.5px solid #BAE6FD">

      <!-- Header bar -->
      <div style="padding:10px 14px;background:#0C4A6E;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span style="font-size:13px;font-weight:800;color:white">${rev.title || '✨ LLM Revised Version'}</span>
        <span style="background:rgba(255,255,255,.15);color:#BAE6FD;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:10px">Confidence: ${rev.confidence}%</span>
        <span style="background:rgba(255,255,255,.10);color:#BAE6FD;font-size:10.5px;padding:2px 8px;border-radius:10px">📄 ${rev.source}</span>
        <button data-diffmode-id="${id}" style="margin-left:auto;background:${rev.diffMode?'rgba(255,255,255,.25)':'none'};border:1px solid rgba(255,255,255,.35);color:white;padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit">
          Diff View ${rev.diffMode?'▲':'▼'}
        </button>
      </div>

      ${rev.diffMode ? `
        <div style="padding:14px 16px;background:white;border-bottom:1px solid #E0F2FE">
          <div style="font-size:11px;color:#64748B;font-weight:700;margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em">Diff View — Red = removed · Green = added</div>
          <div style="font-size:13.5px">${rv2WordDiff(rev.original, rev.revised)}</div>
        </div>
      ` : `
        <div style="display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid #E0F2FE">
          <div style="padding:12px 16px;border-right:1px solid #E0F2FE">
            <div style="font-size:10px;font-weight:700;color:#64748B;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Original (Auto-generated)</div>
            <div style="font-size:13px;line-height:1.8;color:#374151">${safe(rev.original)}</div>
          </div>
          <div style="padding:12px 16px;background:#F0FFF4">
            <div style="font-size:10px;font-weight:700;color:#15803D;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">✨ LLM Revised</div>
            <div style="font-size:13px;line-height:1.8;color:#14532D">${safe(rev.revised)}</div>
          </div>
        </div>
      `}

      <!-- Actions -->
      <div style="padding:10px 16px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:white">
        <button data-reject-llmrev-id="${id}" style="${btnBase}border:1px solid #E2E8F0;background:white;color:#475569;">Reject</button>
        <button data-rerequest-llmrev-id="${id}" style="${btnBase}border:1px solid #CBD5E1;background:white;color:#374151;">Request Different Revision</button>
        <div style="flex:1"></div>
        <button data-accept-llmrev-id="${id}" style="${btnBase}border:1px solid #15803D;background:#15803D;color:white;">Accept Revision ✓</button>
      </div>

    </div>`;
}

// Highlights quote strings inside pre-rendered HTML by replacing only text nodes (not attribute values or tags).
// If the quote ends mid-word (e.g. "urinary trac"), the highlight expands to the full word boundary.
function _rv2HlQuotes(html, quotes) {
  if (!quotes || !quotes.length) return html;
  return html.replace(/(<[^>]*>)|([^<]+)/g, (_, tag, txt) => {
    if (tag) return tag;
    let out = txt;
    for (const q of quotes) {
      if (!q || q.length < 3) continue;
      const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      // Extend match to word boundary if the quote ends mid-word
      const trailer = /\w$/.test(q) ? '\\w*' : '';
      const re = new RegExp(escaped + trailer, 'gi');
      out = out.replace(re, m => `<mark style="background:#FEF08A;border-radius:2px;padding:0 2px;font-weight:700;outline:2px solid #EAB308">${m}</mark>`);
    }
    return out;
  });
}

function rv2_passage(passage, sectionId, highlightQuotes) {
  const id           = passage.id;
  const displayText  = _rv2.edits[id] !== undefined ? _rv2.edits[id] : passage.text;
  const support      = passage.support;
  const chunkId      = passage.chunkId;
  const edited       = passage.edited || (_rv2.edits[id] !== undefined);

  // Read-only mode when viewing a historical version
  if (_rv2.viewingVersionId) {
    if (displayText === "INCORRECT_STRING") {
      return `<div style="padding:10px 14px;background:#FEF2F2;border-left:4px solid #DC2626;border-radius:4px;margin-bottom:6px;font-size:12.5px;color:#991B1B">⚠ Section failed AI confidence check — manual entry required.</div>`;
    }
    return `<div style="padding:6px 6px 6px 18px;border-left:4px solid #C8A0C8;margin-bottom:6px;color:#374151;font-size:13.5px;line-height:1.7">${displayText.replace(/\n/g,"<br>")}</div>`;
  }

  // Failed confidence gate — show placeholder instead of raw "INCORRECT_STRING"
  if (displayText === "INCORRECT_STRING") {
    const btnBase = "display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;font-family:inherit;transition:all .14s;";
    return `<div style="padding:12px 14px;background:#FEF2F2;border-left:4px solid #DC2626;border-radius:0 8px 8px 0;margin-bottom:6px">
      <div style="font-size:12.5px;font-weight:700;color:#DC2626;margin-bottom:4px">⚠ AI confidence too low — section could not be auto-generated</div>
      <div style="font-size:12px;color:#6B7280;margin-bottom:10px">The AI was not confident enough to generate this section from the source data (below 60% threshold, retries exhausted). Please enter the content manually.</div>
      <button data-edit-id="${id}" data-edit-section="${sectionId||''}" style="${btnBase}border:1.5px solid #DC2626;background:white;color:#DC2626;">✏ Enter manually</button>
    </div>`;
  }

  const isSelected   = _rv2.selectedId === id;
  const isEditing    = _rv2.editingId  === id;
  const isAifix      = _rv2.aifixId   === id;
  const isSource     = _rv2.sourceId  === id;
  const isRevision   = _rv2.revisionId === id;
  const isResolved   = _rv2.resolved.has(id);
  const source       = chunkId ? rv2GetCleanSource(chunkId) : null;
  const effSupport   = isResolved ? "strong" : support;

  const borders = {
    strong:    "border-left:4px solid #A8D9BC;background:transparent;",
    uncertain: "border-left:4px solid #D97706;background:rgba(217,119,6,0.04);",
    conflict:  "border-left:4px solid #DC2626;background:rgba(220,38,38,0.05);",
  };
  const btnBase = "display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;font-family:inherit;transition:all .14s;";

  const llmRev   = _rv2.llmRevisions[id];
  const isLlmRev = !!llmRev;

  // Toolbar (shown when selected, not editing)
  let toolbarHTML = "";
  if (isSelected && !isEditing) {
    toolbarHTML = `
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;padding-top:6px;padding-bottom:4px;border-top:1px dashed #EDE3ED;margin-top:4px">
        <button data-edit-id="${id}" data-edit-section="${sectionId||''}" style="${btnBase}border:1px solid #E0D0E0;background:white;color:#2A102A;">✏ Edit</button>
        <button data-aifix-id="${id}" style="${btnBase}border:1px solid #A020A0;background:${isAifix?"#F5E6F5":"white"};color:#800080;">✦ AI Fix</button>
        ${source ? `<button data-source-id="${id}" style="${btnBase}border:1px solid #E0D0E0;background:${isSource?"#F5E6F5":"white"};color:#6B4A6B;">View Source</button>` : ""}
        ${(support==="uncertain"||support==="conflict")&&!isResolved ? `
          <button data-mark-id="${id}" style="${btnBase}border:1px solid #A8D9BC;background:#E6F7F2;color:#065F46;">✓ Mark reviewed</button>
          <button data-revision-id="${id}" style="${btnBase}border:1px solid #EDD08A;background:${isRevision?"#FEF3CD":"white"};color:#92400E;">⟳ Revision</button>
        ` : ""}
      </div>`;
  }

  // Body — editing textarea or clickable text
  let bodyHTML = "";
  if (isEditing) {
    if (sectionId === 's6' && _rv2.s6EditItems && _rv2.s6EditPassageId === id) {
      bodyHTML = rv2RenderS6Editor(id, _rv2.s6EditItems);
    } else {
      const safeText = _rv2.editText.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
      const isMedSection = sectionId === "s11";
      const curTier = _rv2.editTier || (isMedSection ? 2 : 1);
      const tierBtnBase = "padding:3px 10px;border-radius:99px;font-size:10.5px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .12s;";
      bodyHTML = `
        <div style="padding-top:4px;padding-bottom:6px">
          <textarea id="rv2-edit-ta" style="width:100%;font-size:13.5px;line-height:1.8;color:#1E293B;border:1.5px solid #93C5FD;border-radius:6px;padding:8px 10px;resize:vertical;min-height:80px;background:#F8FAFF;outline:none;box-sizing:border-box;font-family:inherit">${safeText}</textarea>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;flex-wrap:wrap;gap:6px">
            <div style="display:flex;align-items:center;gap:5px">
              <span style="font-size:10px;color:#64748B;font-weight:600;letter-spacing:.04em">ERROR TYPE:</span>
              <button class="rv2-tier-btn" data-tier="1" style="${tierBtnBase}border:${curTier===1?"2px solid #2563EB":"1.5px solid #CBD5E1"};background:${curTier===1?"#DBEAFE":"#F8FAFC"};color:${curTier===1?"#1D4ED8":"#64748B"}">T1 Minor</button>
              <button class="rv2-tier-btn" data-tier="2" style="${tierBtnBase}border:${curTier===2?"2px solid #D97706":"1.5px solid #CBD5E1"};background:${curTier===2?"#FEF3C7":"#F8FAFC"};color:${curTier===2?"#92400E":"#64748B"}">T2 Medication</button>
            </div>
            <div style="display:flex;gap:8px">
              <button data-save-edit-id="${id}" style="${btnBase}border:1px solid #2A6F77;background:#2A6F77;color:white;">Save</button>
              <button id="rv2-cancel-edit" style="${btnBase}border:1px solid #E2E8F0;background:white;color:#475569;">Cancel</button>
            </div>
          </div>
        </div>`;
    }
  } else {
    const editBadge = edited ? `<span style="display:inline-block;margin-left:8px;font-size:10.5px;color:#800080;background:#F5E6F5;border:1px solid #D4A0D4;border-radius:20px;padding:1px 8px;vertical-align:middle;font-family:inherit;font-weight:700">Edited</span>` : "";
    const conflictBox = effSupport==="conflict" ? `
      <div style="margin-top:8px;padding:8px 12px;background:#FFF5F5;border:1px solid #FCA5A5;border-radius:8px;font-size:13px;color:#9B1C1C;font-family:inherit;display:flex;align-items:flex-start;gap:8px;line-height:1.6">
        ${iconSVG("alert",13)}<span><strong>Conflicting evidence</strong> — please verify this information before signing.</span>
      </div>` : "";
    const resolvedBadge = isResolved&&support!=="strong" ? `
      <div style="margin-top:6px;font-size:12px;color:#0D9E6E;display:flex;align-items:center;gap:6px;font-family:inherit;font-weight:600">
        ${iconSVG("check",13)} <span>Reviewed & confirmed</span>
      </div>` : "";
    bodyHTML = `
      <div data-select-id="${id}" data-passage-section="${sectionId||''}" style="cursor:pointer;padding:8px 0 4px;user-select:none">
        ${rv2FormatSectionBody(sectionId, displayText)}${editBadge}${conflictBox}${resolvedBadge}
      </div>`;
  }

  // AI fix panel
  let aifixHTML = "";
  if (isAifix) {
    const safeAifix = _rv2.aifixText.replace(/&/g,"&amp;").replace(/</g,"&lt;");
    const isRec = _rv2.aifixRecording;
    aifixHTML = `
      <div style="margin-top:8px;padding:12px 14px;background:#F5F3FF;border:1px solid #DDD6FE;border-radius:8px">
        <div style="font-size:12px;font-weight:700;color:#5B21B6;margin-bottom:4px;display:flex;align-items:center;gap:6px">
          ✦ AI Fix
          <span style="font-size:10px;font-weight:400;color:#7C3AED;margin-left:2px">· speaks your correction → AI re-reads source data → regenerates this section</span>
        </div>

        <div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:10px">
          <div style="flex:1;position:relative">
            <textarea id="rv2-aifix-ta" placeholder="Speak your correction or type it — e.g. 'Potassium is wrong, source shows 4.1 not 3.1'"
              style="width:100%;font-family:inherit;font-size:13px;color:#1C1917;border:1.5px solid ${isRec?"#DC2626":"#A78BFA"};border-radius:6px;padding:8px 10px;resize:vertical;min-height:80px;background:white;outline:none;box-sizing:border-box;line-height:1.6">${safeAifix}</textarea>
            ${isRec ? `<div style="position:absolute;top:8px;right:8px;display:flex;align-items:center;gap:4px;font-size:10px;color:#DC2626;font-weight:600;background:rgba(255,255,255,0.9);padding:2px 6px;border-radius:4px">
              <span style="width:6px;height:6px;border-radius:50%;background:#DC2626;display:inline-block;animation:pulse 0.8s infinite"></span> Listening…
            </div>` : ""}
          </div>

          <button id="rv2-mic-btn"
            style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:4px;padding:10px 14px;border-radius:8px;cursor:pointer;font-family:inherit;font-size:11px;font-weight:600;border:1.5px solid ${isRec?"#DC2626":"#A78BFA"};background:${isRec?"#FEE2E2":"white"};color:${isRec?"#DC2626":"#7C3AED"};min-width:60px">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="${isRec?"#DC2626":"none"}" stroke="${isRec?"#DC2626":"#7C3AED"}" stroke-width="2"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 19v3M9 22h6"/></svg>
            ${isRec ? "On" : "Speak"}
          </button>
        </div>

        ${_rv2.aifixError ? `<div style="font-size:11.5px;color:#DC2626;background:#FEF2F2;border:1px solid #FCA5A5;border-radius:6px;padding:7px 10px;margin-bottom:8px;line-height:1.5">${_rv2.aifixError}</div>` : ""}
        <div style="display:flex;gap:8px;align-items:center">
          ${_rv2.aifixLoading && _rv2.aifixId === id
            ? `<button disabled style="${btnBase}border:1px solid #7C3AED;background:#7C3AED;color:white;opacity:0.8;gap:8px">
                <div style="width:11px;height:11px;border:2px solid rgba(255,255,255,0.4);border-top-color:white;border-radius:50%;animation:spin 0.7s linear infinite;flex-shrink:0"></div>
                AI regenerating…
              </button>`
            : `<button data-submit-aifix-id="${id}" style="${btnBase}border:1px solid #7C3AED;background:#7C3AED;color:white;">
                ${isRec ? `<span style="width:8px;height:8px;border-radius:50%;background:white;display:inline-block;animation:pulse 0.8s infinite"></span>` : ""}
                Submit to AI
              </button>`
          }
          <button data-cancel-aifix-id="${id}" style="${btnBase}border:1px solid #E2E8F0;background:white;color:#475569;">Cancel</button>
        </div>
      </div>`;
  }
  const existingCommentsHTML = "";

  // Source panel
  let sourcePanelHTML = isSource && source ? rv2_sourcePanel(source, id) : "";

  // Revision panel
  let revisionHTML = "";
  if (isRevision) {
    const safeRev = _rv2.revisionText.replace(/&/g,"&amp;").replace(/</g,"&lt;");
    revisionHTML = `
      <div style="margin-top:8px;padding:10px 12px;background:#EFF6FF;border:1px solid #BFDBFE;border-radius:6px">
        <div style="font-size:12px;font-weight:600;color:#1E40AF;margin-bottom:6px">Describe the issue for revision</div>
        <textarea id="rv2-revision-ta" placeholder="e.g. Dose should be 850 mg BD, not 500 mg" style="width:100%;font-family:inherit;font-size:13px;color:#1C1917;border:1px solid #93C5FD;border-radius:5px;padding:7px 10px;resize:none;min-height:56px;background:white;outline:none;box-sizing:border-box">${safeRev}</textarea>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button data-submit-revision-id="${id}" style="${btnBase}border:1px solid #1D4ED8;background:#1D4ED8;color:white;">Request revision</button>
          <button data-cancel-revision-id="${id}" style="${btnBase}border:1px solid #E2E8F0;background:white;color:#475569;">Cancel</button>
        </div>
      </div>`;
  }

  // S4d — LLM Revision panel
  let llmRevisionHTML = "";
  if (llmRev) {
    if (llmRev.status === "processing") {
      llmRevisionHTML = `
        <div style="margin-top:8px;padding:14px 16px;background:#F0F9FF;border:1px solid #BAE6FD;border-radius:8px;display:flex;align-items:center;gap:10px">
          <div style="width:16px;height:16px;border:2.5px solid rgba(14,116,144,0.3);border-top-color:#0E7490;border-radius:50%;animation:spin 0.7s linear infinite;flex-shrink:0"></div>
          <div>
            <div style="font-size:12.5px;font-weight:700;color:#0E7490">LLM is analysing source documents…</div>
            <div style="font-size:11.5px;color:#0369A1;margin-top:2px">Cross-referencing uploaded records against section content.</div>
          </div>
        </div>`;
    } else if (llmRev.status === "ready") {
      llmRevisionHTML = rv2RenderLlmRevisionPanel(id, llmRev);
    }
  }

  const outline = (isSelected||isEditing) ? "outline:2px solid #B880B8;outline-offset:4px;border-radius:8px;" : "";
  const passageHtml = `
    <div style="margin-bottom:8px;padding:6px 6px 6px 18px;position:relative;border-radius:0 10px 10px 0;${borders[effSupport]}${outline}transition:background .14s">
      ${bodyHTML}${toolbarHTML}${aifixHTML}${existingCommentsHTML}${sourcePanelHTML}${revisionHTML}${llmRevisionHTML}
    </div>`;
  return highlightQuotes && highlightQuotes.length ? _rv2HlQuotes(passageHtml, highlightQuotes) : passageHtml;
}

// ── Source-panel helpers ──────────────────────────────────────────────────────

const _rv2DocNames = {
  s1:'Admission Records', s2:'Admission Notes', s3:'Clinical History',
  s4:'Past Medical History', s5:'Nursing Notes / Vitals',
  s6:'Lab Reports', s7:'Imaging & Procedure Reports',
  s8:'Clinical Assessment', s9:'Hospital Course Notes',
  s10:'Procedure Notes', s11:'Medication Chart',
  s12:'Discharge Instructions', s13:'Diagnosis Records',
  s14:'Discharge Notes', s15:'Acknowledgement Form',
};

// Maps each clinical context block header → which NABH sections it feeds
// Must mirror the Pass 2 SOURCE FIELD → NABH SECTION MAPPING in backend/app/main.py
const _rv2BlockToNabh = {
  'PATIENT & ADMISSION':                    ['S1'],                     // demographics+admission → s1 only; s2=diagnosis, s14=discharge vitals
  'DIAGNOSES':                              ['S2','S4','S8','S13'],     // icd10_codes → s2(CC), s4(comorbidities), s8(working dx), s13(discharge dx)
  'DRG CODES':                              ['S8'],                     // billing/risk classification → s8(working dx) only; NOT s3(HPI)
  'CLINICAL NOTES':                         ['S2','S3','S9','S12'],     // CC blocks→s2, HPI blocks→s3, progress notes→s9, discharge advice→s12
  'PROCEDURES PERFORMED':                   ['S7','S10'],               // cath_lab.*→s7(imaging), procedures.*+cath_lab.intervention→s10
  'ICU PROCEDURE EVENTS':                   ['S9','S10'],               // ICU procedures → hospital course(s9) + procedures(s10)
  'ICU DATETIME EVENTS':                    ['S9'],
  'ICU STAYS':                              ['S9'],
  'TRANSFERS / WARD MOVEMENT':              ['S9'],
  'CLINICAL SERVICES':                      ['S9','S12'],               // consultations → hospital course(s9) + discharge advice(s12)
  'VITAL SIGNS':                            ['S3','S5','S9','S14'],     // vital_signs_trend→s3,s5,s9; vitals_on_admission→s5; discharge_vitals→s14
  'LAB RESULTS':                            ['S6','S7'],                // all_labs+ecg→s6; ecg_findings+imaging→s7
  'MICROBIOLOGY CULTURES':                  ['S6'],
  'MEDICATIONS / PRESCRIPTIONS':            ['S11'],
  'eMAR (MEDICATION ADMINISTRATION RECORD)':['S9','S11'],
  'ICU FLUIDS I/O':                         ['S9'],
  'ICU NUTRITION / INGREDIENT EVENTS':      ['S9'],
  'PHARMACY DISPENSING':                    ['S11'],
  'PHYSICIAN ORDERS (POE)':                 ['S7','S9'],
  'UPLOADED FILES':                         ['S1','S6','S9','S10','S11'],
  'OUTPATIENT MEASUREMENTS (OMR)':          ['S5','S6','S14'],          // omr_measurements → s5(exam), s6(labs), s14(discharge)
  'HCPCS BILLED ITEMS':                     ['S10'],
};

// Source panel tabs — mirror upload.html tab names so the doctor sees the same structure
const _RV2_CTX_TABS = [
  { key:'Admissions',       label:'Admissions',       blocks:['PATIENT & ADMISSION'] },
  { key:'Diagnoses',        label:'Diagnoses',         blocks:['DIAGNOSES','DRG CODES'] },
  { key:'Procedures',       label:'Procedures',        blocks:['PROCEDURES PERFORMED','HCPCS BILLED ITEMS'] },
  { key:'Vitals',           label:'Vitals',            blocks:['VITAL SIGNS'] },
  { key:'Labs',             label:'Labs',              blocks:['LAB RESULTS','OUTPATIENT MEASUREMENTS (OMR)'] },
  { key:'Medications',      label:'Medications',       blocks:['MEDICATIONS / PRESCRIPTIONS','eMAR (MEDICATION ADMINISTRATION RECORD)'] },
  { key:'Pharmacy',         label:'Pharmacy',          blocks:['PHARMACY DISPENSING'] },
  { key:'Microbiology',     label:'Microbiology',      blocks:['MICROBIOLOGY CULTURES'] },
  { key:'ICU Events',       label:'ICU Events',        blocks:['ICU PROCEDURE EVENTS','ICU DATETIME EVENTS'] },
  { key:'Fluids I/O',       label:'Fluids I/O',        blocks:['ICU FLUIDS I/O','ICU NUTRITION / INGREDIENT EVENTS'] },
  { key:'Transfers',        label:'Transfers',         blocks:['TRANSFERS / WARD MOVEMENT'] },
  { key:'ICU Stays',        label:'ICU Stays',         blocks:['ICU STAYS'] },
  { key:'Physician Orders', label:'Physician Orders',  blocks:['PHYSICIAN ORDERS (POE)'] },
  { key:'Uploaded Files',   label:'Uploaded Files',    blocks:['UPLOADED FILES'] },
  { key:'Notes',            label:'Notes',             blocks:['CLINICAL NOTES','CLINICAL SERVICES'] },
];

// Returns tab keys that contain source blocks relevant to a given NABH section id (e.g. 's6')
function _rv2TabsForSection(nabhId) {
  const nabh = nabhId ? nabhId.toUpperCase() : null;
  if (!nabh) return [];
  return _RV2_CTX_TABS
    .filter(t => t.blocks.some(b => (_rv2BlockToNabh[b] || []).includes(nabh)))
    .map(t => t.key);
}

// Explicit primary tab override for sections where the most clinically relevant tab
// isn't the first returned by _rv2TabsForSection due to array ordering
const _rv2SectionPrimaryTab = {
  // S3 and S9 intentionally omitted — default to Vitals (first relevant tab in order)
  // so the doctor sees real chartevents data rather than the clinical-context Notes block
  // which can be empty/unavailable for some encounters.
};

// Lazy-fetched tabs → data server endpoint key (mirrors upload.html LAZY constant)
const _RV2_LAZY_TAB_MAP = {
  'Labs':'labevents', 'Vitals':'chartevents', 'Medications':'prescriptions',
  'Pharmacy':'pharmacy', 'Fluids I/O':'fluids', 'ICU Events':'procedureevents',
  'Physician Orders':'poe',
};
const _RV2_DISPLAY_TABS = new Set(['Admissions','Diagnoses','Procedures','Microbiology','Transfers','ICU Stays']);

// Inject CSS classes that mirror upload.html's .tbl / .pill / .mono / .muted once per page load
function rv2InjectTabStyles() {
  if (document.getElementById('rv2-src-tab-styles')) return;
  const s = document.createElement('style');
  s.id = 'rv2-src-tab-styles';
  s.textContent = `.rv2t{width:100%;border-collapse:collapse;font-size:12.5px}.rv2t th{text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#6b7280;padding:7px 10px;border-bottom:1px solid #e5e7eb;white-space:nowrap;background:#f9fafb}.rv2t td{padding:7px 10px;border-bottom:1px solid #f3f4f6;vertical-align:middle;color:#111827}.rv2t tr:last-child td{border-bottom:none}.rv2t tr:hover td{background:#f9fafb}.rv2p{display:inline-flex;align-items:center;font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:10px;white-space:nowrap}.rv2p-blue{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe}.rv2p-slate{background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0}.rv2p-green{background:#ecfdf5;color:#059669;border:1px solid #a7f3d0}.rv2p-red{background:#fef2f2;color:#dc2626;border:1px solid #fecaca}.rv2p-amber{background:#fffbeb;color:#d97706;border:1px solid #fde68a}.rv2p-teal{background:#f0fdfa;color:#0d9488;border:1px solid #99f6e4}.rv2mn{font-family:'SF Mono','Menlo','Consolas',monospace}.rv2mu{color:#6b7280}.rv2b{font-weight:600}`;
  document.head.appendChild(s);
}

// Fetch data for a source panel tab (mirrors upload.html's lazyLoad + display fetch)
async function rv2FetchTabData(tab) {
  if (_rv2.srcTabLoading[tab] || _rv2.srcTabData[tab] !== undefined) return;
  const DATA  = window.FOQAL_DATA_BASE || '';
  const API   = window.FOQAL_API_BASE  || '';
  const hid   = APP?.reviewData?.hadmId || APP?.reviewData?.encounter?.hadm_id;
  if (!hid) return;
  _rv2.srcTabLoading[tab] = true; rv2Rerender();
  try {
    if (_RV2_LAZY_TAB_MAP[tab]) {
      const key  = _RV2_LAZY_TAB_MAP[tab];
      const data = await fetch(`${DATA}/api/patient/${hid}/tab/${key}`).then(r => r.ok ? r.json() : {});
      if (key==='prescriptions') {
        const rawMeds = (data.prescriptions||[]).map(m=>({...m,drug:m.drug||m.formulary_drug_cd||'—',dosage:m.dose_val_rx?`${m.dose_val_rx} ${m.dose_unit_rx||''}`.trim():null}));
        if (typeof localizeMeds === 'function' && rawMeds.length) {
          const names = rawMeds.map(m => m.drug);
          const map   = await localizeMeds(names).catch(() => ({}));
          rawMeds.forEach(m => { m._drugIn = map[m.drug] || m.drug; });
        }
        _rv2.srcTabData[tab] = rawMeds;
      }
      else if (key==='pharmacy') {
        const rawPharm = data.pharmacy||[];
        if (typeof localizeMeds === 'function' && rawPharm.length) {
          const names = rawPharm.map(p => p.medication||p.formulary_drug_cd||'—');
          const map   = await localizeMeds(names).catch(() => ({}));
          rawPharm.forEach(p => { const n=p.medication||p.formulary_drug_cd||'—'; p._drugIn = map[n] || n; });
        }
        _rv2.srcTabData[tab] = rawPharm;
      }
      else if (key==='poe')           _rv2.srcTabData[tab] = data.poe||[];
      else if (key==='fluids')        _rv2.srcTabData[tab] = {input:data.fluids||data.inputevents||[],output:data.outputevents||[]};
      else if (key==='labevents')     _rv2.srcTabData[tab] = data.labevents||[];
      else if (key==='chartevents')   _rv2.srcTabData[tab] = data.chartevents||[];
      else if (key==='procedureevents') _rv2.srcTabData[tab] = data.procedureevents||[];
    } else if (_RV2_DISPLAY_TABS.has(tab)) {
      if (!_rv2.srcDisplayData && !_rv2.srcDispLoading) {
        _rv2.srcDispLoading = true;
        const d = await fetch(`${DATA}/api/patient/${hid}/display`).then(r => r.ok ? r.json() : {});
        _rv2.srcDisplayData = d;
        _rv2.srcDispLoading = false;
        for (const t of _RV2_DISPLAY_TABS) _rv2.srcTabData[t] = d;
      } else if (_rv2.srcDisplayData) {
        _rv2.srcTabData[tab] = _rv2.srcDisplayData;
      }
    } else if (tab === 'Uploaded Files') {
      const encId = APP?.reviewData?.encounter?.id;
      if (!encId) { _rv2.srcTabData[tab] = []; }
      else {
        const d = await fetch(`${API}/api/encounters/${encId}/files`).then(r => r.ok ? r.json() : {});
        _rv2.srcTabData[tab] = d.files||[];
      }
    } else {
      _rv2.srcTabData[tab] = null; // Notes: rendered from clinicalCtx
    }
  } catch(e) { _rv2.srcTabError[tab] = e.message||'Failed'; _rv2.srcTabData[tab] = null; }
  _rv2.srcTabLoading[tab] = false; rv2Rerender();
}

const _rv2Spinner = (msg) => `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:340px;height:100%;gap:20px;padding:40px 24px;text-align:center"><div style="width:52px;height:52px;border:5px solid #ede9f5;border-top-color:#800080;border-radius:50%;animation:spin 0.85s linear infinite;flex-shrink:0"></div><div><div style="font-size:16px;font-weight:700;color:#374151;margin-bottom:6px">${msg}</div><div style="font-size:12.5px;color:#9ca3af;line-height:1.6">Fetching clinical data from BigQuery…<br>This may take a few seconds.</div></div></div>`;

// Render tab content — mirrors upload.html _tabBody exactly, using rv2t- CSS classes
function rv2SrcTabBody(tab) {
  rv2InjectTabStyles();
  // Show spinner if loading or not yet fetched (init / click handlers trigger the actual fetch)
  if (_rv2.srcTabLoading[tab] || _rv2.srcTabData[tab] === undefined) return _rv2Spinner(_rv2.srcDisplayData ? `Loading ${tab}…` : 'Loading Sources…');
  if (_rv2.srcTabError[tab]) return `<div style="padding:20px;color:#dc2626;font-size:12px">${_rv2.srcTabError[tab]}</div>`;
  const d    = _rv2.srcDisplayData || {};
  const none = `<div style="padding:20px;color:#6b7280;font-size:12px">No data on record.</div>`;

  if (tab==='Admissions') {
    const a = d.admission || {};
    const fmtDT = dt => { if (!dt) return null; try { return new Date(dt).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'})+', '+new Date(dt).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}); } catch{ return String(dt).slice(0,16).replace('T',' '); } };
    const fld = k => `<td style="width:200px;font-size:11px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.3px;padding:10px 14px">${k}</td>`;
    const val = v => `<td style="font-size:13px;padding:10px 14px">${v}</td>`;
    return `<table class="rv2t" style="border-radius:0"><tbody>
      ${[['Admission Type',`<span class="rv2p ${(a.admission_type==='EMERGENCY'||a.admission_type==='URGENT')?'rv2p-red':'rv2p-amber'}">${a.admission_type||'URGENT'}</span>`],['Admission Date / Time',fmtDT(a.admittime||a.admit_time)||'Not recorded'],['Insurance / TPA',a.insurance||'—'],['Admit Diagnosis',`<span class="rv2b">${(d.diagnoses&&d.diagnoses[0]&&d.diagnoses[0].long_title)||a.diagnosis||'—'}</span>`]].map(([k,v])=>`<tr>${fld(k)}${val(v)}</tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Diagnoses') {
    const dx = d.diagnoses||[];
    if (!dx.length) return none;
    const sb = i => i===0?`<span class="rv2p rv2p-blue" style="font-size:10px">Primary</span>`:i<=2?`<span class="rv2p rv2p-amber" style="font-size:10px">Secondary</span>`:`<span class="rv2p rv2p-slate" style="font-size:10px">Comorbidity</span>`;
    return `<table class="rv2t"><thead><tr><th>ICD-10</th><th>Description</th><th>Type</th></tr></thead><tbody>
      ${dx.map((r,i)=>`<tr${i===0?' style="background:#eff6ff"':''}><td><span class="rv2mn" style="color:${i===0?'#1d4ed8':'#374151'};font-weight:700">${r.icd_code}</span></td><td${i===0?' style="font-weight:600"':''}>${r.long_title||'—'}</td><td>${sb(i)}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Procedures') {
    const pr = d.procedures||[];
    if (!pr.length) return none;
    return `<table class="rv2t"><thead><tr><th>ICD Code</th><th>Procedure</th><th>Version</th><th>Date</th></tr></thead><tbody>
      ${pr.map(p=>`<tr><td><span class="rv2mn" style="color:#0d9488;font-weight:600">${p.icd_code}</span></td><td>${p.long_title||'—'}</td><td><span class="rv2p rv2p-slate">ICD-${p.icd_version}</span></td><td class="rv2mu">${p.chartdate||'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Labs') {
    const rows = _rv2.srcTabData[tab]||[];
    const flag = l => { if(l.flag==='critical')return`<span class="rv2p rv2p-red" style="font-size:10px">↑↑ Critical</span>`;if(l.flag==='high')return`<span class="rv2p rv2p-amber" style="font-size:10px">↑ High</span>`;if(l.flag==='low')return`<span class="rv2p rv2p-amber" style="font-size:10px">↓ Low</span>`;const v=parseFloat(l.valuenum??l.value),hi=parseFloat(l.ref_range_upper),lo=parseFloat(l.ref_range_lower);if(!isNaN(v)&&!isNaN(hi)&&v>hi*3)return`<span class="rv2p rv2p-red" style="font-size:10px">↑↑ Critical</span>`;if(!isNaN(v)&&!isNaN(hi)&&v>hi)return`<span class="rv2p rv2p-amber" style="font-size:10px">↑ High</span>`;if(!isNaN(v)&&!isNaN(lo)&&v<lo)return`<span class="rv2p rv2p-amber" style="font-size:10px">↓ Low</span>`;if(l.flag&&l.flag!=='normal')return`<span class="rv2p rv2p-amber" style="font-size:10px">↑ Abnormal</span>`;return`<span class="rv2p rv2p-green" style="font-size:10px">✓ Normal</span>`; };
    const ref  = l => { if(l.ref_range_lower!=null&&l.ref_range_upper!=null)return`${l.ref_range_lower}–${l.ref_range_upper}`;if(l.ref_range_upper!=null)return`< ${l.ref_range_upper}`;if(l.ref_range_lower!=null)return`> ${l.ref_range_lower}`;return'—'; };
    if (!rows.length) return none;
    return `<table class="rv2t"><thead><tr><th>Test</th><th>Value</th><th>Reference</th><th>Flag</th><th>Date</th></tr></thead><tbody>
      ${rows.slice(0,500).map(l=>`<tr><td class="rv2b">${l.label||l.itemid||'—'}</td><td><span class="rv2mn" style="font-weight:600">${l.valuenum??l.value??'—'}</span> <span class="rv2mu" style="font-size:11px">${l.valueuom||''}</span></td><td class="rv2mu">${ref(l)}</td><td>${flag(l)}</td><td class="rv2mu">${(l.charttime||'').replace('T',' ').slice(0,10)||'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Vitals') {
    const evts = _rv2.srcTabData[tab]||[];
    if (!evts.length) return none;
    const lm = (lbl,...t) => t.some(s=>lbl.toLowerCase().includes(s));
    const news2 = (s2,hr,bpS,rr,tp) => { let s=0;if(s2!=null)s+=s2<=91?3:s2<=93?2:s2<=95?1:0;if(hr!=null)s+=hr<=40?3:hr<=50?1:hr<=90?0:hr<=110?1:hr<=130?2:3;if(bpS!=null)s+=bpS<=90?3:bpS<=100?2:bpS<=110?1:bpS<=219?0:3;if(rr!=null)s+=rr<=8?3:rr<=11?1:rr<=20?0:rr<=24?1:3;if(tp!=null)s+=tp<=35?3:tp<=36?1:tp<=38?0:tp<=39?1:2;return s; };
    const n2b = sc => `<span class="rv2p ${sc>=7?'rv2p-red':sc>=5?'rv2p-amber':'rv2p-green'}" style="font-size:10px;font-weight:700">${sc}</span>`;
    const byH={},hOrd=[];
    for(const e of evts){const hk=(e.charttime||'').slice(0,13);if(!hk)continue;if(!byH[hk]){byH[hk]=[];hOrd.push(hk);}byH[hk].push(e);}
    const rows=[...new Set(hOrd)].slice(0,60).map(hk=>{
      const ev=byH[hk];let s2=null,hr=null,bpS=null,bpD=null,rr=null,tp=null;
      for(const e of ev){const lb=(e.label||'').toLowerCase(),v=parseFloat(e.valuenum??e.value);if(isNaN(v))continue;if(lm(lb,'spo2','o2 sat','peripheral o2'))s2=v;else if(lm(lb,'heart rate'))hr=v;else if(lm(lb,'blood pressure s','arterial bp s','non invasive blood pressure s'))bpS=v;else if(lm(lb,'blood pressure d','arterial bp d','non invasive blood pressure d'))bpD=v;else if(lm(lb,'respiratory rate'))rr=v;else if(lm(lb,'temperature'))tp=(e.valueuom||'').toLowerCase().includes('f')&&v>50?Math.round((v-32)*5/9*10)/10:v;}
      const sc=news2(s2,hr,bpS,rr,tp),dt=hk.replace('T',' ')+':00';
      return `<tr><td class="rv2mu" style="font-size:11px;white-space:nowrap">${dt}</td><td class="rv2mn">${s2!=null?s2+'%':'—'}</td><td class="rv2mn">${hr??'—'}</td><td class="rv2mn">${bpS!=null?(bpD!=null?bpS+' / '+bpD:bpS):'—'}</td><td class="rv2mn">${rr??'—'}</td><td class="rv2mn">${tp??'—'}</td><td>${n2b(sc)}</td></tr>`;
    });
    return `<table class="rv2t"><thead><tr><th>Date / Time</th><th>SpO₂ (%)</th><th>HR (bpm)</th><th>BP (mmHg)</th><th>RR (/min)</th><th>Temp (°C)</th><th>NEWS2</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }
  if (tab==='Medications') {
    const meds = _rv2.srcTabData[tab]||[];
    if (!meds.length) return none;
    return `<table class="rv2t"><thead><tr><th>Drug (Indian Brand)</th><th>Dose</th><th>Route</th><th>Freq</th></tr></thead><tbody>
      ${meds.map(m=>{const raw=m.drug||m.formulary_drug_cd||'—';const ind=m._drugIn||raw;return`<tr><td class="rv2b">${ind}</td><td class="rv2mn">${m.dosage||(m.dose_val_rx?(m.dose_val_rx+' '+(m.dose_unit_rx||'')).trim():'—')}</td><td><span class="rv2p rv2p-slate" style="font-size:10px">${m.route||'—'}</span></td><td class="rv2mu">${m.frequency||(m.doses_per_24_hrs?m.doses_per_24_hrs+'×/day':'—')}</td></tr>`;}).join('')}
    </tbody></table>`;
  }
  if (tab==='Pharmacy') {
    const ph = _rv2.srcTabData[tab]||[];
    if (!ph.length) return none;
    return `<table class="rv2t"><thead><tr><th>Drug (Indian Brand)</th><th>Frequency</th><th>Doses/24h</th><th>Status</th><th>Start</th></tr></thead><tbody>
      ${ph.map(p=>{const raw=p.medication||p.formulary_drug_cd||'—';const ind=p._drugIn||raw;return`<tr><td class="rv2b">${ind}</td><td class="rv2mu">${p.frequency||'—'}</td><td class="rv2mn">${p.doses_per_24_hrs??'—'}</td><td><span class="rv2p rv2p-slate" style="font-size:10px">${p.status||'—'}</span></td><td class="rv2mu">${(p.starttime||'').replace('T',' ').slice(0,16)||'—'}</td></tr>`;}).join('')}
    </tbody></table>`;
  }
  if (tab==='Microbiology') {
    const mc = d.microbiologyevents||d.microbiology||[];
    if (!mc.length) return none;
    return `<table class="rv2t"><thead><tr><th>Specimen</th><th>Organism</th><th>Antibiotic</th><th>Interp.</th><th>Time</th></tr></thead><tbody>
      ${mc.map(m=>`<tr><td class="rv2b">${m.spec_type_desc||'—'}</td><td style="color:#dc2626">${m.org_name||'—'}</td><td>${m.ab_name||'—'}</td><td><span class="rv2p ${m.interpretation==='S'?'rv2p-green':'rv2p-red'}">${m.interpretation||'—'}</span></td><td class="rv2mu">${(m.charttime||'').replace('T',' ').slice(0,16)||'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='ICU Events') {
    const ev = _rv2.srcTabData[tab]||[];
    if (!ev.length) return none;
    return `<table class="rv2t"><thead><tr><th>Event</th><th>Value</th><th>Status</th><th>Start</th><th>End</th></tr></thead><tbody>
      ${ev.map(e=>`<tr><td class="rv2b">${e.label||e.ordercategoryname||'—'}</td><td class="rv2mn">${e.value!=null?e.value:e.valuenum!=null?e.valuenum:'—'} ${e.valueuom||''}</td><td><span class="rv2p rv2p-blue" style="font-size:10px">${e.statusdescription||'—'}</span></td><td class="rv2mu">${(e.starttime||'').replace('T',' ').slice(0,16)||'—'}</td><td class="rv2mu">${(e.endtime||'').replace('T',' ').slice(0,16)||'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Fluids I/O') {
    const {input=[],output=[]} = _rv2.srcTabData[tab]||{};
    const netSty = n => n<0?'color:#059669;font-weight:700':n>2000?'color:#dc2626;font-weight:700':n>1000?'color:#d97706;font-weight:700':'';
    const hdrs = `<thead><tr><th>Date</th><th>IV Intake (mL)</th><th>Oral Intake (mL)</th><th>Urine Output (mL)</th><th>Net Balance (mL)</th></tr></thead>`;
    if (!input.length&&!output.length) return none;
    const byD={},dOrd=[];
    for(const e of input){const dd=(e.starttime||e.charttime||'').slice(0,10);if(!dd)continue;if(!byD[dd]){byD[dd]={iv:0,ur:0};dOrd.push(dd);}const a=parseFloat(e.amount??e.totalamount??0);if(!isNaN(a)&&(e.amountuom||'').toLowerCase().includes('ml'))byD[dd].iv+=a;}
    for(const e of output){const dd=(e.charttime||'').slice(0,10);if(!dd)continue;if(!byD[dd]){byD[dd]={iv:0,ur:0};dOrd.push(dd);}const v=parseFloat(e.value??0);if(!isNaN(v)&&(e.label||'').toLowerCase().includes('urine'))byD[dd].ur+=v;}
    const dates=[...new Set(dOrd)].sort();let cIV=0,cUr=0;
    const dRows=dates.map(dd=>{const r=byD[dd];const net=Math.round(r.iv-r.ur);cIV+=r.iv;cUr+=r.ur;return`<tr><td class="rv2b">${dd}</td><td class="rv2mn">${Math.round(r.iv).toLocaleString()}</td><td class="rv2mu">—</td><td class="rv2mn">${Math.round(r.ur).toLocaleString()}</td><td class="rv2mn" style="${netSty(net)}">${net>=0?'+':''}${net.toLocaleString()}</td></tr>`;});
    const cNet=Math.round(cIV-cUr);
    return `<table class="rv2t">${hdrs}<tbody>${dRows.join('')}<tr style="background:#f9fafb;font-weight:700"><td>Cumulative</td><td class="rv2mn">${Math.round(cIV).toLocaleString()}</td><td class="rv2mu">—</td><td class="rv2mn">${Math.round(cUr).toLocaleString()}</td><td class="rv2mn" style="${netSty(cNet)}">${cNet>=0?'+':''}${cNet.toLocaleString()}</td></tr></tbody></table>`;
  }
  if (tab==='Transfers') {
    const tr = d.transfers||[];
    if (!tr.length) return none;
    return `<table class="rv2t"><thead><tr><th>Event</th><th>Care Unit</th><th>In</th><th>Out</th></tr></thead><tbody>
      ${tr.map(t=>`<tr><td><span class="rv2p rv2p-slate">${t.eventtype||'—'}</span></td><td class="rv2b">${t.careunit||'—'}</td><td class="rv2mu">${(t.intime||'').replace('T',' ').slice(0,16)||'—'}</td><td class="rv2mu">${(t.outtime||'').replace('T',' ').slice(0,16)||'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='ICU Stays') {
    const is = d.icustays||d.icu_stays||[];
    if (!is.length) return none;
    return `<table class="rv2t"><thead><tr><th>Stay ID</th><th>First Unit</th><th>Last Unit</th><th>In</th><th>Out</th><th>LOS</th></tr></thead><tbody>
      ${is.map(s=>`<tr><td class="rv2mn">${s.stay_id}</td><td>${s.first_careunit||'—'}</td><td>${s.last_careunit||'—'}</td><td class="rv2mu">${(s.intime||'').replace('T',' ').slice(0,16)||'—'}</td><td class="rv2mu">${(s.outtime||'').replace('T',' ').slice(0,16)||'—'}</td><td class="rv2mn">${s.los!=null?Number(s.los).toFixed(2):'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Physician Orders') {
    const po = _rv2.srcTabData[tab]||[];
    if (!po.length) return none;
    return `<table class="rv2t"><thead><tr><th>Type</th><th>Subtype</th><th>Status</th><th>Time</th></tr></thead><tbody>
      ${po.slice(0,200).map(p=>`<tr><td class="rv2b">${p.order_type||'—'}</td><td class="rv2mu">${p.order_subtype||'—'}</td><td><span class="rv2p rv2p-slate" style="font-size:10px">${p.order_status||'—'}</span></td><td class="rv2mu">${(p.ordertime||'').replace('T',' ').slice(0,16)||'—'}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Uploaded Files') {
    const files = _rv2.srcTabData[tab]||[];
    if (!files.length) return `<div style="padding:20px;color:#6b7280;font-size:12px">No files uploaded yet.</div>`;
    return `<table class="rv2t"><thead><tr><th>File</th><th>Type</th><th>Date</th></tr></thead><tbody>
      ${files.map(f=>`<tr><td class="rv2mn" style="font-size:12px">${f.file_name||f.name||'—'}</td><td><span class="rv2p rv2p-slate" style="font-size:10px">${f.file_type||'—'}</span></td><td class="rv2mu">${(f.upload_date||f.created_at||'—').slice(0,10)}</td></tr>`).join('')}
    </tbody></table>`;
  }
  if (tab==='Notes') {
    // Render CLINICAL NOTES + CLINICAL SERVICES blocks from clinicalCtx
    if (!_rv2.clinicalCtx) return none;
    const blocks = rv2ParseCtxBlocks(_rv2.clinicalCtx).filter(b => ['CLINICAL NOTES','CLINICAL SERVICES'].includes(b.header));
    if (!blocks.length) return none;
    return blocks.map(b=>`<div style="margin-bottom:12px"><div style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.07em;padding:4px 0 6px">${b.header}</div><pre style="font-size:11.5px;line-height:1.75;color:#111827;white-space:pre-wrap;word-break:break-word;margin:0">${b.lines.join('\n').trim().replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre></div>`).join('');
  }
  return none;
}

// NABH section badge colours (same palette used in summary panel)
const _rv2NabhColors = {
  S1:'#1A56DB', S2:'#0891B2', S3:'#0891B2', S4:'#7C3AED',
  S5:'#059669', S6:'#D97706', S7:'#DC2626', S8:'#0891B2',
  S9:'#6366F1', S10:'#DC2626', S11:'#059669', S12:'#7C3AED',
  S13:'#1A56DB', S14:'#D97706', S15:'#374151',
};

// Parse clinical context text into typed blocks [{header, content}]
function rv2ParseCtxBlocks(text) {
  const lines = text.split('\n');
  const blocks = [];
  let cur = null;
  for (const line of lines) {
    const m = line.match(/^\[([^\]]+)\]/);
    if (m) {
      if (cur) blocks.push(cur);
      cur = { header: m[1].trim(), lines: [] };
    } else if (cur) {
      cur.lines.push(line);
    }
  }
  if (cur) blocks.push(cur);
  return blocks;
}

function rv2BuildSourceContent(clinicalCtx, activeSectionId, activeCtxTab) {
  if (!clinicalCtx) {
    if (!activeSectionId) {
      return `
        <div style="text-align:center;padding:48px 20px;color:var(--ink-4);line-height:1.8">
          <div style="width:36px;height:36px;border-radius:6px;background:#E8F0FE;display:grid;place-items:center;margin:0 auto 12px">${iconSVG("doc",16)}</div>
          <div style="font-size:13px;font-weight:600;color:var(--ink-3)">Click any NABH section</div>
          <div style="font-size:12px;margin-top:4px">The corresponding source blocks<br/>will highlight here.</div>
        </div>`;
    }
    return `
      <div style="text-align:center;padding:36px 20px;color:var(--ink-4);line-height:1.7">
        <div style="width:32px;height:32px;border-radius:6px;background:#F3F4F6;display:grid;place-items:center;margin:0 auto 12px">${iconSVG("doc",16)}</div>
        <div style="font-size:13px;font-weight:500;color:var(--ink-3)">No source context available</div>
        <div style="font-size:11.5px;margin-top:4px">Context loads when a summary is<br/>generated from the backend.</div>
      </div>`;
  }

  const blocks = rv2ParseCtxBlocks(clinicalCtx);
  if (!blocks.length) {
    return `<pre style="font-family:var(--mono);font-size:11px;line-height:1.7;color:#1E293B;white-space:pre-wrap;word-break:break-word;margin:0">${clinicalCtx.replace(/</g,"&lt;").replace(/>/g,"&gt;")}</pre>`;
  }

  // Filter to only the active tab's blocks (all shown when no tab selected)
  const _activeTabDef = _RV2_CTX_TABS.find(t => t.key === activeCtxTab);
  const visibleBlocks = _activeTabDef
    ? blocks.filter(b => _activeTabDef.blocks.includes(b.header))
    : blocks;

  // Which NABH section is active (e.g. "s6" → "S6")
  const activeNabh = activeSectionId ? activeSectionId.toUpperCase() : null;

  // Find the first highlighted block so we can auto-scroll to it
  let firstActiveId = null;

  const html = visibleBlocks.map((block, idx) => {
    const nabhs  = _rv2BlockToNabh[block.header] || [];
    const isActive = activeNabh && nabhs.includes(activeNabh);
    const isDimmed = activeNabh && !isActive;
    const content  = block.lines.join('\n').trim();
    const safeContent = content.replace(/</g,"&lt;").replace(/>/g,"&gt;");

    // NABH badges for this block
    const badges = nabhs.map(s => {
      const col = _rv2NabhColors[s] || '#374151';
      const isHighlighted = s === activeNabh;
      return `<span style="font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:99px;background:${isHighlighted?col:'#F1F5F9'};color:${isHighlighted?'#fff':col};border:1px solid ${isHighlighted?col:'#E2E8F0'};letter-spacing:.03em">${s}</span>`;
    }).join(' ');

    const blockId = isActive && !firstActiveId ? (firstActiveId = `rv2-src-active-${idx}`, firstActiveId) : `rv2-src-block-${idx}`;
    const borderLeft = isActive ? '3px solid #800080' : '3px solid #E8DEE8';
    const bg         = isActive ? '#FDF8FF' : '#fff';
    const headerColor = isActive ? '#800080' : '#374151';

    return `
      <div id="${blockId}" style="border:1px solid ${isActive?'#D4A0D4':'#E8DEE8'};border-left:${borderLeft};border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:8px;background:${bg};scroll-margin-top:12px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap">
          <span style="font-size:10px;font-weight:700;color:${headerColor};text-transform:uppercase;letter-spacing:.07em">${block.header}</span>
          ${badges}
          ${isActive && activeNabh ? `<span style="margin-left:auto;font-size:9px;color:#800080;font-weight:700;text-transform:uppercase;letter-spacing:.06em;background:#F5E6F5;border:1px solid #D4A0D4;border-radius:12px;padding:1px 7px">Source · ${activeNabh}</span>` : ''}
        </div>
        <pre style="font-family:var(--mono);font-size:11.5px;line-height:1.75;color:${isActive?'#1A001A':'#4B5563'};white-space:pre-wrap;word-break:break-word;margin:0">${safeContent||'<span style="color:#9CA3AF;font-style:italic">No data</span>'}</pre>
      </div>`;
  }).join('');

  // Auto-scroll to first highlighted block after render
  if (firstActiveId) {
    setTimeout(() => {
      const el = document.getElementById(firstActiveId);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
  }

  return html;
}

// ── Section body formatters ───────────────────────────────────────────────────

function rv2FormatLabResults(rawText) {
  // Normalize dash-separated lab format before parsing.
  // AI sometimes generates "- Test: val- Test2: val" (hyphen separators) or
  // "val\nMicrobiology:" (no gap) instead of the semicolon format parsers expect.
  let text = rawText
    .replace(/^\s*-\s*/, '')                // strip leading "- " bullet
    .replace(/\s*-\s+(?=[A-Z])/g, '; ')    // "- CapLetter" separator → "; "
    .replace(/(\d)([A-Z][a-z])/g, '$1; $2') // "1.9Microbiology" → "1.9; Microbiology"
    .replace(/\n\s*-\s*/g, '; ');           // newline-bullet "- item" → "; item"

  // Parse groups from either format:
  // Format A (with asterisks): *CBC*: item; item. *Renal*: item
  // Format B (plain):          CBC: item; item. Renal/Electrolytes: item
  let groups = [];

  // Try Format A first
  const partsA = text.split(/\*([^*]+)\*:\s*/);
  if (partsA.length >= 3) {
    for (let i = 1; i < partsA.length; i += 2) {
      groups.push({ name: partsA[i].trim(), raw: (partsA[i+1]||'').replace(/\.\s*$/, '') });
    }
  } else {
    // Format B: split on "CategoryName:" at start or after a period
    // Category names are Title Case words, may include / & spaces
    const partsB = text.split(/(?:^|\.\s*)([A-Z][A-Za-z\/&,() -]{1,40}):\s*/);
    if (partsB.length >= 3) {
      for (let i = 1; i < partsB.length; i += 2) {
        const raw = (partsB[i+1]||'').replace(/\.\s*$/, '').trim();
        if (raw) groups.push({ name: partsB[i].trim(), raw });
      }
    }
  }

  // Format C — flat "Group: Test: val Test: val Group2: Test: val" (no semicolons/asterisks)
  // Also runs when Format B found groups but their raw values look like unsplit sub-items
  // (contains ":" without ";", meaning B only caught the first category and dumped the rest as one blob)
  const needsFormatC = !groups.length || (groups.length <= 2 && groups.some(g => g.raw.includes(':') && !g.raw.includes(';')));
  if (needsFormatC) {
    groups = []; // reset groups so Format C can build them fresh
    const extracted = [];
    const kvRe = /([A-Z][A-Za-z0-9\s\/&().\-]{0,35}?):\s*/g;
    let km;
    while ((km = kvRe.exec(text)) !== null) {
      const lbl = km[1].trim();
      if (/^(Not|The|A |An |Is |Are |Was |Were )/i.test(lbl)) continue;
      if (lbl.split(/\s+/).length > 5) continue;
      extracted.push({ label: lbl, pos: km.index, end: km.index + km[0].length });
    }
    if (extracted.length > 2) {
      const groupedC = [];
      let curC = null;
      extracted.forEach((lab, i) => {
        const nextPos = i + 1 < extracted.length ? extracted[i+1].pos : text.length;
        const val = text.slice(lab.end, nextPos).replace(/\s*\([^)]*\)/g, '').replace(/^[;,\-\s]+|[;,\-\s]+$/g, '').trim();
        // empty val = next label follows immediately = group header; any non-empty val = terminal item
        const isTerminal = val !== '';
        if (!isTerminal) {
          curC = { name: lab.label, rows: [] };
          groupedC.push(curC);
        } else {
          if (!curC) { curC = { name: 'Investigations', rows: [] }; groupedC.push(curC); }
          const numVal = val.match(/^([\d<>≤≥~\-.]+(?:\s*[a-zA-Z\/µ%°]+)?)/)?.[1]?.trim() || '';
          const isNotDoc = /not documented/i.test(val) && !numVal;
          const isAbnormal = /\b(elevated|high|low|abnormal|critical|borderline|increased|decreased|positive|raised|deranged|poor|reduced|impaired)\b/i.test(val);
          curC.rows.push({ label: lab.label, value: numVal || (isNotDoc ? '—' : val), missing: isNotDoc, abnormal: isAbnormal && !isNotDoc });
        }
      });
      const validC = groupedC.filter(g => g.rows.length > 0);
      if (validC.length > 0) {
        const pal = ['#3B82F6','#8B5CF6','#10B981','#F59E0B','#EF4444','#EC4899','#14B8A6','#6366F1'];
        const tRows = validC.flatMap((g, gi) => {
          const color = pal[gi % pal.length];
          const abnCount = g.rows.filter(r => r.abnormal).length;
          const docCount = g.rows.filter(r => !r.missing).length;
          const hdr = `<tr><td colspan="3" style="padding:7px 12px;background:${color}12;border-top:2px solid ${color};border-bottom:1px solid ${color}30">
            <div style="display:flex;align-items:center;gap:8px">
              <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;flex-shrink:0"></span>
              <span style="font-size:11px;font-weight:700;color:${color};text-transform:uppercase;letter-spacing:.07em">${g.name.replace(/</g,'&lt;')}</span>
              ${abnCount ? `<span style="margin-left:auto;font-size:10px;background:#FEE2E2;color:#DC2626;border-radius:10px;padding:1px 8px;font-weight:600">${abnCount} abnormal</span>` : docCount ? `<span style="margin-left:auto;font-size:10px;background:#DCFCE7;color:#15803D;border-radius:10px;padding:1px 8px;font-weight:600">${docCount} value${docCount!==1?'s':''}</span>` : `<span style="margin-left:auto;font-size:10px;color:${color}80">${g.rows.length} item${g.rows.length!==1?'s':''}</span>`}
            </div></td></tr>`;
          const rows = g.rows.map((r, idx) => `
            <tr style="background:${idx%2===0?'#FFFFFF':'#F9FAFB'}">
              <td style="padding:7px 12px;font-size:13px;color:#374151;border-bottom:1px solid #F1F5F9;width:50%">${r.label.replace(/</g,'&lt;')}</td>
              <td style="padding:7px 12px;font-size:13px;font-weight:600;color:${r.missing?'#94A3B8':r.abnormal?'#DC2626':'#0F172A'};border-bottom:1px solid #F1F5F9;width:25%">${r.value}</td>
              <td style="padding:7px 12px;border-bottom:1px solid #F1F5F9;width:25%;text-align:center">
                ${r.missing  ? `<span style="font-size:10px;font-weight:700;background:#F1F5F9;color:#64748B;border-radius:4px;padding:2px 8px;letter-spacing:.04em">NOT DOCUMENTED</span>`
                : r.abnormal ? `<span style="font-size:10px;font-weight:700;background:#FEE2E2;color:#DC2626;border-radius:4px;padding:2px 8px;letter-spacing:.04em">ABNORMAL</span>`
                             : `<span style="font-size:10px;font-weight:700;background:#DCFCE7;color:#15803D;border-radius:4px;padding:2px 8px;letter-spacing:.04em">NORMAL</span>`}
              </td>
            </tr>`).join('');
          return hdr + rows;
        });
        return `<table style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;font-family:var(--sans,sans-serif)">
          <thead><tr style="background:#F8FAFC;border-bottom:1.5px solid #E2E8F0">
            <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;text-transform:uppercase;letter-spacing:.07em;width:50%">Investigation</th>
            <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;text-transform:uppercase;letter-spacing:.07em;width:25%">Result</th>
            <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:center;text-transform:uppercase;letter-spacing:.07em;width:25%">Status</th>
          </tr></thead>
          <tbody>${tRows.join('')}</tbody>
        </table>`;
      }
    }
  }

  // Fallback — legacy ungrouped lab text, split on semicolons
  if (!groups.length) {
    const normalized = text.replace(/\.\s+(?=[A-Z])/g, "; ").replace(/\.\s*$/, "").trim();
    const looksLikeLabs = /[A-Za-z].*\d/.test(normalized) && normalized.includes(";");
    if (looksLikeLabs) {
      groups.push({ name: "Investigations", raw: normalized });
    } else {
      const safe = text.replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return `<p style="font-size:13.5px;line-height:1.9;color:#1E293B">${safe}</p>`;
    }
  }

  const palette = ['#3B82F6','#8B5CF6','#10B981','#F59E0B','#EF4444','#EC4899','#14B8A6','#6366F1','#F97316','#64748B'];

  const tableRows = groups.flatMap((g, gi) => {
    const color = palette[gi % palette.length];
    const items = g.raw.split(';').map(s => s.trim()).filter(Boolean);
    const abnCount = items.filter(i => /\(abnormal\)/i.test(i)).length;

    // Group header row
    const headerRow = `
      <tr>
        <td colspan="3" style="padding:7px 12px;background:${color}12;border-top:2px solid ${color};border-bottom:1px solid ${color}30">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;flex-shrink:0"></span>
            <span style="font-size:11px;font-weight:700;color:${color};text-transform:uppercase;letter-spacing:.07em">${g.name.replace(/</g,'&lt;')}</span>
            ${abnCount ? `<span style="margin-left:auto;font-size:10px;background:#FEE2E2;color:#DC2626;border-radius:10px;padding:1px 8px;font-weight:600">${abnCount} abnormal</span>` : `<span style="margin-left:auto;font-size:10px;color:${color}80">${items.length} value${items.length!==1?'s':''}</span>`}
          </div>
        </td>
      </tr>`;

    // Data rows — one test per row
    const dataRows = items.map((item, idx) => {
      const abnormal = /\(abnormal\)/i.test(item);
      const clean = item.replace(/\s*\(abnormal\)\s*/gi,'').trim();
      // Split "Test Name 9.2 g/dL" → label + value
      // Match: everything up to last space-number boundary
      const vm = clean.match(/^(.+?)\s+([\d<>≤≥~][^\s]*)(\s+[^\d].+)?$/);
      const label  = vm ? vm[1].trim() : clean;
      const val    = vm ? vm[2].trim() : '';
      const unit   = vm && vm[3] ? vm[3].trim() : '';
      const rowBg  = abnormal ? '#FFF5F5' : (idx % 2 === 0 ? '#FFFFFF' : '#F9FAFB');
      return `
        <tr style="background:${rowBg}">
          <td style="padding:7px 12px;font-size:13px;color:#374151;border-bottom:1px solid #F1F5F9;width:50%">${label.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</td>
          <td style="padding:7px 12px;font-size:13px;font-weight:600;${abnormal?'color:#DC2626':'color:#0F172A'};border-bottom:1px solid #F1F5F9;width:25%;white-space:nowrap">
            ${val.replace(/</g,'&lt;').replace(/>/g,'&gt;')}${unit ? `<span style="font-size:11px;font-weight:400;color:#94A3B8;margin-left:4px">${unit.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</span>` : ''}
          </td>
          <td style="padding:7px 12px;border-bottom:1px solid #F1F5F9;width:25%;text-align:center">
            ${abnormal
              ? `<span style="font-size:10px;font-weight:700;background:#FEE2E2;color:#DC2626;border-radius:4px;padding:2px 8px;letter-spacing:.04em">ABNORMAL</span>`
              : `<span style="font-size:10px;font-weight:700;background:#DCFCE7;color:#15803D;border-radius:4px;padding:2px 8px;letter-spacing:.04em">NORMAL</span>`}
          </td>
        </tr>`;
    }).join('');

    return [headerRow, dataRows];
  });

  return `
    <table style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;font-family:var(--sans,sans-serif)">
      <thead>
        <tr style="background:#F8FAFC;border-bottom:1.5px solid #E2E8F0">
          <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;text-transform:uppercase;letter-spacing:.07em;width:50%">Investigation</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;text-transform:uppercase;letter-spacing:.07em;width:25%">Result</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:center;text-transform:uppercase;letter-spacing:.07em;width:25%">Status</th>
        </tr>
      </thead>
      <tbody>${tableRows.join('')}</tbody>
    </table>`;
}

function rv2FormatS14(text) {
  // Split on sentences or semicolons to get individual status items
  const safe = t => t.replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const items = text.split(/[.;]/).map(s => s.trim()).filter(Boolean);
  if (items.length <= 1) {
    return `<div style="font-size:14px;line-height:1.9;color:#1E293B">${safe(text)}</div>`;
  }
  const rows = items.map((item, i) => {
    // Try to detect "Label: value" pattern
    const cm = item.match(/^([^:]{1,30}):\s*(.+)$/);
    const label = cm ? cm[1].trim() : (i === 0 ? "Overall Status" : "Detail");
    const value = cm ? cm[2].trim() : item;
    const isGood = /stable|improved|good|normal|well|intact|tolerating|afebrile/i.test(value);
    const isBad  = /critical|poor|deteriorat|worsened|unstable/i.test(value);
    const color  = isBad ? '#DC2626' : isGood ? '#059669' : '#374151';
    const bg     = isBad ? '#FFF5F5' : isGood ? '#F0FDF4' : '#F8FAFC';
    return `<tr style="background:${i%2===0?bg:'white'}">
      <td style="padding:8px 12px;font-size:12.5px;font-weight:600;color:#374151;border-bottom:1px solid #F1F5F9;width:28%">${safe(label)}</td>
      <td style="padding:8px 12px;font-size:13px;color:${color};border-bottom:1px solid #F1F5F9">${safe(value)}</td>
    </tr>`;
  }).join('');
  return `<table style="width:100%;border-collapse:collapse;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden">
    <thead><tr style="background:#F8FAFC;border-bottom:1.5px solid #E2E8F0">
      <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;text-transform:uppercase;letter-spacing:.07em;width:28%">Parameter</th>
      <th style="padding:8px 12px;font-size:11px;font-weight:700;color:#64748B;text-align:left;text-transform:uppercase;letter-spacing:.07em">Status / Findings</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function rv2FormatSectionBody(sectionId, text) {
  if (!text) return '';
  if (sectionId === 's6') return rv2FormatLabResults(text);
  if (sectionId === 's14') return rv2FormatS14(text);
  const safe = text.replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // Medications: render as bullet with pill styling
  if (sectionId === 's11') {
    return `<div style="display:flex;align-items:flex-start;gap:14px;padding:6px 0;border-bottom:1px solid #F8F0F8">
      <span style="width:9px;height:9px;border-radius:50%;background:#800080;flex-shrink:0;margin-top:7px;box-shadow:0 0 0 3px #F5E6F5"></span>
      <span style="font-size:15px;color:#0D000D;line-height:1.85;font-weight:500">${safe}</span>
    </div>`;
  }
  // Procedures: numbered-feel bullet
  if (sectionId === 's10') {
    return `<div style="display:flex;align-items:flex-start;gap:14px;padding:6px 0;border-bottom:1px solid #F8F0F8">
      <span style="width:9px;height:9px;border-radius:50%;background:#5C005C;flex-shrink:0;margin-top:7px;box-shadow:0 0 0 3px #F0E6F0"></span>
      <span style="font-size:15px;color:#0D000D;line-height:1.85;font-weight:400">${safe}</span>
    </div>`;
  }
  // Diagnoses: split by semicolons into numbered rows
  if (sectionId === 's13') {
    const items = text.split(/;\s*/g).map(s => s.trim()).filter(Boolean);
    if (items.length > 1) {
      let rowNum = 0;
      return items.map(item => {
        const isPrimary = /^primary\s*:/i.test(item);
        const clean = item.replace(/^primary\s*:\s*/i, '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        rowNum++;
        return `<div style="display:flex;align-items:flex-start;gap:10px;padding:6px 0;border-bottom:1px solid #F0FAF6">
          <span style="min-width:22px;height:22px;border-radius:50%;background:${isPrimary?'#0D9E6E':'#E6F7F2'};color:${isPrimary?'white':'#0D9E6E'};display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0;margin-top:2px">${rowNum}</span>
          ${isPrimary ? `<span style="font-size:10px;font-weight:700;color:#0D9E6E;background:#E6F7F2;border:1px solid #A7F3D0;border-radius:4px;padding:1px 7px;flex-shrink:0;margin-top:4px;white-space:nowrap">PRIMARY</span>` : ''}
          <span style="font-size:14px;color:#0D000D;line-height:1.8">${clean}</span>
        </div>`;
      }).join('');
    }
    return `<div style="display:flex;align-items:flex-start;gap:14px;padding:6px 0;border-bottom:1px solid #F0FAF6">
      <span style="width:9px;height:9px;border-radius:50%;background:#0D9E6E;flex-shrink:0;margin-top:7px;box-shadow:0 0 0 3px #E6F7F2"></span>
      <span style="font-size:15px;color:#0D000D;line-height:1.85;font-weight:400">${safe}</span>
    </div>`;
  }
  // Default: clean, readable paragraph
  return `<div style="font-size:15.5px;line-height:2.0;color:#0D000D;letter-spacing:0.01em;font-weight:400">${safe}</div>`;
}

function rv2_section(section) {
  const hasConflict  = section.passages.some(p => p.support==="conflict" && !_rv2.resolved.has(p.id));
  const hasUncertain = section.passages.some(p => p.support==="uncertain" && !_rv2.resolved.has(p.id));
  const isS15       = section.nabhNum === "S15";
  const isActive    = _rv2.activeSectionId === section.id;

  // --- Tier data from LLM sections_json (live, not hardcoded) ---
  // section.id is already "s1"–"s15" matching the sections_json keys directly.
  const _sj       = APP.reviewData?.sectionsJson || null;
  const _secData  = _sj ? (_sj[section.id] || null) : null;
  // Tier and issues come exclusively from Pass 3 (sections_json written after generation)
  let _tier = _secData?.tier || null;   // "OK" | "T1" | "T2" | "T3" | null
  const _rawIssues = Array.isArray(_secData?.issues) ? _secData.issues.filter(Boolean) : [];
  const _TRUNC_RE = /truncat|cut.?off|mid.?sentence|incomplete.*sentence|sentence.*incomplete|appears.*truncated|text.*truncated/i;
  // Normalise issues — supports both new format {category,ai_output,source_value,explanation}
  // and legacy format {description,quote}. no_source issues are informational only, never shown.
  const _issues = _rawIssues
    .filter(i => (typeof i === 'object' && i !== null) && i.category !== 'no_source')
    .map(i => {
      if (typeof i === 'string') return { description: i, quote: '', sourceValue: null, category: null };
      const desc  = i.explanation || i.description || '';
      const quote = i.ai_output   || i.quote       || '';
      return {
        description:  desc,
        quote:        quote,
        sourceValue:  i.source_value !== undefined ? i.source_value : null,
        category:     i.category || null,
      };
    })
    .filter(i => !(_tier === 'T1' && _TRUNC_RE.test(i.description)));
  if (_tier === 'T1' && _issues.length === 0) _tier = 'OK';
  const _allIssues = _issues;
  const _quotes    = _issues.map(i => i.quote).filter(q => q && q.length >= 3);
  const _conf     = _secData?.confidence ?? null;
  const _passed   = _secData?.passed !== false;      // false = failed confidence gate
  const _tierOpen = _rv2.tierPanelId === section.id;
  const _hasIssues = _tier && _tier !== "OK" && _allIssues.length > 0;
  const _secTierResolved = _rv2.resolvedTierSections.has(section.id);

  let borderColor = "#C8A0C8";
  let headerBg    = "linear-gradient(135deg,#FDFAFD 0%,#F8F0F8 100%)";
  let badgeBg     = "#EDD0ED"; let badgeColor = "#3D003D"; let badgeBorder = "#B880B8";
  let statusDot   = "";
  let cardShadow  = "0 3px 14px rgba(128,0,128,.10),0 1px 4px rgba(128,0,128,.06)";
  let titleColor  = "#0D000D";

  // T3 sections override border to red to make critical issues immediately visible
  if (_tier === "T3") {
    borderColor = "#FCA5A5";
    cardShadow  = "0 2px 10px rgba(220,38,38,.13)";
  } else if (_tier === "T2") {
    borderColor = "#FCD34D";
    cardShadow  = "0 2px 10px rgba(217,119,6,.10)";
  } else if (_tier === "T1") {
    borderColor = "#FDE047";
    cardShadow  = "0 2px 10px rgba(234,179,8,.10)";
  }
  // Doctor acknowledged this tier error — override to green
  if (_secTierResolved && _hasIssues) {
    borderColor = "#86EFAC";
    cardShadow  = "0 2px 10px rgba(22,163,74,.10)";
  }

  if (isActive) {
    borderColor = "#800080"; headerBg = "linear-gradient(135deg,#F5E6F5 0%,#FBF0FB 100%)";
    badgeBg = "linear-gradient(135deg,#800080,#A020A0)"; badgeColor = "#fff"; badgeBorder = "#800080";
    cardShadow = "0 6px 20px rgba(128,0,128,.20),0 2px 6px rgba(128,0,128,.10)"; titleColor = "#5C005C";
  } else if (hasConflict) {
    borderColor = "#FCA5A5"; headerBg = "linear-gradient(135deg,#FFF8F8,#FEF2F2)";
    badgeBg = "#FEE2E2"; badgeColor = "#DC2626"; badgeBorder = "#FCA5A5";
    cardShadow = "0 2px 10px rgba(220,38,38,.09)"; titleColor = "#1A001A";
    statusDot = `<span style="width:9px;height:9px;border-radius:50%;background:#DC2626;display:inline-block;flex-shrink:0;box-shadow:0 0 0 3px #FEE2E2,0 0 8px rgba(220,38,38,.4)"></span>`;
  } else if (hasUncertain) {
    borderColor = "#FCD34D"; headerBg = "linear-gradient(135deg,#FFFFF5,#FFFBEB)";
    badgeBg = "#FEF3C7"; badgeColor = "#92400E"; badgeBorder = "#FCD34D";
    cardShadow = "0 2px 10px rgba(217,119,6,.09)"; titleColor = "#1A001A";
    statusDot = `<span style="width:9px;height:9px;border-radius:50%;background:#F59E0B;display:inline-block;flex-shrink:0;box-shadow:0 0 0 3px #FEF3C7,0 0 8px rgba(245,158,11,.35)"></span>`;
  } else if (isS15) {
    borderColor = "#FCA5A5"; headerBg = "linear-gradient(135deg,#FFF8F8,#FEF2F2)";
    badgeBg = "#FEE2E2"; badgeColor = "#DC2626"; badgeBorder = "#FCA5A5";
  }

  const nabhBadge = section.nabhNum
    ? `<span style="display:inline-flex;align-items:center;padding:3px 11px;border-radius:20px;font-size:10px;font-weight:800;letter-spacing:0.09em;background:${badgeBg};color:${badgeColor};border:1.5px solid ${badgeBorder};flex-shrink:0;font-family:var(--mono,monospace)">${section.nabhNum}</span>`
    : "";

  // Tier badge — resolved sections show green "TX ✓ Resolved"; others show T3/T2/T1 or ✓ OK.
  const _tierBadge =
    (_secTierResolved && _hasIssues)
      ? `<span class="rv2-tier-badge" data-sec-id="${section.id}" style="display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:800;background:#F0FDF4;color:#15803D;border:1.5px solid #86EFAC;flex-shrink:0;cursor:pointer;letter-spacing:0.04em">${_tier} ✓ Resolved${_tierOpen?" ▾":""}</span>`
    : (_tier === "T3")
      ? `<span class="rv2-tier-badge" data-sec-id="${section.id}" style="display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:800;background:#FEE2E2;color:#DC2626;border:1.5px solid #FCA5A5;flex-shrink:0;cursor:${_hasIssues?"pointer":"default"};letter-spacing:0.04em">T3 Critical${_hasIssues?" ▾":""}</span>`
    : (_tier === "T2")
      ? `<span class="rv2-tier-badge" data-sec-id="${section.id}" style="display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:800;background:#FEF3C7;color:#92400E;border:1.5px solid #FCD34D;flex-shrink:0;cursor:${_hasIssues?"pointer":"default"};letter-spacing:0.04em">T2 Medication${_hasIssues?" ▾":""}</span>`
    : (_tier === "T1")
      ? `<span class="rv2-tier-badge" data-sec-id="${section.id}" style="display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:800;background:#FEF9C3;color:#854D0E;border:1.5px solid #FDE047;flex-shrink:0;cursor:${_hasIssues?"pointer":"default"};letter-spacing:0.04em">T1 Minor${_hasIssues?" ▾":""}</span>`
    : `<span style="display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:700;background:#F0FDF4;color:#15803D;border:1.5px solid #86EFAC;flex-shrink:0;letter-spacing:0.04em">✓ OK</span>`;

  // Confidence chip — shown when confidence < 0.80 to flag low-certainty sections
  const _confChip = (_conf !== null && _conf < 0.80 && _tier !== "OK")
    ? `<span style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;font-size:9.5px;font-weight:700;background:#F3F4F6;color:#6B7280;border:1px solid #E5E7EB;flex-shrink:0;font-family:monospace">${Math.round(_conf*100)}% conf</span>`
    : "";

  // Click-expandable issues panel (inside card, between header and passages)
  const _issueColor  = _tier==="T3" ? "#DC2626" : _tier==="T2" ? "#92400E" : "#854D0E";
  const _issueBg     = _tier==="T3" ? "#FEF2F2" : _tier==="T2" ? "#FFFBEB" : "#FEFCE8";
  const _issueBorder = _tier==="T3" ? "#FCA5A5" : _tier==="T2" ? "#FCD34D" : "#FDE047";
  const _issueLabel  = _tier==="T3" ? "T3 — Critical Clinical Error" : _tier==="T2" ? "T2 — Medication Concern" : "T1 — Minor Edit";
  const _issueFooter = _secTierResolved
    ? `Acknowledged: ${_issueLabel} was flagged by AI verification — reviewed and resolved by attending.`
    : !_passed
    ? `⚠ Section failed confidence gate (${_conf !== null ? Math.round(_conf*100)+"%" : "unknown"} — threshold 60%). Manual entry required.`
    : _tier==="T3" ? "Resolve this critical error before signing." : _tier==="T2" ? "Review medication before sign-off." : "Minor edit — fix before signing.";
  const _resolveBtn = _hasIssues
    ? (!_secTierResolved
        ? `<button data-resolve-sec="${section.id}" style="margin-top:10px;padding:5px 14px;border:none;border-radius:6px;background:#15803D;color:#fff;font-size:11.5px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:5px">✓ Mark as Resolved</button>`
        : `<button data-unresolve-sec="${section.id}" style="margin-top:8px;padding:4px 12px;border:1px solid #D1D5DB;border-radius:6px;background:#fff;font-size:11px;color:#6B7280;cursor:pointer;font-weight:600">↩ Un-resolve</button>`)
    : '';
  const _issuesPanel = _hasIssues && _tierOpen ? `
    <div style="padding:12px 20px 14px;background:${_secTierResolved?"#F0FDF4":_issueBg};border-bottom:1.5px solid ${_secTierResolved?"#86EFAC":_issueBorder}">
      <div style="font-size:10.5px;font-weight:800;color:${_secTierResolved?"#15803D":_issueColor};text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">${_issueLabel}</div>
      ${_secTierResolved ? `<div style="background:#DCFCE7;border:1px solid #86EFAC;border-radius:6px;padding:7px 12px;margin-bottom:10px;font-size:11px;font-weight:700;color:#15803D;display:flex;align-items:center;gap:6px">✓ Error acknowledged and resolved by attending physician</div>` : ''}
      <div style="${_secTierResolved?"opacity:0.55;":""}">
      ${_allIssues.map(iss => {
        const catLabel = iss.category ? iss.category.replace(/_/g,' ') : null;
        const catChip  = catLabel
          ? `<span style="display:inline-block;padding:1px 7px;border-radius:99px;font-size:9.5px;font-weight:700;background:${_issueBg};border:1px solid ${_issueBorder};color:${_issueColor};letter-spacing:0.04em;text-transform:uppercase;margin-right:6px;flex-shrink:0">${catLabel}</span>`
          : '';
        const aiLine = iss.quote
          ? `<div style="margin:5px 0 0 20px;padding:5px 10px;background:#FEF08A;border-left:3px solid #EAB308;border-radius:0 4px 4px 0;font-size:11.5px;font-weight:600;color:#713F12;font-family:monospace;letter-spacing:0.01em">AI wrote: &ldquo;${iss.quote}&rdquo;</div>`
          : '';
        const srcLine = iss.sourceValue !== null && iss.sourceValue !== undefined
          ? `<div style="margin:4px 0 0 20px;padding:5px 10px;background:#F0FDF4;border-left:3px solid #22C55E;border-radius:0 4px 4px 0;font-size:11.5px;font-weight:600;color:#15803D;font-family:monospace">Source: ${String(iss.sourceValue)}</div>`
          : (iss.quote ? `<div style="margin:4px 0 0 20px;padding:5px 10px;background:#FEF2F2;border-left:3px solid #EF4444;border-radius:0 4px 4px 0;font-size:11.5px;font-weight:600;color:#DC2626;font-family:monospace">Source: not found in source data</div>` : '');
        return `
        <div style="margin-bottom:12px">
          <div style="display:flex;gap:4px;align-items:baseline;font-size:12.5px;color:#374151;flex-wrap:wrap">
            <span style="color:${_issueColor};font-size:15px;line-height:1;flex-shrink:0">•</span>
            ${catChip}<span>${iss.description}</span>
          </div>
          ${aiLine}${srcLine}
        </div>`;
      }).join("")}
      </div>
      <div style="font-size:11px;color:#6B7280;margin-top:4px">${_issueFooter}</div>
      ${_resolveBtn}
    </div>` : "";

  const srcHint = isActive
    ? `<span style="font-size:10.5px;color:#800080;font-weight:700;flex-shrink:0;border:1.5px solid #800080;border-radius:20px;padding:3px 12px;background:#F5E6F5;letter-spacing:0.03em">source ↗</span>`
    : `<span style="font-size:10.5px;color:#5C005C;font-weight:600;flex-shrink:0;border:1.5px solid #C8A0C8;border-radius:20px;padding:3px 12px;background:#F5E6F5;letter-spacing:0.02em">source</span>`;

  return `
    <div style="margin-bottom:18px;border:2px solid ${borderColor};border-radius:14px;overflow:hidden;background:#FFFFFF;box-shadow:${cardShadow}">
      <div data-rv2-section="${section.id}" style="display:flex;align-items:center;gap:8px;padding:14px 20px;background:${headerBg};border-bottom:2px solid ${borderColor};cursor:pointer;user-select:none" title="Click to highlight source blocks">
        ${nabhBadge}
        <span style="font-size:14px;font-weight:700;color:${titleColor};flex:1;letter-spacing:-0.01em">${section.nabhLabel || section.title}</span>
        ${statusDot}
        ${_tierBadge}
        ${_confChip}
        ${srcHint}
      </div>
      ${_issuesPanel}
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:8px;background:#FFFFFF">
        ${section.passages.map(p => rv2_passage(p, section.id, _tierOpen ? _quotes : null)).join("")}
      </div>
    </div>`;
}

// ── Per-section error flag form ──────────────────────────────────────────────

function rv2ToggleFlagForm(sectionId) {
  _rv2.flagFormSectionId = _rv2.flagFormSectionId === sectionId ? null : sectionId;
  rv2Rerender();
}

function rv2ResolveTierSection(secId) {
  _rv2.resolvedTierSections.add(secId);
  rv2Rerender();
}
function rv2UnresolveTierSection(secId) {
  _rv2.resolvedTierSections.delete(secId);
  rv2Rerender();
}

function rv2_flagForm(section) {
  const aiText = (section.passages || []).map(p => p.text || '').join(' ').slice(0, 300);
  return `<div id="rv2-flag-form-${section.id}" style="background:#FFF7ED;border-bottom:2px solid #FED7AA;padding:14px 20px;display:flex;flex-direction:column;gap:10px">
    <div style="font-size:12px;font-weight:800;color:#92400E;text-transform:uppercase;letter-spacing:0.06em">Report AI Error — ${section.nabhLabel || section.title}</div>
    <div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">
      <div style="display:flex;gap:8px;align-items:center">
        <span style="font-size:11px;font-weight:700;color:#6B7280">Tier:</span>
        ${[['1','T1 Minor','#854D0E'],['2','T2 Medication','#92400E'],['3','T3 Critical','#DC2626']].map(([v,label,col])=>`
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;font-weight:700;color:${col}">
            <input type="radio" name="rv2-flag-tier-${section.id}" value="${v}" style="cursor:pointer" ${v==='1'?'checked':''}>
            ${label}
          </label>`).join('')}
      </div>
      <div style="display:flex;gap:6px;align-items:center">
        <span style="font-size:11px;font-weight:700;color:#6B7280">Category:</span>
        <select id="rv2-flag-cat-${section.id}" style="font-size:11px;padding:3px 6px;border:1.5px solid #D1D5DB;border-radius:5px">
          <option value="formatting">T1 — Formatting / Phrasing</option>
          <option value="medication_dose">T2 — Wrong Drug / Dose / Duration</option>
          <option value="diagnosis">T3 — Wrong Diagnosis</option>
          <option value="hallucination">T3 — Hallucinated Data</option>
          <option value="missed_finding">T3 — Missed Finding</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div style="display:flex;gap:6px;align-items:center">
        <span style="font-size:11px;font-weight:700;color:#6B7280">Source present?</span>
        <label style="font-size:11px;cursor:pointer"><input type="radio" name="rv2-flag-src-${section.id}" value="yes" checked> Yes</label>
        <label style="font-size:11px;cursor:pointer"><input type="radio" name="rv2-flag-src-${section.id}" value="no"> No</label>
      </div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <div style="flex:1;min-width:200px">
        <div style="font-size:10px;font-weight:700;color:#6B7280;margin-bottom:3px">What AI wrote (editable)</div>
        <textarea id="rv2-flag-ai-${section.id}" rows="2" style="width:100%;font-size:12px;padding:6px 8px;border:1.5px solid #D1D5DB;border-radius:6px;resize:vertical;box-sizing:border-box">${aiText.replace(/"/g,'&quot;')}</textarea>
      </div>
      <div style="flex:1;min-width:200px">
        <div style="font-size:10px;font-weight:700;color:#6B7280;margin-bottom:3px">Correct value / what it should say</div>
        <textarea id="rv2-flag-cv-${section.id}" rows="2" placeholder="e.g. Atorva 80mg OD, not 40mg" style="width:100%;font-size:12px;padding:6px 8px;border:1.5px solid #D1D5DB;border-radius:6px;resize:vertical;box-sizing:border-box"></textarea>
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <button onclick="rv2SubmitFlag('${section.id}')" style="background:#DC2626;color:#fff;border:none;border-radius:6px;padding:6px 18px;font-size:12px;font-weight:700;cursor:pointer">Submit Error Report</button>
      <button onclick="rv2ToggleFlagForm('${section.id}')" style="background:none;border:1.5px solid #D1D5DB;border-radius:6px;padding:5px 14px;font-size:11px;color:#6B7280;cursor:pointer">Cancel</button>
      <span id="rv2-flag-status-${section.id}" style="font-size:11px;color:#16A34A;font-weight:700"></span>
    </div>
  </div>`;
}

async function rv2SubmitFlag(sectionId) {
  const tierEl = document.querySelector(`input[name="rv2-flag-tier-${sectionId}"]:checked`);
  const catEl  = document.getElementById(`rv2-flag-cat-${sectionId}`);
  const aiEl   = document.getElementById(`rv2-flag-ai-${sectionId}`);
  const cvEl   = document.getElementById(`rv2-flag-cv-${sectionId}`);
  const srcEl  = document.querySelector(`input[name="rv2-flag-src-${sectionId}"]:checked`);
  const statusEl = document.getElementById(`rv2-flag-status-${sectionId}`);
  if (!tierEl) return;
  const tier = parseInt(tierEl.value, 10);
  const hadmId = APP.reviewData?.hadmId || APP.reviewData?.encounter?.hadm_id;
  const version = String(APP.reviewData?.encounter?.version || '1');
  if (statusEl) statusEl.textContent = 'Submitting…';
  const result = await apiLogError({
    hadm_id:         String(hadmId),
    summary_version: version,
    nabh_section:    sectionId,
    error_tier:      tier,
    error_category:  catEl ? catEl.value : 'other',
    ai_output:       aiEl ? aiEl.value.slice(0, 1000) : '',
    correct_value:   cvEl ? cvEl.value.slice(0, 500) : null,
    source_present:  srcEl ? srcEl.value === 'yes' : null,
    attending_id:    APP.currentUser?.id || null,
  });
  if (statusEl) statusEl.textContent = `✓ Logged as T${tier}`;
  // Check pilot pause gate
  if (result && result.gate_status === 'pause') {
    _rv2.pilotPauseBanner = { rate_pct: result.tier3_rate_pct };
  }
  setTimeout(() => { _rv2.flagFormSectionId = null; rv2Rerender(); }, 1200);
}

// ── Version history helpers ───────────────────────────────────────────────────

function _rv2LCS(a, b) {
  const m = a.length, n = b.length;
  if (m === 0 || n === 0) return a.map(t=>({type:'del',text:t})).concat(b.map(t=>({type:'ins',text:t})));
  const dp = Array.from({length: m + 1}, () => new Int32Array(n + 1));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1]);
  const result = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i-1] === b[j-1]) { result.unshift({type:'same',text:a[i-1]}); i--; j--; }
    else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) { result.unshift({type:'ins',text:b[j-1]}); j--; }
    else { result.unshift({type:'del',text:a[i-1]}); i--; }
  }
  return result;
}

function _rv2WordDiff(oldText, newText) {
  if (oldText === newText) return [{type:'same',text:oldText}];
  // Limit to prevent O(n²) slowdown on very long texts
  const oldW = oldText.split(/(\s+)/).slice(0, 500);
  const newW = newText.split(/(\s+)/).slice(0, 500);
  return _rv2LCS(oldW, newW);
}

function _rv2RenderDiff(tokens) {
  return tokens.map(t => {
    const esc = t.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    if (t.type === 'del') return `<span style="background:#fee2e2;color:#991b1b;text-decoration:line-through">${esc}</span>`;
    if (t.type === 'ins') return `<span style="background:#dcfce7;color:#166534">${esc}</span>`;
    return `<span>${esc}</span>`;
  }).join('');
}

function _rv2FmtVerDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}) + ' ' +
         d.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'});
}

function rv2HistoryDrawer() {
  if (!_rv2.historyOpen && !_rv2.compareMode) return '';

  const SPIN = `<div style="width:18px;height:18px;border:3px solid #e5e7eb;border-top-color:#800080;border-radius:50%;animation:spin .7s linear infinite;flex-shrink:0"></div>`;
  const HEADER = (title, extra='') => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #e5e7eb;flex-shrink:0;background:linear-gradient(135deg,#1A001A,#2E002E)">
      <div>
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:#7A4A7A;font-weight:800">Version Control</div>
        <div style="font-size:15px;font-weight:800;color:#F0D8F0;margin-top:1px">${title}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">${extra}
        <button id="rv2-hist-close" style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#D090D0;padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">✕ Close</button>
      </div>
    </div>`;

  // ── Compare diff view — full-screen overlay ──
  if (_rv2.compareMode) {
    const vA = _rv2.compareDataA, vB = _rv2.compareDataB;
    const fmtVDate = iso => { try { return new Date(iso).toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}); } catch(_){ return iso||''; } };
    let diffBody = '';
    if (_rv2.comparePending) {
      diffBody = `<div style="display:flex;align-items:center;gap:12px;padding:48px;justify-content:center;color:#6b7280">${SPIN} Computing diff…</div>`;
    } else if (vA && vB) {
      const [old_, new_] = (vA.version_num < vB.version_num) ? [vA, vB] : [vB, vA];
      const sectsOld = (typeof rv2ParseSummary === 'function') ? rv2ParseSummary(old_.content) : [];
      const sectsNew = (typeof rv2ParseSummary === 'function') ? rv2ParseSummary(new_.content) : [];
      const _NABH_LABELS = {s1:'Patient Details',s2:'Chief Complaint',s3:'History of Presenting Illness',s4:'Past Medical History',s5:'Vital Signs',s6:'Laboratory Investigations',s7:'Imaging & Procedures',s8:'Diagnosis',s9:'Hospital Course',s10:'ICU Summary',s11:'Discharge Medications',s12:'Follow-up Instructions',s13:'Final Diagnosis',s14:'Discharge Condition',s15:'Patient Acknowledgement'};
      const allIds = ['s1','s2','s3','s4','s5','s6','s7','s8','s9','s10','s11','s12','s13','s14','s15'];
      let changed = 0, unchanged = 0;
      const sectBlocks = allIds.map(sid => {
        const soSec = sectsOld.find(s => s.id === sid);
        const snSec = sectsNew.find(s => s.id === sid);
        const oldTxt = (soSec?.passages||[]).map(p=>p.text).join('\n') || '';
        const newTxt = (snSec?.passages||[]).map(p=>p.text).join('\n') || '';
        const label  = _NABH_LABELS[sid] || sid.toUpperCase();
        if (oldTxt === newTxt) {
          unchanged++;
          const safe = oldTxt.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
          return `<details style="border:1px solid #e5e7eb;border-radius:8px;margin-bottom:8px;overflow:hidden">
            <summary style="padding:10px 14px;background:#f9fafb;cursor:pointer;font-size:12.5px;font-weight:600;color:#6b7280;list-style:none;display:flex;align-items:center;gap:8px">
              <span style="font-size:10px;font-weight:700;background:#e5e7eb;color:#6b7280;padding:2px 7px;border-radius:4px">${sid.toUpperCase()}</span>
              ${label} <span style="margin-left:auto;font-size:11px;color:#9ca3af">No changes</span>
            </summary>
            <div style="padding:12px 14px;font-size:12.5px;line-height:1.7;color:#374151;white-space:pre-wrap">${safe}</div>
          </details>`;
        }
        changed++;
        const tokens = _rv2WordDiff(oldTxt, newTxt);
        const diffHTML = _rv2RenderDiff(tokens);
        return `<div style="border:1.5px solid #c4b5fd;border-radius:8px;margin-bottom:10px;overflow:hidden">
          <div style="padding:10px 14px;background:#f5f3ff;border-bottom:1px solid #e9d5ff;display:flex;align-items:center;gap:8px">
            <span style="font-size:10px;font-weight:700;background:#7c3aed;color:#fff;padding:2px 7px;border-radius:4px">${sid.toUpperCase()}</span>
            <span style="font-size:12.5px;font-weight:700;color:#3b0764">${label}</span>
            <span style="margin-left:auto;font-size:10.5px;font-weight:700;color:#7c3aed">CHANGED</span>
          </div>
          <div style="padding:14px;font-size:12.5px;line-height:1.9;color:#374151;white-space:pre-wrap">${diffHTML}</div>
        </div>`;
      }).join('');
      diffBody = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px">
          <div>
            <div style="font-size:16px;font-weight:800;color:#111827">V${old_.version_num} vs V${new_.version_num}</div>
            <div style="font-size:11.5px;color:#6b7280;margin-top:2px">${fmtVDate(old_.created_at)} · ${old_.saved_by_name||'Doctor'} &nbsp;→&nbsp; ${fmtVDate(new_.created_at)} · ${new_.saved_by_name||'Doctor'}</div>
          </div>
          <div style="display:flex;gap:8px;font-size:11.5px;flex-wrap:wrap">
            <span style="background:#fee2e2;color:#b91c1c;border-radius:4px;padding:3px 10px;text-decoration:line-through">Removed</span>
            <span style="background:#dcfce7;color:#15803d;border-radius:4px;padding:3px 10px">Added</span>
            <span style="background:#f3f4f6;color:#6b7280;border-radius:4px;padding:3px 10px">Unchanged</span>
          </div>
        </div>
        <div style="font-size:12px;color:#6b7280;margin-bottom:16px">${changed} section${changed!==1?'s':''} changed · ${unchanged} unchanged (collapsed)</div>
        ${sectBlocks}`;
    } else {
      diffBody = `<div style="padding:32px;color:#6b7280;font-size:13px">Failed to load version data.</div>`;
    }
    return `
      <div id="rv2-hist-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9400;display:flex;align-items:flex-start;justify-content:center;padding:24px;overflow-y:auto">
        <div style="width:100%;max-width:860px;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 24px 64px rgba(0,0,0,.3);display:flex;flex-direction:column;min-height:0">
          <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 24px;background:linear-gradient(135deg,#1A001A,#2E002E);flex-shrink:0">
            <div>
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:#7A4A7A;font-weight:800">Version Control</div>
              <div style="font-size:15px;font-weight:800;color:#F0D8F0;margin-top:1px">DS Version Compare</div>
            </div>
            <div style="display:flex;gap:8px">
              <button id="rv2-hist-back" style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#D090D0;padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">← Back to versions</button>
              <button id="rv2-hist-close" style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#D090D0;padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">✕ Close</button>
            </div>
          </div>
          <div style="padding:24px;overflow-y:auto">${diffBody}</div>
        </div>
      </div>`;
  }

  // ── Version list ──
  if (!_rv2.historyOpen) return '';

  let body = '';
  if (_rv2.historyLoading) {
    body = `<div style="display:flex;align-items:center;gap:12px;padding:32px;color:#6b7280">${SPIN} Loading version history…</div>`;
  } else if (_rv2.historyError) {
    body = `<div style="padding:24px">
      <div style="color:#dc2626;font-weight:600;margin-bottom:6px">Failed to load history</div>
      <div style="font-size:12px;color:#6b7280;margin-bottom:12px">${_rv2.historyError}</div>
      <button id="rv2-hist-retry" style="padding:6px 14px;background:#800080;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-family:inherit">Retry</button>
    </div>`;
  } else {
    const versions = _rv2.historyVersions || [];
    if (versions.length === 0) {
      body = `<div style="padding:48px 24px;text-align:center;color:#6b7280">
        <div style="font-size:32px;margin-bottom:10px">📋</div>
        <div style="font-size:14px;font-weight:700;color:#374151;margin-bottom:4px">No versions yet</div>
        <div style="font-size:12.5px">Save a draft to create the first version snapshot.</div>
      </div>`;
    } else {
      const compareReady = _rv2.compareSelA && _rv2.compareSelB;
      const rows = versions.map((v, i) => {
        const isCurrent = i === 0;
        const isSelA = _rv2.compareSelA === v.id;
        const isSelB = _rv2.compareSelB === v.id;
        const isChecked = isSelA || isSelB;
        const canCheck  = isChecked || (!_rv2.compareSelA || !_rv2.compareSelB);
        const typePill = v.save_type === 'signed'
          ? `<span style="background:#F3E8FF;color:#6b21a8;border:1px solid #e9d5ff;border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700">Signed</span>`
          : `<span style="background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb;border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700">Draft</span>`;
        return `
          <div class="rv2h-row" data-vid="${v.id}" style="padding:12px 14px;border-bottom:1px solid #f3f4f6;display:flex;align-items:center;gap:10px;background:${isCurrent?'#faf5ff':'#fff'};transition:background .15s">
            <input type="checkbox" class="rv2h-compare-cb" data-vid="${v.id}" ${isChecked?'checked':''} ${(!canCheck&&!isChecked)?'disabled':''} style="width:15px;height:15px;cursor:pointer;accent-color:#800080;flex-shrink:0">
            <div style="flex:1;min-width:0">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
                <span style="font-size:13px;font-weight:800;color:#800080">V${v.version_num}</span>
                ${isCurrent?`<span style="background:#800080;color:#fff;border-radius:20px;padding:2px 8px;font-size:10px;font-weight:700">Current</span>`:''}
                ${typePill}
              </div>
              <div style="font-size:11px;color:#6b7280">${_rv2FmtVerDate(v.created_at)} · ${v.saved_by_name||'Doctor'}</div>
            </div>
            <button class="rv2h-view-btn" data-vid="${v.id}" style="background:#f9fafb;border:1px solid #e5e7eb;color:#374151;padding:5px 10px;border-radius:6px;font-size:11.5px;font-weight:600;cursor:pointer;font-family:inherit;white-space:nowrap">View</button>
          </div>`;
      }).join('');
      body = `
        <div style="flex:1;overflow-y:auto">
          <div style="padding:10px 14px;background:#f9fafb;border-bottom:1px solid #e5e7eb;font-size:11px;color:#6b7280">
            ${versions.length} version${versions.length>1?'s':''} · Check 2 versions to compare
          </div>
          ${rows}
        </div>
        ${compareReady ? `
        <div style="padding:14px;border-top:2px solid #e5e7eb;flex-shrink:0;background:#faf5ff">
          <button id="rv2h-compare-btn" style="width:100%;padding:10px;background:linear-gradient(135deg,#800080,#A020A0);color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit">
            Compare V${(_rv2.historyVersions.find(v=>v.id===_rv2.compareSelA)||{}).version_num||'?'} vs V${(_rv2.historyVersions.find(v=>v.id===_rv2.compareSelB)||{}).version_num||'?'}
          </button>
        </div>` : ''}`;
    }
  }

  return `
    <div id="rv2-hist-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9400;display:flex;justify-content:flex-end">
      <div id="rv2-hist-drawer" style="width:min(460px,100vw);height:100%;background:#fff;display:flex;flex-direction:column;overflow:hidden;box-shadow:-4px 0 24px rgba(0,0,0,.2)">
        ${HEADER('Versions')}
        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden">${body}</div>
      </div>
    </div>`;
}

// ── Screen renderer (overrides review.js) ─────────────────────────────────────

SCREEN_RENDERERS["review"] = function renderReviewV2() {
  if (_rv2.auditMode) {
    const banner = `
      <div id="rv2-audit-banner" style="position:fixed;top:0;left:0;right:0;z-index:9999;background:#1C1200;border-bottom:2px solid #D97706;padding:9px 24px;display:flex;align-items:center;justify-content:space-between">
        <div style="display:flex;align-items:center;gap:10px">
          ${iconSVG("alert",15)}
          <span style="font-size:12px;font-weight:700;color:#D97706;text-transform:uppercase;letter-spacing:0.08em">Technical Audit View</span>
          <span style="font-size:12px;color:#78350F">— For compliance, AI debugging, and administrative review only. Not intended for clinical decision-making.</span>
        </div>
        <button id="rv2-back-clinical" class="btn btn-ghost" style="font-size:12px;padding:4px 10px">Back to clinical view</button>
      </div>
      <div style="height:52px"></div>`;
    return banner + (_rv2OldRenderer ? _rv2OldRenderer() : "");
  }

  const user      = getUser();
  const rd        = APP.reviewData;
  // When viewing a historical version, render its content instead of live content
  const _viewSects = _rv2.viewingVersion?.content
    ? rv2ParseSummary(_rv2.viewingVersion.content)
    : null;
  const docSects  = _viewSects || (rd?.docSections?.length ? rd.docSections : rv2BuildDocSections(APP.claims || CLAIMS_INITIAL));
  const allP      = rv2AllPassages(docSects);
  const redP       = allP.filter(p => p.support==="conflict");
  const amberP     = allP.filter(p => p.support==="uncertain");
  const unresolvedRed = redP.filter(p => !_rv2.resolved.has(p.id));
  // NABH MN4 hard gate — S15 acknowledgement is a hard prerequisite for sign-off
  const s15ForGate    = docSects.find(s => s.id === "s15");
  const s15GateBlocked = !s15ForGate || s15ForGate.passages.some(p => !_rv2.resolved.has(p.id));
  const _sjForSign = APP.reviewData?.sectionsJson || null;
  const unresolvedT3 = _sjForSign
    ? Object.entries(_sjForSign).filter(([k, s]) => s?.tier === "T3" && !_rv2.resolvedTierSections.has(k)).length
    : 0;
  const canSign    = unresolvedRed.length === 0 && !s15GateBlocked && unresolvedT3 === 0;

  let statusDot, statusText, statusColor;
  if (unresolvedRed.length > 0 || s15GateBlocked || unresolvedT3 > 0) {
    statusDot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#DC2626;flex-shrink:0"></span>`;
    const parts = [];
    if (unresolvedRed.length > 0) parts.push(`${unresolvedRed.length} section${unresolvedRed.length>1?"s":""} flagged`);
    if (s15GateBlocked) parts.push("S15 acknowledgement required (NABH MN4)");
    if (unresolvedT3 > 0) parts.push(`${unresolvedT3} T3 Critical error${unresolvedT3>1?"s":""} unresolved — click the T3 badge, review the error, then click "Mark as Resolved"`);
    statusText = parts.join(" · ") + " — resolve before signing";
    statusColor = "#991B1B";
  } else if (amberP.length > 0) {
    statusDot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#D97706;flex-shrink:0"></span>`;
    statusText = `${amberP.length} section${amberP.length>1?"s":""} flagged for your review`;
    statusColor = "#92400E";
  } else {
    statusDot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#0D9E6E;flex-shrink:0"></span>`;
    statusText = "Ready to sign";
    statusColor = "#065F46";
  }

  const bannerHTML = _rv2.bannerDone ? "" : `
    <div style="background:linear-gradient(135deg,#FDF8FF,#F5E6F5);border:1.5px solid #D4A0D4;border-radius:12px;padding:14px 18px;margin-bottom:20px;display:flex;align-items:flex-start;justify-content:space-between;gap:12px;box-shadow:0 2px 8px rgba(128,0,128,.08)">
      <div style="display:flex;gap:10px;align-items:flex-start">
        <div style="width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#800080,#A020A0);display:grid;place-items:center;flex-shrink:0;box-shadow:0 2px 8px rgba(128,0,128,.35)">${iconSVG("info",14)}</div>
        <div>
          <div style="font-size:12.5px;font-weight:700;color:#2A102A;margin-bottom:4px">Evidence Verification Guide</div>
          <span style="font-size:12px;color:#4A2A4A;line-height:1.7">
            <span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px"><span style="width:8px;height:8px;border-radius:50%;background:#0D9E6E;display:inline-block"></span> Supported</span>
            <span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px"><span style="width:8px;height:8px;border-radius:50%;background:#D97706;display:inline-block"></span> Uncertain — verify</span>
            <span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px"><span style="width:8px;height:8px;border-radius:50%;background:#DC2626;display:inline-block"></span> Conflict — must resolve</span>
          </span>
        </div>
      </div>
      <button id="rv2-banner-close" style="background:rgba(128,0,128,.08);border:1px solid #D4A0D4;cursor:pointer;color:#800080;padding:4px 8px;border-radius:6px;flex-shrink:0;font-size:13px">${iconSVG("x",12)}</button>
    </div>`;


  const pilotPauseBannerHTML = _rv2.pilotPauseBanner ? `
    <div style="position:sticky;top:0;z-index:200;background:#7F1D1D;border-bottom:3px solid #DC2626;padding:10px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px">
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:16px">🛑</span>
        <span style="font-size:13px;font-weight:800;color:#FFF;letter-spacing:0.01em">PILOT PAUSE — T3 rate is ${_rv2.pilotPauseBanner.rate_pct || '>25'}% (threshold: 25%)</span>
        <span style="font-size:12px;color:#FCA5A5;font-weight:600">Escalate to Nitin Sahni immediately. No new summaries should be signed off until reviewed.</span>
      </div>
      <button onclick="_rv2.pilotPauseBanner=null;rv2Rerender()" style="background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.3);color:#fff;border-radius:6px;padding:4px 12px;font-size:11px;font-weight:700;cursor:pointer">Dismiss</button>
    </div>` : '';

  const modalHTML = (typeof renderClaimEditModal==="function" ? renderClaimEditModal() : "");

  // Discharge type badge
  const dischargeType = rd?.dischargeType || "Standard";
  const dtColors = { Standard:"#16A34A", LAMA:"#D97706", DAMA:"#D97706", Death:"#DC2626", Referral:"#7C3AED" };
  const dtBg     = { Standard:"#F0FDF4", LAMA:"#FFFBEB",  DAMA:"#FFFBEB",  Death:"#FEF2F2", Referral:"#F5F3FF" };
  const dtColor  = dtColors[dischargeType] || "#16A34A";
  const dtBgCol  = dtBg[dischargeType]     || "#F0FDF4";

  // Medication flag callout (shown when there are amber/conflict passages in s11)
  const s11 = docSects.find(s => s.id === "s11");
  const hasMedFlags = s11 && s11.passages.some(p => p.support === "uncertain" || p.support === "conflict");
  const medFlagBanner = hasMedFlags ? `
    <div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:8px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:flex-start;gap:10px">
      <span style="display:inline-block;width:16px;height:16px;border-radius:50%;background:#DC2626;flex-shrink:0;margin-top:1px"></span>
      <div>
        <div style="font-weight:700;font-size:12.5px;color:#DC2626">Medication Flag — Review Required</div>
        <div style="font-size:12px;color:#7F1D1D;margin-top:2px">One or more discharge medications require verification before sign-off.</div>
      </div>
    </div>` : "";

  // S15 NABH MN4 hard gate banner (uses s15GateBlocked computed with canSign above)
  const s15Unresolved = s15GateBlocked;
  const s15Banner = s15GateBlocked ? `
    <div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:8px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap">
      ${iconSVG("lock",15)}
      <div style="flex:1;min-width:0">
        <div style="font-weight:700;font-size:12.5px;color:#DC2626">NABH MN4 — Patient Acknowledgement Pending</div>
        <div style="font-size:12px;color:#7F1D1D;margin-top:2px">Patient/attendant signature must be obtained and confirmed before e-sign activates. See S15.</div>
      </div>
      <button id="rv2-s15-ack-btn" style="flex-shrink:0;padding:6px 14px;background:#065F46;color:white;border:none;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;white-space:nowrap">
        ✓ Patient acknowledgement confirmed
      </button>
    </div>` : "";

  const revisionModalHTML = _rv2.revisionModalOpen ? `
    <div id="rv2-revision-overlay" style="position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,0.65);display:flex;align-items:center;justify-content:center;padding:20px">
      <div style="background:white;border-radius:12px;padding:28px;width:500px;max-width:100%;box-shadow:0 24px 64px rgba(0,0,0,0.3)">
        <div style="display:flex;align-items:flex-start;gap:14px;margin-bottom:18px">
          <div style="width:40px;height:40px;border-radius:10px;background:#FEF2F2;display:grid;place-items:center;flex-shrink:0">${iconSVG("alert",18)}</div>
          <div>
            <div style="font-size:15px;font-weight:700;color:#1E293B">Reject summary?</div>
            <div style="font-size:12.5px;color:#64748B;margin-top:4px;line-height:1.65">
              Staff will see your message in the queue and can upload missing documents, fix data issues, and regenerate the summary before sending it back to you.
            </div>
          </div>
        </div>
        <label style="font-size:12px;font-weight:600;color:#374151;display:block;margin-bottom:6px">What needs to be fixed? <span style="color:#DC2626">*</span></label>
        <textarea id="rv2-rev-modal-ta" placeholder="e.g. CBC lab report is missing — please upload it and regenerate. The potassium value also looks incorrect."
          style="width:100%;font-size:13px;color:#1C1917;border:1.5px solid #CBD5E1;border-radius:8px;padding:10px 12px;resize:vertical;min-height:100px;font-family:inherit;box-sizing:border-box;outline:none;line-height:1.7">${_rv2.revisionModalText.replace(/</g,"&lt;")}</textarea>
        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px">
          <button id="rv2-rev-modal-cancel" class="btn btn-ghost btn-sm">Cancel</button>
          <button id="rv2-rev-modal-confirm" style="display:inline-flex;align-items:center;gap:7px;padding:8px 16px;border-radius:6px;font-size:13px;font-weight:600;background:#DC2626;border:1px solid #DC2626;color:white;cursor:pointer;font-family:inherit">
            ${iconSVG("alert",13)} Submit Rejection
          </button>
        </div>
      </div>
    </div>` : "";

  // E-sign canvas modal
  const esignModalHTML = _rv2.esignOpen ? (() => {
    const _u = getUser();
    const _rawN = _u?.full_name || _u?.name || "Doctor";
    const _dn   = /^Dr\.?\s/i.test(_rawN) ? _rawN : `Dr. ${_rawN}`;
    const _mci  = _u?.mci_number || _u?.registration_number || "";
    const _pat  = (APP.reviewData?.patient?.full_name) || "Patient";
    const _eid  = APP.reviewData?.hadmId ? fmtPid(APP.reviewData.hadmId) : "—";
    return `
    <div id="rv2-esign-overlay" style="position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,0.7);display:flex;align-items:center;justify-content:center;padding:20px">
      <div style="background:#fff;border-radius:14px;width:500px;max-width:100%;box-shadow:0 24px 64px rgba(0,0,0,0.35);overflow:hidden">

        <!-- Header -->
        <div style="padding:20px 22px 16px;border-bottom:1.5px solid #f3f4f6">
          <div style="display:flex;align-items:center;gap:12px">
            <div style="width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#800080,#a020a0);display:grid;place-items:center;flex-shrink:0">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            </div>
            <div>
              <div style="font-size:15px;font-weight:700;color:#111827">Sign Discharge Summary</div>
              <div style="font-size:12px;color:#6b7280;margin-top:2px">${_eid} — ${_pat}</div>
            </div>
            <button id="rv2-esign-close" style="margin-left:auto;background:none;border:none;cursor:pointer;padding:4px;color:#9ca3af;display:grid;place-items:center;border-radius:6px">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>

        <!-- Body -->
        <div style="padding:20px 22px">

          <!-- Doctor info row -->
          <div style="display:flex;gap:10px;margin-bottom:16px">
            <div style="flex:1;background:#f9fafb;border:1.5px solid #e5e7eb;border-radius:8px;padding:10px 12px">
              <div style="font-size:11px;color:#6b7280;font-weight:600;margin-bottom:3px;text-transform:uppercase;letter-spacing:.4px">Attending Doctor</div>
              <div style="font-size:13px;font-weight:700;color:#111827">${_dn}</div>
            </div>
            <div style="flex:1;background:#f9fafb;border:1.5px solid #e5e7eb;border-radius:8px;padding:10px 12px">
              <div style="font-size:11px;color:#6b7280;font-weight:600;margin-bottom:3px;text-transform:uppercase;letter-spacing:.4px">MCI / Reg. No.</div>
              <input id="rv2-esign-mci" value="${_mci.replace(/"/g,'&quot;')}" placeholder="Enter MCI number" style="border:none;background:transparent;font-size:13px;font-weight:700;color:#111827;width:100%;outline:none;font-family:monospace">
            </div>
          </div>

          <!-- Canvas label -->
          <div style="font-size:12px;font-weight:600;color:#374151;margin-bottom:8px">Draw your signature below</div>

          <!-- Canvas area -->
          <div style="position:relative;border:1.5px solid #d1d5db;border-radius:10px;background:#fff;overflow:hidden;height:130px">
            <canvas id="rv2-esign-canvas" width="456" height="130" style="display:block;width:100%;height:130px;cursor:crosshair;touch-action:none"></canvas>
            <div id="rv2-esign-hint" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none">
              <span style="font-size:13px;color:#d1d5db;font-style:italic">Sign here</span>
            </div>
          </div>

          <!-- Clear -->
          <button id="rv2-esign-clear" style="margin-top:8px;background:none;border:none;cursor:pointer;font-size:12px;color:#6b7280;padding:3px 0;font-family:inherit">
            Clear signature
          </button>
        </div>

        <!-- Footer -->
        <div style="padding:14px 22px 18px;border-top:1.5px solid #f3f4f6;display:flex;gap:10px;justify-content:flex-end">
          <button id="rv2-esign-cancel" style="padding:9px 18px;border:1.5px solid #e5e7eb;border-radius:8px;background:#fff;font-size:13.5px;font-weight:600;color:#374151;cursor:pointer;font-family:inherit">Cancel</button>
          <button id="rv2-esign-confirm" disabled style="padding:9px 22px;border:none;border-radius:8px;background:linear-gradient(135deg,#800080,#a020a0);color:#fff;font-size:13.5px;font-weight:700;cursor:pointer;font-family:inherit;opacity:.45;transition:opacity .15s">
            Confirm &amp; Sign
          </button>
        </div>
      </div>
    </div>`;
  })() : "";

  // Rejection flow re-review banner (shown when this summary was regenerated after rejection)
  // ── Amendment banner ──────────────────────────────────────────────────────
  const amdFlowBanner = (function() {
    const af = APP.amdFlow;
    if (!af || String(af.hadmId) !== String(rd?.hadmId)) return "";
    const detailHtml = af.details
      ? `<div style="font-size:12px;color:#78350F;padding:8px 12px;background:rgba(217,119,6,.1);border-radius:6px;border-left:3px solid #D97706;margin-top:4px">
           <strong>Details:</strong> ${af.details.replace(/</g,"&lt;")}
         </div>` : "";
    const sectionHtml = af.section
      ? `<span style="font-size:11px;color:#92400E;font-weight:600"> · Section: ${af.section}</span>` : "";
    return `
      <div style="background:#FFF7ED;border:1.5px solid #D97706;border-radius:10px;padding:12px 16px;margin-bottom:14px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="width:26px;height:26px;border-radius:7px;background:#D97706;display:grid;place-items:center;flex-shrink:0;font-size:14px">📝</div>
          <span style="font-size:12.5px;font-weight:700;color:#92400E">Amendment Requested</span>
          ${sectionHtml}
        </div>
        ${af.reason ? `<div style="font-size:12px;color:#78350F;padding:8px 12px;background:rgba(217,119,6,.1);border-radius:6px;border-left:3px solid #D97706;margin-top:4px">
           <strong>Reason:</strong> ${af.reason.replace(/</g,"&lt;")}
         </div>` : ""}
        ${detailHtml}
        <div style="font-size:11.5px;color:#92400E;margin-top:6px">
          Requested by <strong>${af.requestedBy}</strong>. Please update the relevant section and re-sign.
        </div>
      </div>`;
  })();

  const rejFlowBanner = (function() {
    const rf = APP.rejFlow;
    // Show banner when this encounter was previously rejected — match hadmId to avoid cross-patient bleed
    // Suppress if an amendment banner is already showing
    if (APP.amdFlow && String(APP.amdFlow.hadmId) === String(rd?.hadmId)) return "";
    if (!rf || !rf.rejectionLogId || !rf.rejectedAt) return "";
    if (String(rf.hadmId) !== String(rd?.hadmId)) return "";
    const reasonHtml = rf.rejectionReason
      ? `<div style="font-size:12px;color:#78350F;padding:8px 12px;background:rgba(245,158,11,.12);border-radius:6px;border-left:3px solid #F59E0B;margin-top:4px">
           <strong>Rejection reason:</strong> ${rf.rejectionReason.replace(/</g,"&lt;")}
         </div>` : "";
    return `
      <div style="background:#FFF7ED;border:1.5px solid #F59E0B;border-radius:10px;padding:12px 16px;margin-bottom:14px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="width:26px;height:26px;border-radius:7px;background:#F59E0B;display:grid;place-items:center;flex-shrink:0">${iconSVG("refresh",13)}</div>
          <span style="font-size:12.5px;font-weight:700;color:#92400E">Regenerated Summary — Addresses Previous Rejection</span>
        </div>
        ${reasonHtml}
        <div style="font-size:11.5px;color:#92400E;margin-top:6px;display:flex;align-items:center;gap:5px">
          ${iconSVG("check",12)}
          <span>Summary regenerated with your feedback applied. Review all sections before signing off.</span>
        </div>
      </div>`;
  })();

  const isMobile = window.innerWidth < 768;
  const mobTab   = _rv2.mobileTab || "summary";

  // Parse age/sex from summary text as fallback when rd.patient fields are absent
  const _rv2RawContent = rd?.encounter?.summary?.content || '';
  function _rv2ParseRaw(re) { const m = _rv2RawContent.match(re); return m ? m[1] : null; }
  const _ageRaw = rd?.patient?.age || rd?.patient?.anchor_age || _rv2ParseRaw(/Age\s*[:\-]?\s*(\d+)\s*(?:yrs?|years?)/i);
  const _sexRaw = rd?.patient?.gender      || _rv2ParseRaw(/Sex\s*:\s*([MF])\b/i);
  const _ageSexLabel = (_ageRaw || _sexRaw)
    ? `${_ageRaw ? _ageRaw + "Y" : "—"} / ${_sexRaw === "M" || _sexRaw === "m" ? "Male" : _sexRaw === "F" || _sexRaw === "f" ? "Female" : _sexRaw || "—"}`
    : "—";

  // Mobile tab switcher (shown on small screens instead of side-by-side panes)
  const mobileTabBar = isMobile ? `
    <div style="display:flex;background:white;border-bottom:2px solid var(--border);flex-shrink:0;position:sticky;top:0;z-index:10">
      <button id="rv2-mob-summary" style="flex:1;padding:12px 8px;font-size:13px;font-weight:700;border:none;cursor:pointer;background:${mobTab==='summary'?'white':'#FDFAFD'};color:${mobTab==='summary'?'#800080':'#9E7E9E'};border-bottom:3px solid ${mobTab==='summary'?'#800080':'transparent'};font-family:inherit;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px">
        ${iconSVG("doc",14)} Summary
      </button>
      <button id="rv2-mob-source" style="flex:1;padding:12px 8px;font-size:13px;font-weight:700;border:none;cursor:pointer;background:${mobTab==='source'?'white':'#FDFAFD'};color:${mobTab==='source'?'#800080':'#9E7E9E'};border-bottom:3px solid ${mobTab==='source'?'#800080':'transparent'};font-family:inherit;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px">
        ${iconSVG("search",14)} Source
      </button>
    </div>` : "";

  // Panel visibility logic
  const showSummary = !isMobile || mobTab === "summary";
  const showSource  = !isMobile || mobTab === "source";

  const summaryPanelStyle = _rv2.fullscreen==='summary'
    ? 'position:fixed;inset:0;z-index:9000;background:#F5F0FA;display:flex;flex-direction:column;overflow:hidden;'
    : showSummary
      ? `flex:1;border-right:${isMobile?'none':'1px solid var(--border)'};display:flex;flex-direction:column;overflow:hidden;`
      : 'display:none;';

  const sourcePanelStyle = _rv2.fullscreen==='source'
    ? 'position:fixed;inset:0;z-index:9000;width:100vw;display:flex;flex-direction:column;background:white;overflow:hidden;'
    : showSource
      ? `${isMobile?'flex:1;width:100%;':'width:'+_rv2.srcPanelWidth+'px;flex-shrink:0;'}display:flex;flex-direction:column;background:white;overflow:hidden;`
      : 'display:none;';

  const navBtnBase = "border:1px solid rgba(255,255,255,.12);cursor:pointer;font-size:12px;display:flex;align-items:center;gap:4px;font-family:inherit;padding:4px 10px;border-radius:6px;font-weight:500;flex-shrink:0";

  return `
    <div style="display:flex;flex-direction:column;height:100vh;overflow:hidden">
      ${renderTopbar({ user, hideSearch:true, crumbs:[{label:"My Queue", onclick:"navigate('doctor-dashboard')"}, rd?.patient?.full_name || _ddSynthName(rd?.hadmId) || "Patient", "Review"] })}
      <div style="display:flex;flex:1;overflow:hidden">
        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;background:#F5F0FA;min-width:0">



          <!-- Mobile tab bar -->
          ${mobileTabBar}

          <!-- Split pane / stacked pane -->
          <div style="flex:1;display:flex;overflow:hidden;min-height:0">

            <!-- SUMMARY PANEL -->
            <div style="${summaryPanelStyle}">
              <div style="padding:10px 14px;background:linear-gradient(135deg,#FFFFFF 0%,#FDF8FD 100%);border-bottom:1.5px solid #E8DEE8;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;position:relative">
                <div style="display:flex;align-items:center;gap:8px;min-width:0">
                  <div style="width:5px;height:18px;border-radius:3px;background:linear-gradient(180deg,#800080,#A020A0);flex-shrink:0"></div>
                  <span style="font-size:12.5px;font-weight:800;color:#1A001A;white-space:nowrap">NABH Summary</span>
                  <span style="font-size:9.5px;background:#F5E6F5;color:#5C005C;border:1px solid #D4A0D4;border-radius:20px;padding:2px 8px;font-weight:700;white-space:nowrap">15 SECTIONS</span>
                </div>
                ${!isMobile ? `<span style="position:absolute;left:50%;transform:translateX(-50%);font-size:11.5px;font-weight:700;color:#1A001A;white-space:nowrap;pointer-events:none">Click section to check ground truth of AI generated summary</span>` : ""}
                <button id="rv2-summary-fullscreen" style="cursor:pointer;padding:5px 10px;border-radius:6px;display:flex;align-items:center;gap:4px;font-family:inherit;font-size:11px;font-weight:600;border:1px solid ${_rv2.fullscreen==='summary'?'#800080':'#E0D0E0'};background:${_rv2.fullscreen==='summary'?'#800080':'white'};color:${_rv2.fullscreen==='summary'?'white':'#2A102A'}">
                  ${_rv2.fullscreen==='summary' ? `${iconSVG("x",12)} Exit` : `${iconSVG("external",11)} Full`}
                </button>
              </div>
              <div id="rv2-scroll" style="flex:1;overflow-y:auto;padding:14px 12px;padding-bottom:${isMobile?'110px':'14px'}">
                ${pilotPauseBannerHTML}
                ${amdFlowBanner}
                ${rejFlowBanner}
                <div style="background:#FDF8FF;border:1px solid #E8DEE8;border-radius:8px;padding:9px 14px;margin-bottom:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;flex-shrink:0">
                  ${statusDot}
                  <span style="font-size:12px;font-weight:600;color:${statusColor};flex:1;min-width:0">${statusText}</span>
                  ${!s15GateBlocked ? `<span style="font-size:11px;color:#6b7280;display:inline-flex;align-items:center;gap:10px;flex-shrink:0;flex-wrap:wrap">
                    <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:7px;height:7px;border-radius:50%;background:#0D9E6E;display:inline-block"></span>Supported</span>
                    <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:7px;height:7px;border-radius:50%;background:#D97706;display:inline-block"></span>Uncertain</span>
                    <span style="display:inline-flex;align-items:center;gap:4px"><span style="width:7px;height:7px;border-radius:50%;background:#DC2626;display:inline-block"></span>Conflict</span>
                  </span>` : ""}
                  ${s15GateBlocked ? `<button id="rv2-s15-ack-btn" style="flex-shrink:0;padding:5px 12px;background:#065F46;color:white;border:none;border-radius:6px;font-size:11.5px;font-weight:700;cursor:pointer;font-family:inherit;white-space:nowrap">✓ Confirm patient acknowledgement</button>` : ""}
                </div>
                <!-- Patient header card -->
                <div style="background:linear-gradient(135deg,#1A001A 0%,#2D0030 100%);border-radius:12px;padding:14px 16px;margin-bottom:14px;position:relative;overflow:hidden;box-shadow:0 4px 16px rgba(128,0,128,.25)">
                  <div style="position:absolute;right:-20px;top:-20px;width:80px;height:80px;border-radius:50%;background:radial-gradient(circle,rgba(192,64,192,.25),transparent 70%);pointer-events:none"></div>
                  <div style="font-size:9px;font-weight:800;color:rgba(192,64,192,.6);text-transform:uppercase;letter-spacing:0.20em;margin-bottom:8px">Foqal AI · Discharge Summary</div>
                  <div style="font-size:16px;font-weight:800;color:#F5E0F5;letter-spacing:-0.02em;margin-bottom:10px;line-height:1.2">${rd?.patient?.full_name || _ddSynthName(rd?.hadmId) || "Patient"}</div>
                  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(${isMobile?'100px':'130px'},1fr));gap:8px">
                    ${(() => {
                      // Parse dates from raw summary content (most reliable — no structure dependency)
                      const _rawContent = rd?.encounter?.summary?.content || '';
                      function _parseRaw(re) { const m = _rawContent.match(re); return m ? m[1] : null; }
                      function _fmtD(d) {
                        if (!d) return "—";
                        try { return new Date(d).toLocaleDateString("en-IN",{day:"numeric",month:"short",year:"numeric"}); }
                        catch { return String(d).slice(0,10); }
                      }
                      const admitRaw = rd?.admission?.admittime || _parseRaw(/Admission\s+Date\s*[:\-]\s*(\d{4}-\d{2}-\d{2}|\d{2}[\/\-]\d{2}[\/\-]\d{4})/i);
                      const dischRaw = rd?.admission?.dischtime || _parseRaw(/Discharge\s+Date\s*[:\-]\s*(\d{4}-\d{2}-\d{2}|\d{2}[\/\-]\d{2}[\/\-]\d{4})/i);
                      return [
                      ["Patient ID",  fmtPid(rd?.hadmId, rd?.encounter?.display_id) || "—"],
                      ["Age / Sex",  _ageSexLabel],
                      ["Admitted",   _fmtD(admitRaw)],
                      ["Discharged", _fmtD(dischRaw)],
                      ].map(([k,v]) => `<div style="background:rgba(255,255,255,.06);border-radius:6px;padding:7px 8px;border:1px solid rgba(255,255,255,.08)">
                        <div style="font-size:8.5px;font-weight:700;color:rgba(192,64,192,.7);text-transform:uppercase;letter-spacing:0.10em;margin-bottom:2px">${k}</div>
                        <div style="font-size:12px;font-weight:600;color:#F0D0F0;line-height:1.3">${v}</div>
                      </div>`).join("");
                    })()}
                  </div>
                </div>
                ${docSects.map(s=>rv2_section(s)).join("")}
              </div>
            </div>

            <!-- Resize handle — hidden on mobile -->
            ${!isMobile ? `<div id="rv2-src-resize" title="Drag to resize" style="width:5px;flex-shrink:0;cursor:col-resize;background:var(--border);position:relative;transition:background 0.15s;${_rv2.fullscreen ? 'display:none;' : ''}"></div>` : ""}

            <!-- SOURCE PANEL -->
            <div id="rv2-src-panel" style="${sourcePanelStyle}">
              <div style="padding:10px 14px;border-bottom:1.5px solid #E8DEE8;flex-shrink:0;background:linear-gradient(135deg,#FFFFFF 0%,#FDF8FD 100%)">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px">
                  <div style="display:flex;align-items:center;gap:7px;min-width:0;overflow:hidden">
                    <div style="width:5px;height:18px;border-radius:3px;background:linear-gradient(180deg,#5C005C,#800080);flex-shrink:0"></div>
                    <span style="font-size:12.5px;font-weight:800;color:#1A001A;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                      ${_rv2.activeSectionId ? `${_rv2.activeSectionId.toUpperCase()} — Source` : "Clinical Source"}
                    </span>
                  </div>
                  ${!isMobile ? `<button id="rv2-source-fullscreen" style="cursor:pointer;padding:5px 10px;border-radius:6px;display:flex;align-items:center;gap:4px;font-family:inherit;font-size:11px;font-weight:600;border:1px solid ${_rv2.fullscreen==='source'?'#800080':'#E0D0E0'};background:${_rv2.fullscreen==='source'?'#800080':'white'};color:${_rv2.fullscreen==='source'?'white':'#2A102A'};flex-shrink:0">
                    ${_rv2.fullscreen==='source' ? `${iconSVG("x",12)} Exit` : `${iconSVG("external",11)} Full`}
                  </button>` : ""}
                </div>
                <div style="font-size:10.5px;color:#9E7E9E;padding-left:12px">
                  ${_rv2.activeSectionId
                    ? `Source for <strong style="color:#800080">${_rv2.activeSectionId.toUpperCase()}</strong>`
                    : isMobile ? "Tap a section in Summary to highlight" : "Click a section → highlight source"}
                </div>
              </div>

              <!-- Source panel tab bar — same style as upload.html -->
              <div id="rv2-src-tab-bar" style="display:flex;border-bottom:1px solid #E8DEE8;padding-left:4px;overflow-x:auto;scrollbar-width:none;flex-shrink:0;background:#fff">
                ${(() => {
                  const _activeTabs = _rv2TabsForSection(_rv2.activeSectionId);
                  return _RV2_CTX_TABS.map(t => {
                    const isActive   = _rv2.activeCtxTab === t.key;
                    const isRelevant = !isActive && _activeTabs.includes(t.key);
                    const color = isActive ? '#800080' : isRelevant ? '#800080' : '#6b7280';
                    const borderBottom = isActive ? '2px solid #800080' : isRelevant ? '2px solid #C060C0' : '2px solid transparent';
                    const fw = isActive || isRelevant ? '600' : '400';
                    const bg = isRelevant && !isActive ? '#FDF8FF' : 'none';
                    const dot = isRelevant ? `<span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#800080;margin-left:5px;flex-shrink:0"></span>` : '';
                    return `<button data-rv2-ctx-tab="${t.key}" style="padding:10px 13px;font-size:12px;white-space:nowrap;background:${bg};border:none;border-bottom:${borderBottom};cursor:pointer;display:inline-flex;align-items:center;margin-bottom:-1px;color:${color};font-weight:${fw};flex-shrink:0;font-family:inherit;transition:color .12s">${t.label}${dot}</button>`;
                  }).join('');
                })()}
              </div>

              <div id="rv2-ctx-body" style="flex:1;overflow-y:auto;padding:0">
                ${_rv2.ctxLoading
                  ? `<div style="display:flex;align-items:center;gap:10px;padding:24px 16px;color:#6b7280">
                       <div style="width:16px;height:16px;border:2px solid var(--border);border-top-color:#800080;border-radius:50%;animation:spin 0.7s linear infinite;flex-shrink:0"></div>
                       <span style="font-size:12.5px">Loading source…</span>
                     </div>`
                  : _rv2.ctxError
                    ? `<div style="font-size:12.5px;color:var(--red);padding:16px">${_rv2.ctxError}</div>`
                    : _rv2.activeCtxTab
                      ? rv2SrcTabBody(_rv2.activeCtxTab)
                      : `<div style="text-align:center;padding:48px 20px;color:#9ca3af;line-height:1.8">
                           <div style="font-size:13px;font-weight:600;color:#6b7280;margin-bottom:4px">Select a tab above</div>
                           <div style="font-size:12px">or click a NABH section to auto-switch</div>
                         </div>`
                }
              </div>
            </div>

          </div>

          <!-- Footer action bar (desktop only — mobile uses fixed bar below) -->
          ${!isMobile ? `
          <div style="flex-shrink:0;background:white;border-top:2px solid #E8DEE8;box-shadow:0 -4px 16px rgba(128,0,128,.06)">
            <div style="display:flex;align-items:center;justify-content:flex-end;padding:11px 18px;gap:8px">
              <div style="display:flex;gap:8px;flex-shrink:0">
                <button class="btn btn-ghost btn-sm" id="rv2-show-history" style="border:1px solid #C8A0C8;color:#5C005C">Version Control</button>
                <button class="btn btn-ghost btn-sm" id="rv2-save-draft" ${Object.keys(_rv2.edits).length === 0 ? 'style="opacity:0.4"' : ""}>Save Version</button>
                <button class="btn btn-sm" id="rv2-send-revision" style="border:1px solid #EDD08A;color:#92400E;background:white;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:600">✕ Reject</button>
                <button id="rv2-sign" class="${canSign?"btn btn-navy":"btn btn-outline"} btn-sm" ${canSign?"":"disabled"} style="display:flex;align-items:center;gap:5px;padding:6px 14px;font-size:13px;${canSign?"background:linear-gradient(135deg,#800080,#A020A0);border-color:transparent;box-shadow:0 4px 14px rgba(128,0,128,.4);":"opacity:0.45;color:var(--ink-4)"}">
                  ${!canSign ? iconSVG("lock",12) : ""} Approve &amp; Sign
                </button>
              </div>
            </div>
          </div>` : ""}

        </div>
      </div>
      ${modalHTML}
      ${revisionModalHTML}
      ${esignModalHTML}

      <!-- Version read-only banner (when viewing a historical snapshot) -->
      ${_rv2.viewingVersionId && _rv2.viewingVersion ? `
      <div style="position:fixed;top:0;left:0;right:0;z-index:9300;background:#FEF3C7;border-bottom:2px solid #F59E0B;padding:8px 16px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 12px rgba(245,158,11,.2)">
        <span style="font-size:18px">📖</span>
        <div style="flex:1;font-size:12.5px;color:#92400E;font-weight:600">
          Viewing V${_rv2.viewingVersion.version_num} (${_rv2.viewingVersion.save_type === 'signed' ? 'Signed' : 'Draft'}) — ${_rv2FmtVerDate(_rv2.viewingVersion.created_at)} by ${_rv2.viewingVersion.saved_by_name || 'Doctor'} — <strong>Read Only</strong>
        </div>
        <button id="rv2-hist-close-view" style="background:#F59E0B;color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;white-space:nowrap">Return to Current Version</button>
      </div>` : ""}

      <!-- Mobile fixed action bar — always visible at bottom of screen -->
      ${isMobile ? `
      <div style="position:fixed;bottom:0;left:0;right:0;z-index:120;background:white;border-top:2px solid #E8DEE8;box-shadow:0 -4px 16px rgba(128,0,128,.1);padding:10px 14px;padding-bottom:max(10px,env(safe-area-inset-bottom))">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
          ${statusDot}
          <span style="font-size:11.5px;font-weight:600;color:${statusColor}">${statusText}</span>
        </div>
        <div style="display:flex;gap:6px">
          <button id="rv2-show-history" style="background:#f3e8ff;border:1px solid #C8A0C8;color:#6b21a8;padding:8px 8px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;flex-shrink:0">📋</button>
          <button class="btn btn-ghost btn-sm" id="rv2-save-draft" style="flex:1;justify-content:center;${Object.keys(_rv2.edits).length === 0 ? 'opacity:0.4;' : ''}">Save Version</button>
          <button class="btn btn-sm" id="rv2-send-revision" style="flex:1;justify-content:center;border:1px solid #EDD08A;color:#92400E;background:white;border-radius:8px;padding:8px 8px;font-size:11.5px;font-weight:600">✕ Reject</button>
          <button id="rv2-sign" class="${canSign?"btn btn-navy":"btn btn-outline"} btn-sm" ${canSign?"":"disabled"} style="flex:1;justify-content:center;display:flex;align-items:center;gap:4px;padding:8px 8px;font-size:12px;${canSign?"background:linear-gradient(135deg,#800080,#A020A0);border-color:transparent;box-shadow:0 4px 14px rgba(128,0,128,.4);":"opacity:0.45;color:var(--ink-4)"}">
            ${!canSign ? iconSVG("lock",11) : ""} Sign
          </button>
        </div>
      </div>` : ""}

      <!-- Version history / compare drawer (fixed overlay) -->
      ${rv2HistoryDrawer()}
    </div>`;
};

// ── DL inline modal (replaces full dl1 screen navigation) ────────────────────

function _rv2ShowDLModal(enc) {
  document.getElementById("rv2-dl-modal")?.remove();
  const hadmId  = enc?.hadm_id || enc?.hadmId;
  if (!hadmId) return;

  const dlRows  = Array.isArray(enc.summary?.gap_rows) ? enc.summary.gap_rows : [];
  const dlCount = enc.summary?.dl_flags || dlRows.length;

  const _tierColor  = { T3: "#DC2626", T2: "#92400E", T1: "#854D0E" };
  const _tierBg     = { T3: "#FEE2E2", T2: "#FEF3C7", T1: "#FEF9C3" };
  const _tierBorder = { T3: "#FCA5A5", T2: "#FCD34D", T1: "#FDE047" };

  const rowsHTML = dlRows.length === 0
    ? `<div style="text-align:center;padding:28px 20px">
        <div style="font-size:32px;margin-bottom:8px">✅</div>
        <div style="font-size:14px;font-weight:700;color:#059669">No flagged sections</div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px">Pass 3 found no issues for this patient.</div>
       </div>`
    : dlRows.map(r => {
        const tc  = _tierColor[r.tier]  || "#374151";
        const bg  = _tierBg[r.tier]     || "#F9FAFB";
        const bor = _tierBorder[r.tier] || "#E5E7EB";
        const iss = Array.isArray(r.issues)
          ? r.issues.map(i => typeof i === "string" ? i : (i.description || "")).filter(Boolean)
          : [];
        const detail = iss.length ? iss.join("; ") : (r.missing || "");
        return `<div style="border:1px solid ${bor};border-radius:8px;padding:10px 14px;margin-bottom:8px;background:${bg}40">
          <div style="display:flex;align-items:center;gap:7px;margin-bottom:${detail?"5px":"0"}">
            <span style="font-size:10px;font-weight:800;background:${tc};color:#fff;padding:2px 8px;border-radius:20px;letter-spacing:.04em;flex-shrink:0">${r.tier||"?"}</span>
            <span style="font-size:12.5px;font-weight:700;color:#111827">${r.title||r.sec||""}</span>
          </div>
          ${detail ? `<div style="font-size:12px;color:#374151;line-height:1.5;padding-left:2px">${detail}</div>` : ""}
        </div>`;
      }).join("");

  const overlay = document.createElement("div");
  overlay.id = "rv2-dl-modal";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;font-family:inherit";

  overlay.innerHTML = `
    <div style="background:#fff;border-radius:14px;width:100%;max-width:480px;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.28)">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e5e7eb;position:sticky;top:0;background:#fff;border-radius:14px 14px 0 0;z-index:1">
        <div>
          <div style="font-size:10px;font-weight:800;color:#1e40af;text-transform:uppercase;letter-spacing:.1em">Flagged Sections · Pass 3</div>
          <div style="font-size:13px;font-weight:700;color:#111827;margin-top:2px">${dlCount} section${dlCount!==1?"s":""} flagged · ${fmtPid(hadmId, APP.reviewData?.encounter?.display_id)}</div>
        </div>
        <button id="rv2-dl-modal-close" style="width:28px;height:28px;border:1px solid #e5e7eb;border-radius:8px;background:#f9fafb;cursor:pointer;font-size:17px;color:#6b7280;display:flex;align-items:center;justify-content:center;font-family:inherit;line-height:1">×</button>
      </div>
      <div style="padding:14px 16px">${rowsHTML}</div>
    </div>`;

  document.body.appendChild(overlay);
  overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });
  document.getElementById("rv2-dl-modal-close")?.addEventListener("click", () => overlay.remove());
}

// ── Screen setup (overrides review.js) ───────────────────────────────────────

function rv2Rerender() {
  const el     = document.getElementById("rv2-scroll");
  const top    = el ? el.scrollTop : 0;
  const ctx    = document.getElementById("rv2-ctx-body");
  const ctxTop = ctx ? ctx.scrollTop : 0;
  renderApp();
  const restore = () => {
    const newEl  = document.getElementById("rv2-scroll");
    const newCtx = document.getElementById("rv2-ctx-body");
    if (newEl)  newEl.scrollTop  = top;
    if (newCtx) newCtx.scrollTop = ctxTop;
  };
  restore();                       // immediate
  requestAnimationFrame(restore);  // again after layout settles (prevents jump on edit/table swap)
}

SCREEN_SETUP["review"] = function setupReviewV2() {
  if (_rv2.auditMode) {
    document.getElementById("rv2-back-clinical")?.addEventListener("click", () => {
      _rv2.auditMode = false;
      rv2Rerender();
    });
    if (typeof _rv2OldSetup === "function") _rv2OldSetup();
    return;
  }

  // Step 6: mark re_reviewed_at if doctor is opening this after a rejection
  (function() {
    const rf = APP.rejFlow;
    if (rf?.rejectionLogId && String(rf.hadmId) === String(APP.reviewData?.hadmId)) {
      fetch(`${API_BASE}/api/rejection_logs/${rf.rejectionLogId}`, {
        method: "PATCH", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ re_reviewed_at: new Date().toISOString() }),
      }).catch(() => {});
    }
  })();

  // Load clinical context from stored summary blob only — no re-fetch
  const encId  = APP.reviewData?.encounter?.id;
  const ctxKey = encId || APP.reviewData?.hadmId;
  if (ctxKey && ctxKey !== _rv2.ctxHadmId) {
    _rv2.ctxHadmId      = ctxKey;
    _rv2.clinicalCtx    = APP.reviewData?.encounter?.summary?.clinical_context || null;
    _rv2.ctxLoading     = false;
    _rv2.ctxError       = null;
    // Reset source panel state for new patient
    _rv2.srcTabData           = {};
    _rv2.srcTabLoading        = {};
    _rv2.srcTabError          = {};
    _rv2.srcDisplayData       = null;
    _rv2.srcDispLoading       = false;
    _rv2.activeSectionId      = null;
    _rv2.activeCtxTab         = 'Diagnoses'; // auto-open first tab so "Loading Sources..." shows immediately
    _rv2.resolvedTierSections = new Set();
    // Restore any previously acknowledged tier errors from draft
    const _rts = APP.reviewData?.encounter?.summary?.draft_edits?.resolvedTierSections;
    if (Array.isArray(_rts)) _rts.forEach(id => _rv2.resolvedTierSections.add(id));
    rv2Rerender();
    // Start fetching all tabs in background so they're cached before doctor clicks them.
    // Display tabs (Admissions, Diagnoses, Procedures, Microbiology, Transfers, ICU Stays) share
    // one /display endpoint call — fetching Diagnoses fetches all of them at once.
    rv2FetchTabData('Diagnoses');
    _RV2_CTX_TABS.forEach(t => { if (t.key !== 'Diagnoses') rv2FetchTabData(t.key); });

    // Kick off Pass 1 pre-computation in background so Generate Summary only needs Pass 2
    const _preHadmId = APP.reviewData?.hadmId;
    if (_preHadmId) {
      fetch(`${_API}/api/encounters/${_preHadmId}/precompute`, { method: "POST" }).catch(() => {});
    }
  }

  // Fullscreen handlers — CSS overlay toggle (state-driven, reliable)
  document.getElementById("rv2-summary-fullscreen")?.addEventListener("click", () => {
    _rv2.fullscreen = _rv2.fullscreen === "summary" ? null : "summary";
    rv2Rerender();
  });

  document.getElementById("rv2-source-fullscreen")?.addEventListener("click", () => {
    _rv2.fullscreen = _rv2.fullscreen === "source" ? null : "source";
    rv2Rerender();
  });

  // Mobile tab switcher
  document.getElementById("rv2-mob-summary")?.addEventListener("click", () => {
    _rv2.mobileTab = "summary"; rv2Rerender();
  });
  document.getElementById("rv2-mob-source")?.addEventListener("click", () => {
    _rv2.mobileTab = "source"; rv2Rerender();
  });

  // On mobile: clicking a section header should also switch to source tab after a moment
  if (window.innerWidth < 768) {
    document.querySelectorAll("[data-rv2-section]").forEach(el => {
      const existingClick = el.onclick;
      el.addEventListener("click", () => {
        setTimeout(() => { _rv2.mobileTab = "source"; rv2Rerender(); }, 300);
      });
    });
  }

  // ESC key exits fullscreen
  if (!_rv2._escHandlerBound) {
    _rv2._escHandlerBound = true;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && _rv2.fullscreen) {
        _rv2.fullscreen = null;
        rv2Rerender();
      }
    });
  }

  // Source panel drag-to-resize
  const _rv2ResizeHandle = document.getElementById("rv2-src-resize");
  if (_rv2ResizeHandle) {
    _rv2ResizeHandle.addEventListener("mousedown", e => {
      e.preventDefault();
      const startX = e.clientX;
      const panel  = document.getElementById("rv2-src-panel");
      const startW = panel ? panel.offsetWidth : _rv2.srcPanelWidth;
      function onMove(ev) {
        const newW = Math.max(260, Math.min(750, startW + startX - ev.clientX));
        _rv2.srcPanelWidth = newW;
        if (panel) panel.style.width = newW + "px";
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  // Textarea input handlers — no re-render, just update state var
  document.getElementById("rv2-edit-ta")?.addEventListener("input",     e => { _rv2.editText     = e.target.value; });
  document.getElementById("rv2-comment-ta")?.addEventListener("input",  e => { _rv2.commentText  = e.target.value; });
  document.getElementById("rv2-revision-ta")?.addEventListener("input", e => { _rv2.revisionText = e.target.value; });

  // Tech toggle inside source panel
  document.getElementById("rv2-tech-toggle")?.addEventListener("click", () => {
    _rv2.sourceTechOpen = !_rv2.sourceTechOpen;
    rv2Rerender();
  });

  // Info banner dismiss
  document.getElementById("rv2-banner-close")?.addEventListener("click", () => {
    _rv2.bannerDone = true;
    rv2Rerender();
  });

  // Tier badge click — expand/collapse issues panel for that section
  document.querySelectorAll(".rv2-tier-badge").forEach(el => {
    el.addEventListener("click", e => {
      e.stopPropagation(); // don't also trigger section highlight
      const id = el.dataset.secId;
      _rv2.tierPanelId = _rv2.tierPanelId === id ? null : id;
      rv2Rerender();
    });
  });

  // Tier error resolve/un-resolve buttons
  document.querySelectorAll("[data-resolve-sec]").forEach(el => {
    el.addEventListener("click", e => {
      e.stopPropagation();
      rv2ResolveTierSection(el.dataset.resolveSec);
    });
  });
  document.querySelectorAll("[data-unresolve-sec]").forEach(el => {
    el.addEventListener("click", e => {
      e.stopPropagation();
      rv2UnresolveTierSection(el.dataset.unresolveSec);
    });
  });

  // Source panel tab clicks → set active tab, kick off data fetch
  document.querySelectorAll("[data-rv2-ctx-tab]").forEach(el => {
    el.addEventListener("click", () => {
      const tab = el.dataset.rv2CtxTab;
      _rv2.activeCtxTab = tab;
      rv2Rerender();
      rv2FetchTabData(tab);
    });
  });

  // NABH section header click → switch source tab + highlight matching blocks
  document.querySelectorAll("[data-rv2-section]").forEach(el => {
    el.addEventListener("click", e => {
      e.stopPropagation();
      const id = el.dataset.rv2Section;
      const toggling = _rv2.activeSectionId === id;
      _rv2.activeSectionId = toggling ? null : id;
      const relevantTabs = toggling ? [] : _rv2TabsForSection(id);
      const primary = !toggling ? (_rv2SectionPrimaryTab[id.toUpperCase()] || relevantTabs[0]) : null;
      _rv2.activeCtxTab = primary || _rv2.activeCtxTab || 'Diagnoses';
      rv2Rerender();
      if (_rv2.activeCtxTab) rv2FetchTabData(_rv2.activeCtxTab);
      // Scroll highlighted source into view
      setTimeout(() => {
        const hl = document.getElementById("rv2-src-highlighted");
        if (hl) hl.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 80);
    });
  });

  // Navigation — back to queue + prev/next patient
  document.getElementById("rv2-back")?.addEventListener("click", () => navigate("doctor-dashboard"));

  document.querySelectorAll(".rv2-dl-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const enc = APP.reviewData?.encounter;
      if (enc) _rv2ShowDLModal(enc);
    });
  });

  // Save Version — persist edits + create a version snapshot
  document.getElementById("rv2-save-draft")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const rd  = APP.reviewData;
    const encId = rd?.encounter?.id;
    if (!encId || !rd?.docSections) return;

    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      const editedContent = (typeof buildEditedContent === "function")
        ? buildEditedContent(rd.docSections, _rv2.edits || {}, _rv2.comments || {})
        : rd.content;
      const _u = getUser();
      await updateSummary(encId, {
        content:        editedContent,
        draft_saved_at: new Date().toISOString(),
        draft_edits:    { edits: _rv2.edits || {}, resolved: [..._rv2.resolved], resolvedTierSections: [..._rv2.resolvedTierSections] },
        save_version:   true,
        save_type:      "draft",
        saved_by_name:  _u?.full_name || _u?.name || null,
      });
      // Keep local reviewData in sync so re-entering this session shows edits
      rd.content     = editedContent;
      rd.docSections = rv2ParseSummary(editedContent);
      if (typeof dqInvalidate === "function") dqInvalidate();
      btn.textContent = "Saved ✓";
      setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 2000);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = orig;
      alert("Failed to save version: " + (err?.message || err));
    }
  });

  // ── Version History ─────────────────────────────────────────────────────────

  // Open history drawer
  document.getElementById("rv2-show-history")?.addEventListener("click", async () => {
    _rv2.historyOpen     = true;
    _rv2.compareMode     = false;
    _rv2.compareSelA     = null;
    _rv2.compareSelB     = null;
    _rv2.historyVersions = null;
    _rv2.historyError    = null;
    _rv2.historyLoading  = true;
    rv2Rerender();
    const encId = APP.reviewData?.encounter?.id;
    try {
      const versions = await fetchSummaryVersions(encId);
      _rv2.historyVersions = Array.isArray(versions) ? versions : [];
    } catch (e) {
      _rv2.historyError = e.message || "Unknown error";
    }
    _rv2.historyLoading = false;
    rv2Rerender();
  });

  // Close drawer (close button or backdrop)
  document.getElementById("rv2-hist-close")?.addEventListener("click", () => {
    _rv2.historyOpen  = false;
    _rv2.compareMode  = false;
    rv2Rerender();
  });
  document.getElementById("rv2-hist-overlay")?.addEventListener("click", e => {
    if (e.target.id === "rv2-hist-overlay") { _rv2.historyOpen = false; _rv2.compareMode = false; rv2Rerender(); }
  });

  // Close read-only banner — return to live version
  document.getElementById("rv2-hist-close-view")?.addEventListener("click", () => {
    _rv2.viewingVersionId = null;
    _rv2.viewingVersion   = null;
    rv2Rerender();
  });

  // Retry loading history
  document.getElementById("rv2-hist-retry")?.addEventListener("click", async () => {
    _rv2.historyError   = null;
    _rv2.historyLoading = true;
    rv2Rerender();
    const encId = APP.reviewData?.encounter?.id;
    try {
      const versions = await fetchSummaryVersions(encId);
      _rv2.historyVersions = Array.isArray(versions) ? versions : [];
    } catch (e) {
      _rv2.historyError = e.message || "Unknown error";
    }
    _rv2.historyLoading = false;
    rv2Rerender();
  });

  // Back from compare diff to version list
  document.getElementById("rv2-hist-back")?.addEventListener("click", () => {
    _rv2.compareMode  = false;
    _rv2.compareSelA  = null;
    _rv2.compareSelB  = null;
    _rv2.compareDataA = null;
    _rv2.compareDataB = null;
    _rv2.historyOpen  = true;
    rv2Rerender();
  });

  // View a specific version (read-only)
  document.querySelectorAll(".rv2h-view-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const vid = btn.dataset.vid;
      _rv2.historyLoading = true;
      rv2Rerender();
      const v = await fetchSummaryVersion(vid);
      _rv2.viewingVersionId = vid;
      _rv2.viewingVersion   = v;
      _rv2.historyLoading   = false;
      _rv2.historyOpen      = false;
      rv2Rerender();
    });
  });

  // Compare checkbox selection (max 2)
  document.querySelectorAll(".rv2h-compare-cb").forEach(cb => {
    cb.addEventListener("change", () => {
      const vid = cb.dataset.vid;
      if (cb.checked) {
        if      (!_rv2.compareSelA) _rv2.compareSelA = vid;
        else if (!_rv2.compareSelB) _rv2.compareSelB = vid;
        else { cb.checked = false; return; }
      } else {
        if (_rv2.compareSelA === vid) _rv2.compareSelA = null;
        if (_rv2.compareSelB === vid) _rv2.compareSelB = null;
      }
      rv2Rerender();
    });
  });

  // Compare CTA — load both versions and show diff
  document.getElementById("rv2h-compare-btn")?.addEventListener("click", async () => {
    if (!_rv2.compareSelA || !_rv2.compareSelB) return;
    _rv2.compareMode    = true;
    _rv2.historyOpen    = false;
    _rv2.comparePending = true;
    _rv2.compareDataA   = null;
    _rv2.compareDataB   = null;
    rv2Rerender();
    const [vA, vB] = await Promise.all([
      fetchSummaryVersion(_rv2.compareSelA),
      fetchSummaryVersion(_rv2.compareSelB),
    ]);
    _rv2.compareDataA   = vA;
    _rv2.compareDataB   = vB;
    _rv2.comparePending = false;
    rv2Rerender();
  });

  // Send back for revision — open modal
  document.getElementById("rv2-send-revision")?.addEventListener("click", () => {
    _rv2.revisionModalOpen = true;
    _rv2.revisionModalText = "";
    rv2Rerender();
    setTimeout(() => document.getElementById("rv2-rev-modal-ta")?.focus(), 60);
  });

  // Revision modal cancel
  document.getElementById("rv2-rev-modal-cancel")?.addEventListener("click", () => {
    _rv2.revisionModalOpen = false;
    rv2Rerender();
  });

  // Click outside modal overlay to close
  document.getElementById("rv2-revision-overlay")?.addEventListener("click", e => {
    if (e.target === e.currentTarget) { _rv2.revisionModalOpen = false; rv2Rerender(); }
  });

  // Revision modal textarea
  document.getElementById("rv2-rev-modal-ta")?.addEventListener("input", e => {
    _rv2.revisionModalText = e.target.value;
  });

  // Revision modal confirm → API → navigate
  document.getElementById("rv2-rev-modal-confirm")?.addEventListener("click", async () => {
    const reason = _rv2.revisionModalText.trim();
    if (!reason) { document.getElementById("rv2-rev-modal-ta")?.focus(); return; }
    const btn = document.getElementById("rv2-rev-modal-confirm");
    if (btn) { btn.disabled = true; btn.textContent = "Sending…"; }
    try {
      const hadmId = APP.reviewData?.hadmId;
      if (!hadmId) throw new Error("No encounter ID available.");
      // Use the dedicated /reject endpoint (handles status update + rejection_log creation)
      const rejRes = await fetch(`${API_BASE}/api/encounters/${hadmId}/reject`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          reason,
          prev_t1_count: 0,
          rejected_by:   APP.currentUser?.id || null,
        }),
      }).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
      // Log as Tier 3, check pilot pause gate
      apiLogError({
        hadm_id:         String(hadmId),
        summary_version: String(APP.reviewData?.encounter?.version || "1"),
        error_tier:      3,
        error_category:  "hallucination",
        ai_output:       reason.slice(0, 1000),
        correct_value:   null,
        source_present:  false,
        attending_id:    APP.currentUser?.id || null,
      }).then(res => {
        if (res && res.gate_status === 'pause') {
          _rv2.pilotPauseBanner = { rate_pct: res.tier3_rate_pct };
        }
      });
      _rv2.revisionModalOpen = false;
      // Launch 7-step rejection flow
      APP.rejFlow = {
        step:            2,
        hadmId:          String(hadmId),
        patName:         (APP.reviewData?.patient || {}).full_name || "Patient",
        reason,
        rejectionReason: reason,
        rejectedAt:      new Date().toISOString(),
        regenerating:    false,
        regeneratedAt:   null,
        rejectionLogId:  rejRes.rejection_log_id || null,
        notifiedAt:      null,
      };
      try { localStorage.setItem('rejFlow_active', JSON.stringify(APP.rejFlow)); } catch(e) {}
      // Show brief toast then go back to queue — no wizard screen
      const _toast = document.createElement('div');
      _toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1A001A;color:#F5E0F5;padding:12px 22px;border-radius:8px;font-size:13px;font-weight:600;z-index:99999;box-shadow:0 4px 16px rgba(0,0,0,.4)';
      _toast.textContent = '✓ Summary rejected and sent back for revision';
      document.body.appendChild(_toast);
      setTimeout(() => { _toast.remove(); navigate("doctor-dashboard"); }, 1800);
    } catch (err) {
      if (btn) { btn.disabled = false; btn.innerHTML = `${iconSVG("alert",13)} Submit Rejection`; }
      alert("Failed: " + err.message);
    }
  });

  // ── S4d — LLM Revision (AI Revise) handlers ──────────────────────────────────
  const rd4d      = APP.reviewData;
  const docSects4 = rd4d?.docSections?.length ? rd4d.docSections : rv2BuildDocSections(APP.claims || CLAIMS_INITIAL);
  const allP4d    = docSects4.reduce((a, s) => a.concat(s.passages.map(p => Object.assign({}, p, { sectionId: s.id }))), []);

  // AI Revise button — start LLM revision for this passage
  document.querySelectorAll("[data-airevise-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.aireviseId;
      // If already showing, toggle it off
      if (_rv2.llmRevisions[id]) {
        delete _rv2.llmRevisions[id];
        rv2Rerender();
        return;
      }
      const passage = allP4d.find(p => p.id === id);
      const text = (_rv2.edits[id] !== undefined ? _rv2.edits[id] : passage?.text) || "";
      const secId = passage?.sectionId || "";
      _rv2.llmRevisions[id] = { status: "processing" };
      rv2Rerender();
      setTimeout(() => {
        _rv2.llmRevisions[id] = rv2MockRevision(id, text, secId);
        rv2Rerender();
      }, 1400);
    });
  });

  // Accept LLM revision / AI Fix review — apply revised text as an edit
  document.querySelectorAll("[data-accept-llmrev-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id  = btn.dataset.acceptLlmrevId;
      const rev = _rv2.llmRevisions[id];
      if (rev?.revised) {
        _rv2.edits[id] = rev.revised;
        // Sync back to claims so section text reflects the accepted content
        const claims = APP.claims || CLAIMS_INITIAL;
        const c = claims.find(x => x.id === id);
        if (c) { c.text = rev.revised; c.status = "v"; c.edited = true; }
        _rv2.resolved.add(id);
      }
      delete _rv2.llmRevisions[id];
      _rv2.selectedId = null;
      rv2Rerender();
    });
  });

  // Reject LLM revision — dismiss panel
  document.querySelectorAll("[data-reject-llmrev-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      delete _rv2.llmRevisions[btn.dataset.rejectLlmrevId];
      rv2Rerender();
    });
  });

  // Request Different Revision — re-enter processing state with a fresh generation
  document.querySelectorAll("[data-rerequest-llmrev-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.rerequestLlmrevId;
      const passage = allP4d.find(p => p.id === id);
      const text    = (_rv2.edits[id] !== undefined ? _rv2.edits[id] : passage?.text) || "";
      const secId   = passage?.sectionId || "";
      _rv2.llmRevisions[id] = { status: "processing" };
      rv2Rerender();
      setTimeout(() => {
        _rv2.llmRevisions[id] = rv2MockRevision(id, text, secId);
        rv2Rerender();
      }, 1200);
    });
  });

  // Diff mode toggle
  document.querySelectorAll("[data-diffmode-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.diffmodeId;
      if (_rv2.llmRevisions[id]) {
        _rv2.llmRevisions[id].diffMode = !_rv2.llmRevisions[id].diffMode;
        rv2Rerender();
      }
    });
  });

  // ── Audit mode toggle ──────────────────────────────────────────────────────
  // Audit mode toggle
  document.getElementById("rv2-audit-toggle")?.addEventListener("click", () => {
    _rv2.auditMode = true;
    rv2Rerender();
  });

  // S15 patient acknowledgement — mark all S15 passages resolved so sign-off gate opens
  document.getElementById("rv2-s15-ack-btn")?.addEventListener("click", () => {
    const rd2 = APP.reviewData;
    const sects2 = rd2?.docSections?.length ? rd2.docSections : rv2BuildDocSections(APP.claims || CLAIMS_INITIAL);
    const s15s = sects2.find(s => s.id === "s15");
    s15s?.passages.forEach(p => _rv2.resolved.add(p.id));
    rv2Rerender();
  });

  // Approve & Sign — navigate to full signoff screen
  document.getElementById("rv2-sign")?.addEventListener("click", () => {
    if (typeof _sgInit === "function") _sgInit();
    navigate("signoff");
  });

  // ── E-sign modal wiring ───────────────────────────────────────────────────────
  if (_rv2.esignOpen) {
    const _esignClose = () => { _rv2.esignOpen = false; rv2Rerender(); };
    document.getElementById("rv2-esign-close")?.addEventListener("click",  _esignClose);
    document.getElementById("rv2-esign-cancel")?.addEventListener("click", _esignClose);
    document.getElementById("rv2-esign-overlay")?.addEventListener("click", e => {
      if (e.target.id === "rv2-esign-overlay") _esignClose();
    });

    // Canvas draw pad
    const _canvas  = document.getElementById("rv2-esign-canvas");
    const _confirm = document.getElementById("rv2-esign-confirm");
    const _hint    = document.getElementById("rv2-esign-hint");
    let _drawing = false, _hasStrokes = false;
    if (_canvas) {
      const ctx = _canvas.getContext("2d");
      ctx.strokeStyle = "#111827";
      ctx.lineWidth   = 2.2;
      ctx.lineCap     = "round";
      ctx.lineJoin    = "round";

      const _pt = ev => {
        const r = _canvas.getBoundingClientRect();
        const sx = _canvas.width  / r.width;
        const sy = _canvas.height / r.height;
        const src = ev.touches ? ev.touches[0] : ev;
        return [(src.clientX - r.left) * sx, (src.clientY - r.top) * sy];
      };
      const _start = ev => {
        ev.preventDefault();
        _drawing = true;
        const [x, y] = _pt(ev);
        ctx.beginPath(); ctx.moveTo(x, y);
      };
      const _move = ev => {
        if (!_drawing) return;
        ev.preventDefault();
        const [x, y] = _pt(ev);
        ctx.lineTo(x, y); ctx.stroke();
        if (!_hasStrokes) {
          _hasStrokes = true;
          if (_hint) _hint.style.display = "none";
          if (_confirm) { _confirm.disabled = false; _confirm.style.opacity = "1"; }
        }
      };
      const _end = () => { _drawing = false; };

      _canvas.addEventListener("mousedown",  _start);
      _canvas.addEventListener("mousemove",  _move);
      _canvas.addEventListener("mouseup",    _end);
      _canvas.addEventListener("mouseleave", _end);
      _canvas.addEventListener("touchstart", _start, { passive: false });
      _canvas.addEventListener("touchmove",  _move,  { passive: false });
      _canvas.addEventListener("touchend",   _end);
    }

    document.getElementById("rv2-esign-clear")?.addEventListener("click", () => {
      if (!_canvas) return;
      const ctx = _canvas.getContext("2d");
      ctx.clearRect(0, 0, _canvas.width, _canvas.height);
      _hasStrokes = false;
      if (_hint)    _hint.style.display = "";
      if (_confirm) { _confirm.disabled = true; _confirm.style.opacity = ".45"; }
    });

    // Confirm & Sign — run the actual signing flow
    _confirm?.addEventListener("click", async () => {
      if (!_hasStrokes) return;
      _confirm.disabled = true;
      _confirm.textContent = "Signing…";
      try {
        const rd    = APP.reviewData || {};
        const encId = rd?.encounter?.id;
        if (!encId) throw new Error("No encounter ID");
        const _u     = getUser();
        const now    = new Date().toISOString();
        const newVer = (rd.encounter?.version ?? 1) + 1;
        const mci    = document.getElementById("rv2-esign-mci")?.value.trim()
                       || _u?.mci_number || _u?.registration_number || null;
        const sigDataUrl = _canvas ? _canvas.toDataURL("image/png") : null;
        const edited = (typeof buildEditedContent === "function")
          ? buildEditedContent(rd.docSections, _rv2.edits || {}, _rv2.comments || {})
          : (rd.content || "");
        // 1. Mark encounter Signed Off
        await updateEncounter(encId, { status: "Signed Off", version: newVer });
        // 2. Persist signed summary + immutable version snapshot
        const summaryResult = await updateSummary(encId, {
          signed_at:      now,
          signed_by:      _u?.id || null,
          signature_data: JSON.stringify({ mci, sig_png: sigDataUrl }),
          content:        edited,
          save_version:   true,
          save_type:      "signed",
          saved_by_name:  _u?.full_name || _u?.name || null,
        });
        // 3. If re-sign after rejection, mark the rejection log as signed
        const _rf = APP.rejFlow;
        if (_rf?.rejectionLogId && String(_rf.hadmId) === String(rd?.hadmId)) {
          fetch(`${API_BASE}/api/rejection_logs/${_rf.rejectionLogId}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ signed_at: now }),
          }).catch(() => {});
          try { localStorage.removeItem("rejFlow_active"); } catch(_) {}
          APP.rejFlow = null;
        }
        // 4. Invalidate doctor queue cache
        if (typeof dqInvalidate === "function") dqInvalidate();
        // 5. Stash sign-off data for the signed page
        APP.reviewData.signedAt     = now;
        APP.reviewData.signedMci    = mci;
        APP.reviewData.finalContent = edited;
        APP.reviewData.docVersion   = summaryResult?.doc_version ?? newVer;
        APP.reviewData._contentHash = null;
        APP.amendment = null;
        _rv2.esignOpen = false;
        navigate("signed");
      } catch (err) {
        _confirm.disabled = false;
        _confirm.textContent = "Confirm & Sign";
        _confirm.style.opacity = "1";
        alert("Sign-off failed: " + (err?.message || err));
      }
    });
  }

  // Cancel edit
  document.getElementById("rv2-cancel-edit")?.addEventListener("click", () => {
    _rv2.editingId       = null;
    _rv2.editText        = "";
    _rv2.s6EditItems     = null;
    _rv2.s6EditPassageId = null;
    rv2Rerender();
  });

  // AI Fix from inside table editor — close table, open AI fix panel for same passage
  document.querySelectorAll("[data-table-aifix-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.tableAifixId;
      _rv2.editingId       = null;
      _rv2.editText        = "";
      _rv2.s6EditItems     = null;
      _rv2.s6EditPassageId = null;
      _rv2.aifixId         = id;
      _rv2.aifixText       = "";
      _rv2.selectedId      = id;
      rv2Rerender();
    });
  });

  // S6 inline table — delete row
  document.querySelectorAll(".rv2-s6-del").forEach(btn => {
    btn.addEventListener("click", () => {
      btn.closest("tr")?.remove();
    });
  });

  // S6 inline table — add row
  document.querySelectorAll(".rv2-s6-add").forEach(btn => {
    btn.addEventListener("click", () => {
      const grp = btn.dataset.group;
      const inp = "width:100%;border:1px solid #E2E8F0;border-radius:4px;padding:4px 8px;font-size:12.5px;color:#1E293B;font-family:inherit;outline:none;background:white;box-sizing:border-box";
      const tr = document.createElement("tr");
      tr.className = "rv2-s6-row";
      tr.dataset.group = grp;
      tr.dataset.idx = "new";
      tr.innerHTML = `
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9"><input class="rv2-s6-name" type="text" placeholder="Test name" style="${inp}"/></td>
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9"><input class="rv2-s6-val" type="text" placeholder="Value + unit" style="${inp}"/></td>
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9;text-align:center">
          <label style="display:flex;align-items:center;gap:4px;cursor:pointer;justify-content:center">
            <input class="rv2-s6-abn" type="checkbox" style="accent-color:#DC2626;width:13px;height:13px"/>
            <span style="font-size:11px;color:#94A3B8">Normal</span>
          </label>
        </td>
        <td style="padding:5px 8px;border-bottom:1px solid #F1F5F9;text-align:center">
          <button style="border:none;background:none;color:#CBD5E1;cursor:pointer;font-size:17px;line-height:1;padding:0" onclick="this.closest('tr').remove()">×</button>
        </td>`;
      // Add checkbox label toggle
      tr.querySelector(".rv2-s6-abn").addEventListener("change", function() {
        this.closest("label").querySelector("span").textContent = this.checked ? "Abnormal" : "Normal";
        this.closest("label").querySelector("span").style.color = this.checked ? "#DC2626" : "#94A3B8";
      });
      btn.closest("tr").insertAdjacentElement("beforebegin", tr);
      tr.querySelector(".rv2-s6-name").focus();
    });
  });

  // S6 inline — toggle abnormal label color on change
  document.querySelectorAll(".rv2-s6-abn").forEach(cb => {
    cb.addEventListener("change", function() {
      const lbl = this.closest("label")?.querySelector(".rv2-s6-abn-lbl");
      if (lbl) { lbl.textContent = this.checked ? "Abnormal" : "Normal"; lbl.style.color = this.checked ? "#DC2626" : "#94A3B8"; }
    });
  });

  // Save edit
  document.querySelectorAll("[data-save-edit-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const pid = btn.dataset.saveEditId;
      // S6 inline table: collect from input fields per row
      if (_rv2.s6EditPassageId === pid && _rv2.s6EditItems) {
        const updated = {};
        document.querySelectorAll("#rv2-s6-tbody .rv2-s6-row").forEach(row => {
          const grp = row.dataset.group;
          if (!updated[grp]) updated[grp] = [];
          const name = row.querySelector(".rv2-s6-name")?.value.trim() || "";
          const val  = row.querySelector(".rv2-s6-val")?.value.trim()  || "";
          const abn  = row.querySelector(".rv2-s6-abn")?.checked       || false;
          if (name || val) {
            updated[grp].push(`${name}${val ? " " + val : ""}${abn ? " (abnormal)" : ""}`);
          }
        });
        _rv2.editText = Object.entries(updated)
          .filter(([, items]) => items.length > 0)
          .map(([grp, items]) => `*${grp}*: ${items.join("; ")}`)
          .join(". ") + ".";
        _rv2.s6EditItems = null; _rv2.s6EditPassageId = null;
      }
      const origText = _rv2.editOrigText || "";
      const newText  = _rv2.editText;
      const tier     = _rv2.editTier || 1;
      _rv2.edits[pid] = newText;
      const claims = APP.claims || CLAIMS_INITIAL;
      const c      = claims.find(x => x.id === pid);
      if (c) { c.text = newText; c.status = "v"; c.edited = true; }
      const docSects = rv2BuildDocSections(claims);
      const allP     = rv2AllPassages(docSects);
      const p        = allP.find(x => x.id === pid);
      if (p && (p.support==="conflict" || p.support==="uncertain")) _rv2.resolved.add(pid);
      _rv2.editingId   = null;
      _rv2.editText    = "";
      _rv2.editOrigText= "";
      rv2Rerender();
      // Log to 3-tier error framework (fire-and-forget)
      const rd = APP.reviewData;
      const sectionId = pid.split("-")[1] || null;   // "p-s11-0" → "s11"
      const category  = sectionId === "s11" ? "medication_dose"
                      : (sectionId === "s8" || sectionId === "s13") ? "diagnosis"
                      : "formatting";
      apiLogError({
        hadm_id:         String(rd?.hadmId || ""),
        summary_version: String(APP.reviewData?.encounter?.version || "1"),
        nabh_section:    sectionId,
        error_tier:      tier,
        ai_output:       origText.slice(0, 1000),
        correct_value:   newText.slice(0, 1000),
        error_category:  category,
        source_present:  p ? p.support !== "conflict" : null,
        attending_id:    APP.currentUser?.id || null,
      });
    });
  });

  // Tier selector buttons (T1 / T2) inside edit UI
  document.querySelectorAll(".rv2-tier-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      _rv2.editTier = parseInt(btn.dataset.tier, 10);
      rv2Rerender();
      setTimeout(() => {
        const ta = document.getElementById("rv2-edit-ta");
        if (ta) { ta.focus(); const l = ta.value.length; ta.setSelectionRange(l, l); }
      }, 30);
    });
  });

  // Passage select (click text) — also highlights source
  document.querySelectorAll("[data-select-id]").forEach(el => {
    el.addEventListener("click", () => {
      if (_rv2.editingId) return;
      const id        = el.dataset.selectId;
      const sectId    = el.dataset.passageSection;
      const selecting = _rv2.selectedId !== id;
      _rv2.selectedId = selecting ? id : null;
      _rv2.sourceId   = null;
      _rv2.revisionId = null;
      if (selecting && sectId) _rv2.activeSectionId = sectId;
      rv2Rerender();
      if (selecting) {
        setTimeout(() => {
          const hl = document.getElementById("rv2-src-highlighted");
          if (hl) hl.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 80);
      }
    });
  });

  // Edit button (toolbar)
  document.querySelectorAll("[data-edit-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id       = btn.dataset.editId;
      const sectId   = btn.dataset.editSection;
      const rd       = APP.reviewData;
      const docSects = rd?.docSections?.length ? rd.docSections : rv2BuildDocSections(APP.claims || CLAIMS_INITIAL);
      const allP     = rv2AllPassages(docSects);
      const p        = allP.find(x => x.id === id);
      const text     = _rv2.edits[id] !== undefined ? _rv2.edits[id] : (p ? p.text : "");
      _rv2.editingId   = id;
      _rv2.editText    = text;
      _rv2.editOrigText= p ? p.text : text;   // capture original for error log
      _rv2.editTier    = sectId === "s11" ? 2 : 1;  // s11 = medications → T2 default
      _rv2.selectedId  = null;
      if (sectId) _rv2.activeSectionId = sectId;
      // S6: parse into groups for inline table editing
      if (sectId === 's6') {
        let parsed = rv2ParseLabGroups(text);
        // If AI-fix changed the text into an unparseable format, fall back to original
        if (!parsed && p && p.text && p.text !== text) parsed = rv2ParseLabGroups(p.text);
        _rv2.s6EditItems     = parsed || null;
        _rv2.s6EditPassageId = parsed ? id : null;
      } else {
        _rv2.s6EditItems = null; _rv2.s6EditPassageId = null;
      }
      rv2Rerender();
      setTimeout(() => {
        const el = document.getElementById("rv2-edit-ta");
        if (el) {
          // "nearest" only scrolls if the box is off-screen — prevents the jarring
          // downward jump when editing a section that's already visible.
          el.scrollIntoView({ behavior: "smooth", block: "nearest" });
          el.focus({ preventScroll: true });
        }
      }, 60);
    });
  });

  // AI fix — open/close panel
  document.querySelectorAll("[data-aifix-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.aifixId;
      _rv2.aifixId    = _rv2.aifixId === id ? null : id;
      _rv2.aifixText  = "";
      _rv2.aifixError = null;
      _rv2.selectedId = null;
      _rv2.sourceId   = null;
      _rv2.revisionId = null;
      rv2Rerender();
    });
  });

  // AI fix textarea input
  document.getElementById("rv2-aifix-ta")?.addEventListener("input", e => {
    _rv2.aifixText = e.target.value;
  });

  // ── Mic button — Web Speech API ───────────────────────────────────────────
  document.getElementById("rv2-mic-btn")?.addEventListener("click", () => {
    if (_rv2.aifixRecording) {
      // Stop recording
      _rv2._speechRecog?.stop();
      return;
    }

    // Browsers block mic on non-HTTPS non-localhost
    const isSecure = location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1";
    if (!isSecure) {
      _rv2.aifixError = "Microphone requires HTTPS. Open the app via https:// or on localhost to use voice input.";
      rv2Rerender();
      return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      _rv2.aifixError = "Speech recognition not supported in this browser — use Chrome or Edge.";
      rv2Rerender();
      return;
    }

    _rv2.aifixError = null;
    const recog = new SR();
    recog.continuous      = true;
    recog.interimResults  = true;
    recog.lang            = "en-US";
    _rv2._speechRecog     = recog;
    _rv2.aifixRecording   = true;
    rv2Rerender();

    // Accumulator — grows as finals come in, survives auto-restarts on silence
    let accumulated = _rv2.aifixText;
    let lastInterimText = "";

    recog.onresult = (event) => {
      let allText = ""; // all results (final + interim combined in order)
      let newFinal = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript.trim();
        if (t) {
          allText += (allText ? " " : "") + t;
          if (event.results[i].isFinal) {
            newFinal += (newFinal ? " " : "") + t;
          }
        }
      }

      // Add only new final words to accumulated (don't re-add finals)
      if (newFinal) {
        accumulated += (accumulated && !accumulated.endsWith(" ") ? " " : "") + newFinal;
        _rv2.aifixText = accumulated;
        lastInterimText = ""; // Clear interim once finals are committed
      }

      // Compute interim text from current event's non-final results
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript.trim();
        if (t && !event.results[i].isFinal) {
          interim += (interim ? " " : "") + t;
        }
      }
      if (interim) lastInterimText = interim; // Remember interim for restart

      // Update textarea live without full re-render (avoids losing focus/cursor)
      const ta = document.getElementById("rv2-aifix-ta");
      if (ta) {
        const display = accumulated && lastInterimText ? accumulated + " " + lastInterimText : (accumulated || lastInterimText || "");
        ta.value = display;
      }
    };

    recog.onerror = (e) => {
      if (e.error === "no-speech") return; // silence — onend will auto-restart
      console.warn("Speech error:", e.error);
      _rv2.aifixRecording = false;
      _rv2._speechRecog   = null;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        _rv2.aifixError = "Microphone access denied. Allow mic permission in browser settings, or use HTTPS.";
      } else if (e.error === "network") {
        _rv2.aifixError = "Network error — speech service unavailable. Check your connection.";
      } else {
        _rv2.aifixError = `Speech error: ${e.error}. Try again.`;
      }
      rv2Rerender();
    };

    recog.onend = () => {
      // If user hasn't clicked Stop, browser ended due to silence — restart seamlessly
      if (_rv2.aifixRecording && _rv2._speechRecog === recog) {
        try { recog.start(); } catch (_) {
          _rv2.aifixRecording = false;
          _rv2._speechRecog   = null;
          rv2Rerender();
        }
        return;
      }
      _rv2.aifixRecording = false;
      _rv2._speechRecog   = null;
      rv2Rerender();
    };

    recog.start();
  });

  // Cancel AI fix
  document.querySelectorAll("[data-cancel-aifix-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      _rv2._speechRecog?.stop();
      _rv2.aifixRecording = false;
      _rv2._speechRecog   = null;
      _rv2.aifixId      = null;
      _rv2.aifixText    = "";
      _rv2.aifixLoading = false;
      rv2Rerender();
    });
  });

  // Submit AI fix → call backend → replace section content
  document.querySelectorAll("[data-submit-aifix-id]").forEach(btn => {
    btn.addEventListener("click", async () => {
      // Stop recording if active
      if (_rv2.aifixRecording) {
        _rv2._speechRecog?.stop();
        _rv2.aifixRecording = false;
        _rv2._speechRecog = null;
        rv2Rerender();
      }

      const passageId = btn.dataset.submitAifixId;
      const feedback  = _rv2.aifixText.trim();
      if (!feedback) return;
      const hadmId = APP.reviewData?.hadmId;
      if (!hadmId) { alert("No HADM ID — cannot call AI."); return; }

      // Find which section this passage belongs to
      const rd       = APP.reviewData;
      const docSects = rd?.docSections?.length ? rd.docSections : rv2BuildDocSections(APP.claims || CLAIMS_INITIAL);
      let sectionId = "", sectionLabel = "", currentText = "";
      for (const sect of docSects) {
        const p = sect.passages.find(x => x.id === passageId);
        if (p) {
          sectionId    = sect.id;
          sectionLabel = sect.nabhLabel || sect.title;
          currentText  = _rv2.edits[passageId] !== undefined ? _rv2.edits[passageId] : p.text;
          break;
        }
      }

      _rv2.aifixLoading = true;
      rv2Rerender();

      try {
        const res = await apiRegenerateSection(hadmId, sectionId, sectionLabel, feedback, currentText);
        // Show the AI-fixed version as a review panel — doctor must Accept or Reject
        const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        _rv2.llmRevisions[passageId] = {
          status:      "ready",
          title:       "✦ AI Fixed Version",
          original:    currentText,
          revised:     res.section_text,
          confidence:  95,
          source:      "AI Fix (source-grounded)",
          sourcePage:  "Section regenerated from original clinical source data",
          sourceQuote: feedback.length > 120 ? feedback.slice(0, 120) + "…" : feedback,
          reasoning:   "AI re-read the original uploaded source documents and regenerated this section using your correction note as guidance. Review the proposed change before accepting.",
          diffMode:    false,
          auditItems:  [
            { icon: "✦", label: "AI Fix requested", time: ts, user: getUser().name, detail: `Feedback: "${feedback.slice(0,80)}${feedback.length>80?'…':''}"` }
          ]
        };
        _rv2.aifixId      = null;
        _rv2.aifixText    = "";
        _rv2.aifixLoading = false;
        _rv2.aifixError   = null;
        _rv2.selectedId   = null;
        rv2Rerender();
      } catch (err) {
        _rv2.aifixLoading = false;
        rv2Rerender();
        alert("AI regeneration failed: " + err.message);
      }
    });
  });

  // Source panel toggle (from toolbar button)
  document.querySelectorAll("[data-source-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.sourceId;
      _rv2.sourceId       = _rv2.sourceId === id ? null : id;
      _rv2.sourceTechOpen = false;
      _rv2.selectedId     = null;
      _rv2.commentingId   = null;
      _rv2.revisionId     = null;
      rv2Rerender();
    });
  });

  // Source panel close (✕ button inside panel)
  document.querySelectorAll("[data-toggle-source-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.toggleSourceId;
      _rv2.sourceId       = _rv2.sourceId === id ? null : id;
      _rv2.sourceTechOpen = false;
      rv2Rerender();
    });
  });

  // Mark as reviewed
  document.querySelectorAll("[data-mark-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id     = btn.dataset.markId;
      const claims = APP.claims || CLAIMS_INITIAL;
      const c      = claims.find(x => x.id === id);
      if (c) { c.status = "v"; c.edited = false; }
      _rv2.resolved.add(id);
      _rv2.selectedId = null;
      rv2Rerender();
    });
  });

  // Revision toggle
  document.querySelectorAll("[data-revision-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.revisionId;
      _rv2.revisionId   = _rv2.revisionId === id ? null : id;
      _rv2.selectedId   = null;
      _rv2.commentingId = null;
      _rv2.sourceId     = null;
      rv2Rerender();
    });
  });

  // Cancel revision
  document.querySelectorAll("[data-cancel-revision-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      _rv2.revisionId   = null;
      _rv2.revisionText = "";
      rv2Rerender();
    });
  });

  // Submit revision
  document.querySelectorAll("[data-submit-revision-id]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.submitRevisionId;
      if (!_rv2.revisionText.trim()) return;
      _rv2.resolved.add(id);
      _rv2.revisionText = "";
      _rv2.revisionId   = null;
      rv2Rerender();
    });
  });

  // Modal setups
  if (typeof setupClaimEditModal === "function") setupClaimEditModal();
};
