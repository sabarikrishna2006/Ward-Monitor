"""
Generate Architecture + ERD PDFs for Sabari and Ashmit projects.
Run with: C:\Program Files\Python313\python.exe generate_architecture_pdfs.py
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle, Polygon
from reportlab.graphics import renderPDF
from reportlab.platypus.flowables import Flowable
from reportlab.lib.colors import HexColor


# ─── Colour palette ───────────────────────────────────────────────────────────
SABARI_PRIMARY   = HexColor("#2A6F77")   # teal
SABARI_ACCENT    = HexColor("#E0F7FA")   # light teal
ASHMIT_PRIMARY   = HexColor("#6B21A8")   # purple
ASHMIT_ACCENT    = HexColor("#F3E8FF")   # light purple

ENTITY_BG        = HexColor("#EFF6FF")
ENTITY_HEADER    = HexColor("#1D4ED8")
SECTION_BG       = HexColor("#F1F5F9")
TEXT_DARK        = HexColor("#1E293B")
TEXT_MID         = HexColor("#475569")
TABLE_HEADER_BG  = HexColor("#334155")
TABLE_ROW_ALT    = HexColor("#F8FAFC")
GREEN            = HexColor("#16A34A")
ORANGE           = HexColor("#EA580C")
RED              = HexColor("#DC2626")
WARN_BG          = HexColor("#FEF3C7")

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── Custom styles ────────────────────────────────────────────────────────────
def make_styles(primary):
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"],
                             fontSize=22, textColor=primary,
                             spaceAfter=6, spaceBefore=16, leading=26),
        "h2": ParagraphStyle("h2", parent=base["Heading2"],
                             fontSize=15, textColor=primary,
                             spaceAfter=4, spaceBefore=12, leading=18),
        "h3": ParagraphStyle("h3", parent=base["Heading3"],
                             fontSize=11, textColor=TEXT_DARK,
                             spaceAfter=3, spaceBefore=8, leading=14),
        "body": ParagraphStyle("body", parent=base["Normal"],
                               fontSize=9, textColor=TEXT_DARK,
                               spaceAfter=3, leading=13),
        "small": ParagraphStyle("small", parent=base["Normal"],
                                fontSize=8, textColor=TEXT_MID,
                                spaceAfter=2, leading=11),
        "code": ParagraphStyle("code", parent=base["Code"],
                               fontSize=7.5, textColor=TEXT_DARK,
                               fontName="Courier", leading=11),
        "center": ParagraphStyle("center", parent=base["Normal"],
                                 fontSize=10, alignment=TA_CENTER,
                                 textColor=TEXT_DARK, leading=14),
        "bold": ParagraphStyle("bold", parent=base["Normal"],
                               fontSize=9, textColor=TEXT_DARK,
                               fontName="Helvetica-Bold", leading=13),
    }


def header_table(title, subtitle, primary, accent):
    data = [[
        Paragraph(f'<font color="white" size="20"><b>{title}</b></font>',
                  ParagraphStyle("x", alignment=TA_CENTER, leading=24)),
        ""
    ], [
        Paragraph(f'<font color="white" size="10">{subtitle}</font>',
                  ParagraphStyle("x", alignment=TA_CENTER, leading=13)),
        ""
    ]]
    t = Table(data, colWidths=["*", 0])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), primary),
        ("SPAN",       (0, 0), (1, 0)),
        ("SPAN",       (0, 1), (1, 1)),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 20),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 20),
    ]))
    return t


def section_header(text, primary, styles):
    return Table(
        [[Paragraph(f'<b>{text}</b>',
                    ParagraphStyle("sh", fontSize=11, textColor=colors.white,
                                   fontName="Helvetica-Bold", leading=14))]],
        colWidths=["*"],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), primary),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ])
    )


def info_table(rows, primary, col_widths=None):
    if col_widths is None:
        col_widths = [60*mm, "*"]
    t = Table(rows, colWidths=col_widths)
    style = [
        ("BACKGROUND",    (0, 0), (0, -1), HexColor("#E2E8F0")),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(0, len(rows), 2):
        style.append(("BACKGROUND", (1, i), (1, i), TABLE_ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def two_col(left_items, right_items):
    """Two items side-by-side as a 2-column table."""
    max_rows = max(len(left_items), len(right_items))
    while len(left_items) < max_rows: left_items.append(Spacer(1, 1))
    while len(right_items) < max_rows: right_items.append(Spacer(1, 1))
    rows = [[l, r] for l, r in zip(left_items, right_items)]
    t = Table(rows, colWidths=["50%", "50%"])
    t.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
    ]))
    return t


# ─── ERD diagram builder (custom Flowable) ───────────────────────────────────

class ERDiagram(Flowable):
    """Draws an ER diagram from a list of entities and relations."""

    def __init__(self, entities, relations, width=170*mm, scale=1.0, primary=ENTITY_HEADER):
        super().__init__()
        self._entities  = entities    # {name, x, y, fields: [(name, type, pk, fk)]}
        self._relations = relations   # [(from_name, to_name, label, card)]
        self._w         = width
        self._scale     = scale
        self._primary   = primary
        # compute overall height from entity positions
        max_y = max(e["y"] + self._entity_height(e) for e in entities)
        self._h = (max_y + 20) * scale

    def _entity_height(self, e):
        return 20 + len(e["fields"]) * 13 + 4

    def wrap(self, availWidth, availHeight):
        return (self._w, self._h)

    def draw(self):
        from reportlab.graphics import renderPDF as rpdf
        c = self.canv
        s = self._scale
        c.saveState()

        # Draw relations first (behind boxes)
        ent_map = {e["name"]: e for e in self._entities}
        for rel in self._relations:
            fe = ent_map.get(rel["from"])
            te = ent_map.get(rel["to"])
            if not fe or not te:
                continue
            fx = (fe["x"] + 70) * s
            fy = (fe["y"] + self._entity_height(fe) / 2) * s
            tx = (te["x"] + 70) * s
            ty = (te["y"] + self._entity_height(te) / 2) * s
            c.setStrokeColor(HexColor("#94A3B8"))
            c.setLineWidth(0.8)
            c.line(fx, self._h - fy, tx, self._h - ty)
            # cardinality label
            mid_x = (fx + tx) / 2
            mid_y = (fy + ty) / 2
            c.setFillColor(HexColor("#64748B"))
            c.setFont("Helvetica", 6)
            c.drawCentredString(mid_x, self._h - mid_y + 3, rel.get("card", "1:N"))

        # Draw entity boxes
        for e in self._entities:
            x = e["x"] * s
            y = e["y"] * s
            w = 140 * s
            hh = self._entity_height(e) * s
            field_h = 13 * s
            header_h = 20 * s

            # Entity box shadow
            c.setFillColor(HexColor("#CBD5E1"))
            c.rect(x + 2*s, self._h - y - hh - 2*s, w, hh, fill=1, stroke=0)

            # Header
            c.setFillColor(self._primary)
            c.rect(x, self._h - y - header_h, w, header_h, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 8 * s)
            c.drawCentredString(x + w/2, self._h - y - header_h + 5*s, e["name"])

            # Body
            c.setFillColor(ENTITY_BG)
            c.rect(x, self._h - y - hh, w, hh - header_h, fill=1, stroke=0)

            # Fields
            for i, (fname, ftype, is_pk, is_fk) in enumerate(e["fields"]):
                fy_row = self._h - y - header_h - (i + 1) * field_h
                if i % 2 == 0:
                    c.setFillColor(HexColor("#DBEAFE"))
                    c.rect(x, fy_row, w, field_h, fill=1, stroke=0)

                # PK / FK badge
                badge = ""
                badge_col = colors.white
                if is_pk:
                    badge = "PK"
                    badge_col = HexColor("#FEF3C7")
                elif is_fk:
                    badge = "FK"
                    badge_col = HexColor("#D1FAE5")
                if badge:
                    c.setFillColor(badge_col)
                    c.roundRect(x + 2*s, fy_row + 2*s, 14*s, 9*s, 2*s, fill=1, stroke=0)
                    c.setFillColor(HexColor("#374151"))
                    c.setFont("Helvetica-Bold", 5.5 * s)
                    c.drawCentredString(x + 9*s, fy_row + 4*s, badge)

                # Field name
                c.setFillColor(TEXT_DARK)
                c.setFont("Helvetica", 7 * s)
                c.drawString(x + 20*s, fy_row + 4*s, fname[:22])

                # Field type
                c.setFillColor(TEXT_MID)
                c.setFont("Helvetica-Oblique", 6.5 * s)
                c.drawRightString(x + w - 3*s, fy_row + 4*s, ftype)

            # Box border
            c.setStrokeColor(self._primary)
            c.setLineWidth(0.8)
            c.rect(x, self._h - y - hh, w, hh, fill=0, stroke=1)

        c.restoreState()


# ─────────────────────────────────────────────────────────────────────────────
#  SABARI PROJECT PDF
# ─────────────────────────────────────────────────────────────────────────────

def build_sabari_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm
    )
    P = SABARI_PRIMARY
    styles = make_styles(P)
    story = []

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20*mm))
    story.append(header_table(
        "Foqal CareOS — Ward Monitor",
        "Backend Architecture & Entity-Relationship Diagram  |  Sabari Krishna",
        P, SABARI_ACCENT
    ))
    story.append(Spacer(1, 8*mm))

    cover_data = [
        ["Project Name",   "Foqal CareOS — Ward Patient Monitor"],
        ["Developer",      "Sabari Krishna"],
        ["Repository",     "github.com/ashmit-verma24134/Integrated_Hospital  [sabari branch]"],
        ["Backend",        "Python FastAPI (uvicorn) · SQLite · SQLAlchemy ORM"],
        ["Frontend",       "Vanilla JS + Vite SPA (Single-Page Application)"],
        ["Port (dev)",     "8000 (backend)  |  5173 (Vite dev)"],
        ["Port (prod)",    "8003 (all-in-one — backend serves static frontend)"],
        ["Database file",  "backend/data/ward_careos.db  (SQLite)"],
        ["Document Date",  "June 2026"],
    ]
    story.append(info_table(
        [[Paragraph(k, styles["bold"]), Paragraph(v, styles["body"])] for k, v in cover_data],
        P
    ))
    story.append(Spacer(1, 6*mm))

    # ── Executive Summary ─────────────────────────────────────────────────────
    story.append(section_header("1. EXECUTIVE SUMMARY", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Foqal CareOS is a real-time clinical early-warning system designed for Indian hospital "
        "wards. It continuously computes NHS NEWS2 scores for every bedside patient, applies a "
        "YAML-driven Drug-Lab interaction rule engine calibrated to Indian cardiology guidelines "
        "(CSI/CDSCO/ICMR), and presents a role-based dashboard to ward nurses and charge nurses. "
        "The backend is a monolithic Python FastAPI service backed by SQLite; the frontend is a "
        "Vite-bundled SPA served directly from the same process in production.",
        styles["body"]
    ))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "<b>Key clinical capabilities:</b> NEWS2 Scale 1 &amp; 2 (COPD/hypercapnic failure), "
        "13 Drug-Lab interaction rules across cardiology drugs (digoxin, amiodarone, loop diuretics, "
        "ACE inhibitors, beta-blockers, statins), India-calibrated SBP ≥ 220 mmHg hypertensive-crisis "
        "flag, forward-fill vitals trajectory for gapless charting, and a nurse escalation workflow "
        "with acknowledgement/resolution lifecycle.",
        styles["body"]
    ))
    story.append(PageBreak())

    # ── Tech Stack ────────────────────────────────────────────────────────────
    story.append(section_header("2. TECHNOLOGY STACK", P, styles))
    story.append(Spacer(1, 2*mm))

    stack_data = [
        ["Layer",          "Technology",        "Details"],
        ["Frontend",       "Vanilla JS + Vite",  "SPA; index.html + app.js + styles.css; Vite build → dist/"],
        ["API Framework",  "Python FastAPI",     "Auto Swagger docs at /docs; Pydantic request/response schemas"],
        ["ASGI Server",    "Uvicorn",            "Port 8000 (dev) / 8003 (prod); single worker process"],
        ["Database",       "SQLite 3",           "File: backend/data/ward_careos.db; single-file RDBMS"],
        ["ORM",            "SQLAlchemy 2.x",     "Declarative Base; Session-per-request via Depends(get_db)"],
        ["Rule Engine",    "PyYAML + Python",    "rules/drug_lab_rules.yaml → engine/drug_lab.py"],
        ["ETL Pipeline",   "Google BigQuery",    "bigquery_pipeline.py; async; MIMIC-IV → SQLite backfill"],
        ["Auth",           "None (demo)",        "No token auth; role differentiated by frontend only"],
        ["Deployment",     "deploy.sh",          "Bash script; installs deps, builds Vite, runs uvicorn"],
    ]
    t = Table(stack_data, colWidths=[35*mm, 38*mm, "*"])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    # ── Backend Architecture ──────────────────────────────────────────────────
    story.append(section_header("3. BACKEND ARCHITECTURE", P, styles))
    story.append(Spacer(1, 2*mm))

    arch_text = """
