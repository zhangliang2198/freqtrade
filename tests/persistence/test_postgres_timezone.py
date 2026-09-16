from datetime import UTC
from unittest.mock import MagicMock

import pytest

from freqtrade.persistence import models


def test_default_trade_open_date_is_utc_not_local_time():
    value = models.Trade.__table__.c.open_date.default.arg(None)
    assert value.tzinfo == UTC


@pytest.mark.parametrize("autocommit", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_postgres_timezone_is_set_outside_transaction_and_restores_mode(autocommit, fail):
    connection = MagicMock(autocommit=autocommit)
    cursor = connection.cursor.return_value.__enter__.return_value

    def execute(sql):
        assert connection.autocommit is True
        assert sql == "SET SESSION TIME ZONE 'UTC'"
        if fail:
            raise RuntimeError("connection failed")

    cursor.execute.side_effect = execute
    if fail:
        with pytest.raises(RuntimeError, match="connection failed"):
            models._set_postgres_timezone(connection, None)
    else:
        models._set_postgres_timezone(connection, None)
    assert connection.autocommit is autocommit
    cursor.execute.assert_called_once()


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_init_db_registers_utc_only_for_postgres(mocker, dialect):
    engine = MagicMock()
    engine.dialect.name = dialect
    mocker.patch.object(models, "create_engine", return_value=engine)
    mocker.patch.object(models, "inspect").return_value.get_table_names.return_value = []
    mocker.patch.object(models.ModelBase.metadata, "create_all")
    mocker.patch.object(models, "check_migrate")
    # Avoid changing global ORM sessions during this connection wiring test.
    for model in (
        models.Trade,
        models.Order,
        models.PairLock,
        models._KeyValueStoreModel,
        models._CustomData,
        models.WalletHistory,
    ):
        mocker.patch.object(model, "session", MagicMock(), create=True)
    mocker.patch.object(models, "scoped_session", return_value=models.Trade.session)
    listen = mocker.patch.object(models.event, "listen")
    models.init_db("sqlite://")
    if dialect == "postgresql":
        listen.assert_called_once_with(engine, "connect", models._set_postgres_timezone)
    else:
        listen.assert_not_called()
