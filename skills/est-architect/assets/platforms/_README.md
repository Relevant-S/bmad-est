# Platform profiles

One data file per platform, and **no code anywhere**. If a platform ever needs code, the
capability boundary is in the wrong place — that is the test this directory exists to keep
failing loudly.

## Fields

| Field | Meaning |
| --- | --- |
| `id`, `name`, `kind` | `iaas`, `paas`, `baas`, `saas` or `self-hosted`. `kind` drives nothing on its own; it is how a reader groups the candidates. |
| `serves` | capability id → what this platform offers for it. `service` is the concrete product name that goes on the diagram and in the cost table, `managed` says whether the team operates it, `interface` is `standard` or `proprietary` and drives the reversibility sub-score, `icon` is the eraser catalogue name. |
| `runtime` | What it can actually run. The runtime-fit sub-score reads these and nothing else. |
| `pricing` | Where the cost breakdown goes to look. `url` per capability where the vendor splits pages. |
| `volatile` | Facts that go stale: certifications, regions, residency. **Every one carries `checked`.** |

## `checked: null` is not "no"

A volatile field with `checked: null` has never been verified by this installation. It is
**not** evidence of absence, and `architect.py` will not evaluate a `certification` or
`data_residency` gate against one — it reports the constraint as *unevaluated* and names the
platform, rather than passing or failing it on a claim nobody checked.

This is deliberate. A profile that shipped with `hipaa: true` typed in from memory would be a
compliance statement with no source, and it would be believed. Research it, write the date and
the URL, and the gate starts working for that platform.
