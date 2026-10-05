# ULPIN interoperability

## Why this document exists

India's national parcel identifier is **ULPIN** (Bhu-Aadhaar), a 14-character
alphanumeric code maintained by the Department of Land Resources under the
Digital India Land Records Modernisation Programme (DILRMP). It is the intended
single source of truth for land parcels.

GEOSIX does **not** issue ULPINs and is not part of that programme. It consumes
them. This note records exactly what GEOSIX assumes about the national format, so
that nobody mistakes the mapping here for an authoritative implementation.

## The national format as GEOSIX understands it

```
SS DD TTT VVV PPPP
 |   |   |    |    +-- 4  plot serial within the village
 |   |   |    +------- 3  village code
 |   |   +------------ 3  sub-district (tehsil) code
 |   +---------------- 2  district code
 +-------------------- 2  state code
```

Fourteen characters, digits only. The component widths are fixed; the *values*
are issued and maintained by state and district registrars.

## What is validated, and what is not

| Checked by GEOSIX | Not checked by GEOSIX |
|---|---|
| Total length is exactly 14 | Whether a state code is currently issued |
| All characters are digits | Whether a district belongs to that state |
| The string splits into 2/2/3/3/4 | Whether a village code is live |
| | Whether a plot serial has been assigned |

The right-hand column requires the national registry. A format check cannot know
it, so GEOSIX never asserts that a well-formed ULPIN refers to a real parcel.
Callers should treat a successful validation as *syntactically* valid only.

## How GEOSIX extends ULPIN vertically

ULPIN is flat. It names a parcel on the ground and stops there. A tower standing
on one parcel contains many independently owned properties, so ULPIN alone
cannot address:

```
Tower A / Floor 5 / Unit 503
```

GEOSIX addresses this with the **VDC** (Vertical DNA Code), which appends four
segments to a parcel key:

```
GEOSX01700-A-F5-503-<checksum>
   │      │ │  │   └── base-36 checksum (tamper detection)
   │      │ │  └────── unit within the level
   │      │ └───────── vertical level (G / F<n> / B<n>)
   │      └─────────── property domain (A residential, B commercial,
   │                    C industrial, D civic/institutional)
   └────────────────── parcel
```

The full specification, including the ABNF grammar and the checksum algorithm, is
in [vdc-specification.md](vdc-specification.md).

### Deriving the GEOSIX parcel key

`app/validators/ulpin.py` derives the GEOSIX parcel key from a national ULPIN by
folding the 4-digit plot serial into the 5-digit GEOSIX space:

| National ULPIN | State | District | Sub-district | Village | Plot | GEOSIX key |
|---|---|---|---|---|---|---|
| `12101055001700` | 12 | 10 | 105 | 500 | 1700 | `GEOSX01700` |

## Important limitations of this mapping

**The GEOSIX key is a local handle, not an identifier to write upstream.** The
5-digit GEOSIX space is narrower than the national village-plus-plot space, so
distinct national ULPINs can collide. The national ULPIN remains the stored
system of record; the GEOSIX key exists only so a VDC has something to anchor
to. Never persist a GEOSIX key in place of a ULPIN.

**GEOSIX does not verify ULPINs against the national registry.** Doing so would
require an interface to DILRMP data that does not exist here. Treat any ULPIN
entering GEOSIX as unverified until confirmed out of band.

**Segment semantics are assumed, not sourced.** The 2/2/3/3/4 split follows the
published structure. If DoLR revises it, `ULPIN_SEGMENT_LENGTHS` in
`app/validators/ulpin.py` is the single place to change.

## What this means for interoperability

A GEOSIX installation can be anchored to national parcel identities, and vertical
VDC codes can be issued beneath them. It is **not** a ULPIN generator, not a
substitute registry, and not conformant with any DILRMP certification. Any claim
of "ULPIN generation" in GEOSIX materials should be read as "VDC generation over
a parcel identity", because that is what the code does.