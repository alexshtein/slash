import xmlrpc.client
import subprocess
import time
from datetime import datetime
from .worker import Worker
import logbook

_logger = logbook.Logger(__name__)


class WorkerManager(object):
    def __init__(self, workers_num, args):
        self.args = ['slash', 'run'] + args
        self.workers_num = workers_num
        self.server_proxy = xmlrpc.client.ServerProxy('http://localhost:8000')
        self.workers = []
        self.max_worker_id = 0

    def try_connect(self):
        TIMEOUT = 10
        start_time = time.time()
        while True:
            try:
                self.server_proxy.has_unfinished_tests()
            except Exception as e:
                if time.time() - start_time > TIMEOUT:
                    raise
                time.sleep(1)
            else:
                break

    def start_worker(self):
        _logger.notice("Statring worker number {}".format(str(self.max_worker_id)))
        proc = subprocess.Popen(self.args[:] + ["--worker_id", str(self.max_worker_id)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        #proc = subprocess.Popen(self.args[:] + ["--worker_id", str(self.max_worker_id)])
        self.workers.append(proc)
        self.max_worker_id += 1

    def assert_slave(self):
        return True

    def clean_slave(self):
        pass

    def start(self):
        self.try_connect()
        for i in range(self.workers_num):
            self.start_worker()
        try:
            while not self.server_proxy.no_more_tests():
                time.sleep(5)
                clients = self.server_proxy.get_client_data()
                for client_id in clients:
                    delta = (datetime.now() - datetime.strptime(clients[client_id].value, "%Y%m%dT%H:%M:%S")).seconds
                    if (delta > 5):
                        _logger.notice("Client {} is down, restarting".format(client_id))
                        self.server_proxy.report_client_disconnection(client_id)
                        self.start_worker()
        except Exception as e:
            print(e)
