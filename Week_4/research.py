# ============================================================
# ISSUE 5 — "Canada Outsourced Its Bond Market"
# Research notebook: yields, flows, correlation, curve, event study
# ============================================================
# Data files are downloaded automatically into Week_4/data/ on first run
# and reused after that. Delete a file to force a refresh.
#   36-10-0028-01  -> data/flows.csv          (monthly portfolio flows)
#   36-10-0444-01  -> data/tenor.csv          (foreign holdings by maturity)
#   36-10-0486-01  -> data/holders_region.csv (foreign holdings by region)
#   36-10-0030-01  -> data/flows_region.csv   (portfolio flows by region)
#   US Treasury TIC SLT Table 5 -> data/tic_holders.txt (UST holders by country)
#   US Treasury TIC SLT Table 3 + legacy S-form -> data/tic_treasury_flows*.txt
#   36-10-0003 (StatCan) -> data/gov_issuance.csv; US Treasury MSPD -> data/us_mspd.csv
#   Natural Earth 110m countries -> data/world.geojson (map basemap)
# ============================================================

import csv, io, json, os, textwrap, zipfile, requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

pd.set_option("display.width", 140)
plt.rcParams.update({
    "figure.figsize": (11, 5.5), "figure.dpi": 130,
    "axes.grid": True, "grid.alpha": 0.25,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10,
})

START = "2010-01-01"
# resolve relative to this file so outputs stay inside Week_4 regardless of cwd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(BASE_DIR, "charts")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(CHART_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

C_CA, C_US, C_ACC = "#D32F2F", "#1565C0", "#F57C00"


# ============================================================
# STEP 0 — DATA LAYER
# ============================================================

def boc(series, start=START):
    """Bank of Canada Valet API. No key required."""
    url = f"https://www.bankofcanada.ca/valet/observations/{series}/json"
    r = requests.get(url, params={"start_date": start}, timeout=30)
    r.raise_for_status()
    obs = r.json()["observations"]
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["d"])
    df[series] = pd.to_numeric(
        df[series].apply(lambda x: x.get("v") if isinstance(x, dict) else np.nan),
        errors="coerce")
    return df.set_index("date")[[series]]


