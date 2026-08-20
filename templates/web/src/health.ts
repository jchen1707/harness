/**
 * The client half of the contract's `Health` shape.
 *
 * Hand-written for now, and that is a debt with a name: `packages/contracts/openapi.yaml`
 * is the source of truth, and the moment this file is generated from it the build starts
 * catching drift the two sides would otherwise carry silently. Until then, changing one
 * means changing the other in the same commit.
 */
export type Health = { status: 'ok' };

/** True when the body is the health response the contract promises, and not something else. */
export function isHealthy(body: unknown): body is Health {
  return (
    typeof body === 'object' && body !== null && (body as { status?: unknown }).status === 'ok'
  );
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
