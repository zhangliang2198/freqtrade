# LeaderSqueezeStrategy

Live-only Binance USD-M futures strategy for ranking the hourly top-10 gainers and
following crowded-short squeezes. It opens long positions only, uses isolated 5x
leverage, allocates 10% of currently available stake per entry, and caps managed
positions at five.

## Data and safety gates

- Rankings refresh every five minutes. Failed refreshes retry after 30 seconds.
- Binance global/top-trader ratios, taker volume, open interest, and liquidation
  events feed the configured weighted score.
- Short crowding below the configured 30% minimum is rejected. The last three
  5-minute rises contribute a 15-minute trend-continuity factor to the ranking;
  volume expansion remains a confidence component rather than a hard gate.
- With fewer than two managed positions, the best eligible candidates are selected
  without the additional-entry score floor. Further entries require the configured
  score. A confirmed rotation preserves its target and refreshes the top-10 after
  the weak position closes.
- Entries stop when rankings, position state, or the liquidation-stream heartbeat
  become stale.
- Market entries require spread at or below 0.10% and estimated slippage at or
  below 0.25%.
- Database trades use mark-price exchange stop-loss orders. Exchange-only positions
  are counted, evaluated by the same exits, and have their algo stop orders checked
  every 60 seconds.
- A 5% UTC-day loss pauses new entries. A 10% peak-equity drawdown closes positions
  and persists the account stop in `user_data/leader_squeeze_state.json`; restoring
  trading after inspection requires explicitly clearing that stopped state.

Binance's all-market liquidation stream publishes at most one liquidation snapshot
per symbol per second. The liquidation component is therefore a pressure proxy, not
an exact total of every liquidation in the interval.

## Configuration

`user_data/config.json` is the only file that must be passed to `-c`; its
`add_config_files` setting loads the other files automatically:

- `config-pairlists.json`: pair whitelist and the top-gainer selector chain.
- `config-blacklist.json`: excluded pair patterns.
- `config-private.json`: database URL, exchange credentials, Telegram settings,
  and API-server credentials. Keep this file mode `0600` and never commit it.

```bash
uv run freqtrade trade -c user_data/config.json
```

## Database

Without `db_url`, live mode uses `tradesv3.sqlite`. This setup keeps the PostgreSQL
URL in `config-private.json`; an environment variable can override it when needed:

```bash
export FREQTRADE__DB_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DATABASE'
```

Do not commit exchange, database, Telegram, proxy, or API-server credentials.
