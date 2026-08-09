# Migrating alfen_modbus to modbus-connection

Notes from porting this integration off raw pymodbus onto
[modbus-connection](https://github.com/home-assistant-libs/modbus-connection)
4.3.0. Two things made this repo interesting to migrate: it is genuinely
**multi-unit** (the station and each socket are separate Modbus slaves on one TCP
link — the canonical `for_unit()` case), and it needs **FC16 forced on a
single-register write**.

The register map was verified against the vendor document — *Modbus Slave TCP/IP:
Implementation of Modbus Slave TCP/IP for Alfen NG9xx platform*, v2.3
(30-10-2020) — not against the pre-migration code, which turned out to matter.

## Shape of the result

| | before | after |
|---|---|---|
| Modbus layer | 483-line `__init__.py` around a hand-rolled `AlfenModbusHub` (sync pymodbus on an executor) | 221-line declarative register map + 262-line device object |
| Poll | 4 hand-written block reads, offsets counted by hand | 5–6 planned block reads, addresses declared on fields |
| Entity data | one `dict[str, Any]` keyed by strings like `"socket_1_VL1-L2"` | typed attributes, `socket.meter.voltage_l1_l2` |
| Update loop | `async_track_time_interval` + a per-entity callback list | `DataUpdateCoordinator` |
| Reconnect | `_ensure_connected()` + "close, reconnect, retry once" around every read and write | connect-on-demand, nothing in the integration |
| Tests | none | 44, against the in-memory mock; no hardware, no charger |

Entity unique ids are unchanged, so an existing install keeps its history.

---

## 1. What weird things does this library do?

**The device is several Modbus units on one socket.** Station registers answer on
slave **200**; socket 1 answers on slave **1** and socket 2 on slave **2** — the
socket number *is* its slave id. The pre-migration code passed `unit=socket`
literally. This is exactly what `ModbusConnection.for_unit()` is for, and it is
the one part of the migration that was pure gain: three `ComponentGroup`s over
three units on one link.

**FC16 is forced on a one-word register.** Register 1215 ("charge using 1 or 3
phases", UNSIGNED16) is a single register, which `auto` write-mode would send as
FC06. The station only honours FC16 there. The pre-migration code got this by
routing *every* write through `write_registers`; the model expresses it as
`force_fc16=True` on the one field that needs it, and a test asserts the
function code the write goes out as. The other writable register — the current
setpoint at 1210 — is FLOAT32, so it is two registers and FC16 anyway.

**The charger fails safe, so the client has a keepalive obligation.** Register
1208 counts down from the station's validity time (60 s by default). If a Modbus
master does not rewrite the max current (1210) before it reaches zero, the socket
drops back to its configured *safe current* — the car slows down. The mechanism
is the write itself, not the value: rewriting the setpoint the station is already
reporting restarts the timer. Pre-migration this lived in the *entity* layer —
the hub kept a second callback list (`self._inputs`) that only the number entity
registered into, and a `refresh_max_current()` that fired it — so an entity was
responsible for a protocol obligation. It now lives in the device library
(`AlfenSocket.async_renew_max_current`), driven from the coordinator after each
poll.

One safety change: the old code rewrote whatever it had last read, including
zero. A station that has never been given a setpoint reads 1210 back as `0.0`
with `valid_time` also `0`, which made the old watchdog fire on every single poll
and write a zero-ampere setpoint. The port skips a falsy setpoint, and there is a
test for it.

**The socket meter block is one register too wide to read.** Registers 300–425
are 126 wide; FC03 tops out at 125. The pre-migration code issued a single
`read(300, 125)` and silently dropped register 425 — the last word of the
reactive-energy total. modbus-connection's planner splits it at `max_span`
without cutting a field, into `(300, 122)` and `(422, 4)`. That is one extra
round trip per socket per poll, and it is the correct number.

**The register map was wrong, and the bundled simulator agreed with it.** Against
the vendor table:

| | spec | pre-migration |
|---|---|---|
| Meter last value timestamp | 301–304, UNSIGNED64 (ms) | read as 4 × UINT16, which pymodbus returns as a *list* — the list became a sensor state |
| Apparent Energy L1/L2/L3/Sum | **394**, 398, 402, 406 | 392, 396, 400, 404 |
| Reactive Energy L1/L2/L3/Sum | **410**, 414, 418, 422 | 408, 412, 416, 420 |

Eight FLOAT64 sensors were decoding two registers off, i.e. reinterpreting the
low half of one value and the high half of the next as a double. `simulator/` had
been written to match the integration rather than the spec, so it reproduced the
bug faithfully and validated nothing; it is corrected here too.

**NaN is a data type here.** The spec fills any unavailable or reserved register
with NaN — `0xFFFF` per 16-bit register — and this is not theoretical: the README
already documents that chargers with a post-2021 Reallin meter leave most of the
energy block unpopulated. The pre-migration sensor's only guard was
`self._hub.data[k] == self._hub.data[k]`, a bare NaN self-comparison. Fields now
declare their sentinel and decode to `None`.

**Everything derived is invented by the integration.** The station has no session
counters and no "car connected" flag. What it has is register 1201: a
five-register *string* holding the IEC 61851 mode 3 state (`A`, `B1`, `B2`, `C1`,
`C2`, `D1`, `D2`, `E`, `F`). "Connected" is `state not in {A, E, F}`; "charging"
is `state in {C2, D2}`. Session energy and duration are snapshot deltas: when the
state first reports current flowing, the delivered-energy total and the *station's
own clock* are captured, and the figures track the difference until it stops —
then freeze, so they stay readable after unplugging. Because the clock comes from
the station unit and the energy from a socket unit, the session update is
sequenced by the device object across two units.

**The station clock is six separate SIGNED16 registers** (168–173) plus a UTC
offset in minutes (178), and `last_boot` is that clock minus a UNSIGNED64 uptime
in milliseconds — recomputed every poll, so it jitters by a second. Preserved
as-is, jitter included.

**Found on the way, unrelated to Modbus:** the pre-migration `number.py` declares
`class AlfenNumber(NumberEntity)` but calls `super().__init__(hub, device_info)`.
`Entity` defines no `__init__`, so that reaches `object.__init__` and raises
`TypeError: object.__init__() takes exactly one argument`. The max-current slider
— the integration's headline control — could not be constructed at all. Verified
against Home Assistant 2026.8.1.

---

## 2. What internals of modbus-connection did you have to touch?

**None.** Nothing private, nothing subclassed beyond `Component`, nothing
monkeypatched, no reaching past a public API. That is the honest answer and it is
a good result for a device this awkward — the whole map, both writes, the block
splitting and the NaN handling are expressible in the documented surface.

Three places used the public API slightly off its obvious grain:

- **`writable=Phases`** — a `WriteValidator` is documented as "a callable that
  vets or coerces the value", and an `IntEnum` class is exactly that: `Phases(2)`
  raises, `Phases(3)` coerces. Using an enum class as the validator is legitimate
  and reads well, but it is not what the docs show.
- **`nan=0xFFFF` on float fields** — see gap 3 below. On a `FloatField` the value
  is never compared to anything; it only switches the `math.isnan` check on. It is
  written as the spec's sentinel for consistency with the integer fields, with a
  comment saying so, because writing `nan=0` or `nan=1` would be equally correct
  and considerably more confusing.
- **`Component.write("field_name", value)`** — the model's whole value is that
  `socket.status.phases` is a typed descriptor, but writing it goes through a
  string. See gap 5.

What was *not* needed is worth recording too: no `message_spacing` (the station
answers back-to-back fine, and explicitly supports two concurrent masters), no
`connect_delay`, no custom backend, no retry policy tuning, no `ManualComponent`,
no `repeating_group`. Connect-on-demand plus "do not reload the entry on a
dropped link" deleted about ninety lines of hand-rolled reconnect-and-retry
without replacement.

---

## 3. What could modbus-connection do better to support this library?

Ordered by how much they cost here.

### 3.1 Nothing pools reads across units

`ComponentGroup(unit, components)` is *the* pooling abstraction and it is
single-unit by construction. A device that **is** several units — the headline
case for `for_unit()`, and the case this repo was picked to exercise — gets no
help above the unit level. `AlfenCharger` hand-rolls all of it: which group to
update, in what order, what to do when one unit answers and another does not, and
how to merge the results.

The ordering is not incidental. The station must be read *first*, because
register 1105 is what decides whether socket 2 is worth addressing at all (on a
single-socket station that unit simply does not answer), and because the station's
clock is what the sockets' session figures are measured against. So the device
object is not just a loop — it encodes a read *order* and a dependency between
units, and there is nowhere in the model to say that.

**Ask:** a `DeviceGroup` / `UnitGroup` taking `{unit: [components]}` that updates
in a declared order and aggregates errors and raw output. Even without dependency
support, the merge and the error handling are the same in every multi-unit device.

### 3.2 `async_read_raw()` cannot represent a multi-unit device — and fails silently

`{space: {address: value}}` has no unit dimension. Socket 1's holding 300 and
socket 2's holding 300 are different registers on different slaves; merging two
dumps loses one, with no error and no warning — just a diagnostics file that says
the wrong thing.

This is not a corner: the Home Assistant guide sells `async_read_raw()` as *the*
diagnostics recipe, and `load_raw()` as the way to replay a user's dump into the
mock for a regression test. Both are unsound the moment a device has more than one
unit. This integration works around it by prefixing the space with a label
(`"socket_1/holding"`), which is a string hack that no `load_raw()` will ever
read back.

**Ask:** `{unit: {space: {address: value}}}` (or a `unit_id` on the readable that
`async_read_raw()` stamps in), and `load_raw()` accepting the same shape. If the
shape cannot change, the multi-unit hazard needs to be documented loudly wherever
the diagnostics recipe is.

### 3.3 `nan=` means two different things depending on the field

On `NumberField` it is a set of raw sentinel values compared against the combined
word. On `FloatField` it is a *flag*: any non-`None` value enables the
`math.isnan` check and the value itself is never used. A device whose spec says
"unavailable registers read 0xFFFF" therefore writes `nan=0xFFFF` on 49 float
fields where `0xFFFF` is decorative.

Worse, the default is wrong for floats. An IEEE NaN read off a register is
*already* the wire encoding of "no value" — there is no consumer anywhere who
wants `float('nan')` handed to them instead of `None`. Every Home Assistant
integration that has ever displayed a Modbus float has a NaN check in it; this
one had `value == value` in its sensor class.

**Ask:** make `FloatField` decode NaN to `None` by default, or give it a separate,
honestly-named `nan_is_none: bool = True`. Keep `nan=` meaning "these raw
patterns are sentinels" for the integer fields, where it already does.

### 3.4 No way to say "this register is a 2-decimal quantity"

Every FLOAT32 here reads back like `231.8000030517578`. The meter resolves two
decimals; the extra digits are float32 noise. The pre-migration code rounded at
every one of its call sites. There is no field-level way to express it: `scale=1.0` with
`offset=0.0` short-circuits `_ScaledField._scale` and returns the raw value
before the rounding branch is reached, so the rounding machinery that exists for
scaled fields is unreachable for unscaled ones.

So the rounding moved to the entity layer, which is the wrong place — precision is
a property of the *register*, not of how Home Assistant displays it, and a
non-Home-Assistant consumer of this library gets the noise.

**Ask:** a `decimals=` (or `precision=`) option on the numeric fields, applied
whether or not a scale is set.

### 3.5 `Component.write()` is stringly-typed

```python
await socket.status.write("max_current", value)  # today
```

The entire premise of the model is that `socket.status.max_current` is a typed
descriptor a checker understands. Writing it goes through a bare string that
nothing validates until runtime. In an integration whose defining pre-migration
problem was `hub.data["maxCurrentValidTime_socket_1"]`, reintroducing an
unchecked string on the write path is a shame — and the device library ends up
wrapping every write in a typed method (`async_set_max_current`,
`async_set_phases`) largely to hide it.

**Ask:** accept the descriptor as well as the name — `component.write(
SocketStatus.max_current, value)` — or generate a setter. `RegisterField.__get__`
already returns the field object on class access, so the plumbing is there.

### 3.6 The device-side keepalive has no home, and getting it wrong stops the car

Alfen, KEBA and ABB Terra all revert a setpoint unless the master rewrites it
inside a validity window; the design review already names this as a Round-3
dimension. What every one of them needs is the same three lines: after a poll, if
the countdown register is below a threshold, write the setpoint register back
with the value it already reports.

Three lines is not a library feature on its own — but it is three lines every
charger integration re-invents, the failure mode is silent (the car quietly
charges at the safe current), and the obvious naive implementation writes back a
zero the device never had and pins the socket at no current. This repo shipped
that bug.

**Ask:** at minimum, name the pattern in the Home Assistant integration guide next
to "reconnecting is automatic". Better: `await component.rewrite("field")` —
write the last decoded value back, no argument, raising if it was never read.
That is trivially general (it is the read-back-and-write-again idiom), and it is
where the "don't write a value you never had" check belongs.

### 3.7 Read plans are only observable through the mock's side effects

The 126-register split into `(300, 122)` + `(422, 4)` is exactly right, and I only
confirmed it by asserting on `mock_modbus_unit.read_events` after a poll. That
works, but it tells you what *happened*, not what *will* happen: there is no way
for a device library to assert its read cost without a mock and a round trip, and
no way to see the plan at all while writing the map.

**Ask:** expose the planned blocks — `group.blocks()` or `component.read_plan()` —
so a device library can unit-test "this map is N reads, none wider than 125"
directly. It would also make `max_span` and `register_ranges` far easier to learn.

### 3.8 Smaller things

- **`ComponentGroup`'s `require_declared` is all-or-nothing.** Adding
  `register_ranges` to one component forces it on every sibling in the group, and
  the failure surfaces at group construction rather than at the component that
  forgot. Defensible, but the error should name the component.
- **`ComponentGroup` membership is fixed at construction.** SCN is optional per
  config here, so the station builds a list conditionally and then constructs the
  group. Fine — just noting `ManualComponent` can add and remove targets and
  `ComponentGroup` cannot.
- **`enum()` has no `nan` semantics distinct from "unmapped".** `0xFFFF` on an
  enum field falls through to the "no mapping for value" path and logs a warning
  before decoding to `None`. Declaring it as `nan=` gets the right answer quietly,
  but only because the sentinel check runs first — that ordering is load-bearing
  and undocumented.

---

## What the library got right here

Worth stating, since the list above is all complaints:

- `for_unit()` over one shared connection is the correct core abstraction for
  this device, full stop. The pre-migration code opened one socket and passed a
  `device_id` per call; the model says what is actually true.
- `force_fc16` on the single field that needs it, rather than a connection-wide
  write mode, is exactly the right granularity — 1210 and 1215 are on the same
  component and want different function codes for the same reason (width) except
  where the firmware disagrees.
- `max_span` splitting between fields rather than through one silently fixed a
  bug this repo had shipped for years.
- Connect-on-demand plus "do not reload the entry when the link drops" deleted
  every line of reconnect logic with nothing to replace it.
- The mock backend, with `read_events` and `WriteEvent.function_code`, is what
  made it possible to test the two things this device is interesting for — the
  block plan and the forced function code — with no hardware. Both would
  otherwise have been untestable claims.
