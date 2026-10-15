"""Execute the shipped cost-display helper against mixed and unknown costs."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    shutil.which("node") is None, reason="JavaScript behavioral checks require Node"
)
def test_history_cost_calculations():
    helper = Path(__file__).parents[1] / "src/image_gen/static/costs.js"
    script = r"""
const assert = require('node:assert/strict');
const costs = require(process.argv[1]);
assert.equal(costs.summarize([]), 'No generations loaded.');
assert.equal(costs.summarize([{cost_usd:null}, {}]),
  'Known cost in loaded history: unknown · 2 with unknown cost');
assert.equal(costs.summarize([{cost_usd:0}, {cost_usd:0.1}, {cost_usd:0.2}, {}]),
  'Known cost in loaded history: $0.300000 · 1 with unknown cost');
for (const invalid of [null, undefined, '1', NaN, Infinity, -1]) {
  assert.equal(costs.format(invalid), 'unknown cost');
}
assert.equal(costs.format(0), '$0.000000');
assert.equal(costs.format(0.0042), '$0.004200');
assert.equal(costs.summarize([{cost_usd:0.0042}, {cost_usd:0.000001}]),
  'Known cost in loaded history: $0.004201 · 0 with unknown cost');
// Refreshing must replace the old sum rather than accumulate it a second time.
assert.equal(costs.summarize([{cost_usd:1}]),
  'Known cost in loaded history: $1.000000 · 0 with unknown cost');
"""
    subprocess.run(["node", "-e", script, str(helper)], check=True, capture_output=True, text=True)


async def test_history_cost_script_is_served(client):
    response = await client.get("/ui/costs.js")
    assert response.status_code == 200
    assert "function summarize" in response.text
    page = await client.get("/ui/")
    assert '<script src="/ui/costs.js"></script>' in page.text
    assert 'id="history-cost" role="status"' in page.text
