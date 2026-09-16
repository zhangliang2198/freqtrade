import logging
import re
import sys
from io import StringIO

import pytest
from rich.console import Console
from rich.table import Table

from freqtrade.exceptions import OperationalException
from freqtrade.loggers import (
    FTBufferingHandler,
    FtRichHandler,
    setup_logging,
    setup_logging_pre,
)
from freqtrade.loggers.set_log_levels import (
    reduce_verbosity_for_bias_tester,
    restore_verbosity_for_bias_tester,
)


def test_rich_handler_strategy_log_style(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)

    terminal_output = StringIO()
    handler = FtRichHandler(
        Console(force_terminal=True, color_system="standard", file=terminal_output)
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    styled_record = logging.LogRecord("test", logging.INFO, __file__, 1, "styled message", (), None)
    styled_record.strategy_log_style = "red"
    handler.emit(styled_record)
    assert "\x1b[31mstyled message\x1b[0m" in terminal_output.getvalue()

    dynamic_record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "literal [red]dynamic[/red]", (), None
    )
    plain_output = StringIO()
    plain_handler = logging.StreamHandler(plain_output)
    plain_handler.setFormatter(logging.Formatter("%(message)s"))
    plain_handler.handle(styled_record)
    plain_handler.handle(dynamic_record)
    assert plain_output.getvalue() == "styled message\nliteral [red]dynamic[/red]\n"
    assert "\x1b[" not in plain_output.getvalue()

    handler.emit(dynamic_record)
    dynamic_output = terminal_output.getvalue()
    assert "literal [red]dynamic[/red]" in dynamic_output
    assert "\x1b[31mliteral" not in dynamic_output

    ordinary_record = logging.LogRecord("test", logging.INFO, __file__, 1, "ordinary", (), None)
    handler.emit(ordinary_record)
    assert terminal_output.getvalue().endswith("ordinary\n")


def test_rich_handler_strategy_log_table():
    terminal_output = StringIO()
    handler = FtRichHandler(Console(width=80, file=terminal_output))
    handler.setFormatter(logging.Formatter("%(message)s"))

    table = Table()
    table.add_column("指标")
    table.add_column("值")
    table.add_row("中文状态", "运行中")
    record = logging.LogRecord(
        "strategy",
        logging.INFO,
        __file__,
        1,
        "%s\n%s",
        ("策略状态", "PLAIN_TABLE_COPY"),
        None,
    )
    record.strategy_log_table = table

    handler.emit(record)

    output = terminal_output.getvalue()
    lines = output.splitlines()
    assert lines[0].endswith("策略状态")
    assert output.count("中文状态") == 1
    assert "运行中" in output
    assert "PLAIN_TABLE_COPY" not in output
    assert all(len(line) <= 80 for line in lines)
    assert table.expand is False


@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers() -> None:
    # Reset Logging to Debug, otherwise this fails randomly as it's set globally
    logging.getLogger("requests").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("ccxt.base.exchange").setLevel(logging.DEBUG)
    logging.getLogger("telegram").setLevel(logging.DEBUG)

    previous_value1 = logging.getLogger("requests").level
    previous_value2 = logging.getLogger("ccxt.base.exchange").level
    previous_value3 = logging.getLogger("telegram").level
    config = {
        "verbosity": 1,
        "ft_tests_force_logging": True,
    }
    setup_logging(config)

    value1 = logging.getLogger("requests").level
    assert previous_value1 is not value1
    assert value1 is logging.INFO

    value2 = logging.getLogger("ccxt.base.exchange").level
    assert previous_value2 is not value2
    assert value2 is logging.INFO

    value3 = logging.getLogger("telegram").level
    assert previous_value3 is not value3
    assert value3 is logging.INFO
    config["verbosity"] = 2
    setup_logging(config)

    assert logging.getLogger("requests").level is logging.DEBUG
    assert logging.getLogger("ccxt.base.exchange").level is logging.INFO
    assert logging.getLogger("telegram").level is logging.INFO
    assert logging.getLogger("werkzeug").level is logging.INFO

    config["verbosity"] = 3
    config["api_server"] = {"verbosity": "error"}
    setup_logging(config)

    assert logging.getLogger("requests").level is logging.DEBUG
    assert logging.getLogger("ccxt.base.exchange").level is logging.DEBUG
    assert logging.getLogger("telegram").level is logging.INFO
    assert logging.getLogger("werkzeug").level is logging.ERROR


@pytest.mark.skipif(sys.platform == "win32", reason="does not run on windows")
@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers_syslog():
    logger = logging.getLogger()
    orig_handlers = logger.handlers
    logger.handlers = []

    config = {
        "ft_tests_force_logging": True,
        "verbosity": 2,
        "logfile": "syslog:/dev/log",
    }

    setup_logging_pre()
    setup_logging(config)
    assert len(logger.handlers) == 3
    assert [x for x in logger.handlers if isinstance(x, logging.handlers.SysLogHandler)]
    assert [x for x in logger.handlers if isinstance(x, FtRichHandler)]
    assert [x for x in logger.handlers if isinstance(x, FTBufferingHandler)]
    # setting up logging again should NOT cause the loggers to be added a second time.
    setup_logging(config)
    assert len(logger.handlers) == 3
    # reset handlers to not break pytest
    logger.handlers = orig_handlers


