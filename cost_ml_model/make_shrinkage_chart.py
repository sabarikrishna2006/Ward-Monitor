import matplotlib.pyplot as plt
import numpy as np

labels = ["n=1\n(710 diagnoses)", "n=2", "n=3-5", "n=6-10", "n=11+"]
raw_mae = [159536, 177501, 159806, 153171, 124573]
shrunk_mae = [159536, 151649, 148803, 149355, 124879]

x = np.arange(len(labels))
width = 0.35

fig, ax = plt.subplots(figsize=(9, 5.5))
b1 = ax.bar(x - width/2, raw_mae, width, label="Raw average (no shrinkage)", color="#e07b54")
b2 = ax.bar(x + width/2, shrunk_mae, width, label="Shrunk average (k=3)", color="#4c8bf5")

ax.set_ylabel("Prediction error (MAE, Rs)")
ax.set_xlabel("Sample size behind the diagnosis's average cost")
ax.set_title("Leave-one-out validation: raw vs. shrunk average cost as a predictor\nfor a new patient's bill, by diagnosis sample size")
ax.set_xticks(x)
ax.set_xticklabels(labels)
ax.legend()
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))

for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h/1000:.0f}k", xy=(bar.get_x() + bar.get_width()/2, h),
                    xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)

plt.tight_layout()
plt.savefig("data/shrinkage_validation_chart.png", dpi=200)
print("saved data/shrinkage_validation_chart.png")
