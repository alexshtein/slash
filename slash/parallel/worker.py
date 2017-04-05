import pickle
import xmlrpc.client
import threading
import time

from ..ctx import context
from ..runner import run_tests

class Worker(object):
    def __init__(self, client_id, collected_tests):
        self.client_id = client_id
        self.all_tests = collected_tests

    def find_test(self, func_data):
        for test in self.all_tests:
            if test.__slash__.file_path == func_data[0] and test.__slash__.function_name == func_data[1] and test.__slash__.variation.id == func_data[2]:
                return test

    def keep_alive(self, proxy, stop_event):
        while not stop_event.is_set():
            proxy.keep_alive(self.client_id)
            stop_event.wait(1)

    def start(self):
        self.client = xmlrpc.client.ServerProxy('http://localhost:8000')
        self.client.connect(self.client_id)
        test_num = 0
        while True:
            func_data = self.client.get_test(self.client_id)
            if func_data == "end":
                break
            elif func_data == "pending":
                time.sleep(5)
                continue
            else:
                test = self.find_test(func_data)
                stop_event = threading.Event()
                tr = threading.Thread(target=self.keep_alive, args=(self.client, stop_event))
                tr.start()
                run_tests([test])
                stop_event.set()
                tr.join()
                result = context.session.results[test_num]
                errors = pickle.dumps(result._errors)
                failures = pickle.dumps(result._failures)
                skips = pickle.dumps(result._skips)
                self.client.finished_test(self.client_id, result.is_success_finished(), errors, failures, skips)
            test_num += 1
