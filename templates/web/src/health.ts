/**
 * The client half of the contract, with the shape generated rather than restated.
 *
 * `Health` comes from `contracts/types.gen.ts`, which `pnpm install` generates from the
 * api's own OpenAPI document. A hand-written mirror would type-check against itself and
 * agree with whatever the author last believed; this one stops compiling when the api
 * changes the shape and this app has not followed.
 */
import type { components } from './contracts/types.gen';

export type Health = components['schemas']['Health'];

/**
 * The one value this client treats as healthy, pinned to the contract.
 *
 * `satisfies` is what makes the seam bite. A type that is merely *imported* does not stop
 * this file comparing against a string the api no longer sends — that comparison still
 * type-checks, and the failure arrives at runtime as a healthy service reported down.
 * Written this way, the api renaming the value fails `tsc` here, in the same build.
 */
const HEALTHY = 'ok' satisfies Health['status'];

/** True when the body is the health response the contract promises, and not something else. */
export function isHealthy(body: unknown): body is Health {
  if (typeof body !== 'object' || body === null) return false;
  return (body as { status?: unknown }).status === HEALTHY;
}

/** Ask the API whether it is up. Returns false rather than throwing on any failure. */
export async function fetchHealth(baseUrl: string): Promise<boolean> {
  try {
    const response = await fetch(`${baseUrl}/healthz`);
    if (!response.ok) return false;
    return isHealthy(await response.json());
  } catch {
    return false;
  }
}
