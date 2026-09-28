import textwrap
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from matplotlib.patches import Rectangle

BASE_DIR = Path(__file__).resolve().parent

AISC_CSV = BASE_DIR / "AISC_data.csv"
CB_XLSX = BASE_DIR / "gold_data.xlsx"
CHART_DIR = BASE_DIR / "charts"
ALT_DIR = CHART_DIR / "alt"

START_DATE = "2000-01-01"
END_DATE = "2026-07-29"
CRIMEA_DATE = "2014-03-18"

GOLD_TICKER = "GC=F"
GLD_TICKER = "GLD"
GDX_TICKER = "GDX"

BLUE = "#2a78d6"      # gold / GLD / primary series
ORANGE = "#eb6834"    # AISC / GDX / secondary series
GRAY_FILL = "#c3c2b7"
CRITICAL = "#d03b3b"
GRID = "#e1e0d9"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"

# fixed figure geometry — this is what actually fixes the margin problem.
# every chart gets the same canvas size and the same reserved margins,
# instead of letting bbox_inches="tight" guess a different crop each time.
FIGSIZE = (11, 5.2)
DPI = 200
MARGINS = dict(left=0.085, right=0.965, top=0.90, bottom=0.17)
MARGINS_2LINE = dict(left=0.085, right=0.965, top=0.90, bottom=0.24)  # for footers that wrap

LEVERAGE_YMAX = 20     # 2013Q2 hit 18.6x — clipped and called out on the chart instead of blowing up the axis
LADDER_QUARTERS = ["2015Q1", "2020Q3", "2022Q1", "2026Q1"]
WGC_Q1_2026_FLOW_ESTIMATE = 244.0  # tonnes, WGC report — sanity check only, not used in any chart
CHART2_XLIM_PAD_DAYS = 120  # room so the "latest" / peak markers aren't flush against the axis edge
CHART6_XLIM_PAD_DAYS = 200  # room for the trough/latest annotation labels
FOOTER_WRAP_WIDTH = 140

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb",
    "axes.edgecolor": GRID,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.labelcolor": INK2,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
})

CHART_DIR.mkdir(exist_ok=True)
ALT_DIR.mkdir(exist_ok=True)

SOURCE_AISC = "Source: AISC digitized from published chart (±$10/oz); GC=F, GLD, GDX via Yahoo Finance."
SOURCE_CB = "Source: gold_data.xlsx, balanced panel of continuously-reporting countries."
SOURCE_MKT = "Source: GLD/GDX via Yahoo Finance."
LABEL_BBOX = dict(boxstyle="round,pad=0.2", fc="#fcfcfb", ec="none", alpha=0.85)

FIGS = []  # (label, value, derivation) -> figures.md at the end


def record(label, value, derivation):
    FIGS.append((label, value, derivation))


# ------------------------------------------------------------------
# chart helpers
# ------------------------------------------------------------------

def new_fig(two_line_footer=False):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(**(MARGINS_2LINE if two_line_footer else MARGINS))
    return fig, ax


def footer(fig, text, wrap=False):
    if wrap:
        text = textwrap.fill(text, width=FOOTER_WRAP_WIDTH)
    fig.text(0.01, 0.02, text, fontsize=8, color=MUTED, ha="left", va="bottom")


def save(fig, path):
    fig.savefig(path, dpi=DPI)  # margins are already reserved, no bbox_inches="tight" needed
    plt.close(fig)


def pad_xlim_days(ax, dmin, dmax, days):
    ax.set_xlim(dmin, dmax + pd.Timedelta(days=days))


# ------------------------------------------------------------------
# AISC + gold price
# ------------------------------------------------------------------

aisc = pd.read_csv(AISC_CSV)
aisc["period"] = pd.PeriodIndex(aisc["quarter"], freq="Q")
aisc = aisc.set_index("period").sort_index()

gc = yf.download(GOLD_TICKER, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)["Close"]
if isinstance(gc, pd.DataFrame):
    gc = gc.iloc[:, 0]
