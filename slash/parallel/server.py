from datetime import datetime
from xmlrpc.server import SimpleXMLRPCServer
import queue
import pickle
from ..core.result import Result
import logbook
from .. import log
_logger = logbook.Logger(__name__)
log.set_log_color(_logger.name, logbook.NOTICE, 'blue')

class Server(object):
    def __init__(self, tests, stop_on_error):
        self.tests = tests
        self.stop_on_error = stop_on_error
        self.has_failed_test = False

        self.not_started_tests = queue.Queue()
        for i in range(len(tests)):
            self.not_started_tests.put(i)
        self.executing_tests = {}
        self.finished_tests = []

        self.clients_last_communication_time = {}

    def get_client_data(self):
        return self.clients_last_communication_time

    def has_unstarted_tests(self):
        return not self.not_started_tests.empty()

    def keep_alive(self, client_id):
        _logger.debug("Client_id {} sent keep_alive".format(client_id))
        self.clients_last_communication_time[client_id] = datetime.now()

    def report_client_disconnection(self, client_id):
        self.clients_last_communication_time.pop(client_id)
        test_index = self.executing_tests.get(client_id, None)
        if test_index is not None:
            self.not_started_tests.put(test_index)

    def has_unfinished_tests(self):
        return len(self.finished_tests) < len(self.tests)

    def no_more_tests(self):
        return (self.stop_on_error and self.has_failed_test) or not self.has_unfinished_tests()

    def has_connected_clients(self):
        return len(self.clients_last_communication_time) > 0

    def connect(self, client_id):
        _logger.notice("Client_id {} connected".format(client_id))
        self.clients_last_communication_time[client_id] = datetime.now()

    def get_test(self, client_id):
        self.clients_last_communication_time[client_id] = datetime.now()
        if self.no_more_tests():
            self.clients_last_communication_time.pop(client_id)
            _logger.notice("No more tests, removing client_id {}".format(client_id))
            return "end"
        elif self.has_unstarted_tests():
            index = self.not_started_tests.get()
            test = self.tests[index]
            self.executing_tests[client_id] = index
            _logger.notice("#{}: {}, Client_id: {}", index, test.__slash__.address, client_id, extra={'to_error_log': 1})
            return (test.__slash__.file_path, test.__slash__.function_name, test.__slash__.variation.id)
        else: #has_unfinished_tests:
            return "pending"

    def handle_test_end(self, failures, errors, skips):
        result = Result()
        for failure in failures:
            result.add_failure(failure)
        for error in errors:
            result.add_error(error)
        for skip in skips:
            result.add_skip(skip)

    def finished_test(self, client_id, is_success_finished, errors, failures, skips):
        self.clients_last_communication_time[client_id] = datetime.now()
        _logger.notice("Client_id {} finished_test".format(client_id))
        _logger.debug("Failures: {}, Errors: {}, Skips: {}".format(pickle.loads(failures.data), pickle.loads(errors.data), pickle.loads(skips.data)))
        self.handle_test_end(pickle.loads(failures.data), pickle.loads(errors.data), pickle.loads(skips.data))
        test_index = self.executing_tests.get(client_id, None)
        if test_index is not None:
            self.finished_tests.append(test_index)
            self.executing_tests[client_id] = None
            if not is_success_finished and self.stop_on_error:
                self.has_failed_test = True
        else:
            raise RuntimeError('finished_test')

    def serve(self):
        with SimpleXMLRPCServer(("localhost", 8000), allow_none=True, logRequests=False) as server:
            server.register_instance(self)
            while self.has_connected_clients() or not self.no_more_tests():
                server.handle_request()
        _logger.debug("Exiting server loop")
