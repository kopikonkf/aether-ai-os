# Founder Approval UX — Local Acceptance

## What does not require manual approval

Under the default policy, bounded read-only observation is automatic:

```text
read
glob
grep
```

## What still requires approval

Examples:

```text
write or overwrite a file
edit existing content
execute shell/runtime operations
mutate operational memory
high-risk or irreversible actions
external side effects
public network fetch until nutrition conformance promotes a bounded adapter
```

## Telegram shortcuts

When exactly one action is pending in the same Telegram chat:

```text
/yes       approve once
/no        reject once
/approve   approve once
/reject    reject once
```

Explicit forms remain available:

```text
/approve approval.xxxxx
/approve approval.xxxxx reviewed exact workspace write
/reject approval.xxxxx not needed
/approvals
```

When multiple actions are pending, `/yes` and `/no` refuse to guess. Use `/approvals` and select the exact ID.

## Expected write receipt

After approval, the response must be derived from the action receipt and resemble:

```text
Selesai, Dee. Action sudah dieksekusi dan receipt authoritative telah dicatat.
Action ID: act.xxxxx
Operation: tool/write
Status: completed
Approval ID: approval.xxxxx (consumed exactly once)
Target: C:\Users\...\Aether\workspace\pengalaman-pertama.md
Size: 1234 bytes
Disposition: created
SHA-256: <64 hex characters>
Tidak ada approval tambahan yang sedang ditunggu untuk action ini.
```

The response must not contain `Waiting for operator approval` after status `completed`.

## Exact-content verification

A completion receipt proves which bytes were written through the SHA-256. To display exact content, ask:

```text
Aether, baca kembali workspace/pengalaman-pertama.md dan tampilkan isi persisnya. Jangan parafrase.
```

`read` is auto-approved. Compare the result with the local file when conducting Founder acceptance.