gc.index = pd.to_datetime(gc.index)

gc_q = gc.resample("QE").last()
gc_q.index = gc_q.index.to_period("Q")

merged = aisc.join(gc_q.rename("gold_price"), how="left")
merged["margin"] = merged["gold_price"] - merged["aisc_usd_oz"]
merged["leverage"] = merged["gold_price"] / merged["margin"]
merged["date"] = merged.index.to_timestamp(how="end")

assert merged["gold_price"].isna().sum() == 0, "missing gold price for some AISC quarters"

# Jan-2026 gold peak
peak_window = gc.loc["2026-01-01":"2026-02-15"]
peak_date = peak_window.idxmax()
peak_price = peak_window.max()
peak_quarter = pd.Period(peak_date, freq="Q")
peak_aisc = aisc.loc[peak_quarter, "aisc_usd_oz"]
peak_margin = peak_price - peak_aisc
peak_leverage = peak_price / peak_margin

record("Jan-2026 gold peak date", str(peak_date.date()), "max(GC=F daily close, 2026-01-01..2026-02-15)")
record("Jan-2026 gold peak price", f"${peak_price:,.2f}/oz", "GC=F close on peak date")
record("Jan-2026 peak leverage P/(P-AISC)", f"{peak_leverage:.2f}x",
       f"peak price {peak_price:,.0f} / ({peak_price:,.0f} - {peak_aisc:,.0f} AISC for {peak_quarter})")

ladder_rows = []
for q in LADDER_QUARTERS:
    r = merged.loc[q]
    ladder_rows.append((q, r["gold_price"], r["aisc_usd_oz"], r["leverage"]))
ladder_rows.append((f"Jan-2026 peak ({peak_date.date()})", peak_price, peak_aisc, peak_leverage))

# ------------------------------------------------------------------
# central bank reserves
# ------------------------------------------------------------------

gold_xlsx = pd.read_excel(CB_XLSX)
cb = gold_xlsx.set_index("Country").apply(pd.to_numeric, errors="coerce")
cb_cols = cb.columns.tolist()


def cb_quarter_to_ts(col):
    q, yy = col.split()
    return pd.Period(f"20{yy}{q}", freq="Q").to_timestamp(how="end")


cb_dates = pd.Index([cb_quarter_to_ts(c) for c in cb_cols])

# countries that reported every single quarter — full-history balanced panel
bal_full = cb[cb.notna().all(axis=1)]
cb_total = bal_full.sum(axis=0)
cb_total.index = cb_dates
n_full = len(bal_full)

# quick sanity check against WGC's headline Q1-2026 net buying number, using just
# the last two columns balanced (most countries haven't reported Q1-2026 yet, so
# this is a much smaller panel than the full-history one above)
win2 = cb[cb_cols[-2:]]
bal2 = cb[win2.notna().all(axis=1)]
q1_2026_flow = bal2[cb_cols[-1]].sum() - bal2[cb_cols[-2]].sum()
n_bal2 = len(bal2)
if abs(q1_2026_flow - WGC_Q1_2026_FLOW_ESTIMATE) > 50:
    print(f"note: balanced-panel Q1-2026 flow = {q1_2026_flow:.1f}t (n={n_bal2}) vs WGC's "
          f"~+{WGC_Q1_2026_FLOW_ESTIMATE:.0f}t — most holders haven't reported Q1-2026 yet, "
          f"treating the CB chart as context only, not a quantitative claim.")

cb_flows = []
for i in range(4, 0, -1):
    c_prev, c_cur = cb_cols[-i - 1], cb_cols[-i]
    win = cb[[c_prev, c_cur]]
    bal = cb[win.notna().all(axis=1)]
    tot = bal.sum(axis=0)
    cb_flows.append((c_cur, tot[c_cur] - tot[c_prev], len(bal)))

# ------------------------------------------------------------------
# GLD / GDX daily
# ------------------------------------------------------------------

