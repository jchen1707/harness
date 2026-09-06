import assert from 'node:assert/strict';
import { test } from 'node:test';
import { applyDelivery, resolveDelivery } from './delivery_policy.mjs';

const config = {
  delivery: {
    default: 'core',
    requirements: {
      acceptance: { kind: 'correctness', description: 'Accepted behavior', gate: 'acceptance' },
      scale: {
        kind: 'engineering',
        description: 'Load targets',
        gate: 'scale',
        deferrableIn: ['prototype'],
      },
    },
    profiles: {
      prototype: {
        required: [],
        deferrals: [
          { requirement: 'scale', rationale: 'No load yet', revisit: 'Before public launch' },
        ],
      },
      core: { required: ['scale'], deferrals: [] },
      hardening: { required: ['scale'], deferrals: [] },
    },
  },
  gates: [{ name: 'acceptance', enabled: false }, { name: 'scale' }],
};

test('Prototype retains correctness and makes engineering deferral visible', () => {
  const policy = resolveDelivery(config, null, 'prototype');
  const effective = applyDelivery(config, policy);
  assert.equal(effective.gates[0].enabled, true);
  assert.equal(effective.gates[1].policyDeferral.revisit, 'Before public launch');
  assert.equal(config.gates[0].enabled, false);
});

test('Children cannot contradict or defer inherited requirements', () => {
  const parent = resolveDelivery(config);
  assert.throws(() => resolveDelivery(config, parent, 'prototype'), /cannot weaken/);
  const child = structuredClone(config);
  child.delivery.requirements.acceptance.description = 'Different contract';
  assert.throws(() => resolveDelivery(child, parent), /Conflicting/);
});

test('Safety and incomplete deferrals are rejected', () => {
  const child = structuredClone(config);
  child.delivery.requirements.scale.kind = 'safety';
  assert.throws(() => resolveDelivery(child, null, 'prototype'), /Invalid deferral/);
  child.delivery.requirements.scale.kind = 'engineering';
  child.delivery.profiles.prototype.deferrals[0].revisit = '';
  assert.throws(() => resolveDelivery(child, null, 'prototype'), /Invalid deferral/);
});
