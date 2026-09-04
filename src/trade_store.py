import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Optional, Union


_DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "trading.db"


@dataclass(frozen=True)
class RiskState:
    peak_account_equity: Optional[Decimal]
    day_start_equity: Optional[Decimal]
    trading_date: date
    daily_realized_pnl: Decimal
    daily_loss_halt_until: Optional[datetime]
    consecutive_losses: int
    consecutive_loss_cooldown_until: Optional[datetime]
    halted: bool
    halt_reason: Optional[str]
    last_update_time: datetime


def _utc_timestamp(value: Optional[datetime] = None) -> str:
    value = datetime.now(timezone.utc) if value is None else value
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Stored timestamp is not timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _decimal_text(value: Union[Decimal, int, str], field: str) -> str:
    if isinstance(value, float):
        raise TypeError(f"{field} must not be a float.")
    return str(Decimal(value))


def _decimal(value: Optional[str]) -> Optional[Decimal]:
    return None if value is None else Decimal(value)


class TradeStore:
    def __init__(self, database_path: Optional[Union[str, Path]] = None):
        self.database_path = Path(database_path or _DEFAULT_DATABASE_PATH)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    signal_time TEXT,
                    quantity TEXT NOT NULL,
                    entry_price TEXT NOT NULL,
                    stop_loss_price TEXT NOT NULL,
                    take_profit_price TEXT NOT NULL,
                    planned_risk TEXT NOT NULL,
                    margin_used TEXT NOT NULL,
                    entry_time TEXT,
                    exit_time TEXT,
                    exit_price TEXT,
                    realized_pnl TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_state (
                    state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                    peak_account_equity TEXT,
                    day_start_equity TEXT,
                    trading_date TEXT NOT NULL,
                    daily_realized_pnl TEXT NOT NULL,
                    daily_loss_halt_until TEXT,
                    consecutive_losses INTEGER NOT NULL,
                    consecutive_loss_cooldown_until TEXT,
                    halted INTEGER NOT NULL,
                    halt_reason TEXT,
                    last_update_time TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(risk_state)")
            }
            if "day_start_equity" not in columns:
                connection.execute("ALTER TABLE risk_state ADD COLUMN day_start_equity TEXT")
            if "consecutive_loss_cooldown_until" not in columns:
                connection.execute("ALTER TABLE risk_state ADD COLUMN consecutive_loss_cooldown_until TEXT")
            if "daily_loss_halt_until" not in columns:
                connection.execute("ALTER TABLE risk_state ADD COLUMN daily_loss_halt_until TEXT")
            trade_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(trades)"
                )
            }
            exchange_order_columns = {
                "signal_time": "TEXT",
                "entry_order_id": "INTEGER",
                "entry_client_order_id": "TEXT",
                "stop_algo_id": "INTEGER",
                "stop_client_algo_id": "TEXT",
                "take_profit_algo_id": "INTEGER",
                "take_profit_client_algo_id": "TEXT",
            }
            for column_name, column_type in exchange_order_columns.items():
                if column_name not in trade_columns:
                    connection.execute(
                        f"ALTER TABLE trades ADD COLUMN "
                        f"{column_name} {column_type}"
                    )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_trades_symbol_signal_time
                ON trades(symbol, signal_time)
                WHERE signal_time IS NOT NULL
                """
            )

            connection.execute(
                """
                INSERT OR IGNORE INTO risk_state (
                    state_id, peak_account_equity, day_start_equity, trading_date,
                    daily_realized_pnl, daily_loss_halt_until, consecutive_losses, consecutive_loss_cooldown_until, halted,
                    halt_reason, last_update_time
                ) VALUES (1, NULL, NULL, ?, '0', NULL, 0, NULL, 0, NULL, ?)
                """,
                (datetime.now(timezone.utc).date().isoformat(), _utc_timestamp()),
            )

    def record_planned_trade(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        planned_risk: Decimal,
        margin_used: Decimal,
        entry_client_order_id: Optional[str] = None,
        stop_client_algo_id: Optional[str] = None,
        take_profit_client_algo_id: Optional[str] = None,
        signal_time: Optional[datetime] = None,
    ) -> int:
        signal_time_text = (
            None
            if signal_time is None
            else _utc_timestamp(signal_time)
        )
        client_ids = (
            entry_client_order_id,
            stop_client_algo_id,
            take_profit_client_algo_id,
        )
        if any(value is not None for value in client_ids):
            if any(
                not isinstance(value, str) or not value
                for value in client_ids
            ):
                raise ValueError(
                    "All planned client order ids are required."
                )

        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT trade_id
                FROM trades
                WHERE symbol = ?
                  AND status IN ('PLANNED', 'OPEN')
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if existing is not None:
                raise ValueError(
                    "An active trade already exists for this symbol."
                )

            if signal_time_text is not None:
                existing_signal = connection.execute(
                    """
                    SELECT trade_id
                    FROM trades
                    WHERE symbol = ? AND signal_time = ?
                    LIMIT 1
                    """,
                    (symbol, signal_time_text),
                ).fetchone()
                if existing_signal is not None:
                    raise ValueError(
                        "This signal candle was already processed."
                    )

            cursor = connection.execute(
                """
                INSERT INTO trades (
                    symbol, side, status, signal_time,
                    quantity, entry_price,
                    stop_loss_price, take_profit_price,
                    planned_risk, margin_used,
                    entry_client_order_id,
                    stop_client_algo_id,
                    take_profit_client_algo_id
                ) VALUES (
                    ?, ?, 'PLANNED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    symbol,
                    side,
                    signal_time_text,
                    _decimal_text(quantity, "quantity"),
                    _decimal_text(entry_price, "entry_price"),
                    _decimal_text(stop_loss_price, "stop_loss_price"),
                    _decimal_text(take_profit_price, "take_profit_price"),
                    _decimal_text(planned_risk, "planned_risk"),
                    _decimal_text(margin_used, "margin_used"),
                    entry_client_order_id,
                    stop_client_algo_id,
                    take_profit_client_algo_id,
                ),
            )
            return int(cursor.lastrowid)

    def mark_open_with_exchange_orders(
        self,
        trade_id: int,
        entry_order_id: int,
        entry_client_order_id: str,
        stop_algo_id: int,
        stop_client_algo_id: str,
        take_profit_algo_id: int,
        take_profit_client_algo_id: str,
        entry_time: Optional[datetime] = None,
    ) -> None:
        numeric_ids = (
            entry_order_id,
            stop_algo_id,
            take_profit_algo_id,
        )
        client_ids = (
            entry_client_order_id,
            stop_client_algo_id,
            take_profit_client_algo_id,
        )
        if any(
            not isinstance(value, int) or value <= 0
            for value in numeric_ids
        ):
            raise ValueError("Exchange order ids must be positive integers.")
        if any(not value for value in client_ids):
            raise ValueError("Exchange client order ids are required.")

        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE trades
                SET status = 'OPEN',
                    entry_time = ?,
                    entry_order_id = ?,
                    entry_client_order_id = ?,
                    stop_algo_id = ?,
                    stop_client_algo_id = ?,
                    take_profit_algo_id = ?,
                    take_profit_client_algo_id = ?
                WHERE trade_id = ? AND status = 'PLANNED'
                """,
                (
                    _utc_timestamp(entry_time),
                    entry_order_id,
                    entry_client_order_id,
                    stop_algo_id,
                    stop_client_algo_id,
                    take_profit_algo_id,
                    take_profit_client_algo_id,
                    trade_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Trade is missing or is not planned.")

    def mark_failed(self, trade_id: int) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE trades
                SET status = 'FAILED'
                WHERE trade_id = ? AND status = 'PLANNED'
                """,
                (trade_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("Trade is missing or is not planned.")

    def mark_open(self, trade_id: int, entry_time: Optional[datetime] = None) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE trades
                SET status = 'OPEN', entry_time = ?
                WHERE trade_id = ? AND status = 'PLANNED'
                """,
                (_utc_timestamp(entry_time), trade_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Trade is missing or is not planned.")

    def mark_closed(
        self,
        trade_id: int,
        exit_price: Decimal,
        realized_pnl: Decimal,
        exit_time: Optional[datetime] = None,
    ) -> None:
        with self._transaction() as connection:
            trade = connection.execute(
                "SELECT status FROM trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()
            if trade is None or trade["status"] != "OPEN":
                raise ValueError("Trade is missing or is not open.")

            pnl_text = _decimal_text(realized_pnl, "realized_pnl")
            connection.execute(
                """
                UPDATE trades
                SET status = 'CLOSED', exit_time = ?, exit_price = ?, realized_pnl = ?
                WHERE trade_id = ? AND status = 'OPEN'
                """,
                (_utc_timestamp(exit_time), _decimal_text(exit_price, "exit_price"), pnl_text, trade_id),
            )

            state = self._current_risk_state(connection)
            pnl = Decimal(pnl_text)
            consecutive_losses = (
                state["consecutive_losses"] + 1 if pnl < 0 else 0
            )
            connection.execute(
                """
                UPDATE risk_state
                SET daily_realized_pnl = ?, consecutive_losses = ?, last_update_time = ?
                WHERE state_id = 1
                """,
                (
                    str(Decimal(state["daily_realized_pnl"]) + pnl),
                    consecutive_losses,
                    _utc_timestamp(),
                ),
            )

    def read_active_trades(self) -> list[dict]:
        rows = self._connection.execute(
            "SELECT * FROM trades WHERE status IN ('PLANNED', 'OPEN') ORDER BY trade_id"
        ).fetchall()
        return [self._trade_row(row) for row in rows]

    def _trade_row(self, row: sqlite3.Row) -> dict:
        return {
            "trade_id": row["trade_id"],
            "symbol": row["symbol"],
            "side": row["side"],
            "status": row["status"],
            "signal_time": (
                None
                if row["signal_time"] is None
                else _utc_datetime(row["signal_time"])
            ),
            "quantity": Decimal(row["quantity"]),
            "entry_price": Decimal(row["entry_price"]),
            "stop_loss_price": Decimal(row["stop_loss_price"]),
            "take_profit_price": Decimal(row["take_profit_price"]),
            "planned_risk": Decimal(row["planned_risk"]),
            "margin_used": Decimal(row["margin_used"]),
            "entry_order_id": row["entry_order_id"],
            "entry_client_order_id": row["entry_client_order_id"],
            "stop_algo_id": row["stop_algo_id"],
            "stop_client_algo_id": row["stop_client_algo_id"],
            "take_profit_algo_id": row["take_profit_algo_id"],
            "take_profit_client_algo_id": row["take_profit_client_algo_id"],
            "entry_time": None if row["entry_time"] is None else _utc_datetime(row["entry_time"]),
            "exit_time": None if row["exit_time"] is None else _utc_datetime(row["exit_time"]),
            "exit_price": _decimal(row["exit_price"]),
            "realized_pnl": _decimal(row["realized_pnl"]),
        }

    def _current_risk_state(self, connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
        if row is None:
            raise ValueError("Risk state is missing.")
        today = datetime.now(timezone.utc).date().isoformat()
        if row["trading_date"] != today:
            clear_legacy_daily_halt = row["halt_reason"] == "Daily realized loss limit reached."
            connection.execute(
                """
                UPDATE risk_state
                SET trading_date = ?, daily_realized_pnl = '0', daily_loss_halt_until = NULL,
                    halted = CASE WHEN ? THEN 0 ELSE halted END,
                    halt_reason = CASE WHEN ? THEN NULL ELSE halt_reason END,
                    last_update_time = ?
                WHERE state_id = 1
                """,
                (today, clear_legacy_daily_halt, clear_legacy_daily_halt, _utc_timestamp()),
            )
            row = connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
        return row

    def read_risk_state(self) -> RiskState:
        with self._transaction() as connection:
            row = self._current_risk_state(connection)
            return self._risk_state(row)

    def sync_equity(self, current_equity: Decimal) -> RiskState:
        equity_text = _decimal_text(current_equity, "current_equity")
        if Decimal(equity_text) <= 0:
            raise ValueError("Current equity must be positive.")
        with self._transaction() as connection:
            today = datetime.now(timezone.utc).date().isoformat()
            row = connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
            if row is None:
                raise ValueError("Risk state is missing.")
            date_changed = row["trading_date"] != today
            peak = row["peak_account_equity"]
            day_start = row["day_start_equity"]
            if date_changed or day_start is None:
                day_start = equity_text
            if peak is None or Decimal(equity_text) > Decimal(peak):
                peak = equity_text
            clear_legacy_daily_halt = date_changed and row["halt_reason"] == "Daily realized loss limit reached."
            connection.execute(
                """
                UPDATE risk_state
                SET peak_account_equity = ?, day_start_equity = ?,
                    trading_date = ?, daily_realized_pnl = ?, daily_loss_halt_until = ?, last_update_time = ?
                    , halted = CASE WHEN ? THEN 0 ELSE halted END
                    , halt_reason = CASE WHEN ? THEN NULL ELSE halt_reason END
                WHERE state_id = 1
                """,
                (peak, day_start, today, "0" if date_changed else row["daily_realized_pnl"], None if date_changed else row["daily_loss_halt_until"], _utc_timestamp(), clear_legacy_daily_halt, clear_legacy_daily_halt),
            )
            return self._risk_state(
                connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
            )

    def update_risk_state(
        self,
        peak_account_equity: Optional[Decimal] = None,
        halted: Optional[bool] = None,
        halt_reason: Optional[str] = None,
        consecutive_loss_cooldown_until: Optional[datetime] = None,
    ) -> RiskState:
        with self._transaction() as connection:
            row = self._current_risk_state(connection)
            current_peak = row["peak_account_equity"]
            peak = (
                current_peak
                if peak_account_equity is None
                else _decimal_text(peak_account_equity, "peak_account_equity")
            )
            new_halted = row["halted"] if halted is None else int(halted)
            new_reason = row["halt_reason"] if halt_reason is None else halt_reason
            new_cooldown = row["consecutive_loss_cooldown_until"]
            if consecutive_loss_cooldown_until is not None:
                new_cooldown = _utc_timestamp(consecutive_loss_cooldown_until)
            connection.execute(
                """
                UPDATE risk_state
                SET peak_account_equity = ?, halted = ?, halt_reason = ?, consecutive_loss_cooldown_until = ?, last_update_time = ?
                WHERE state_id = 1
                """,
                (peak, new_halted, new_reason, new_cooldown, _utc_timestamp()),
            )
            row = connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
            return self._risk_state(row)

    def begin_consecutive_loss_cooldown(self, until: datetime) -> RiskState:
        with self._transaction() as connection:
            row = self._current_risk_state(connection)
            connection.execute(
                """
                UPDATE risk_state
                SET consecutive_losses = 0, consecutive_loss_cooldown_until = ?, last_update_time = ?
                WHERE state_id = 1
                """,
                (_utc_timestamp(until), _utc_timestamp()),
            )
            row = connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
            return self._risk_state(row)

    def begin_daily_loss_halt(self, until: datetime) -> RiskState:
        with self._transaction() as connection:
            self._current_risk_state(connection)
            connection.execute(
                "UPDATE risk_state SET daily_loss_halt_until = ?, last_update_time = ? WHERE state_id = 1",
                (_utc_timestamp(until), _utc_timestamp()),
            )
            row = connection.execute("SELECT * FROM risk_state WHERE state_id = 1").fetchone()
            return self._risk_state(row)

    def _risk_state(self, row: sqlite3.Row) -> RiskState:
        return RiskState(
            peak_account_equity=_decimal(row["peak_account_equity"]),
            day_start_equity=_decimal(row["day_start_equity"]),
            trading_date=date.fromisoformat(row["trading_date"]),
            daily_realized_pnl=Decimal(row["daily_realized_pnl"]),
            daily_loss_halt_until=(
                None
                if row["daily_loss_halt_until"] is None
                else _utc_datetime(row["daily_loss_halt_until"])
            ),
            consecutive_losses=int(row["consecutive_losses"]),
            consecutive_loss_cooldown_until=(
                None
                if row["consecutive_loss_cooldown_until"] is None
                else _utc_datetime(row["consecutive_loss_cooldown_until"])
            ),
            halted=bool(row["halted"]),
            halt_reason=row["halt_reason"],
            last_update_time=_utc_datetime(row["last_update_time"]),
        )