gld = yf.download(GLD_TICKER, start="2004-01-01", end=END_DATE, progress=False, auto_adjust=True)["Close"]
gdx = yf.download(GDX_TICKER, start="2006-01-01", end=END_DATE, progress=False, auto_adjust=True)["Close"]
if isinstance(gld, pd.DataFrame):
    gld = gld.iloc[:, 0]
if isinstance(gdx, pd.DataFrame):
    gdx = gdx.iloc[:, 0]
gld.index = pd.to_datetime(gld.index)
gdx.index = pd.to_datetime(gdx.index)

# ------------------------------------------------------------------
# chart 1 — gold price vs AISC, margin shaded
# ------------------------------------------------------------------

fig, ax = new_fig()
ax.plot(merged["date"], merged["gold_price"], color=BLUE, lw=2, label="Gold price (GC=F, quarter-end)")
ax.plot(merged["date"], merged["aisc_usd_oz"], color=ORANGE, lw=2, label="AISC (all-in sustaining cost)")
ax.fill_between(merged["date"], merged["aisc_usd_oz"], merged["gold_price"], color=BLUE, alpha=0.12, label="Miner margin")
ax.set_ylabel("US$ / oz")
ax.set_title("Gold price vs. AISC: the margin has exploded")
ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.legend(loc="upper left", frameon=False)
ax.set_xlim(merged["date"].min(), merged["date"].max())
footer(fig, SOURCE_AISC)
save(fig, CHART_DIR / "chart1_gold_vs_aisc.png")

# ------------------------------------------------------------------
# chart 2 — structural leverage ladder
# ------------------------------------------------------------------

fig, ax = new_fig()
ax.plot(merged["date"], merged["leverage"], color=BLUE, lw=2)
ax.set_ylabel("P / (P − AISC)   [x]")
ax.set_title("Structural leverage: P / (P − AISC) collapses as the margin widens")
ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
pad_xlim_days(ax, merged["date"].min(), merged["date"].max(), CHART2_XLIM_PAD_DAYS)
ax.set_ylim(0, LEVERAGE_YMAX- 10)

spike_q = merged["leverage"].idxmax()
spike_row = merged.loc[spike_q]
ax.annotate(f"{spike_q}: {spike_row['leverage']:.1f}x — off scale\n(margin fell to ${spike_row['margin']:,.0f}/oz)",
            xy=(spike_row["date"], LEVERAGE_YMAX), xytext=(spike_row["date"], LEVERAGE_YMAX - 1.6),
            fontsize=9, color=INK2, ha="center", va="top", bbox=LABEL_BBOX,
            arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))

for q in ["2015Q1", "2020Q3"]:
    r = merged.loc[q]
    ax.scatter([r["date"]], [r["leverage"]], color=BLUE, zorder=5, s=30)
    ax.annotate(f"{q}: {r['leverage']:.1f}x", (r["date"], r["leverage"]),
                textcoords="offset points", xytext=(0, 12), fontsize=9, color=INK2, ha="center", bbox=LABEL_BBOX)

latest = merged.iloc[-1]
ax.scatter([latest["date"]], [latest["leverage"]], color=BLUE, zorder=5, s=32)
ax.annotate(f"latest ({merged.index[-1]}): {latest['leverage']:.2f}x", xy=(latest["date"], latest["leverage"]),
            xytext=(-15, 26), textcoords="offset points", fontsize=9, color=INK2, ha="right", va="center",
            bbox=LABEL_BBOX, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))

ax.scatter([peak_date], [peak_leverage], color=CRITICAL, zorder=6, s=40, marker="D")
ax.annotate(f"Jan-2026 peak day: {peak_leverage:.2f}x", xy=(peak_date, peak_leverage),
            xytext=(-15, -30), textcoords="offset points", fontsize=9, color=CRITICAL, ha="right", va="center",
            bbox=LABEL_BBOX, arrowprops=dict(arrowstyle="-", color=CRITICAL, lw=0.8))

footer(fig, SOURCE_AISC)
save(fig, CHART_DIR / "chart2_leverage_ladder.png")

