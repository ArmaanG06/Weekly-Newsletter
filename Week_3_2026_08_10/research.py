"""
Chinese AI shock event study + newsletter chart/table assets.
Descriptive only: n=6 events, no regression, no t-tests, no p-values.

Single script -- run this top to bottom:
    1. Config + universe
    2. Download + integrity check
    3. Windowing + excess returns
    4. Anchor validation   <-- STOP AND READ THE OUTPUT
    5. Metrics
    6. Data export (CSVs -> data/)
    7. House style (shared constants/helpers for charts + tables)
    8. Newsletter charts A-F -> figures/chart_a.png .. chart_f.png
    9. Newsletter tables 1-3 -> figures/table_1..3.{png,html} + stdout markdown
    10. Consolidated fact-check report (every data-label number, grouped by file)

Chart E is the one exception to the six-event rule (Biren/2513.HK wasn't
listed until v4_preview, so it gets its own six: v4_preview, v4_pricecut,
glm52, k3, k3_weights, v4_flash). Every other chart/table uses the global
six: r1, k2, v4_preview, v4_pricecut, glm52, k3. Table 3's Target field is
still an open TODO -- the run prints a loud warning for it.
"""

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

WEEK_DIR = Path(__file__).resolve().parent
DATA_DIR = WEEK_DIR / 'data'
FIG_DIR = WEEK_DIR / 'figures'
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)


# ============================================================
# 1. CONFIG
# ============================================================

START = "2024-01-01"
PRE, POST = 10, 20

LAYERS = {
    'compute': ['NVDA', 'AVGO', 'AMD', 'MRVL', 'TSM', '2330.TW', 'SMH'],
    'memory':  ['MU', '000660.KS', '005930.KS', 'SNDK'],
    'wfe':     ['AMAT', 'LRCX', 'ASML'],
    'power':   ['VST', 'CEG', 'VRT', 'GEV'],
    'model':   ['MSFT', 'GOOGL', 'ORCL', 'PLTR', '9984.T'],
    'china':   ['9988.HK', '3067.HK', '0981.HK', '2513.HK'],
}

# ETFs hold their own layer's constituents. Kept for options/vol work,
# excluded from any layer aggregate to avoid double-weighting semis.
ETFS = {'SMH'}


def benchmark_for(ticker):
    """Local index for locally-listed names. ADRs trade US hours -> QQQ."""
    if ticker.endswith('.TW'):
        return '^TWII'
    if ticker.endswith('.KS'):
        return '^KS11'
    if ticker.endswith('.T'):
        return '^N225'
    if ticker.endswith('.HK'):
        return '^HSI'
    return 'QQQ'


EVENTS_DF = pd.DataFrame([
    # release_date drives gap-days (F1). anchor_date drives every price metric.
    {'event_id': 'r1',          'release_date': '2025-01-20', 'anchor_date': '2025-01-27',
     'event_type': 'primary',    'contaminated': False,
     'note': 'HK closed Lunar New Year; FOMC 01-28'},
    {'event_id': 'k2',          'release_date': '2025-07-11', 'anchor_date': '2025-07-11',
     'event_type': 'null_test',  'contaminated': False,
     'note': 'strong tape into event; a null may be absorption not indifference'},
    {'event_id': 'v4_preview',  'release_date': '2026-04-23', 'anchor_date': '2026-04-24',
     'event_type': 'cost_shock', 'contaminated': False,
     'note': 'VERIFY release date: Apr 23 vs Apr 24'},
    {'event_id': 'v4_pricecut', 'release_date': '2026-06-01', 'anchor_date': '2026-06-01',
     'event_type': 'control',    'contaminated': True,
     'note': 'NVDA earnings 2026-05-20 sits in T-10'},
    {'event_id': 'glm52',       'release_date': '2026-06-15', 'anchor_date': '2026-06-15',
     'event_type': 'flagged',    'contaminated': True,
     'note': 'FOMC 06-16/17; export controls 06-12. Jointly caused, not clean'},
    {'event_id': 'k3',          'release_date': '2026-07-16', 'anchor_date': '2026-07-17',
     'event_type': 'primary',    'contaminated': True,
     'note': 'Korea closed on anchor; GOOGL delay 07-16; tape already off highs'},
    {'event_id': 'k3_weights',  'release_date': '2026-07-27', 'anchor_date': '2026-07-27',
     'event_type': 'flagged',    'contaminated': True,
     'note': 'CXMT listing same day'},
    {'event_id': 'v4_flash',    'release_date': '2026-07-31', 'anchor_date': '2026-07-31',
     'event_type': 'control',    'contaminated': True,
     'note': 'FOMC 07-29'},
])
EVENTS_DF['anchor_date'] = pd.to_datetime(EVENTS_DF['anchor_date'])
EVENTS_DF['release_date'] = pd.to_datetime(EVENTS_DF['release_date'])


# ============================================================
# 2. DOWNLOAD + INTEGRITY
# ============================================================

def fetch_all(tickers, start):
    out, no_data = {}, []
    for t in tickers:
        df = yf.download(t, start=start, auto_adjust=True,
                         progress=False, multi_level_index=False).dropna(how='all')
        if df.empty:
            no_data.append(t)
        else:
            out[t] = df
    return out, no_data


_all_layer = [t for tks in LAYERS.values() for t in tks]
BENCH_TICKERS = sorted({benchmark_for(t) for t in _all_layer})

PRICE_PANEL, NO_DATA = fetch_all(_all_layer + BENCH_TICKERS, START)

