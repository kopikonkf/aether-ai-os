# ADR-0026: Runtime Driver Pack

- Status: Accepted
- Date: 2026-07-28

## Decision

Aether will represent vendor coding runtimes through immutable `RuntimeDriverManifest` objects owned by Core contracts and instantiated by Gateway driver translators.

A driver manifest declares identity, protocol, routing key, adapter ID, executable candidates, operations, capabilities, runtime features, platform support, credential names, priority, and implementation state.

Implementation states are:

- `live`;
- `discovery-only`;
- `planned`.

Availability states are:

- `available`;
- `degraded`;
- `unavailable`;
- `disabled`.

## Rationale

Aether needs to discover and use installed coding CLIs without embedding vendor conditionals in Core. A manifest separates stable Aether capability contracts from volatile vendor command-line interfaces.

Missing executables, credentials, or translators must not prevent Aether from booting. Runtime availability is operational state, not identity state.

## Security boundary

- Drivers translate; they do not govern.
- Credentials are deny-by-default and driver-specific.
- Credential values are never written to telemetry.
- Vendor output remains untrusted until Aether verification succeeds.
- Drivers cannot approve actions, mutate DNA, promote belief, or bypass workspace binding.
- Planned manifests are disabled and cannot enter runtime routing.

## Consequences

New vendor support requires a translator and conformance tests, not a Core modification. Driver status can be exposed to AionUi while unavailable drivers remain non-fatal.
