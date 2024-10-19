import logging
import logging.config as logging_config
import sys
from os import getenv
from time import sleep


class Application:

    __success_interval: int
    __retry_interval: int

    def __mgetenv(self, name: str) -> str:
        """Get an environment variable or exit if it is not set"""
        if (value := getenv(name)) is None:
            logging.critical("Environment variable %s is required", name)
            sys.exit(1)
        return value

    def _setup_logging(self) -> None:
        # Configure logging
        log_level = (
            environment_log_level
            if (environment_log_level := getenv("LOG_LEVEL"))
            in logging.getLevelNamesMapping()
            else "INFO"
        )
        logging_config.dictConfig(
            {
                "version": 1,
                "formatters": {
                    "default": {
                        "format": "%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
                    }
                },
                "root": {"level": log_level},
            }
        )

    def _setup(self) -> None:
        """Setup the application"""
        self._setup_logging()
        self.__success_interval = int(self.__mgetenv("SUCCESS_INTERVAL"))
        self.__retry_interval = int(self.__mgetenv("RETRY_INTERVAL"))

    def _loop(self) -> None:
        """Function called in a loop to check for changes in the forwarded port"""
        # TODO

    def run(self) -> None:
        """App entry point, in charge of setting up the app and starting the loop"""
        self._setup()
        while True:
            try:
                self._loop()
            except (Exception,) as exception:
                logging.error("Retryable error in lifecycle", exc_info=exception)
                sleep(self.__retry_interval)
            else:
                sleep(self.__success_interval)


if __name__ == "__main__":
    Application().run()