for b in BENCH_TICKERS:
    if b not in PRICE_PANEL:
        raise RuntimeError(f"Benchmark {b} failed. Every ticker mapped to it is unusable.")

# Drop failed downloads so nothing downstream KeyErrors.
LAYERS = {k: [t for t in v if t in PRICE_PANEL] for k, v in LAYERS.items()}
LAYER_TICKERS = [t for tks in LAYERS.values() for t in tks]
TICKER_BENCH = {t: benchmark_for(t) for t in LAYER_TICKERS}
LAYER_OF = {t: k for k, v in LAYERS.items() for t in v}

if NO_DATA:
    print(f"DROPPED (no data): {NO_DATA}")
    print("  -> if these are HK/STAR codes, verify them in IBKR contract search\n")

print("=== Coverage ===")
for t in LAYER_TICKERS + BENCH_TICKERS:
    df = PRICE_PANEL[t]
    print(f"{t:12s} {df.index.min().date()} -> {df.index.max().date()}  ({len(df)} sessions)")


# ============================================================
# 3. WINDOWING + EXCESS RETURNS
# ============================================================

def get_event_window(ticker, anchor_date, pre=PRE, post=POST):
    """
    Slice T-pre..T+post on the ticker's OWN calendar. If the anchor is not a
    session for this ticker (e.g. Korea closed on K3 day), T+0 rolls forward
    to the next available session. Never forward-filled, never dropped.
    """
    idx = PRICE_PANEL[ticker].index
    anchor_ts = pd.Timestamp(anchor_date)
    pos = idx.searchsorted(anchor_ts)
    if pos >= len(idx):
        raise ValueError(f"{ticker}: no session on/after {anchor_ts.date()}")

    t0 = idx[pos]
    lo, hi = max(pos - pre, 0), min(pos + post + 1, len(idx))
    win = PRICE_PANEL[ticker].iloc[lo:hi].copy()
    win['offset'] = np.arange(lo, hi) - pos
    return {
        't0_date': t0,
        'anchor_shift_days': int((t0.normalize() - anchor_ts.normalize()).days),
        'window_complete': pos + post < len(idx),
        'window': win,
    }


def excess_log_returns(ticker, bench, tol_days=3):
    """Log return minus benchmark log return, matched on the ticker's calendar."""
    tr = np.log(PRICE_PANEL[ticker]['Close']).diff().reset_index()
    br = np.log(PRICE_PANEL[bench]['Close']).diff().reset_index()
    tr.columns, br.columns = ['Date', 'r'], ['Date', 'b']
    m = pd.merge_asof(tr.sort_values('Date'), br.sort_values('Date'), on='Date',
                      direction='backward', tolerance=pd.Timedelta(f'{tol_days}D'))
    stale = int(m['b'].isna().sum())
    if stale:
        print(f"  {ticker} vs {bench}: {stale} rows with no benchmark inside {tol_days}D")
    return pd.Series((m['r'] - m['b']).values, index=m['Date'], name=f'{ticker}_excess')


print("\n=== Benchmark match quality ===")
EXCESS = {t: excess_log_returns(t, TICKER_BENCH[t]) for t in LAYER_TICKERS}


def cum_excess(ticker, ev, pre=PRE, post=POST, max_missing=3):
    """
    Cumulative excess return over the window, rebased to 0 at T-1.
    Returns (series indexed by session offset, window_complete) or (None, _).
    NaN excess is zero-filled only after the missing-count gate, so a data
    hole can never masquerade as a flat day.
    """
    w = get_event_window(ticker, ev.anchor_date, pre, post)
    win = w['window']
    ex = EXCESS[ticker].reindex(win.index)
    if int(ex.isna().sum()) > max_missing:
        return None, w['window_complete']

    cum = ex.fillna(0).cumsum()
    base = cum[win['offset'] == -1]
    if base.empty:
        return None, w['window_complete']

    out = pd.Series((cum - base.iloc[0]).values, index=win['offset'].values)
    return out, w['window_complete']


# ============================================================
# 4. ANCHOR VALIDATION  <-- READ THIS BEFORE TRUSTING ANYTHING BELOW
# ============================================================

VOL_Z = {t: ((PRICE_PANEL[t]['Volume'] - PRICE_PANEL[t]['Volume'].rolling(60).mean())
             / PRICE_PANEL[t]['Volume'].rolling(60).std())
         for t in LAYER_TICKERS}

rows = []
for _, ev in EVENTS_DF.iterrows():
    for t in LAYER_TICKERS:
        w = get_event_window(t, ev.anchor_date)
        z = VOL_Z[t]
        post_release = z.loc[ev.release_date:].head(15)
        spike = post_release[post_release > 2].index.min()
        rows.append({
            'event_id': ev.event_id, 'ticker': t, 'layer': LAYER_OF[t],
            't0_date': w['t0_date'],
            'anchor_shift_days': w['anchor_shift_days'],
            'window_complete': w['window_complete'],
            'vol_z_t0': float(z.get(w['t0_date'], np.nan)),
            'gap_days': (np.nan if pd.isna(spike)
                         else len(PRICE_PANEL[t].loc[ev.release_date:spike]) - 1),
        })
ANCHOR_CHECK = pd.DataFrame(rows)

print("\n=== ANCHOR VALIDATION ===")
print("max volume z-score at T+0 (need > 2, else the date is wrong):")
print(ANCHOR_CHECK.groupby('event_id')['vol_z_t0'].max().round(2).to_string())
print("\nmedian gap days, release -> first volume spike (this is F1):")
print(ANCHOR_CHECK.groupby('event_id')['gap_days'].median().to_string())

