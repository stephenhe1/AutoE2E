from __future__ import annotations


class CrawlConfig:
    """Crawl budget, from the `crawl` section of a subject config.

    Every limit defaults to None, which means unlimited -- the behaviour before budgets
    existed, so an old config keeps running exactly as it did. A run stops as soon as ANY
    configured limit is reached.
    """

    def __init__(self):
        self.max_actions: int | None = None
        self.max_states: int | None = None
        self.max_wall_seconds: float | None = None

    def crawl_config_from_dict(self, config: dict) -> None:
        def limit(key, cast):
            if key not in config or config[key] is None:
                return None
            value = cast(config[key])
            if value <= 0:
                raise ValueError(f'crawl.{key} must be positive, got {config[key]!r}')
            return value

        self.max_actions = limit('max_actions', int)
        self.max_states = limit('max_states', int)
        self.max_wall_seconds = limit('max_wall_seconds', float)
