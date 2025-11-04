"""
Prompt Template Manager

Manages Jinja2 templates for different decision points.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Prompt template manager using Jinja2

    Loads and renders prompt templates for different decision points.
    Templates are stored in user_data/llm_prompts/ directory.
    """

    def __init__(self, config: Dict[str, Any], user_data_dir: Optional[str] = None):
        """
        Initialize the prompt manager

        Args:
            config: LLM configuration dictionary
            user_data_dir: Optional path to user_data directory
        """
        self.config = config

        # Determine template directory
        if user_data_dir:
            template_dir = Path(user_data_dir) / "llm_prompts"
        else:
            template_dir = Path("user_data/llm_prompts")

        template_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir = template_dir

        # Initialize Jinja2 environment
        try:
            from jinja2 import Environment, FileSystemLoader, TemplateNotFound
            self.env = Environment(loader=FileSystemLoader(str(template_dir)))
            self.TemplateNotFound = TemplateNotFound
        except ImportError:
            raise ImportError(
                "Jinja2 package is required for PromptManager. "
                "Install with: pip install jinja2>=3.0.0"
            )

        logger.info(f"Prompt manager initialized with template directory: {template_dir}")

    def build_prompt(self, decision_point: str, context: Dict[str, Any]) -> str:
        """
        Build a prompt from a template

        Args:
            decision_point: Decision point name (e.g., "entry", "exit")
            context: Context data to render the template

        Returns:
            Rendered prompt string

        Raises:
            ValueError: If template not found and no default available
        """
        # Get template name from config
        point_config = self.config.get("decision_points", {}).get(decision_point, {})
        template_name = point_config.get("prompt_template", f"{decision_point}.j2")

        try:
            template = self.env.get_template(template_name)
            prompt = template.render(**context)
            return prompt

        except self.TemplateNotFound:
            logger.warning(
                f"Template '{template_name}' not found in {self.template_dir}. "
                f"Using default prompt for {decision_point}"
            )
            return self._get_default_prompt(decision_point, context)

        except Exception as e:
            logger.error(f"Failed to render template {template_name}: {e}")
            return self._get_default_prompt(decision_point, context)

    def _get_default_prompt(self, decision_point: str, context: Dict[str, Any]) -> str:
        """
        Get a default prompt when template is not available

        Args:
            decision_point: Decision point name
            context: Context data

        Returns:
            Default prompt string
        """
        # Format context for display
        import json
        context_str = json.dumps(context, indent=2, default=str)

        base_prompt = f"""You are a professional cryptocurrency trading analyst.

Decision Point: {decision_point}

Market Data and Context:
{context_str}

"""

        # Add decision-specific instructions
        if decision_point == "entry":
            base_prompt += """Based on the above data, decide whether to enter a position.

Respond in JSON format:
{
    "decision": "buy" | "sell" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation (max 100 words)",
    "parameters": {}
}

Only enter positions with high confidence (>0.7).
"""

        elif decision_point == "exit":
            base_prompt += """Based on the current trade state, decide whether to exit the position.

Respond in JSON format:
{
    "decision": "exit" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation (max 100 words)",
    "parameters": {}
}

Consider profit targets, stop losses, and momentum indicators.
"""

        elif decision_point == "stake":
            base_prompt += """Determine the appropriate position size multiplier.

Respond in JSON format:
{
    "decision": "adjust" | "default",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation (max 50 words)",
    "parameters": {
        "stake_multiplier": 0.5-2.0
    }
}

- 0.5 = half size (high risk/low confidence)
- 1.0 = default size
- 2.0 = double size (low risk/high confidence)
"""

        elif decision_point == "adjust_position":
            base_prompt += """Decide whether to adjust the current position (add or reduce).

Respond in JSON format:
{
    "decision": "add" | "reduce" | "no_change",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation (max 50 words)",
    "parameters": {
        "adjustment_ratio": -0.5 to 0.5
    }
}

Positive ratio = add to position, negative ratio = reduce position.
"""

        elif decision_point == "leverage":
            base_prompt += """Determine the appropriate leverage for this trade.

Respond in JSON format:
{
    "decision": "adjust" | "default",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation (max 50 words)",
    "parameters": {
        "leverage": 1.0-10.0
    }
}

Lower leverage in volatile markets, higher leverage in stable trends.
"""

        else:
            base_prompt += """Respond in JSON format:
{
    "decision": "your decision",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "parameters": {}
}
"""

        return base_prompt

    def create_default_templates(self):
        """
        Create default prompt templates in the template directory

        This can be called to bootstrap a new installation with
        example templates.
        """
        templates = {
            "entry.j2": self._default_entry_template(),
            "exit.j2": self._default_exit_template(),
            "stake.j2": self._default_stake_template(),
            "adjust.j2": self._default_adjust_template(),
            "leverage.j2": self._default_leverage_template(),
        }

        for name, content in templates.items():
            template_path = self.template_dir / name
            if not template_path.exists():
                template_path.write_text(content, encoding="utf-8")
                logger.info(f"Created default template: {template_path}")

    @staticmethod
    def _default_entry_template() -> str:
        """Default entry decision template"""
        return """You are a professional cryptocurrency trading analyst. Analyze the market data and decide whether to enter a position.

## Market Information
- **Pair**: {{ pair }}
- **Current Time**: {{ current_time }}
- **Current Price**: ${{ "%.4f"|format(current_candle.close) }}
- **24h Change**: {{ "%.2f"|format((current_candle.close / current_candle.open - 1) * 100) }}%

## Technical Indicators
{% if indicators %}
{% for key, value in indicators.items() %}
- **{{ key }}**: {{ "%.4f"|format(value) if value is number else value }}
{% endfor %}
{% endif %}

## Market Summary
{{ market_summary }}

## Recent Price Action
{% if recent_candles %}
Last 5 candles (most recent first):
{% for candle in recent_candles[-5:] %}
{{ loop.index }}. Close: ${{ "%.4f"|format(candle.close) }}, Volume: {{ "%.0f"|format(candle.volume) }}
{% endfor %}
{% endif %}

## Your Task
Decide whether to:
1. **BUY** - Enter a long position
2. **SELL** - Enter a short position (if shorting is enabled)
3. **HOLD** - Do not enter

**Response Format** (JSON only, no other text):
```json
{
    "decision": "buy" | "sell" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 100 words)",
    "parameters": {}
}
```

**Guidelines**:
- Confidence above 0.7 is recommended for entry
- Consider trend, momentum, support/resistance
- Be conservative - only enter high-probability setups
- Consider volume and volatility
"""

    @staticmethod
    def _default_exit_template() -> str:
        """Default exit decision template"""
        return """You are a professional cryptocurrency trading analyst. Analyze the current position and decide whether to exit.

## Trade Information
- **Pair**: {{ pair }}
- **Entry Price**: ${{ "%.4f"|format(entry_price) }}
- **Current Price**: ${{ "%.4f"|format(current_price) }}
- **Current Profit**: {{ "%.2f"|format(current_profit_pct) }}%
- **Current Profit (Absolute)**: ${{ "%.4f"|format(current_profit_abs) }}
- **Holding Duration**: {{ "%.1f"|format(holding_duration_minutes) }} minutes
- **Stop Loss**: ${{ "%.4f"|format(stop_loss) }}
{% if max_rate %}
- **Max Rate Reached**: ${{ "%.4f"|format(max_rate) }}
{% endif %}
- **Entry Tag**: {{ entry_tag or "N/A" }}

## Current Market Indicators
{% if current_indicators %}
{% for key, value in current_indicators.items() %}
- **{{ key }}**: {{ "%.4f"|format(value) if value is number else value }}
{% endfor %}
{% endif %}

## Your Task
Decide whether to:
1. **EXIT** - Close the position now
2. **HOLD** - Keep the position open

**Response Format** (JSON only, no other text):
```json
{
    "decision": "exit" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 100 words)",
    "parameters": {}
}
```

**Exit Guidelines**:
- Take profit when momentum weakens or target reached
- Cut losses early if trend reverses against you
- Consider trailing profit protection
- Don't let winners turn into losers
"""

    @staticmethod
    def _default_stake_template() -> str:
        """Default stake amount decision template"""
        return """You are a professional cryptocurrency portfolio manager. Determine the appropriate position size.

## Market Information
- **Pair**: {{ pair }}
- **Current Price**: ${{ "%.4f"|format(current_price) }}
- **Available Balance**: ${{ "%.2f"|format(available_balance) }}

## Market Conditions
{{ market_summary }}

- **Volatility**: {{ "%.2f"|format(volatility) }}%

## Your Task
Determine the position size multiplier (0.5 - 2.0):
- **0.5**: Half the default size (high risk/low confidence)
- **1.0**: Default size (standard conditions)
- **2.0**: Double size (high confidence/low risk)

**Response Format** (JSON only, no other text):
```json
{
    "decision": "adjust" | "default",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 50 words)",
    "parameters": {
        "stake_multiplier": 0.5-2.0
    }
}
```

**Guidelines**:
- Higher volatility → smaller position
- Strong trend + low volatility → larger position
- Diversify risk across multiple positions
"""

    @staticmethod
    def _default_adjust_template() -> str:
        """Default position adjustment template"""
        return """You are a professional cryptocurrency trader. Decide whether to adjust the current position.

## Position Information
- **Pair**: {{ pair }}
- **Current Profit**: {{ "%.2f"|format(current_profit_pct) }}%
- **Current Rate**: ${{ "%.4f"|format(current_rate) }}
- **Entry Rate**: ${{ "%.4f"|format(entry_rate) }}
- **Stake Amount**: ${{ "%.2f"|format(stake_amount) }}
- **Holding Duration**: {{ "%.1f"|format(holding_duration_minutes) }} minutes

## Market Summary
{{ market_summary }}

## Your Task
Decide whether to:
1. **ADD** - Add to the position (DCA or pyramid)
2. **REDUCE** - Reduce the position (take partial profit)
3. **NO_CHANGE** - Keep position as is

**Response Format** (JSON only, no other text):
```json
{
    "decision": "add" | "reduce" | "no_change",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 50 words)",
    "parameters": {
        "adjustment_ratio": -0.5 to 0.5
    }
}
```

**Guidelines**:
- Positive ratio = add to winning position (pyramid)
- Negative ratio = take partial profit
- Consider market momentum and risk management
"""

    @staticmethod
    def _default_leverage_template() -> str:
        """Default leverage decision template"""
        return """You are a professional cryptocurrency risk manager. Determine the appropriate leverage.

## Market Information
- **Pair**: {{ pair }}
- **Current Rate**: ${{ "%.4f"|format(current_rate) }}
- **Proposed Leverage**: {{ "%.1f"|format(proposed_leverage) }}x
- **Max Leverage**: {{ "%.1f"|format(max_leverage) }}x
- **Volatility**: {{ "%.2f"|format(volatility) }}%

## Market Summary
{{ market_summary }}

## Your Task
Determine the appropriate leverage (1.0 - max_leverage):

**Response Format** (JSON only, no other text):
```json
{
    "decision": "adjust" | "default",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 50 words)",
    "parameters": {
        "leverage": 1.0-10.0
    }
}
```

**Guidelines**:
- Lower leverage in volatile markets (1-3x)
- Higher leverage in stable, strong trends (up to max)
- Consider liquidation risk carefully
- When in doubt, use lower leverage
"""
