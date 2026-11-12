"""
International Cost of Capital App
Compares a project's cost of equity, cost of debt and WACC in USD and in the
currency of a selected country.

Data sources (fetched live, cached, refreshable):
  - Unlevered industry betas ........ Damodaran, betas.xls (U.S.)
  - BBB (Baa2) USD default spread ... Damodaran, ratings.html (large non-financial firms)
  - Statutory corporate tax rates ... OECD Corporate Tax Statistics (combined CIT rate)
  - 10-year government bond yields .. Trading Economics, /bonds

Every fetched value can be overridden manually in the sidebar.
"""

from __future__ import annotations

import html as htmllib
import io
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests
import streamlit as st

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
BETA_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URLS = [
    "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html",
    "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ratings.html",
]
OECD_PAGE_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html#chapter-d1e2342-08e74a33fb"
)
# Machine-readable version of the same OECD statutory CIT data (SDMX API)
_OECD_BASE = "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,{ver}/all"
OECD_API_ATTEMPTS = [  # (url, extra headers)
    (_OECD_BASE.format(ver="") + "?startPeriod=2020&format=csvfilewithlabels", {}),
    (_OECD_BASE.format(ver="") + "?startPeriod=2020&dimensionAtObservation=AllDimensions"
     "&format=csvfilewithlabels", {}),
    (_OECD_BASE.format(ver="") + "?startPeriod=2020",
     {"Accept": "application/vnd.sdmx.data+csv; charset=utf-8; labels=both"}),
]
TE_URL = "https://tradingeconomics.com/bonds"

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"
DEFAULT_ERP = 6.5  # %
DEFAULT_DEBT_SHARE = 30  # %

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Fallback combined statutory CIT rates (%), OECD Corporate Tax Statistics 2024
# edition (tax year 2024). Used ONLY if the OECD fetch fails; shown as "fallback".
FALLBACK_TAX = {
    "United States": 25.8, "Canada": 26.1, "Mexico": 30.0, "Brazil": 34.0,
    "Argentina": 35.0, "Chile": 27.0, "Colombia": 35.0, "Peru": 29.5,
    "United Kingdom": 25.0, "Germany": 29.9, "France": 25.8, "Italy": 27.8,
    "Spain": 25.0, "Portugal": 31.5, "Netherlands": 25.8, "Belgium": 25.0,
    "Switzerland": 19.6, "Austria": 23.0, "Ireland": 12.5, "Sweden": 20.6,
    "Norway": 22.0, "Denmark": 22.0, "Finland": 20.0, "Poland": 19.0,
    "Czech Republic": 21.0, "Hungary": 9.0, "Greece": 22.0, "Turkey": 25.0,
    "Israel": 23.0, "Japan": 29.7, "South Korea": 26.4, "China": 25.0,
    "India": 25.2, "Indonesia": 22.0, "Philippines": 25.0, "Thailand": 20.0,
    "Vietnam": 20.0, "Malaysia": 24.0, "Singapore": 17.0, "Hong Kong": 16.5,
    "Australia": 30.0, "New Zealand": 28.0, "South Africa": 27.0,
    "Nigeria": 30.0, "Kenya": 30.0, "Egypt": 22.5, "Saudi Arabia": 20.0,
    "Pakistan": 29.0, "Russia": 20.0,
}

# Harmonise country names across OECD and Trading Economics
ALIASES = {
    "us": "United States", "usa": "United States", "u.s.": "United States",
    "uk": "United Kingdom", "korea": "South Korea", "korea, republic of": "South Korea",
    "türkiye": "Turkey", "turkiye": "Turkey", "china (people's republic of)": "China",
    "hong kong, china": "Hong Kong", "hong kong (china)": "Hong Kong",
    "slovak republic": "Slovakia", "czechia": "Czech Republic", "viet nam": "Vietnam",
    "russian federation": "Russia", "chinese taipei": "Taiwan",
    "euro area": "Euro Area",
}

