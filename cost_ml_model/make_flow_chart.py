import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

steps = [
    ("1", "Diagnosis auto-fetched", "at patient admission"),
    ("2", "Looked up in the\nshrinkage cost-band table", "assigned one of 4 bands"),
    ("3", "Sets the matching feature to 1,\nthe other three to 0",
     "primary_diagnosis_cost_band_\nLow / Mid-Low / Mid-High / High"),
]

fig, ax = plt.subplots(figsize=(11.5, 4.4))
ax.set_xlim(0, 11.5)
ax.set_ylim(0, 4.4)
ax.axis("off")

box_w, box_h = 3.15, 2.6
gap = 0.65
n = len(steps)
total_w = n * box_w + (n - 1) * gap
start_x = (11.5 - total_w) / 2
y = (4.4 - box_h) / 2 + 0.1

colors = ["#2E86C1", "#2E86C1", "#1B4F72"]
fills = ["#EAF2F8", "#EAF2F8", "#D6EAF8"]

for i, (num, title, sub) in enumerate(steps):
    x = start_x + i * (box_w + gap)
    box = FancyBboxPatch((x, y), box_w, box_h, boxstyle="round,pad=0.02,rounding_size=0.12",
                          linewidth=1.5, edgecolor=colors[i], facecolor=fills[i])
    ax.add_patch(box)
    ax.text(x + box_w/2, y + box_h - 0.45, num, fontsize=24, fontweight="bold",
             color=colors[i], ha="center", va="center")
    ax.text(x + box_w/2, y + box_h - 1.25, title, fontsize=12.5, fontweight="bold",
             color="#1B2631", ha="center", va="center", linespacing=1.5)
    ax.text(x + box_w/2, y + 0.5, sub, fontsize=10, color="#4A5A6A",
             ha="center", va="center", linespacing=1.5)

    if i < n - 1:
        ax.annotate("", xy=(x + box_w + gap - 0.1, y + box_h/2), xytext=(x + box_w + 0.1, y + box_h/2),
                     arrowprops=dict(arrowstyle="-|>", color="#5D6D7E", lw=2.4, mutation_scale=24))

ax.set_title("How the Diagnosis Cost-Band Feature Gets Set", fontsize=16, fontweight="bold",
              color="#1B2631", pad=16)

plt.tight_layout()
plt.savefig("data/diagnosis_band_onehot_flow_chart.png", dpi=200, bbox_inches="tight", facecolor="white")
print("saved data/diagnosis_band_onehot_flow_chart.png")
