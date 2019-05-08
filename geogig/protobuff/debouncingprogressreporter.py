import time

# simple progress reporter
# the overhead in reporting progress is quite high - this will only report occasionally
class DebouncingProgressReporter:

    def __init__(self, progressFn):
        self.last_report_time = time.perf_counter()
        self.progressFn = progressFn
        self.nread = 0

    def reportFeatureRead(self):
        self.nread += 1
        time_now = time.perf_counter()
        elapsed = time_now - self.last_report_time
        if elapsed > 0.2:
            if self.progressFn is not None:
                self.progressFn(self.nread)
            #setProgressText("Read " + "{:,}".format(self.nread) + " features...")
            self.last_report_time = time_now
