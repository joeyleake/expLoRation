"""SQLite-backed game state for expLoRation."""
from __future__ import annotations
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import GameConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS node_locations (
    node_id   TEXT PRIMARY KEY,
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prev_node_locations (
    node_id   TEXT PRIMARY KEY,
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_flags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT NOT NULL,
    flag_label TEXT NOT NULL,
    set_at     TEXT NOT NULL,
    expires_at TEXT,
    UNIQUE(node_id, flag_label)
);

CREATE TABLE IF NOT EXISTS zone_flags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_label TEXT NOT NULL,
    flag_label TEXT NOT NULL,
    set_at     TEXT NOT NULL,
    expires_at TEXT,
    UNIQUE(zone_label, flag_label)
);

CREATE TABLE IF NOT EXISTS waypoint_flags (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    waypoint_label TEXT NOT NULL,
    flag_label     TEXT NOT NULL,
    set_at         TEXT NOT NULL,
    expires_at     TEXT,
    UNIQUE(waypoint_label, flag_label)
);

CREATE TABLE IF NOT EXISTS event_state (
    event_label       TEXT PRIMARY KEY,
    times_triggered   INTEGER NOT NULL DEFAULT 0,
    last_triggered_at TEXT,
    disabled          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS node_event_state (
    event_label       TEXT NOT NULL,
    node_id           TEXT NOT NULL,
    times_triggered   INTEGER NOT NULL DEFAULT 0,
    last_triggered_at TEXT,
    PRIMARY KEY (event_label, node_id)
);

CREATE TABLE IF NOT EXISTS node_groups (
    group_label TEXT NOT NULL,
    member_id   TEXT NOT NULL,
    added_at    TEXT NOT NULL,
    PRIMARY KEY (group_label, member_id)
);

CREATE TABLE IF NOT EXISTS mutable_variables (
    label      TEXT NOT NULL,
    node_id    TEXT NOT NULL DEFAULT '',
    value_int  INTEGER,
    value_real REAL,
    value_text TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (label, node_id)
);

CREATE TABLE IF NOT EXISTS dynamic_waypoints (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS dynamic_waypoint_flags (
    waypoint_id INTEGER NOT NULL,
    flag_label  TEXT NOT NULL,
    set_at      TEXT NOT NULL,
    expires_at  TEXT,
    PRIMARY KEY (waypoint_id, flag_label)
);

CREATE INDEX IF NOT EXISTS idx_node_flags_label ON node_flags(flag_label);
CREATE INDEX IF NOT EXISTS idx_node_locations_id ON node_locations(node_id);
CREATE INDEX IF NOT EXISTS idx_mutable_variables_label ON mutable_variables(label);
CREATE INDEX IF NOT EXISTS idx_dynamic_waypoint_flags_label ON dynamic_waypoint_flags(flag_label);
"""

_FLAG_TABLE = {
    "node": ("node_flags", "node_id"),
    "zone": ("zone_flags", "zone_label"),
    "waypoint": ("waypoint_flags", "waypoint_label"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_iso(expiry_mins: float | None) -> str | None:
    if expiry_mins is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(minutes=expiry_mins)).isoformat()


class GameState:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            try:
                self._conn.execute("ALTER TABLE event_state ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
                self._conn.commit()
            except Exception:
                pass

    def apply_initial_groups(self, config: "GameConfig") -> None:
        node_id_by_label = {n.label: n.node_id for n in config.nodes}
        for grp in config.groups:
            for member_label in grp.initial_members:
                member = node_id_by_label[member_label] if grp.kind == "node" else member_label
                self.add_to_group(grp.label, member)

    def apply_initial_flags(self, config: "GameConfig") -> None:
        for node in config.nodes:
            flag_map = {f.label: f for f in config.flags}
            for flag_label in node.initial_flags:
                flag_def = flag_map.get(flag_label)
                expiry_mins = flag_def.expiry_mins if flag_def else None
                self.add_flag("node", node.node_id, flag_label, expiry_mins=expiry_mins)

    def init_event_states(self, config: "GameConfig") -> None:
        with self._lock:
            for event in config.events:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO event_state(event_label, times_triggered, last_triggered_at, disabled)
                    VALUES(?, 0, NULL, ?)
                    """,
                    (event.label, int(event.disabled)),
                )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Node locations
    # ------------------------------------------------------------------

    def update_node_location(self, node_id: str, lat: float, lon: float) -> None:
        with self._lock:
            # Copy current position to prev before overwriting
            self._conn.execute(
                """
                INSERT INTO prev_node_locations(node_id, lat, lon, updated_at)
                SELECT node_id, lat, lon, updated_at FROM node_locations WHERE node_id=?
                ON CONFLICT(node_id) DO UPDATE SET
                    lat=excluded.lat, lon=excluded.lon, updated_at=excluded.updated_at
                """,
                (node_id,),
            )
            self._conn.execute(
                """
                INSERT INTO node_locations(node_id, lat, lon, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET lat=excluded.lat, lon=excluded.lon,
                    updated_at=excluded.updated_at
                """,
                (node_id, lat, lon, _now_iso()),
            )
            self._conn.commit()

    def get_node_location_updated_at(self, node_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT updated_at FROM node_locations WHERE node_id=?", (node_id,)
            ).fetchone()
            return row["updated_at"] if row else None

    def get_prev_node_location(self, node_id: str) -> tuple[float, float] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT lat, lon FROM prev_node_locations WHERE node_id=?", (node_id,)
            ).fetchone()
            return (row["lat"], row["lon"]) if row else None

    def get_node_location(self, node_id: str) -> tuple[float, float] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT lat, lon FROM node_locations WHERE node_id=?", (node_id,)
            ).fetchone()
            return (row["lat"], row["lon"]) if row else None

    def get_all_located_nodes(self) -> dict[str, tuple[float, float]]:
        with self._lock:
            rows = self._conn.execute("SELECT node_id, lat, lon FROM node_locations").fetchall()
            return {r["node_id"]: (r["lat"], r["lon"]) for r in rows}

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def add_flag(
        self,
        kind: str,
        target: str,
        flag_label: str,
        expiry_mins: float | None = None,
    ) -> None:
        table, col = _FLAG_TABLE[kind]
        with self._lock:
            self._conn.execute(
                f"""
                INSERT INTO {table}({col}, flag_label, set_at, expires_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT({col}, flag_label) DO UPDATE SET
                    set_at=excluded.set_at, expires_at=excluded.expires_at
                """,
                (target, flag_label, _now_iso(), _expires_iso(expiry_mins)),
            )
            self._conn.commit()

    def remove_flag(self, kind: str, target: str, flag_label: str) -> None:
        table, col = _FLAG_TABLE[kind]
        with self._lock:
            self._conn.execute(
                f"DELETE FROM {table} WHERE {col}=? AND flag_label=?",
                (target, flag_label),
            )
            self._conn.commit()

    def has_flag(self, kind: str, target: str, flag_label: str) -> bool:
        table, col = _FLAG_TABLE[kind]
        now = _now_iso()
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT id, expires_at FROM {table}
                WHERE {col}=? AND flag_label=?
                """,
                (target, flag_label),
            ).fetchone()
            if row is None:
                return False
            if row["expires_at"] is not None and row["expires_at"] <= now:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE {col}=? AND flag_label=?",
                    (target, flag_label),
                )
                self._conn.commit()
                return False
            return True

    def get_flags(self, kind: str, target: str) -> list[str]:
        table, col = _FLAG_TABLE[kind]
        now = _now_iso()
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT flag_label FROM {table}
                WHERE {col}=? AND (expires_at IS NULL OR expires_at > ?)
                """,
                (target, now),
            ).fetchall()
            return [r["flag_label"] for r in rows]

    def get_nodes_with_flag(self, flag_label: str) -> list[str]:
        now = _now_iso()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT node_id FROM node_flags
                WHERE flag_label=? AND (expires_at IS NULL OR expires_at > ?)
                """,
                (flag_label, now),
            ).fetchall()
            return [r["node_id"] for r in rows]

    def expire_flags(self) -> list[tuple[str, str, str]]:
        """Delete expired static flags. Returns [(kind, entity_id, flag_label), ...]."""
        now = _now_iso()
        expired: list[tuple[str, str, str]] = []
        with self._lock:
            for table, kind, col in (
                ("node_flags",     "node",     "node_id"),
                ("zone_flags",     "zone",     "zone_label"),
                ("waypoint_flags", "waypoint", "waypoint_label"),
            ):
                rows = self._conn.execute(
                    f"SELECT {col}, flag_label FROM {table} "
                    f"WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now,),
                ).fetchall()
                if rows:
                    self._conn.execute(
                        f"DELETE FROM {table} WHERE expires_at IS NOT NULL AND expires_at <= ?",
                        (now,),
                    )
                    expired.extend((kind, row[0], row[1]) for row in rows)
            self._conn.commit()
        return expired

    def expire_dynamic_waypoint_flags(self) -> list[tuple[int, str]]:
        """Delete expired flags on live dynamic waypoints.
        Returns [(waypoint_id, flag_label), ...]. Does not touch the waypoints themselves."""
        now = _now_iso()
        expired: list[tuple[int, str]] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT waypoint_id, flag_label FROM dynamic_waypoint_flags "
                "WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            ).fetchall()
            if rows:
                self._conn.execute(
                    "DELETE FROM dynamic_waypoint_flags "
                    "WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now,),
                )
                expired.extend((row[0], row[1]) for row in rows)
                self._conn.commit()
        return expired

    # ------------------------------------------------------------------
    # Mutable variables
    # ------------------------------------------------------------------

    def get_mutable_variable(self, label: str, node_id: str = '') -> int | float | str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_int, value_real, value_text FROM mutable_variables "
                "WHERE label=? AND node_id=?",
                (label, node_id),
            ).fetchone()
            if row is None:
                return None
            if row["value_int"] is not None:
                return row["value_int"]
            if row["value_real"] is not None:
                return row["value_real"]
            return row["value_text"]

    def set_mutable_variable(self, label: str, value: int | float | str, node_id: str = '') -> None:
        vi = value if isinstance(value, int) and not isinstance(value, bool) else None
        vr = value if isinstance(value, float) else None
        vt = value if isinstance(value, str) else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO mutable_variables(label, node_id, value_int, value_real, value_text, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(label, node_id) DO UPDATE SET
                    value_int=excluded.value_int, value_real=excluded.value_real,
                    value_text=excluded.value_text, updated_at=excluded.updated_at
                """,
                (label, node_id, vi, vr, vt, _now_iso()),
            )
            self._conn.commit()

    def init_mutable_variables(self, config: "GameConfig") -> None:
        with self._lock:
            for mv in config.mutable_variables:
                value = mv.initial
                vi = value if isinstance(value, int) and not isinstance(value, bool) else None
                vr = value if isinstance(value, float) else None
                vt = value if isinstance(value, str) else None
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO mutable_variables
                        (label, node_id, value_int, value_real, value_text, updated_at)
                    VALUES(?, '', ?, ?, ?, ?)
                    """,
                    (mv.label, vi, vr, vt, _now_iso()),
                )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def add_to_group(self, group_label: str, member_id: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO node_groups(group_label, member_id, added_at)
                VALUES(?, ?, ?)
                ON CONFLICT(group_label, member_id) DO UPDATE SET added_at=excluded.added_at
                """,
                (group_label, member_id, _now_iso()),
            )
            self._conn.commit()

    def remove_from_group(self, group_label: str, member_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM node_groups WHERE group_label=? AND member_id=?",
                (group_label, member_id),
            )
            self._conn.commit()

    def is_in_group(self, group_label: str, member_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM node_groups WHERE group_label=? AND member_id=?",
                (group_label, member_id),
            ).fetchone()
            return row is not None

    def get_group_members(self, group_label: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT member_id FROM node_groups WHERE group_label=?",
                (group_label,),
            ).fetchall()
            return [r["member_id"] for r in rows]

    # ------------------------------------------------------------------
    # Event state
    # ------------------------------------------------------------------

    def get_event_state(self, event_label: str) -> tuple[int, datetime | None]:
        with self._lock:
            row = self._conn.execute(
                "SELECT times_triggered, last_triggered_at FROM event_state WHERE event_label=?",
                (event_label,),
            ).fetchone()
            if row is None:
                return 0, None
            last = datetime.fromisoformat(row["last_triggered_at"]) if row["last_triggered_at"] else None
            return row["times_triggered"], last

    def increment_event_triggers(self, event_label: str) -> None:
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO event_state(event_label, times_triggered, last_triggered_at)
                VALUES(?, 1, ?)
                ON CONFLICT(event_label) DO UPDATE SET
                    times_triggered = times_triggered + 1,
                    last_triggered_at = excluded.last_triggered_at
                """,
                (event_label, now),
            )
            self._conn.commit()

    def set_event_triggers(self, event_label: str, value: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO event_state(event_label, times_triggered, last_triggered_at)
                VALUES(?, ?, NULL)
                ON CONFLICT(event_label) DO UPDATE SET
                    times_triggered = excluded.times_triggered
                """,
                (event_label, value),
            )
            self._conn.commit()

    def is_event_disabled(self, event_label: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT disabled FROM event_state WHERE event_label=?", (event_label,)
            ).fetchone()
            return bool(row["disabled"]) if row else False

    def get_node_event_state(self, event_label: str, node_id: str) -> tuple[int, datetime | None]:
        with self._lock:
            row = self._conn.execute(
                "SELECT times_triggered, last_triggered_at FROM node_event_state WHERE event_label=? AND node_id=?",
                (event_label, node_id),
            ).fetchone()
            if row is None:
                return 0, None
            last = datetime.fromisoformat(row["last_triggered_at"]) if row["last_triggered_at"] else None
            return row["times_triggered"], last

    def increment_node_event_triggers(self, event_label: str, node_id: str) -> None:
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO node_event_state(event_label, node_id, times_triggered, last_triggered_at)
                VALUES(?, ?, 1, ?)
                ON CONFLICT(event_label, node_id) DO UPDATE SET
                    times_triggered = times_triggered + 1,
                    last_triggered_at = excluded.last_triggered_at
                """,
                (event_label, node_id, now),
            )
            self._conn.commit()

    def set_event_disabled(self, event_label: str, disabled: bool) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO event_state(event_label, times_triggered, last_triggered_at, disabled)
                VALUES(?, 0, NULL, ?)
                ON CONFLICT(event_label) DO UPDATE SET disabled = excluded.disabled
                """,
                (event_label, int(disabled)),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Dynamic waypoints
    # ------------------------------------------------------------------

    def get_dynamic_waypoint_location(self, waypoint_id: int) -> tuple[float, float] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT lat, lon FROM dynamic_waypoints WHERE id=?", (waypoint_id,)
            ).fetchone()
            return (row["lat"], row["lon"]) if row else None

    def create_dynamic_waypoint(self, lat: float, lon: float, expiry_mins: float | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO dynamic_waypoints(lat, lon, created_at, expires_at) VALUES(?, ?, ?, ?)",
                (lat, lon, _now_iso(), _expires_iso(expiry_mins)),
            )
            self._conn.commit()
            return cur.lastrowid

    def add_dynamic_waypoint_flag(self, waypoint_id: int, flag_label: str, expiry_mins: float | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO dynamic_waypoint_flags(waypoint_id, flag_label, set_at, expires_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(waypoint_id, flag_label) DO UPDATE SET
                    set_at=excluded.set_at, expires_at=excluded.expires_at
                """,
                (waypoint_id, flag_label, _now_iso(), _expires_iso(expiry_mins)),
            )
            self._conn.commit()

    def remove_dynamic_waypoint_flag(self, waypoint_id: int, flag_label: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM dynamic_waypoint_flags WHERE waypoint_id=? AND flag_label=?",
                (waypoint_id, flag_label),
            )
            self._conn.commit()

    def has_dynamic_waypoint_flag(self, waypoint_id: int, flag_label: str) -> bool:
        now = _now_iso()
        with self._lock:
            row = self._conn.execute(
                "SELECT expires_at FROM dynamic_waypoint_flags WHERE waypoint_id=? AND flag_label=?",
                (waypoint_id, flag_label),
            ).fetchone()
            if row is None:
                return False
            if row["expires_at"] is not None and row["expires_at"] <= now:
                self._conn.execute(
                    "DELETE FROM dynamic_waypoint_flags WHERE waypoint_id=? AND flag_label=?",
                    (waypoint_id, flag_label),
                )
                self._conn.commit()
                return False
            return True

    def get_dynamic_waypoints_with_flag(self, flag_label: str) -> list[tuple[int, float, float]]:
        now = _now_iso()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT dw.id, dw.lat, dw.lon
                FROM dynamic_waypoints dw
                JOIN dynamic_waypoint_flags dwf ON dwf.waypoint_id = dw.id
                WHERE dwf.flag_label = ?
                  AND (dw.expires_at IS NULL OR dw.expires_at > ?)
                  AND (dwf.expires_at IS NULL OR dwf.expires_at > ?)
                """,
                (flag_label, now, now),
            ).fetchall()
            return [(r["id"], r["lat"], r["lon"]) for r in rows]

    def destroy_dynamic_waypoint(self, waypoint_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM dynamic_waypoint_flags WHERE waypoint_id=?", (waypoint_id,)
            )
            self._conn.execute(
                "DELETE FROM dynamic_waypoints WHERE id=?", (waypoint_id,)
            )
            self._conn.commit()

    def expire_dynamic_waypoints(self) -> list[tuple[int, frozenset[str]]]:
        """Delete expired dynamic waypoints and their flags.
        Returns [(waypoint_id, frozenset_of_flag_labels), ...] per deleted waypoint.
        Flag labels are captured before deletion for had_flag trigger filtering only —
        no flag_expired events fire for cascade-deleted flags."""
        now = _now_iso()
        expired: list[tuple[int, frozenset[str]]] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM dynamic_waypoints WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            ).fetchall()
            for row in rows:
                wp_id = row["id"]
                flag_rows = self._conn.execute(
                    "SELECT flag_label FROM dynamic_waypoint_flags WHERE waypoint_id=?",
                    (wp_id,),
                ).fetchall()
                flags = frozenset(r["flag_label"] for r in flag_rows)
                self._conn.execute(
                    "DELETE FROM dynamic_waypoint_flags WHERE waypoint_id=?", (wp_id,))
                self._conn.execute(
                    "DELETE FROM dynamic_waypoints WHERE id=?", (wp_id,))
                expired.append((wp_id, flags))
            if expired:
                self._conn.commit()
        return expired

    def get_dynamic_waypoint_count(self) -> int:
        now = _now_iso()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM dynamic_waypoints WHERE expires_at IS NULL OR expires_at > ?",
                (now,),
            ).fetchone()
            return row["cnt"] if row else 0
