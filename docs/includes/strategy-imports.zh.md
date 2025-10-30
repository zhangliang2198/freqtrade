## 策略所需基础导入

在编写策略时，需要导入一些基础模块。以下示例包含常用必备的 Import，可作为模板使用；根据策略需要再补充其他库。

```python
# flake8: noqa: F401
# isort: skip_file
# --- 请勿删除以下导入 ---
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pandas import DataFrame
from typing import Dict, Optional, Union, Tuple

from freqtrade.strategy import (
    IStrategy,
    Trade,
    Order,
    PairLocks,
    informative,  # @informative 装饰器
    # Hyperopt 参数
    BooleanParameter,
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    RealParameter,
    # 时间框架辅助函数
    timeframe_to_minutes,
    timeframe_to_next_date,
    timeframe_to_prev_date,
    # 策略辅助函数
    merge_informative_pair,
    stoploss_from_absolute,
    stoploss_from_open,
)

# 自行添加的第三方库
import talib.abstract as ta
from technical import qtpylib
```
