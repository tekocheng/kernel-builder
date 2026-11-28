# Kernel Builder For Android

A configurable GitHub Actions builder for Android kernels. The current configuration targets the **Poco F5 / Redmi Note 12 Turbo** (`marble` / `marblein`) and packages the compiled kernel image into a flashable **AnyKernel3** ZIP.

Kernel sources, root managers, toolchains, and device-specific values are kept in `config/`. The workflow is the entry point; the scripts resolve those configuration files and build each requested source/manager combination.

> **Current scope:** the simple workflow exposes the `marble` device and the predefined kernel sources. The advanced workflow also supports custom Git/manifest sources and one-run overrides. Adding a device still requires updating the workflow dropdowns and checking its AnyKernel3 installer settings.

## What the workflow produces

- Builds the kernel `Image` target, then detects the available boot image in this order: `Image`, `Image.gz`, `Image.gz-dtb`.
- Packages that image into an AnyKernel3 ZIP configured to check the device codename and write the **`boot`** partition.
- Builds on a GitHub-hosted `ubuntu-24.04` runner; no self-hosted server is required.
- In the default `image-menu` mode, uploads one Actions artifact per source with a single AK3 ZIP containing the selected manager variants. In `image-only` or `full` mode, uploads separate artifacts per source/manager combination. Artifacts are retained for 14 days.
- Writes `build-manifest.json` with source/project commits, manager commit when discoverable, feature settings, toolchain version/hash, and output checksums.
- Writes `project-commits.tsv` so manifest and extra repositories can be audited by their resolved commit SHA.

The AnyKernel3 installer has `do.modules=0`, so the flashable ZIP installs the kernel image only. When `build_scope=full` produces module and DTB archives, those archives are separate build outputs; they are not installed by the AnyKernel3 ZIP.

## Run a build

1. Push or fork this repository to GitHub.
2. Open **Actions** → **Build Kernel** → **Run workflow** for the recommended compact menu. Use **Build Kernel Advanced** when you need custom repositories, refs, custom kernel paths, all-sources builds, manager refs, or compiler/SUSFS/NoMount overrides.
3. In the simple workflow, choose the device, source, manager checkboxes, and build options.
4. Open the completed workflow run and download the artifact: one per source in `image-menu` mode, or one per source/manager pair in the other modes.
5. Check `build-info.txt` and the ZIP name before flashing. Only flash a build that matches the device and ROM/kernel base it was built for.

The build job runs on `ubuntu-24.04`, has a 300-minute timeout, frees some preinstalled runner disk space, and creates a 16 GB swap file. The matrix uses `fail-fast: false` and `max-parallel: 2`: a failed combination does not cancel the others, and no more than two matrix builds run concurrently. The `Validate Builder` workflow also runs configuration checks, unit tests, and syntax checks on pushes and pull requests.

Runner disk cleanup and swap setup are implemented in the reusable composite action at `.github/actions/runner-setup/action.yml`. Its policy is configured in `config/runner.json` (40 GiB disk threshold, aggressive/light cleanup profiles, 16 GiB swap for LTO builds, and swappiness 100). The workflow calls this action in the same build job, so cleanup and swap apply to the actual kernel build runner. No additional `workflow_dispatch` inputs are required.

### Simple workflow inputs

`Build Kernel` intentionally exposes only 13 inputs: device, kernel source, five manager checkboxes, SUSFS, NoMount, toolchain, LTO, build scope, and draft release. Compiler cache and uname suffixes use their safe defaults automatically. At least one manager checkbox must be selected.

### Advanced workflow

Use `Build Kernel Advanced` for `kernel_name`, `all_sources`, source and manager refs, custom Git/manifest source fields, and the `advanced_overrides` JSON field. The advanced workflow retains the full set of controls while sharing the same build implementation as the simple workflow.

### Recommended first build