# ------------------------------------------------------------------
# chart 3 — peak-to-now drawdown (rebased), plus an alt 2020 rebase
# ------------------------------------------------------------------

def rebased_chart(rebase_date, out_path, title):
    rb = pd.Timestamp(rebase_date)
    g = gld.loc[gld.index >= rb]
    m = gdx.loc[gdx.index >= rb]
    g_idx = g / g.iloc[0] * 100
    m_idx = m / m.iloc[0] * 100

    fig, ax = new_fig()
    ax.plot(g_idx.index, g_idx, color=BLUE, lw=2, label="GLD (rebased 100)")
    ax.plot(m_idx.index, m_idx, color=ORANGE, lw=2, label="GDX (rebased 100)")
    ax.axhline(100, color=GRAY_FILL, lw=1, ls="--")
    ax.set_ylabel(f"Index (100 = {rb.date()})")
    ax.set_title(title)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(loc="best", frameon=False)

    for s, c, name in [(g_idx, BLUE, "GLD"), (m_idx, ORANGE, "GDX")]:
        ax.annotate(f"{name}: {s.iloc[-1]:.0f}", (s.index[-1], s.iloc[-1]),
                    textcoords="offset points", xytext=(6, 0), fontsize=9, color=c, va="center")

    footer(fig, SOURCE_MKT)
    save(fig, out_path)
    return g_idx.iloc[-1] - 100, m_idx.iloc[-1] - 100


peak_gld_pct, peak_gdx_pct = rebased_chart("2026-01-29", CHART_DIR / "chart3_drawdown_peak.png",
                                            "GDX gave you bullion-like downside for miner-specific risk")
realized_beta_peaknow = peak_gdx_pct / peak_gld_pct

alt_gld_pct, alt_gdx_pct = rebased_chart("2020-01-01", ALT_DIR / "chart3_alt_2020_rebase.png",
                                          "Since 2020: GDX has outperformed gold — the opposite story")

# ------------------------------------------------------------------
# chart 4 — realized beta (252d rolling) vs structural leverage
# ------------------------------------------------------------------

ret = pd.concat([gld.pct_change().rename("gld"), gdx.pct_change().rename("gdx")], axis=1).dropna()
roll_beta = (ret["gdx"].rolling(252).cov(ret["gld"]) / ret["gld"].rolling(252).var()).dropna()

fig, ax = new_fig(two_line_footer=True)
ax.plot(roll_beta.index, roll_beta, color=ORANGE, lw=1.3, alpha=0.9, label="252-day rolling beta, GDX vs GLD (daily)")
ax.plot(merged["date"], merged["leverage"], color=BLUE, lw=2.2, drawstyle="steps-post",
        label="Structural leverage P/(P−AISC) (quarterly)")
ax.set_ylabel("Ratio [x]")
ax.set_title("Realized rolling beta vs. structural leverage — descriptive comparison only")
ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.set_xlim(max(roll_beta.index.min(), merged["date"].min()), merged["date"].max())
ax.set_ylim(0, LEVERAGE_YMAX)
ax.legend(loc="upper left", frameon=False, fontsize=9)

footer(fig, SOURCE_AISC + f" Structural leverage axis clipped at {LEVERAGE_YMAX:.1f}x (2013Q2 peaked at "
       f"{merged['leverage'].max():.1f}x); rolling 252-day windows overlap heavily — this is a visual "
       "comparison, not a statistical test.", wrap=True)
save(fig, CHART_DIR / "chart4_beta_vs_leverage.png")

# ------------------------------------------------------------------
# chart 5 — central bank reserves (context only)
# ------------------------------------------------------------------

fig, ax = new_fig()
ax.plot(cb_total.index, cb_total.values, color=BLUE, lw=2)
ax.axvspan(pd.Timestamp("2022-02-24"), cb_total.index.max(), color=GRAY_FILL, alpha=0.4,
           label="Post Russia/Ukraine invasion (Feb 2022)")