_bad = ANCHOR_CHECK.groupby('event_id')['vol_z_t0'].max()
_bad = _bad[_bad < 2]
if len(_bad):
    print(f"\nWARNING - no volume confirmation for: {list(_bad.index)}")
    print("Fix these anchor dates before reading any chart.")

_short = ANCHOR_CHECK[~ANCHOR_CHECK.window_complete]['event_id'].unique()
if len(_short):
    print(f"\nIncomplete T+{POST} windows (excluded from charts): {list(_short)}")


# ============================================================
# 5. METRICS
# ============================================================

def event_metrics(ticker, ev):
    cum, complete = cum_excess(ticker, ev)
    if cum is None:
        return None

    post_c = cum[cum.index >= 0]
    if post_c.empty:
        return None

    max_dd = float(post_c.min())
    trough_off = int(post_c.idxmin())
    after = post_c.loc[trough_off:]

    reclaim = after[after >= 0]
    # Half-life is meaningless with no drawdown; without this guard a name that
    # rallied all window records half_life = 0 and fakes a fast recovery.
    half = after[after >= max_dd * 0.5] if max_dd < 0 else pd.Series(dtype=float)

    return {
        'day1_excess': float(post_c.iloc[0]),
        'max_dd': max_dd if max_dd < 0 else 0.0,
        'no_drawdown': max_dd >= 0,
        'trough_offset': trough_off,
        'days_to_reclaim': int(reclaim.index[0]) if len(reclaim) else np.nan,
        'half_life': int(half.index[0] - trough_off) if len(half) else np.nan,
        'window_complete': complete,
    }


recs = []
for _, ev in EVENTS_DF.iterrows():
    for t in LAYER_TICKERS:
        m = event_metrics(t, ev)
        if m:
            recs.append({'event_id': ev.event_id, 'ticker': t, 'layer': LAYER_OF[t], **m})

METRICS = pd.DataFrame(recs)
METRICS = METRICS.merge(ANCHOR_CHECK[['event_id', 'ticker', 'vol_z_t0',
                                      'gap_days', 'anchor_shift_days']],
                        on=['event_id', 'ticker'], how='left')

# Charts use complete windows and exclude ETFs. METRICS keeps everything for
# the article table, where truncated events get reported with a flag.
CLEAN = METRICS[METRICS.window_complete & ~METRICS.ticker.isin(ETFS)].copy()

DISPERSION = CLEAN.groupby(['event_id', 'layer'])['day1_excess'].agg(['mean', 'std', 'count'])

print("\n=== Layer means, day-one excess (%) ===")
print((CLEAN.pivot_table(index='event_id', columns='layer',
                         values='day1_excess', aggfunc='mean') * 100).round(2).to_string())


# ============================================================
# 6. DATA EXPORT
# ============================================================
# Dumps every intermediate table to CSV so an LLM (or anyone) can search for
# patterns without re-running the pipeline. Long/tidy format throughout.
# Computed once here and reused (not re-read from disk) by the charts/tables
# sections below.

def event_paths_long():
    """Cumulative excess return path for every (event, ticker) pair -- the
    actual series behind the charts, in long format."""
    rows = []
    for _, ev in EVENTS_DF.iterrows():
        for t in LAYER_TICKERS:
            cum, complete = cum_excess(t, ev)
            if cum is None:
                continue
            rows.append(pd.DataFrame({
                'event_id': ev.event_id,
                'ticker': t,
                'layer': LAYER_OF[t],
                'offset': cum.index,
                'cum_excess_return': cum.values,
                'window_complete': complete,
            }))
    return pd.concat(rows, ignore_index=True)


EVENT_PATHS_LONG = event_paths_long()
DISPERSION_FLAT = DISPERSION.reset_index()


def save_all_data():
    # Raw OHLCV for every ticker (layer names + benchmarks), long format.
    price_rows = []
    for t, df in PRICE_PANEL.items():
        d = df.reset_index().rename(columns={'index': 'Date'})
        d['ticker'] = t
        d['layer'] = LAYER_OF.get(t, 'benchmark')
        price_rows.append(d)
    pd.concat(price_rows, ignore_index=True).to_csv(DATA_DIR / 'price_panel_raw.csv', index=False)

    EVENTS_DF.to_csv(DATA_DIR / 'events.csv', index=False)

    excess_rows = [s.rename('excess_return').to_frame().assign(ticker=t)
                   for t, s in EXCESS.items()]
    (pd.concat(excess_rows).reset_index().rename(columns={'index': 'Date'})
       .to_csv(DATA_DIR / 'excess_returns.csv', index=False))

    EVENT_PATHS_LONG.to_csv(DATA_DIR / 'event_paths.csv', index=False)

    ANCHOR_CHECK.to_csv(DATA_DIR / 'anchor_check.csv', index=False)
    METRICS.to_csv(DATA_DIR / 'metrics.csv', index=False)
    DISPERSION_FLAT.to_csv(DATA_DIR / 'dispersion.csv', index=False)

    print(f"\nSaved raw data -> {DATA_DIR}")


save_all_data()

# Aliases used by the charts/tables sections below -- same data section 6
# just wrote to CSV, reused in memory instead of reading it back.
metrics = METRICS
event_paths = EVENT_PATHS_LONG
dispersion = DISPERSION_FLAT
events = EVENTS_DF


