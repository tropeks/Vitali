# This app is intentionally stateless — the demand-forecast service computes
# its answers on the fly from `apps.pharmacy.StockMovement` history. No new
# models are needed. The empty module is here so Django's app loader does
# not warn about a missing models module.
