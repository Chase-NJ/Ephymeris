"""The RHX command client, against a fake RHX on real sockets.

What is pinned here is the part Intan's examples get wrong by omission: a `set`
answers nothing on success, so "sent" and "accepted" look identical unless the
client makes them differ.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.intan.client import (
    RhxCommandClient,
    RhxCommandFailed,
    RhxUnavailable,
    _batches,
    rhx_path,
)
from tests.fake_rhx import FakeRhx


@pytest.fixture
async def rhx():
    fake = await FakeRhx().start()
    yield fake
    await fake.stop()


async def connected(fake: FakeRhx, **kwargs) -> RhxCommandClient:
    client = RhxCommandClient(fake.command_port, reply_timeout_s=0.5, settle_s=0.01, **kwargs)
    await client.connect()
    return client


async def test_a_get_returns_the_value_without_its_envelope(rhx):
    client = await connected(rhx)
    assert await client.get("sampleratehertz") == "30000"
    assert await client.get("type") == "ControllerRecordUSB3"
    await client.close()


async def test_nothing_listening_says_what_to_click():
    client = RhxCommandClient(1)  # nothing listens on port 1
    with pytest.raises(RhxUnavailable, match="Remote TCP Control"):
        await client.connect(timeout_s=0.5)


async def test_a_refused_set_is_an_error_not_a_silence(rhx):
    """The whole reason for the sentinel: RHX says nothing when a set works and
    a sentence when it does not, and a sleep cannot tell those apart."""
    rhx.refuse.add("fileformat")
    client = await connected(rhx)
    with pytest.raises(RhxCommandFailed, match="fileformat"):
        await client.set("fileformat", "OneFilePerChannel")
    # ...and the connection is still usable: the error text was consumed with
    # its own transmission rather than answering the next question.
    assert await client.get("runmode") == "Stop"
    assert client.confirms_writes is True
    await client.close()


async def test_many_sets_travel_as_few_transmissions_and_all_land(rhx):
    client = await connected(rhx)
    await client.send([f"set a-{n:03d}.enabled true" for n in range(64)])
    assert len(rhx.enabled("enabled")) == 64
    # 64 commands + a sentinel per batch, not 64 round trips.
    assert rhx.log.count("get version") < 5
    await client.close()


def test_a_batch_stays_inside_rhx_s_read_buffer():
    batches = _batches([f"set a-{n:03d}.tcpdataoutputenabledspike true" for n in range(128)])
    assert sum(len(b) for b in batches) == 128
    assert all(len(";".join(b).encode()) < 1000 for b in batches)


async def test_an_rhx_that_ignores_batched_gets_degrades_instead_of_failing():
    """The sentinel is an assumption about RHX. If it is wrong, the first write
    discovers it and the client falls back to the examples' discipline -- and
    the commands still land, including the batch that was in flight."""
    fake = await FakeRhx(answers_batched_get=False).start()
    client = await connected(fake)
    await client.send(["set fileformat Traditional", "set savespikedata true"])
    assert client.confirms_writes is False
    assert fake.params["fileformat"] == "Traditional"
    assert fake.params["savespikedata"] == "true"
    # A refusal is still caught in this mode, by the text that follows it.
    fake.refuse.add("note1")
    with pytest.raises(RhxCommandFailed):
        await client.set("note1", "x")
    await client.close()
    await fake.stop()


async def test_verify_catches_a_value_rhx_accepted_and_stored_differently():
    """A path with a space, on an RHX that splits on whitespace: the set is
    ACCEPTED, and the recording would be saved to C:/Hart. Only reading the
    value back can see that, which is why the save location is verified."""
    fake = await FakeRhx(truncate_at_space=True).start()
    client = await connected(fake)
    with pytest.raises(RhxCommandFailed, match="C:/Hart"):
        await client.set("filename.path", rhx_path(r"C:\Hart Lab\data"), verify=True)
    await client.set("filename.path", rhx_path(r"C:\HartLab\data"), verify=True)
    await client.close()
    await fake.stop()


async def test_run_mode_is_waited_for_not_assumed(rhx):
    """The documentation: 'changes do not immediately take effect'."""
    rhx.runmode_delay_s = 0.15
    client = await connected(rhx)
    await client.set_run_mode("record")
    assert rhx.params["runmode"] == "Record"  # true on return, not merely requested
    await client.set_run_mode("stop")
    assert await client.run_mode() == "stop"
    await client.close()


async def test_nothing_rides_behind_a_run_mode_change(rhx):
    """FOUND ON THE REAL RHX. Whatever follows `set runmode run` in the same
    transmission is not answered until acquisition STOPS -- so a sentinel behind
    it timed out ("RHX stopped answering", on every Start All), and its reply
    surfaced a minute later as the answer to something else. The fake used to
    answer at once, which is why nothing here could see it; it now defers the
    way RHX does."""
    client = await connected(rhx)
    await client.set_run_mode("record")
    assert rhx.params["runmode"] == "Record"
    assert "set runmode record" in rhx.log  # sent alone...
    assert rhx.log[rhx.log.index("set runmode record") + 1] == "get runmode"  # ...then polled

    # While running, ordinary confirmed writes still work.
    await client.set("a-000.spikethresholdmicrovolts", -90, verify=True)
    await client.set_run_mode("stop")
    assert await client.get("sampleratehertz") == "30000"  # no stale reply in the way

    # And the mistake cannot be made by accident.
    with pytest.raises(ValueError, match="set_run_mode"):
        await client.send(["set fileformat Traditional", "set runmode run"])
    await client.close()


async def test_the_fake_defers_like_the_real_thing(rhx):
    """The model itself, pinned: a `get` batched behind `set runmode run` is
    answered only after the stop. If this ever passes trivially the test above
    is no longer testing anything."""
    import asyncio

    reader, writer = await asyncio.open_connection("127.0.0.1", rhx.command_port)
    writer.write(b"set runmode run;get version")
    await writer.drain()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(reader.read(100), 0.4)
    writer.write(b"set runmode stop")
    await writer.drain()
    assert b"return: version" in (await asyncio.wait_for(reader.read(100), 1.0)).lower()
    writer.close()


async def test_nameless_replies_are_values_not_names(rhx):
    """`Return: 704383`, not `Return: CurrentTimestamp 704383`. Read as
    name-then-value it came back empty, and `start_recording` could not parse
    an empty string as a sample count."""
    client = await connected(rhx)
    assert await client.get("currenttimestamp") == "-1"
    await client.set_run_mode("run")
    assert int(await client.get("currenttimestamp")) >= 0
    await client.set_run_mode("stop")
    await client.close()


async def test_run_waits_out_an_upload(rhx):
    """RHX aborts `set runmode` while an upload holds the USB bus, silently
    from the point of view of a client that does not look."""
    rhx.params["uploadinprogress"] = "True"
    client = await connected(rhx)
    with pytest.raises(RhxCommandFailed, match="upload"):
        await client.set_run_mode("run", timeout_s=0.3)
    assert rhx.params["runmode"] == "Stop"
    await client.close()


async def test_rhx_vanishing_is_unavailable_not_a_hang(rhx):
    client = await connected(rhx)
    await rhx.die()
    with pytest.raises(RhxUnavailable):
        await client.get("runmode")
    assert not client.connected
