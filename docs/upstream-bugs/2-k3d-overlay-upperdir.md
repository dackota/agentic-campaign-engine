# Draft for kagent-dev/substrate: actors crash on Docker-based nodes (k3d) because /var/lib/ate is overlayfs

**Versions:** Substrate 0.4.0-alpha1, kagent 1.0.0-alpha9, k3d v5.9.0, `rancher/k3s:v1.37.1-k3s1`,
Docker Desktop (linuxkit 7.0.12, arm64).

**Repro:** k3d cluster with default volumes; install Substrate and kagent; apply a Harness,
AgentTemplate and Agent.

**Actual:** Agent `Ready=False`, `GoldenActorCrashed`. The ateom log shows:
```
while composing pause rootfs: while mounting overlay rootfs at ".../bundles/_pause/rootfs":
while setting overlay upperdir=".../bundles/_pause/upper": invalid argument
(kernel: overlay: filesystem on .../upper not supported as upperdir)
```
**Cause:** `/var/lib/ate` is on the k3d node's root filesystem, which is overlayfs. The
kernel does not accept an overlayfs upperdir on overlayfs.

**Workaround:** mount a Docker volume at `/var/lib/ate` on the node
(`volumes: - volume: ace-spike-ate:/var/lib/ate`). With it, gVisor actors run on k3d.

**Ask:** document this for k3d and other container-as-node clusters, and/or have atelet
check the filesystem type of its actor directory at start and fail with a clear message.
