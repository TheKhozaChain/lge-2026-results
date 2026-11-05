# LGE 2026 Results Explorer

An unofficial, plain-language view of South Africa's 2026 municipal election count, built on results published by the Electoral Commission (IEC) at https://results.elections.org.za/dashboards/lge/.

- `refresh.py` downloads the latest IEC results and builds the page from `template.html`.
- `.github/workflows/refresh.yml` runs it every 10 minutes and publishes the page to GitHub Pages.
- The page checks for a newer version every 2 minutes and reloads itself, so visitors never need to refresh.

To stop the updates after the count ends, disable the "Refresh results" workflow under the Actions tab.
