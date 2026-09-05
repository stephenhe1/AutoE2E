import os
import sys
import time
import json
import signal
import datetime

from autoe2e.utils import *
from autoe2e.init_utils import *
from autoe2e.infer_utils import *
from autoe2e.loop_utils import *
from autoe2e.mongo_utils import *
from autoe2e.manual_ndd import *
from autoe2e.llm_api_call import _resolve_api_key, configure_llm
from autoe2e.browser import shutdown_driver_container
from autoe2e.crawler.action import ActionExecutionError
from autoe2e.crawler.budget import (
    BUDGET_REASONS,
    CrawlBudget,
    INTERRUPTED_REASON,
    classify_outcome,
)


APP_NAME = os.getenv('APP_NAME', 'PETCLINIC')

STATUS_FILE = f'./tmp/status_{APP_NAME}.json'
START_TIME = time.time()
LOOP_COUNTER = 0
STOP_REQUESTED = False
STOP_REASON = None      # a budget name, or 'interrupted'
ACTION_FAILURES = []    # action-level execution failures that were skipped, not fatal
EXIT_STATUS = 'failed'  # pessimistic until the run actually reaches an end state
ERROR_MSG = None


def handle_stop_signal(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logger.info('Stop signal received, finishing current action and writing results...')


signal.signal(signal.SIGINT, handle_stop_signal)
signal.signal(signal.SIGTERM, handle_stop_signal)


def save_state_graph(crawl_context, app_name):
    states_converted = {}

    for state_id, state_obj in crawl_context.state_machine.state_graph.states.items():
        states_converted[state_id] = {
            'url': state_obj.url,
            'context': state_obj.context,
            'actions': [{
                    'type': a.action_type.get_value(),
                    'id': a.element.get_id(),
                    'outerHTML': clean_children_html(a.element.outerHTML),
                    'testId': a.element.test_id
                } for a in state_obj.get_actions()
            ],
            'prev_state': state_obj.crawl_path.get_state(-1).get_id() if len(state_obj.crawl_path) > 0 else None,
            'prev_action': state_obj.crawl_path.get_action(-1).get_id() if len(state_obj.crawl_path) > 0 else None,
        }

    adj_list_converted = {}

    for state_id, neighbor_list in crawl_context.state_machine.state_graph.adjacency_list.items():
        adj_list_converted[state_id] = {}

        for action_obj, n_state_id in neighbor_list.items():
            adj_list_converted[state_id][action_obj.get_id()] = n_state_id

    json.dump(
        {
            'nodes': states_converted,
            'edges': adj_list_converted
        },
        open(f'./report/{app_name}.json', 'w+')
    )


BUDGET = None


def write_status(
    loop_counter,
    queue_size,
    states_discovered,
    current_state_id=None,
    current_action=None,
    error=None,
    status='running',
    budget_triggered=None,
):
    """Write run status.

    `status` is one of: running, completed, budget_exhausted, interrupted, failed. It used to be
    only 'running' or 'error' -- a finished crawl was left saying "running" with current_state
    set to 'DONE', which is why the July status files cannot be told apart from a crawl that
    died mid-flight.

    `loop_counter` is kept for compatibility with tooling that reads the older files;
    `actions_executed` is the same number under the name that says what it is.
    """
    payload = {
        'app': APP_NAME,
        'started_at': datetime.datetime.fromtimestamp(START_TIME).isoformat(),
        'elapsed_seconds': round(time.time() - START_TIME, 1),
        'loop_counter': loop_counter,
        'actions_executed': loop_counter,
        'queue_size': queue_size,
        'states_discovered': states_discovered,
        'current_state': current_state_id,
        'current_action': current_action,
        'last_updated': datetime.datetime.now().isoformat(),
        'status': 'failed' if error else status,
        'budget': BUDGET.describe() if BUDGET is not None else None,
        'budget_triggered': budget_triggered,
        'action_execution_failures': len(ACTION_FAILURES),
        'action_execution_failure_details': ACTION_FAILURES[-20:],
        'error': error,
    }
    with open(STATUS_FILE, 'w') as f:
        json.dump(payload, f, indent=2)


try:
    crawl_context: CrawlContext = CrawlContext()
    crawl_context = crawl_context.set_temp_var('config_path', f'./configs/{APP_NAME}.json')

    config: dict = read_config(config_path=crawl_context.temp_vars.get('config_path', None))
    config_obj: Config = Config.from_dict(config)

    if config_obj.base_url is None:
        raise ValueError('base_url is required in config')

    crawl_context = crawl_context.set_config(config_obj)

    # Bound every LLM request before the first call. Models are built lazily, so this must run
    # before any invocation. Without it a stalled request blocks forever and the crawl budget
    # cannot intervene, because it is only checked at action boundaries.
    configure_llm(config_obj)

    # Resolve the LLM credential up front. The crawl needs it for its very first state, and
    # everything below this line is either slow or destructive, so failing here is cheapest.
    logger.info('Resolving LLM credential')
    _resolve_api_key()

    driver = initialize_driver(config_obj)
    crawl_context = crawl_context.set_driver(driver)

    # Runs lifecycle on_visit hooks (login, client-state seeding) before the first state is
    # captured, so a failed login aborts here rather than producing a logged-out crawl.
    crawl_context = initialize_variables(crawl_context)

    # ONLY NOW discard the previous run's predictions for this app. These deletes used to be
    # the first statements in the file, which meant a typo in APP_NAME, a dead service, a
    # missing credential or a failed login destroyed the previous run's rows and then failed --
    # and those rows are the only copy of that run's output, since nothing writes them to disk.
    logger.info(f'Clearing previous stored results for {APP_NAME}')
    action_func_db.delete_many({ 'app': APP_NAME })
    func_db.delete_many({ 'app': APP_NAME })

    BUDGET = CrawlBudget.from_config(config_obj)
    if BUDGET.is_limited:
        logger.info(f'Crawl budget: {BUDGET.describe()}')
    else:
        logger.info('Crawl budget: unlimited (no crawl.* limits configured)')

    write_status(0, len(crawl_context.crawl_queue), len(crawl_context.state_machine.state_graph.states))
    logger.info(f'=== Crawl started. Queue size: {len(crawl_context.crawl_queue)} ===')

    while len(crawl_context.crawl_queue) > 0 and not STOP_REQUESTED and STOP_REASON is None:
        state: State = crawl_context.crawl_queue.dequeue()
        logger.info(f"Visiting state {state.get_id(StateIdEvaluator.BY_ACTIONS)}")
        crawl_context.state_machine.set_current_state(state)

        current_state: State = crawl_context.state_machine.get_current_state()
        current_actions: list[Action] = current_state.get_actions()

        crawl_context.load_state(current_state)

        logger.info('Extracting state context using LLM')

        state_context = extract_state_context(
            crawl_context,
            current_state,
            current_state.crawl_path.get_state(-1) if len(current_state.crawl_path) > 0 else None,
            current_state.crawl_path.get_action(-1) if len(current_state.crawl_path) > 0 else None,
        )
        current_state.set_context(state_context)

        for action in current_actions:
            if STOP_REQUESTED:
                STOP_REASON = INTERRUPTED_REASON
                break

            # Budget is checked BEFORE executing, so a declared limit is never overshot. This
            # only decides whether to schedule more work; the exploration algorithm itself is
            # untouched, and everything produced so far is preserved by the teardown below.
            triggered = BUDGET.exceeded(
                LOOP_COUNTER, len(crawl_context.state_machine.state_graph.states))
            if triggered is not None:
                STOP_REASON = triggered
                logger.info(
                    f'Crawl budget reached ({triggered}); stopping cleanly after '
                    f'{LOOP_COUNTER} action(s), '
                    f'{len(crawl_context.state_machine.state_graph.states)} state(s), '
                    f'{round(BUDGET.elapsed(), 1)}s'
                )
                break

            LOOP_COUNTER += 1

            write_status(
                LOOP_COUNTER,
                len(crawl_context.crawl_queue),
                len(crawl_context.state_machine.state_graph.states),
                current_state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                current_action=action.element.outerHTML[:100] if action.element.outerHTML else None,
            )

            logger.info(f'Executing action {action.element.outerHTML}')

            should_extract_func = True

            is_critical = is_action_critical(action)

            if not is_critical:
                if action.get_type().get_value() == 'form':
                    values = create_form_filling_values(action)
                    action.set_params(values)

                # An action that cannot be executed is an action-level failure, not a crawl
                # failure. ClickAction used to call driver.quit(); sys.exit(1) here, which ended
                # the whole run over one stale control. The transition handling below is skipped
                # so a failed click is never recorded as a successful transition, and the
                # load_state() replay at the end of this iteration returns the browser to a known
                # state before the next action.
                execution_error = None
                try:
                    action.execute(crawl_context.driver)
                except ActionExecutionError as action_err:
                    execution_error = action_err
                    ACTION_FAILURES.append(action_err.as_dict())
                    logger.warn(
                        f'Skipping action after execution failure '
                        f'({len(ACTION_FAILURES)} so far): {action_err}')

                if execution_error is None:
                    new_actions = []

                    for i in range(10):
                        try:
                            new_actions: list[Action] = CandidateActionExtractor.extract_candidate_actions(crawl_context.driver)
                            break
                        except:
                            time.sleep(0.1)

                    if len(new_actions) == 0:
                        raise Exception("no new actions")

                    new_state: State = crawl_context.create_state_from_driver(new_actions)

                    if not is_state_in_graph(crawl_context, new_state):
                        print('Adding state', new_state.get_id(StateIdEvaluator.BY_ACTIONS))
                        crawl_context.crawl_queue.enqueue(new_state)
                        crawl_context.state_machine.add_state_from_current_state(new_state, action)
                    else:
                        should_extract_func = False
                else:
                    # no execution, so no transition and no functionality attribution
                    should_extract_func = False

            if should_extract_func:
                try:
                    logger.info(f'Extracting action scenarios: {action.element.outerHTML}')

                    functionalities = extract_action_functionalities(current_state, action)
                    if len(functionalities) != 0:
                        functionality_ids = insert_functionalities(functionalities)
                        insert_action_functionality(
                            func_ids=functionality_ids,
                            state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                            state_url=state.url,
                            prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                            action_id=action.get_id(),
                            prev_action_id=state.crawl_path.get_action(-1).get_id() if len(state.crawl_path) > 0 else None,
                            action_test_id=action.element.test_id,
                            action_depth=len(state.crawl_path),
                            action_type="SINGLE"
                        )

                    if len(current_state.crawl_path) > 0:
                        logger.info('Extracting double action scenarios')
                        functionalities = extract_action_functionalities(current_state, action, current_state.crawl_path.get_action(-1))
                        if len(functionalities) != 0:
                            functionality_ids = insert_functionalities(functionalities)
                            insert_action_functionality(
                                func_ids=functionality_ids,
                                state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                                state_url=state.url,
                                prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                                action_id=action.get_id(),
                                prev_action_id=state.crawl_path.get_action(-1).get_id() if len(state.crawl_path) > 0 else None,
                                action_test_id=action.element.test_id,
                                action_depth=len(state.crawl_path),
                                action_type="DOUBLE"
                            )

                        logger.info('Updating action scores')

                        update_functionality_score(
                            current_state.crawl_path.get_state(-1),
                            current_state.crawl_path.get_action(-1),
                            current_state,
                            action
                        )

                        logger.info('Action scores updated')

                    logger.info('Marking final functionalities')

                    mark_final_functionalities(current_state, action)

                    logger.info('Final actions marked')
                except Exception as func_err:
                    logger.error(f'Functionality extraction failed, continuing crawl: {type(func_err).__name__}: {func_err}')

            crawl_context.load_state(crawl_context.state_machine.get_current_state())

            logger.info("")

        save_state_graph(crawl_context, APP_NAME)

    EXIT_STATUS, _ = classify_outcome(STOP_REASON, STOP_REQUESTED)

# BaseException, not Exception: a KeyboardInterrupt must still reach the teardown below. It
# would otherwise skip it entirely and leak the browser -- the exact failure this is here to
# prevent.
except BaseException as e:
    import traceback
    EXIT_STATUS = 'failed'
    ERROR_MSG = f'{type(e).__name__}: {e}'
    logger.error(f'Crawl failed: {ERROR_MSG}')
    logger.error(traceback.format_exc())

finally:
    # Runs on every path: normal completion, budget exhaustion, exception and interruption.
    # Order matters -- persist results first, then close the browser, so a failure to quit
    # cannot cost us the run's output.
    states_discovered = 0
    try:
        if 'crawl_context' in dir() and getattr(crawl_context, 'state_machine', None) is not None:
            states_discovered = len(crawl_context.state_machine.state_graph.states)
            save_state_graph(crawl_context, APP_NAME)
            logger.info(f'Saved state graph to ./report/{APP_NAME}.json')
    except Exception as save_err:  # noqa: BLE001
        logger.error(f'Could not save state graph: {type(save_err).__name__}: {save_err}')

    quit_ok = shutdown_driver_container()
    logger.info(f'Browser teardown: {"driver quit" if quit_ok else "no driver to quit"}')

    try:
        write_status(
            LOOP_COUNTER,
            len(crawl_context.crawl_queue) if 'crawl_context' in dir() else 0,
            states_discovered,
            current_state_id='DONE' if EXIT_STATUS in ('completed', 'budget_exhausted') else None,
            status=EXIT_STATUS,
            budget_triggered=STOP_REASON if STOP_REASON in BUDGET_REASONS else None,
            error=ERROR_MSG,
        )
    except Exception as status_err:  # noqa: BLE001
        logger.error(f'Could not write status: {type(status_err).__name__}: {status_err}')

    logger.info(
        f'=== Crawl {EXIT_STATUS}. {LOOP_COUNTER} action(s) executed, '
        f'{states_discovered} state(s) discovered, '
        f'{round(time.time() - START_TIME, 1)}s elapsed'
        + (f', budget_triggered={STOP_REASON}' if STOP_REASON in BUDGET_REASONS else '')
        + (f', {len(ACTION_FAILURES)} action execution failure(s) skipped' if ACTION_FAILURES else '')
        + ' ==='
    )

# completed and budget_exhausted are both successful outcomes: the budget is a declared stopping
# rule, not an error. An interruption exits 130 by convention; a real failure exits 1.
_, EXIT_CODE = classify_outcome(STOP_REASON, STOP_REQUESTED, ERROR_MSG)
sys.exit(EXIT_CODE)
