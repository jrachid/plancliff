from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    ratio_threshold: float = 10.0
    min_gap_ms: float = 5.0
    runs: int = 3
    timeout_s: float = 30.0
    verify: bool = True
    verify_calls: int = 20

    def is_slowdown(self, slow_ms: float, fast_ms: float) -> bool:
        """is_slowdown applies the cliff rule: at least ratio_threshold times slower and min_gap_ms milliseconds lost."""
        return slow_ms >= self.ratio_threshold * fast_ms and slow_ms - fast_ms >= self.min_gap_ms