The workflow defaults to a combined AK3 manager menu for one source: `kernel_source=aospa`, official KernelSU selected, `enable_susfs=true`, `enable_nomount=false`, `toolchain=auto`, `lto=thin`, `build_scope=image-menu`, and `ccache=true`. In the Run workflow form, tick one or more manager checkboxes: `build_kernelsu`, `build_kernelsu_next`, `build_sukisu_nova`, `build_kowsu`, and `build_bakasu`. At least one must be selected. The ZIP contains the stock kernel plus the selected variants that the plan allows and the build successfully produces. With SUSFS enabled, KOWSU is rejected because its SUSFS patch is incompatible; set `enable_susfs=false` to build KOWSU without SUSFS. Leave `source_ref` and `manager_ref` empty to use configured presets. Advanced one-run overrides (`susfs_ref`, `susfs_branch`, `nomount_ref`, `toolchain_url`, and `toolchain_sha256`) are supplied as a JSON object in `advanced_overrides`. Select a source that matches the ROM/kernel base on the target device.

## Workflow inputs

The values below match the inputs declared in `.github/workflows/build-advanced.yml`.

| Input | Available values / default | Description |
|---|---|---|
| `device` | `marble` (default) | Device config file: `config/devices/marble.env`. Add a workflow dropdown option when adding another device. |
| `kernel_name` | Text / empty | Overrides `CONFIG_LOCALVERSION`. Empty keeps the source's own `CONFIG_LOCALVERSION`. The `uname_hash` and `uname_run_id` inputs independently control the `-g<hash12>` and `-ab<run id>` suffixes; disabled suffixes are omitted and `-dirty` is suppressed. A leading `-` is added automatically when needed. |
| `kernel_source` | `aospa` (default), `infinityx`, `lineage`, `shinkai`, `lunaris`, `melt`, `bouquet`, `custom` | Selects a key in `config/sources.json`, or a one-off custom source. |
| `all_sources` | `false` (default) | Builds every entry in `config/sources.json`. It cannot be combined with `kernel_source=custom`; when enabled, the selected source is replaced by the configured source list. |
| `source_ref` | Text / empty | Overrides a source revision. For a Git source it overrides the kernel repository ref. For a predefined manifest source it overrides only the kernel project revision, not the manifest revision or every project in the manifest. Custom-source behavior is described below. |
| `custom_repo` | Text / empty | Required for `kernel_source=custom`. Use `owner/repository` or a supported Git URL. For `custom_fetch=manifest`, this is the manifest repository. |
| `custom_ref` | Text / empty | Required for a custom source unless `source_ref` is supplied. For Git, this is the kernel repository ref; for a manifest, it is the manifest repository ref. |
| `custom_fetch` | `git` (default), `manifest` | Selects how the custom source is fetched. |
| `custom_kernel_path` | Text / empty | Optional path to the kernel tree inside the fetched repository/manifest. Defaults to `.` for Git and `kernel_platform/xiaomi/sm8450` for a custom manifest. |
| `build_kernelsu` | `true` (default) / `false` | Build official KernelSU (tiann). |
| `build_kernelsu_next` | `false` (default) / `true` | Build KernelSU-Next. |
| `build_sukisu_nova` | `false` (default) / `true` | Build SukiSU Nova. |
| `build_kowsu` | `false` (default) / `true` | Build KOWSU. With SUSFS enabled, this is rejected because the current fork-specific patch is incompatible. |
| `build_bakasu` | `false` (default) / `true` | Build BakaSU. Select at least one manager. |
| `manager_ref` | Text / empty | Overrides the branch, tag, or commit for every selected manager. |
| `enable_susfs` | `true` (default), `false` | Enables the SUSFS kernel and manager integration when the selected manager supports it. A build without a manager (`MANAGER=none` in a local `scripts/build.sh` run) never uses SUSFS. |
| `advanced_overrides` | JSON object / `{}` | Optional overrides for `susfs_ref`, `susfs_branch`, `nomount_ref`, `toolchain_url`, and `toolchain_sha256`. Example: `{"susfs_branch":"gki-android12-5.10","nomount_ref":"dev"}`. Values must be strings. |
| `lto` | `thin` (default), `none`, `full` | Selects the kernel LTO configuration. See [LTO](#lto). |
| `build_scope` | `image-menu` (default), `image-only`, `full` | `image-menu` builds every selected manager in one job per source and packages stock plus the built variants as one [Patch-menu ZIP](#patch-menu-zip). `image-only` builds one flashable kernel image per manager. `full` also builds in-tree modules and DTBs, and builds the configured external SM8450 techpack modules where the source provides a techpack list. |
| `ccache` | `true` (default), `false` | Enables compiler caching. The workflow also caches toolchain files, ccache data, and the ThinLTO cache between runs. |
| `uname_hash` | `true` (default), `false` | Adds `-g<kernel commit>` to the kernel uname. |
| `uname_run_id` | `auto` (default), `off` / `none`, or your own text | `auto` adds `-ab<run id>`. `off` or `none` adds nothing. Any other text (1 to 24 characters from letters, digits, `.`, `_`, `-`) is added as `-<text>`, for example `r35` gives `-r35`. With `uname_hash` also off and this set to `off`, the uname is the plain release string (kernel version plus `CONFIG_LOCALVERSION`). |
| `draft_release` | `false` (default), `true` | On a fully successful build matrix, creates a draft GitHub release containing the ZIP files and their SHA-256 checksums. |

### Build matrix behavior

For `build_scope=image-only` and `full`, the selected manager checkboxes and `all_sources` expand into a matrix. If both are enabled, the workflow builds the Cartesian product of all configured sources and managers. There are currently seven sources and five manager checkboxes, so ticking all of them schedules 35 build jobs. With `enable_susfs=true` KOWSU cannot be selected (the Plan job stops with an error instead of skipping it), so at most 28 jobs are possible.

With `build_scope=image-menu`, the matrix has one job per source, and that job carries every selected manager, because the menu ZIP packages all of them together. Selecting no manager checkbox stops the run in the Plan job before any build starts.

Each matrix job has its own artifact named:

```text
<device>-<source>-<manager>-r<run-number>
```

In `image-menu` mode `<manager>` is the comma-separated list of the selected managers, for example `marble-aospa-kernelsu,kernelsu-next,sukisu-nova-r<run-number>`.

A draft release is created only when the complete build job/matrix succeeds. Its tag and title use the device and workflow run number, for example `marble-r123`. `max-parallel: 2` limits active matrix builds to two at a time; it does not reduce the total number of combinations.

**Matrix-wide override warning:** `source_ref` is passed to every source in the matrix, and `manager_ref` is passed to every manager. When using `all_sources`, leave `source_ref` empty unless the same branch, tag, or commit is valid for every selected source. Likewise, when selecting multiple manager checkboxes, leave `manager_ref` empty unless that ref exists and is appropriate in every manager repository. A single override is not independently selected for each matrix entry. The matrix planner emits a warning when a shared override is supplied across multiple sources or managers. It also warns if one `toolchain_sha256` is applied to `all_sources` while `toolchain=auto` selects different source-specific compilers.

## Configured kernel sources

The predefined sources are declared in [`config/sources.json`](config/sources.json).

| Key | Repository / revision | Fetch method | Intended ROM / base | Toolchain (`auto`) |
|---|---|---|---|---|
| `aospa` | [aospa-shadedark/kernel_manifest](https://github.com/aospa-shadedark/kernel_manifest), `calcite-xiaomi-sm8450` | `manifest` | Paranoid Android (Calcite) | `android-r596125` |
| `infinityx` | [aosp-pablo/android_kernel_xiaomi_sm8450](https://github.com/aosp-pablo/android_kernel_xiaomi_sm8450), `17` | `git` | AOSP / LOS-based | `llvm-23.1.6` |
| `lineage` | [LineageOS/android_kernel_xiaomi_sm8450](https://github.com/LineageOS/android_kernel_xiaomi_sm8450), `lineage-24.0` | `git` | LineageOS official | `llvm-23.1.6` |
| `shinkai` | [nekoshirro/platform_kernel_xiaomi_marble](https://github.com/nekoshirro/platform_kernel_xiaomi_marble), `17` (modules and devicetrees from branch `16`) | `git` | AOSP / Shinkai Project | `llvm-23.1.6` |
| `lunaris` | [dhanush281/android_kernel_xiaomi_sm8450](https://github.com/dhanush281/android_kernel_xiaomi_sm8450), `lineage-23.2` (modules and devicetrees from branch `16.2`) | `git` | Lunaris AOSP | `llvm-23.1.6` |
| `melt` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble), `melt-rebase` | `git` | HyperOS | `llvm-23.1.6` |
| `bouquet` | [Pzqqt/android_kernel_xiaomi_marble](https://github.com/Pzqqt/android_kernel_xiaomi_marble), `bouquet_ci` | `git` | AOSP / LOS-based | `llvm-slim-23.1.6` |

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
| `android-r596125` | [Google AOSP prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86), branch `main-kernel`, directory `clang-r596125` | Official Google clang-r596125. Fetched with a sparse git checkout of that one directory, so no checksum applies; the checked-out commit is recorded instead. |
| `llvm-23.1.6` | [LLVM Project](https://github.com/llvm/llvm-project/releases/tag/llvmorg-23.1.6) | Upstream LLVM 23.1.6; `max_jobs=2` caps parallel make jobs for this toolchain. It is marked as the global default. |
| `llvm-slim-23.1.6` | [kernel.org slim LLVM](https://mirrors.edge.kernel.org/pub/tools/llvm/) | Slim LLVM 23.1.6 (`llvm-23.1.6-x86_64.tar.xz`); `max_jobs=2`. Not a global default. Used automatically for the `bouquet` source, matching the upstream `bouquet_ci` workflow. |
| `alchemist-llvm-23` | [nekoshirro/Alchemist-LLVM](https://github.com/nekoshirro/Alchemist-LLVM) | Alchemist LLVM 23 (clang 23.0.1), release `lto-20261105`, pinned by SHA-256; `max_jobs=2`. Not a default. |

A toolchain entry is either an archive (`url`) or a git directory (`git`, `branch`, `dir`). For a git entry the builder runs a shallow, filtered clone of the branch and checks out only `dir`, then records the commit in `toolchain-commit.txt` and in `build-manifest.json`. The first run downloads the whole clang directory, which is large; later runs reuse the Actions cache. `toolchain_sha256` is rejected for git entries, because a git checkout has no archive to hash.

For an archive entry, the builder downloads and safely extracts the selected archive, locates `bin/clang`, and adds that toolchain's `bin` directory to `PATH`. Archive paths and links are checked before extraction. The workflow caches the `toolchains/` directory using a cache identity that includes the toolchain URL and expected checksum. A `toolchain_url` override takes precedence over the named toolchain and is stored in a URL-derived toolchain directory. Supply `toolchain_sha256` when a trusted checksum is available; a cached archive is reused only when its recorded checksum matches the expected value.

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
| `sukisu-nova` | SukiSU Nova | [SukiSU-Nova/SukiSU-Nova](https://github.com/SukiSU-Nova/SukiSU-Nova), `main` |
| `bakasu` | BakaSU | [Baka-SU/BakaSU](https://github.com/Baka-SU/BakaSU), `main` |
| `kowsu` | KOWSU | [KOWX712/KernelSU](https://github.com/KOWX712/KernelSU), `master`. Builds without SUSFS only: the official SUSFS patch does not apply to this fork, so `enable_susfs=true` stops the run in the Plan job (and the matrix planner skips it with a warning when expanding all managers). |

The builder fetches the configured manager's `setup` script and runs it in the kernel tree. Before setup, it removes stale KernelSU/KernelSU-Next directories or known in-tree locations so that a previously embedded manager does not silently replace the selected manager. It then checks that the expected manager Kconfig was created and that `CONFIG_KSU` remains enabled after `olddefconfig` (`y` or `m`).

### Important mode limitation

The current workflow has **no `ksu_mode` input and no KernelSU LKM packaging step**. KernelSU is integrated through the selected manager's setup script and built according to the resulting kernel configuration. The workflow does not produce a separate `kernelsu.ko` file or run the documented `ksud boot-patch` flow.

### Manager-specific SUSFS handling

- **Official KernelSU:** when its Kconfig does not already define `KSU_SUSFS`, the builder applies `10_enable_susfs_for_ksu.patch` from the selected SUSFS checkout.
- **KernelSU-Next:** it tries the configured official tree first. If the manager-side SUSFS patch cannot be applied, it can fall back to `pershoot/KernelSU-Next` at `dev-susfs`.
- **SukiSU Nova:** its manager entry sets `susfs_ref` to `builtin`; when SUSFS is enabled and no `manager_ref` override is supplied, that branch is selected.
- **BakaSU:** its configured tree is expected to provide `KSU_SUSFS` already; the builder skips the manager-side patch when that Kconfig option exists.

## SUSFS

The current device configuration points to [simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu), branch `gki-android12-5.10` for `marble`. The builder:

1. Fetches the selected SUSFS branch and, when provided, checks out `susfs_ref`.
2. Adds the manager-side SUSFS Kconfig support when the selected manager tree does not already contain `KSU_SUSFS`.
3. Applies the kernel patch named for the selected branch (for marble, `50_add_susfs_in_gki-android12-5.10.patch`) unless the kernel tree already references `susfs.o` in `fs/Makefile`.
4. Copies the SUSFS kernel patch files into the kernel tree and verifies that `CONFIG_KSU_SUSFS=y` survives `olddefconfig`.

`MANAGER=none` cannot use SUSFS. A manager entry without `susfs: true` triggers a warning and is built without SUSFS. Kernel and manager trees can change over time; a patch-context failure usually means the selected source/manager/SUSFS revisions are not compatible. Pin compatible refs or update the device's SUSFS branch as appropriate.

## NoMount

NoMount is controlled by the Boolean `enable_nomount` input. When enabled, the builder downloads and runs `kernel/setup.sh` from the device's configured NoMount repository/ref (for marble: [maxsteeel/nomount](https://github.com/maxsteeel/nomount), `dev`), then enables `CONFIG_NOMOUNT=y` and verifies that it remains enabled after `olddefconfig`.

**NoMount is integrated directly into the kernel image.** The current workflow supports this built-in integration only; it does not provide a separate-module build mode.

## Build scope

| Value | What is built |
|---|---|
| `image-only` | Kernel image only. This is the default and is the image packaged into AnyKernel3. |
| `full` | Kernel image, in-tree `modules` and `dtbs` targets, plus external techpack modules when the selected source defines `modules_src` and `modules_list`. |

The SM8450 techpack module list is [`config/techpack-sm8450.txt`](config/techpack-sm8450.txt). It is used only by sources that reference it in `config/sources.json` (currently `aospa`, `infinityx`, `lineage`, `shinkai` and `lunaris`). Missing individual module directories in that list are skipped with a warning. `melt` and `bouquet` do not currently define that external techpack list.

When files are produced, `full` adds `modules.tar.gz` and/or `dtbs.tar.gz` to the build outputs. These archives are not inserted into the AnyKernel3 ZIP. Missing techpack directories remain optional and are skipped with a warning; the exact missing entries are written to `skipped-techpack.txt` so partial techpack coverage is visible in the artifact.

## Patch-menu ZIP

`build_scope=image-menu` packages the kernel the way the Bouquet Kernel installer does. One runner builds everything, one build after the other, and the ZIP lets you pick the manager when you flash:

1. **stock**: no root manager.
2. **one build per selected manager**, for example KernelSU, KernelSU-Next and SukiSU Nova, each on a clean tree.
3. **one more build per manager with SUSFS**, when `enable_susfs=true` and the manager supports it.

Between two managers the builder resets the kernel tree (`git checkout` and `git clean`, keeping `out/` so the build stays incremental), applies NoMount again and then the next manager, so managers never stack on each other. Matrix jobs run on separate runners, so with any other scope every selected manager is its own job. With `image-menu` all selected managers share one job per source.

The stock build never contains a manager. A kernel source can already reference the manager's Kconfig from `drivers/Kconfig`, so the builder sets up the first selected manager before the stock build only to make that file exist. `CONFIG_KSU` is then switched off explicitly, because otherwise `olddefconfig` can turn it back on and the stock Image would contain KernelSU. The build stops with an error if `CONFIG_KSU` is still enabled for a build without a manager, and the tree is reset right after the stock build.

The ZIP holds the stock `Image`, one diff per variant in `bs_patches/` (`<manager>.p` and `<manager>-susfs.p`, HDiffPatch diffs against the stock Image), `bs_patches/managers.txt` (key, display name and SHA-1 of each image) and `bs_patches/sha1.env` (SHA-1 of the stock image). At flash time the installer asks with the volume keys:

- For each manager in order: "Install the kernel with <manager> built in?" Vol+ picks it and then asks whether to add SUSFS (Vol+ applies the `-susfs` diff instead). Vol- moves on to the next manager.
- No to every manager, or no key within 20 seconds per question, installs the plain kernel. So an install from an app without key input never hangs.
- The stock image is checked before patching and the result after patching. A mismatch aborts before anything is flashed.

The builder verifies every diff on the runner too: it applies the diff to the stock Image and compares the SHA-1 with the variant it came from. The ZIP is named `<device>-<source>-<manager>_<manager>-menu-r<run>.zip`, and `build-manifest.json` lists the manager commits as `key=commit` pairs.

Limits:

- Kernel image only, like the normal ZIP. It does not install modules, DTBs or `vendor_dlkm`, which some sources need to boot.
- With `enable_nomount`, NoMount is part of every variant, so the diffs only carry the manager and SUSFS.
- A job runs 1 + 2 x managers kernel builds in a row (7 for three managers with SUSFS). The first is a full build, the others are incremental. The job timeout is 300 minutes. The memory peak is the same as for one build, because each link starts after the previous one has finished, but one failed link stops the whole job, so use `lto=thin`. The run warns when `lto=full` is combined with more than one manager.
- Every extra manager adds about 3 MB to the ZIP for its diff, and as much again for its SUSFS diff. The Telegram upload limit is 50 MB.
- The same build number and timestamp are used for all variants so the diffs stay small.
- `ak3/tools-extra/` holds prebuilt `hpatchz` (aarch64) and `keycheck` (ARM) taken from the Bouquet Kernel v5.3 ZIP. See the README in that folder.
- The CI runner builds `hdiffz` from [HDiffPatch](https://github.com/sisong/HDiffPatch) at `v5.1.3` (`HDIFFPATCH_REF`).

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
  "toolchain": "llvm-23.1.6",
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

`uname_suffix` (optional, default `true`) lets one source opt out of both uname suffixes whatever the workflow switches say. No source uses it at the moment.

`builtin_nomount` (optional, default `false`) marks a source whose kernel tree already contains NoMount (currently `shinkai`). For such a source the builder skips the external NoMount setup and no longer forces `CONFIG_NOMOUNT` off, so the source's own setting is kept.

`extra` repositories are cloned after the main Git tree, to paths relative to the kernel directory. `modules_src` is also relative to the kernel directory; `modules_list` is relative to the repository root.

### Telegram notifications

Each build job can send a Telegram message when it succeeds, fails, or is cancelled. It is off until you add two repository secrets (Settings, Secrets and variables, Actions): `TELEGRAM_BOT_TOKEN` (from @BotFather) and `TELEGRAM_CHAT_ID` (your chat or channel ID; send the bot a message first). Without the secrets the step is skipped. The message names the device, source, and manager, and includes the kernel uname, the zip name, and the run link when they exist. A failed notification never fails the build. With `all_sources`, expect one message per build.

When a build succeeds, the zip is sent as a file with that message as its caption (it also carries the zip's SHA-256), so you can flash it straight from the chat. Telegram bots can upload files up to 50 MB; a larger zip is not sent, and the message says so and points to the run page. A failed upload falls back to the plain text message. To keep the text message only, add a repository variable named `TELEGRAM_SEND_ZIP` (Settings, Secrets and variables, Actions, Variables tab) with the value `false`. This is a variable and not a workflow input because GitHub allows at most 25 dispatch inputs.

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

Add an entry to [`config/managers.json`](config/managers.json). The workflow currently exposes five manager checkboxes. When adding a manager, add its checkbox to `.github/workflows/build-advanced.yml` (as a `workflow_dispatch` input and as a `workflow_call` input) and map it in the Plan job's normalization step there. If it should appear in the simple menu, also add the checkbox to `.github/workflows/build.yml` and forward it in the `with:` block; `scripts/validate.py` fails if an input is not forwarded. Keep each `workflow_dispatch` workflow at or below GitHub's 25-input limit: `build-advanced.yml` declares exactly 25 today, so an existing input has to be removed or folded away before a new checkbox fits. The resolver expects a `display`, `repo`, `ref`, and `setup` value. The setup script must create a Kconfig at one of the paths checked by `scripts/build.sh` (`KernelSU/kernel/Kconfig` or `KernelSU-Next/kernel/Kconfig`).

Optional manager fields:

- `aliases`: short names accepted in the `MANAGER` value read by `scripts/plan.py` and `scripts/build.sh` (the workflows themselves use checkboxes), lowercase letters, digits and dashes. They must not repeat another manager key or short name.
- `susfs`: set to `true` only when the manager tree supports the required SUSFS integration.
- `susfs_ref`: alternate manager ref used by default when SUSFS is enabled, unless `manager_ref` overrides it.
- `susfs_blocked`: reason text. When set, `enable_susfs=true` is refused for this manager before any build starts, and the matrix planner leaves it out when expanding all managers.
- `susfs_fallback_repo` and `susfs_fallback_ref`: fallback manager source/ref used by the KernelSU-Next SUSFS path when the primary manager-side patch cannot be applied.

There is no generic LKM build recipe or `lkm` manager flag in the current builder.

## Add or update a toolchain

For a one-run override, paste an HTTPS URL to a `.tar.gz` or `.tar.xz` compiler archive into `toolchain_url`. The archive must contain `bin/clang` where the builder can locate it.

To add a reusable named toolchain, add an entry to [`config/toolchains.json`](config/toolchains.json) and add its key to the `toolchain` options in `.github/workflows/build.yml` and `.github/workflows/build-advanced.yml` (the simple menu only lists supported named toolchains):

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
- [dhanush281](https://github.com/dhanush281): Lunaris AOSP kernel, modules, and device trees (`lineage-23.2` and `16.2`).
- [nekoshirro](https://github.com/nekoshirro): Shinkai Project kernel (`platform_kernel_xiaomi_marble`) with its modules and devicetrees, and the Alchemist LLVM toolchain.
- [LineageOS](https://github.com/LineageOS): official SM8450 kernel, modules, and device trees (`lineage-24.0`).
- [aosp-pablo](https://github.com/aosp-pablo): AOSP / LineageOS-based SM8450 kernel, modules, and device trees.
- [Pzqqt](https://github.com/Pzqqt): Melt and Bouquet kernels for marble.

**Root managers and patches**

- [tiann/KernelSU](https://github.com/tiann/KernelSU): official KernelSU.
- [KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next) and [pershoot/KernelSU-Next](https://github.com/pershoot/KernelSU-Next): KernelSU-Next and the configured `dev-susfs` fallback.
- [SukiSU Nova](https://github.com/SukiSU-Nova/SukiSU-Nova) and [BakaSU](https://github.com/Baka-SU/BakaSU).
- [simonpunk/susfs4ksu](https://gitlab.com/simonpunk/susfs4ksu): SUSFS kernel and manager patches.
- [maxsteeel/nomount](https://github.com/maxsteeel/nomount): NoMount integration.

**Toolchains and packaging**

- [Android Clang prebuilts](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86): official Google clang used by `android-r596125`.
- [LLVM Project](https://github.com/llvm/llvm-project): upstream LLVM releases.
- [osm0sis/AnyKernel3](https://github.com/osm0sis/AnyKernel3): flashable ZIP template.

**Reference builders**

- [mohdakil2426/marble-kernel-builder](https://github.com/mohdakil2426/marble-kernel-builder)
- [bryanyee33/aospa-gki-kernel-build](https://github.com/bryanyee33/aospa-gki-kernel-build)
- [aosp-pablo/KernelSU-Next-marble](https://github.com/aosp-pablo/KernelSU-Next-marble)
