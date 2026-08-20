import { describe, expect, it } from 'vitest';

import { isHealthy } from './health';

describe('isHealthy', () => {
  it('accepts the body the contract promises', () => {
    expect(isHealthy({ status: 'ok' })).toBe(true);
  });

  it('rejects a body that merely looks like it', () => {
    expect(isHealthy({ status: 'OK' })).toBe(false);
    expect(isHealthy({})).toBe(false);
    expect(isHealthy(null)).toBe(false);
    expect(isHealthy('ok')).toBe(false);
  });
});