# ============================================================
# 7. HOUSE STYLE
# ============================================================
# Shared constants/helpers for both the newsletter charts and tables below,
# so all nine PNGs read as one set.

NAVY, RED, GREY = '#1f3a68', '#c0392b', '#9aa5b1'
RULE_GREY = '#dfe3e8'  # table row-separator rule

LAYER_LABELS = {'wfe': 'equipment'}  # display-only; underlying column stays 'wfe'

FIG_WIDTH_PX = 2080
FIG_DPI = 200
FIG_WIDTH_IN = FIG_WIDTH_PX / FIG_DPI


def style_axes(ax, value_axis='y'):
    """White bg, no top/right spine, 0.3-alpha horizontal gridlines, solid
    zero line on the value axis."""
    ax.set_facecolor('white')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    if value_axis == 'y':
        ax.axhline(0, color='black', lw=0.8)
    else:
        ax.axvline(0, color='black', lw=0.8)


def suptitle(fig, text):
    fig.suptitle(text, x=0.02, ha='left', fontsize=14, fontweight='bold')


def color_key(ax, pairs, x=0.99, y0=1.02, dy=0.055):
    """Stack of colored words in the top-right corner -- direct labeling
    instead of a boxed legend, for charts with exactly two series."""
    for i, (label, color) in enumerate(pairs):
        ax.text(x, y0 + i * dy, label, transform=ax.transAxes, color=color,
                 fontweight='bold', fontsize=9, ha='right', va='bottom')


def save(fig, name):
    fig.savefig(FIG_DIR / name, dpi=FIG_DPI, facecolor='white')
    plt.close(fig)


def country_of(ticker):
    return 'China/Asia' if any(ticker.endswith(s) for s in ('.HK', '.KS', '.TW', '.T')) else 'US'


def sign_color(v):
    return RED if v < 0 else (NAVY if v > 0 else 'black')


SIX_EVENTS = ['r1', 'k2', 'v4_preview', 'v4_pricecut', 'glm52', 'k3']
BIREN_EVENTS = ['v4_preview', 'v4_pricecut', 'glm52', 'k3', 'k3_weights', 'v4_flash']

CHART_LABELS = []


def record_chart(chart, label, value, unit='%'):
    CHART_LABELS.append({'chart': chart, 'label': label, 'value': round(float(value), 2), 'unit': unit})


# ============================================================
# 8. NEWSLETTER CHARTS (chart_a .. chart_f)
# ============================================================

def chart_a():
    """"The tails swapped passports" -- worst 6 + best 1 names, T0-T+5, R1 vs K3."""
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 6), sharex=True)
    panels = [('r1', '2025-01-27'), ('k3', '2026-07-17')]
    for ax, (ev, date_label) in zip(axes, panels):
        sub = event_paths[(event_paths.event_id == ev) & (event_paths.offset == 5)
                           & (event_paths.ticker != 'SMH')].copy()
        sub['pct'] = sub['cum_excess_return'] * 100
        sel = pd.concat([sub.nsmallest(6, 'pct'), sub.nlargest(1, 'pct')]).sort_values('pct')

        colors = [NAVY if country_of(t) == 'US' else RED for t in sel['ticker']]
        bars = ax.barh(sel['ticker'], sel['pct'], color=colors)
        ax.margins(x=0.18)

        for ticker, val, bar in zip(sel['ticker'], sel['pct'], bars):
            y = bar.get_y() + bar.get_height() / 2
            ha = 'left' if val >= 0 else 'right'
            ax.annotate(f"{val:+.1f}%", xy=(val, y), xytext=(4 if val >= 0 else -4, 0),
                        textcoords='offset points', va='center', ha=ha, fontsize=8)
            record_chart('A', f"{ticker} ({ev})", val)
            if ticker == 'GOOGL' and ev == 'k3':
                ax.annotate('own model delay', xy=(val, y),
                            xytext=(-45, -16), textcoords='offset points',
                            fontsize=7, color=GREY, ha='right',
                            arrowprops=dict(arrowstyle='-', color=GREY, lw=0.6))

        style_axes(ax, value_axis='x')
        ax.set_title(f"{ev.upper()} — {date_label}", loc='left', fontsize=10)
        ax.set_xlabel('5-session cum. excess return, T0–T+5 (%)')

    color_key(axes[1], [('US', NAVY), ('China/Asia', RED)])
    suptitle(fig, 'The tails swapped passports')
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, 'chart_a.png')


def chart_b():
    """"The argument moved inside China" -- day-1 cross-sectional sigma by layer."""
    disp = dispersion[dispersion.event_id.isin(SIX_EVENTS)]
    piv = (disp.pivot(index='event_id', columns='layer', values='std')
               .reindex(SIX_EVENTS) * 100)
    layers = list(piv.columns)

    fig, ax = plt.subplots(figsize=(10.4, 6))
    n = len(layers)
    width = 0.8 / n
    x = np.arange(len(SIX_EVENTS))

    for i, layer in enumerate(layers):
        color = RED if layer == 'china' else (NAVY if layer == 'compute' else GREY)
        vals = piv[layer].values
        xpos = x + i * width - 0.4 + width / 2
        ax.bar(xpos, vals, width=width, color=color, label=LAYER_LABELS.get(layer, layer))
        for xi, xp, v in zip(x, xpos, vals):
            if not np.isnan(v):
                ax.text(xp, v + 0.15, f"{v:.1f}", ha='center', va='bottom', fontsize=6)
                record_chart('B', f"{LAYER_LABELS.get(layer, layer)} ({SIX_EVENTS[xi]})", v)

    ax.set_xticks(x)
    ax.set_xticklabels(SIX_EVENTS)
    style_axes(ax, value_axis='y')
    ax.set_ylabel('day-1 cross-sectional sigma, %')
    ax.legend(fontsize=7, ncol=3, frameon=False, loc='upper left')
    suptitle(fig, 'The argument moved inside China')
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, 'chart_b.png')


