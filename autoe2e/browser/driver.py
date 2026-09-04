from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver

from autoe2e.utils import AbstractSingleton
from autoe2e.crawler.config import Config


class DriverContainer(AbstractSingleton):
    def __init__(self, config: Config):
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("detach", True)
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(5)
        self.driver = driver


    def get_driver(self) -> WebDriver:
        return self.driver


def get_driver_container(config: Config) -> DriverContainer:
    driver_container = DriverContainer(config)
    return driver_container
