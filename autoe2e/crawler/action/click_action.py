from __future__ import annotations

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.remote.webdriver import WebDriver

from autoe2e.utils import logger
from autoe2e.crawler.action.action import Action, ActionType
from autoe2e.crawler.action.element import Element
from autoe2e.crawler.action.errors import ActionExecutionError


class ClickActionType(ActionType):
    def __init__(self):
        super().__init__('click')


class ClickAction(Action):
    def __init__(self, element: Element):
        super().__init__(element, action_type=ClickActionType())


    def execute(self, driver: WebDriver) -> None:
        """Click the element.

        Raises ActionExecutionError when the element cannot be located or clicked. It does NOT
        quit the driver and does NOT exit the process: global browser teardown belongs to the
        runner's finally block, and one unclickable control must not end the crawl.

        Element.get() waits via WebDriverWait(driver, 10), so a control that has gone stale or
        never appears surfaces here as TimeoutException. WebDriverException is caught as well --
        an intercepted, detached or non-interactable element is the same class of problem from
        the crawl's point of view, and enumerating subclasses would be guesswork.
        """
        try:
            element = self.element.get(driver)
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            ActionChains(driver).move_to_element(element).click(element).perform()

        except TimeoutException as exc:
            raise self._failure('element could not be located within the wait timeout',
                                exc, driver) from exc

        except WebDriverException as exc:
            raise self._failure('element could not be clicked', exc, driver) from exc


    def _failure(self, reason: str, exc: BaseException, driver: WebDriver) -> ActionExecutionError:
        # current_url is best-effort: if the session itself is gone, asking for it raises, and
        # that must not replace the original failure.
        url = None
        try:
            url = driver.current_url
        except Exception:  # noqa: BLE001
            pass
        err = ActionExecutionError(self, reason, cause=exc, url=url)
        logger.warn(f'ClickAction failed, not fatal: {err}')
        return err
