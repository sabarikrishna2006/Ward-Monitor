const fs = require('fs');

const v2Content = fs.readFileSync('e:/IP_EarlyWarning/EWS-CDS/foqal_careos_erd_v2.html', 'utf8');
const execJs = fs.readFileSync('e:/IP_EarlyWarning/EWS-CDS/temp_exec.js', 'utf8');

// I will execute temp_exec to get the tables
const { execSync } = require('child_process');
const tablesOutput = execSync('node temp_exec.js').toString();

const hcTables = tablesOutput.substring(tablesOutput.indexOf('--- HC ---') + 11, tablesOutput.indexOf('--- EWS ---')).trim();
const ewsTables = tablesOutput.substring(tablesOutput.indexOf('--- EWS ---') + 12, tablesOutput.indexOf('--- DAI ---')).trim();
const daiTables = tablesOutput.substring(tablesOutput.indexOf('--- DAI ---') + 12).trim();

// Now add relations. We'll use standard relations for HC since we know them.
const hcRelations = `
    HOSPITALS ||--o{ DEPARTMENTS : "has"
    HOSPITALS ||--o{ WARDS : "has"
    HOSPITALS ||--o{ STAFF : "employs"
    HOSPITALS ||--o{ PATIENTS : "registers"
    HOSPITALS ||--o{ ADMISSIONS : "hosts"
    HOSPITALS ||--o{ COST_LOOKUPS : "defines"
    DEPARTMENTS ||--o{ WARDS : "organises"
    DEPARTMENTS ||--o{ STAFF : "has"
    WARDS ||--o{ BEDS : "contains"
    PATIENTS ||--o{ ADMISSIONS : "admitted via"
    PATIENTS ||--o{ HIS_PATIENT_SYNC : "syncs"
    PATIENTS ||--o{ INSURANCE_POLICIES : "holds"
    STAFF ||--o{ ADMISSIONS : "assigned to treat"
    STAFF ||--o{ NOTIFICATIONS : "receives"
    ADMISSIONS ||--o{ DOCTOR_PATIENT_ASSIGNMENTS : "tracked by"
    ADMISSIONS ||--o{ WARD_TRANSFERS : "logged in ADT"
    ADMISSIONS ||--o{ PRE_AUTH_REQUESTS : "requests"
    ADMISSIONS ||--o{ NOTIFICATIONS : "triggers"
    INSURANCE_POLICIES ||--o{ PRE_AUTH_REQUESTS : "covers"
    STAFF ||--o{ DOCTOR_PATIENT_ASSIGNMENTS : "fulfils role"
    WARDS ||--o{ WARD_TRANSFERS : "from / to"
`;

const ewsRelations = `
    ADMISSIONS ||--o{ VITALS_TIMESERIES : "has"
    ADMISSIONS ||--o{ LAB_EVENTS : "has"
    ADMISSIONS ||--o{ MEDICATIONS : "has"
    ADMISSIONS ||--o{ ESCALATIONS : "has"
    ADMISSIONS ||--o{ EWS_EVENTS : "has"
    ADMISSIONS ||--o{ DCM_ASSESSMENTS : "has"
    ADMISSIONS ||--o{ FLUID_BALANCE : "has"
    ADMISSIONS ||--o{ TRANSFER_REQUESTS : "requests"
    ADMISSIONS ||--o{ DRUG_LAB_FLAGS : "flags"
    DRUG_LAB_RULES ||--o{ DRUG_LAB_FLAGS : "triggers"
    STAFF ||--o{ VITALS_TIMESERIES : "recorded_by"
    STAFF ||--o{ LAB_EVENTS : "recorded_by"
    STAFF ||--o{ MEDICATIONS : "prescribed_by"
    STAFF ||--o{ ESCALATIONS : "escalated_by"
    STAFF ||--o{ DRUG_LAB_FLAGS : "actioned_by"
    STAFF ||--o{ TRANSFER_REQUESTS : "requested_by"
    WARDS ||--o{ TRANSFER_REQUESTS : "from_ward"
    WARDS ||--o{ TRANSFER_REQUESTS : "to_ward"
`;

const daiRelations = `
    ADMISSIONS ||--o| ACTIVE_PATIENTS : "matches"
    ADMISSIONS ||--o{ APP_ENCOUNTERS : "has"
    ADMISSIONS ||--o{ BILLING : "billed via"
    ACTIVE_PATIENTS ||--o{ APP_ENCOUNTERS : "has"
    ACTIVE_PATIENTS ||--o{ APP_UPLOADED_FILES : "has"
    ACTIVE_PATIENTS ||--o{ APP_CLINICAL_ROWS : "has"
    ACTIVE_PATIENTS ||--o| AP_ADMISSIONS : "has"
    ACTIVE_PATIENTS ||--o{ AP_LABEVENTS : "has"
    ACTIVE_PATIENTS ||--o{ AP_CHARTEVENTS : "has"
    ACTIVE_PATIENTS ||--o{ AP_PRESCRIPTIONS : "has"
    ACTIVE_PATIENTS ||--o{ AP_OTHER_x14 : "has"
    APP_ENCOUNTERS ||--o{ APP_SUMMARIES : "generates"
    APP_SUMMARIES ||--o{ DISCHARGE_SECTIONS : "split into"
    APP_SUMMARIES ||--o{ DISCHARGE_AMENDMENTS : "amended by"
    APP_SUMMARIES ||--o{ ERROR_LOG : "monitored by"
    COST_LOOKUPS ||--o{ BILLING : "estimates"
    INSURANCE_POLICIES ||--o{ BILLING : "covers"
    STAFF ||--o{ APP_ENCOUNTERS : "assigned_to"
    STAFF ||--o{ APP_SUMMARIES : "signed_by"
    STAFF ||--o{ DISCHARGE_SECTIONS : "edited_by"
`;

