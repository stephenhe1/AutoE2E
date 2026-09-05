from __future__ import annotations


class LLMConfig:
    """LLM request safety, from the `llm` section of a subject config.

    Why this exists: ChatOpenAI was constructed with no explicit request timeout, so a stalled
    request blocked forever. Confirmed on KEYSTONE_BLOG -- call #17 was sent, never returned, and
    the process sat at 0% CPU for ~41 minutes until it was killed. `max_wall_seconds` could not
    help: the crawl budget is only evaluated at action boundaries, so a hang *inside* one action
    is unbounded by construction.

    Defaults are conservative runtime-safety values, identical for every subject. They bound the
    worst case at request_timeout_seconds x (1 + max_retries) per call.
    """

    def __init__(self):
        self.request_timeout_seconds: float = 120.0
        self.max_retries: int = 1

    def llm_config_from_dict(self, config: dict) -> None:
        if 'request_timeout_seconds' in config:
            value = float(config['request_timeout_seconds'])
            if value <= 0:
                raise ValueError(
                    f'llm.request_timeout_seconds must be positive, got {config["request_timeout_seconds"]!r}')
            self.request_timeout_seconds = value
        if 'max_retries' in config:
            value = int(config['max_retries'])
            if value < 0:
                raise ValueError(
                    f'llm.max_retries must be >= 0, got {config["max_retries"]!r}')
            self.max_retries = value
