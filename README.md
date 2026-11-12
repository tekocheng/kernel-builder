# Kernel builder

One GitHub Actions workflow that builds a flashable AnyKernel3 zip for Poco F5 (`marble` / `marblein`). Another device only needs one env file. Kernel trees are data in `config/`, not copies of the workflow.

## Run

Actions, **Build Kernel**, **Run workflow**. Device, kernel source, root manager, KernelSU mode, toolchain, LTO, build scope and NoMount are dropdowns. The free-text fields (refs, custom repo) are optional overrides.

Download the zip from the run artifacts. It flashes `boot` and checks the device codename. A run with `draft_release` on also creates a draft GitHub release.

## Inputs

| Input | Values | Notes |
|---|---|---|
| `device` | `marble` | One entry per file in `config/devices/` |
| `kernel_source` | `aospa`, `aosp`, `melt`, `bouquet`, `custom` | Keys of `config/sources.json` |
| `all_sources` | on / off | Builds every source in `sources.json` |
| `source_ref` | text | Overrides the kernel branch, tag, or commit |
| `custom_*` | text / `git`, `manifest` | Only for `kernel_source=custom` |
| `manager` | `none`, `kernelsu`, `kernelsu-next`, `sukisu-ultra`, `resukisu`, `all` | Keys of `config/managers.json` |
| `ksu_mode` | `builtin`, `lkm` | See [KernelSU as LKM](#kernelsu-as-an-lkm) |
| `manager_ref` | text | Overrides the manager branch, tag, or commit |
| `enable_susfs` | on / off | Builtin mode only |
| `nomount` | `off`, `builtin`, `lkm` | See [NoMount](#nomount) |
| `toolchain` | `auto`, `android-r596125`, `llvm-23.1.5` | `auto` follows the source preset |
| `lto` | `thin`, `none`, `full` | See [LTO](#lto) |
| `build_scope` | `image-only`, `full` | `full` adds in-tree modules, dtbs, and the SM8450 techpack list |
| `ccache` | on / off | Compiler cache between runs |

## Kernel sources

| Key | Tree | Toolchain | ROM |
|---|---|---|---|
| `aospa` | [aospa-shadedark/kernel_manifest](https://github.com/aospa-shadedark/kernel_manifest) `calcite-xiaomi-sm8450` | `android-r596125` | Paranoid Android |
| `aosp` | [aosp-pablo/android_kernel_xiaomi_sm8450](https://github.com/aosp-pablo/android_kernel_xiaomi_sm8450) `17` | `llvm-23.1.5` | LOS-based |
| `melt` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble) `melt-rebase` | `llvm-23.1.5` | HyperOS |
| `bouquet` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble) `bouquet_ci` | `llvm-23.1.5` | AOSP / LOS-based |

`aospa` reads `default.xml` and clones the GitHub projects in it. The AOSP clang and host gcc prebuilts are skipped (they are multi-gigabyte and unused). The compiler comes from the `toolchain` input.

## Toolchains

| Name | Source | Notes |
|---|---|---|
| `android-r596125` | [Neebe3289/aosp-clang](https://github.com/Neebe3289/aosp-clang) release `clang-22.0.2-15682573` (Clang 22.0.2, based on r596125), about 1 GB | Replace the link with `ANDROID_CLANG_URL` (top of `scripts/build.sh`) |
| `llvm-23.1.5` | Upstream [llvm-project](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.5) release, about 1.9 GB | Make jobs are capped at 2 to stay inside runner memory |

Toolchains are cached between runs, but only after a successful run. The `android-clang/` and `llvm-23.1.5/` folders are in the cache path.

## LTO

`thin` is the default and the safe choice on GitHub-hosted runners (16 GB RAM). `full` links the whole kernel in one process and needs about 32 GB. On a smaller machine the build prints a warning and uses `thin` instead, because the runner otherwise kills the linker and drops the job. `none` is the fastest and uses the least memory.

## Root managers

`manager` picks the root manager. `none` builds the kernel without one.

### Builtin (default)

The manager is compiled into the Image. Flash the zip and you are done.

- Official KernelSU has no in-tree SUSFS, so the build applies `10_enable_susfs_for_ksu.patch` from the same SUSFS commit, then the `50_add_susfs_in_gki-android12-5.10.patch` kernel patch.
- KernelSU-Next tries the official tree first. If that patch does not apply, it falls back to `pershoot/KernelSU-Next` `dev-susfs`.
- SukiSU Ultra with SUSFS checks out `builtin`. ReSukiSU already ships `KSU_SUSFS`.
- Some kernel trees list KernelSU as a submodule. The build removes that stale folder before running `setup.sh`, so the chosen `manager` and `manager_ref` are used.

### KernelSU as an LKM

`ksu_mode=lkm` builds `kernelsu.ko` instead of putting KernelSU in the Image.

- The Image in the zip has no KernelSU. The run also uploads `<zip name>-kernelsu.ko`.
- `kernelsu.ko` matches this Image and config only. Do not load it on another kernel.
- Patch your boot image with the module:

  ```sh
  ksud boot-patch -b <boot.img> --module kernelsu.ko --kmi <kmi>
  ```

  Use `init_boot.img` if your device has that partition.
- Official KernelSU only. The other managers stop with an error. With `manager=all` only `kernelsu` is built.
- SUSFS is turned off in this mode (a warning says so).
- If the build tree has no `Module.symvers`, the first LKM build also runs the kernel `modules` build once. That adds time.
- The build runs the upstream `check_symbol` tool against `vmlinux` and warns when a symbol is missing.

## SUSFS

[simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu) branch `gki-android12-5.10`. Override it with `susfs_branch` and `susfs_ref`. `manager=none` cannot enable SUSFS, and neither can `ksu_mode=lkm`.

Vendor trees drift. If a hunk fails, the log says so. Pin `source_ref` or `manager_ref`, or refresh the SUSFS branch for that device.

## NoMount

[maxsteeel/nomount](https://github.com/maxsteeel/nomount), integrated with upstream `kernel/setup.sh`.

| Input | Result |
|---|---|
| `off` | Not included |
| `builtin` | `CONFIG_NOMOUNT=y` inside the kernel image |
| `lkm` | The Image has no NoMount. The run uploads `nomount.ko`. Drop it into the `lkm/` folder of the NoMount module zip, then flash that module from KernelSU or APatch. |

`builtin` and `lkm` are different kernels. Do not load the LKM on a kernel that already has NoMount built in.

## Build outputs

| File | Content |
|---|---|
| `<device>-<source>-<manager>-<susfs>-<nomount>-r<run>.zip` | AnyKernel3 zip (`<manager>` ends in `-lkm` for LKM builds) |
| `*.sha256` | Checksum of the zip |
| `*-kernelsu.ko` | KernelSU module, `ksu_mode=lkm` only |
| `*-nomount.ko` | NoMount module, `nomount=lkm` only |
| `build-info.txt`, `plan.env` | What was built and from which commits |
| `modules.tar.gz`, `dtbs.tar.gz` | `build_scope=full` only |

## Add a kernel source

Add one object to [config/sources.json](config/sources.json), then add its key to the `kernel_source` options in `.github/workflows/build.yml`. GitHub cannot fill a dropdown from a file. For a one-off run, pick `custom` and fill `custom_repo` / `custom_ref`.

Git tree:

```json
"lineage": {
  "display": "LineageOS",
  "rom": "LineageOS",
  "fetch": "git",
  "repo": "LineageOS/android_kernel_xiaomi_sm8450",
  "ref": "lineage-23.2",
  "defconfig_mode": "gki_fragments",
  "toolchain": "llvm-23.1.5",
  "modules_src": "../sm8450-modules/qcom/opensource",
  "modules_list": "config/techpack-sm8450.txt",
  "extra": [
    {"repo": "LineageOS/android_kernel_xiaomi_sm8450-modules", "ref": "lineage-23.2", "dest": "../sm8450-modules"}
  ]
}
```

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
  "toolchain": "android-r596125"
}
```

`defconfig_mode` is `single`, `gki_fragments`, or `auto`. Fragments default to the device file. Set `defconfig` to override the single-defconfig name. `auto` picks fragments when the `vendor/*_GKI.config` files exist, otherwise `<device>_defconfig`.

`source_ref` overrides the kernel revision. On a manifest preset it overrides only the kernel project, not every repo in the XML.

## Add a device

Copy [config/devices/marble.env](config/devices/marble.env) to `config/devices/<name>.env`. Set the codenames, the defconfig or GKI fragments, and the SUSFS branch (`gki-android14-6.1`, and so on). Add the name to the `device` options in the workflow.

The AnyKernel3 script only allows `DEVICE_NAME_1` and `DEVICE_NAME_2`.

## Add a manager

Edit [config/managers.json](config/managers.json), then add the key to the `manager` options in the workflow. Each entry needs `repo`, `ref`, and `setup` (usually `kernel/setup.sh`). `susfs_ref` replaces `ref` when SUSFS is on. `susfs_fallback_repo` is optional. Add `"lkm": true` only after the manager builds as a module with the recipe in `scripts/build.sh`.

## Add a toolchain

Add a case to `fetch_toolchain` in `scripts/build.sh`, add the name to the allowed set in `scripts/plan.py` and to the `toolchain` options in the workflow, and add its folder to the cache path.

## Local resolve check

```bash
RESOLVE_ONLY=1 SKIP_APT=1 KERNEL_SOURCE=aospa MANAGER=kernelsu bash scripts/build.sh
```

This writes `release/plan.env` and does not download or compile anything.

## Troubleshooting

| Log message | Cause and fix |
|---|---|
| `Unable to fetch ... @ ...` | Wrong branch, tag, or commit in `source_ref` or the preset |
| `Manager setup did not create a kernel Kconfig` | The manager setup failed. Check the lines before it. Pin `manager_ref` if upstream changed |
| `SUSFS ... patch does not apply` | Pin `manager_ref` or `source_ref`, or change `susfs_branch` / `susfs_ref` |
| `The runner has received a shutdown signal` after `LTO vmlinux.o` | Out of memory. Use `lto=thin` |
| `curl: (22)` while fetching a toolchain | The download link moved. Update `ANDROID_CLANG_URL` or the LLVM URL in `scripts/build.sh` |

## Credits

This builder only glues other people's work together. All credit goes to their authors.

**Kernel sources**

- [aospa-shadedark](https://github.com/aospa-shadedark): AOSPA kernel manifest and SM8450 kernel trees. The manifest also pulls build tooling from [pa-gr](https://github.com/pa-gr).
- [aosp-pablo](https://github.com/aosp-pablo): AOSP / LineageOS-based SM8450 kernel, modules and devicetrees.
- [Pzqqt](https://github.com/Pzqqt): Melt and Bouquet kernels for marble.

**Root managers and patches**

- [tiann/KernelSU](https://github.com/tiann/KernelSU): official KernelSU.
- [KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next) and [pershoot/KernelSU-Next](https://github.com/pershoot/KernelSU-Next) (`dev-susfs` fallback).
- [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) and [ReSukiSU](https://github.com/ReSukiSU/ReSukiSU).
- [simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu): SUSFS kernel and manager patches.
- [maxsteeel/nomount](https://github.com/maxsteeel/nomount): NoMount.

**Toolchains and packaging**

- [Neebe3289/aosp-clang](https://github.com/Neebe3289/aosp-clang): prebuilt AOSP Clang releases, built from [Android's clang prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86).
- [LLVM Project](https://github.com/llvm/llvm-project): upstream LLVM releases.
- [osm0sis/AnyKernel3](https://github.com/osm0sis/AnyKernel3): flashable zip template.

**Reference builders**

- [mohdakil2426/marble-kernel-builder](https://github.com/mohdakil2426/marble-kernel-builder)
- [bryanyee33/aospa-gki-kernel-build](https://github.com/bryanyee33/aospa-gki-kernel-build)
- [aosp-pablo/KernelSU-Next-marble](https://github.com/aosp-pablo/KernelSU-Next-marble)
