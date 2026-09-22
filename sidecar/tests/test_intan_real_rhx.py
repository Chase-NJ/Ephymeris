"""The questions only a REAL Intan RHX can answer (`recording.md` §8).

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


async def probe_can_a_threshold_and_a_tcp_output_change_while_running(rhx):
    """NOT handled if the answer is no: a SpikeScope opened mid-recording would
    wait forever (fix: enable the band at configure time), and the threshold
    drag would be refused by its read-back."""
    channel = await first_channel(rhx)
    threshold = await rhx.get(f"{channel}.spikethresholdmicrovolts")
    await rhx.set_run_mode("run")
    try:
        await asyncio.sleep(0.5)
        print(f"\n  currenttimestamp while running: {await rhx.get('currenttimestamp')}")

        await rhx.send([f"set {channel}.tcpdataoutputenabledhigh true"])
        took = (await rhx.get(f"{channel}.tcpdataoutputenabledhigh")).lower() == "true"
        print(f"  TCP highpass output changed while running: {took}")

        probe = -123 if threshold.strip() != "-123" else -124
        await rhx.send([f"set {channel}.spikethresholdmicrovolts {probe}"])
        moved = (await rhx.get(f"{channel}.spikethresholdmicrovolts")).strip() == str(probe)
        print(f"  spike threshold changed while running:     {moved}")
    finally:
        await rhx.set_run_mode("stop")
        await rhx.send(
            [
                f"set {channel}.tcpdataoutputenabledhigh false",
                f"set {channel}.spikethresholdmicrovolts {threshold}",
            ]
        )


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
    probe_can_a_threshold_and_a_tcp_output_change_while_running,
    probe_how_are_digital_inputs_named,
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
