# 各交易所注意事项

本页汇总了与特定交易所相关的常见问题与配置说明，其他交易所可能不适用。

## 支持能力概览

--8<-- "includes/exchange-features.md"

## 交易所配置

Freqtrade 基于 [CCXT](https://github.com/ccxt/ccxt)，后者支持 100+ 加密货币交易所。虽然列表非常长，但官方主要针对少数交易所做过详尽测试，最新支持情况可在文档首页查询。

欢迎测试其他交易所并通过反馈或 PR 帮助改进。

部分交易所需要特殊配置，详见下文。

### 示例配置

```json
"exchange": {
    "name": "binance",
    "key": "your_exchange_key",
    "secret": "your_exchange_secret",
    "ccxt_config": {},
    "ccxt_async_config": {}
    // ...
}
```

### 速率限制

CCXT 默认的速率限制通常可靠。如遇到 DDOS 相关错误，可在配置中调整：

```json
"exchange": {
    "name": "kraken",
    "key": "your_exchange_key",
    "secret": "your_exchange_secret",
    "ccxt_config": {"enableRateLimit": true},
    "ccxt_async_config": {
        "enableRateLimit": true,
        "rateLimit": 3100
    }
}
```

`rateLimit` 单位为毫秒，上述示例表示每次调用间隔 3.1 秒。不同交易所、交易对列表规模不同，最佳数值也会不一样。

## Binance

!!! Warning "服务器地区限制"
    Binance 会根据服务器所在地限制 API 访问。目前已知的限制地区包括加拿大、马来西亚、荷兰、美国等，请参考 [Binance 条款](https://www.binance.com/en/terms)。

Binance 支持 [time_in_force](configuration.md#understand-order_time_in_force)。

!!! Tip "交易所止损"
    Binance 支持 `stoploss_on_exchange`（使用 `stop-loss-limit` 订单）。在合约模式下，还可选择 `stop-limit` 或 `stop-market`。通过 `order_types.stoploss` 的 `"limit"` / `"market"` 配置即可切换。

**黑名单建议**：除非你会额外保留充足 BNB 或关闭 BNB 手续费抵扣，否则建议把 `"BNB/<STAKE>"` 加入黑名单，以免 BNB 手动持仓被手续费抵扣导致无法卖出。

**站点区分**：

* `binance`：国际站
* `binanceus`：美国站

**RSA 密钥**：Freqtrade 支持 Binance RSA API Key，推荐通过环境变量设置。若写入配置文件，需要将换行转换为 `\n`。

### Binance Futures

必须遵守 Binance 的[量化规则](https://www.binance.com/en/support/faq/4f462ebe6ff445d4a170be7d9e897272)，否则可能遭到限速或停权。常见注意事项：

* **持仓限制**：`availBal` 与 `maxPosition` 需保持在允许范围内。  
* **订单限制**：短时间内过多取消或小额订单都会触发延迟。  
* **仓位与保证金**：杠杆模式切换、强平规则都要特别留意。

请定期查看官方公告了解最新限制。

## Kraken

* 官方接口波动较大，请务必启用速率限制。  
* Kraken 返回金额包含报价货币和基础货币，处理时需留意。  
* Kraken 的历史 OHLCV 数据覆盖有限，建议通过 `--dl-trades` 下载成交数据后本地重采样。

## Kucoin

* 需要在 API 权限中启用交易功能。  
* USDT 等稳定币可能存在链上充值延迟。  
* 如遇 `Too many open requests`，请降低请求频率。

## OKX

* API Key 创建后需要绑定 IP 白名单。  
* 合约杠杆、资金费率等需按官方要求设置。

## Hyperliquid

Hyperliquid API 与传统交易所有所不同：

* 所有交易以永续合约形式进行，没有现货市场。  
* 不支持市价单，CCXT 会通过挂限价单并设定 5% 滑点模拟市价成交。  
* 仅提供最近 5000 根 K 线，回测需要长期累计或使用实时数据。

### Vault / 子账户

若使用 Vault 或子账户，可按下方配置：

```json
"exchange": {
    "name": "hyperliquid",
    "walletAddress": "your_vault_address",
    "privateKey": "your_api_private_key",
    "ccxt_config": {
        "options": {
            "vaultAddress": "your_vault_address"
        }
    }
}
```

### 安全建议

* 使用专用 API 钱包，不要把主钱包私钥放在服务器上。  
* 不要重复使用硬件钱包的助记词。  
* 定期将未交易的盈利用于提回硬件钱包。

## Bitvavo

如果账户需要 `operatorId`，可以在配置中设置：

``` json
"exchange": {
    "name": "bitvavo",
    "key": "",
    "secret": "",
    "ccxt_config": {
        "options": {
            "operatorId": "123567"
        }
    }
}
```

Bitvavo 要求 `operatorId` 为整数。

## 通用提示

* 若频繁出现 `InvalidNonce` 等异常，请重新生成 API Key。  
* 部分交易所（如 The Ocean）需要额外依赖，例如 `web3`：`pip3 install web3`。  
* 很多交易所的 OHLCV 接口会返回未收盘的蜡烛，Freqtrade 默认丢弃最后一根。若需要最新价格，可通过策略中的 [DataProvider](strategy-customization.md#possible-options-for-dataprovider) 获取。

### 高级配置

可以通过 `_ft_has_params` 覆盖默认行为，例如：

```json
"exchange": {
    "name": "kraken",
    "_ft_has_params": {
        "order_time_in_force": ["GTC", "FOK"],
        "ohlcv_candle_limit": 200
    }
}
```

!!! Warning
    修改 `_ft_has_params` 可能影响核心行为甚至导致机器人异常，请务必了解其含义并自行承担风险。
