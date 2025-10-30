# 🎯 Freqtrade Backtesting Commands Cheat Sheet

## 📥 Data Download

```powershell
# Download last 6 months data
freqtrade download-data --config user_data/config_backtest.json --timerange 20240801-20250131 --timeframes 1h 8h

# Download by specifying number of days
freqtrade download-data --config user_data/config_backtest.json --days 90 --timeframes 1h 8h

# Update existing data
freqtrade download-data --config user_data/config_backtest.json --timeframes 1h 8h --prepend
```

## 🔄 Backtesting

```powershell
# Basic backtesting
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131

# Backtesting and export trade records
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --export trades

# Breakdown backtest results by month
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --breakdown month

# Breakdown by week
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --breakdown week

# Breakdown by day
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --breakdown day
```

## 🔍 View Backtest Results

```powershell
# List all backtest results
freqtrade backtesting-show

# View latest backtest result
freqtrade backtesting-show --show-latest

# Analyze backtest results
freqtrade backtesting-analysis

# View specific backtest
freqtrade backtesting-show --backtest-filename user_data/backtest_results/backtest-result-2025-01-31.json
```

## 🎨 Generate Charts

```powershell
# Plot specific trading pairs
freqtrade plot-dataframe --config user_data/config_backtest.json --strategy Theshortgod_V_1_0_1 --pairs BTC/USDT:USDT ETH/USDT:USDT

# Plot and specify indicators
freqtrade plot-dataframe --config user_data/config_backtest.json --strategy Theshortgod_V_1_0_1 --pairs BTC/USDT:USDT --indicators1 ema50_8h,ema200_8h

# Plot profit chart
freqtrade plot-profit --config user_data/config_backtest.json --timerange 20240801-20250131
```

## 🔧 Parameter Optimization (Hyperopt)

建议一遍又一遍地运行 500-1000 个周期，直到您总共达到至少 10000 个周期

```powershell
# Optimize buy parameters (50 epochs)
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SharpeHyperOptLoss --spaces buy --epochs 50

# Optimize sell parameters (50 epochs)
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SharpeHyperOptLoss --spaces sell --epochs 50

# Optimize both buy and sell (100 epochs)
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SharpeHyperOptLoss --spaces buy sell --epochs 100

# Optimize ROI
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SharpeHyperOptLoss --spaces roi --epochs 50

# Optimize all parameters (200 epochs, time-consuming)
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SharpeHyperOptLoss --spaces all --epochs 200

# Use different loss functions
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SortinoHyperOptLoss --spaces buy sell --epochs 100
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss CalmarHyperOptLoss --spaces buy sell --epochs 100
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss MaxDrawDownHyperOptLoss --spaces buy sell --epochs 100
```

## 📊 View Optimization Results

```powershell
# View all optimization results
freqtrade hyperopt-show

# View best result
freqtrade hyperopt-show --best

# View top 10 results
freqtrade hyperopt-show --no-header --print-all | Select-Object -First 10

# View specific result by number
freqtrade hyperopt-show -n 5

# Export best parameters to strategy
freqtrade hyperopt-show --best --print-json
```

## 📋 Trading Pair Management

```powershell
# List current trading pairs
freqtrade list-pairs --config user_data/config_backtest.json

# List trading pairs and display count
freqtrade list-pairs --config user_data/config_backtest.json --print-one-column

# Test pairlist configuration
freqtrade test-pairlist --config user_data/config_backtest.json
```

## 🧪 Strategy Testing

```powershell
# List all available strategies
freqtrade list-strategies --config user_data/config_backtest.json

# Test if strategy loads correctly
freqtrade test-strategy --config user_data/config_backtest.json --strategy Theshortgod_V_1_0_1

# Show strategy information
freqtrade show-config --config user_data/config_backtest.json
```

## 🗂️ Data Management

```powershell
# List downloaded data
freqtrade list-data --config user_data/config_backtest.json

# Convert data format (json to feather)
freqtrade convert-data --config user_data/config_backtest.json --format-from json --format-to feather

# Clean old data
Remove-Item user_data/data/binance/* -Recurse -Force
```

## 🎬 Quick Scripts

```powershell
# Use quick backtesting script
.\user_data\backtest_quick.ps1

# Use optimization script
.\user_data\hyperopt.ps1

# Custom timerange
.\user_data\backtest_quick.ps1 -timerange "20241001-20250131"

# Custom optimization epochs
.\user_data\hyperopt.ps1 -epochs 200 -space "buy sell"
```

## 💡 Combined Usage Examples

```powershell
# Complete workflow: Download -> Backtest -> Optimize -> Re-backtest
# 1. Download data
freqtrade download-data --config user_data/config_backtest.json --timerange 20240801-20250131 --timeframes 1h 8h

# 2. Initial backtest
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --export trades

# 3. Optimize parameters
freqtrade hyperopt --config user_data/config_backtest.json --hyperopt-loss SharpeHyperOptLoss --spaces buy sell --epochs 100

# 4. View best parameters
freqtrade hyperopt-show --best

# 5. Re-backtest after modifying strategy
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --breakdown month

# 6. Generate chart analysis
freqtrade plot-profit --config user_data/config_backtest.json --timerange 20240801-20250131
```

## 🆘 Troubleshooting

```powershell
# View detailed logs
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 --log-file user_data/logs/backtest.log

# Enable verbose output
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 -v

# Enable debug mode
freqtrade backtesting --config user_data/config_backtest.json --timerange 20240801-20250131 -vv

# Check if configuration is correct
freqtrade show-config --config user_data/config_backtest.json
```

---

**Tip**: Bookmark this file for quick reference! 🔖