CURRENCY = {
    "United States": "USD", "Canada": "CAD", "Mexico": "MXN", "Brazil": "BRL",
    "Argentina": "ARS", "Chile": "CLP", "Colombia": "COP", "Peru": "PEN",
    "United Kingdom": "GBP", "Switzerland": "CHF", "Sweden": "SEK", "Norway": "NOK",
    "Denmark": "DKK", "Poland": "PLN", "Czech Republic": "CZK", "Hungary": "HUF",
    "Turkey": "TRY", "Israel": "ILS", "Japan": "JPY", "South Korea": "KRW",
    "China": "CNY", "India": "INR", "Indonesia": "IDR", "Philippines": "PHP",
    "Thailand": "THB", "Vietnam": "VND", "Malaysia": "MYR", "Singapore": "SGD",
    "Hong Kong": "HKD", "Australia": "AUD", "New Zealand": "NZD",
    "South Africa": "ZAR", "Nigeria": "NGN", "Kenya": "KES", "Egypt": "EGP",
    "Pakistan": "PKR", "Russia": "RUB", "Taiwan": "TWD", "Iceland": "ISK",
    "Romania": "RON", "Bulgaria": "BGN", "Serbia": "RSD", "Ukraine": "UAH",
    "Bangladesh": "BDT", "Sri Lanka": "LKR", "Morocco": "MAD", "Uganda": "UGX",
    "Zambia": "ZMW", "Botswana": "BWP", "Namibia": "NAD", "Mauritius": "MUR",
}
EURO = {
    "Germany", "France", "Italy", "Spain", "Portugal", "Netherlands", "Belgium",
    "Austria", "Ireland", "Finland", "Greece", "Slovakia", "Slovenia", "Lithuania",
    "Latvia", "Estonia", "Croatia", "Cyprus", "Malta", "Luxembourg", "Euro Area",
}


def canon(name: str) -> str:
    """Canonical country name."""
    n = re.sub(r"\s+", " ", str(name)).strip()
    n = re.sub(r"\s*10Y$", "", n, flags=re.I).strip()
    return ALIASES.get(n.lower(), n)


def currency_of(country: str) -> str:
    if country in EURO:
        return "EUR"
    return CURRENCY.get(country, "Local currency")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --------------------------------------------------------------------------------------
