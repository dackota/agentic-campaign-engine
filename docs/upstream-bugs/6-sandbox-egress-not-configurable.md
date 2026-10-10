# Draft for kagent-dev/kagent: no way to configure or learn the egress policy of a standalone sandbox

**Versions:** kagent chart 1.0.0-alpha9, Substrate 0.4.0-alpha1, k3d.

**Repro:** apply a SandboxTemplate (digest-pinned alpine), `kagent sandbox create`, then
`kagent sandbox exec <id> -- wget -T5 -qO- http://example.com`.

**Actual:** `wget: server returned error: HTTP/1.1 403 Forbidden`, for every host tried
(example.com over HTTP and HTTPS, in-cluster services, 169.254.169.254). DNS still resolves
and ICMP is dropped. The 403 body says nothing about a policy. The SandboxTemplate CRD has
no egress or network field, and no doc page names one.

**Expected:** a documented field (allow-list of hosts) on SandboxTemplate or SandboxConfig,
and a 403 body or log line that says the egress policy denied the request.
