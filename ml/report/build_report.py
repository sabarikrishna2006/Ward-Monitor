"""Inject the PNG charts as base64 data URIs into the briefing template."""
import base64, os

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(HERE, "..", "data", "charts")
TOKENS = {
    "__CHART_CINDEX__": "cindex_comparison.png",
    "__CHART_ALERT__": "alert_burden.png",
    "__CHART_COVERAGE__": "coverage.png",
    "__CHART_RISK__": "risk_separation.png",
    "__CHART_SHAP__": "shap_top.png",
}

def datauri(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

html = open(os.path.join(HERE, "_template.html"), encoding="utf-8").read()
for token, fname in TOKENS.items():
    html = html.replace(token, datauri(os.path.join(CHARTS, fname)))

out = os.path.join(HERE, "briefing.html")
open(out, "w", encoding="utf-8").write(html)
print("wrote", out, f"({len(html)/1024:.0f} KB)")
