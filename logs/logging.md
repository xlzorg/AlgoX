top of code:
from logs.file_logger import get_file_logger


on the init function:
self._file_logger = get_file_logger("paper_broker")

example usecase/implementation:
self._file_logger.info("=== PaperBroker.submit ===")
    self._file_logger.info(
        "approved=%s | price=%s | entry_price=%s | order_type=%s | direction=%s | qty=%s",
        intent.approved, price, intent.entry_price, order_type, intent.direction, intent.quantity,
    )

    