# Data fetchers (cached; the Refresh button clears the cache)
# --------------------------------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_betas():
    """Damodaran U.S. industry unlevered betas."""
    meta = {"source": "Damodaran – Betas by Sector (US)", "url": BETA_URL,
            "fetched": now_utc(), "as_of": "n/a", "status": "ok"}
    try:
        r = requests.get(BETA_URL, headers=HEADERS, timeout=40)
        r.raise_for_status()
        sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
        raw = sheets.get("Industry Averages")
        if raw is None:  # find any sheet that has an "Industry Name" header
            raw = next(df for df in sheets.values()
                       if df.astype(str).apply(lambda c: c.str.strip().eq("Industry Name")).any().any())
        hdr_idx = raw.index[raw.astype(str).apply(
            lambda row: row.str.strip().eq("Industry Name").any(), axis=1)][0]

        # Date stamp sits in the rows above the header ("Date updated:")
        for i in range(hdr_idx):
            row = raw.iloc[i].tolist()
            for j, v in enumerate(row):
                if isinstance(v, str) and "date" in v.lower():
                    rest = [x for x in row[j + 1:] if pd.notna(x)]
                    if rest:
                        d = rest[0]
                        meta["as_of"] = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    break
            if meta["as_of"] != "n/a":
                break

        df = raw.iloc[hdr_idx + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[hdr_idx]]
        ucol = next(c for c in df.columns if c.lower() == "unlevered beta")
        out = df[["Industry Name", ucol]].rename(columns={"Industry Name": "Industry", ucol: "Unlevered beta"})
        out["Unlevered beta"] = pd.to_numeric(out["Unlevered beta"], errors="coerce")
        out = out.dropna()
        out = out[~out["Industry"].str.contains("Total Market", case=False)]
        out["Industry"] = out["Industry"].str.strip()
        return out.reset_index(drop=True), meta
    except Exception as e:  # noqa: BLE001
        meta["status"] = f"failed: {e}"
        return pd.DataFrame(columns=["Industry", "Unlevered beta"]), meta


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_bbb_spread():
    """Damodaran Baa2/BBB default spread, large non-financial service firms (1st table)."""
    meta = {"source": "Damodaran – Ratings, coverage ratios & default spreads "
                      "(Baa2/BBB, large non-financial firms)",
            "url": RATINGS_URLS[0], "fetched": now_utc(), "as_of": "n/a", "status": "ok"}
    last_err = None
    for url in RATINGS_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            html = r.text
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", htmllib.unescape(text).replace("\xa0", " "))
            m = re.search(r"(January|February|March|April|May|June|July|August|September|"
                          r"October|November|December)\s+(?:\d{1,2},\s*)?(20\d{2})", text)
            if m:
                meta["as_of"] = m.group(0)
            # Primary: first "Baa2/BBB <x.xx>%" in page text (first table = large non-financial firms)
            mm = re.search(r"Baa2\s*/\s*BBB\s*(-?\d+(?:\.\d+)?)\s*%", text)
            if mm:
                meta["url"] = url
                return float(mm.group(1)) / 100, meta
            # Fallback: parse HTML tables
            tables = pd.read_html(io.StringIO(html))
            for t in tables:  # first table = large non-financial service firms
                for _, row in t.astype(str).iterrows():
                    cells = [c for c in row.tolist()]
                    if any("Baa2/BBB" in c.replace(" ", "") for c in cells):
                        pcts = re.findall(r"(-?\d+(?:\.\d+)?)\s*%", " ".join(cells))
                        if pcts:
                            meta["url"] = url
                            return float(pcts[-1]) / 100, meta
                        nums = [float(c) for c in cells if re.fullmatch(r"-?\d+(\.\d+)?", c.strip())]
                        if nums:
                            v = nums[-1]
                            meta["url"] = url
                            return (v / 100 if v > 0.2 else v), meta
            last_err = "Baa2/BBB row not found"
        except Exception as e:  # noqa: BLE001
            last_err = e
    meta["status"] = f"failed: {last_err}"
    return np.nan, meta


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_tax_rates():
    """OECD combined (central + sub-central) statutory CIT rates, latest year per country."""
    meta = {"source": "OECD Corporate Tax Statistics – statutory CIT rates (combined)",
            "url": OECD_PAGE_URL, "fetched": now_utc(), "as_of": "n/a", "status": "ok"}
    errors = []
    df = None
    for url, extra in OECD_API_ATTEMPTS:
        try:
            r = requests.get(url, headers={**HEADERS, **extra}, timeout=60)
            r.raise_for_status()
            cand = pd.read_csv(io.StringIO(r.text), low_memory=False)
            if {"TIME_PERIOD", "OBS_VALUE"} <= set(cand.columns):
                df = cand
                break
            errors.append(f"unexpected columns {list(cand.columns)[:6]}")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e)[:120])
    try:
        if df is None:
            raise ValueError(" | ".join(errors))
        area_col = next((c for c in ("Reference area", "REF_AREA: Reference area", "REF_AREA")
                         if c in df.columns), "REF_AREA")
        label_cols = [c for c in df.columns if df[c].dtype == object and c not in (area_col,)]
        txt = df[label_cols].astype(str).agg(" | ".join, axis=1).str.lower()
        mask = txt.str.contains("combined|comb") & ~txt.str.contains("target|small|sub-central|subcentral")
        sub = df.loc[mask, [area_col, "TIME_PERIOD", "OBS_VALUE"]].dropna()
        if sub.empty:
            raise ValueError("no 'combined' CIT rows in OECD response")
        sub["TIME_PERIOD"] = pd.to_numeric(sub["TIME_PERIOD"], errors="coerce")
        sub = sub.sort_values("TIME_PERIOD").groupby(area_col).tail(1)
        area_vals = sub[area_col].astype(str).str.split(":").str[-1].str.strip()
        out = pd.DataFrame({
            "Country": area_vals.map(canon),
            "Tax rate": sub["OBS_VALUE"].astype(float) / 100,
            "Year": sub["TIME_PERIOD"].astype(int),
        }).drop_duplicates("Country")
        meta["as_of"] = f"tax year {int(out['Year'].max())} (OECD SDMX API)"
        return out.reset_index(drop=True), meta
    except Exception as e:  # noqa: BLE001
        meta["status"] = f"OECD API failed ({str(e)[:300]}); using embedded OECD 2024 snapshot"
        meta["as_of"] = "tax year 2024 (Corporate Tax Statistics 2024, embedded fallback)"
        out = pd.DataFrame({"Country": list(FALLBACK_TAX),
                            "Tax rate": [v / 100 for v in FALLBACK_TAX.values()],
                            "Year": 2024})
        return out, meta


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_yields():
    """Trading Economics 10-year government bond yields (all regional tables)."""
    meta = {"source": "Trading Economics – 10Y government bond yields", "url": TE_URL,
            "fetched": now_utc(), "as_of": "n/a", "status": "ok"}
    try:
        r = requests.get(TE_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        rows = {}
        dates = []
        for t in tables:
            t.columns = [str(c).strip() for c in t.columns]
            ycol = next((c for c in t.columns if c.lower() == "yield"), None)
            if ycol is None:
                continue
            # name column = first text column that is not the yield/date column
            name_col = None
            for c in t.columns:
                if c == ycol or c.lower() == "date":
                    continue
                vals = t[c].dropna().astype(str)
                if len(vals) and vals.str.contains(r"[A-Za-z]").mean() > 0.8:
                    name_col = c
                    break
            if name_col is None:
                continue
            dcol = next((c for c in t.columns if c.lower() == "date"), None)
            for _, row in t.iterrows():
                y = pd.to_numeric(str(row[ycol]).replace("%", ""), errors="coerce")
                if pd.isna(y):
                    continue
                name = canon(row[name_col])
                d = str(row[dcol]) if dcol else ""
                rows.setdefault(name, (y / 100, d))
                if d:
                    dates.append(d)
        if not rows:
            raise ValueError("no yield tables parsed")
        out = pd.DataFrame([(k, v[0], v[1]) for k, v in rows.items()],
                           columns=["Country", "10Y yield", "Quote date"])
        if dates:
            meta["as_of"] = f"latest quote {pd.Series(dates).mode().iloc[0]} (TE table date)"
        return out.sort_values("Country").reset_index(drop=True), meta
    except Exception as e:  # noqa: BLE001
        meta["status"] = f"failed: {e} – use the manual yield overrides"
        return pd.DataFrame(columns=["Country", "10Y yield", "Quote date"]), meta


# --------------------------------------------------------------------------------------
# Calculation engine (pure function – easy to verify)
# --------------------------------------------------------------------------------------
def compute(bu, tax, w_d, erp, y_us, y_f, s_us, s_f_override=None):
    """
    Class formulas (all rates decimals, full precision; round only for display).
      D/E   = d / (1 - d)
      bE    = bU * [1 + (1 - t) * D/E]
      USD:  Re  = Rf + bE * ERP          Rd  = Rf + s
            WACC = (1 - d) Re + d Rd (1 - t)
      FC:   F   = (1 + Rf*) / (1 + Rf)
            Re* = (1 + Re) F - 1
            s*  = s F   (unless overridden)
            Rd* = Rf* + s*
            WACC* = (1 - d) Re* + d Rd* (1 - t)
    """
    w_e = 1 - w_d
    de = w_d / w_e
    bl = bu * (1 + (1 - tax) * de)

    ke_us = y_us + bl * erp
    kd_us = y_us + s_us

    F = (1 + y_f) / (1 + y_us)
    ke_f = (1 + ke_us) * F - 1
    s_f_auto = s_us * F
    s_f = s_f_auto if s_f_override is None else s_f_override
    kd_f = y_f + s_f

    wacc_us = w_e * ke_us + w_d * kd_us * (1 - tax)
    wacc_f = w_e * ke_f + w_d * kd_f * (1 - tax)

    return {
        "levered_beta": bl, "de_ratio": de, "conversion_factor_F": F,
        "rf_us": y_us, "rf_f": y_f,
        "ke_us": ke_us, "ke_f": ke_f,
        "spread_us": s_us, "spread_f": s_f, "spread_f_auto": s_f_auto,
        "kd_us": kd_us, "kd_f": kd_f,
        "kd_at_us": kd_us * (1 - tax), "kd_at_f": kd_f * (1 - tax),
        "wacc_us": wacc_us, "wacc_f": wacc_f,
    }


def run_checks(bu, tax, w_d, erp, y_us, y_f, s_us):
    """The three verification checks required by the assignment."""
    base = compute(bu, tax, w_d, erp, y_us, y_f, s_us, None)
    eq = compute(bu, tax, w_d, erp, y_us, y_us, s_us, None)
    zero = compute(bu, tax, 0.0, erp, y_us, y_f, s_us, None)
    ovr = compute(bu, tax, w_d, erp, y_us, y_f, s_us, base["spread_f_auto"] + 0.02)
    tol = 1e-12
    return [
        ("Equal government yields → identical USD and foreign results (spread override off)",
         all(abs(eq[a] - eq[b]) < tol for a, b in
             [("ke_us", "ke_f"), ("kd_us", "kd_f"), ("wacc_us", "wacc_f")])),
        ("Zero debt → WACC equals cost of equity (both currencies)",
         abs(zero["wacc_us"] - zero["ke_us"]) < tol and abs(zero["wacc_f"] - zero["ke_f"]) < tol),
        ("Overriding the foreign spread (+200 bp) leaves all USD results unchanged",
         all(abs(base[k] - ovr[k]) < tol for k in ("ke_us", "kd_us", "wacc_us"))),
    ]


def pct(x, d=2):
    return "—" if x is None or pd.isna(x) else f"{x * 100:.{d}f}%"


# --------------------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="International Cost of Capital", page_icon="🌐", layout="wide")
    st.title("🌐 International Cost of Capital")
    st.caption("Cost of equity, cost of debt and WACC for a project in USD and in the "
               "currency of a selected country.")

    with st.spinner("Fetching latest data…"):
        betas, m_beta = fetch_betas()
        spread_usd, m_spread = fetch_bbb_spread()
        taxes, m_tax = fetch_tax_rates()
        yields, m_yld = fetch_yields()

    tax_map = dict(zip(taxes["Country"], taxes["Tax rate"]))
    yld_map = dict(zip(yields["Country"], yields["10Y yield"]))
    date_map = dict(zip(yields["Country"], yields["Quote date"]))

    # ---------------- Sidebar ----------------
    sb = st.sidebar
    if sb.button("🔄 Refresh data", width="stretch",
                 help="Clear the cache and re-fetch all sources"):
        st.cache_data.clear()
        st.rerun()

    sb.header("Project inputs")
    industries = betas["Industry"].tolist() or [DEFAULT_INDUSTRY]
    industry = sb.selectbox("Industry", industries,
                            index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0)

    countries = sorted(set(yld_map) | set(tax_map) | {DEFAULT_COUNTRY})
    countries = [c for c in countries if c != "Euro Area"]
    country = sb.selectbox("Target country", countries, index=countries.index(DEFAULT_COUNTRY))
    ccy = currency_of(country)

    erp = sb.number_input("Equity risk premium (%)", 0.0, 20.0, DEFAULT_ERP, 0.1) / 100
    w_d = sb.slider("Target debt share D/(D+E) (%)", 0, 90, DEFAULT_DEBT_SHARE, 1) / 100

    tax_basis = sb.radio("Project tax rate", ["U.S. rate", f"{country} rate"],
                         horizontal=True, index=0)

    sb.header("Manual overrides")

    def override(label, fetched, key, step=0.01, unit="%"):
        on = sb.checkbox(f"Override {label}", key=f"ov_{key}")
        if on:
            default = 0.0 if fetched is None or pd.isna(fetched) else (fetched * 100 if unit == "%" else fetched)
            v = sb.number_input(f"{label} ({unit})" if unit else label, value=float(round(default, 4)),
                                step=step, format="%.4f", key=f"val_{key}")
            return (v / 100 if unit == "%" else v), True
        return fetched, False

    bu_fetched = betas.loc[betas["Industry"] == industry, "Unlevered beta"]
    bu_fetched = float(bu_fetched.iloc[0]) if len(bu_fetched) else np.nan

    bu, ov_bu = override("unlevered beta", bu_fetched, "bu", 0.01, "")
    tax_us, ov_tus = override("U.S. tax rate", tax_map.get("United States"), "tus")
    tax_f, ov_tf = override(f"{country} tax rate", tax_map.get(country), "tf")
    s_us, ov_s = override("USD BBB spread", spread_usd, "s")
    y_us, ov_yus = override("U.S. 10Y yield", yld_map.get("United States"), "yus")
    y_f, ov_yf = override(f"{country} 10Y yield", yld_map.get(country), "yf")
    if country == "United States" and not ov_yf:
        y_f = y_us  # same country → same yield (incl. any U.S. override)
    if country == "United States" and not ov_tf:
        tax_f = tax_us

    ov_sf = sb.checkbox(f"Override {ccy} BBB spread", key="ov_sf",
                        help="Off = auto: s* = s × (1 + Rf*) / (1 + Rf)")
    s_f_input = None
    if ov_sf:
        s_f_input = sb.number_input(f"{ccy} BBB spread (%)", value=1.50, step=0.01,
                                    format="%.4f", key="val_sf") / 100

    tax = tax_us if tax_basis.startswith("U.S.") else tax_f

    # ---------------- Missing-data guard ----------------
    missing = [n for n, v in [("unlevered beta", bu), ("project tax rate", tax),
                              ("USD BBB spread", s_us), ("U.S. 10Y yield", y_us),
                              (f"{country} 10Y yield", y_f)]
               if v is None or pd.isna(v)]
    if missing:
        st.error("Missing data: " + ", ".join(missing) +
                 ". The live fetch did not return these – enter them under **Manual overrides**.")
        show_sources(m_beta, m_spread, m_tax, m_yld)
        st.stop()

    r = compute(bu, tax, w_d, erp, y_us, y_f, s_us, s_f_input)

    # ---------------- Results side by side ----------------
    st.subheader(f"{industry} · United States (USD) vs {country} ({ccy})")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("WACC – USD", pct(r["wacc_us"]))  # display rounding only
    k2.metric(f"WACC – {ccy}", pct(r["wacc_f"]), delta=f"{(r['wacc_f'] - r['wacc_us']) * 1e4:+.0f} bp vs USD",
              delta_color="off")
    k3.metric("Levered beta", f"{r['levered_beta']:.3f}")
    k4.metric("Project tax rate", pct(tax), help=f"Basis: {tax_basis}")

    res = pd.DataFrame({
        "Component": ["10Y government yield (risk-free)", "Conversion factor F = (1+Rf*)/(1+Rf)",
                      "Debt/equity D/E", "Unlevered beta", "Levered beta",
                      "Equity risk premium", "Cost of equity",
                      "BBB default spread", "Pre-tax cost of debt", "After-tax cost of debt",
                      "Equity weight E/V", "Debt weight D/V", "Project tax rate", "WACC"],
        "USD": [pct(r["rf_us"]), "1.000000", f"{r['de_ratio']:.6f}", f"{bu:.4f}", f"{r['levered_beta']:.6f}", pct(erp), pct(r["ke_us"], 4),
                pct(r["spread_us"], 4), pct(r["kd_us"], 4), pct(r["kd_at_us"], 4),
                pct(1 - w_d, 1), pct(w_d, 1), pct(tax), pct(r["wacc_us"], 4)],
        ccy if ccy != "USD" else f"USD ({country})": [
                pct(r["rf_f"]), f"{r['conversion_factor_F']:.7f}", f"{r['de_ratio']:.6f}", f"{bu:.4f}", f"{r['levered_beta']:.6f}", pct(erp), pct(r["ke_f"], 4),
                pct(r["spread_f"], 4) + (" (manual)" if ov_sf else " (auto)"), pct(r["kd_f"], 4),
                pct(r["kd_at_f"], 4), pct(1 - w_d, 1), pct(w_d, 1), pct(tax), pct(r["wacc_f"], 4)],
    })
    st.dataframe(res, hide_index=True, width="stretch")
    if ov_sf:
        st.caption(f"Auto-calculated {ccy} spread (s × F) would be {pct(r['spread_f_auto'], 4)}.")

    overrides = [n for n, f in [("beta", ov_bu), ("U.S. tax", ov_tus), (f"{country} tax", ov_tf),
                                ("USD spread", ov_s), ("U.S. yield", ov_yus),
                                (f"{country} yield", ov_yf), (f"{ccy} spread", ov_sf)] if f]
    if overrides:
        st.info("Manual overrides active: " + ", ".join(overrides))

    # ---------------- Assumptions ----------------
    with st.expander("📘 Method & main assumptions", expanded=True):
        st.markdown("**Same project, two currencies.** Beta, ERP, debt share and one project tax rate "
                    "τ are shared by both currencies; only the risk-free rate and the debt spread differ. "
                    "Full precision in all calculations; values are rounded only for display.")
        st.markdown("**1. Relever beta**")
        st.latex(r"D/E=\frac{d}{1-d}\qquad \beta_E=\beta_U\left[1+(1-\tau)\,D/E\right]")
        st.markdown("**2. USD**")
        st.latex(r"R_e=R_f+\beta_E\cdot ERP\qquad R_d=R_f+s")
        st.latex(r"WACC=(1-d)R_e+d\,R_d(1-\tau)")
        st.markdown("**3. Foreign currency**")
        st.latex(r"F=\frac{1+R_f^*}{1+R_f}\qquad R_e^*=(1+R_e)F-1\qquad s^*=s\cdot F\ \text{(unless overridden)}")
        st.latex(r"R_d^*=R_f^*+s^*\qquad WACC^*=(1-d)R_e^*+d\,R_d^*(1-\tau)")
        st.markdown(
            "**Key assumptions**\n"
            "- Risk is measured relative to the U.S. market; U.S. industry betas (Damodaran) proxy project risk.\n"
            "- 10-year government yields are used as risk-free proxies (they may include liquidity, term "
            "or default premia).\n"
            "- Equal real interest rates plus relative PPP link the yield gap to expected depreciation, "
            "which is why rates are converted with F.\n"
            "- No separate country equity risk premium.\n"
            "- Constant target leverage, fully usable interest deductions in each financing currency "
            "(same τ), and zero debt beta.\n"
            "- USD BBB spread = Damodaran Baa2/BBB, large non-financial firms; tax rates = OECD combined "
            "statutory CIT rates."
        )

    # ---------------- Verification ----------------
    with st.expander("✅ Built-in verification checks"):
        for name, ok in run_checks(bu, tax, w_d, erp, y_us, y_f, s_us):
            st.write(("✅ " if ok else "❌ ") + name)

    # ---------------- All-industry comparison ----------------
    st.subheader("All-industry comparison")
    st.caption(f"Same inputs as above (country: {country}, tax {pct(tax)}, ERP {pct(erp)}, "
               f"D/V {pct(w_d, 0)}); only the unlevered beta changes.")
    flab = f"{country} ({ccy})"  # distinct label even when the target country is the U.S.
    rows = []
    for ind, b in zip(betas["Industry"], betas["Unlevered beta"]):
        b_use = bu if (ind == industry and ov_bu) else b
        x = compute(b_use, tax, w_d, erp, y_us, y_f, s_us, s_f_input)
        rows.append({"Industry": ind, "Unlevered beta": b_use, "Levered beta": x["levered_beta"],
                     "Cost of equity USD": x["ke_us"], f"Cost of equity {flab}": x["ke_f"],
                     "WACC USD": x["wacc_us"], f"WACC {flab}": x["wacc_f"]})
    all_ind = pd.DataFrame(rows)
    if not all_ind.empty:
        pct_cols = [c for c in all_ind.columns if c.startswith(("Cost", "WACC"))]
        fmt = {c: "{:.2%}" for c in pct_cols}
        fmt.update({"Unlevered beta": "{:.3f}", "Levered beta": "{:.3f}"})
        sort_col = st.selectbox("Sort by", ["WACC USD", f"WACC {flab}", "Unlevered beta", "Industry"])
        view = all_ind.sort_values(sort_col, ascending=(sort_col == "Industry"))
        st.dataframe(
            view.style.format(fmt).apply(
                lambda row: ["background-color: rgba(255,200,0,.25)" if row["Industry"] == industry else ""
                             for _ in row], axis=1),
            hide_index=True, width="stretch", height=420)
        chart = all_ind.set_index("Industry")[["WACC USD", f"WACC {flab}"]].sort_values("WACC USD") * 100
        if country == "United States":
            chart = chart[["WACC USD"]]
        st.bar_chart(chart, height=380, y_label="WACC (%)")
    else:
        st.warning("Industry betas unavailable – all-industry comparison needs the Damodaran file.")

    # ---------------- Downloads ----------------
    st.subheader("Download results")
    inputs = pd.DataFrame({
        "Input": ["Industry", "Country", "Currency", "Unlevered beta", "Tax basis", "Project tax rate",
                  "U.S. tax rate", f"{country} tax rate", "ERP", "Debt share D/V", "U.S. 10Y yield",
                  f"{country} 10Y yield", "USD BBB spread", f"{ccy} BBB spread",
                  "Foreign spread mode", "Generated"],
        "Value": [industry, country, ccy, bu, tax_basis, tax, tax_us, tax_f, erp, w_d, y_us, y_f,
                  s_us, r["spread_f"], "manual" if ov_sf else "auto", now_utc()],
    })
    numeric = pd.DataFrame({"Metric": list(r.keys()), "Value": list(r.values())})
    sources = sources_table(m_beta, m_spread, m_tax, m_yld)

    c1, c2, c3 = st.columns(3)
    c1.download_button("Results (CSV)", pd.concat(
        [inputs.assign(Section="Input"), numeric.rename(columns={"Metric": "Input"}).assign(Section="Result")]
    ).to_csv(index=False), "cost_of_capital_results.csv", "text/csv", width="stretch")
    c2.download_button("All industries (CSV)", all_ind.to_csv(index=False),
                       "all_industry_comparison.csv", "text/csv", width="stretch")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        inputs.astype(str).to_excel(xw, sheet_name="Inputs", index=False)
        numeric.to_excel(xw, sheet_name="Results", index=False)
        all_ind.to_excel(xw, sheet_name="All industries", index=False)
        sources.to_excel(xw, sheet_name="Sources", index=False)
    c3.download_button("Everything (Excel)", buf.getvalue(), "cost_of_capital.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch")

    # ---------------- Sources ----------------
    show_sources(m_beta, m_spread, m_tax, m_yld, extra={
        "U.S. yield quote date": date_map.get("United States", "n/a"),
        f"{country} yield quote date": date_map.get(country, "n/a"),
        f"{country} tax year": int(taxes.loc[taxes["Country"] == country, "Year"].iloc[0])
        if country in tax_map else "not in OECD data – override",
    })


def sources_table(*metas):
    return pd.DataFrame([{"Data": m["source"], "Status": m["status"], "Source date": m["as_of"],
                          "Fetched": m["fetched"], "Link": m["url"]} for m in metas])


def show_sources(m_beta, m_spread, m_tax, m_yld, extra=None):
    st.subheader("Data sources & dates")
    st.dataframe(sources_table(m_beta, m_spread, m_tax, m_yld), hide_index=True,
                 width="stretch",
                 column_config={"Link": st.column_config.LinkColumn("Link")})
    if extra:
        st.caption(" · ".join(f"{k}: {v}" for k, v in extra.items()))
    st.caption("Use **🔄 Refresh data** in the sidebar to re-fetch. Any value can be overridden manually.")


if __name__ == "__main__":
    main()
