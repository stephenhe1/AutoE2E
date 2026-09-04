import os
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
from autoe2e.llm_api_call import _resolve_api_key


APP_NAME = os.getenv('APP_NAME', 'PETCLINIC')

STATUS_FILE = f'./tmp/status_{APP_NAME}.json'
START_TIME = time.time()
LOOP_COUNTER = 0
STOP_REQUESTED = False


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


def write_status(loop_counter, queue_size, states_discovered, current_state_id=None, current_action=None, error=None):
    status = {
        'app': APP_NAME,
        'started_at': datetime.datetime.fromtimestamp(START_TIME).isoformat(),
        'elapsed_seconds': round(time.time() - START_TIME, 1),
        'loop_counter': loop_counter,
        'queue_size': queue_size,
        'states_discovered': states_discovered,
        'current_state': current_state_id,
        'current_action': current_action,
        'last_updated': datetime.datetime.now().isoformat(),
        'status': 'error' if error else 'running',
        'error': error,
    }
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)


try:
    crawl_context: CrawlContext = CrawlContext()
    crawl_context = crawl_context.set_temp_var('config_path', f'./configs/{APP_NAME}.json')

    config: dict = read_config(config_path=crawl_context.temp_vars.get('config_path', None))
    config_obj: Config = Config.from_dict(config)

    if config_obj.base_url is None:
        raise ValueError('base_url is required in config')

    crawl_context = crawl_context.set_config(config_obj)

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

    write_status(0, len(crawl_context.crawl_queue), len(crawl_context.state_machine.state_graph.states))
    logger.info(f'=== Crawl started. Queue size: {len(crawl_context.crawl_queue)} ===')

    while len(crawl_context.crawl_queue) > 0 and not STOP_REQUESTED:
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

                action.execute(crawl_context.driver)

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

    crawl_context.driver.quit()

    write_status(
        LOOP_COUNTER,
        0,
        len(crawl_context.state_machine.state_graph.states),
        current_state_id='DONE',
    )
    logger.info(f'=== Crawl complete. {LOOP_COUNTER} actions processed, {len(crawl_context.state_machine.state_graph.states)} states discovered ===')

    save_state_graph(crawl_context, APP_NAME)

except Exception as e:
    import traceback
    error_msg = f'{type(e).__name__}: {e}'
    logger.error(f'Crawl failed: {error_msg}')
    logger.error(traceback.format_exc())
    write_status(LOOP_COUNTER, 0, 0, error=error_msg)
    try:
        crawl_context.driver.quit()
    except:
        pass
    raise