def fred(sid, start=START):
    """FRED CSV endpoint. No key required. Missing values arrive as '.'"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    df = pd.read_csv(url, parse_dates=[0], index_col=0)
    df.columns = [sid]
    df[sid] = pd.to_numeric(df[sid], errors="coerce")
    return df.loc[start:]


print("Pulling BoC...")
GOC = {"2Y": "BD.CDN.2YR.DQ.YLD", "5Y": "BD.CDN.5YR.DQ.YLD",
       "10Y": "BD.CDN.10YR.DQ.YLD", "30Y": "BD.CDN.LONG.DQ.YLD"}   # BoC's long benchmark is the 30Y
goc = pd.concat([boc(v).rename(columns={v: f"CA_{k}"}) for k, v in GOC.items()], axis=1)

print("Pulling FRED...")
ust = pd.concat([fred(s) for s in ["DGS2", "DGS10", "DGS30"]], axis=1)
ust.columns = ["US_2Y", "US_10Y", "US_30Y"]

# inner join on shared business days, short ffill only (different holiday calendars)
df = goc.join(ust, how="inner").ffill(limit=3)

df["ca_10s30s"] = df["CA_30Y"] - df["CA_10Y"]
df["us_10s30s"] = df["US_30Y"] - df["US_10Y"]
df["curve_diff"] = df["ca_10s30s"] - df["us_10s30s"]
df["ca_us_10y"]  = df["CA_10Y"] - df["US_10Y"]

print(f"\n{len(df)} obs | {df.index.min().date()} -> {df.index.max().date()}")
print(df[["CA_10Y", "US_10Y", "ca_us_10y", "ca_10s30s"]].tail(3).round(3))


# ============================================================
# STEP 1 — 10s30s PERCENTILE  [GATES THE TRADE]
# ============================================================
print("\n" + "=" * 60 + "\nSTEP 1 — CURVE PERCENTILE\n" + "=" * 60)


def percentile_report(series, label):
    s = series.dropna()
    cur = s.iloc[-1]
    pct = (s < cur).mean() * 100
    z = (cur - s.mean()) / s.std()
    print(f"\n{label}")
    print(f"  current {cur*100:7.1f} bp   pct {pct:5.1f}   z {z:+.2f}")
    print(f"  mean {s.mean()*100:7.1f}   min {s.min()*100:7.1f}   max {s.max()*100:7.1f}")
    for p in [10, 25, 50, 75, 90]:
        print(f"    p{p:<3} {np.percentile(s, p)*100:7.1f} bp")
    return {"current": cur, "pct": pct, "z": z,
            "p75": np.percentile(s, 75), "p25": np.percentile(s, 25)}


ca_curve = percentile_report(df["ca_10s30s"], "CANADA 10s30s")
us_curve = percentile_report(df["us_10s30s"], "US 10s30s")
dif_curve = percentile_report(df["curve_diff"], "CA minus US 10s30s  <-- the dislocation stat")
cross     = percentile_report(df["ca_us_10y"], "CA-US 10Y SPREAD (context only)")

print("\n--- TRADE GATE ---")
if ca_curve["pct"] < 50:
    print(f"LIVE. Canada 10s30s at p{ca_curve['pct']:.0f}. Steepener has room.")
elif ca_curve["pct"] < 75:
    print(f"MARGINAL. p{ca_curve['pct']:.0f}. Check curve_diff before committing.")
else:
    print(f"DEAD. p{ca_curve['pct']:.0f} — supply story is priced. Publish without a trade.")
print(f"Suggested target = p75 = {ca_curve['p75']*100:.1f} bp "
      f"({(ca_curve['p75']-ca_curve['current'])*100:+.1f} bp from spot)")

# stop from realized vol of the spread
vol20 = df["ca_10s30s"].diff().rolling(20).std().iloc[-1] * 100
print(f"20d realized vol of spread: {vol20:.2f} bp/day | 1.5x stop = {1.5*vol20:.1f} bp")
rr = ((ca_curve["p75"] - ca_curve["current"]) * 100) / (1.5 * vol20)
print(f"Implied R:R = {rr:.2f} : 1   (need >2.0)")


# ============================================================
# STEP 2 — ROLLING GoC/UST CORRELATION  [HEADLINE TEST]
# ============================================================
print("\n" + "=" * 60 + "\nSTEP 2 — CORRELATION\n" + "=" * 60)

# CRITICAL: correlate daily CHANGES, not levels. Levels give spurious 0.9+.
chg = df[["CA_10Y", "US_10Y"]].diff()

corr = pd.DataFrame({
    f"{w}d": chg["CA_10Y"].rolling(w).corr(chg["US_10Y"])
    for w in (63, 126, 252)
})

print(corr.tail(1).round(3).to_string())
for w in ("63d", "126d", "252d"):
    s = corr[w].dropna()
    print(f"  {w}: now {s.iloc[-1]:.3f} | 2015-19 avg {s['2015':'2019'].mean():.3f} "
          f"| 2024+ avg {s['2024':].mean():.3f}")

pre, post = corr["126d"]['2015':'2019'].mean(), corr["126d"]['2024':].mean()
print(f"\nShift: {pre:.3f} -> {post:.3f} ({post-pre:+.3f})")
print("If positive and material, the beta claim in section 5 survives.")
print("Note in print: quarterly ownership data gives ~20 obs. Describe, don't infer.")


# ============================================================
# STEP 3 — DOMESTIC DATA SENSITIVITY  [CLEANER IDENTIFICATION]
# ============================================================
print("\n" + "=" * 60 + "\nSTEP 3 — EVENT STUDY\n" + "=" * 60)

# >>> PASTE REAL RELEASE DATES <
# StatCan CPI: https://www150.statcan.gc.ca/n1/en/subjects/prices_and_price_indexes
# StatCan LFS: https://www150.statcan.gc.ca/n1/en/subjects/labour
CA_CPI_2023 = ["2023-01-17","2023-02-21","2023-03-21","2023-04-18","2023-05-16","2023-06-27",
               "2023-07-18","2023-08-15","2023-09-19","2023-10-17","2023-11-21","2023-12-19"]
CA_LFS_2023 = ["2023-01-06","2023-02-10","2023-03-10","2023-04-06","2023-05-05","2023-06-09",
               "2023-07-07","2023-08-04","2023-09-08","2023-10-06","2023-11-03","2023-12-01"]
CA_CPI_2026 = []   # <-- fill
CA_LFS_2026 = []   # <-- fill

# Contamination dates: FOMC decisions, US CPI prints, BoC decisions
CONTAM = ["2026-09-16", "2026-09-11", "2026-09-02"]   # <-- extend


def event_study(dates, series, contam=CONTAM, window=1, baseline=60):
    """Abs 1d move on release days, normalized by surrounding baseline vol."""
    if not dates:
        return None
    d = pd.to_datetime(dates)
    bad = pd.to_datetime(contam) if contam else pd.DatetimeIndex([])
    keep = [x for x in d if not any(abs((x - b).days) <= window for b in bad)]
    dropped = len(d) - len(keep)

    absmove = series.diff().abs()
    rows = []
    for dt in keep:
        idx = absmove.index.searchsorted(dt)
        if idx >= len(absmove):
            continue
        ev = absmove.iloc[idx]
        lo, hi = max(0, idx - baseline // 2), min(len(absmove), idx + baseline // 2)
        base = absmove.iloc[lo:hi].drop(absmove.index[idx], errors="ignore").mean()
        if pd.notna(ev) and pd.notna(base) and base > 0:
            rows.append({"date": absmove.index[idx], "move_bp": ev * 100,
                         "base_bp": base * 100, "ratio": ev / base})
    r = pd.DataFrame(rows, columns=["date", "move_bp", "base_bp", "ratio"])
    if r.empty:
        return None
    return {"n": len(r), "dropped": dropped,
            "mean_move": r["move_bp"].mean(), "mean_ratio": r["ratio"].mean(),
            "median_ratio": r["ratio"].median(), "detail": r}


for name, d23, d26 in [("CPI", CA_CPI_2023, CA_CPI_2026),
                       ("LFS", CA_LFS_2023, CA_LFS_2026)]:
    a, b = event_study(d23, df["CA_10Y"]), event_study(d26, df["CA_10Y"])
    print(f"\n--- Canadian {name} ---")
    if a: print(f"  2023: n={a['n']} (dropped {a['dropped']}) "
                f"move {a['mean_move']:.2f}bp  ratio {a['mean_ratio']:.2f}")
    if b: print(f"  2026: n={b['n']} (dropped {b['dropped']}) "
                f"move {b['mean_move']:.2f}bp  ratio {b['mean_ratio']:.2f}")
    if a and b and b["n"]:
        print(f"  ratio {a['mean_ratio']:.2f} -> {b['mean_ratio']:.2f} "
              f"({(b['mean_ratio']/a['mean_ratio']-1)*100:+.0f}%)")
        print("  Falling ratio = GoC less sensitive to domestic data. Thesis supported.")
    print("  n~12/yr. Report the ratio and n. No p-values.")


# ============================================================
# STEP 4 — FLOWS
# ============================================================
print("\n" + "=" * 60 + "\nSTEP 4 — FLOWS vs YIELDS\n" + "=" * 60)


def fetch_file(url, name):
    """Download once into DATA_DIR, reuse the cached copy after that."""
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        print(f"  downloading {name} ...")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(r.content)
    return path


def load_statcan(pid, name):
    """Full-table StatCan CSV, pulled from the zip endpoint if not cached."""
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        try:
            print(f"  downloading StatCan {pid} -> {name} ...")
            r = requests.get(f"https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-eng.zip", timeout=120)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z, open(path, "wb") as fh:
                fh.write(z.read(f"{pid}.csv"))
        except Exception as e:
            print(f"  MISSING {path} — download failed ({e}), see header.")
            return None
    # utf-8-sig: StatCan CSVs start with a BOM that otherwise corrupts "REF_DATE"
    d = pd.read_csv(path, low_memory=False, encoding="utf-8-sig")
    d.columns = [c.strip().strip('"') for c in d.columns]
    return d


flows_raw = load_statcan("36100028", "flows.csv")
flows = None

if flows_raw is not None:
    print("  Columns:", list(flows_raw.columns)[:8])
    cat_col = next((c for c in ["Type of instrument and issuer", "Instrument",
                                "Portfolio investment"] if c in flows_raw.columns), None)
    if cat_col:
        cats = flows_raw[cat_col].dropna().unique()
        fed = [c for c in cats if "ederal" in str(c) and "bond" in str(c).lower()]
        print("  Federal bond lines found:", fed[:5])
        # >>> set FED_LINE to the exact federal BOND label (not money market) <
        FED_LINE = fed[0] if fed else None
        if FED_LINE:
            f = flows_raw[flows_raw[cat_col] == FED_LINE]
            # table also carries Sales and Purchases rows for each month
            if "Summary of transactions" in f.columns:
                f = f[f["Summary of transactions"] == "Net flows"]
            f = f.copy()
            f["date"] = pd.to_datetime(f["REF_DATE"])
            f["flow"] = pd.to_numeric(f["VALUE"], errors="coerce")
            flows = f.set_index("date")["flow"].sort_index()
            print(f"  Using: {FED_LINE}  ({len(flows)} months)")
            print(flows.tail(6).round(0).to_string())

if flows is not None:
    m_yield = df["CA_10Y"].resample("ME").last()
    j = pd.DataFrame({"flow": flows.resample("ME").last(),
                      "dy": m_yield.diff() * 100}).dropna().loc["2025":]
    if len(j) > 4:
        r = np.corrcoef(j["flow"], j["dy"])[0, 1]
        print(f"\n  n={len(j)}  corr={r:+.3f}  R2={r**2:.3f}")
        print("  Expect noise at this n. Report sign and R2, then move on.")

# Arithmetic tail scenario — BoC SAN 2025-20: 1% of supply sold -> ~0.2% price drop
print("\n--- TAIL SCENARIO (arithmetic, no regression) ---")
FOREIGN_SHARE, DURATION_10Y = 0.45, 8.5   # <-- verify duration from CTD
for liq in (0.10, 0.25):
    supply_pct = FOREIGN_SHARE * liq * 100
    price_drop = supply_pct * 0.2
    print(f"  {liq:.0%} of foreign stock sold = {supply_pct:.1f}% of supply "
          f"-> {price_drop:.1f}% price -> ~{price_drop/DURATION_10Y*100:.0f} bp")


# ============================================================
# STEP 5 — TENOR BREAKDOWN  [GATES TRADE STRUCTURE]
# ============================================================
print("\n" + "=" * 60 + "\nSTEP 5 — FOREIGN HOLDINGS BY MATURITY\n" + "=" * 60)

tenor_raw = load_statcan("36100444", "tenor.csv")
tenor = None
if tenor_raw is not None:
    mat_col = next((c for c in tenor_raw.columns if "maturity" in c.lower()), None)
    if mat_col:
        print("  Buckets:", list(tenor_raw[mat_col].dropna().unique())[:8])
        # keep one series per bucket: federal bonds at market value, no "All maturities" total
        TENOR_FILTER = {"Type of instrument": "Canadian bonds",
                        "Sector": "Federal government",
                        "Valuation": "Market value"}
        t = tenor_raw[tenor_raw[mat_col] != "All maturities"]
        for col, val in TENOR_FILTER.items():
            if col in t.columns:
                t = t[t[col] == val]
        t = t.copy()
        t["date"] = pd.to_datetime(t["REF_DATE"])
        t["v"] = pd.to_numeric(t["VALUE"], errors="coerce")
        tenor = t.pivot_table(index="date", columns=mat_col, values="v", aggfunc="sum")
        share = tenor.div(tenor.sum(axis=1), axis=0) * 100
        print("\n  Share by bucket (%):")
        print(share.tail(3).round(1).to_string())
        print("\n  Short/medium skew -> steepener confirmed by ownership data.")
        print("  Long-end skew     -> trade logic inverts. Rethink section 6.")


# ============================================================
# STEP 6 — HEDGING COST PROXY  [TIMEBOX 2 HOURS]
# ============================================================
print("\n" + "=" * 60 + "\nSTEP 6 — HEDGED PICKUP (PROXY)\n" + "=" * 60)
print("Clean version needs CAD/USD xccy basis (Bloomberg/Refinitiv).")
print("Proxy below uses CORRA-SOFR and IGNORES the basis — weakest exactly")
print("when the story matters most. Label it a proxy in the chart footnote.")

try:
    corra = boc("AVG.INTWO")                      # CORRA
    sofr  = fred("SOFR")
    hedge = pd.DataFrame({"corra": corra.iloc[:, 0], "sofr": sofr.iloc[:, 0]}).ffill(limit=3)
    hedge["cost"] = hedge["corra"] - hedge["sofr"]          # CAD->USD hedge cost proxy
    h = df.join(hedge["cost"], how="inner")
    h["hedged_pickup"] = (h["CA_10Y"] - h["cost"]) - h["US_10Y"]
    print(f"\n  Hedged pickup now: {h['hedged_pickup'].iloc[-1]*100:+.1f} bp")
    print(h["hedged_pickup"].loc["2025":].resample("QE").last().mul(100).round(1).to_string())
    print("\n  Widening as inflows accelerated -> mechanism supported.")
except Exception as e:
    print(f"  Proxy failed ({e}). Write section 3 qualitatively — it stands")
    print("  on BoC research and flow data without this chart.")
    h = None


# ============================================================
# CHARTS
# ============================================================
print("\n" + "=" * 60 + "\nCHARTS\n" + "=" * 60)

# Chart 1 — ownership crossover (HERO). Needs manual data entry.
own = pd.DataFrame({
    "date": pd.to_datetime(["2019-12-31", "2026-06-30"]),   # <-- fill quarterly series
    "foreign": [33.0, 45.0],
    "domestic": [np.nan, 42.9],
}).set_index("date")

fig, ax = plt.subplots()
ax.plot(own.index, own["foreign"], "o-", color=C_CA, lw=2.5, label="Non-resident")
ax.plot(own.index, own["domestic"], "o-", color=C_US, lw=2.5, label="Domestic")
ax.set_title("Foreigners now own more of Canada's debt than Canadians do",
             fontweight="bold", loc="left")
ax.set_ylabel("Share of GoC bonds outstanding (%)")
ax.legend(frameon=False)
ax.text(0.01, -0.16, "Source: StatCan, National Bank. PLACEHOLDER — fill quarterly series.",
        transform=ax.transAxes, fontsize=8, color="gray")
plt.tight_layout(); plt.savefig(os.path.join(CHART_DIR, "1_ownership.png"), bbox_inches="tight"); plt.show()

# Chart 2 — monthly federal bond purchases
if flows is not None:
    f2 = flows.loc["2024":]
    fig, ax = plt.subplots()
    ax.bar(f2.index, f2.values, width=20,
           color=[C_CA if v > 0 else "#999" for v in f2.values])
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title("Foreign purchases of Canadian federal bonds, monthly",
                 fontweight="bold", loc="left")
    ax.set_ylabel("C$ millions")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    plt.tight_layout(); plt.savefig(os.path.join(CHART_DIR, "2_flows.png"), bbox_inches="tight"); plt.show()

# Chart 3 — correlation
fig, ax = plt.subplots()
ax.plot(corr.index, corr["126d"], color=C_CA, lw=1.8, label="126d rolling corr")
ax.plot(corr.index, corr["252d"], color=C_US, lw=1.2, alpha=0.6, label="252d")
ax.axhline(corr["126d"]['2015':'2019'].mean(), ls="--", color="gray", lw=1,
           label="2015-19 avg")
ax.set_title("GoC 10Y vs UST 10Y — rolling correlation of daily changes",
             fontweight="bold", loc="left")
ax.set_ylabel("Correlation"); ax.set_ylim(0, 1); ax.legend(frameon=False)
plt.tight_layout(); plt.savefig(os.path.join(CHART_DIR, "3_correlation.png"), bbox_inches="tight"); plt.show()

# Chart 4 — curve with percentile band
s = df["ca_10s30s"].dropna() * 100
fig, ax = plt.subplots()
ax.plot(s.index, s.values, color=C_CA, lw=1.4)
ax.axhspan(np.percentile(s, 25), np.percentile(s, 75), color=C_ACC, alpha=0.12,
           label="p25-p75")
ax.axhline(s.iloc[-1], color="k", ls="--", lw=1.2,
           label=f"spot {s.iloc[-1]:.0f}bp (p{ca_curve['pct']:.0f})")
ax.set_title("Canada 10s30s", fontweight="bold", loc="left")
ax.set_ylabel("bp"); ax.legend(frameon=False)
plt.tight_layout(); plt.savefig(os.path.join(CHART_DIR, "4_curve.png"), bbox_inches="tight"); plt.show()

# Chart 5 — tenor
if tenor is not None:
    sh = tenor.div(tenor.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots()
    ax.stackplot(sh.index, *[sh[c] for c in sh.columns], labels=list(sh.columns), alpha=0.85)
    ax.set_title("Foreign holdings of Canadian debt by remaining maturity",
                 fontweight="bold", loc="left")
    ax.set_ylabel("% of foreign-held stock")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    plt.tight_layout(); plt.savefig(os.path.join(CHART_DIR, "5_tenor.png"), bbox_inches="tight"); plt.show()


# ============================================================
# EXPLAINER CHARTS — walk the reader through the mechanism
#   6  yields move together      9  who holds (regions, over time)
#   7  curves compared          10  who bought in the last 12 months
#   8  size of the inflow       11  who bought the NEW bonds: map (since 2020) + 11b bars
#                              12  world maps: Canada vs US holders
#   + hedged pickup (7b) when the CORRA-SOFR proxy loaded
# ============================================================
print("\n" + "=" * 60 + "\nEXPLAINER CHARTS\n" + "=" * 60)

INK_MUTED, LAND, SEA = "#898781", "#e1e0d9", "#fcfcfb"
# fixed categorical order (validated palette), one slot per StatCan region
REGIONS = {
    "United States": ("United States", "#2a78d6"),
    "United Kingdom": ("United Kingdom", "#eb6834"),
    "Other European Union countries": ("Other EU", "#1baf7a"),
    "Japan": ("Japan", "#eda100"),
    "Other Organisation for Economic Co-operation and Development (OECD) countries":
        ("Other OECD", "#e87ba4"),
    "All other countries": ("All other", "#008300"),
}


def source_note(ax, text, y=-0.14, width=160):
    ax.text(0.0, y, textwrap.fill(text, width), transform=ax.transAxes,
            fontsize=8, color=INK_MUTED, va="top")


def save(name):
    plt.tight_layout()
    plt.savefig(os.path.join(CHART_DIR, name), bbox_inches="tight")
    plt.show()


def pad_right(ax, first, last, days):
    """Leave room for end labels without drawing tick labels for future years."""
    ax.set_xlim(first, last + pd.Timedelta(days=days))
    lim = mdates.date2num(last)
    ax.set_xticks([t for t in ax.get_xticks() if t <= lim])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def end_labels(ax, x, items, min_gap=28):
    """items: [(y, text, color)]. Labels at the line ends, pushed apart if they would collide."""
    fig = ax.figure
    fig.tight_layout()
    fig.canvas.draw()
    ys = [ax.transData.transform((mdates.date2num(x), y))[1] for y, _, _ in items]
    order = sorted(range(len(items)), key=lambda i: ys[i])
    placed = []
    for i in order:
        py = ys[i] if not placed else max(ys[i], placed[-1] + min_gap)
        placed.append(py)
        y, text, color = items[i]
        ax.annotate(text, (x, y), xytext=(6, (py - ys[i]) * 72 / fig.dpi),
                    textcoords="offset points", va="center", fontsize=9, color="#0b0b0b",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, lw=1))


# Chart 6 — Canadian 10Y yields are tied to Treasuries
y10 = df[["CA_10Y", "US_10Y"]].dropna()
fig, ax = plt.subplots()
ax.plot(y10.index, y10["US_10Y"], color=C_US, lw=2)
ax.plot(y10.index, y10["CA_10Y"], color=C_CA, lw=2)
ax.set_title("Canadian 10-year yields move with Treasuries, now about 1 point lower",
             fontweight="bold", loc="left")
ax.set_ylabel("Yield (%)")
pad_right(ax, y10.index[0], y10.index[-1], 800)
end_labels(ax, y10.index[-1], [
    (y10["US_10Y"].iloc[-1], f"US 10Y {y10['US_10Y'].iloc[-1]:.2f}%", C_US),
    (y10["CA_10Y"].iloc[-1], f"Canada 10Y {y10['CA_10Y'].iloc[-1]:.2f}%", C_CA)])
source_note(ax, f"Gap today: {cross['current']*100:.0f} bp, wider than {100-cross['pct']:.0f}% "
                "of days since 2010. Source: Bank of Canada, FRED.", y=-0.08)
save("6_yields.png")

# Chart 7 — 10s30s curves side by side (the dislocation)
fig, ax = plt.subplots()
ax.axhline(0, color="#c3c2b7", lw=1)
ax.plot(df.index, df["us_10s30s"] * 100, color=C_US, lw=1.6)
ax.plot(df.index, df["ca_10s30s"] * 100, color=C_CA, lw=1.6)
ax.set_title("Canada's long end has caught up to the US curve",
             fontweight="bold", loc="left")
ax.set_ylabel("30Y minus 10Y yield (bp)")
pad_right(ax, df.index[0], df.index[-1], 600)
end_labels(ax, df.index[-1], [
    (df["us_10s30s"].iloc[-1] * 100, f"US {df['us_10s30s'].iloc[-1]*100:.0f} bp", C_US),
    (df["ca_10s30s"].iloc[-1] * 100, f"Canada {df['ca_10s30s'].iloc[-1]*100:.0f} bp", C_CA)])
source_note(ax, f"Canada minus US gap: {dif_curve['current']*100:+.0f} bp, "
                f"higher than {dif_curve['pct']:.0f}% of days since 2010. "
                "Source: Bank of Canada, FRED.", y=-0.08)
save("7_curves.png")

# Chart 7b — why foreigners buy: hedged pickup proxy
# starts 2020: the Sept 2019 repo spike in SOFR (+300 bp for a day) swamps the scale
if h is not None:
    hp = h["hedged_pickup"].dropna().loc["2020":] * 100
    hp_m = hp.rolling(21).mean()
    fig, ax = plt.subplots()
    ax.axhline(0, color="#c3c2b7", lw=1)
    ax.plot(hp.index, hp.values, color=C_CA, lw=0.8, alpha=0.35)
    ax.plot(hp_m.index, hp_m.values, color=C_CA, lw=2)
    ax.set_title("Since 2025, hedged Canadian bonds have paid more than Treasuries",
                 fontweight="bold", loc="left")
    ax.set_ylabel("Hedged GoC 10Y minus UST 10Y (bp)")
    pad_right(ax, hp.index[0], hp.index[-1], 420)
    end_labels(ax, hp_m.index[-1], [(hp_m.iloc[-1], f"{hp_m.iloc[-1]:+.0f} bp", C_CA)])
    source_note(ax, "Above zero = a US investor earns more in Canadian 10Ys after hedging the "
                    "currency. PROXY: hedge cost = CORRA minus SOFR, ignores the CAD/USD "
                    "cross-currency basis. Faint line daily, bold 21-day average.", y=-0.08)
    save("7b_hedged_pickup.png")

# Chart 8 — size of the inflow: cumulative net foreign purchases of federal bonds
if flows is not None:
    cum = flows.loc["2015":].cumsum() / 1000
    since20 = cum.iloc[-1] - cum.loc[:"2019"].iloc[-1]
    fig, ax = plt.subplots()
    ax.axhline(0, color="#c3c2b7", lw=1)
    ax.fill_between(cum.index, cum.values, color=C_CA, alpha=0.12, lw=0)
    ax.plot(cum.index, cum.values, color=C_CA, lw=2)
    ax.set_title("Foreign buying of Canadian federal bonds took off after 2020",
                 fontweight="bold", loc="left")
    ax.set_ylabel("Cumulative net purchases since Jan 2015 (C$ billions)")
    pad_right(ax, cum.index[0], cum.index[-1], 330)
    end_labels(ax, cum.index[-1], [(cum.iloc[-1], f"C${cum.iloc[-1]:,.0f}B", C_CA)])
    source_note(ax, f"C${since20:,.0f}B of net purchases since Jan 2020. Net purchases by "
                    f"non-residents of Government of Canada bonds, through {cum.index[-1]:%b %Y}. "
                    "Source: Statistics Canada 36-10-0028-01.", y=-0.08)
    save("8_cumulative_flows.png")

# Chart 9 — who holds Canadian bonds, by region
reg_raw = load_statcan("36100486", "holders_region.csv")
holders = None
if reg_raw is not None:
    r9 = reg_raw[(reg_raw["Type of instrument"] == "Canadian bonds")
                 & (reg_raw["Valuation"] == "Market value")
                 & (reg_raw["Geographic region"].isin(REGIONS))].copy()
    r9["date"] = pd.to_datetime(r9["REF_DATE"])
    r9["v"] = pd.to_numeric(r9["VALUE"], errors="coerce") / 1000
    holders = r9.pivot_table(index="date", columns="Geographic region", values="v")[list(REGIONS)]
    hs = holders.loc["2010":]
    fig, ax = plt.subplots()
    ax.stackplot(hs.index, *[hs[c] for c in hs.columns],
                 colors=[REGIONS[c][1] for c in hs.columns], edgecolor=SEA, lw=0.6)
    # direct labels at the right edge, centred in each band
    mid = hs.iloc[-1].cumsum() - hs.iloc[-1] / 2
    for c in hs.columns:
        share = hs[c].iloc[-1] / hs.iloc[-1].sum() * 100
        ax.annotate(f"{REGIONS[c][0]}  {share:.0f}%", (hs.index[-1], mid[c]),
                    xytext=(6, 0), textcoords="offset points", va="center", fontsize=9)
    pad_right(ax, hs.index[0], hs.index[-1], 1000)
    ax.set_title("Who owns Canada's bonds: the US leads, but everyone is adding",
                 fontweight="bold", loc="left")
    ax.set_ylabel("Foreign holdings, market value (C$ billions)")
    source_note(ax, f"All Canadian bonds (federal, provincial, corporate), {hs.index[-1]:%b %Y}. "
                    "StatCan publishes regions, not individual countries. "
                    "Source: Statistics Canada 36-10-0486-01.", y=-0.08)
    ax.legend([plt.Rectangle((0, 0), 1, 1, fc=REGIONS[c][1]) for c in hs.columns],
              [REGIONS[c][0] for c in hs.columns], frameon=False, fontsize=8, loc="upper left")
    save("9_holders_by_region.png")
    print(holders.iloc[-1].rename(lambda c: REGIONS[c][0]).round(1).to_string())

# Chart 10 — who bought in the last 12 months
freg_raw = load_statcan("36100030", "flows_region.csv")
if freg_raw is not None:
    r10 = freg_raw[(freg_raw["Type of instrument"] == "Canadian bonds")
                   & (freg_raw["Summary of transactions"] == "Net flows")
                   & (freg_raw["Countries or regions"].isin(REGIONS))].copy()
    r10["date"] = pd.to_datetime(r10["REF_DATE"])
    r10["v"] = pd.to_numeric(r10["VALUE"], errors="coerce") / 1000
    fr = r10.pivot_table(index="date", columns="Countries or regions", values="v")[list(REGIONS)]
    last12 = fr.iloc[-12:].sum().sort_values()
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.axvline(0, color="#c3c2b7", lw=1)
    ax.barh([REGIONS[c][0] for c in last12.index], last12.values, height=0.6,
            color=[REGIONS[c][1] for c in last12.index])
    for i, v in enumerate(last12.values):
        ax.annotate(f"C${v:,.1f}B", (v, i), xytext=(6 if v >= 0 else -6, 0),
                    textcoords="offset points", va="center",
                    ha="left" if v >= 0 else "right", fontsize=9)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(min(0, last12.min()) * 1.25, last12.max() * 1.2)
    us_pct = last12["United States"] / last12.sum() * 100
    ax.set_title(f"US investors did {us_pct:.0f}% of foreign net buying, "
                 f"{fr.index[-12]:%b %Y} to {fr.index[-1]:%b %Y}",
                 fontweight="bold", loc="left")
    ax.set_xlabel("C$ billions (negative = net selling)")
    source_note(ax, "All Canadian bonds (federal, provincial, corporate). Source: Statistics Canada 36-10-0030-01.", y=-0.18)
    save("10_buyers_last_12m.png")
    print("  Last 12m net purchases (C$B):")
    print(last12.rename(lambda c: REGIONS[c][0]).round(1).to_string())


# Chart 11 — who bought the NEW government bonds: foreign vs domestic, Canada vs US
# supply  = net new issuance (par). Canada: StatCan 10-10-0003, GoC direct & guaranteed bonds.
#           US: change in marketable notes + bonds + TIPS + FRNs outstanding (MSPD).
# foreign = net purchases by non-residents. Canada: StatCan 36-10-0028 (federal bonds).
#           US: TIC SLT Table 3, long-term Treasuries, Grand Total.
# domestic = supply minus foreign, so it includes the central bank (BoC / Fed).
def load_us_mspd():
    path = os.path.join(DATA_DIR, "us_mspd.csv")
    if not os.path.exists(path):
        print("  downloading us_mspd.csv ...")
        rows, page = [], 1
        while True:
            r = requests.get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_1",
                             params={"filter": "record_date:gte:2019-11-01,security_type_desc:eq:Marketable",
                                     "fields": "record_date,security_class_desc,total_mil_amt",
                                     "sort": "record_date", "page[size]": 1000, "page[number]": page},
                             timeout=60)
            r.raise_for_status()
            js = r.json()
            rows += js["data"]
            if page >= js["meta"]["total-pages"]:
                break
            page += 1
        pd.DataFrame(rows).to_csv(path, index=False)
    m = pd.read_csv(path)
    lt = m[m["security_class_desc"].isin(["Notes", "Bonds", "Floating Rate Notes",
                                          "Treasury Inflation-Protected Securities"])]
    out = lt.groupby("record_date")["total_mil_amt"].sum() / 1000
    out.index = pd.to_datetime(out.index).to_period("M").to_timestamp()
    return out.diff()


def load_tic_lt_flows():
    path = fetch_file("https://ticdata.treasury.gov/resource-center/data-chart-center/"
                      "tic/Documents/slt_table3.txt", "tic_treasury_flows.txt")
    t = pd.read_csv(path, sep="\t", skiprows=8)   # row 9 holds the machine-readable column codes
    g = t[t["country"] == "Grand Total"]
    slt = pd.Series(pd.to_numeric(g["for_lt_treas_net"], errors="coerce").values / 1000,
                    index=pd.to_datetime(g["date"])).dropna()   # SLT net flows start Feb 2023
    # before that: legacy S-form, gross purchases minus gross sales of Treasury bonds & notes
    old = {}
    with open(fetch_file("https://ticdata.treasury.gov/resource-center/data-chart-center/"
                         "tic/Documents/s1_99996.txt", "tic_treasury_flows_legacy.txt")) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 14 and parts[0] == "99996":
                buy, sell = (float(parts[i].replace(",", "")) for i in (2, 8))
                old[pd.Timestamp(parts[1] + "-01")] = (buy - sell) / 1000
    old = pd.Series(old)
    return pd.concat([old[old.index < slt.index.min()], slt]).sort_index()


new_supply = None
try:
    iss = load_statcan("10100003", "gov_issuance.csv")
    iss = iss[(iss["Issuers"] == "Government of Canada direct and guaranteed bonds")
              & (iss["GEO"] == "Canada and Abroad") & (iss["Type of issues"] == "Net new issues")]
    ca_net = pd.Series(pd.to_numeric(iss["VALUE"], errors="coerce").values / 1000,
                       index=pd.to_datetime(iss["REF_DATE"])).sort_index()
    # central banks: BoC month-end GoC bond holdings; Fed notes+bonds+TIPS held outright (weekly -> month-end)
    boc_hold = boc("V36654", start="2019-01-01").iloc[:, 0] / 1000
    fed_hold = (fred("WSHONBNL", start="2019-01-01").iloc[:, 0]
                + fred("WSHONBIIL", start="2019-01-01").iloc[:, 0]) / 1000
    fed_hold = fed_hold.resample("ME").last()
    fed_hold.index = fed_hold.index.to_period("M").to_timestamp()
    new_supply = {
        "Canada": pd.DataFrame({"net": ca_net, "foreign": flows / 1000,
                                "cb": boc_hold.diff()}).dropna(),
        "United States": pd.DataFrame({"net": load_us_mspd(), "foreign": load_tic_lt_flows(),
                                       "cb": fed_hold.diff()}).dropna(),
    }
except Exception as e:
    print(f"  New-supply data failed ({e}). Skipping chart 11.")

if new_supply is not None:
    SEGS = [("other", "Other domestic investors", "#2a78d6"),   # categorical slots 1-3, fixed order
            ("cb", "Central bank", "#1baf7a"),
            ("foreign", "Foreign investors", "#eb6834")]
    end = min(d.index[-1] for d in new_supply.values())
    windows = [(f"Last 12 months ({end - pd.DateOffset(months=11):%b %Y} to {end:%b %Y})",
                end - pd.DateOffset(months=11)),
               (f"Since the pandemic (Jan 2020 to {end:%b %Y})", pd.Timestamp("2020-01-01"))]
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True)
    lo, hi = 0, 100
    for ax, (wlabel, start) in zip(axes, windows):
        for i, (country, cur) in enumerate([("Canada", "C$"), ("United States", "US$")]):
            d = new_supply[country].loc[start:end].sum()
            d["other"] = d["net"] - d["foreign"] - d["cb"]
            pct = {k: d[k] / d["net"] * 100 for k, _, _ in SEGS}
            y = 1 - i
            pos, neg = 0.0, 0.0   # positive shares stack right from 0, negative (net selling) stack left
            for k, _, color in SEGS:
                w = pct[k]
                left = pos if w >= 0 else neg + w
                ax.barh(y, abs(w), left=left, color=color, height=0.62, edgecolor=SEA, lw=2)
                if abs(w) >= 8:
                    ax.text(left + abs(w) / 2, y, f"{w:.0f}%", ha="center", va="center",
                            color="white", fontsize=10, fontweight="bold")
                if w >= 0:
                    pos += w
                else:
                    neg += w
            lo, hi = min(lo, neg), max(hi, pos)
            ax.annotate(f"{cur}{d['net']:,.0f}B of new bonds", (pos, y), xytext=(8, 0),
                        textcoords="offset points", va="center", fontsize=9, color="#52514e")
            print(f"  {country:14s} {wlabel[:14]}: net new {cur}{d['net']:,.0f}B | "
                  + " | ".join(f"{lab} {cur}{d[k]:,.0f}B ({pct[k]:.0f}%)" for k, lab, _ in SEGS))
        ax.axvline(0, color="#52514e", lw=1)
        ax.axvline(100, color=INK_MUTED, lw=1, ls="--")
        ax.set_yticks([1, 0], ["Canada", "United States"], fontsize=11)
        ax.set_title(wlabel, loc="left", fontsize=10, color="#52514e")
        ax.grid(False)
        ax.tick_params(axis="y", length=0)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_visible(False)
    for ax in axes:
        ax.set_xlim(lo - 8, hi + 40)
    axes[0].text(100, 1.55, " 100% = all net new bonds", fontsize=8, color=INK_MUTED, va="center")
    ticks = [t for t in range(-100, 201, 25) if lo - 8 <= t <= hi]
    axes[-1].set_xticks(ticks, [f"{t}%" for t in ticks])
    axes[-1].set_xlabel("Share of net new government bonds bought (below 0 = net sellers)")
    fig.legend([plt.Rectangle((0, 0), 1, 1, fc=c) for _, _, c in SEGS], [l for _, l, _ in SEGS],
               loc="upper left", bbox_to_anchor=(0.01, 0.955), ncol=3, frameon=False, fontsize=9)
    fig.suptitle("Americans buy America's new bonds. Foreigners buy Canada's.",
                 x=0.01, ha="left", fontweight="bold", fontsize=13)
    fig.tight_layout(rect=(0, 0.08, 1, 0.93))
    fig.text(0.01, 0.01, textwrap.fill(
        "Net new bonds = new bonds sold minus bonds that matured, at par (Canada: Government of Canada "
        "bonds; US: Treasury notes, bonds, TIPS and FRNs, excluding bills). Foreign = net purchases by "
        "non-residents. Central bank = change in Bank of Canada / Federal Reserve holdings (negative = "
        "holdings shrinking as bonds mature). Other domestic = the remainder. Sources: Statistics Canada "
        "10-10-0003-01, 36-10-0028-01; Bank of Canada; US Treasury MSPD and TIC; Federal Reserve H.4.1.", 170),
        fontsize=8, color=INK_MUTED, va="bottom")
    plt.savefig(os.path.join(CHART_DIR, "11b_new_bond_buyers_bars.png"), bbox_inches="tight")
    plt.show()


# Chart 12 — world maps: who holds Canada's bonds vs who holds US Treasuries
def draw_world(ax, geo):
    from matplotlib.collections import PolyCollection
    polys = []
    for feat in geo["features"]:
        if feat["properties"].get("NAME") == "Antarctica":
            continue
        g = feat["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        polys += [np.asarray(p[0]) for p in parts]
    ax.add_collection(PolyCollection(polys, facecolor=LAND, edgecolor=SEA, lw=0.4, zorder=1))
    ax.set_xlim(-180, 180); ax.set_ylim(-58, 84); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)


BUBBLE_K = 55   # marker area (pt^2) per 1% share, same on both maps so bubbles compare


def fmt_share(sh):
    txt = f"{abs(sh):.0f}%" if abs(sh) >= 9.5 else f"{abs(sh):.1f}%"
    return ("−" if sh < 0 else "") + txt


def bubbles(ax, pts, color):
    """pts: list of (label, lon, lat, share_pct, (dx, dy) label offset in points[, color]).
    Negative shares (net sellers) are drawn as dashed grey rings."""
    for p in sorted(pts, key=lambda p: -abs(p[3])):
        lab, lon, lat, sh, (dx, dy) = p[:5]
        c = p[5] if len(p) > 5 else color
        if sh >= 0:
            ax.scatter(lon, lat, s=sh * BUBBLE_K, color=c, alpha=0.75,
                       edgecolor="white", lw=1.2, zorder=3)
        else:
            ax.scatter(lon, lat, s=-sh * BUBBLE_K, facecolor="none", edgecolor="#52514e",
                       lw=1.2, linestyle=(0, (3, 2)), zorder=3)
        if lab:
            ax.annotate(f"{lab} {fmt_share(sh)}", (lon, lat), xytext=(dx, dy),
                        textcoords="offset points", fontsize=8.5, zorder=4,
                        ha="left" if dx >= 0 else "right", va="center",
                        arrowprops=dict(arrowstyle="-", color=INK_MUTED, lw=0.6)
                        if abs(dx) + abs(dy) > 25 else None)


def size_key(ax, color):
    """Bubble-size legend in the empty South Pacific."""
    ax.text(-168, -24, "Bubble area = share", fontsize=8, color=INK_MUTED)
    for sh, x in ((5, -164), (15, -151), (30, -128)):
        ax.scatter(x, -38, s=sh * BUBBLE_K, facecolor="none", edgecolor=color, lw=1, zorder=3)
        ax.text(x, -51, f"{sh}%", ha="center", va="top", fontsize=7.5, color=INK_MUTED)


# (lon, lat, label offset) — StatCan regions pinned to a representative point
REGION_PTS = {
    "United States": (-98, 39, (30, -30)),
    "United Kingdom": (-2, 54, (-40, 22)),
    "Other European Union countries": (10, 49, (30, 18)),
    "Japan": (139, 37, (22, 16)),
    "Other Organisation for Economic Co-operation and Development (OECD) countries":
        (134, -25, (28, 0)),
    "All other countries": (80, 25, (-30, -34)),
}
TIC_PTS = {
    "Japan": (139, 37, (22, 16)), "United Kingdom": (-2, 54, (-40, 24)),
    "China, Mainland": (104, 35, (-20, -40)), "Belgium": (4.5, 50.6, (34, 34)),
    "Canada": (-100, 57, (-30, -12)), "Cayman Islands": (-81, 19.5, (-30, -20)),
    "Luxembourg": (6.1, 49.8, (44, 6)), "France": (2.5, 46.5, (-40, -22)),
    "Ireland": (-8, 53.2, (-42, 0)), "Taiwan": (121, 23.7, (30, -10)),
    "Switzerland": (8.2, 46.8, (40, -22)), "Singapore": (103.8, 1.35, (-26, -20)),
    "Hong Kong": (114.2, 22.3, (-8, -30)), "Norway": (9, 61, (0, 0)),
    "India": (79, 22, (0, 0)), "Brazil": (-52, -10, (0, 0)),
    "Saudi Arabia": (45, 24, (0, 0)), "Korea, South": (128, 36.5, (0, 0)),
    "United Arab Emirates": (54, 24, (0, 0)), "Israel": (35, 31.5, (0, 0)),
}
LABEL_MIN_SHARE = 2.9   # label TIC countries at or above this share; smaller get a bubble only


def load_tic():
    path = fetch_file("https://ticdata.treasury.gov/resource-center/data-chart-center/"
                      "tic/Documents/slt_table5.txt", "tic_holders.txt")
    rows, month = {}, None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            cells = [c.strip() for c in line.rstrip("\n").split("\t")]
            if cells[0] == "Country":
                month = cells[1]
            elif month and len(cells) > 1 and cells[1]:
                if cells[0].startswith("Of Which"):
                    break
                rows[cells[0]] = float(cells[1])
    return month, rows


try:
    geo = json.load(open(fetch_file(
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
        "geojson/ne_110m_admin_0_countries.geojson", "world.geojson"), encoding="utf-8"))
    tic_month, tic = load_tic()
except Exception as e:
    print(f"  Map data failed ({e}). Skipping chart 12.")
    geo = None

if geo is not None and holders is not None:
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 9.2))

    ca_last = holders.iloc[-1]
    ca_tot = ca_last.sum()
    draw_world(a1, geo)
    bubbles(a1, [(REGIONS[k][0], lon, lat, ca_last[k] / ca_tot * 100, off)
                 for k, (lon, lat, off) in REGION_PTS.items()], C_CA)
    size_key(a1, C_CA)
    a1.set_title(f"Who holds Canada's bonds  (C${ca_tot:,.0f}B foreign-held, "
                 f"{holders.index[-1]:%b %Y})", fontweight="bold", loc="left")
    source_note(a1, "Share of foreign-held Canadian bonds. StatCan reports regions only, "
                    "so each bubble sits on a representative point: 'Other OECD' covers "
                    "Australia, Switzerland, Korea, Norway etc.; 'All other' covers China, "
                    "Hong Kong, Singapore, Gulf states, offshore centres.", y=-0.01, width=175)

    tic_tot = tic["Grand Total"]
    missing = [k for k in tic if k not in TIC_PTS and k not in ("All Other", "Grand Total")]
    if missing:
        print("  No map coordinates for:", missing, "— add them to TIC_PTS")
    draw_world(a2, geo)
    bubbles(a2, [(k if tic[k] / tic_tot * 100 >= LABEL_MIN_SHARE else None,
                  lon, lat, tic[k] / tic_tot * 100, off)
                 for k, (lon, lat, off) in TIC_PTS.items() if k in tic], C_US)
    size_key(a2, C_US)
    a2.set_title(f"Who holds US Treasuries  (US${tic_tot/1000:,.1f}T foreign-held, "
                 f"{pd.to_datetime(tic_month):%b %Y})", fontweight="bold", loc="left")
    source_note(a2, f"Share of foreign-held Treasuries, top 20 countries shown; "
                    f"{tic['All Other']/tic_tot*100:.0f}% sits with all other countries. "
                    "Custody centres (Belgium, Luxembourg, Cayman) hold on behalf of others. "
                    "Source: US Treasury TIC; Statistics Canada 36-10-0486-01.", y=-0.01, width=175)

    tic_top_name, tic_top = max(((k, v) for k, v in tic.items()
                                 if k not in ("All Other", "Grand Total")), key=lambda kv: kv[1])
    fig.text(0.02, 0.985, f"One country holds {ca_last['United States']/ca_tot*100:.0f}% of Canada's "
                          f"foreign-held bonds. The top Treasury holder, {tic_top_name}, "
                          f"holds {tic_top/tic_tot*100:.0f}%",
             fontsize=13, fontweight="bold", va="top")
    fig.subplots_adjust(top=0.93, bottom=0.04, hspace=0.24)
    plt.savefig(os.path.join(CHART_DIR, "12_buyer_maps.png"), bbox_inches="tight")
    plt.show()
    top3 = sorted(((k, v) for k, v in tic.items() if k not in ("All Other", "Grand Total")),
                  key=lambda kv: -kv[1])[:3]
    print(f"  Canada: US share {ca_last['United States']/ca_tot*100:.0f}% of foreign holdings")
    print(f"  UST: top 3 = " + ", ".join(f"{k} {v/tic_tot*100:.0f}%" for k, v in top3))


# Chart 11 (map) — who bought the NEW bonds since 2020, by country, Canada vs US
# Uses the same supply/foreign/central-bank data as the chart 11 bars (new_supply).
# Window is Jan 2020 onward: over the last 12 months Canada's domestic share is negative,
# which a bubble can't show (see the bar version for that).
def load_tic_country_flows(start, end):
    """Net foreign purchases of long-term Treasuries by country, US$B, summed over [start, end]."""
    rows = []
    legacy = fetch_file("https://ticdata.treasury.gov/resource-center/data-chart-center/"
                        "tic/Documents/s1_globl.txt", "tic_s1_countries.txt")
    with open(legacy, encoding="utf-8", errors="replace") as fh:
        for r in csv.reader(fh, delimiter="\t"):
            if len(r) >= 10 and r[1].strip().isdigit() and len(r[2].strip()) == 7:
                try:   # col [1] gross purchases, col [7] gross sales of Treasury bonds & notes
                    net = float(r[3].replace(",", "")) - float(r[9].replace(",", ""))
                except ValueError:
                    continue
                rows.append((r[0].strip(), pd.Timestamp(r[2].strip() + "-01"), net))
    old = pd.DataFrame(rows, columns=["country", "date", "net"])
    t = pd.read_csv(os.path.join(DATA_DIR, "tic_treasury_flows.txt"), sep="\t", skiprows=8)
    new = pd.DataFrame({"country": t["country"], "date": pd.to_datetime(t["date"]),
                        "net": pd.to_numeric(t["for_lt_treas_net"], errors="coerce")}).dropna()
    both = pd.concat([old[old["date"] < new["date"].min()], new])
    both = both[(both["date"] >= start) & (both["date"] <= end)]
    s = both.groupby("country")["net"].sum() / 1000
    aggregates = ("Total", "Memo", "Grand", "All Countries", "Of Which", "International",
                  "Other", "Country Unknown")
    return s[[not c.startswith(aggregates) for c in s.index]]


def ne_points(geo):
    """Country label points from Natural Earth, keyed by several name variants."""
    pts = {}
    for f in geo["features"]:
        p = f["properties"]
        for key in ("NAME", "ADMIN", "NAME_LONG"):
            if p.get(key):
                pts[p[key]] = (p["LABEL_X"], p["LABEL_Y"])
    return pts


# TIC names -> Natural Earth names, plus places too small for the 110m basemap
TIC_ALIASES = {"China, Mainland": "China", "Korea, South": "South Korea",
               "Bahamas": "The Bahamas", "Russia": "Russia"}
SMALL_PLACES = {"Cayman Islands": (-81, 19.5), "Bermuda": (-64.8, 32.3), "Singapore": (103.8, 1.35),
                "Hong Kong": (114.2, 22.3), "Guernsey": (-2.6, 49.5), "Jersey": (-2.1, 49.2),
                "British Virgin Islands": (-64.6, 18.4), "Curacao": (-69, 12.2), "Aruba": (-70, 12.5),
                "Barbados": (-59.5, 13.2), "Anguilla": (-63, 18.2), "Bahrain": (50.6, 26),
                "Malta": (14.4, 35.9), "Mauritius": (57.6, -20.3), "Macau": (113.5, 22.2),
                "Luxembourg": (6.1, 49.8), "Saint Kitts and Nevis": (-62.7, 17.3), "Monaco": (7.4, 43.7),
                "Liechtenstein": (9.5, 47.1)}
# label offsets (points) for the countries that get a label; everything else uses DEFAULT_OFF
NEW_LABEL_OFF = {"United States": (40, -40), "Canada": (-40, 20), "United Kingdom": (-44, 26),
                 "France": (-44, -24), "Germany": (38, 26), "Belgium": (46, 4),
                 "Luxembourg": (46, -12), "Ireland": (-46, 0), "China, Mainland": (-50, 24),
                 "Japan": (24, 16), "India": (-34, -24), "Hong Kong": (10, -34),
                 "Singapore": (-30, -22), "Brazil": (30, -10), "Cayman Islands": (-34, -20),
                 "Norway": (20, 20), "Taiwan": (30, -8)}
DEFAULT_OFF = (14, 10)
NEW_LABEL_MIN = 0.95   # label countries whose |share| of new supply is at least this (%)

if geo is not None and new_supply is not None and freg_raw is not None:
    C_DOM, C_FOR = "#2a78d6", "#eb6834"      # same roles/colours as the chart 11 bars
    start, end = pd.Timestamp("2020-01-01"), min(d.index[-1] for d in new_supply.values())
    tot = {c: new_supply[c].loc[start:end].sum() for c in new_supply}
    names = ne_points(geo)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 9.4))

    # Canada: domestic bubble + foreign share split by region. StatCan's regional flows cover
    # ALL Canadian bonds, so the federal foreign total is apportioned with those regional weights.
    ca = tot["Canada"]
    ca_dom = (ca["net"] - ca["foreign"]) / ca["net"] * 100
    ca_for = ca["foreign"] / ca["net"] * 100
    reg = r10[(r10["date"] >= start) & (r10["date"] <= end)].groupby("Countries or regions")["v"].sum()
    reg_w = reg / reg.sum()
    draw_world(a1, geo)
    pts = [("Canada (domestic)", -106, 60, ca_dom, (-40, 26), C_DOM)]
    for k, (lon, lat, off) in REGION_PTS.items():
        pts.append((REGIONS[k][0], lon, lat, ca_for * reg_w[k], off, C_FOR))
    bubbles(a1, pts, C_FOR)
    size_key(a1, "#52514e")
    a1.set_title(f"Who bought Canada's new federal bonds  (C${ca['net']:,.0f}B net new, "
                 f"{start:%b %Y} to {end:%b %Y})", fontweight="bold", loc="left")
    source_note(a1, f"Domestic {ca_dom:.0f}% (includes the Bank of Canada), foreign {ca_for:.0f}%. Regional split of the foreign share is "
                    "estimated from StatCan's regional flows for all Canadian bonds (federal-only by region "
                    "isn't published); each region sits on a representative point. Dashed ring = net seller. "
                    "Sources: Statistics Canada 10-10-0003-01, 36-10-0028-01, 36-10-0030-01.",
                y=-0.01, width=175)

    # US: domestic bubble + every country with its own net purchases
    us = tot["United States"]
    us_dom = (us["net"] - us["foreign"]) / us["net"] * 100
    by_c = load_tic_country_flows(start, end) / us["net"] * 100
    draw_world(a2, geo)
    pts = [("United States (domestic, incl. Fed)", -98, 39, us_dom, NEW_LABEL_OFF["United States"], C_DOM)]
    skipped = []
    for k, sh in by_c.items():
        if abs(sh) < 0.05:
            continue
        lonlat = SMALL_PLACES.get(k) or names.get(TIC_ALIASES.get(k, k))
        if lonlat is None:
            skipped.append(k)
            continue
        lab = k.replace(", Mainland", "") if abs(sh) >= NEW_LABEL_MIN else None
        pts.append((lab, *lonlat, sh, NEW_LABEL_OFF.get(k, DEFAULT_OFF), C_FOR))
    if skipped:
        print("  No map point for:", skipped)
    bubbles(a2, pts, C_FOR)
    size_key(a2, "#52514e")
    a2.set_title(f"Who bought America's new Treasuries  (US${us['net']/1000:,.1f}T net new, "
                 f"{start:%b %Y} to {end:%b %Y})", fontweight="bold", loc="left")
    sellers = by_c[by_c < 0].sort_values().head(3)
    source_note(a2, f"Domestic {us_dom:.0f}%, foreign {100-us_dom:.0f}%. Largest net sellers: "
                    + ", ".join(f"{k.replace(', Mainland', '')} US${-v * us['net'] / 100:,.0f}B"
                                for k, v in sellers.items())
                    + ". The UK figure is inflated by London custody accounts that trade for other "
                      "countries. Dashed ring = net seller. Sources: US Treasury MSPD and TIC.",
                y=-0.01, width=175)

    fig.legend([plt.Line2D([], [], ls="", marker="o", ms=10, mfc=C_DOM, mec="white"),
                plt.Line2D([], [], ls="", marker="o", ms=10, mfc=C_FOR, mec="white"),
                plt.Line2D([], [], ls="", marker="o", ms=10, mfc="none", mec="#52514e")],
               ["Domestic buyers", "Foreign buyers", "Net seller"],
               loc="upper left", bbox_to_anchor=(0.02, 0.955), ncol=3, frameon=False, fontsize=9)
    fig.text(0.02, 0.99, f"Americans bought {us_dom:.0f}% of America's new bonds. "
                         f"Foreigners bought {ca_for:.0f}% of Canada's.",
             fontsize=13, fontweight="bold", va="top")
    fig.subplots_adjust(top=0.9, bottom=0.04, hspace=0.26)
    plt.savefig(os.path.join(CHART_DIR, "11_new_bond_buyers_map.png"), bbox_inches="tight")
    plt.show()
    print("  Top US Treasury net buyers since 2020 (% of new supply):")
    print(by_c.sort_values().tail(6).round(2).to_string())


# ============================================================
# HEDGE RATIO — fill from Montréal Exchange front-month specs
# ============================================================
print("\n" + "=" * 60 + "\nHEDGE RATIO\n" + "=" * 60)

CGB_CTD_BPV, CGB_CF = None, None   # <-- m-x.ca front month
LGB_CTD_BPV, LGB_CF = None, None

if all(v is not None for v in [CGB_CTD_BPV, CGB_CF, LGB_CTD_BPV, LGB_CF]):
    cgb_bpv, lgb_bpv = CGB_CTD_BPV / CGB_CF, LGB_CTD_BPV / LGB_CF
    ratio = lgb_bpv / cgb_bpv
    print(f"  CGB BPV {cgb_bpv:.2f} | LGB BPV {lgb_bpv:.2f}")
    print(f"  Ratio: {ratio:.2f} CGB per 1 LGB   (expect 2.5-3.5)")
    NAV, STOP_BP, RISK = 1_000_000, 1.5 * vol20, 0.005
    spread_dv01 = (NAV * RISK) / STOP_BP
    n_lgb = spread_dv01 / lgb_bpv
    print(f"  Stop {STOP_BP:.1f}bp -> spread DV01 ${spread_dv01:,.0f}/bp")
    print(f"  Sell {n_lgb:.1f} LGB | Buy {n_lgb*ratio:.1f} CGB")
else:
    print("  Fill CTD BPV and conversion factors from m-x.ca front month.")


# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Canada 10s30s   {ca_curve['current']*100:6.1f} bp  p{ca_curve['pct']:.0f}")
print(f"CA-US curve     {dif_curve['current']*100:6.1f} bp  p{dif_curve['pct']:.0f}")
print(f"CA-US 10Y       {cross['current']*100:6.1f} bp  p{cross['pct']:.0f}")
print(f"Corr 126d       {corr['126d'].iloc[-1]:6.3f}  (2015-19 {pre:.3f})")
print(f"R:R             {rr:6.2f} : 1")
print("\nGates: (1) curve pct <50  (2) corr risen  (3) tenor skews short")
print("Any fail -> publish the null, keep the structural argument.")