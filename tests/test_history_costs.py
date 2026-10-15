"""Execute the shipped cost-display helper against server aggregates and statuses."""

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
assert.equal(costs.summarizeAggregate(null), 'Cost summary unavailable.');
assert.equal(costs.summarizeAggregate({
  all_time: {
    completed_known_count: 2,
    completed_unknown_count: 1,
    known_cost_usd: 0.3,
    failed_count: 1,
    generating_count: 0,
    pending_count: 1,
    other_count: 0
  },
  today: {
    completed_known_count: 0,
    completed_unknown_count: 2,
    known_cost_usd: null,
    failed_count: 0,
    generating_count: 1,
    pending_count: 1,
    other_count: 0
  }
}), 'All-time reported cost: $0.300000 · 1 completed with unknown cost · 1 failed · 1 pending | ' +
  'Today (UTC) reported cost: unknown · 2 completed with unknown cost · 1 generating · 1 pending');
assert.equal(costs.summarizeAggregate({
  all_time: {
    completed_known_count: 0,
    completed_unknown_count: 0,
    known_cost_usd: null,
    failed_count: 1,
    generating_count: 0,
    pending_count: 1,
    other_count: 0
  },
  today: {
    completed_known_count: 0,
    completed_unknown_count: 0,
    known_cost_usd: null,
    failed_count: 0,
    generating_count: 0,
    pending_count: 0,
    other_count: 0
  }
}), 'All-time reported cost: no completed costs · 1 failed · 1 pending | ' +
  'Today (UTC) reported cost: no completed costs');
for (const invalid of [null, undefined, '1', NaN, Infinity, -1]) {
  assert.equal(costs.format(invalid), 'unknown cost');
}
assert.equal(costs.format(0), '$0.000000');
assert.equal(costs.format(0.0042), '$0.004200');
assert.equal(costs.formatRecord({status:'pending', cost_usd:1}), 'pending');
assert.equal(costs.formatRecord({status:'failed'}), 'failed');
assert.equal(costs.formatRecord({status:'future-state'}), 'not completed');
assert.equal(costs.formatRecord({status:'completed', cost_usd:null}), 'unknown cost');
// A fresh server response replaces the previous aggregate instead of accumulating it.
assert.equal(costs.summarizeAggregate({
  all_time: {
    completed_known_count: 1,
    completed_unknown_count: 0,
    known_cost_usd: 1,
    failed_count: 0,
    generating_count: 0,
    pending_count: 0,
    other_count: 0
  },
  today: {
    completed_known_count: 1,
    completed_unknown_count: 0,
    known_cost_usd: 1,
    failed_count: 0,
    generating_count: 0,
    pending_count: 0,
    other_count: 0
  }
}), 'All-time reported cost: $1.000000 | Today (UTC) reported cost: $1.000000');
"""
    subprocess.run(["node", "-e", script, str(helper)], check=True, capture_output=True, text=True)


async def test_history_cost_script_is_served(client):
    response = await client.get("/ui/costs.js")
    assert response.status_code == 200
    assert "function summarizeAggregate" in response.text
    page = await client.get("/ui/")
    assert '<script src="/ui/costs.js"></script>' in page.text
    assert 'id="history-cost" role="status"' in page.text
    assert "costs:   '/api/images/costs'" in page.text
    assert "ImageCosts.summarizeAggregate(data)" in page.text
    assert "ImageCosts.formatRecord(rec)" in page.text
