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

## Method

1. Relever beta (Hamada): `βL = βU × [1 + (1 − t) × D/E]`
2. USD: `ke$ = y_US + βL × ERP`, `kd$ = y_US + s$`
3. Foreign currency (default, parity): `keFC = (1 + ke$)(1 + y_F)/(1 + y_US) − 1`; auto spread `sFC = (1 + kd$)(1 + y_F)/(1 + y_US) − 1 − y_F`; `kdFC = y_F + sFC`
   An additive alternative (`keFC = y_F + βL × ERP`, `sFC = s$`) can be selected under *Formula settings*.
4. `WACC = E/V × ke + D/V × kd × (1 − t)` in each currency, with the same tax rate, weights and ERP.

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
