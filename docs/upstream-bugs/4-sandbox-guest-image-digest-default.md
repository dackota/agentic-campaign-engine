# Draft for kagent-dev/kagent: standalone sandboxes fail on a default install (guest image has no digest)

**Versions:** kagent chart 1.0.0-alpha9, Substrate 0.4.0-alpha1.

**Repro:** install per the guide. Apply a SandboxTemplate with a digest-pinned workload
image. Run `kagent sandbox create <template> --request-id x`.

**Actual:** template `Ready=False`, `PreparationFailed: Sandbox preparation failed; inspect controller logs`.
`create` returns `SandboxTemplate has no prepared revision`. Only the controller log says
`sandbox workload and guest images must be pinned by sha256 digest`.
The chart's `controller.sandbox.guestImage.digest` defaults to `""`.

**Workaround:** `--set controller.sandbox.guestImage.digest=sha256:d5ac5bfa263a0bfa0953804ba9cfec4d9c13b6c78c0af7d36f6e5952630987a2`
(the `sandbox-guest:1.0.0-alpha9` index digest).

**Expected:** the chart defaults to a digest for the guest image it ships, or the status
message names the missing value. Also, the guide's examples do not show SandboxTemplate.