def chart_c():
    """"How long the damage takes to work through" -- median half-life, R1 vs K3."""
    sub = metrics[metrics.event_id.isin(['r1', 'k3']) & metrics.half_life.notna()]
    piv = sub.groupby(['layer', 'event_id'])['half_life'].median().unstack('event_id')
    layers = list(piv.index)

    fig, ax = plt.subplots(figsize=(10.4, 6))
    x = np.arange(len(layers))
    width = 0.35

    for i, ev in enumerate(['r1', 'k3']):
        color = NAVY if ev == 'r1' else RED
        vals = piv[ev].reindex(layers).values
        xpos = x + (i - 0.5) * width
        ax.bar(xpos, vals, width=width, color=color)
        for xi, xp, v in zip(x, xpos, vals):
            if not np.isnan(v):
                ax.text(xp, v + 0.1, f"{v:.1f}", ha='center', va='bottom', fontsize=8)
                record_chart('C', f"{LAYER_LABELS.get(layers[xi], layers[xi])} ({ev})", v, unit='sessions')

    ax.set_xticks(x)
    ax.set_xticklabels([LAYER_LABELS.get(l, l) for l in layers])
    style_axes(ax, value_axis='y')
    ax.set_ylabel('median sessions, trough to 50% recovery')
    color_key(ax, [('R1', NAVY), ('K3', RED)])
    suptitle(fig, 'How long the damage takes to work through')
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, 'chart_c.png')


US_LAYERS = ['compute', 'memory', 'wfe', 'power']


def chart_d():
    """"Where the money went, day by day" -- china avg vs US aggregate, T-5..T+5."""
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 5.5), sharey=True)
    panels = [('r1', '2025-01-27'), ('k3', '2026-07-17')]

    for ax, (ev, date_label) in zip(axes, panels):
        win = event_paths[(event_paths.event_id == ev)
                           & (event_paths.offset >= -5) & (event_paths.offset <= 5)]

        china = (win[win.layer == 'china']
                 .groupby('offset')['cum_excess_return'].mean() * 100).sort_index()
        us = (win[win.layer.isin(US_LAYERS) & (win.ticker != 'SMH')]
              .groupby('offset')['cum_excess_return'].mean() * 100).sort_index()

        ax.plot(china.index, china.values, color=RED, lw=2)
        ax.plot(us.index, us.values, color=NAVY, lw=2)
        ax.text(china.index[-1], china.values[-1], '  China', color=RED,
                fontsize=9, fontweight='bold', va='center')
        ax.text(us.index[-1], us.values[-1], '  US', color=NAVY,
                fontsize=9, fontweight='bold', va='center')

        for off, v in china.items():
            record_chart('D', f"china avg ({ev}, offset {off:+d})", v)
        for off, v in us.items():
            record_chart('D', f"us aggregate ({ev}, offset {off:+d})", v)

        ax.axvline(0, color=GREY, lw=0.8, ls='--')
        style_axes(ax, value_axis='y')
        ax.set_xlim(-5, 5)
        ax.set_title(f"{ev.upper()} — {date_label}", loc='left', fontsize=10)
        ax.set_xlabel('session offset (T0 = event date)')

    axes[0].set_ylabel('cum. excess return, % (rebased T-1)')
    suptitle(fig, 'Where the money went, day by day')
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, 'chart_d.png')


BIREN_MEAN = 15.8


def chart_e():
    """"Same news, fifteen times the move" -- Biren vs Alibaba, |day-1| move."""
    sub = metrics[metrics.event_id.isin(BIREN_EVENTS)]
    biren = (sub[sub.ticker == '2513.HK'].set_index('event_id')['day1_excess']
             .reindex(BIREN_EVENTS).abs() * 100)
    alibaba = (sub[sub.ticker == '9988.HK'].set_index('event_id')['day1_excess']
               .reindex(BIREN_EVENTS).abs() * 100)

    fig, ax = plt.subplots(figsize=(10.4, 6))
    x = np.arange(len(BIREN_EVENTS))
    width = 0.35

    ax.bar(x - width / 2, biren.values, width=width, color=RED)
    ax.bar(x + width / 2, alibaba.values, width=width, color=GREY)
    for xi, v in zip(x, biren.values):
        ax.text(xi - width / 2, v + 0.4, f"{v:.1f}", ha='center', va='bottom', fontsize=8)
        record_chart('E', f"Biren |day1| ({BIREN_EVENTS[xi]})", v)
    for xi, v in zip(x, alibaba.values):
        ax.text(xi + width / 2, v + 0.4, f"{v:.1f}", ha='center', va='bottom', fontsize=8)
        record_chart('E', f"Alibaba |day1| ({BIREN_EVENTS[xi]})", v)

    ax.axhline(BIREN_MEAN, color=RED, lw=1, ls='--')
    ax.text(len(BIREN_EVENTS) - 0.5, BIREN_MEAN + 0.5, 'Biren mean', color=RED,
            fontsize=8, ha='right')
    record_chart('E', 'Biren mean (ref line)', BIREN_MEAN)

    ax.set_xticks(x)
    ax.set_xticklabels(BIREN_EVENTS)
    style_axes(ax, value_axis='y')
    ax.set_ylabel('|day-1 excess return|, %')
    color_key(ax, [('Biren', RED), ('Alibaba', GREY)])
    suptitle(fig, 'Same news, fifteen times the move')
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, 'chart_e.png')


