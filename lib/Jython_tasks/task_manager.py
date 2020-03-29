import logging
import threading
import time

from java.util.concurrent import Executors, TimeUnit
from threading import InterruptedException


class TaskManager:
    def __init__(self, number_of_threads=10):
        self.log = logging.getLogger("infra")
        self.log.info("Initiating TaskManager with {0} threads"
                      .format(number_of_threads))
        self.number_of_threads = number_of_threads
        self.pool = Executors.newFixedThreadPool(self.number_of_threads)
        self.futures = {}

    def sleep(self, time_in_sec, message):
        self.log.info("%s. Sleep for %s seconds.." % (message, time_in_sec))
        time.sleep(time_in_sec)

    def add_new_task(self, task):
        future = self.pool.submit(task)
        self.futures[task.thread_name] = future
        self.log.info("Added new task: %s" % task.thread_name)

    def get_task_result(self, task):
        self.log.debug("Getting task result for %s" % task.thread_name)
        future = self.futures[task.thread_name]
        result = future.get()
        self.futures.pop(task.thread_name)
        return result

    def schedule(self, task, sleep_time=0):
        self.add_new_task(task)

    def stop_task(self, task):
        if task.thread_name not in self.futures.keys():
            return
        future = self.futures[task.thread_name]
        i = 0
        while not future.isDone() and i < 30:
            self.sleep(1, "Wait for %s to complete. Current status: %s"
                          % (task.thread_name, future.isDone()))
            i += 1
        else:
            self.log.debug("Task {0} in already finished. No need to stop task"
                           .format(task.thread_name))
        if not future.isDone():
            self.log.debug("Stopping task {0}".format(task.thread_name))
            future.cancel(True)

    def shutdown_task_manager(self, timeout=5):
        self.shutdown(timeout)

    def shutdown(self, timeout):
        self.log.info("Running TaskManager shutdown")
        self.pool.shutdown()
        try:
            if not self.pool.awaitTermination(timeout, TimeUnit.SECONDS):
                self.pool.shutdownNow()
                self.log.debug("TaskManager shutdown forcefully")
                if not self.pool.awaitTermination(timeout, TimeUnit.SECONDS):
                    self.log.error("Pool did not terminate")
        except InterruptedException, ex:
            self.log.error(ex)
            # (Re-)Cancel if current thread also interrupted
            self.pool.shutdownNow()
            # Preserve interrupt status
            threading.currentThread().interrupt()

    def print_tasks_in_pool(self):
        for task_name, future in self.futures.items():
            if not future.isDone():
                self.log.warning("Task '{0}' not completed".format(task_name))

    def abort_all_tasks(self):
        for task_name, future in self.futures.items():
            self.log.info("Stopping task {0}".format(task_name))
            result = future.cancel(True)
            if result:
                self.log.debug("Stopped task {0}".format(task_name))
            else:
                self.log.debug("Task {0} could not be cancelled or already finished."
                               .format(task_name))
