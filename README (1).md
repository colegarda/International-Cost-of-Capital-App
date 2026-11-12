# International Cost of Capital App

A Streamlit app that compares a project's **cost of equity, cost of debt and WACC in USD and in the currency of any selected country**, using live market and reference data.

## Data sources (fetched live, cached, with a 🔄 Refresh button)

| Input | Source | Notes |
|---|---|---|
| Unlevered industry beta | [Damodaran – betas.xls](https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls) | U.S. industries, "Unlevered beta" column |
| USD BBB spread | [Damodaran – ratings.html](https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html) | Baa2/BBB, large non-financial service firms |
| Corporate tax rates | [OECD Corporate Tax Statistics](https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/full-report/statutory-corporate-income-tax-rates_440f9286.html) | Combined statutory CIT rate, latest year, via OECD SDMX API; embedded 2024 snapshot as fallback |
| 10Y government yields | [Trading Economics – Bonds](https://tradingeconomics.com/bonds) | Scraped, no API key |

The app shows each source's own date, the fetch time and fetch status. Every value can be overridden manually in the sidebar.

## Inputs

- Industry, target country, equity risk premium, target debt share D/V
- Project tax rate: switch between the U.S. and the selected country's rate
- Manual overrides: unlevered beta, U.S. and foreign tax rates, USD BBB spread, U.S. and foreign 10Y yields, foreign-currency BBB spread (off = auto-calculated)

**Defaults:** Software (System & Application), United States, U.S. tax rate, ERP 6.5%, 30% debt.

## Method (class formulas)

Rates are decimals; full precision in calculations, rounded only for display.

1. Relever beta: `D/E = d/(1−d)`, `βE = βU × [1 + (1 − τ) × D/E]`
2. USD: `Re = Rf + βE × ERP`, `Rd = Rf + s`, `WACC = (1−d)·Re + d·Rd·(1−τ)`
3. Foreign currency: `F = (1 + Rf*)/(1 + Rf)`, `Re* = (1 + Re)·F − 1`, `s* = s·F` (unless overridden), `Rd* = Rf* + s*`, `WACC* = (1−d)·Re* + d·Rd*·(1−τ)`

One project tax rate τ (U.S. or foreign, via toggle) is used in both currencies.

**Test case** (βU 0.80, d 0.30, τ 0.35, ERP 6.5%, Rf 4%, Rf* 12%, s 1.5%): USD WACC 8.5265%, COP WACC 16.0670%. The app reproduces this exactly.

**Key assumptions:** risk measured relative to the U.S. market; U.S. industry betas proxy project risk; government yields as risk-free proxies (may include liquidity/term/default premia); equal real rates + relative PPP link yield gaps to expected depreciation; no country equity premium; constant target leverage, fully usable interest deductions, zero debt beta.

## Built-in verification

The app checks, using the current inputs, that:
- equal government yields give identical USD and foreign results (spread override off),
- zero debt makes WACC equal the cost of equity,
- overriding the foreign spread leaves every USD result unchanged.

## Outputs

Side-by-side results table, all-industry comparison (table + chart), and downloads (results CSV, all-industry CSV, full Excel workbook including sources).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Push `app.py`, `requirements.txt` and `README.md` to a GitHub repo, then on [share.streamlit.io](https://share.streamlit.io) create a new app pointing to `app.py`.

*Built with AI assistance; calculations verified independently.*
