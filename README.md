# Kernel builder

One GitHub Actions workflow for Poco F5 (`marble` / `marblein`). The same files work for another device after you add one env file. Kernel trees are data, not copies of the workflow.

Presets:

| Key | Tree | ROM |
|---|---|---|
| `aospa` | [aospa-shadedark/kernel_manifest](https://github.com/aospa-shadedark/kernel_manifest) `calcite-xiaomi-sm8450` | Paranoid Android |
| `aosp` | [aosp-pablo/android_kernel_xiaomi_sm8450](https://github.com/aosp-pablo/android_kernel_xiaomi_sm8450) `17` | LOS-based |
| `melt` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble) `melt-rebase` | HyperOS |

`aospa` reads `default.xml` and clones the GitHub projects in it. AOSP clang and host gcc prebuilts are skipped (they are multi-gigabyte and unused). The compiler comes from the toolchain input instead.

## Run

Actions, **Build kernel**, then **Run workflow**.

Leave `kernel_source` as `aosp`, `aospa`, or `melt`. Set `manager` to `kernelsu` (or `none`, `kernelsu-next`, `sukisu-ultra`, `resukisu`, `all`). Download the AnyKernel3 zip from the run artifacts. It flashes `boot` and checks the device codename.

`build_scope=image-only` is the boot image. `full` also builds in-tree modules, dtbs, and the SM8450 techpack list in [config/techpack-sm8450.txt](config/techpack-sm8450.txt).

## SUSFS

SUSFS comes from [simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu) branch `gki-android12-5.10` (override with `susfs_branch` / `susfs_ref`).

- Official KernelSU has no in-tree SUSFS, so the build applies `10_enable_susfs_for_ksu.patch` from that same SUSFS commit, then the `50_add_susfs_in_gki-android12-5.10.patch` kernel patch.
- KernelSU-Next tries the official tree first. If that patch does not apply, it falls back to `pershoot/KernelSU-Next` `dev-susfs`.
- SukiSU Ultra with SUSFS checks out `builtin`. ReSukiSU already ships `KSU_SUSFS`.
- `manager=none` cannot enable SUSFS.

Vendor trees drift. If a hunk fails, the log says so. Pin `source_ref` or `manager_ref`, or refresh the SUSFS branch for that device.

## NoMount

[maxsteeel/nomount](https://github.com/maxsteeel/nomount), integrated with upstream `kernel/setup.sh`.

| Input | Result |
|---|---|
| `off` | Not included |
| `builtin` | `CONFIG_NOMOUNT=y` inside the kernel image |
| `lkm` | Boot image stays stock regarding NoMount. The run uploads `nomount.ko`. Drop that file into the `lkm/` folder of the NoMount module zip, then flash the module from KernelSU or APatch. |

`builtin` and `lkm` are different kernels. Do not load the LKM on a kernel that already has NoMount built in.

## Add a kernel source

Add one object to [config/sources.json](config/sources.json). The workflow input is a free string, so you do not edit the YAML.

Git tree:

```json
"lineage": {
  "display": "LineageOS",
  "rom": "LineageOS",
  "fetch": "git",
  "repo": "LineageOS/android_kernel_xiaomi_sm8450",
  "ref": "lineage-23.2",
  "defconfig_mode": "gki_fragments",
  "toolchain": "llvm-22.1.8",
  "modules_src": "../sm8450-modules/qcom/opensource",
  "modules_list": "config/techpack-sm8450.txt",
  "extra": [
    {"repo": "LineageOS/android_kernel_xiaomi_sm8450-modules", "ref": "lineage-23.2", "dest": "../sm8450-modules"}
  ]
}
```

`defconfig_mode` is `single`, `gki_fragments`, or `auto`. Fragments default to the device file (`vendor/<device>_GKI.config` and the usual GKI overlays). Set `defconfig` to override the single-defconfig name. `toolchain` is `android-r416183b` or `llvm-22.1.8`.

Manifest tree (same shape as AOSPA):

```json
"myrom": {
  "display": "My ROM",
  "rom": "My ROM",
  "fetch": "manifest",
  "manifest_repo": "owner/kernel_manifest",
  "manifest_ref": "main",
  "manifest_file": "default.xml",
  "kernel_path": "kernel_platform/xiaomi/sm8450",
  "manifest_skip": ["prebuilts/clang", "prebuilts-master", "gcc/linux-x86"],
  "defconfig_mode": "gki_fragments",
  "toolchain": "llvm-22.1.8"
}
```

One-off, without editing JSON: set `kernel_source` to `custom`, `custom_fetch` to `git` or `manifest`, and fill `custom_repo` / `custom_ref`. `auto` picks fragments when `vendor/<device>_GKI.config` exists, otherwise `<device>_defconfig`.

`source_ref` overrides the kernel revision. On a manifest preset it overrides only the kernel project, not every repo in the XML.

## Add a device

Copy [config/devices/marble.env](config/devices/marble.env) to `config/devices/<name>.env`. Set the codenames, the defconfig or GKI fragments, and the SUSFS branch (`gki-android14-6.1`, and so on). Run the workflow with `device` set to that name.

The AnyKernel3 script only allows `DEVICE_NAME_1` and `DEVICE_NAME_2`.

## Managers

Edit [config/managers.json](config/managers.json). Each entry needs `repo`, `ref`, and `setup` (usually `kernel/setup.sh`). `susfs_ref` replaces `ref` when SUSFS is on. `susfs_fallback_repo` is optional.

## Local resolve check

```bash
RESOLVE_ONLY=1 KERNEL_SOURCE=aospa MANAGER=kernelsu bash scripts/build.sh
```

That writes `release/plan.env` and does not download or compile anything.
