from autoe2e.crawler.config.browser_config import BrowserConfig
from autoe2e.crawler.config.crawl_config import CrawlConfig
from autoe2e.crawler.config.driver_config import DriverConfig
from autoe2e.crawler.config.lifecycle_config import LifecycleConfig


class Config(
    BrowserConfig,
    CrawlConfig,
    DriverConfig,
    LifecycleConfig
):
    def __init__(self):
        # Each section is initialised explicitly rather than through a single super().__init__().
        # These mixins do not cooperate in the MRO -- none of them calls super().__init__() -- so
        # one chained call only ever reached the FIRST base and silently left the others'
        # attributes undefined. That is why a config omitting the `lifecycle` key used to raise
        # AttributeError on `config.on_visit` instead of defaulting to no hooks.
        BrowserConfig.__init__(self)
        CrawlConfig.__init__(self)
        DriverConfig.__init__(self)
        LifecycleConfig.__init__(self)

        self.temp_dir = None
    
    
    @staticmethod
    def from_dict(config: dict):
        config_obj: Config = Config()
        config_obj.temp_dir = config.get('temp_dir', '/tmp')
        if 'driver' in config:
            config_obj.driver_config_from_dict(config['driver'])
        if 'lifecycle' in config:
            config_obj.lifecycle_config_from_dict(config['lifecycle'])
        if 'browser' in config:
            config_obj.browser_config_from_dict(config['browser'])
        if 'crawl' in config:
            config_obj.crawl_config_from_dict(config['crawl'])
        return config_obj