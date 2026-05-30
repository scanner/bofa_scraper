import time


class Timeout:
    """
    Global configurable sleep used between page-load steps.

    A single duration applies to the whole scraping session. Set it once at
    startup via set_duration(); call timeout() wherever the code must wait for
    a page or dialog to finish loading.
    """

    duration: float = 0

    @staticmethod
    def set_duration(t: float) -> None:
        """
        Set the global sleep duration in seconds.

        Args:
            t: Seconds to sleep on each timeout() call. Use 0 in tests.
        """
        Timeout.duration = t

    @staticmethod
    def timeout() -> None:
        """Sleep for the configured duration."""
        time.sleep(Timeout.duration)
