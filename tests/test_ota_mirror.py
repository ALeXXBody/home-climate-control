"""Verified-pair OTA delivery (full rewrite of the LAN mirror).

Contract under test: the hub never serves an image+signature pair it has
not proven in the same pass — catalog sha256 + exact size, then the
board's own ECDSA check over the exact bytes. Every failure purges the
local files and hands the board the original release URL.
"""

from __future__ import annotations

import asyncio
import hashlib as _hl
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from custom_components.home_climate_control import firmware_manager as fm
from custom_components.home_climate_control.firmware_manager import (
    FirmwareManager,
    HcsDevice,
)

# A dedicated ECDSA keypair for tests; the production key is pinned in
# firmware_manager and never needed here.
_TEST_SK = ec.generate_private_key(ec.SECP256R1())
_TEST_KEY_PEM = _TEST_SK.public_key().public_bytes(
    encoding=__import__(
        "cryptography.hazmat.primitives.serialization",
        fromlist=["serialization"],
    ).Encoding.PEM,
    format=__import__(
        "cryptography.hazmat.primitives.serialization",
        fromlist=["serialization"],
    ).PublicFormat.SubjectPublicKeyInfo,
).decode()


def _sign(image: bytes) -> bytes:
    sig = _TEST_SK.sign(image, ec.ECDSA(hashes.SHA256()))
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
    )

    r, s = decode_dss_signature(sig)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


IMG = b"x" * 70000
GOOD_SHA = _hl.sha256(IMG).hexdigest()

GH = (
    "https://github.com/ALeXXBody/home-climate-system/releases/download/"
    "v1.1.1/firmware-d1_mini.bin"
)
GHS = GH + ".sig"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(FirmwareManager, "MIRROR_DIR", tmp_path)
    monkeypatch.setattr(fm.FirmwareManager, "OTA_PUBLIC_KEY_PEM", _TEST_KEY_PEM)
    hass = MagicMock()
    m = FirmwareManager(hass)
    m.catalog = [
        {
            "board": "d1_mini",
            "version": "1.1.1",
            "size": "70000",
            "sha256": GOOD_SHA,
            "url": GH,
        },
    ]
    return m, tmp_path


def _fake_session(image: bytes, sig: bytes, calls: list):
    class _Content:
        def __init__(self, body):
            self._body = body

        async def read(self, n=-1):
            return self._body if n < 0 else self._body[:n]

    class _Resp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        @property
        def content(self):
            return _Content(self._body)

    class _CM:
        def __init__(self, body):
            self._body = body

        async def __aenter__(self):
            return _Resp(self._body)

        async def __aexit__(self, *a):
            return False

    class _Sess:
        def get(self, url):
            calls.append(url)
            return _CM(sig if url.endswith(".sig") else image)

    return _Sess()


# ----------------------------------------------------------------- pass-through

def test_non_release_urls_pass_through(env):
    m, _ = env
    assert asyncio.run(m._async_ota_url("http://lan/fw.bin")) == "http://lan/fw.bin"


# ----------------------------------------------------------------- happy path

def test_verified_pair_is_served_and_written(env, monkeypatch):
    """A proven pair is atomically placed and the LAN mirror URL returned."""
    m, tmp = env
    # Pre-existing stale files must be replaced wholesale.
    (tmp / "firmware-d1_mini.bin").write_bytes(b"stale-image")
    (tmp / "firmware-d1_mini.bin.sig").write_bytes(b"z" * 64)
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, _sign(IMG), calls),
    )
    url = asyncio.run(m._async_ota_url(GH))
    assert calls == [GH, GHS]
    assert (tmp / "firmware-d1_mini.bin").read_bytes() == IMG
    # ECDSA is randomised — assert the stored signature VERIFIES over the
    # stored image with the test key rather than comparing bytes.
    stored_sig = (tmp / "firmware-d1_mini.bin.sig").read_bytes()
    _TEST_SK.public_key().verify(
        encode_dss_signature(
            int.from_bytes(stored_sig[:32], "big"),
            int.from_bytes(stored_sig[32:], "big"),
        ),
        IMG,
        ec.ECDSA(hashes.SHA256()),
    )
    assert url.endswith("/home_climate_control_static/firmware/firmware-d1_mini.bin")


def test_stateless_every_flash_redownloads(env, monkeypatch):
    """No staleness heuristics: a second flash re-verifies from source."""
    m, tmp = env
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, _sign(IMG), calls),
    )
    asyncio.run(m._async_ota_url(GH))
    asyncio.run(m._async_ota_url(GH))
    assert calls.count(GH) == 2 and calls.count(GHS) == 2