@pytest.mark.skipif(sys.platform == "win32", reason="does not run on windows")
@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers_Filehandler(tmp_path):
    logger = logging.getLogger()
    orig_handlers = logger.handlers
    logger.handlers = []
    logfile = tmp_path / "logs/ft_logfile.log"
    config = {
        "ft_tests_force_logging": True,
        "verbosity": 2,
        "logfile": str(logfile),
    }

    setup_logging_pre()
    setup_logging(config)
    assert len(logger.handlers) == 3
    assert [x for x in logger.handlers if isinstance(x, logging.handlers.RotatingFileHandler)]
    assert [x for x in logger.handlers if isinstance(x, FtRichHandler)]
    assert [x for x in logger.handlers if isinstance(x, FTBufferingHandler)]
    # setting up logging again should NOT cause the loggers to be added a second time.
    setup_logging(config)
    assert len(logger.handlers) == 3
    # reset handlers to not break pytest
    if logfile.exists:
        logfile.unlink()
    logger.handlers = orig_handlers


@pytest.mark.skipif(sys.platform == "win32", reason="does not run on windows")
@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers_Filehandler_without_permission(tmp_path):
    logger = logging.getLogger()
    orig_handlers = logger.handlers
    logger.handlers = []

    try:
        tmp_path.chmod(0o400)
        logfile = tmp_path / "logs/ft_logfile.log"
        config = {
            "ft_tests_force_logging": True,
            "verbosity": 2,
            "logfile": str(logfile),
        }

        setup_logging_pre()
        with pytest.raises(OperationalException):
            setup_logging(config)

        logger.handlers = orig_handlers
    finally:
        tmp_path.chmod(0o700)


@pytest.mark.skip(reason="systemd is not installed on every system, so we're not testing this.")
@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers_journald():
    logger = logging.getLogger()
    orig_handlers = logger.handlers
    logger.handlers = []

    config = {
        "ft_tests_force_logging": True,
        "verbosity": 2,
        "logfile": "journald",
    }

    setup_logging_pre()
    setup_logging(config)
    assert len(logger.handlers) == 3
    assert [x for x in logger.handlers if type(x).__name__ == "JournaldLogHandler"]
    assert [x for x in logger.handlers if isinstance(x, FtRichHandler)]
    # reset handlers to not break pytest
    logger.handlers = orig_handlers


@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers_journald_importerror(import_fails):
    logger = logging.getLogger()
    orig_handlers = logger.handlers
    logger.handlers = []

    config = {
        "ft_tests_force_logging": True,
        "verbosity": 2,
        "logfile": "journald",
    }
    with pytest.raises(OperationalException, match=r"You need the cysystemd python package.*"):
        setup_logging(config)
    logger.handlers = orig_handlers


@pytest.mark.usefixtures("keep_log_config_loggers")
def test_set_loggers_json_format(capsys):
    logger = logging.getLogger()
    orig_handlers = logger.handlers
    logger.handlers = []

    config = {
        "ft_tests_force_logging": True,
        "verbosity": 2,
        "log_config": {
            "version": 1,
            "formatters": {
                "json": {
                    "()": "freqtrade.loggers.json_formatter.JsonFormatter",
                    "fmt_dict": {
                        "timestamp": "asctime",
                        "level": "levelname",
                        "logger": "name",
                        "message": "message",
                    },
                }
            },
            "handlers": {
                "json": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                }
            },
            "root": {
                "handlers": ["json"],
                "level": "DEBUG",
            },
        },
    }

    setup_logging_pre()
    setup_logging(config)
    assert len(logger.handlers) == 2
    assert [x for x in logger.handlers if type(x).__name__ == "StreamHandler"]
    assert [x for x in logger.handlers if isinstance(x, FTBufferingHandler)]

    logger.info("Test message")

    captured = capsys.readouterr()
    assert re.search(r'{"timestamp": ".*"Test message".*', captured.err)

    # reset handlers to not break pytest
    logger.handlers = orig_handlers


def test_reduce_verbosity():
    setup_logging_pre()
    reduce_verbosity_for_bias_tester()
    prior_level = logging.getLogger("freqtrade").getEffectiveLevel()

    assert logging.getLogger("freqtrade.resolvers").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("freqtrade.strategy.hyper").getEffectiveLevel() == logging.WARNING
    # base level wasn't changed
    assert logging.getLogger("freqtrade").getEffectiveLevel() == prior_level

    restore_verbosity_for_bias_tester()

    assert logging.getLogger("freqtrade.resolvers").getEffectiveLevel() == prior_level
    assert logging.getLogger("freqtrade.strategy.hyper").getEffectiveLevel() == prior_level
    assert logging.getLogger("freqtrade").getEffectiveLevel() == prior_level
    # base level wasn't changed


def test_rich_table_title_does_not_request_plain_text():
    class PlainTextMustNotRender:
        def __str__(self):
            raise AssertionError("Rich handler requested duplicate plain text")

    output = StringIO()
    handler = FtRichHandler(Console(width=80, file=output))
    table = Table("Rule")
    table.add_row("hourly break")
    record = logging.LogRecord(
        "strategy", logging.INFO, __file__, 1, PlainTextMustNotRender(), (), None
    )
    record.strategy_log_table = table
    record.strategy_log_title = "Exit rules"
    handler.emit(record)
    assert "Exit rules" in output.getvalue()
    assert "hourly break" in output.getvalue()
