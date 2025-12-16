"""NBA SGP Engine Signals"""

from .base import BaseSignal, SignalResult, PropContext, get_stat_value, STAT_TYPE_TO_FIELD
from .line_value_signal import LineValueSignal
from .trend_signal import TrendSignal
from .usage_signal import UsageSignal
from .matchup_signal import MatchupSignal
from .environment_signal import EnvironmentSignal
from .correlation_signal import CorrelationSignal

# All signal classes in order of weight
ALL_SIGNALS = [
    LineValueSignal,    # 30%
    TrendSignal,        # 20%
    UsageSignal,        # 20%
    MatchupSignal,      # 15%
    EnvironmentSignal,  # 10%
    CorrelationSignal,  # 5%
]

__all__ = [
    'BaseSignal',
    'SignalResult',
    'PropContext',
    'LineValueSignal',
    'TrendSignal',
    'UsageSignal',
    'MatchupSignal',
    'EnvironmentSignal',
    'CorrelationSignal',
    'ALL_SIGNALS',
    'get_stat_value',
    'STAT_TYPE_TO_FIELD',
]