def test_trigger_publishes_mirrored_url(env, monkeypatch):
    """End-to-end: flash command must hand the board the LAN mirror URL."""
    from homeassistant.components import mqtt

    m, _ = env
    dev = HcsDevice(node_id="hcs-x", board="d1_mini")
    m.devices["hcs-x"] = dev
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, _sign(IMG), calls),
    )
    res = asyncio.run(m.async_trigger_ota("hcs-x", GH, target_version="1.1.1"))
    assert res["ok"] is True
    args = mqtt.async_publish.call_args[0]
    assert "/home_climate_control_static/firmware/firmware-d1_mini.bin" in args[2]
    assert dev.ota_target_version == "1.1.1"


# ------------------------------------------------- no-mirror failure modes

def test_digest_mismatch_purges_and_serves_source(env, monkeypatch):
    m, tmp = env
    (tmp / "firmware-d1_mini.bin").write_bytes(b"keep" * 1000)
    (tmp / "firmware-d1_mini.bin.sig").write_bytes(b"keep-sig" * 8)
    offered = b"E" * 70000
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(offered, _sign(offered), calls),
    )
    url = asyncio.run(m._async_ota_url(GH))
    # digest fails although the ECDSA sig matches the offered bytes —
    # catalog wins; nothing unverifiable survives on disk.
    assert calls == [GH]
    assert not (tmp / "firmware-d1_mini.bin").exists()
    assert not (tmp / "firmware-d1_mini.bin.sig").exists()
    assert url == GH


def test_bad_signature_purges_and_serves_source(env, monkeypatch):
    """Digest OK but the signature does not verify — the board would
    reject it; the hub must reject it first."""
    m, tmp = env
    other = _sign(b"totally different firmware")
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, other, calls),
    )
    url = asyncio.run(m._async_ota_url(GH))
    assert calls == [GH, GHS]
    assert not (tmp / "firmware-d1_mini.bin").exists()
    assert not (tmp / "firmware-d1_mini.bin.sig").exists()
    assert url == GH


def test_no_catalog_digest_purges_and_serves_source(env, monkeypatch):
    m, tmp = env
    m.catalog[0]["sha256"] = ""
    (tmp / "firmware-d1_mini.bin").write_bytes(b"old")
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, _sign(IMG), calls),
    )
    url = asyncio.run(m._async_ota_url(GH))
    assert calls == []  # nothing is even downloaded
    assert not (tmp / "firmware-d1_mini.bin").exists()
    assert url == GH


def test_unknown_board_purges_nothing_but_serves_source(env, tmp_path):
    m = env[0]
    url = asyncio.run(m._async_ota_url(
        "https://github.com/ALeXXBody/home-climate-system/releases/download/"
        "v1.1.1/firmware-esp32_d1_mini.bin"
    ))
    assert url.endswith("firmware-esp32_d1_mini.bin")


def test_size_mismatch_rejected(env, monkeypatch):
    """Exact size enforcement: partial downloads can't masquerade."""
    m, tmp = env
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(b"x" * 6999, _sign(b"x" * 6999), calls),
    )
    url = asyncio.run(m._async_ota_url(GH))
    assert not (tmp / "firmware-d1_mini.bin").exists()
    assert url == GH


def test_truncated_signature_rejected(env, monkeypatch):
    m, tmp = env
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, b"\x00" * 63, calls),
    )
    url = asyncio.run(m._async_ota_url(GH))
    assert not (tmp / "firmware-d1_mini.bin").exists()
    assert url == GH


def test_download_failure_purges_and_serves_source(env, monkeypatch):
    m, tmp = env
    (tmp / "firmware-d1_mini.bin").write_bytes(b"keep")

    class _Boom:
        def get(self, url):
            raise TimeoutError()

    monkeypatch.setattr(fm, "async_get_clientsession", lambda h: _Boom())
    url = asyncio.run(m._async_ota_url(GH))
    assert not (tmp / "firmware-d1_mini.bin").exists()
    assert url == GH


# ------------------------------------------------- LAN URL construction

def test_no_request_context_still_mirrors(env, monkeypatch):
    """Regression (v1.0.31 live finding): WS-triggered flashes have no HTTP
    request context; the base must still be built toward the device."""
    from homeassistant.helpers import network as ha_network

    m, _ = env
    dev = HcsDevice(node_id="hcs-x", board="d1_mini")
    dev.online = True
    dev.ip = "192.168.50.153"
    m.devices["hcs-x"] = dev
    calls = []
    monkeypatch.setattr(
        fm, "async_get_clientsession",
        lambda h: _fake_session(IMG, _sign(IMG), calls),
    )

    def _boom(*a, **k):
        raise RuntimeError("NoURLAvailableError stand-in")

    m.hass.config.api.port = 8123

    async def _exec(fn, *a, **k):
        return fn(*a, **k)

    m.hass.async_add_executor_job = _exec
    monkeypatch.setattr(ha_network, "get_url", _boom)
    monkeypatch.setattr(
        FirmwareManager, "_lan_source_ip", staticmethod(lambda ip: "192.168.50.200")
    )
    url = asyncio.run(m._async_ota_url(GH))
    assert url == (
        "http://192.168.50.200:8123/home_climate_control_static/firmware/firmware-d1_mini.bin"
    ), url