VOL_LAYERS = ['compute', 'memory', 'wfe']
RECENT_FOUR = ['v4_preview', 'v4_pricecut', 'glm52', 'k3']


def chart_f():
    """"What you'd be selling vol against" -- mean |day-1| move, compute+memory+equipment."""
    sub = metrics[metrics.event_id.isin(SIX_EVENTS) & metrics.layer.isin(VOL_LAYERS)
                  & (metrics.ticker != 'SMH')]
    vals = (sub.groupby('event_id')['day1_excess'].apply(lambda s: s.abs().mean())
            .reindex(SIX_EVENTS) * 100)

    fig, ax = plt.subplots(figsize=(10.4, 6))
    x = np.arange(len(SIX_EVENTS))
    edge = [RED if ev in RECENT_FOUR else 'none' for ev in SIX_EVENTS]
    ax.bar(x, vals.values, color=NAVY, edgecolor=edge, linewidth=2.5)
    for xi, v in zip(x, vals.values):
        ax.text(xi, v + 0.1, f"{v:.1f}", ha='center', va='bottom', fontsize=8)
        record_chart('F', f"compute+memory+equipment |day1| avg ({SIX_EVENTS[xi]})", v)

    lo, hi = x[SIX_EVENTS.index('v4_preview')], x[SIX_EVENTS.index('k3')]
    bracket_y = vals.values[2:].max() + 1.2
    ax.plot([lo, hi], [bracket_y, bracket_y], color=RED, lw=1)
    ax.text((lo + hi) / 2, bracket_y + 0.3, 'all under 3.3%', color=RED,
            fontsize=9, ha='center', fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(SIX_EVENTS)
    style_axes(ax, value_axis='y')
    ax.set_ylabel('mean |day-1 excess return|, %')
    suptitle(fig, "What you'd be selling vol against")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    save(fig, 'chart_f.png')


# ============================================================
# 9. NEWSLETTER TABLES (table_1 .. table_3)
# ============================================================
#
# Generic renderer: rows are either a list of (text, color) tuples (one per
# column) or a dict {'cells': [...], 'grey': bool, 'sep_before': bool} to
# de-emphasise a whole row or draw a heavier rule above it.

TABLE_LABELS = []


def record_table(source, label, value, unit='%'):
    TABLE_LABELS.append({'source': source, 'label': label, 'value': round(float(value), 2), 'unit': unit})


TITLE_H, HEADER_H, ROW_LINE_H, ROW_PAD = 0.55, 0.40, 0.22, 0.14
PAD_TOP, PAD_BOTTOM, SEP_GAP = 0.18, 0.15, 0.08


def _row_parts(row):
    if isinstance(row, dict):
        return row['cells'], row.get('grey', False), row.get('sep_before', False)
    return row, False, False


def render_table_png(name, title, col_labels, col_aligns, col_widths, rows,
                      has_header=True, wrap_cols=None, bold_cols=None):
    wrap_cols = wrap_cols or {}
    bold_cols = bold_cols or set()

    prepared = []
    for row in rows:
        cells, grey, sep = _row_parts(row)
        new_cells, n_lines = [], 1
        for i, (text, color) in enumerate(cells):
            t = str(text)
            if i in wrap_cols:
                wrapped = textwrap.wrap(t, wrap_cols[i])
                t = '\n'.join(wrapped) if wrapped else t
            n_lines = max(n_lines, t.count('\n') + 1)
            new_cells.append((t, color))
        prepared.append({'cells': new_cells, 'grey': grey, 'sep': sep, 'n_lines': n_lines})

    header_h = HEADER_H if has_header else 0
    content_h = sum(ROW_PAD + p['n_lines'] * ROW_LINE_H + (SEP_GAP if p['sep'] else 0)
                     for p in prepared)
    height = PAD_TOP + TITLE_H + header_h + content_h + PAD_BOTTOM

    fig = plt.figure(figsize=(FIG_WIDTH_IN, height), dpi=FIG_DPI, facecolor='white')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(height, 0)  # y=0 at the top

    x_margin = 0.015
    usable_w = 1 - 2 * x_margin
    col_x, acc = [], x_margin
    for w in col_widths:
        col_x.append(acc)
        acc += w * usable_w

    ax.text(x_margin, PAD_TOP + TITLE_H * 0.5, title, fontsize=14,
            fontweight='bold', va='center', ha='left')

    y = PAD_TOP + TITLE_H

    if has_header:
        ax.add_patch(mpatches.Rectangle((0, y), 1, header_h, facecolor=NAVY, edgecolor='none'))
        for label, align, xpos, w in zip(col_labels, col_aligns, col_x, col_widths):
            tx = xpos if align == 'left' else xpos + w * usable_w
            ax.text(tx, y + header_h / 2, label, color='white', fontweight='bold',
                    fontsize=10, va='center', ha=align)
        y += header_h

    for p in prepared:
        if p['sep']:
            ax.plot([0, 1], [y, y], color=NAVY, lw=1.2)
            y += SEP_GAP
        row_h = ROW_PAD + p['n_lines'] * ROW_LINE_H
        cy = y + row_h / 2
        for i, ((text, color), align, xpos, w) in enumerate(zip(p['cells'], col_aligns, col_x, col_widths)):
            tx = xpos if align == 'left' else xpos + w * usable_w
            c = GREY if p['grey'] else color
            fw = 'bold' if i in bold_cols else 'normal'
            ax.text(tx, cy, text, color=c, fontsize=9.5, va='center', ha=align, fontweight=fw)
        y += row_h
        ax.plot([0, 1], [y, y], color=RULE_GREY, lw=0.5)

    save(fig, name)


def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def render_table_html(name, title, col_labels, col_aligns, rows, has_header=True):
    lines = [
        '<table style="border-collapse:collapse;font-family:Georgia,serif;width:100%;">',
        f'<caption style="text-align:left;font-weight:bold;font-size:1.15em;'
        f'padding-bottom:10px;">{_esc(title)}</caption>',
    ]
    if has_header:
        lines.append('<tr>')
        for label, align in zip(col_labels, col_aligns):
            lines.append(f'<th style="background:{NAVY};color:#ffffff;text-align:{align};'
                         f'padding:6px 10px;border-bottom:1px solid {RULE_GREY};">{_esc(label)}</th>')
        lines.append('</tr>')
    for row in rows:
        cells, grey, _ = _row_parts(row)
        lines.append('<tr>')
        for (text, color), align in zip(cells, col_aligns):
            c = GREY if grey else color
            text_html = _esc(text).replace('\n', '<br>')
            lines.append(f'<td style="text-align:{align};padding:6px 10px;'
                         f'border-bottom:1px solid {RULE_GREY};color:{c};">{text_html}</td>')
        lines.append('</tr>')
    lines.append('</table>')
    (FIG_DIR / name).write_text('\n'.join(lines), encoding='utf-8')


def print_markdown(title, col_labels, col_aligns, rows, has_header=True):
    print(f"\n### {title}\n")
    if has_header:
        print('| ' + ' | '.join(col_labels) + ' |')
        print('|' + '|'.join('---' if a == 'left' else '---:' for a in col_aligns) + '|')
    for row in rows:
        cells, grey, _ = _row_parts(row)
        text_cells = [str(text).replace('\n', ' ') for text, _ in cells]
        marker = ' *(no usable window)*' if grey and not has_header else ''
        print('| ' + ' | '.join(text_cells) + ' |' + marker)


WHAT_ELSE = {
    'r1': "FOMC 28-29 Jan 2025, day after reaction date. HK closure claim DISPUTED.",
    'k2': "clean",
    'v4_preview': "clean",
    'v4_pricecut': "Nvidia Q1 FY27 earnings 20 May 2026 - DATE CONFLICT vs Jun-26 label",
    'glm52': "FOMC 16-17 Jun 2026 + export controls",
    'k3': ("KRX closure claim DISPUTED. FOMC 28-29 Jul 2026 lands at T+8, which is "
           "why every headline number is cut at T+5."),
    'k3_weights': "no usable window",
    'v4_flash': "no usable window",
}


def build_table_1():
    """"The eight events, and what else was going on" -- events.csv + hardcoded notes."""
    ev_sorted = events.sort_values('anchor_date')
    rows = []
    for _, e in ev_sorted.iterrows():
        eid = e['event_id']
        grey = eid not in SIX_EVENTS
        cells = [
            (eid, 'black'),
            (e['release_date'].strftime('%Y-%m-%d'), 'black'),
            (e['anchor_date'].strftime('%Y-%m-%d'), 'black'),
            (e['event_type'], 'black'),
            (WHAT_ELSE[eid], 'black'),
        ]
        rows.append({'cells': cells, 'grey': grey})

    col_labels = ['Event', 'Release date', 'Reaction date', 'Type', 'What else was happening']
    col_aligns = ['left'] * 5
    col_widths = [0.09, 0.11, 0.12, 0.12, 0.56]
    title = 'The eight events, and what else was going on'

    render_table_png('table_1.png', title, col_labels, col_aligns, col_widths, rows,
                     wrap_cols={4: 68})
    render_table_html('table_1.html', title, col_labels, col_aligns, rows)
    print_markdown(title, col_labels, col_aligns, rows)


LAYER_ORDER = ['power', 'compute', 'memory', 'wfe', 'model', 'china']
BIREN_TICKER = '2513.HK'


def group_worst_t0_t5(layer, event_id, exclude=()):
    """Worst point (min) of the layer's equal-weight average cumulative
    excess return path, restricted to offset 0..5. Excludes SMH always."""
    excl = set(exclude) | {'SMH'}
    sub = event_paths[(event_paths.event_id == event_id) & (event_paths.layer == layer)
                       & (event_paths.offset >= 0) & (event_paths.offset <= 5)
                       & (~event_paths.ticker.isin(excl))]
    avg_path = sub.groupby('offset')['cum_excess_return'].mean()
    return np.nan if avg_path.empty else avg_path.min() * 100


def best_worst_name(event_id):
    """Single best/worst NAME (not group) at T+5, excluding SMH -- same
    selection chart_a uses, printed here as a cross-check, not on the PNG."""
    sub = event_paths[(event_paths.event_id == event_id) & (event_paths.offset == 5)
                       & (event_paths.ticker != 'SMH')].copy()
    sub['pct'] = sub['cum_excess_return'] * 100
    return sub.loc[sub.pct.idxmax()], sub.loc[sub.pct.idxmin()]


def build_table_2():
    """"Where the damage landed, R1 vs Kimi K3" -- computed from metrics/event_paths."""
    rows = []
    for layer in LAYER_ORDER:
        label = LAYER_LABELS.get(layer, layer)
        r1_val = group_worst_t0_t5(layer, 'r1')
        k3_val = group_worst_t0_t5(layer, 'k3')
        rows.append({'cells': [
            (label, 'black'),
            (f"{r1_val:+.1f}%", sign_color(r1_val)),
            (f"{k3_val:+.1f}%", sign_color(k3_val)),
        ]})
        record_table('table_2.png', f"{label} worst T0-T5 (r1)", r1_val)
        record_table('table_2.png', f"{label} worst T0-T5 (k3)", k3_val)

    spreads = {}
    for ev in ['r1', 'k3']:
        sub = event_paths[(event_paths.event_id == ev) & (event_paths.offset == 5)
                           & (event_paths.ticker != 'SMH')]
        pct = sub['cum_excess_return'] * 100
        spreads[ev] = pct.max() - pct.min()
    rows.append({'sep_before': True, 'cells': [
        ('Best-minus-worst spread (all names)', 'black'),
        (f"{spreads['r1']:.1f} pts", NAVY),
        (f"{spreads['k3']:.1f} pts", NAVY),
    ]})
    record_table('table_2.png', 'best-minus-worst spread (r1)', spreads['r1'], unit='pts')
    record_table('table_2.png', 'best-minus-worst spread (k3)', spreads['k3'], unit='pts')

    china_ex_r1 = group_worst_t0_t5('china', 'r1', exclude={BIREN_TICKER})
    china_ex_k3 = group_worst_t0_t5('china', 'k3', exclude={BIREN_TICKER})
    rows.append({'cells': [
        ('China ex-Biren', 'black'),
        (f"{china_ex_r1:+.1f}%", sign_color(china_ex_r1)),
        (f"{china_ex_k3:+.1f}%", sign_color(china_ex_k3)),
    ]})
    record_table('table_2.png', 'china ex-Biren worst T0-T5 (r1)', china_ex_r1)
    record_table('table_2.png', 'china ex-Biren worst T0-T5 (k3)', china_ex_k3)

    col_labels = ['Group', 'R1 (2025-01-27)', 'K3 (2026-07-17)']
    col_aligns = ['left', 'right', 'right']
    col_widths = [0.4, 0.3, 0.3]
    title = 'Where the damage landed, R1 vs Kimi K3'

    render_table_png('table_2.png', title, col_labels, col_aligns, col_widths, rows)
    render_table_html('table_2.html', title, col_labels, col_aligns, rows)
    print_markdown(title, col_labels, col_aligns, rows)

    print("\n--- Table 2: single best/worst NAME per event, T+5, ex-SMH (cross-check vs article) ---")
    for ev in ['r1', 'k3']:
        best, worst = best_worst_name(ev)
        print(f"{ev}: best = {best.ticker} ({best.pct:+.1f}%)   "
              f"worst = {worst.ticker} ({worst.pct:+.1f}%)")


TRADE_ROWS = [
    ('Position', 'Long optionality on Chinese AI pure-plays, short optionality on '
                  'US semis into a parity release window', 'black'),
    ('Trigger', 'A Chinese frontier release at or above current frontier capability', 'black'),
    ('Entry', 'T-2 or T-1 vs expected release date; half size on announcement, '
              'half on day-one confirmation', 'black'),
    ('Horizon', '20 sessions', 'black'),
    ('Target', 'TODO - implied vol at entry vs realised 15.8% mean day-one move '
               'on the pure-play leg', RED),
    ('Invalidation', 'Nvidia moves more than 3% on day one', 'black'),
    ('Sizing', 'Pure-play leg sized as option premium, written off to zero', 'black'),
    ('Execution', 'Biren and recent HK/STAR listings: options near-untradeable, '
                  'borrow thin and expensive, foreign retail shut out of mainland '
                  'IPOs. Realistic: small outright pure-play long, an HSTECH/KWEB '
                  'overlay capturing roughly a fifth of the move, or nothing.', 'black'),
]


def build_table_3():
    """"The trade" -- no CSV, hardcoded trade sheet. Target field still a TODO."""
    rows = [{'cells': [(field, NAVY), (detail, color)]} for field, detail, color in TRADE_ROWS]
    col_labels = ['Field', 'Detail']
    col_aligns = ['left', 'left']
    col_widths = [0.16, 0.84]
    title = 'The trade'

    render_table_png('table_3.png', title, col_labels, col_aligns, col_widths, rows,
                     has_header=False, wrap_cols={1: 95}, bold_cols={0})
    render_table_html('table_3.html', title, col_labels, col_aligns, rows, has_header=False)
    print_markdown(title, col_labels, col_aligns, rows, has_header=False)
    print("\n*** TABLE 3 SHIPS WITH AN UNFILLED TARGET ***")


# ============================================================
# 10. RUN
# ============================================================

chart_a()
chart_b()
chart_c()
chart_d()
chart_e()
chart_f()

build_table_1()
build_table_2()
build_table_3()

print("\n" + "=" * 70)
print("CONSOLIDATED DATA LABELS -- every number on every chart/table")
print("=" * 70)

ALL_LABELS = (
    [{**d, 'source': f"chart_{d['chart'].lower()}.png"} for d in CHART_LABELS]
    + TABLE_LABELS
)
labels_df = pd.DataFrame(ALL_LABELS)
for source, g in labels_df.groupby('source'):
    print(f"\n--- {source} ---")
    print(g[['label', 'value', 'unit']].to_string(index=False))