ax.axvspan(pd.Timestamp(CRIMEA_DATE), pd.Timestamp("2022-02-24"), color=GRAY_FILL, alpha=0.2,
           label="Russian annexation of Crimea (First wave of sanctions)")
ax.set_ylabel("Tonnes")
ax.set_title(f"Central bank gold reserves — balanced panel ({n_full} continuously-reporting countries)")
ax.xaxis.set_major_locator(mdates.YearLocator(4))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.legend(loc="upper left", frameon=False)
footer(fig, SOURCE_CB + " Context only — no quantitative claim is made from this chart.")
save(fig, CHART_DIR / "chart5_cb_reserves.png")

# ------------------------------------------------------------------
# chart 6 — AISC cost curve
# ------------------------------------------------------------------

trough_q = merged["aisc_usd_oz"].idxmin()
trough_val = merged["aisc_usd_oz"].min()
latest_q = merged.index[-1]
latest_val = merged["aisc_usd_oz"].iloc[-1]
pct_off_trough = (latest_val - trough_val) / trough_val * 100
six_q_val = merged["aisc_usd_oz"].iloc[-7]
pct_6q = (latest_val - six_q_val) / six_q_val * 100

fig, ax = new_fig()
ax.plot(merged["date"], merged["aisc_usd_oz"], color=ORANGE, lw=2)
ax.set_ylabel("AISC (US$ / oz)")
ax.set_title("AISC cost curve: a 20-quarter trend, not a recent shock")
ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
pad_xlim_days(ax, merged["date"].min(), merged["date"].max(), CHART6_XLIM_PAD_DAYS)

trough_date = merged.loc[trough_q, "date"]
ax.scatter([trough_date], [trough_val], color=BLUE, zorder=5, s=30)
ax.annotate(f"trough {trough_q}: ${trough_val:,.0f}", (trough_date, trough_val),
            textcoords="offset points", xytext=(0, 12), fontsize=9, color=INK2, ha="center")

latest_date = merged.loc[latest_q, "date"]
ax.scatter([latest_date], [latest_val], color=ORANGE, zorder=5, s=30)
ax.annotate(f"{latest_q}: ${latest_val:,.0f}\n+{pct_off_trough:.0f}% off trough, +{pct_6q:.0f}% last 6q",
            xy=(latest_date, latest_val), textcoords="offset points", xytext=(-10, -8), fontsize=9,
            color=INK2, ha="right", va="top", bbox=LABEL_BBOX)

footer(fig, SOURCE_AISC)
save(fig, CHART_DIR / "chart6_aisc_cost_curve.png")

# ------------------------------------------------------------------
# chart 7 — leverage vs. gold price: spot-anchored ladder. The point isn't
# that leverage decays on the upside (true, irrelevant) — it's that leverage
# returns fast on the downside, because P is much closer to AISC than to
# the upside prices. AISC held fixed at the current quarter's cost base.
# ------------------------------------------------------------------
# identity, not a forecast: leverage L(P) = P / (P - AISC).

LV_STEP = 500
N_UPSIDE = 3
N_DOWNSIDE = 5
DOWNSIDE_FLOOR_MULT = 1.10  # stop stepping down once price nears AISC (leverage blows up / becomes absurd)

aisc_now = latest["aisc_usd_oz"]
q1_price = latest["gold_price"]          # 2026Q1 quarter-end print — stale, kept for continuity with other charts
spot_price = gc.iloc[-1]                 # latest daily close — the actually-current number
spot_date = gc.index[-1]

up_start = np.ceil((spot_price + 1) / LV_STEP) * LV_STEP
upside_prices = [up_start + k * LV_STEP for k in range(N_UPSIDE)]

down_start = np.floor((spot_price - 1) / LV_STEP) * LV_STEP
downside_prices = []
p = down_start
while len(downside_prices) < N_DOWNSIDE and p > aisc_now * DOWNSIDE_FLOOR_MULT:
    downside_prices.append(p)
    p -= LV_STEP

