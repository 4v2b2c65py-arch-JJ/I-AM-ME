# I-AM-ME

A deterministic, authenticated, capability-controlled, fork-aware state graph
with explicit joins, atomic transactions, and durable crash recovery.

## Architecture

```
derive
  ↓
canonicalize
  ↓
authenticate
  ↓
authorize
  ↓
commit
  ↓
lineage
  ↓
atomicity
  ↓
recovery
```

| Layer | Module | Responsibility |
| --- | --- | --- |
| RCS-0 | `soe_ddci/rcs.py` | Exact identity selection, zero reasoning |
| UTT | `soe_ddci/rcs.py` | `G → Q → R` triple with `direct_index` address |
| F4 | `soe_ddci/formation.py` | Deterministic formation `H("formation::" \|\| H(R))` |
| Canonical | `soe_ddci/canonical.py` | Representation-independent identity |
| Integrity | `soe_ddci/canonical.py` | `H(F)`, public, reproducible |
| Authenticity | `soe_ddci/authenticity.py` | `HMAC_K(canonical_bytes(F))`, secret-backed |
| RWA-1 | `soe_ddci/rwa.py` | Capability-based read/write authority |
| LGC-1 | `soe_ddci/lgc.py` | Lineage graph, fork detection, explicit joins |
| ATC-1 | `soe_ddci/atc.py` | Atomic transactions with snapshot/rollback |
| DRC-1 | `soe_ddci/drc.py` | Durable checkpoint, journal, crash recovery |

## Durability contracts

```
Replay(J, J) = Replay(J)
```

Replay is cursor-based and idempotent. A second recovery replays nothing new.

```
H ∈ VisibleHeads  ⇒  H ∈ DurableHeads
```

Every visible head carries a durable commit marker. A head cannot be exposed
without a commit record reaching durable storage.

## Identities

Three distinct identities are never collapsed:

```
formation_id        instance identity (UUID, per construction)
formation_encoding  content identity (H("formation::" || H(R)), public)
authenticity tag    authority over representation (HMAC, secret-backed)
```

## Testing

```
python3 run_tests.py
```

90/90 passing.