# Decision: `make up` builds its own cluster `ace`; the spike cluster stays as it is

Date: 2026-10-10. Status: accepted (user decision while planning #26).

`make up` creates and `make down` deletes the k3d cluster `ace` (context `k3d-ace`), built from a
copy of the spike's cluster config. The spike cluster `ace-spike` (context `k3d-ace-spike`) is shared
by live checks that run in parallel, so no make target or script may delete, recreate, stop, or
change it. The existing live-check targets `gateway-check` and `gateway-failover-check`
keep running against `ace-spike`, as #25 built them; the new targets `up`, `down`, `status`, and
`dev` and the scripts under `platform/` name only `k3d-ace`. `make up` reuses the spike's pinned versions and install scripts, called with
`KCTX=k3d-ace`, so there is one source for the install steps. Both clusters fit in Docker Desktop
at once (23.4 GiB VM; the spike node uses about 3.5 GiB), and `make up` refuses to start when free
Docker memory is below its threshold.