lv_entries = [(f"${p:,.0f}", p) for p in upside_prices]
lv_entries.append((f"${q1_price:,.0f}  (2026Q1 quarter-end)", q1_price))
lv_entries.append((f"${spot_price:,.0f}  (spot, {spot_date.date()})", spot_price))
lv_entries.extend((f"${p:,.0f}", p) for p in downside_prices)
lv_entries.sort(key=lambda r: r[1], reverse=True)

lv_rows = []
for label, p in lv_entries:
    margin = p - aisc_now
    lev = p / margin
    is_anchor = "quarter-end" in label or "spot," in label
    lv_rows.append((label, p, margin, lev, is_anchor))

spot_lev = spot_price / (spot_price - aisc_now)
lev_min = min(r[3] for r in lv_rows)
lev_max = max(r[3] for r in lv_rows)
blue_rgb = mcolors.to_rgb(BLUE)
critical_rgb = mcolors.to_rgb(CRITICAL)

fig, ax = new_fig(two_line_footer=True)
ax.axis("off")
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.set_title("Leverage vs. gold price: flat above spot, steep on the way back down toward AISC")

col_x = [0.03, 0.42, 0.72]
headers = ["Gold price", "Margin  (P − AISC)", "Leverage  P/(P−AISC)"]
n_rows = len(lv_rows)
top, bottom = 0.86, 0.06
row_h = (top - bottom) / n_rows

for c, h in zip(col_x, headers):
    ax.text(c, top + row_h * 0.15, h, fontsize=10, fontweight="bold", color=INK2, ha="left", va="bottom")
ax.plot([0.0, 1.0], [top, top], color=GRID, lw=1.2, transform=ax.transAxes)

for i, (label, p, margin, lev, is_anchor) in enumerate(lv_rows):
    y = top - row_h * (i + 1)
    if i % 2 == 0:
        ax.add_patch(Rectangle((0.0, y - row_h * 0.5 + row_h * 0.05), 1.0, row_h * 0.9,
                                facecolor=GRID, alpha=0.35, edgecolor="none", zorder=0))
    downside = lev > spot_lev
    if downside:
        frac = (lev - spot_lev) / max(lev_max - spot_lev, 1e-9)
        base, cap = critical_rgb, 0.60
    else:
        frac = (spot_lev - lev) / max(spot_lev - lev_min, 1e-9)
        base, cap = blue_rgb, 0.40
    alpha = 0.10 + cap * frac
    ax.add_patch(Rectangle((col_x[2] - 0.02, y - row_h * 0.5 + row_h * 0.05), 0.26, row_h * 0.9,
                            facecolor=base, alpha=alpha, edgecolor="none", zorder=1))
    txt_color = "white" if (downside and alpha > 0.45) else INK
    weight = "bold" if is_anchor else "normal"
    ax.text(col_x[0], y, label, fontsize=9.5, color=INK, ha="left", va="center", fontweight=weight, zorder=2)
    ax.text(col_x[1], y, f"${margin:,.0f}", fontsize=9.5, color=INK, ha="left", va="center", fontweight=weight, zorder=2)
    ax.text(col_x[2], y, f"{lev:.2f}x", fontsize=9.5, color=txt_color, ha="left", va="center", fontweight=weight, zorder=2)

footer(fig, SOURCE_AISC + " Leverage = P/(P−AISC), an identity, not a forecast. AISC held fixed at the current "
       "quarter's reported cost base. Rows are round-number price levels around spot; the 2026Q1 quarter-end "
       "print is shown separately since it is several months stale relative to the spot row.", wrap=True)
save(fig, CHART_DIR / "chart7_leverage_vs_price.png")

# ------------------------------------------------------------------
# figures.md + sanity dump
# ------------------------------------------------------------------

if FIGS:
    with open("figures.md", "w") as f:
        f.write("# Figures\n\n| Label | Value | Derivation |\n|---|---|---|\n")
        for label, value, derivation in FIGS:
            f.write(f"| {label} | {value} | {derivation} |\n")


print("done")