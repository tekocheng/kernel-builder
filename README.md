# Kernel Builder

A configurable GitHub Actions builder for Android kernels. The current configuration targets the **Poco F5 / Redmi Note 12 Turbo** (`marble` / `marblein`) and packages the compiled kernel image into a flashable **AnyKernel3** ZIP.

Kernel sources, root managers, toolchains, and device-specific values are kept in `config/`. The workflow is the entry point; the scripts resolve those configuration files and build each requested source/manager combination.

> **Current scope:** the workflow currently exposes one device (`marble`) and four predefined kernel sources. The configuration is structured so more devices and sources can be added, but adding a device also requires updating the workflow's device dropdown and checking its AnyKernel3 installer settings.

## What the workflow produces

- Builds the kernel `Image` target, then detects the available boot image in this order: `Image`, `Image.gz`, `Image.gz-dtb`.
- Packages that image into an AnyKernel3 ZIP configured to check the device codename and write the **`boot`** partition.
- Builds on a GitHub-hosted `ubuntu-24.04` runner; no self-hosted server is required.
- Uploads a separate Actions artifact for each source/manager combination. Artifacts are retained for 14 days.
- Writes `build-manifest.json` with source/project commits, manager commit when discoverable, feature settings, toolchain version/hash, and output checksums.
- Writes `project-commits.tsv` so manifest and extra repositories can be audited by their resolved commit SHA.

The AnyKernel3 installer has `do.modules=0`, so the flashable ZIP installs the kernel image only. When `build_scope=full` produces module and DTB archives, those archives are separate build outputs; they are not installed by the AnyKernel3 ZIP.

## Run a build

1. Push or fork this repository to GitHub.
2. Open **Actions** → **Build Kernel** → **Run workflow**.
3. Choose the device, source, manager, and build options described below.
4. Open the completed workflow run and download the artifact for the desired source/manager pair.
5. Check `build-info.txt` and the ZIP name before flashing. Only flash a build that matches the device and ROM/kernel base it was built for.

The build job runs on `ubuntu-24.04`, has a 180-minute timeout, frees some preinstalled runner disk space, and creates a 16 GB swap file. The matrix uses `fail-fast: false` and `max-parallel: 2`: a failed combination does not cancel the others, and no more than two matrix builds run concurrently. The `Validate Builder` workflow also runs configuration checks, unit tests, and syntax checks on pushes and pull requests.

### Recommended first build

For the first test, start with one source and one manager rather than enabling the full matrix. The current workflow defaults are `kernel_source=aospa`, `manager=kernelsu`, `enable_susfs=true`, `enable_nomount=false`, `toolchain=auto`, `lto=thin`, `build_scope=image-only`, and `ccache=true`. Leave `source_ref` and `manager_ref` empty to use the configured presets. These defaults are not a guarantee of compatibility with every ROM: select the source that matches the ROM/kernel base on the target device.

## Workflow inputs

The values below match the inputs declared in `.github/workflows/build.yml`.

