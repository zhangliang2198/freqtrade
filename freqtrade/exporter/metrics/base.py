from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional


@dataclass(slots=True)
class MetricSample:
    """Prometheus 单条样本的轻量封装。"""

    name: str
    value: float | int | bool | None
    description: str | None = None
    metric_type: str = "gauge"
    labels: Dict[str, str] | None = None


def _coerce_numeric(value: float | int | bool | str | None) -> float | None:
    """将不同数值类型转换为 Prometheus 可接受的浮点值。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            return None
    else:
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    if not math.isfinite(result):
        return None
    return result


def _sanitize_label_value(value: str) -> str:
    """根据 Prometheus 规范转义标签值。"""
    escaped = (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )
    return escaped


def _format_labels(labels: Dict[str, str] | None) -> str:
    if not labels:
        return ""

    parts: List[str] = []
    for key, raw_value in labels.items():
        if raw_value is None:
            continue
        value = _sanitize_label_value(str(raw_value))
        parts.append(f'{key}="{value}"')
    if not parts:
        return ""
    return "{" + ",".join(parts) + "}"


def render_samples(samples: Iterable[MetricSample]) -> List[str]:
    """把样本列表渲染为 Prometheus 暴露格式。"""
    lines: List[str] = []
    seen_help: set[str] = set()
    seen_type: set[str] = set()

    for sample in samples:
        numeric = _coerce_numeric(sample.value)
        if numeric is None:
            continue

        if sample.description and sample.name not in seen_help:
            lines.append(f"# HELP {sample.name} {sample.description}")
            seen_help.add(sample.name)

        metric_type = sample.metric_type or "gauge"
        if metric_type and sample.name not in seen_type:
            lines.append(f"# TYPE {sample.name} {metric_type}")
            seen_type.add(sample.name)

        label_str = _format_labels(sample.labels)
        lines.append(f"{sample.name}{label_str} {numeric}")

    return lines


def to_lower_bool(value: bool | None) -> str:
    """布尔标签统一输出 true/false（None 按 false 处理）。"""
    return "true" if value else "false"


def iter_optional(samples: Iterable[Optional[MetricSample]]) -> Iterator[MetricSample]:
    """过滤掉 None，便于链式构造指标。"""
    for sample in samples:
        if sample is not None:
            yield sample