<b>3.1 Deployment Architecture</b><br/>
In production, a single uvicorn process runs on port 8003. FastAPI mounts the compiled
frontend (dist/) at the root path via <i>StaticFiles</i>, so the same process serves both
the REST API (<i>/api/*</i>) and the SPA. SQLite lives in backend/data/ward_careos.db,
accessible from the same filesystem.

<br/><br/><b>3.2 Request Lifecycle</b><br/>
Browser → GET/POST /api/* → CORS middleware → FastAPI router → Depends(get_db) opens
SQLAlchemy session → route handler queries/writes DB → NEWS2 engine or Drug-Lab engine
called inline → JSON response → browser renders DOM.

<br/><br/><b>3.3 Startup</b><br/>
On uvicorn startup, <i>@app.on_event("startup")</i> calls <i>init_db()</i> which runs
Base.metadata.create_all() — creating all five SQLite tables if they don't exist.
The demo DB is pre-populated by build_demo_db.py.

<br/><br/><b>3.4 NEWS2 Scoring Engine</b><br/>
<i>calculate_news2(vitals_dict, hypercapnic_failure)</i> is a pure Python function in main.py.
It implements NHS NEWS2 with two scales: Scale 1 (standard) and Scale 2 (SpO₂ scoring for
COPD/hypercapnic patients). SBP ≥ 220 mmHg scores 3 (India calibration per CSI/ICMR guidelines).
Output is {total: int, factors: [{name, score}]}.

<br/><br/><b>3.5 Drug-Lab Rule Engine</b><br/>
engine/drug_lab.py loads rules/drug_lab_rules.yaml at each call (stateless, file-read).
13 rules cover: hyperkalemia with ACE inhibitors, digoxin toxicity with hypokalemia,
amiodarone-warfarin INR interaction, lactic acidosis with metformin + low eGFR, loop diuretic
hypokalemia, statin hepatotoxicity (ALT > 3×ULN), beta-blocker bradycardia, and more.
The DRUG_CLASS_MAP resolves generic drug classes to Indian brand/generic synonyms.

<br/><br/><b>3.6 Forward-Fill Vitals Pipeline</b><br/>
/api/ward-data performs an in-memory forward-fill: it sorts vitals_timeseries by chart_hour
(latest 24 rows) and propagates the most recent non-null value for each vital parameter.
This prevents gaps on the frontend trajectory chart and stabilises NEWS2 calculation
when vitals are recorded at irregular intervals.

<br/><br/><b>3.7 MIMIC-IV ETL (bigquery_pipeline.py)</b><br/>
An asynchronous standalone script that pulls data from Google BigQuery (physionet-data
MIMIC-IV v3.1). It queries admissions, chartevents, labevents, prescriptions, and transfers
then writes them to the local SQLite DB. This is a one-shot population script, not a live
streaming pipeline.
"""
    story.append(Paragraph(arch_text.strip(), styles["body"]))
    story.append(Spacer(1, 4*mm))

    # Architecture flow diagram as a table
    story.append(Paragraph("<b>3.8 Data Flow Diagram</b>", styles["h3"]))
    flow_data = [
        ["Layer",               "Component",             "Direction",  "Notes"],
        ["Browser / Nurse UI",  "Vite SPA (app.js)",     "→  API",     "Fetch /api/ward-data, /api/escalations"],
        ["CORS Middleware",     "FastAPI CORS",           "↕",          "allow_origins=[*] — all origins"],
        ["API Router",          "main.py routes",         "→  Logic",   "9 REST endpoints (GET/POST)"],
        ["NEWS2 Engine",        "calculate_news2()",      "→  Score",   "Called inline per patient in /api/ward-data"],
        ["Drug-Lab Engine",     "engine/drug_lab.py",    "→  Alerts",  "YAML rules; 13 drug-lab interactions"],
        ["ORM Layer",           "SQLAlchemy Session",    "↕  DB",      "Depends(get_db) — per-request session"],
        ["Database",            "SQLite ward_careos.db", "←  Results", "5 tables; 1 file on filesystem"],
        ["ETL (offline)",       "bigquery_pipeline.py",  "→  DB",      "One-shot; BigQuery MIMIC-IV → SQLite"],
    ]
    t2 = Table(flow_data, colWidths=[40*mm, 45*mm, 20*mm, "*"])
    t2.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t2)
    story.append(PageBreak())

    # ── Database Schema ───────────────────────────────────────────────────────
    story.append(section_header("4. DATABASE SCHEMA ANALYSIS", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "<b>Database:</b> SQLite 3 · File: backend/data/ward_careos.db · "
        "ORM: SQLAlchemy declarative (models.py) · Tables created by init_db() on startup",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    tables_info = [
        {
            "name": "patients",
            "purpose": "Master patient registry. One row per admitted patient.",
            "pk": "subject_id (Integer)",
            "fk": "None",
            "fields": [
                ("subject_id",         "Integer",  "PK",  "-",  "Manual sequence (max+1)"),
                ("name",               "String",   "-",   "-",  "Patient full name"),
                ("age",                "Integer",  "-",   "-",  ""),
                ("sex",                "String",   "-",   "-",  "'M' or 'F'"),
                ("ward",               "String",   "-",   "-",  "Default: 'Ward 4B'"),
                ("room",               "String",   "-",   "-",  ""),
                ("bed",                "String",   "-",   "-",  ""),
                ("admitted",           "String",   "-",   "-",  "Date string e.g. '01 Jan 2024'"),
                ("complaint",          "String",   "-",   "-",  "Chief presenting complaint"),
                ("hypercapnic_failure","Integer",  "-",   "-",  "0=No, 1=Yes (COPD NEWS2 Scale 2)"),
            ]
        },
        {
            "name": "vitals_timeseries",
            "purpose": "Hourly / scheduled vital sign readings per patient. Forward-fill enabled.",
            "pk": "id (Integer, AutoIncr)",
            "fk": "subject_id → patients.subject_id",
            "fields": [
                ("id",             "Integer",  "PK",  "-",  "Auto-increment"),
                ("subject_id",     "Integer",  "FK",  "patients", "Indexed"),
                ("chart_hour",     "String",   "-",   "-",  "ISO datetime string; Indexed"),
                ("heart_rate",     "Float",    "-",   "-",  "bpm"),
                ("resp_rate",      "Float",    "-",   "-",  "breaths/min"),
                ("spo2",           "Float",    "-",   "-",  "% oxygen saturation"),
                ("sbp",            "Float",    "-",   "-",  "Systolic BP mmHg"),
                ("dbp",            "Float",    "-",   "-",  "Diastolic BP mmHg"),
                ("temperature",    "Float",    "-",   "-",  "°C"),
                ("consciousness",  "String",   "-",   "-",  "A/C/V/P/U (ACVPU scale); default 'A'"),
                ("air_or_oxygen",  "String",   "-",   "-",  "'Air' or 'Oxygen'; default 'Air'"),
            ]
        },
        {
            "name": "lab_events",
            "purpose": "Blood test results per patient per time-point for Drug-Lab rule engine.",
            "pk": "id (Integer, AutoIncr)",
            "fk": "subject_id → patients.subject_id",
            "fields": [
                ("id",          "Integer", "PK", "-",       "Auto-increment"),
                ("subject_id",  "Integer", "FK", "patients","Indexed"),
                ("chart_hour",  "String",  "-",  "-",       "ISO datetime; Indexed"),
                ("potassium",   "Float",   "-",  "-",       "mmol/L; rule trigger threshold >5.5"),
                ("creatinine",  "Float",   "-",  "-",       "mg/dL; renal function marker"),
                ("lactate",     "Float",   "-",  "-",       "mmol/L; sepsis marker"),
                ("inr",         "Float",   "-",  "-",       "International Normalised Ratio"),
                ("egfr",        "Float",   "-",  "-",       "mL/min; metformin lactic acidosis risk"),
                ("alt",         "Float",   "-",  "-",       "U/L; statin hepatotoxicity flag"),
            ]
        },
        {
            "name": "medications",
            "purpose": "Active prescriptions per patient. Matched against Drug-Lab rules.",
            "pk": "id (Integer, AutoIncr)",
            "fk": "subject_id → patients.subject_id",
            "fields": [
                ("id",         "Integer", "PK", "-",       "Auto-increment"),
                ("subject_id", "Integer", "FK", "patients","Indexed"),
                ("med_name",   "String",  "-",  "-",       "Generic/brand drug name"),
                ("dose",       "String",  "-",  "-",       "e.g. '5mg'"),
                ("frequency",  "String",  "-",  "-",       "e.g. 'OD', 'BD'"),
            ]
        },
        {
            "name": "escalations",
            "purpose": "Nurse-initiated escalation records with full lifecycle (active→acknowledged→resolved).",
            "pk": "id (Integer, AutoIncr)",
            "fk": "subject_id → patients.subject_id",
            "fields": [
                ("id",               "Integer", "PK", "-",       "Auto-increment"),
                ("subject_id",       "Integer", "FK", "patients","Indexed"),
                ("patient_name",     "String",  "-",  "-",       "Denormalised for audit log"),
                ("ward",             "String",  "-",  "-",       "Denormalised snapshot"),
                ("bed",              "String",  "-",  "-",       "Denormalised snapshot"),
                ("news2_score",      "Integer", "-",  "-",       "Score at time of escalation"),
                ("level",            "String",  "-",  "-",       "nurse | doctor | code_blue"),
                ("attending",        "String",  "-",  "-",       "Attending physician name"),
                ("escalated_by",     "String",  "-",  "-",       "Escalating nurse"),
                ("observations",     "String",  "-",  "-",       "Clinical observations"),
                ("interventions",    "String",  "-",  "-",       "Interventions taken"),
                ("status",           "String",  "-",  "-",       "active | acknowledged | resolved"),
                ("escalated_at",     "String",  "-",  "-",       "ISO datetime"),
                ("acknowledged_at",  "String",  "-",  "-",       "Nullable"),
                ("resolved_at",      "String",  "-",  "-",       "Nullable"),
                ("resolved_by",      "String",  "-",  "-",       "Nullable"),
                ("resolution_notes", "String",  "-",  "-",       "Nullable"),
            ]
        },
    ]

    for tbl in tables_info:
        story.append(KeepTogether([
            Paragraph(f"<b>Table: {tbl['name']}</b>", styles["h3"]),
            Paragraph(tbl["purpose"], styles["body"]),
            Spacer(1, 1*mm),
        ]))
        meta = Table([
            [Paragraph("<b>Primary Key</b>", styles["small"]), Paragraph(tbl["pk"], styles["small"])],
            [Paragraph("<b>Foreign Keys</b>", styles["small"]), Paragraph(tbl["fk"], styles["small"])],
        ], colWidths=[35*mm, "*"])
        meta.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), HexColor("#E2E8F0")),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ]))
        story.append(meta)
        story.append(Spacer(1, 1*mm))

        hdr = ["Column", "Type", "PK/FK", "References", "Notes"]
        rows_data = [hdr] + [[Paragraph(str(v), styles["small"]) for v in row] for row in tbl["fields"]]
        col_w = [32*mm, 18*mm, 12*mm, 22*mm, "*"]
        ft = Table(rows_data, colWidths=col_w)
        ft.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), P),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ft)
        story.append(Spacer(1, 3*mm))

    story.append(PageBreak())

    # ── ER Diagram ────────────────────────────────────────────────────────────
    story.append(section_header("5. ENTITY-RELATIONSHIP DIAGRAM", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Relationships: patients (1) — (N) vitals_timeseries  |  patients (1) — (N) lab_events  |  "
        "patients (1) — (N) medications  |  patients (1) — (N) escalations",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    erd_entities = [
        {
            "name": "patients",
            "x": 190, "y": 60,
            "fields": [
                ("subject_id",          "Integer",  True,  False),
                ("name",                "String",   False, False),
                ("age",                 "Integer",  False, False),
                ("sex",                 "String",   False, False),
                ("ward",                "String",   False, False),
                ("room / bed",          "String",   False, False),
                ("admitted",            "String",   False, False),
                ("complaint",           "String",   False, False),
                ("hypercapnic_failure", "Integer",  False, False),
            ]
        },
        {
            "name": "vitals_timeseries",
            "x": 10, "y": 30,
            "fields": [
                ("id",            "Integer",  True,  False),
                ("subject_id",    "Integer",  False, True),
                ("chart_hour",    "String",   False, False),
                ("heart_rate",    "Float",    False, False),
                ("resp_rate",     "Float",    False, False),
                ("spo2",          "Float",    False, False),
                ("sbp / dbp",     "Float",    False, False),
                ("temperature",   "Float",    False, False),
                ("consciousness", "String",   False, False),
                ("air_or_oxygen", "String",   False, False),
            ]
        },
        {
            "name": "lab_events",
            "x": 10, "y": 220,
            "fields": [
                ("id",          "Integer",  True,  False),
                ("subject_id",  "Integer",  False, True),
                ("chart_hour",  "String",   False, False),
                ("potassium",   "Float",    False, False),
                ("creatinine",  "Float",    False, False),
                ("lactate",     "Float",    False, False),
                ("inr",         "Float",    False, False),
                ("egfr",        "Float",    False, False),
                ("alt",         "Float",    False, False),
            ]
        },
        {
            "name": "medications",
            "x": 380, "y": 30,
            "fields": [
                ("id",          "Integer",  True,  False),
                ("subject_id",  "Integer",  False, True),
                ("med_name",    "String",   False, False),
                ("dose",        "String",   False, False),
                ("frequency",   "String",   False, False),
            ]
        },
        {
            "name": "escalations",
            "x": 380, "y": 200,
            "fields": [
                ("id",               "Integer",  True,  False),
                ("subject_id",       "Integer",  False, True),
                ("patient_name",     "String",   False, False),
                ("ward / bed",       "String",   False, False),
                ("news2_score",      "Integer",  False, False),
                ("level",            "String",   False, False),
                ("attending",        "String",   False, False),
                ("status",           "String",   False, False),
                ("escalated_at",     "String",   False, False),
                ("resolved_at",      "String",   False, False),
            ]
        },
    ]
    erd_relations = [
        {"from": "patients", "to": "vitals_timeseries", "card": "1:N"},
        {"from": "patients", "to": "lab_events",        "card": "1:N"},
        {"from": "patients", "to": "medications",       "card": "1:N"},
        {"from": "patients", "to": "escalations",       "card": "1:N"},
    ]

    erd = ERDiagram(erd_entities, erd_relations, width=180*mm, scale=0.9, primary=P)
    story.append(erd)
    story.append(Spacer(1, 4*mm))
    story.append(PageBreak())

    # ── API Documentation ─────────────────────────────────────────────────────
    story.append(section_header("6. API DOCUMENTATION SUMMARY", P, styles))
    story.append(Spacer(1, 2*mm))

    api_endpoints = [
        ["Method", "Endpoint",                         "Description",                           "Tables"],
        ["POST",   "/api/patients",                    "Register new patient + initial vitals",  "patients, vitals_timeseries"],
        ["GET",    "/api/ward-data?ward=&replay=",     "Full ward data, NEWS2, Drug-Lab alerts", "All tables"],
        ["GET",    "/api/patients/{subject_id}",       "Single patient detail (reuses ward-data)","All tables"],
        ["POST",   "/api/escalations",                 "Raise new clinical escalation",          "escalations, patients, vitals"],
        ["GET",    "/api/escalations",                 "List all escalations",                   "escalations"],
        ["POST",   "/api/escalations/{id}/resolve",   "Resolve an escalation",                  "escalations"],
        ["GET",    "/docs",                            "FastAPI Swagger UI (auto-generated)",    "—"],
        ["GET",    "/",                                "SPA frontend (StaticFiles mount)",       "—"],
    ]
    ta = Table(api_endpoints, colWidths=[14*mm, 60*mm, 60*mm, "*"])
    ta.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ta)
    story.append(Spacer(1, 4*mm))

    # RBAC
    story.append(Paragraph("<b>Role-Based Access (Frontend-Enforced)</b>", styles["h3"]))
    rbac_data = [
        ["Role",         "Username example",  "Capabilities"],
        ["Ward Nurse",   "rekha.devi",        "Enter vitals, view NEWS2 score, raise escalation"],
        ["Charge Nurse", "leena.kurup",       "Ward-overview dashboard, acknowledge/resolve escalations, trends"],
    ]
    tr = Table(rbac_data, colWidths=[30*mm, 35*mm, "*"])
    tr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), P),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
    ]))
    story.append(tr)
    story.append(Spacer(1, 4*mm))

    # ── Architecture Review ───────────────────────────────────────────────────
    story.append(section_header("7. ARCHITECTURE REVIEW", P, styles))
    story.append(Spacer(1, 2*mm))

    review_items = [
        ("Design Pattern",        "Monolithic MVC-like. FastAPI = Controller; models.py = Model; Vite SPA = View."),
        ("Strengths",             "Simple deployment (1 process, 1 file DB). Low operational overhead. YAML rule engine makes clinical rules updateable by doctors without code changes. NEWS2 follows NHS spec exactly."),
        ("Bottlenecks",           "SQLite does not support concurrent writes → single-writer limit. No auth (demo only). Rules YAML loaded on every request (file I/O). REPLAY_OFFSET is a global variable (not thread-safe)."),
        ("Scalability",           "For a single ward demo: adequate. For multi-ward production: needs PostgreSQL, per-request rule caching, proper JWT auth, and horizontal uvicorn workers with a connection pool."),
        ("Improvements",          "Replace SQLite with PostgreSQL. Add JWT authentication layer. Cache parsed YAML rules at startup. Add proper indexes for chart_hour on vitals_timeseries. Implement WebSocket for real-time push."),
        ("India-specific tuning", "SBP ≥ 220 mmHg = NEWS2 score 3 (CSI/ICMR hypertension calibration). Drug-Lab rules use Indian drug names (frusemide, acitrom, glycomet). CSI/CDSCO/RSSDI/ICMR guideline citations."),
    ]
    for label, text in review_items:
        row = Table([[
            Paragraph(f"<b>{label}</b>", styles["bold"]),
            Paragraph(text, styles["body"])
        ]], colWidths=[38*mm, "*"])
        row.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), SABARI_ACCENT),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(row)
        story.append(Spacer(1, 1*mm))

    story.append(PageBreak())

    # ── Conclusion ────────────────────────────────────────────────────────────
    story.append(section_header("8. CONCLUSION", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Foqal CareOS delivers a focused, production-ready early-warning capability for Indian "
        "hospital wards. The 5-table SQLite schema is deliberately minimal and maps directly to "
        "clinical need: patient demographics, time-series vitals, lab results, active medications, "
        "and escalation records. The decoupled YAML rule engine and India-calibrated NEWS2 scorer "
        "provide genuine clinical value without sacrificing maintainability.",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "The architecture is appropriate for a ward-level proof-of-concept and intern project "
        "demonstration. Moving to production at scale would require replacing SQLite with "
        "PostgreSQL, adding JWT-based authentication, and separating the frontend into its own "
        "deployment. The codebase is well-structured and the separation of models, database "
        "config, rule engine, and main API is commendable for a project of this scope.",
        styles["body"]
    ))

    doc.build(story)
    print(f"[OK] {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
#  ASHMIT PROJECT PDF
# ─────────────────────────────────────────────────────────────────────────────

def build_ashmit_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm
    )
    P = ASHMIT_PRIMARY
    styles = make_styles(P)
    story = []

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20*mm))
    story.append(header_table(
        "Discharge Summary AI",
        "Backend Architecture & Entity-Relationship Diagram  |  Ashmit Verma",
        P, ASHMIT_ACCENT
    ))
    story.append(Spacer(1, 8*mm))

    cover_data = [
        ["Project Name",     "Discharge Summary AI — MIMIC-IV Cardiology"],
        ["Developer",        "Ashmit Verma"],
        ["Repository",       "github.com/ashmit-verma24134/Integrated_Hospital  [main branch]"],
        ["Backend",          "Python FastAPI · Google Cloud SQL (PostgreSQL) · BigQuery ETL"],
        ["AI Engine",        "Google Gemini 2.5 Flash (Pass 1 + Pass 2 prompting)"],
        ["Frontend",         "Vanilla JS + Vite SPA — multi-screen role-based UI"],
        ["API Port",         "8000 (main FastAPI)  |  7002 (data_server — BigQuery proxy)"],
        ["Database",         "Cloud SQL (PostgreSQL) — 35+ tables  |  Qdrant (vector store)"],
        ["Data Source",      "MIMIC-IV v3.1 via Google BigQuery (physionet-data)"],
        ["Document Date",    "June 2026"],
    ]
    story.append(info_table(
        [[Paragraph(k, styles["bold"]), Paragraph(v, styles["body"])] for k, v in cover_data],
        P
    ))
    story.append(Spacer(1, 6*mm))

    # ── Executive Summary ─────────────────────────────────────────────────────
    story.append(section_header("1. EXECUTIVE SUMMARY", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Discharge Summary AI is an LLM-powered clinical document generation system designed for "
        "cardiology wards. It ingests structured patient data from MIMIC-IV (via Google BigQuery) "
        "or manually-uploaded CSV files, builds a comprehensive clinical context, and uses Google "
        "Gemini 2.5 Flash in a two-pass prompting pipeline to generate structured discharge "
        "summaries compliant with NABH standards.",
        styles["body"]
    ))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "<b>Key capabilities:</b> Multi-role authentication (Doctor / Admin Staff) with bcrypt "
        "password hashing and email-based password reset; CSV file upload for 18 clinical data "
        "types; BigQuery ETL pipeline for MIMIC-IV cardiology cohort (DCM, STEMI, HF patients); "
        "two-pass Gemini summarisation with NLI claim verification; NLI-based entailment scoring; "
        "doctor sign-off workflow; comprehensive audit log; Qdrant vector store for RAG; "
        "BM25 + dense hybrid retrieval.",
        styles["body"]
    ))
    story.append(PageBreak())

    # ── Tech Stack ────────────────────────────────────────────────────────────
    story.append(section_header("2. TECHNOLOGY STACK", P, styles))
    story.append(Spacer(1, 2*mm))

    stack_data = [
        ["Layer",             "Technology",             "Details"],
        ["API Framework",     "Python FastAPI",         "Async; 2946 lines; port 8000; Pydantic schemas"],
        ["Data Server",       "FastAPI (data_server.py)","BigQuery proxy; port 7002; in-memory tab cache"],
        ["AI Model",          "Google Gemini 2.5 Flash", "Pass 1: structure+sections. Pass 2: refine+verify"],
        ["Database",          "Cloud SQL (PostgreSQL)",  "Managed GCP; 35+ tables; WAL; ACID guarantees"],
        ["Vector Store",      "Qdrant",                 "Dense embeddings for RAG context retrieval"],
        ["Embeddings",        "embedder.py",            "Sentence embeddings for RAG chunks"],
        ["Indexer",           "BM25 (bm25_index.py)",   "Sparse retrieval; hybrid BM25+dense scoring"],
        ["ETL",               "BigQuery (bulk_cardiology_etl.py)", "MIMIC-IV cardiology cohort → Cloud SQL"],
        ["Auth",              "bcrypt + session tokens", "Bcrypt hashing; plain-text → bcrypt upgrade on login"],
        ["Email",             "SMTP (Gmail)",            "Reset-password email via smtplib/MIMEMultipart"],
        ["Frontend",          "Vanilla JS + Vite SPA",  "18+ screens; multi-role; nurse/doctor/admin/CMO"],
        ["ORM/DB access",     "SQLAlchemy + raw SQL",   "cloud_sql_app_db.py; cloud_sql_db.py (pg engine)"],
        ["Deployment",        "GCP Cloud Run / nginx",  "nginx.conf; deploy.sh; Docker-ready"],
    ]
    t = Table(stack_data, colWidths=[35*mm, 42*mm, "*"])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    # ── Backend Architecture ──────────────────────────────────────────────────
    story.append(section_header("3. BACKEND ARCHITECTURE", P, styles))
    story.append(Spacer(1, 2*mm))

    arch_text = """
<b>3.1 Service Architecture (Dual-Server)</b><br/>
The backend runs as TWO FastAPI processes:
<br/>• <b>main.py (port 8000)</b> — application API: auth, encounters, summaries, file uploads,
Gemini generation, sign-off, audit log, settings.
<br/>• <b>data_server.py (port 7002)</b> — data proxy: reads clinical data from Cloud SQL
(ap_* tables fetched from BigQuery), serves lazy tab data to the frontend, maintains an in-memory
per-patient cache. Main server calls DATA_SERVER_URL internally via httpx.

<br/><br/><b>3.2 Authentication Flow</b><br/>
Login: POST /api/auth/login → bcrypt.checkpw → session token. Password reset:
forgot-password → generate token → store in app_reset_tokens → email via SMTP →
/api/auth/reset-password validates token + expiry → bcrypt new hash → delete token.
Plain-text passwords in DB are auto-upgraded to bcrypt on first successful login.

<br/><br/><b>3.3 Discharge Summary Generation Pipeline (Two-Pass Gemini)</b><br/>
<b>Pass 1:</b> Build clinical context (build_clinical_context) → assemble structured prompt
with NABH sections → Gemini 2.5 Flash generates full discharge summary draft.<br/>
<b>Pass 2:</b> Review pass — LLM verifies factual claims against source data; flags sections
needing manual review. NLI entailment score saved to app_summaries.nli_score.<br/>
Prompt versions tracked (pass1_version, pass2_version) in app_summaries for A/B and error analysis.

<br/><br/><b>3.4 CSV File Upload Pipeline</b><br/>
POST /api/encounters/{hadm_id}/ingest_file (18 file_type values supported) →
CSV parsed → rows enriched (ICD titles via BigQuery, lab labels) → stored as JSONB
in app_clinical_rows AND written to structured ap_* tables → data_server cache invalidated.

<br/><br/><b>3.5 BigQuery ETL Pipeline</b><br/>
bulk_cardiology_etl.py / bigquery_mimic_loader.py: pulls MIMIC-IV cardiology cohort
(DCM ICU patients filtered by ICD codes) from physionet-data.mimiciv_hosp / mimiciv_icu →
inserts into Cloud SQL ap_* tables → updates active_patients.data_fetch_status.
Advisory lock (pg_advisory_xact_lock) prevents double-fetch. Two rounds: hosp data first,
ICU data second.

<br/><br/><b>3.6 RAG Context Assembly</b><br/>
chunker.py splits clinical data into text chunks → embedder.py creates dense vectors →
stored in Qdrant. At summary time: section query → hybrid BM25 (bm25_index.py) + dense
(qdrant_store.py) retrieval → top-k chunks assembled as context for Gemini prompt.
"""
    story.append(Paragraph(arch_text.strip(), styles["body"]))
    story.append(Spacer(1, 4*mm))

    # Data flow
    story.append(Paragraph("<b>3.7 End-to-End Data Flow</b>", styles["h3"]))
    flow_data = [
        ["Step", "Layer",                "Action",                                       "Component"],
        ["1",    "BigQuery",             "ETL: MIMIC-IV cardiology → Cloud SQL",          "bulk_cardiology_etl.py"],
        ["2",    "Cloud SQL",            "Store in ap_* tables + active_patients",        "cloud_sql_db.py (get_engine)"],
        ["3",    "Data Server (7002)",   "Serve lazy-tab data (labs, meds, vitals…)",    "data_server.py"],
        ["4",    "Main API (8000)",      "Auth → encounter lifecycle management",         "main.py /api/auth, /api/encounters"],
        ["5",    "CSV Upload",           "Admin uploads CSV → ingest → Cloud SQL",        "main.py /api/encounters/{id}/ingest_file"],
        ["6",    "Context Builder",      "Aggregate clinical data → prose context",       "build_clinical_context()"],
        ["7",    "RAG Retrieval",        "BM25+dense → relevant clinical chunks",         "bm25_index.py + qdrant_store.py"],
        ["8",    "Gemini Pass 1",        "Full discharge summary generation (NABH)",      "Gemini 2.5 Flash API"],
        ["9",    "Gemini Pass 2",        "Claim verification + NLI scoring",              "Gemini 2.5 Flash API"],
        ["10",   "Sign-Off",             "Doctor reviews → signs → PDF generated",        "main.py /api/summaries/{id}/signoff"],
        ["11",   "Audit Log",            "All actions logged with user_id + details",     "app_audit_log"],
    ]
    t3 = Table(flow_data, colWidths=[8*mm, 32*mm, 60*mm, "*"])
    t3.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t3)
    story.append(PageBreak())

    # ── Database Schema — APP TABLES ─────────────────────────────────────────
    story.append(section_header("4. DATABASE SCHEMA — APPLICATION TABLES", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "<b>Database:</b> Google Cloud SQL (PostgreSQL) · 35+ tables across 3 schema groups: "
        "App tables (workflow), Clinical data tables (ap_*), and Cardiology staging tables.",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))

    app_tables = [
        {
            "name": "app_users",
            "purpose": "System users — Doctors, Admin Staff, Billing Staff, Super Admin.",
            "pk": "id (UUID, gen_random_uuid())",
            "fk": "None",
            "fields": [
                ("id",             "UUID",        "PK",  "-",          "Auto-generated"),
                ("hospital_email", "VARCHAR(255)", "-",  "-",          "UNIQUE per (email, role)"),
                ("role",           "VARCHAR(30)",  "-",  "-",          "Doctor|Admin Staff|Billing Staff|Super Admin"),
                ("full_name",      "VARCHAR(120)", "-",  "-",          ""),
                ("password_hash",  "TEXT",         "-",  "-",          "bcrypt hash; auto-upgraded on login"),
                ("session_token",  "TEXT",         "-",  "-",          "Nullable; dummy token in demo"),
                ("is_active",      "BOOLEAN",      "-",  "-",          "Default TRUE"),
                ("created_at",     "TIMESTAMPTZ",  "-",  "-",          ""),
                ("updated_at",     "TIMESTAMPTZ",  "-",  "-",          "Auto-updated trigger"),
            ]
        },
        {
            "name": "active_patients",
            "purpose": "Master patient hub — one row per registered hadm_id. Denormalised summary for fast list views.",
            "pk": "id (UUID) + UNIQUE(hadm_id)",
            "fk": "assigned_doctor_id → app_users, signed_by → app_users, encounter_id → app_encounters, summary_id → app_summaries",
            "fields": [
                ("id",                    "UUID",        "PK",  "-",         ""),
                ("hadm_id",               "INTEGER",     "-",   "-",         "UNIQUE; MIMIC-IV admission ID"),
                ("subject_id",            "INTEGER",     "-",   "-",         "MIMIC-IV patient ID"),
                ("gender / anchor_age",   "CHAR/SMALLINT","-", "-",         "Demographics snapshot"),
                ("race / marital_status", "VARCHAR",     "-",   "-",         ""),
                ("admission_type",        "VARCHAR(50)", "-",   "-",         "EMERGENCY|ELECTIVE|etc."),
                ("admit_time/discharge",  "TIMESTAMPTZ", "-",   "-",         ""),
                ("los_days",              "NUMERIC(6,2)","-",   "-",         "Length of stay"),
                ("primary_diagnosis_*",   "VARCHAR/TEXT","-",   "-",         "Denormalised from ap_diagnoses"),
                ("status",                "VARCHAR(30)", "-",   "-",         "active→data_fetching→data_ready→…"),
                ("data_fetch_status",     "VARCHAR(20)", "-",   "-",         "pending|fetching|fetched|partial|failed"),
                ("assigned_doctor_id",    "UUID",        "FK",  "app_users", ""),
                ("encounter_id",          "UUID",        "FK",  "app_encounters",""),
                ("summary_id",            "UUID",        "FK",  "app_summaries",""),
            ]
        },
        {
            "name": "app_encounters",
            "purpose": "Discharge summary workflow case. One encounter per hadm_id.",
            "pk": "id (UUID) + UNIQUE(hadm_id)",
            "fk": "hadm_id → active_patients(hadm_id), assigned_to → app_users",
            "fields": [
                ("id",            "UUID",        "PK",  "-",         ""),
                ("hadm_id",       "INTEGER",     "FK",  "active_patients","ON DELETE CASCADE; UNIQUE"),
                ("status",        "VARCHAR(40)", "-",   "-",         "Pending Ingestion→Processing→Ready for Review→Signed Off"),
                ("complexity",    "VARCHAR(20)", "-",   "-",         "Low|Medium|High"),
                ("assigned_to",   "UUID",        "FK",  "app_users", "Assigning doctor/admin"),
                ("version",       "INTEGER",     "-",   "-",         "Summary version counter"),
                ("discharge_type","VARCHAR(20)", "-",   "-",         "Standard|LAMA|DAMA|Death|Referral"),
            ]
        },
        {
            "name": "app_summaries",
            "purpose": "AI-generated discharge summary content + NLI verification metadata.",
            "pk": "id (UUID) + UNIQUE(encounter_id)",
            "fk": "encounter_id → app_encounters, signed_by → app_users",
            "fields": [
                ("id",                       "UUID",        "PK",  "-",           ""),
                ("encounter_id",             "UUID",        "FK",  "app_encounters","ON DELETE CASCADE; UNIQUE"),
                ("hadm_id",                  "INTEGER",     "-",   "-",           "Denormalised for query"),
                ("content",                  "TEXT",        "-",   "-",           "Full generated summary (Markdown)"),
                ("clinical_context",         "TEXT",        "-",   "-",           "Input context used for generation"),
                ("nli_score",                "NUMERIC(5,4)","-",   "-",           "Entailment score 0.0–1.0"),
                ("claim_verification_status","VARCHAR(30)", "-",   "-",           "Needs Review|Verified|Manual"),
                ("signed_by",                "UUID",        "FK",  "app_users",   "Nullable; doctor who signed"),
                ("signed_at",                "TIMESTAMPTZ", "-",   "-",           ""),
                ("pass1_version",            "TEXT",        "-",   "-",           "Prompt version tracking"),
                ("pass2_version",            "TEXT",        "-",   "-",           "Prompt version tracking"),
            ]
        },
        {
            "name": "app_uploaded_files",
            "purpose": "File upload registry — tracks every CSV uploaded for an encounter.",
            "pk": "id (UUID)",
            "fk": "hadm_id → active_patients, encounter_id → app_encounters, uploaded_by → app_users",
            "fields": [
                ("id",             "UUID",        "PK",  "-",           ""),
                ("hadm_id",        "INTEGER",     "FK",  "active_patients",""),
                ("encounter_id",   "UUID",        "FK",  "app_encounters",""),
                ("file_type",      "VARCHAR(30)", "-",   "-",           "labs|meds|notes|diagnoses|procedures|…"),
                ("file_name",      "VARCHAR(255)","-",   "-",           "Original filename"),
                ("file_size",      "BIGINT",      "-",   "-",           "Bytes"),
                ("indexed_status", "VARCHAR(20)", "-",   "-",           "pending|indexed|failed"),
                ("uploaded_by",    "UUID",        "FK",  "app_users",   ""),
            ]
        },
        {
            "name": "app_clinical_rows",
            "purpose": "Raw JSON blob storage for uploaded CSV rows (JSONB array per file).",
            "pk": "id (BIGSERIAL) + UNIQUE(hadm_id, file_type, file_id)",
            "fk": "None (orphan-safe by design)",
            "fields": [
                ("id",       "BIGSERIAL",  "PK", "-",        ""),
                ("hadm_id",  "INTEGER",    "-",  "-",        "Not FK — orphan-safe for demo uploads"),
                ("file_type","VARCHAR(30)","-",  "-",        "labs|meds|notes|…"),
                ("file_id",  "UUID",       "-",  "-",        "Links to app_uploaded_files.id"),
                ("rows",     "JSONB",      "-",  "-",        "Full CSV rows as JSON array"),
            ]
        },
        {
            "name": "app_reset_tokens",
            "purpose": "Single-use password reset tokens with 1-hour expiry.",
            "pk": "token (TEXT)",
            "fk": "user_id → app_users",
            "fields": [
                ("token",      "TEXT",       "PK", "-",        "32-byte URL-safe random"),
                ("user_id",    "UUID",       "FK", "app_users","ON DELETE CASCADE"),
                ("expiry",     "BIGINT",     "-",  "-",        "Unix timestamp; token deleted on use"),
                ("created_at", "TIMESTAMPTZ","-",  "-",        ""),
            ]
        },
        {
            "name": "app_audit_log",
            "purpose": "Append-only immutable audit trail for all system actions.",
            "pk": "id (BIGSERIAL)",
            "fk": "user_id → app_users (nullable), hadm_id not FK",
            "fields": [
                ("id",         "BIGSERIAL",  "PK", "-",        ""),
                ("action",     "VARCHAR(80)","-",  "-",        "e.g. 'summary_generated', 'file_uploaded'"),
                ("hadm_id",    "INTEGER",    "-",  "-",        ""),
                ("user_id",    "UUID",       "FK", "app_users","Nullable"),
                ("details",    "JSONB",      "-",  "-",        "Action-specific payload"),
                ("created_at", "TIMESTAMPTZ","-",  "-",        "Never updated"),
            ]
        },
        {
            "name": "app_settings",
            "purpose": "Singleton system settings (hospital name, NLI threshold, chunk count).",
            "pk": "id = 1 (enforced by CHECK)",
            "fk": "None",
            "fields": [
                ("id",                      "INTEGER",      "PK", "-",  "Always 1 (singleton)"),
                ("hospital_name / wing",    "VARCHAR",      "-",  "-",  ""),
                ("nli_entailment_threshold","NUMERIC(4,3)", "-",  "-",  "Default 0.5"),
                ("k_retrieved_chunks",      "SMALLINT",     "-",  "-",  "Default 5"),
                ("dense_retrieval_weight",  "NUMERIC(4,3)", "-",  "-",  "Default 0.7"),
                ("auto_notify_doctor",      "BOOLEAN",      "-",  "-",  "Default FALSE"),
            ]
        },
        {
            "name": "error_log",
            "purpose": "3-tier accuracy framework error logging for Tier 3 launch gate monitoring.",
            "pk": "id (SERIAL)",
            "fk": "None",
            "fields": [
                ("id",               "SERIAL",      "PK", "-",  ""),
                ("hadm_id",          "VARCHAR(20)", "-",  "-",  "Admission ID"),
                ("error_tier",       "SMALLINT",    "-",  "-",  "1=minor, 2=moderate, 3=critical (launch gate)"),
                ("nabh_section",     "VARCHAR(10)", "-",  "-",  "s1…s15 NABH section"),
                ("error_category",   "VARCHAR(50)", "-",  "-",  "medication_dose|diagnosis|hallucination|…"),
                ("ai_output",        "TEXT",         "-",  "-",  "AI-generated text"),
                ("correct_value",    "TEXT",         "-",  "-",  "Ground truth"),
                ("source_present",   "BOOLEAN",      "-",  "-",  "Was fact present in source data?"),
            ]
        },
    ]

    for tbl in app_tables:
        story.append(KeepTogether([
            Paragraph(f"<b>Table: {tbl['name']}</b>", styles["h3"]),
            Paragraph(tbl["purpose"], styles["body"]),
            Spacer(1, 1*mm),
        ]))
        meta = Table([
            [Paragraph("<b>Primary Key</b>", styles["small"]), Paragraph(tbl["pk"], styles["small"])],
            [Paragraph("<b>Foreign Keys</b>", styles["small"]), Paragraph(tbl["fk"], styles["small"])],
        ], colWidths=[35*mm, "*"])
        meta.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), HexColor("#E2E8F0")),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ]))
        story.append(meta)
        story.append(Spacer(1, 1*mm))

        hdr = ["Column", "Type", "PK/FK", "References", "Notes"]
        rows_data = [hdr] + [[Paragraph(str(v), styles["small"]) for v in row] for row in tbl["fields"]]
        col_w = [38*mm, 22*mm, 10*mm, 22*mm, "*"]
        ft = Table(rows_data, colWidths=col_w)
        ft.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), P),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ft)
        story.append(Spacer(1, 3*mm))

    story.append(PageBreak())

    # ── Database Schema — CLINICAL DATA TABLES ────────────────────────────────
    story.append(section_header("5. DATABASE SCHEMA — CLINICAL DATA TABLES (ap_*)", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "All ap_* tables are fetched from BigQuery MIMIC-IV v3.1 and stored in Cloud SQL. "
        "Every table has a FK to active_patients(hadm_id) ON DELETE CASCADE and a source_fetched_at timestamp. "
        "All inserts use INSERT … ON CONFLICT DO NOTHING for idempotent re-fetching.",
        styles["body"]
    ))
    story.append(Spacer(1, 2*mm))

    clinical_tables_summary = [
        ["Table",                 "Purpose",                                              "Primary Key",      "Key Columns"],
        ["ap_admissions",         "Merged admissions + patients (demographics snapshot)", "hadm_id (FK→ap)",  "admittime, dischtime, gender, anchor_age"],
        ["ap_diagnoses",          "ICD-9/10 diagnoses; computed is_primary column",       "BIGSERIAL id",     "seq_num, icd_code, icd_version, long_title, is_primary"],
        ["ap_procedures",         "ICD procedure codes",                                  "BIGSERIAL id",     "seq_num, icd_code, icd_version, chartdate"],
        ["ap_drgcodes",           "DRG billing codes (severity + mortality)",             "BIGSERIAL id",     "drg_type, drg_code, description, drg_severity"],
        ["ap_labevents",          "High-volume lab results (~500-5000 rows/admit)",       "labevent_id BIGINT","itemid, label, charttime, valuenum, flag, ref_range_*"],
        ["ap_microbiologyevents", "Culture results + antibiotic sensitivity",             "microevent_id",    "spec_type_desc, org_name, ab_name, interpretation"],
        ["ap_prescriptions",      "Prescribed medications (prescriptions.csv)",           "BIGSERIAL id",     "drug, dose_val_rx, route, starttime, stoptime"],
        ["ap_icustays",           "ICU stay records (parent of ICU sub-tables)",         "stay_id INT (MIMIC)","first_careunit, last_careunit, intime, outtime, los"],
        ["ap_chartevents",        "Vitals + ICU monitoring (largest table per patient)", "BIGSERIAL id",     "stay_id FK, itemid, charttime, value, valuenum, warning"],
        ["ap_transfers",          "Patient movement through hospital wards",              "transfer_id INT",  "careunit, eventtype, intime, outtime"],
        ["ap_services",           "Clinical service assignments (CMED, SURG, etc.)",     "BIGSERIAL id",     "transfertime, prev_service, curr_service"],
        ["ap_pharmacy",           "Pharmacy dispensing + frequency for discharge meds",  "pharmacy_id BIGINT","medication, frequency, route, status, starttime/stop"],
        ["ap_poe",                "Physician orders (consults, radiology, discharge)",   "poe_id VARCHAR(30)","order_type, order_subtype, ordertime, order_status"],
        ["ap_omr",                "Outpatient baseline vitals (OMR data)",               "BIGSERIAL id",     "chartdate, result_name, result_value"],
        ["ap_procedureevents",    "ICU procedures (ventilation, CRRT, lines)",           "BIGSERIAL id",     "stay_id FK, itemid, label, starttime, endtime"],
        ["ap_datetimeevents",     "ICU event timestamps (intubation, extubation)",       "BIGSERIAL id",     "stay_id FK, itemid, label, charttime, value (timestamp)"],
        ["ap_inputevents",        "ICU IV fluids + infusions",                           "BIGSERIAL id",     "stay_id FK, itemid, amount, rate, ordercategoryname"],
        ["ap_outputevents",       "ICU fluid output (urine, drains)",                   "BIGSERIAL id",     "stay_id FK, itemid, charttime, value"],
    ]
    tc = Table(clinical_tables_summary, colWidths=[38*mm, 50*mm, 30*mm, "*"])
    tc.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tc)
    story.append(Spacer(1, 3*mm))

    # Cardiology staging tables
    story.append(Paragraph("<b>Cardiology Staging Tables (create_cardiology_tables.sql)</b>", styles["h3"]))
    story.append(Paragraph(
        "A parallel set of cardiology_* tables mirrors the ap_* schema for the legacy BigQuery "
        "bulk ETL pipeline. Tables include: cardiology_patients, cardiology_admissions, "
        "cardiology_diagnoses, cardiology_procedures, cardiology_labevents, "
        "cardiology_prescriptions, cardiology_icustays, cardiology_chartevents, "
        "cardiology_inputevents, cardiology_outputevents, cardiology_microevents, "
        "cardiology_emar, cardiology_pharmacy, cardiology_poe, cardiology_drgcodes, "
        "cardiology_services, cardiology_transfers + lookup tables: "
        "mimic_d_icd_diagnoses, mimic_d_icd_procedures, mimic_d_labitems, mimic_d_items.",
        styles["body"]
    ))
    story.append(PageBreak())

    # ── ER Diagram ────────────────────────────────────────────────────────────
    story.append(section_header("6. ENTITY-RELATIONSHIP DIAGRAM — APP TABLES", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Core app-level relationships. Clinical data tables (ap_*) all FK to active_patients(hadm_id).",
        styles["body"]
    ))
    story.append(Spacer(1, 2*mm))

    erd_entities_app = [
        {
            "name": "app_users",
            "x": 190, "y": 5,
            "fields": [
                ("id",             "UUID",    True,  False),
                ("hospital_email", "VARCHAR", False, False),
                ("role",           "VARCHAR", False, False),
                ("full_name",      "VARCHAR", False, False),
                ("password_hash",  "TEXT",    False, False),
                ("is_active",      "BOOLEAN", False, False),
            ]
        },
        {
            "name": "active_patients",
            "x": 190, "y": 140,
            "fields": [
                ("id",                "UUID",    True,  False),
                ("hadm_id",           "INTEGER", False, False),
                ("subject_id",        "INTEGER", False, False),
                ("status",            "VARCHAR", False, False),
                ("data_fetch_status", "VARCHAR", False, False),
                ("assigned_doctor_id","UUID",    False, True),
                ("encounter_id",      "UUID",    False, True),
                ("summary_id",        "UUID",    False, True),
            ]
        },
        {
            "name": "app_encounters",
            "x": 10, "y": 140,
            "fields": [
                ("id",           "UUID",    True,  False),
                ("hadm_id",      "INTEGER", False, True),
                ("status",       "VARCHAR", False, False),
                ("complexity",   "VARCHAR", False, False),
                ("assigned_to",  "UUID",    False, True),
                ("discharge_type","VARCHAR",False, False),
            ]
        },
        {
            "name": "app_summaries",
            "x": 380, "y": 140,
            "fields": [
                ("id",                       "UUID",    True,  False),
                ("encounter_id",             "UUID",    False, True),
                ("hadm_id",                  "INTEGER", False, False),
                ("content",                  "TEXT",    False, False),
                ("nli_score",                "NUMERIC", False, False),
                ("claim_verification_status","VARCHAR", False, False),
                ("signed_by",                "UUID",    False, True),
                ("pass1_version",            "TEXT",    False, False),
            ]
        },
        {
            "name": "app_uploaded_files",
            "x": 10, "y": 300,
            "fields": [
                ("id",           "UUID",    True,  False),
                ("hadm_id",      "INTEGER", False, True),
                ("encounter_id", "UUID",    False, True),
                ("file_type",    "VARCHAR", False, False),
                ("file_name",    "VARCHAR", False, False),
                ("indexed_status","VARCHAR",False, False),
                ("uploaded_by",  "UUID",    False, True),
            ]
        },
        {
            "name": "app_audit_log",
            "x": 380, "y": 300,
            "fields": [
                ("id",         "BIGSERIAL", True,  False),
                ("action",     "VARCHAR",   False, False),
                ("hadm_id",    "INTEGER",   False, False),
                ("user_id",    "UUID",      False, True),
                ("details",    "JSONB",     False, False),
                ("created_at", "TIMESTAMPTZ",False,False),
            ]
        },
    ]
    erd_relations_app = [
        {"from": "app_users",       "to": "active_patients", "card": "1:N"},
        {"from": "active_patients", "to": "app_encounters",  "card": "1:1"},
        {"from": "active_patients", "to": "app_summaries",   "card": "1:1"},
        {"from": "app_encounters",  "to": "app_uploaded_files","card": "1:N"},
        {"from": "app_users",       "to": "app_audit_log",   "card": "1:N"},
        {"from": "active_patients", "to": "app_audit_log",   "card": "1:N"},
    ]

    erd2 = ERDiagram(erd_entities_app, erd_relations_app, width=180*mm, scale=0.9, primary=P)
    story.append(erd2)
    story.append(Spacer(1, 4*mm))

    # Clinical data ER
    story.append(Paragraph("<b>Clinical Data Table Relationships (ap_* tables)</b>", styles["h3"]))
    story.append(Paragraph(
        "All 18 clinical data tables (ap_admissions, ap_diagnoses, ap_labevents, etc.) hold a "
        "FK → active_patients(hadm_id) ON DELETE CASCADE. ICU sub-tables additionally FK to "
        "ap_icustays(stay_id).",
        styles["body"]
    ))
    story.append(Spacer(1, 2*mm))

    # Simple clinical data ERD
    erd_clinical = [
        {
            "name": "active_patients",
            "x": 190, "y": 60,
            "fields": [
                ("hadm_id",    "INTEGER", False, False),
                ("subject_id", "INTEGER", False, False),
                ("status",     "VARCHAR", False, False),
            ]
        },
        {
            "name": "ap_admissions",
            "x": 10, "y": 10,
            "fields": [
                ("hadm_id",    "INTEGER PK/FK", True, False),
                ("admittime",  "TIMESTAMPTZ",  False, False),
                ("gender",     "CHAR(1)",       False, False),
            ]
        },
        {
            "name": "ap_diagnoses",
            "x": 10, "y": 105,
            "fields": [
                ("id",         "BIGSERIAL", True,  False),
                ("hadm_id",    "INTEGER",   False, True),
                ("icd_code",   "VARCHAR",   False, False),
                ("is_primary", "BOOLEAN",   False, False),
            ]
        },
        {
            "name": "ap_labevents",
            "x": 10, "y": 205,
            "fields": [
                ("labevent_id","BIGINT",  True,  False),
                ("hadm_id",    "INTEGER", False, True),
                ("itemid",     "INTEGER", False, False),
                ("valuenum",   "NUMERIC", False, False),
                ("flag",       "VARCHAR", False, False),
            ]
        },
        {
            "name": "ap_prescriptions",
            "x": 380, "y": 10,
            "fields": [
                ("id",         "BIGSERIAL", True,  False),
                ("hadm_id",    "INTEGER",   False, True),
                ("drug",       "VARCHAR",   False, False),
                ("route",      "VARCHAR",   False, False),
            ]
        },
        {
            "name": "ap_icustays",
            "x": 380, "y": 120,
            "fields": [
                ("stay_id",         "INTEGER PK",True,  False),
                ("hadm_id",         "INTEGER",   False, True),
                ("first_careunit",  "VARCHAR",   False, False),
                ("los",             "NUMERIC",   False, False),
            ]
        },
        {
            "name": "ap_chartevents",
            "x": 380, "y": 230,
            "fields": [
                ("id",       "BIGSERIAL", True,  False),
                ("hadm_id",  "INTEGER",   False, True),
                ("stay_id",  "INTEGER",   False, True),
                ("itemid",   "INTEGER",   False, False),
                ("valuenum", "NUMERIC",   False, False),
            ]
        },
    ]
    erd_clinical_rel = [
        {"from": "active_patients", "to": "ap_admissions",   "card": "1:1"},
        {"from": "active_patients", "to": "ap_diagnoses",    "card": "1:N"},
        {"from": "active_patients", "to": "ap_labevents",    "card": "1:N"},
        {"from": "active_patients", "to": "ap_prescriptions","card": "1:N"},
        {"from": "active_patients", "to": "ap_icustays",     "card": "1:N"},
        {"from": "ap_icustays",     "to": "ap_chartevents",  "card": "1:N"},
    ]

    erd3 = ERDiagram(erd_clinical, erd_clinical_rel, width=180*mm, scale=0.9, primary=P)
    story.append(erd3)
    story.append(PageBreak())

    # ── API Summary ───────────────────────────────────────────────────────────
    story.append(section_header("7. API DOCUMENTATION SUMMARY", P, styles))
    story.append(Spacer(1, 2*mm))

    api_groups = [
        ("Authentication", [
            ["POST", "/api/auth/login",          "Bcrypt login; auto-detects role",          "app_users"],
            ["POST", "/api/auth/register",        "Create user (Doctor/Admin)",               "app_users"],
            ["POST", "/api/auth/forgot-password", "Generate reset token + send email",        "app_reset_tokens"],
            ["POST", "/api/auth/reset-password",  "Validate token, set new bcrypt password",  "app_users, app_reset_tokens"],
            ["POST", "/api/auth/direct-reset",    "Force-set password (recovery only)",       "app_users"],
        ]),
        ("Dashboard & Encounters", [
            ["GET",  "/api/dashboard",             "Stats: open cases, ready, signed this month", "app_encounters, app_summaries"],
            ["POST", "/api/encounters",            "Create encounter for a hadm_id",           "app_encounters, active_patients"],
            ["GET",  "/api/encounters",            "List encounters (filter by status/doctor)", "app_encounters"],
            ["GET",  "/api/active_patients",       "All loaded patients with encounter status", "active_patients + app_encounters JOIN"],
            ["POST", "/api/seed/cardiology",       "Seed 10 DCM ICU encounters",              "app_encounters"],
        ]),
        ("File Upload & Ingest", [
            ["POST", "/api/encounters/{id}/ingest_file","Upload CSV (18 file_types)",         "app_clinical_rows + ap_* tables"],
            ["GET",  "/api/encounters/{id}/uploaded_clinical_data","All uploaded rows",        "app_clinical_rows"],
            ["DELETE","/api/uploaded_files/{file_id}","Delete file + its clinical rows",      "app_uploaded_files, app_clinical_rows"],
            ["DELETE","/api/encounters/{id}/clinical_rows/{type}","Purge all rows by type",   "app_clinical_rows"],
        ]),
        ("Summaries & Sign-Off", [
            ["GET",  "/api/summaries",             "List summaries with encounter/doctor info", "app_summaries + app_encounters"],
            ["POST", "/api/patient/{id}/generate", "Run Gemini Pass1+Pass2 generation",       "app_summaries, active_patients"],
            ["POST", "/api/summaries/{id}/signoff","Doctor sign-off",                         "app_summaries, app_audit_log"],
        ]),
    ]

    for group_name, endpoints in api_groups:
        story.append(Paragraph(f"<b>{group_name}</b>", styles["h3"]))
        hdr = ["Method", "Endpoint", "Description", "Tables"]
        rows_data = [hdr] + endpoints
        ta = Table(rows_data, colWidths=[14*mm, 65*mm, 55*mm, "*"])
        ta.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), P),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [TABLE_ROW_ALT, colors.white]),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ta)
        story.append(Spacer(1, 3*mm))

    story.append(PageBreak())

    # ── Architecture Review ───────────────────────────────────────────────────
    story.append(section_header("8. ARCHITECTURE REVIEW", P, styles))
    story.append(Spacer(1, 2*mm))

    review_items = [
        ("Patterns",         "Dual-server microservice (main + data_server). Repository pattern via cloud_sql_app_db.py. Factory pattern for DB engine. Strategy pattern for retrieval (BM25 vs dense)."),
        ("Strengths",        "Production-grade Cloud SQL with ACID guarantees, advisory locks, SELECT FOR UPDATE. bcrypt auth. Two-pass LLM with NLI scoring. Comprehensive audit log. NABH-compliant output sections. Error log with Tier 3 launch gate."),
        ("Bottlenecks",      "Single Gemini API call per patient (latency ~5-15s). In-memory data_server cache is per-process (lost on restart). No real JWT (dummy token). BigQuery ETL is synchronous per patient."),
        ("Scalability",      "Cloud SQL scales vertically. Qdrant can be horizontally scaled. BigQuery ETL can be parallelised. Bottleneck is Gemini API rate limits. Add async task queue (Celery/Cloud Tasks) for generation."),
        ("DB Design",        "35+ tables, well-normalised with appropriate FKs, partial indexes, and UNIQUE constraints. Trigger-based updated_at. Concurrency patterns documented inline (advisory locks, SKIP LOCKED)."),
        ("Improvements",     "Replace dummy session tokens with proper JWT. Add Celery for async Gemini generation. Implement Redis caching for data_server. Add rate limiting. Add WebSocket for real-time generation progress."),
    ]
    for label, text in review_items:
        row = Table([[
            Paragraph(f"<b>{label}</b>", styles["bold"]),
            Paragraph(text, styles["body"])
        ]], colWidths=[32*mm, "*"])
        row.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, -1), ASHMIT_ACCENT),
            ("GRID",          (0, 0), (-1, -1), 0.3, HexColor("#CBD5E1")),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(row)
        story.append(Spacer(1, 1*mm))

    # ── Conclusion ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 4*mm))
    story.append(section_header("9. CONCLUSION", P, styles))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Discharge Summary AI is a sophisticated full-stack AI system that demonstrates strong "
        "engineering practices: production PostgreSQL with concurrency controls, a two-pass "
        "LLM pipeline with NLI-based hallucination detection, a comprehensive file upload and "
        "data ingestion pipeline supporting 18 clinical data types, bcrypt authentication with "
        "email-based password reset, and a role-based multi-screen frontend.",
        styles["body"]
    ))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "The system's 35+ table schema is well-designed for the problem domain: structured "
        "MIMIC-IV clinical data (18 ap_* tables) with FK cascade integrity, an application "
        "workflow layer (app_users, app_encounters, app_summaries, app_uploaded_files), and "
        "quality monitoring infrastructure (error_log with Tier 3 launch gate, app_audit_log). "
        "This is a production-grade architecture suitable for clinical deployment with the "
        "addition of real JWT tokens, async task queues, and Gemini rate-limit management.",
        styles["body"]
    ))

    doc.build(story)
    print(f"[OK] {output_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sabari_out = os.path.join(OUT_DIR, "Sabari_Project_Architecture_and_ERD.pdf")
    ashmit_out = os.path.join(OUT_DIR, "Ashmit_Project_Architecture_and_ERD.pdf")

    print("Generating Sabari project PDF...")
    build_sabari_pdf(sabari_out)

    print("Generating Ashmit project PDF...")
    build_ashmit_pdf(ashmit_out)

    print("\nDone! PDFs written to:")
    print(f"  {sabari_out}")
    print(f"  {ashmit_out}")