| Input | Available values / default | Description |
|---|---|---|
| `device` | `marble` (default) | Device config file: `config/devices/marble.env`. Add a workflow dropdown option when adding another device. |
| `kernel_name` | Text / empty | Overrides `CONFIG_LOCALVERSION`. Empty uses the device file's `KERNEL_NAME`; for `marble`, that value is `Imu`. A leading `-` is added automatically when needed. |
| `kernel_source` | `aospa` (default), `aosp`, `melt`, `bouquet`, `custom` | Selects a key in `config/sources.json`, or a one-off custom source. |
| `all_sources` | `false` (default) | Builds every entry in `config/sources.json`. It cannot be combined with `kernel_source=custom`; when enabled, the selected source is replaced by the configured source list. |
| `source_ref` | Text / empty | Overrides a source revision. For a Git source it overrides the kernel repository ref. For a predefined manifest source it overrides only the kernel project revision, not the manifest revision or every project in the manifest. Custom-source behavior is described below. |
| `custom_repo` | Text / empty | Required for `kernel_source=custom`. Use `owner/repository` or a supported Git URL. For `custom_fetch=manifest`, this is the manifest repository. |
| `custom_ref` | Text / empty | Required for a custom source unless `source_ref` is supplied. For Git, this is the kernel repository ref; for a manifest, it is the manifest repository ref. |
| `custom_fetch` | `git` (default), `manifest` | Selects how the custom source is fetched. |
| `custom_kernel_path` | Text / empty | Optional path to the kernel tree inside the fetched repository/manifest. Defaults to `.` for Git and `kernel_platform/xiaomi/sm8450` for a custom manifest. |
| `manager` | `kernelsu` (default), `none`, `kernelsu-next`, `sukisu-ultra`, `resukisu`, `all` | Selects the root manager. `all` builds every entry in `config/managers.json`, including `none`. |
| `manager_ref` | Text / empty | Overrides the selected manager's branch, tag, or commit. If empty, the manager's configured ref is used (or its SUSFS-specific ref when applicable). |
| `enable_susfs` | `true` (default), `false` | Enables the SUSFS kernel and manager integration when the selected manager supports it. `manager=none` disables SUSFS. |
| `susfs_ref` | Text / empty | Optional SUSFS commit or tag. Empty uses the tip of the selected SUSFS branch. |
| `susfs_branch` | Text / empty | SUSFS branch to fetch. Empty uses the device default; for `marble`, `gki-android12-5.10`. |
| `enable_nomount` | `false` (default), `true` | Integrates NoMount into the kernel. This is a built-in kernel option, not a separate module build. |
| `nomount_ref` | Text / empty | NoMount branch or tag. Empty uses the device default; for `marble`, `dev`. |
| `toolchain` | `auto` (default), `android-r596125`, `llvm-23.1.5` | Selects a toolchain from `config/toolchains.json`. `auto` prefers the source's configured toolchain, then the global default. |
| `toolchain_url` | HTTPS URL / empty | Optional direct link to a `.tar.gz` or `.tar.xz` compiler archive. When supplied, it overrides `toolchain` for that run. The archive must contain `bin/clang` at its root or within the supported directory depth. The URL must be HTTPS; embedded username/password credentials are rejected. The workflow log and build metadata do not expose URL credentials, query strings, or fragments. The uploaded `plan.env` is sanitized by an exit trap, including when a later build step fails. |
| `toolchain_sha256` | 64-character SHA-256 / empty | Optional expected checksum for the selected archive. A mismatch stops the build before extraction. When omitted, the builder still records the downloaded archive's actual checksum but cannot verify it against a trusted expected value. |
| `lto` | `thin` (default), `none`, `full` | Selects the kernel LTO configuration. See [LTO](#lto). |
| `build_scope` | `image-only` (default), `full` | `image-only` builds the flashable kernel image. `full` also builds in-tree modules and DTBs, and builds the configured external SM8450 techpack modules where the source provides a techpack list. |
| `ccache` | `true` (default), `false` | Enables compiler caching. The workflow also caches toolchain files, ccache data, and the ThinLTO cache between runs. |
| `draft_release` | `false` (default), `true` | On a fully successful build matrix, creates a draft GitHub release containing the ZIP files and their SHA-256 checksums. |

### Build matrix behavior

`all_sources` and `manager=all` expand into a matrix. If both are enabled, the workflow builds the Cartesian product of all configured sources and all configured managers. There are currently four sources and five manager entries (including `none`), so that combination schedules 20 build jobs.

Each matrix job has its own artifact named:

```text
<device>-<source>-<manager>-r<run-number>
```

A draft release is created only when the complete build job/matrix succeeds. Its tag and title use the device and workflow run number, for example `marble-r123`. `max-parallel: 2` limits active matrix builds to two at a time; it does not reduce the total number of combinations.

**Matrix-wide override warning:** `source_ref` is passed to every source in the matrix, and `manager_ref` is passed to every manager. When using `all_sources`, leave `source_ref` empty unless the same branch, tag, or commit is valid for every selected source. Likewise, when `manager=all`, leave `manager_ref` empty unless that ref exists and is appropriate in every manager repository. A single override is not independently selected for each matrix entry. The matrix planner emits a warning when a shared override is supplied across multiple sources or managers. It also warns if one `toolchain_sha256` is applied to `all_sources` while `toolchain=auto` selects different source-specific compilers.

## Configured kernel sources

The predefined sources are declared in [`config/sources.json`](config/sources.json).

| Key | Repository / revision | Fetch method | Intended ROM / base | Toolchain (`auto`) |
|---|---|---|---|---|
| `aospa` | [aospa-shadedark/kernel_manifest](https://github.com/aospa-shadedark/kernel_manifest), `calcite-xiaomi-sm8450` | `manifest` | Paranoid Android (Calcite) | `android-r596125` |
| `aosp` | [aosp-pablo/android_kernel_xiaomi_sm8450](https://github.com/aosp-pablo/android_kernel_xiaomi_sm8450), `17` | `git` | AOSP / LOS-based | `llvm-23.1.5` |
| `melt` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble), `melt-rebase` | `git` | HyperOS | `llvm-23.1.5` |
| `bouquet` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble), `bouquet_ci` | `git` | AOSP / LOS-based | `llvm-23.1.5` |

**ROM compatibility matters.** The `melt` preset is labelled for HyperOS in its source configuration. Do not assume a kernel built for one ROM/base is interchangeable with another.

### Source-specific fetch details

- **AOSPA:** the builder clones the manifest and reads `default.xml`, including nested `<include>` files. It clones projects using HTTPS, SSH, or `git://` remote fetch URLs, while skipping paths/names matching `manifest_skip`. The large AOSP Clang and host GCC prebuilts are skipped; the selected toolchain input is used instead.
- **AOSP:** the kernel repository is cloned along with the configured modules and device-tree repositories in the `extra` list.
- **Melt / Bouquet:** each uses a single kernel Git repository and its own configured defconfig and toolchain.

For predefined Git sources, `source_ref` replaces the configured kernel ref. For predefined manifest sources, it replaces the revision of the project at `kernel_path`; it does not change the manifest branch or all other project revisions.

## Toolchains

Toolchain definitions live in [`config/toolchains.json`](config/toolchains.json).

| Key | Compiler source | Configuration |
|---|---|---|
| `android-r596125` | [Neebe3289/aosp-clang](https://github.com/Neebe3289/aosp-clang), release `clang-22.0.2-15682573` | AOSP Clang 22.0.2 based on Android r596125. |
| `llvm-23.1.5` | [LLVM Project](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.5) | Upstream LLVM 23.1.5; `max_jobs=2` caps parallel make jobs for this toolchain. It is marked as the global default. |

The builder downloads and safely extracts the selected archive, locates `bin/clang`, and adds that toolchain's `bin` directory to `PATH`. Archive paths and links are checked before extraction. The workflow caches the `toolchains/` directory using a cache identity that includes the toolchain URL and expected checksum. A `toolchain_url` override takes precedence over the named toolchain and is stored in a URL-derived toolchain directory. Supply `toolchain_sha256` when a trusted checksum is available; a cached archive is reused only when its recorded checksum matches the expected value.

## LTO

- `thin` enables Clang ThinLTO and uses a wrapper that limits ThinLTO linker jobs (default: 2). It is the workflow default and also uses a persistent ThinLTO cache directory through Actions cache.
- `none` disables the supported Clang LTO options and enables the kernel's no-LTO option where available.
- `full` enables full Clang LTO. The workflow creates a 16 GB swap file. The build checks **RAM + swap**; if the total is below approximately 30 GiB, it prints a warning and automatically switches to `thin` to avoid an out-of-memory failure. Full LTO can be slow when the runner relies heavily on swap.

## Root managers

Manager definitions are stored in [`config/managers.json`](config/managers.json). `none` builds without a root manager. The other configured choices are:

| Key | Manager | Configured source |
|---|---|---|
| `kernelsu` | Official KernelSU | [tiann/KernelSU](https://github.com/tiann/KernelSU), `main` |
| `kernelsu-next` | KernelSU-Next | [KernelSU-Next/KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next), `dev` |
| `sukisu-ultra` | SukiSU Ultra | [SukiSU-Ultra/SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra), `main` |
| `resukisu` | ReSukiSU | [ReSukiSU/ReSukiSU](https://github.com/ReSukiSU/ReSukiSU), `main` |

The builder fetches the configured manager's `setup` script and runs it in the kernel tree. Before setup, it removes stale KernelSU/KernelSU-Next directories or known in-tree locations so that a previously embedded manager does not silently replace the selected manager. It then checks that the expected manager Kconfig was created and that `CONFIG_KSU` remains enabled after `olddefconfig` (`y` or `m`).

### Important mode limitation

The current workflow has **no `ksu_mode` input and no KernelSU LKM packaging step**. KernelSU is integrated through the selected manager's setup script and built according to the resulting kernel configuration. The workflow does not produce a separate `kernelsu.ko` file or run the documented `ksud boot-patch` flow.

### Manager-specific SUSFS handling

- **Official KernelSU:** when its Kconfig does not already define `KSU_SUSFS`, the builder applies `10_enable_susfs_for_ksu.patch` from the selected SUSFS checkout.
- **KernelSU-Next:** it tries the configured official tree first. If the manager-side SUSFS patch cannot be applied, it can fall back to `pershoot/KernelSU-Next` at `dev-susfs`.
- **SukiSU Ultra:** its manager entry sets `susfs_ref` to `builtin`; when SUSFS is enabled and no `manager_ref` override is supplied, that branch is selected.
- **ReSukiSU:** its configured tree is expected to provide `KSU_SUSFS` already; the builder skips the manager-side patch when that Kconfig option exists.

## SUSFS

The current device configuration points to [simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu), branch `gki-android12-5.10` for `marble`. The builder:

1. Fetches the selected SUSFS branch and, when provided, checks out `susfs_ref`.
2. Adds the manager-side SUSFS Kconfig support when the selected manager tree does not already contain `KSU_SUSFS`.
3. Applies the kernel patch named for the selected branch (for marble, `50_add_susfs_in_gki-android12-5.10.patch`) unless the kernel tree already references `susfs.o` in `fs/Makefile`.
4. Copies the SUSFS kernel patch files into the kernel tree and verifies that `CONFIG_KSU_SUSFS=y` survives `olddefconfig`.

`manager=none` cannot use SUSFS. A manager entry without `susfs: true` triggers a warning and is built without SUSFS. Kernel and manager trees can change over time; a patch-context failure usually means the selected source/manager/SUSFS revisions are not compatible. Pin compatible refs or update the device's SUSFS branch as appropriate.

## NoMount

NoMount is controlled by the Boolean `enable_nomount` input. When enabled, the builder downloads and runs `kernel/setup.sh` from the device's configured NoMount repository/ref (for marble: [maxsteeel/nomount](https://github.com/maxsteeel/nomount), `dev`), then enables `CONFIG_NOMOUNT=y` and verifies that it remains enabled after `olddefconfig`.

**NoMount is integrated directly into the kernel image.** The current workflow supports this built-in integration only; it does not provide a separate-module build mode.

## Build scope

| Value | What is built |
|---|---|
| `image-only` | Kernel image only. This is the default and is the image packaged into AnyKernel3. |
| `full` | Kernel image, in-tree `modules` and `dtbs` targets, plus external techpack modules when the selected source defines `modules_src` and `modules_list`. |

The SM8450 techpack module list is [`config/techpack-sm8450.txt`](config/techpack-sm8450.txt). It is used only by sources that reference it in `config/sources.json` (currently `aospa` and `aosp`). Missing individual module directories in that list are skipped with a warning. `melt` and `bouquet` do not currently define that external techpack list.

When files are produced, `full` adds `modules.tar.gz` and/or `dtbs.tar.gz` to the build outputs. These archives are not inserted into the AnyKernel3 ZIP. Missing techpack directories remain optional and are skipped with a warning; the exact missing entries are written to `skipped-techpack.txt` so partial techpack coverage is visible in the artifact.

## Build outputs

Each build writes to `release/` and the workflow uploads that directory as its Actions artifact.

| Output | Description |
|---|---|
| `<device>-<source>-<manager>-<susfs-tag>-<nomount-tag>-r<run>.zip` | Flashable AnyKernel3 ZIP containing the kernel image. `susfs-tag` is `susfs` or `nosusfs`; `nomount-tag` is `nm-on` or `nm-off`. |
| `<zip-name>.sha256` | SHA-256 checksum for the ZIP. |
| `Image`, `Image.gz`, or `Image.gz-dtb` | The raw compiled image copied into `release/`, when that is the image produced by the kernel tree. |
| `build-info.txt` | Human-readable summary, including ZIP checksum and links to provenance files. |
| `build-manifest.json` | Machine-readable provenance: resolved kernel/project commits, manager commit when discoverable, SUSFS/NoMount metadata, compiler version/hash, build options, and output checksums. |
| `project-commits.tsv` | Resolved commit SHA for each manifest or extra Git project. |
| `projects.tsv` | Manifest project URL, requested revision, and checkout path when manifest fetch is used. |
| `plan.env` | Resolved build configuration used by the script. The toolchain URL is redacted to remove credentials, query strings, and fragments before the file is uploaded. |
| `kernel-commit.txt`, `manager-commit.txt` | Resolved kernel and manager commits. The manager commit may be `unknown` if its setup script does not leave Git metadata. |
| `manifest-commit.txt`, `anykernel-commit.txt` | Manifest checkout and AnyKernel3 template commits when those repositories are used. |
| `manager-setup.sha256` | Checksum of the manager setup script that was fetched, when a manager is enabled. |
| `susfs-commit.txt`, `susfs-version.txt` | SUSFS revision/version information when available. |
| `toolchain-version.txt`, `toolchain-archive.sha256` | Compiler version and actual downloaded archive checksum when available. |
| `skipped-techpack.txt` | Missing optional techpack directories skipped during `build_scope=full`, when any are absent. |
| `nomount-setup.sha256` | SHA-256 of the NoMount setup script fetched for the build, when enabled. |
| `modules.tar.gz`, `dtbs.tar.gz` | Produced only when `build_scope=full` and the corresponding files exist. |
| `ccache-stats.txt` | ccache statistics when ccache is enabled and available. |

The ZIP filename does not include the custom `kernel_name`; the selected name is reflected in the AnyKernel3 kernel string and `build-info.txt`.

### Reproducible builds

Most presets use branch names, which can move as upstream repositories are updated. For a repeatable build, record the selected commits and prefer full commit SHAs for `source_ref`, `manager_ref`, `susfs_ref`, and `nomount_ref` instead of relying on moving branches. Also pin `ANYKERNEL_REF` in the device file if the packaging template must remain fixed.

`build-manifest.json` records resolved commits for the kernel and each manifest/extra project. It also records the requested and effective manager repository/ref (including a SUSFS fallback, if used), the manager commit when the setup script leaves a Git checkout, plus the actual compiler archive SHA-256 and toolchain version. For strongest repeatability, provide full commit SHAs for source/manager/SUSFS/NoMount refs and a trusted `toolchain_sha256`. A checksum generated by the builder is useful for later comparison, but is not a substitute for checking it against a trusted upstream checksum on the first download.

## Add a kernel source

Add a source object to [`config/sources.json`](config/sources.json). To select it directly in the Actions UI, also add its key to the `kernel_source` options in `.github/workflows/build.yml`. GitHub Actions does not populate a choice dropdown from the JSON file automatically. The new source is included in `all_sources` once it is present in `sources.json` (unless it is `custom`, which is a special one-off input and is not stored there).

### Git source example

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
    {
      "repo": "LineageOS/android_kernel_xiaomi_sm8450-modules",
      "ref": "lineage-23.2",
      "dest": "../sm8450-modules"
    }
  ]
}
```

`extra` repositories are cloned after the main Git tree, to paths relative to the kernel directory. `modules_src` is also relative to the kernel directory; `modules_list` is relative to the repository root.

### Manifest source example

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

The manifest parser expands nested `<include>` files, reads `<remote>`, `<default>`, and `<project>` entries, applies common `<extend-project>` changes (`remote`, `revision`, and `dest-path`), and removes entries selected by `<remove-project>`. Project remotes may use HTTPS, SSH, or `git://`; the builder no longer silently drops non-GitHub remotes. `manifest_skip` entries are substring matches against each project's path and name. `kernel_path` must match the final manifest path of the kernel project.

**Manifest parser limitations:** `<submanifest>` and nested `<project>` entries are not supported and stop the build with an explicit error. Project-level `<copyfile>` and `<linkfile>` entries are currently reported as warnings but are not applied. Flatten or adapt a manifest that relies on those operations before using it. Project paths and include paths are checked to prevent absolute paths and `..` traversal outside the checkout. Duplicate or overlapping project checkout paths are rejected rather than allowing one clone to overwrite another.

### Defconfig settings

`defconfig_mode` supports:

- `single`: uses the source's `defconfig` value, or the device's `DEFCONFIG_SINGLE` when the source does not specify one.
- `gki_fragments`: starts from `gki_defconfig` and merges the source's `config_fragments`, or the device's `GKI_FRAGMENTS` when `config_fragments` is not provided.
- `auto`: checks whether `gki_defconfig` and all configured GKI fragments exist. If they do, it uses `gki_fragments`; otherwise it uses the configured single defconfig when present. If that is unavailable but `gki_defconfig` exists, it uses `gki_defconfig` as a single defconfig. It stops with an error if no usable defconfig is found.

`source_ref` overrides the kernel revision for the selected source. For a predefined manifest source, only the kernel project revision is overridden; the rest of the manifest stays at its configured revisions.

### Use a one-off custom source

Choose `kernel_source=custom` and fill `custom_repo`, `custom_ref`, and `custom_fetch`. `custom_kernel_path` is optional. A custom Git source defaults to the repository root (`.`); a custom manifest defaults to `kernel_platform/xiaomi/sm8450` and `default.xml`.

For a custom Git source, `source_ref` takes precedence over `custom_ref` when both are supplied. For a custom manifest, `custom_ref` selects the manifest revision; when `source_ref` is also supplied, it takes precedence for the manifest revision and is also passed as the kernel project revision override. `all_sources` cannot be used with `kernel_source=custom`.

## Add a device

1. Copy [`config/devices/marble.env`](config/devices/marble.env) to `config/devices/<name>.env`.
2. Set the device's `ARCH`, `DEVICE_NAME_1`, `DEVICE_NAME_2`, defconfig or GKI fragments, and any device-specific kernel name.
3. Set the SUSFS and NoMount repository/ref values as appropriate. Review `ANYKERNEL_REPO`, `ANYKERNEL_REF`, `KBUILD_BUILD_USER`, and `KBUILD_BUILD_HOST` too.
4. Add the device key to the `device` options in `.github/workflows/build.yml`.
5. Check the AnyKernel3 device check against the target device codenames before flashing.

`ak3/anykernel.sh` receives `DEVICE_NAME_1` and `DEVICE_NAME_2` from the device env file. The current installer targets the `boot` partition (`block=boot`) and enables a device check. A new device may need a different installer configuration; adding an env file alone does not guarantee compatibility.

## Add a manager

Add an entry to [`config/managers.json`](config/managers.json) and add its key to the `manager` options in `.github/workflows/build.yml`. The resolver expects a `display`, `repo`, `ref`, and `setup` value. The setup script must create a Kconfig at one of the paths checked by `scripts/build.sh` (`KernelSU/kernel/Kconfig` or `KernelSU-Next/kernel/Kconfig`).

Optional manager fields:

- `susfs`: set to `true` only when the manager tree supports the required SUSFS integration.
- `susfs_ref`: alternate manager ref used by default when SUSFS is enabled, unless `manager_ref` overrides it.
- `susfs_fallback_repo` and `susfs_fallback_ref`: fallback manager source/ref used by the KernelSU-Next SUSFS path when the primary manager-side patch cannot be applied.

There is no generic LKM build recipe or `lkm` manager flag in the current builder.

## Add or update a toolchain

For a one-run override, paste an HTTPS URL to a `.tar.gz` or `.tar.xz` compiler archive into `toolchain_url`. The archive must contain `bin/clang` where the builder can locate it.

To add a reusable named toolchain, add an entry to [`config/toolchains.json`](config/toolchains.json) and add its key to the `toolchain` options in `.github/workflows/build.yml`:

```json
"llvm-24.1.0": {
  "url": "https://github.com/llvm/llvm-project/releases/download/llvmorg-24.1.0/LLVM-24.1.0-Linux-X64.tar.xz",
  "max_jobs": 2
}
```

`max_jobs` is optional and caps the normal `make -j` job count for that toolchain. An optional `sha256` field can pin the archive checksum; do not add a guessed checksum. `default: true` marks a global fallback toolchain for sources without their own `toolchain` field. `toolchain=auto` prefers a source-specific toolchain first. To change a source's automatic compiler, update its `toolchain` field in `config/sources.json`. Toolchain versions are pinned; a newer upstream release does not change existing builds automatically.

## Local validation and plan check

Run the same configuration checks and unit tests used by GitHub Actions before pushing changes:

```bash
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
bash -n scripts/build.sh
python3 -m compileall -q scripts tests
```

The following command resolves the selected configuration and writes `release/plan.env` without downloading sources or compiling the kernel. The toolchain URL in `release/plan.env` is redacted in both resolve-only and normal builds. The script also applies this redaction from an exit trap, so it still runs when a later build step fails and Actions uploads artifacts.

```bash
RESOLVE_ONLY=1 SKIP_APT=1 KERNEL_SOURCE=aospa MANAGER=kernelsu bash scripts/build.sh
```

Change the environment variables to test another source or manager. The script still needs the repository's JSON/env config files, but does not need the compiler or kernel source for this plan-only check.

## Troubleshooting

| Log / symptom | Likely cause and next step |
|---|---|
| `Unable to fetch ... @ ...` | The repository, branch, tag, or commit is unavailable. Check the preset or override (`source_ref`, `custom_ref`, or `manager_ref`). |
| `Kernel Makefile not found` | `kernel_path` does not point to the kernel tree, or the manifest path does not match the actual project path. |
| `Could not detect a defconfig` / missing GKI fragment | Check `DEFCONFIG_SINGLE`, `GKI_FRAGMENTS`, source `defconfig`, `config_fragments`, and `defconfig_mode`. |
| `Manager setup did not create a kernel Kconfig` | The selected manager setup script did not integrate at a path expected by the builder. Check the manager ref and setup script. |
| `SUSFS ... patch does not apply` | The kernel or manager tree may not match the selected SUSFS branch. Pin compatible source/manager refs or choose a compatible device SUSFS branch. |
| `CONFIG_NOMOUNT=y did not stay enabled` | The kernel tree did not retain NoMount's Kconfig option after `olddefconfig`. Check the NoMount setup integration and kernel compatibility. |
| `The runner has received a shutdown signal` during full LTO | The linker may have run out of memory. Use `lto=thin`; the builder also falls back to thin when detected RAM plus swap is below its threshold. |
| `curl: (22)` while fetching a toolchain | The download URL may have moved or become unavailable. Update `config/toolchains.json` or use `toolchain_url` for a one-off run. |
| `No bin/clang inside ...` | The archive is not a supported Clang package, or `bin/clang` is outside the search depth. |
| `Toolchain SHA-256 mismatch` | The downloaded archive does not match `toolchain_sha256`. Verify the URL and checksum before retrying. |
| `Manifest include not found` / include cycle | Check the include path relative to the manifest checkout and remove circular includes. |
| `Unsupported manifest <submanifest>` | Flatten or adapt the manifest; nested submanifest checkouts are not currently implemented. |
| `Path escapes checkout root` | A configured source path, project path, or extra repository destination attempts to write outside its checkout. Correct the path in the source/device configuration. |

## Credits

This repository coordinates and automates the work of the projects below. Credit belongs to their respective authors.

**Kernel sources**

- [aospa-shadedark](https://github.com/aospa-shadedark): AOSPA kernel manifest and SM8450 kernel trees; the manifest also pulls build tooling from [pa-gr](https://github.com/pa-gr).
- [aosp-pablo](https://github.com/aosp-pablo): AOSP / LineageOS-based SM8450 kernel, modules, and device trees.
- [Pzqqt](https://github.com/Pzqqt): Melt and Bouquet kernels for marble.

**Root managers and patches**

- [tiann/KernelSU](https://github.com/tiann/KernelSU): official KernelSU.
- [KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next) and [pershoot/KernelSU-Next](https://github.com/pershoot/KernelSU-Next): KernelSU-Next and the configured `dev-susfs` fallback.
- [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) and [ReSukiSU](https://github.com/ReSukiSU/ReSukiSU).
- [simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu): SUSFS kernel and manager patches.
- [maxsteeel/nomount](https://github.com/maxsteeel/nomount): NoMount integration.

**Toolchains and packaging**

- [Neebe3289/aosp-clang](https://github.com/Neebe3289/aosp-clang): prebuilt AOSP Clang releases, based on [Android's Clang prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86).
- [LLVM Project](https://github.com/llvm/llvm-project): upstream LLVM releases.
- [osm0sis/AnyKernel3](https://github.com/osm0sis/AnyKernel3): flashable ZIP template.

**Reference builders**

- [mohdakil2426/marble-kernel-builder](https://github.com/mohdakil2426/marble-kernel-builder)
- [bryanyee33/aospa-gki-kernel-build](https://github.com/bryanyee33/aospa-gki-kernel-build)
- [aosp-pablo/KernelSU-Next-marble](https://github.com/aosp-pablo/KernelSU-Next-marble)
