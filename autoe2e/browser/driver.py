from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.remote.webdriver import WebDriver

from autoe2e.utils import AbstractSingleton, logger
from autoe2e.crawler.config import Config


def build_chrome_options(config: Config) -> ChromeOptions:
    """Build ChromeOptions from a config. Pure: launches nothing, so it is unit-testable.

    `detach` is passed through as configured. It used to be hardcoded True, which keeps Chrome
    running after the driver process exits -- a leaked browser per run, and directly at odds
    with quitting the driver on every exit path. It is now opt-in for debugging.
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--no-sandbox')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])

    if getattr(config, 'headless', False):
        # The modern headless mode; the legacy one behaves differently enough to change which
        # elements are considered visible.
        options.add_argument('--headless=new')

    window_size = getattr(config, 'window_size', None)
    if window_size:
        options.add_argument(f'--window-size={window_size}')

    options.add_experimental_option('detach', bool(getattr(config, 'detach', False)))
    return options


class DriverContainer(AbstractSingleton):
    def __init__(self, config: Config):
        options = build_chrome_options(config)
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(int(getattr(config, 'page_load_timeout', 30)))
        driver.implicitly_wait(int(getattr(config, 'implicit_wait', 5)))
        self.driver = driver
        self.config = config

        logger.info(
            f'Driver started: headless={getattr(config, "headless", False)} '
            f'detach={getattr(config, "detach", False)} '
            f'window={getattr(config, "window_size", None)} '
            f'chromedriver_pid={self.service_pid}'
        )

    @property
    def service_pid(self):
        """PID of the chromedriver process, or None. Used to verify nothing is left behind."""
        try:
            return self.driver.service.process.pid
        except Exception:  # noqa: BLE001
            return None

    def get_driver(self) -> WebDriver:
        return self.driver


def get_driver_container(config: Config) -> DriverContainer:
    driver_container = DriverContainer(config)
    return driver_container


def shutdown_driver_container() -> bool:
    """Quit the driver, if one was created, and clear the singleton.

    Idempotent and never raises: it is called from teardown paths, including after a failure,
    where a second exception would mask the original one. Clearing the singleton entry matters
    for any process that legitimately needs a second driver -- without it, DriverContainer would
    keep handing back the instance that was just quit.
    """
    from autoe2e.utils.singleton import Singleton

    instance = Singleton._instances.get(DriverContainer)
    if instance is None:
        return False

    pid = instance.service_pid
    try:
        instance.driver.quit()
        logger.info(f'Driver quit (chromedriver_pid={pid})')
        quit_ok = True
    except Exception as e:  # noqa: BLE001
        logger.error(f'Driver quit failed: {type(e).__name__}: {e}')
        quit_ok = False
    finally:
        Singleton._instances.pop(DriverContainer, None)
    return quit_ok