// Now let's extract the header, overview, and footer from v2Content
const beforeHc = v2Content.substring(0, v2Content.indexOf('<!-- ────────────── hospital_core ERD ────────────── -->'));
const footerIndex = v2Content.indexOf('</div><!-- /tw -->');
const afterDai = v2Content.substring(footerIndex);

let finalHtml = beforeHc + 
`<!-- ────────────── hospital_core ERD ────────────── -->
<div class="section page-break">
  <div class="section-hdr h-core">
    <span class="badge b-core">hospital_core</span>
    <h2>Master Data Schema — 15 Tables</h2>
  </div>
  <p class="section-desc">
    New shared schema. Neither the EWS app nor the Discharge AI app owns this — both connect to it as a read layer. The central table is <strong>admissions</strong> whose <code>admission_id</code> UUID is the universal key flowing into all downstream tables. <code>HOSPITALS</code> acts as the top-level tenant anchor for multi-hospital scalability.
  </p>
  <div class="mermaid-wrap">
<pre class="mermaid">
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ccfbf1', 'primaryBorderColor': '#0d9488', 'primaryTextColor': '#0f766e', 'lineColor': '#0d9488', 'secondaryColor': '#f0fdfa', 'tertiaryColor': '#f8fafc', 'background': '#ffffff', 'fontFamily': 'Segoe UI, sans-serif', 'fontSize': '13px', 'attributeBackgroundColorEven': '#f0fdfa', 'attributeBackgroundColorOdd': '#ffffff'}}}%%
${hcTables.replace('erDiagram', 'erDiagram').replace(/\\n/g, '\\n')}
${hcRelations}
</pre>
  </div>
</div>

<!-- ────────────── EWS ERD ────────────── -->
<div class="section page-break">
  <div class="section-hdr h-ews">
    <span class="badge b-ews">ews</span>
    <h2>EWS Schema — Foqal CareOS (10 Tables)</h2>
  </div>
  <p class="section-desc">
    All 10 tables are foreign-keyed to <code>admissions.admission_id</code> (shown as a reference entity from hospital_core). Migration from SQLite is a connection-string change in SQLAlchemy — ORM models stay the same, only schema prefix changes from default to <code>ews.*</code>.
  </p>
  <div class="mermaid-wrap">
<pre class="mermaid">
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#ede9fe', 'primaryBorderColor': '#7c3aed', 'primaryTextColor': '#6d28d9', 'lineColor': '#7c3aed', 'secondaryColor': '#f5f3ff', 'background': '#ffffff', 'fontFamily': 'Segoe UI, sans-serif', 'fontSize': '13px', 'attributeBackgroundColorEven': '#f5f3ff', 'attributeBackgroundColorOdd': '#ffffff'}}}%%
${ewsTables.replace('erDiagram', 'erDiagram')}
    ADMISSIONS {
        UUID admission_id PK "reference"
    }
    STAFF {
        UUID staff_id PK "reference"
    }
    WARDS {
        UUID ward_id PK "reference"
    }
${ewsRelations}
</pre>
  </div>
</div>

<!-- ────────────── DISCHARGE AI ERD ────────────── -->
<div class="section page-break">
  <div class="section-hdr h-dis">
    <span class="badge b-dis">discharge_ai</span>
    <h2>Discharge Summary AI Schema (16 Tables)</h2>
  </div>
  <p class="section-desc">
    Tracks the AI summary generation workflow, error logs, and RAG data pipeline. Foreign keys link back to <code>hospital_core.admissions</code> and <code>hospital_core.staff</code>. Maintains MIMIC-IV compatibility via <code>hadm_id</code>.
  </p>
  <div class="mermaid-wrap">
<pre class="mermaid">
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#dcfce7', 'primaryBorderColor': '#16a34a', 'primaryTextColor': '#15803d', 'lineColor': '#16a34a', 'secondaryColor': '#f0fdf4', 'background': '#ffffff', 'fontFamily': 'Segoe UI, sans-serif', 'fontSize': '13px', 'attributeBackgroundColorEven': '#f0fdf4', 'attributeBackgroundColorOdd': '#ffffff'}}}%%
${daiTables.replace('erDiagram', 'erDiagram')}
    ADMISSIONS {
        UUID admission_id PK "reference"
    }
    STAFF {
        UUID staff_id PK "reference"
    }
    COST_LOOKUPS {
        UUID cost_id PK "reference"
    }
    INSURANCE_POLICIES {
        UUID policy_id PK "reference"
    }
${daiRelations}
</pre>
  </div>
</div>
` + afterDai;

fs.writeFileSync('e:/IP_EarlyWarning/EWS-CDS/foqal_careos_unified_erd_final.html', finalHtml);
console.log("Written unified ERD file.");
