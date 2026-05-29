import time


class Timeout:
    duration: float = 0

    @staticmethod
    def set_duration(t: float) -> None:
        Timeout.duration = t

    @staticmethod
    def timeout() -> None:
        time.sleep(Timeout.duration)
