"""A fake Intan RHX: the three TCP servers, speaking the documented protocol.

Not a mock of our client -- a stand-in for the OTHER END, so the client, the
service and the stream parsers are exercised through real sockets. It models
the behaviours the integration has to survive, each switchable:

  * `set`/`execute` answer nothing on success and a sentence on failure;
  * `runmode` takes effect a moment AFTER it is set;
  * a transmission is `;`-separated commands, answered in order;
  * `answers_batched_get=False` is an RHX that ignores a `get` riding a batch,
    which is the case the client's fallback discipline exists for;
  * `truncate_at_space` stores a value cut at its first space -- what a
    whitespace-splitting parser does to "C:/Hart Lab/data".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class FakeRhx:
    answers_batched_get: bool = True
    truncate_at_space: bool = False
    runmode_delay_s: float = 0.05
    #: OBSERVED ON THE REAL RHX, and on by default because it is how RHX
    #: behaves: whatever follows a `set runmode run|record` in the SAME
    #: transmission is not processed until acquisition stops. RHX enters its
    #: run loop from inside the batch and finishes the batch on the way out.
    defers_batch_behind_runmode: bool = True
    #: The socket stays open and nothing is answered -- a wedged RHX, or a
    #: half-open connection. The harder of the two ways to lose the link,
    #: because nothing about the socket says so.
    silent: bool = False
    refuse: set[str] = field(default_factory=set)

    params: dict[str, str] = field(default_factory=dict)
    executed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    command_port: int = 0
    waveform_port: int = 0
    spike_port: int = 0

    def __post_init__(self) -> None:
        self.params = {
            "runmode": "Stop",
            "version": "3.5.0",
            "type": "ControllerRecordUSB3",
            "sampleratehertz": "30000",
            "uploadinprogress": "False",
            "headstagepresent": "True",
            "synthetic": "True",
            "playback": "False",
            "currenttimestamp": "-1",
            "filename.activefiletimestamp": "RecordingNotStarted",
            "tcpwaveformdatasocket.status": "Disconnected",
            "tcpspikedatasocket.status": "Disconnected",
            "a.numberamplifierchannels": "32",
            "b.numberamplifierchannels": "0",
            "c.numberamplifierchannels": "0",
            "d.numberamplifierchannels": "0",
            **self.params,
        }
        self._servers: list[asyncio.base_events.Server] = []
        self._waveform: asyncio.StreamWriter | None = None
        self._spike: asyncio.StreamWriter | None = None
        self._clients: list[asyncio.StreamWriter] = []
        self._tasks: set[asyncio.Task] = set()
        self._deferred: list[tuple[asyncio.StreamWriter, list[str]]] = []

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> "FakeRhx":
        command = await asyncio.start_server(self._on_command, "127.0.0.1", 0)
        waveform = await asyncio.start_server(self._on_waveform, "127.0.0.1", 0)
        spike = await asyncio.start_server(self._on_spike, "127.0.0.1", 0)
        self._servers = [command, waveform, spike]
        self.command_port = command.sockets[0].getsockname()[1]
        self.waveform_port = waveform.sockets[0].getsockname()[1]
        self.spike_port = spike.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for writer in [*self._clients, self._waveform, self._spike]:
            if writer is not None:
                writer.close()
        for server in self._servers:
            server.close()
            try:
                # Since 3.12 this waits for every connection to drop, and a
                # client cancelled mid-connect can leave one the fake never
                # saw. A test double must not be able to hang the suite.
                await asyncio.wait_for(server.wait_closed(), 1.0)
            except asyncio.TimeoutError:
                pass

    async def hang_up(self) -> None:
        """The operator pressed Disconnect in RHX's Remote TCP Control dialog:
        the command socket is closed from RHX's side. RHX itself is fine, and
        (unlike the real thing, which also stops listening until Connect is
        pressed again) the fake keeps listening, so a test can watch the
        service come back on its own."""
        clients, self._clients = self._clients, []
        for writer in clients:
            writer.close()

    async def die(self) -> None:
        """RHX crashing mid-recording: every socket drops at once."""
        await self.stop()

    # --- data sockets -----------------------------------------------------

    async def _on_waveform(self, _reader, writer) -> None:
        self._waveform = writer

    async def _on_spike(self, _reader, writer) -> None:
        self._spike = writer

    async def push_waveform(self, data: bytes) -> None:
        assert self._waveform is not None, "nothing connected to the waveform port"
        self._waveform.write(data)
        await self._waveform.drain()

    async def push_spikes(self, data: bytes) -> None:
        assert self._spike is not None, "nothing connected to the spike port"
        self._spike.write(data)
        await self._spike.drain()

    @property
    def data_sockets_connected(self) -> bool:
        return self._waveform is not None and self._spike is not None

    # --- command socket ---------------------------------------------------

    async def _on_command(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._clients.append(writer)
        try:
            while data := await reader.read(65536):
                commands = [c.strip() for c in data.decode("utf-8").split(";") if c.strip()]
                for index, command in enumerate(commands):
                    self.log.append(command)
                    reply = self._handle(command, batched=len(commands) > 1)
                    if reply:
                        writer.write(reply.encode("utf-8"))
                    lowered = command.lower()
                    if (
                        self.defers_batch_behind_runmode
                        and lowered.startswith("set runmode")
                        and not lowered.endswith("stop")
                        and index + 1 < len(commands)
                    ):
                        self._deferred.append((writer, commands[index + 1 :]))
                        break
                    if lowered.startswith("set runmode") and lowered.endswith("stop"):
                        self._later(self._flush_deferred())
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass

    def _handle(self, command: str, *, batched: bool) -> str:
        if self.silent:
            return ""  # socket open, nobody home
        verb, _, rest = command.partition(" ")
        verb = verb.lower()
        if verb == "get":
            if batched and not self.answers_batched_get:
                return ""
            key = rest.strip().lower()
            if key not in self.params:
                return f"Error: unrecognized parameter {rest.strip()}"
            if key == "currenttimestamp" and self.params["runmode"].lower() != "stop":
                self.params[key] = str(int(self.params[key]) + 3000)
            if key in ("currenttimestamp", "currenttimeseconds"):
                return f"Return: {self.params[key]}"  # nameless, as the real RHX sends it
            return f"Return: {rest.strip()} {self.params[key]}"
        if verb == "set":
            key, _, value = rest.strip().partition(" ")
            key = key.lower()
            if key in self.refuse:
                return f"Error: {key} cannot be set"
            if self.truncate_at_space:
                value = value.split(" ")[0]
            if key == "runmode":
                self._later(self._apply_runmode(value))
                return ""
            self.params[key] = value
            return ""
        if verb == "execute":
            if rest.split(" ")[0].lower() in self.refuse:
                return f"Error: {rest} failed"
            self.executed.append(rest.strip().lower())
            if rest.strip().lower() == "clearalldataoutputs":
                for key in [k for k in self.params if ".tcpdataoutputenabled" in k]:
                    self.params[key] = "False"
            return ""
        if verb == "livenotes":
            self.notes.append(rest)
            return ""
        return f"Error: unrecognized command {command}"

    async def _flush_deferred(self) -> None:
        """Acquisition stopped: finish the batches that were cut short by it."""
        await asyncio.sleep(self.runmode_delay_s + 0.01)
        pending, self._deferred = self._deferred, []
        for writer, commands in pending:
            for command in commands:
                reply = self._handle(command, batched=True)
                if reply and not writer.is_closing():
                    writer.write(reply.encode("utf-8"))

    async def _apply_runmode(self, value: str) -> None:
        await asyncio.sleep(self.runmode_delay_s)
        mode = value.strip().capitalize()
        previous = self.params["runmode"]
        self.params["runmode"] = mode
        if mode == "Stop":
            self.params["currenttimestamp"] = "-1"
        elif previous == "Stop":
            self.params["currenttimestamp"] = "0"
        if mode == "Record":
            self.params["filename.activefiletimestamp"] = "260920_101500"

    def _later(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- assertions -------------------------------------------------------

    def enabled(self, suffix: str) -> list[str]:
        """Channels for which `<channel>.<suffix>` was set true, in RHX order."""
        suffix = "." + suffix.lower()
        return sorted(
            key[: -len(suffix)].upper()
            for key, value in self.params.items()
            if key.endswith(suffix) and value.lower() == "true"
        )
