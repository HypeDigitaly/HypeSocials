# Virlo fixture corpus — real API responses, captured 2026-08-11

**Why this exists.** The Virlo free trial expires ~2026-08-13. After that there are no live calls,
and roughly 1,200 lines of planned work (`plans/xmasterplan-virlo-throughput-and-fidelity.md`
Increment A waves A2′–A3 and all of Increment B, plus
`plans/xmasterplan-copy-voice-transposition.md`) still needs real response shapes to develop and
test against. These files are that insurance: **develop offline, no key required, no spend.**

Captured read-only, free endpoints only. Every call returned `x-cost 0.00`. **The metered
`/trends/digest` was deliberately NOT called** — it is the only Virlo endpoint that bills, and the
digest exemplar work (A18) is developed against the shapes in `spikes/RESULTS.md` instead.

## What is here

| File | Endpoint | Notes |
|---|---|---|
| `agents.json` | `GET /v1/agents` | 3 monitors on the operator's key |
| `agent_detail.json` | `GET /v1/agents/{id}` | `analysis_data.themes[]`, tactics, timing |
| `agent_trends_latest.json` | `GET /v1/agents/{id}/trends/latest` | **9 theme rows** — the endpoint plan §1.3 found and nothing in the repo calls yet. Increment B's raw material |
| `videos_views_desc_limit100.json` | `GET /v1/agents/{id}/videos?limit=100&order_by=views&sort=desc` | 100 of 2,039 |
| `slideshows_views_desc_limit100.json` | `GET /v1/agents/{id}/slideshows?limit=100&order_by=views&sort=desc` | 100 of 635 |

Monitor: `9c96fddf-dc35-4be0-bbd9-12f4d22aea12` ("AI Trends Tracker") — the one
`configs/hypedigitaly.yaml` ships. Bodies are stored **whole**, including Virlo's `{"data": …}`
envelope, so a test can exercise `virlo_mcp.server._unwrap` rather than assume it.

Nothing is redacted. **These bodies contain no secret** — the API key travels in the
`Authorization` header and never appears in a response (D30). Verified by sweep before commit.

## What the corpus proves, at the wire

The sorted fetch is the single biggest quality lever in the plan, and these files are its
independent confirmation — measured on capture, at `limit=100`:

| | videos | slideshows |
|---|---:|---:|
| rows | 100 of 2,039 | 100 of 635 |
| max views | 26,756,830 | 5,487,494 |
| median views | 1,101,624 | 147,587 |
| rows carrying `intelligence{}` | 70/100 | 84/100 |

Compare the **unsorted** baseline the engine shipped with (plan §1.1, `limit=50`): median
**2,534** views for videos and **7,088** for slideshows, with `intelligence{}` on 17/50 and 29/50.

⚠️ **Calibration note for anyone re-running the live checks.** Plan §1.1 and
`plans/EXECUTION-ORDER.md` quote medians of ~1.9M (videos) and ~280k (slideshows). Those were
measured at **`limit=50`**. The adapter now requests **`limit=100`**, and a deeper page pulls the
median down by design — the true sorted medians at 100 rows are the **1.10M / 148k** above. Both
are still ~435× and ~21× the unsorted baseline, so the check passes decisively; do not read
1.10M as a miss against the 1.9M figure. Assert against the *unsorted* baseline, not against a
median measured at a different page size.

## Using them

```python
import json, pathlib
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "virlo"
body = json.loads((FIXTURES / "videos_views_desc_limit100.json").read_text(encoding="utf-8"))
rows = body["data"]["videos"]
```

Real data has real edges, which is the point of using it: rows with `intelligence: null`
(30/100 videos), duplicate posts across calls, absent `hook_text`, slideshows whose `images[]`
carry `{image_url, position}` rather than a flat URL list. Do not "clean" these files — a fixture
tidied into the shape the code expects tests nothing.

## Re-capturing

The capture script is not committed (it is a one-shot conductor tool, not engine code). Any
re-capture must keep three rules: free endpoints only, never `/trends/digest`, and the key stays
in the `Authorization` header — never in a file, a log line or a filename.
