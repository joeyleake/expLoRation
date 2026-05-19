"""Shared fixtures for expLoRation tests."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from state import GameState
from engine import Engine
from config import (
    GameConfig, Channel, Zone, Waypoint, Message, FlagDef, NodeDef,
    GroupDef, MutableVariableDef, Variable, Event,
)


@pytest.fixture
def db(tmp_path):
    gs = GameState(str(tmp_path / "test.db"))
    gs.init_schema()
    return gs


@pytest.fixture
def tmp_yaml(tmp_path):
    def _write(content: str) -> str:
        p = tmp_path / "game.yaml"
        p.write_text(textwrap.dedent(content))
        return str(p)
    return _write


def _make_mock_interface():
    iface = MagicMock()
    iface.nodes = {}
    return iface


def make_engine(config: GameConfig, db: GameState, channel_map: dict | None = None) -> Engine:
    """Build an Engine with a mock interface; patch send methods to capture output."""
    eng = Engine(config, db, _make_mock_interface(), send_delay=0)
    eng.channel_index_map = channel_map or {}

    sent_dms: list[tuple[str, str]] = []
    sent_channels: list[tuple[str, str]] = []
    # Respect _suppress_messages so seed_node_location silences messages correctly
    eng._send_dm = lambda node_id, text: (None if eng._suppress_messages else sent_dms.append((node_id, text)))
    eng._send_channel = lambda ch, text: (None if eng._suppress_messages else sent_channels.append((ch, text)))
    eng.sent_dms = sent_dms
    eng.sent_channels = sent_channels
    return eng


# ---------------------------------------------------------------------------
# Reusable geographic constants
# ---------------------------------------------------------------------------

# Triangle in south Puget Sound area — easy to reason about
ZONE_POINTS = [
    (47.000, -122.000),
    (47.010, -122.000),
    (47.000, -122.010),
]
INSIDE_ZONE = (47.003, -122.003)   # near centroid, clearly inside
OUTSIDE_ZONE = (47.020, -121.900)  # clearly outside

NODE_ID = "!aabbccdd"
NODE2_ID = "!11223344"


def minimal_config(**overrides) -> GameConfig:
    """A GameConfig with one zone, one node, standard flags and messages."""
    cfg = GameConfig(
        channels=[Channel(label="main", name="LongFast", psk="AQ==", monitor=True, participate=True)],
        zones=[Zone(label="zone_a", points=list(ZONE_POINTS))],
        waypoints=[Waypoint(label="wp_a", lat=47.005, lon=-122.005)],
        messages=[
            Message(label="hello", text="Hello world"),
            Message(label="greet_node", text="Hi {node_id}"),
            Message(label="greet_zone", text="Zone: {zone}"),
        ],
        flags=[FlagDef(label="active"), FlagDef(label="scored")],
        nodes=[NodeDef(label="node_a", node_id=NODE_ID, initial_flags=[])],
        groups=[GroupDef(label="players", kind="node")],
        mutable_variables=[
            MutableVariableDef(label="score", type="integer", scope="global", initial=0),
        ],
        variables=[
            Variable(label="active_count", scope="global", tracks="flag_count", target="active"),
        ],
        events=[],
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg
