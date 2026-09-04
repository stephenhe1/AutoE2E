from __future__ import annotations


class BrowserConfig:
    """Browser behaviour, from the `browser` section of a subject config.

    Defaults reproduce the previous hardcoded behaviour with ONE deliberate exception:
    `detach` now defaults to False. It was hardcoded True, which keeps Chrome alive after the
    driver process exits -- so every run leaked a browser, and it directly contradicts the
    guarantee that driver.quit() runs on completion, failure and interruption. A visible or
    detached browser is a debugging choice and is now opt-in.
    """

    def __init__(self):
        self.headless: bool = False
        self.detach: bool = False
        self.page_load_timeout: int = 30
        self.implicit_wait: int = 5
        # Headless Chrome otherwise picks a small default viewport, which changes which elements
        # are considered visible and therefore which actions are discovered. Pinning it keeps
        # headless and headed runs comparable.
        self.window_size: str = '1920,1080'

    def browser_config_from_dict(self, config: dict) -> None:
        if 'headless' in config:
            self.headless = bool(config['headless'])
        if 'detach' in config:
            self.detach = bool(config['detach'])
        if 'page_load_timeout' in config:
            self.page_load_timeout = int(config['page_load_timeout'])
        if 'implicit_wait' in config:
            self.implicit_wait = int(config['implicit_wait'])
        if 'window_size' in config:
            self.window_size = str(config['window_size'])
