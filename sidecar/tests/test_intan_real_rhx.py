"""The questions only a REAL Intan RHX can answer (`RECORDING.md#not-yet-verified`).

Opt-in, and doubly so: it needs `EPHYMERIS_REAL_RHX=1` AND RHX's command server
free on 127.0.0.1:5000. RHX accepts ONE command client, so Ephymeris itself
must be closed (or disconnected on the Recording tab) while this runs:

    set EPHYMERIS_REAL_RHX=1
    pytest tests/test_intan_real_rhx.py -v -s

It is polite: RHX must be stopped (it refuses to run otherwise rather than
interrupt a recording), it starts acquisition only in `run` mode -- never
`record`, so nothing is written to disk -- and every value it changes is put
back. Each test PRINTS its finding; the ones whose bad answer the integration
already handles pass either way, and say which way it went.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from ephymeris_sidecar.intan.client import RhxCommandClient, RhxCommandFailed, RhxError
from ephymeris_sidecar.intan.streams import SpikeParser

pytestmark = pytest.mark.skipif(
    os.environ.get("EPHYMERIS_REAL_RHX") != "1",
    reason="set EPHYMERIS_REAL_RHX=1 with RHX's command server free to run against the real thing",
)

PORT = int(os.environ.get("EPHYMERIS_RHX_PORT", "5000"))


async def first_channel(client: RhxCommandClient) -> str:
    for letter in "abcdefgh":
        try:
            if int(await client.get(f"{letter}.numberamplifierchannels")) > 0:
                return f"{letter}-000"
        except (RhxError, ValueError):
            break
    raise RuntimeError("no headstage (real or synthetic) on any port")


async def probe_identity(rhx):
    for name in ("version", "type", "sampleratehertz", "synthetic", "headstagepresent"):
        print(f"\n  {name:18s} = {await rhx.get(name)!r}")


async def probe_does_a_get_that_rides_a_batch_get_answered(rhx):
    """HANDLED either way: False means the client fell back to one command per
    transmission and refused `set`s go undetected (values are still read back)."""
    await rhx.send(["set note1 ephymeris-probe"])
    print(f"\n  confirms writes (sentinel works): {rhx.confirms_writes}")
    assert await rhx.get("note1") == "ephymeris-probe"
    await rhx.set("note1", "-")


async def probe_is_a_refused_set_reported_as_text(rhx):
    try:
        await rhx.send(["set thisparameterdoesnotexist 1"])
        print("\n  a bogus `set` was NOT reported -- refusals are silent on this RHX")
    except RhxCommandFailed as exc:
        print(f"\n  a bogus `set` is reported: {exc.reply.strip()!r}")


async def probe_does_the_save_path_keep_a_space(rhx):
    """HANDLED either way -- `intan.configure` refuses a truncated path. The
    lab's data directory has a space in it, so this decides whether recordings
    can live beside the behavior data."""
    original = await rhx.get("filename.path")
    wanted = "C:/Users/Public/Ephymeris Probe/ephys"
    try:
        await rhx.send([f"set filename.path {wanted}"])
        stored = await rhx.get("filename.path")
        print(f"\n  asked for {wanted!r}\n  RHX kept  {stored!r}\n  -> spaces {'SURVIVE' if stored == wanted else 'ARE LOST'}")
    finally:
        if original:
            await rhx.send([f"set filename.path {original}"])


#: How long each batching setting streams spikes for, and how many channels.
LATENCY_RUN_S = 6.0
LATENCY_CHANNELS = 16


async def _spike_lags(rhx, rate: float, arrivals: list[tuple[float, int]]) -> list[float]:
    """Run for `LATENCY_RUN_S` and return each spike's lag in ms: when it
    reached us, less when RHX itself had that sample.

    `arrivals` is filled by a reader on the spike socket, which stays open
    across runs: RHX 3.5.0 puts the socket back to *Disconnected* when its
    client leaves, so a socket per run gets spikes on the first run only.

    RHX's clock is read with `get currenttimestamp` every 50 ms. Each reply
    bounds the offset between our monotonic clock and its sample clock from
    above (the sample was in RHX's hands no later than the reply), so the
    SMALLEST bound seen is the tightest. The lag is therefore measured from
    RHX having the sample -- what RHX's own displays start from -- and leaves
    out the USB transfer before it, which no client can see or shorten.
    """
    loop = asyncio.get_running_loop()
    bounds: list[float] = []
    arrivals.clear()
    await rhx.set_run_mode("run")
    try:
        end = loop.time() + LATENCY_RUN_S
        while loop.time() < end:
            stamp = int(await rhx.get("currenttimestamp"))
            bounds.append(loop.time() - stamp / rate)
            await asyncio.sleep(0.05)
    finally:
        await rhx.set_run_mode("stop")
    await asyncio.sleep(0.2)  # the last write's spikes
    offset = min(bounds)
    return sorted((t - (stamp / rate + offset)) * 1000 for t, stamp in arrivals)


async def probe_how_late_do_spikes_arrive(rhx):
    """Decides whether a live firing map can feel real-time. RHX writes to
    TCP every `TCPNumberDataBlocksPerWrite` blocks of 128 samples (default 10:
    43 ms at 30 kS/s); fewer means sooner. Measured at several settings."""
    rate = float(await rhx.get("sampleratehertz"))
    channel = await first_channel(rhx)
    port = channel.split("-")[0]
    channels = [f"{port}-{n:03d}" for n in range(LATENCY_CHANNELS)]
    original = await rhx.get("tcpnumberdatablocksperwrite")
    status = await rhx.get("tcpspikedatasocket.status")
    spike_port = int(await rhx.get("tcpspikedatasocket.port"))
    if status.lower() == "disconnected":
        await rhx.set("tcpspikedatasocket.status", "Pending")
    loop = asyncio.get_running_loop()
    reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", spike_port), 2.0)
    arrivals: list[tuple[float, int]] = []

    async def read() -> None:
        parser = SpikeParser()
        while data := await reader.read(1 << 16):
            now = loop.time()
            arrivals.extend((now, spike.timestamp) for spike in parser.feed(data))

    reading = asyncio.create_task(read())
    print(f"\n  {rate:.0f} S/s, {len(channels)} channels on port {port.upper()}, default batch {original}")
    try:
        await rhx.send([f"set {name}.tcpdataoutputenabledspike true" for name in channels])
        for blocks in (10, 4, 2, 1):
            await rhx.set("tcpnumberdatablocksperwrite", blocks, verify=True)
            lags = await _spike_lags(rhx, rate, arrivals)
            if not lags:
                print(f"  {blocks:>3} blocks/write: no spikes arrived (check thresholds)")
                continue
            pick = lambda q: lags[min(len(lags) - 1, int(q * len(lags)))]  # noqa: E731
            print(
                f"  {blocks:>3} blocks/write ({blocks * 128 / rate * 1000:5.1f} ms): "
                f"{len(lags):6d} spikes, lag p50 {pick(0.5):6.1f}  p95 {pick(0.95):6.1f}  "
                f"max {lags[-1]:6.1f} ms"
            )
    finally:
        reading.cancel()
        writer.close()
        await rhx.send(
            [f"set {name}.tcpdataoutputenabledspike false" for name in channels]
            + [f"set tcpnumberdatablocksperwrite {original}"]
        )


async def probe_does_rhx_measure_and_save_impedances(rhx):
    """`RECORDING.md#impedance-tracking`: the parameter names, that the
    sentinel answers only once `MeasureImpedance` is done, and the CSV's
    shape. Writes one CSV to a temporary folder; puts every value back."""
    import tempfile
    import time
    from pathlib import Path

    from ephymeris_sidecar.intan.client import rhx_path
    from ephymeris_sidecar.intan.impedance import parse_csv

    saved = {k: await rhx.get(k) for k in (
        "desiredimpedancefreqhertz", "impedancefilename.path", "impedancefilename.basefilename")}
    folder = Path(tempfile.mkdtemp(prefix="ephymeris-impedance-"))
    try:
        await rhx.set("desiredimpedancefreqhertz", 1000)
        await rhx.set("impedancefilename.path", rhx_path(str(folder)), verify=True)
        await rhx.set("impedancefilename.basefilename", "probe", verify=True)
        began = time.monotonic()
        await rhx.execute("measureimpedance", timeout_s=180)
        took = time.monotonic() - began
        await rhx.execute("saveimpedance")
        path = folder / "probe.csv"
        print(f"\n  MeasureImpedance answered after {took:.1f} s; CSV written: {path.is_file()}")
        print(f"  actual frequency: {await rhx.get('actualimpedancefreqhertz')} Hz")
        reading = parse_csv(path.read_text(encoding="utf-8"))
        first = reading.sites[0] if reading.sites else None
        print(f"  {len(reading.sites)} sites at {reading.frequency_hz:g} Hz; first {first}")
    finally:
        await rhx.send([f"set {k} {v}" for k, v in saved.items() if v])


async def probe_how_are_digital_inputs_named(rhx):
    for name in ("digital-in-01", "digital-in-1", "digital-in-00"):
        try:
            print(f"\n  {name:14s} -> enabled={await rhx.get(name + '.enabled')}")
        except RhxError as exc:
            print(f"\n  {name:14s} -> not a channel here ({str(exc)[:60]})")


PROBES = (
    probe_identity,
    probe_does_a_get_that_rides_a_batch_get_answered,
    probe_is_a_refused_set_reported_as_text,
    probe_does_the_save_path_keep_a_space,
    probe_how_are_digital_inputs_named,
    probe_how_late_do_spikes_arrive,
    probe_does_rhx_measure_and_save_impedances,
)


async def test_everything_over_one_connection():
    """ONE connection for every probe, and that is a finding in itself: RHX's
    command server returns to *Disconnected* the moment its client leaves, so a
    connection per test gets exactly one test before someone has to press
    Connect in RHX again. A probe that fails is reported and the rest still run.
    """
    client = RhxCommandClient(PORT)
    try:
        await client.connect()
    except RhxError as exc:
        pytest.skip(f"RHX's command server is not free: {exc}")
    failures: list[str] = []
    try:
        if await client.run_mode() != "stop":
            pytest.skip("RHX is running; stop it first -- this will not interrupt it")
        for probe in PROBES:
            print(f"\n--- {probe.__name__.removeprefix('probe_').replace('_', ' ')}")
            try:
                await probe(client)
            except Exception as exc:  # noqa: BLE001 - report and carry on
                print(f"\n  PROBE FAILED: {type(exc).__name__}: {exc}")
                failures.append(probe.__name__)
    finally:
        try:
            if client.connected and await client.run_mode() != "stop":
                await client.set_run_mode("stop")
        finally:
            await client.close()
    assert not failures, failures
