#!/usr/bin/env bash
# Build one flashable marble (or other device) kernel.
# Inputs are environment variables. See README.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

DEVICE="${DEVICE:-marble}"
KERNEL_SOURCE="${KERNEL_SOURCE:-aosp}"
SOURCE_REF="${SOURCE_REF:-}"
CUSTOM_REPO="${CUSTOM_REPO:-}"
CUSTOM_REF="${CUSTOM_REF:-}"
CUSTOM_FETCH="${CUSTOM_FETCH:-git}"
CUSTOM_KERNEL_PATH="${CUSTOM_KERNEL_PATH:-}"
MANAGER="${MANAGER:-kernelsu}"
MANAGER_REF="${MANAGER_REF:-}"
KSU_MODE="${KSU_MODE:-builtin}"
ENABLE_SUSFS="${ENABLE_SUSFS:-true}"
SUSFS_REF="${SUSFS_REF:-}"
SUSFS_BRANCH="${SUSFS_BRANCH:-}"
NOMOUNT="${NOMOUNT:-off}"
NOMOUNT_REF="${NOMOUNT_REF:-}"
TOOLCHAIN="${TOOLCHAIN:-auto}"
LTO="${LTO:-thin}"
BUILD_SCOPE="${BUILD_SCOPE:-image-only}"
USE_CCACHE="${USE_CCACHE:-true}"
ALL_SOURCES="${ALL_SOURCES:-false}"
# AOSP clang r596125 (Clang 22.0.2). android.googlesource.com main no longer carries this directory.
ANDROID_CLANG_URL="${ANDROID_CLANG_URL:-https://github.com/Neebe3289/aosp-clang/releases/download/clang-22.0.2-15682573/clang-22.0.2-15682573.tar.gz}"

SRC="${ROOT}/src"
RELEASE="${ROOT}/release"
mkdir -p "${SRC}" "${RELEASE}"

log() { printf '%s\n' "$*"; }
die() { printf '::error::%s\n' "$*" >&2; exit 1; }

if [[ -n "${GITHUB_OUTPUT:-}" && "${MATRIX_ONLY:-}" == "1" ]]; then
  python3 "${ROOT}/scripts/plan.py" matrix \
    --device "${DEVICE}" \
    --kernel-source "${KERNEL_SOURCE}" \
    --source-ref "${SOURCE_REF}" \
    --custom-repo "${CUSTOM_REPO}" \
    --custom-ref "${CUSTOM_REF}" \
    --custom-fetch "${CUSTOM_FETCH}" \
    --manager "${MANAGER}" \
    --ksu-mode "${KSU_MODE}" \
    --all-sources "${ALL_SOURCES}" \
    --github-output "${GITHUB_OUTPUT}"
  exit 0
fi

python3 "${ROOT}/scripts/plan.py" write-plan \
  --device "${DEVICE}" \
  --kernel-source "${KERNEL_SOURCE}" \
  --source-ref "${SOURCE_REF}" \
  --custom-repo "${CUSTOM_REPO}" \
  --custom-ref "${CUSTOM_REF}" \
  --custom-fetch "${CUSTOM_FETCH}" \
  --custom-kernel-path "${CUSTOM_KERNEL_PATH}" \
  --manager "${MANAGER}" \
  --manager-ref "${MANAGER_REF}" \
  --ksu-mode "${KSU_MODE}" \
  --susfs "${ENABLE_SUSFS}" \
  --susfs-ref "${SUSFS_REF}" \
  --susfs-branch "${SUSFS_BRANCH}" \
  --nomount "${NOMOUNT}" \
  --nomount-ref "${NOMOUNT_REF}" \
  --toolchain "${TOOLCHAIN}" \
  --lto "${LTO}" \
  --build-scope "${BUILD_SCOPE}" \
  --ccache "${USE_CCACHE}" \
  --out "${RELEASE}/plan.env"

# shellcheck disable=SC1091
source "${RELEASE}/plan.env"

# Full LTO links vmlinux.o in one process and needs about 30 GB of RAM plus swap.
# With less, the linker gets killed and the runner drops the job, so fall back to ThinLTO.
# The workflow adds a 16 GB swap file, which brings a 16 GB hosted runner over the limit.
if [[ "${LTO}" == "full" ]]; then
  mem_kb="$(awk '/^(MemTotal|SwapTotal):/ {sum += $2} END {print sum + 0}' /proc/meminfo 2>/dev/null || echo 0)"
  if (( mem_kb < 30 * 1024 * 1024 )); then
    log "::warning::LTO=full needs about 30 GB of RAM plus swap (this machine has $((mem_kb / 1024 / 1024)) GB). Using thin instead."
    LTO="thin"
  fi
fi

log "Plan: ${SOURCE_DISPLAY} (${SOURCE_KEY}) ${FETCH} + ${MANAGER_DISPLAY} (${KSU_MODE}) susfs=${ENABLE_SUSFS} nomount=${NOMOUNT} toolchain=${TOOLCHAIN} lto=${LTO} scope=${BUILD_SCOPE}"
if [[ "${RESOLVE_ONLY:-}" == "1" ]]; then
  cat "${RELEASE}/plan.env"
  exit 0
fi

sudo_cmd() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

install_deps() {
  if [[ "${SKIP_APT:-}" == "1" ]]; then
    return
  fi
  sudo_cmd apt-get update
  sudo_cmd apt-get install -y --no-install-recommends \
    bc bison build-essential ca-certificates ccache clang cpio curl file flex \
    git libelf-dev libncurses-dev libssl-dev lld llvm patch python3 rsync \
    unzip xz-utils zip zstd device-tree-compiler
}

clone_ref() {
  local url="$1" dest="$2" ref="$3"
  local branch="${ref#refs/heads/}"
  rm -rf "${dest}"
  mkdir -p "$(dirname "${dest}")"
  git init -q "${dest}"
  git -C "${dest}" remote add origin "${url}"
  if git -C "${dest}" fetch --depth 1 -q origin "${branch}"; then
    git -C "${dest}" checkout -q --detach FETCH_HEAD
    return
  fi
  if [[ "${branch}" != "${ref}" ]] && git -C "${dest}" fetch --depth 1 -q origin "${ref}"; then
    git -C "${dest}" checkout -q --detach FETCH_HEAD
    return
  fi
  die "Unable to fetch ${url} @ ${ref}"
}

github_url() {
  local repo="$1"
  if [[ "${repo}" == https://* || "${repo}" == git@* ]]; then
    printf '%s\n' "${repo}"
  else
    printf 'https://github.com/%s.git\n' "${repo}"
  fi
}

fetch_tree() {
  if [[ "${FETCH}" == "manifest" ]]; then
    local manifest_url
    manifest_url="$(github_url "${MANIFEST_REPO}")"
    log "Manifest ${manifest_url} @ ${MANIFEST_REF}"
    clone_ref "${manifest_url}" "${SRC}/manifest" "${MANIFEST_REF}"
    python3 "${ROOT}/scripts/plan.py" manifest \
      --xml "${SRC}/manifest/${MANIFEST_FILE}" \
      --skip "${MANIFEST_SKIP}" \
      --kernel-path "${KERNEL_PATH}" \
      --kernel-ref "${SOURCE_REF_OVERRIDE}" \
      > "${RELEASE}/projects.tsv"
    while IFS=$'\t' read -r url rev path; do
      [[ -n "${url}" ]] || continue
      log "Clone ${url} @ ${rev} -> ${path}"
      clone_ref "${url}" "${SRC}/tree/${path}" "${rev}"
    done < "${RELEASE}/projects.tsv"
    KERNEL_DIR="${SRC}/tree/${KERNEL_PATH}"
  else
    local kernel_url
    kernel_url="$(github_url "${KERNEL_REPO}")"
    log "Kernel ${kernel_url} @ ${KERNEL_REF}"
    clone_ref "${kernel_url}" "${SRC}/kernel" "${KERNEL_REF}"
    KERNEL_DIR="${SRC}/kernel"
    if [[ -n "${KERNEL_PATH}" && "${KERNEL_PATH}" != "." ]]; then
      KERNEL_DIR="${SRC}/kernel/${KERNEL_PATH}"
    fi
    if [[ -s "${RELEASE}/extra.tsv" ]]; then
      while IFS=$'\t' read -r repo ref dest; do
        [[ -n "${repo}" ]] || continue
        local abs
        abs="$(cd "${KERNEL_DIR}" && mkdir -p "$(dirname "${dest}")" && cd "$(dirname "${dest}")" && pwd)/$(basename "${dest}")"
        log "Extra $(github_url "${repo}") @ ${ref} -> ${abs}"
        clone_ref "$(github_url "${repo}")" "${abs}" "${ref}"
      done < "${RELEASE}/extra.tsv"
    fi
  fi
  [[ -f "${KERNEL_DIR}/Makefile" ]] || die "Kernel Makefile not found at ${KERNEL_DIR}"
  git -C "${KERNEL_DIR}" rev-parse HEAD > "${RELEASE}/kernel-commit.txt" || true
  log "Kernel tree: ${KERNEL_DIR}"
}

resolve_defconfig_if_auto() {
  if [[ "${DEFCONFIG_MODE}" != "auto" ]]; then
    return
  fi
  local fragment cfg_root="${KERNEL_DIR}/arch/${ARCH}/configs"
  local ok=1
  for fragment in ${GKI_FRAGMENTS}; do
    [[ -f "${cfg_root}/${fragment}" ]] || ok=0
  done
  if [[ "${ok}" == "1" && -n "${GKI_FRAGMENTS}" && -f "${cfg_root}/gki_defconfig" ]]; then
    DEFCONFIG_MODE="gki_fragments"
  elif [[ -n "${DEFCONFIG_SINGLE}" && -f "${cfg_root}/${DEFCONFIG_SINGLE}" ]]; then
    DEFCONFIG_MODE="single"
  elif [[ -f "${cfg_root}/gki_defconfig" ]]; then
    DEFCONFIG_MODE="single"
    DEFCONFIG_SINGLE="gki_defconfig"
  else
    die "Could not detect a defconfig under ${cfg_root}. Set defconfig_mode in the source entry."
  fi
  log "Auto defconfig mode: ${DEFCONFIG_MODE} (${DEFCONFIG_SINGLE:-fragments})"
}

fetch_toolchain() {
  case "${TOOLCHAIN}" in
    android-r596125)
      local bin="${ROOT}/android-clang/clang-r596125/bin"
      if [[ ! -x "${bin}/clang" ]]; then
        local tarball="${SRC}/clang-r596125.tar.gz"
        curl -fL --retry 3 -o "${tarball}" "${ANDROID_CLANG_URL}"
        rm -rf "${ROOT}/android-clang/clang-r596125"
        mkdir -p "${ROOT}/android-clang/clang-r596125"
        # The tarball has no top-level directory: bin/, lib/ ... sit at the root.
        tar -xzf "${tarball}" -C "${ROOT}/android-clang/clang-r596125"
        rm -f "${tarball}"
        [[ -x "${bin}/clang" ]] || die "bin/clang missing after extracting ${ANDROID_CLANG_URL}"
      fi
      TOOLCHAIN_BIN="${bin}"
      ;;
    llvm-23.1.5)
      local bin="${ROOT}/llvm-23.1.5/bin"
      if [[ ! -x "${bin}/clang" ]]; then
        local tarball="${SRC}/LLVM-23.1.5-Linux-X64.tar.xz"
        local url="https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.5/LLVM-23.1.5-Linux-X64.tar.xz"
        curl -fL --retry 3 -o "${tarball}" "${url}"
        rm -rf "${ROOT}/llvm-23.1.5"
        mkdir -p "${ROOT}/llvm-23.1.5"
        tar -xJf "${tarball}" -C "${ROOT}/llvm-23.1.5" --strip-components=1
      fi
      TOOLCHAIN_BIN="${bin}"
      ;;
    *)
      die "No fetch recipe for toolchain ${TOOLCHAIN}"
      ;;
  esac
  export PATH="${TOOLCHAIN_BIN}:${PATH}"
  "${TOOLCHAIN_BIN}/clang" --version | head -n 2
}

kconfig_path() {
  local candidate
  for candidate in \
    "${KERNEL_DIR}/KernelSU/kernel/Kconfig" \
    "${KERNEL_DIR}/KernelSU-Next/kernel/Kconfig"
  do
    if [[ -f "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

setup_manager_from() {
  local repo="$1" ref="$2"
  local url="https://raw.githubusercontent.com/${repo}/${ref}/${MANAGER_SETUP}"
  log "Manager setup ${repo} @ ${ref}"
  # Some kernel trees list KernelSU as a submodule. A shallow clone leaves an empty
  # KernelSU/ directory, so setup.sh skips its clone and runs git inside the kernel repo.
  # Remove the stale directory and symlink so setup.sh starts from a clean state.
  rm -rf "${KERNEL_DIR}/KernelSU" "${KERNEL_DIR}/KernelSU-Next" \
    "${KERNEL_DIR}/drivers/kernelsu" "${KERNEL_DIR}/common/drivers/kernelsu"
  curl -fsSL "${url}" -o "${SRC}/manager-setup.sh"
  (
    cd "${KERNEL_DIR}"
    bash "${SRC}/manager-setup.sh" "${ref}"
  )
}

apply_patch() {
  local dir="$1" file="$2"
  if [[ ! -f "${file}" ]]; then
    die "Missing patch ${file}"
  fi
  if ( cd "${dir}" && patch -p1 --dry-run --forward < "${file}" >/dev/null ); then
    ( cd "${dir}" && patch -p1 --forward < "${file}" )
    return 0
  fi
  if ( cd "${dir}" && patch -p1 --dry-run --forward --fuzz=3 < "${file}" >/dev/null ); then
    log "::warning::Applied $(basename "${file}") with fuzz 3"
    ( cd "${dir}" && patch -p1 --forward --fuzz=3 < "${file}" )
    return 0
  fi
  return 1
}

apply_manager() {
  if [[ "${MANAGER}" == "none" ]]; then
    log "No root manager"
    return
  fi
  if [[ "${KSU_MODE}" == "lkm" ]]; then
    # LKM: the kernel tree stays untouched. The manager is only cloned and built later as kernelsu.ko.
    log "Manager (LKM) ${MANAGER_REPO} @ ${MANAGER_REF}"
    clone_ref "$(github_url "${MANAGER_REPO}")" "${SRC}/ksu-lkm" "${MANAGER_REF}"
    [[ -f "${SRC}/ksu-lkm/kernel/Kbuild" ]] || die "No kernel/Kbuild in ${MANAGER_REPO}@${MANAGER_REF}"
    git -C "${SRC}/ksu-lkm" rev-parse HEAD > "${RELEASE}/manager-commit.txt" || true
    return
  fi
  setup_manager_from "${MANAGER_REPO}" "${MANAGER_REF}"
  kconfig_path >/dev/null || die "Manager setup did not create a kernel Kconfig"
}

apply_susfs() {
  if [[ "${ENABLE_SUSFS}" != "true" ]]; then
    log "SUSFS disabled"
    return
  fi
  [[ "${MANAGER}" != "none" ]] || die "SUSFS needs a root manager"
  local susfs_dir="${SRC}/susfs4ksu"
  rm -rf "${susfs_dir}"
  git init -q "${susfs_dir}"
  git -C "${susfs_dir}" remote add origin "${SUSFS_REPO}"
  git -C "${susfs_dir}" fetch --depth 1 -q origin "${SUSFS_BRANCH}"
  if [[ -n "${SUSFS_REF}" ]]; then
    git -C "${susfs_dir}" fetch --depth 1 -q origin "${SUSFS_REF}"
  fi
  git -C "${susfs_dir}" checkout -q --detach FETCH_HEAD
  git -C "${susfs_dir}" rev-parse HEAD > "${RELEASE}/susfs-commit.txt"
  log "SUSFS $(cat "${RELEASE}/susfs-commit.txt") from ${SUSFS_BRANCH}"

  local kconfig manager_root
  kconfig="$(kconfig_path)" || die "SUSFS needs the manager Kconfig"
  manager_root="$(dirname "$(dirname "${kconfig}")")"
  if ! grep -q '^config KSU_SUSFS$' "${kconfig}"; then
    local hook="${susfs_dir}/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch"
    if ! apply_patch "${manager_root}" "${hook}"; then
      if [[ -n "${MANAGER_SUSFS_FALLBACK_REPO}" ]]; then
        log "::warning::Official SUSFS patch missed ${MANAGER_REPO}@${MANAGER_REF}; trying ${MANAGER_SUSFS_FALLBACK_REPO}@${MANAGER_SUSFS_FALLBACK_REF}"
        rm -rf "${KERNEL_DIR}/KernelSU" "${KERNEL_DIR}/KernelSU-Next"
        setup_manager_from "${MANAGER_SUSFS_FALLBACK_REPO}" "${MANAGER_SUSFS_FALLBACK_REF}"
        kconfig="$(kconfig_path)" || die "Fallback manager setup failed"
        manager_root="$(dirname "$(dirname "${kconfig}")")"
        if ! grep -q '^config KSU_SUSFS$' "${kconfig}"; then
          apply_patch "${manager_root}" "${hook}" || die "SUSFS manager patch does not apply. Pin manager_ref to a compatible commit."
        fi
      else
        die "SUSFS manager patch does not apply on ${MANAGER_REPO}@${MANAGER_REF}. Pin manager_ref."
      fi
    fi
  else
    log "Manager already has KSU_SUSFS; skipping 10_enable_susfs_for_ksu.patch"
  fi

  local kernel_patch="${susfs_dir}/kernel_patches/50_add_susfs_in_gki-${SUSFS_BRANCH#gki-}.patch"
  if grep -q 'susfs\.o' "${KERNEL_DIR}/fs/Makefile"; then
    log "Kernel already references susfs.o; skipping the kernel SUSFS patch"
  elif ! apply_patch "${KERNEL_DIR}" "${kernel_patch}"; then
    die "SUSFS kernel patch failed for ${SUSFS_BRANCH}. Check ${kernel_patch}"
  fi
  cp -a "${susfs_dir}/kernel_patches/fs/." "${KERNEL_DIR}/fs/"
  cp -a "${susfs_dir}/kernel_patches/include/linux/." "${KERNEL_DIR}/include/linux/"
  if [[ -f "${susfs_dir}/kernel_patches/include/linux/susfs.h" ]]; then
    grep -m1 'SUSFS_VERSION' "${susfs_dir}/kernel_patches/include/linux/susfs.h" | tee "${RELEASE}/susfs-version.txt" || true
  fi
}

apply_nomount() {
  if [[ "${NOMOUNT}" == "off" ]]; then
    log "NoMount disabled"
    return
  fi
  local url="${NOMOUNT_REPO%/}/raw/${NOMOUNT_REF}/kernel/setup.sh"
  # GitHub raw URL, whether NOMOUNT_REPO is a repo URL or already ends without .git.
  local raw="https://raw.githubusercontent.com/maxsteeel/nomount/${NOMOUNT_REF}/kernel/setup.sh"
  if [[ "${NOMOUNT_REPO}" != "https://github.com/maxsteeel/nomount" ]]; then
    raw="${url}"
  fi
  log "NoMount setup @ ${NOMOUNT_REF} (${NOMOUNT})"
  curl -fsSL "${raw}" -o "${SRC}/nomount-setup.sh"
  (
    cd "${KERNEL_DIR}"
    bash "${SRC}/nomount-setup.sh" "${NOMOUNT_REF}"
  )
  [[ -e "${KERNEL_DIR}/fs/nomount/Kconfig" || -L "${KERNEL_DIR}/fs/nomount" ]] || die "NoMount setup did not link fs/nomount"
}

make_kernel() {
  export ARCH
  export SUBARCH="${ARCH}"
  export KBUILD_BUILD_USER KBUILD_BUILD_HOST
  export PATH="${TOOLCHAIN_BIN}:${PATH}"
  local cc="clang"
  if [[ "${USE_CCACHE}" == "true" ]] && command -v ccache >/dev/null 2>&1; then
    export CCACHE_DIR="${CCACHE_DIR:-${HOME}/.ccache}"
    export CCACHE_COMPILERCHECK=content
    export CCACHE_NOHASHDIR=true
    ccache -M 6G >/dev/null
    ccache -o compression=true || true
    ccache -z || true
    cc="ccache clang"
  fi

  local jobs
  jobs="${JOBS:-$(nproc)}"
  if [[ -z "${JOBS_FORCE:-}" && "${TOOLCHAIN}" == "llvm-23.1.5" && "${jobs}" -gt 2 ]]; then
    log "Capping jobs from ${jobs} to 2 for ${TOOLCHAIN}"
    jobs=2
  fi

  local out="${KERNEL_DIR}/out"
  mkdir -p "${out}"
  local common=(O="${out}" ARCH="${ARCH}" LLVM=1 LLVM_IAS=1 CC="${cc}")

  case "${DEFCONFIG_MODE}" in
    single)
      [[ -n "${DEFCONFIG_SINGLE}" ]] || die "single defconfig mode needs a defconfig name"
      log "defconfig ${DEFCONFIG_SINGLE}"
      make -C "${KERNEL_DIR}" "${common[@]}" "${DEFCONFIG_SINGLE}"
      ;;
    gki_fragments)
      log "defconfig gki_defconfig + fragments"
      make -C "${KERNEL_DIR}" "${common[@]}" gki_defconfig
      local fragment paths=()
      for fragment in ${GKI_FRAGMENTS}; do
        local path="${KERNEL_DIR}/arch/${ARCH}/configs/${fragment}"
        [[ -f "${path}" ]] || die "Missing fragment ${path}"
        paths+=("${path}")
        log "  + ${fragment}"
      done
      "${KERNEL_DIR}/scripts/kconfig/merge_config.sh" -O "${out}" -m "${out}/.config" "${paths[@]}"
      ;;
    *)
      die "Bad DEFCONFIG_MODE ${DEFCONFIG_MODE}"
      ;;
  esac

  local cfg=(scripts/config --file "${out}/.config")
  if [[ "${MANAGER}" != "none" && "${KSU_MODE}" == "builtin" ]]; then
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e KSU )
  fi
  if [[ "${ENABLE_SUSFS}" == "true" ]]; then
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e KSU_SUSFS )
  fi
  case "${NOMOUNT}" in
    builtin) ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e NOMOUNT ) ;;
    lkm|off) ( cd "${KERNEL_DIR}" && "${cfg[@]}" -d NOMOUNT ) || true ;;
  esac
  case "${LTO}" in
    none)
      ( cd "${KERNEL_DIR}" && "${cfg[@]}" -d LTO_CLANG -d LTO_CLANG_THIN -d LTO_CLANG_FULL -e LTO_NONE ) || true
      ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e LTO_CLANG_NONE ) || true
      ;;
    thin)
      ( cd "${KERNEL_DIR}" && "${cfg[@]}" -d LTO_NONE -d LTO_CLANG_NONE -d LTO_CLANG_FULL -e LTO_CLANG -e LTO_CLANG_THIN ) || true
      ;;
    full)
      ( cd "${KERNEL_DIR}" && "${cfg[@]}" -d LTO_NONE -d LTO_CLANG_NONE -d LTO_CLANG_THIN -e LTO_CLANG -e LTO_CLANG_FULL ) || true
      ;;
  esac

  make -C "${KERNEL_DIR}" "${common[@]}" olddefconfig
  if [[ "${MANAGER}" != "none" && "${KSU_MODE}" == "builtin" ]] && ! grep -Eq '^(CONFIG_KSU=y|CONFIG_KSU=m)$' "${out}/.config"; then
    die "CONFIG_KSU did not stay enabled"
  fi
  if [[ "${KSU_MODE}" == "lkm" ]] && ! grep -q '^CONFIG_KPROBES=y$' "${out}/.config"; then
    log "::warning::CONFIG_KPROBES is not enabled. kernelsu.ko needs kprobes to load."
  fi
  if [[ "${ENABLE_SUSFS}" == "true" ]] && ! grep -q '^CONFIG_KSU_SUSFS=y$' "${out}/.config"; then
    die "CONFIG_KSU_SUSFS did not stay enabled"
  fi
  if [[ "${NOMOUNT}" == "builtin" ]] && ! grep -q '^CONFIG_NOMOUNT=y$' "${out}/.config"; then
    die "CONFIG_NOMOUNT=y did not stay enabled"
  fi

  if [[ "${LTO}" == "thin" ]]; then
    local wrapper="${RELEASE}/ld-thinlto-wrapper" jobs_lto="${THINLTO_JOBS:-2}"
    local cache="${HOME}/.cache/thinlto"
    mkdir -p "${cache}"
    cat > "${wrapper}" <<EOF
#!/bin/bash
exec ld.lld "\$@" --thinlto-jobs=${jobs_lto} --thinlto-cache-dir=${cache}
EOF
    chmod +x "${wrapper}"
    export LD="${wrapper}" HOSTLD="${wrapper}"
    log "ThinLTO jobs=${jobs_lto}"
  fi

  local targets=(Image)
  if [[ "${BUILD_SCOPE}" == "full" ]]; then
    targets+=(modules dtbs)
  fi
  make -C "${KERNEL_DIR}" -j"${jobs}" "${common[@]}" "${targets[@]}"

  local image=""
  for candidate in Image Image.gz Image.gz-dtb; do
    if [[ -s "${out}/arch/${ARCH}/boot/${candidate}" ]]; then
      image="${out}/arch/${ARCH}/boot/${candidate}"
      break
    fi
  done
  [[ -n "${image}" ]] || die "No Image under ${out}/arch/${ARCH}/boot"
  local bytes
  bytes="$(stat -c%s "${image}")"
  [[ "${bytes}" -gt 2000000 ]] || die "Image is unexpectedly small (${bytes} bytes)"
  cp -f "${image}" "${RELEASE}/$(basename "${image}")"
  log "Image ${bytes} bytes"

  if [[ "${BUILD_SCOPE}" == "full" ]]; then
    build_techpack "${cc}" "${jobs}" "${out}"
  fi

  if [[ "${KSU_MODE}" == "lkm" && "${MANAGER}" != "none" ]]; then
    log "Building ${MANAGER_DISPLAY} as an LKM"
    make -C "${KERNEL_DIR}" "${common[@]}" modules_prepare
    if [[ ! -s "${out}/Module.symvers" ]]; then
      # Without Module.symvers the module would carry no symbol CRCs and fail to load.
      log "Module.symvers is missing; running the kernel modules build once to create it"
      make -C "${KERNEL_DIR}" -j"${jobs}" "${common[@]}" modules
    fi
    [[ -d "${out}/usr/include" ]] || log "::warning::${out}/usr/include is missing; the manager builds without preinit"
    make -C "${KERNEL_DIR}" -j"${jobs}" "${common[@]}" M="${SRC}/ksu-lkm/kernel" CONFIG_KSU=m modules
    [[ -s "${SRC}/ksu-lkm/kernel/kernelsu.ko" ]] || die "kernelsu.ko was not produced"
    cp -f "${SRC}/ksu-lkm/kernel/kernelsu.ko" "${RELEASE}/kernelsu.ko"
    llvm-strip -d "${RELEASE}/kernelsu.ko" || true
    # Same check the upstream Makefile runs: every symbol the module needs must exist in vmlinux.
    if cc -o "${SRC}/check_symbol" "${SRC}/ksu-lkm/kernel/tools/check_symbol.c" 2>/dev/null; then
      "${SRC}/check_symbol" "${RELEASE}/kernelsu.ko" "${out}/vmlinux" \
        || log "::warning::check_symbol reported missing symbols. kernelsu.ko may fail to load."
    fi
    cat > "${RELEASE}/kernelsu-lkm.txt" <<'EOF'
kernelsu.ko matches this kernel only (same Image, same config).
Flash the AnyKernel3 zip first, then patch your boot or init_boot image with:
  ksud boot-patch -b <boot.img> --module kernelsu.ko --kmi <kmi>
The Image in the zip does not contain KernelSU.
EOF
  fi

  if [[ "${NOMOUNT}" == "lkm" ]]; then
    log "Building NoMount as an LKM"
    make -C "${KERNEL_DIR}" "${common[@]}" modules_prepare
    CONFIG_NOMOUNT=m make -C "${KERNEL_DIR}" "${common[@]}" M="${KERNEL_DIR}/fs/nomount" modules
    local ko
    ko="$(find "${KERNEL_DIR}/fs/nomount" "${out}" -name 'nomount.ko' -print -quit || true)"
    [[ -n "${ko}" ]] || die "nomount.ko was not produced"
    cp -f "${ko}" "${RELEASE}/nomount.ko"
    cat > "${RELEASE}/nomount-lkm.txt" <<'EOF'
nomount.ko matches this kernel only.
Put it in the lkm/ directory of the NoMount module zip
(https://github.com/maxsteeel/nomount/releases) and flash that module
from KernelSU or APatch. The boot image does not contain NoMount.
EOF
  fi

  if [[ "${BUILD_SCOPE}" == "full" || "${NOMOUNT}" == "lkm" ]]; then
    local ko_roots=("${out}")
    if [[ -n "${MODULES_SRC}" && -d "${KERNEL_DIR}/${MODULES_SRC}" ]]; then
      ko_roots+=("${KERNEL_DIR}/${MODULES_SRC}")
    fi
    if [[ -d "${KERNEL_DIR}/fs/nomount" ]]; then
      ko_roots+=("${KERNEL_DIR}/fs/nomount")
    fi
    if find "${ko_roots[@]}" -name '*.ko' -print -quit | grep -q .; then
      find "${ko_roots[@]}" -name '*.ko' -print0 | tar --null -T - -czf "${RELEASE}/modules.tar.gz"
    fi
    if [[ "${BUILD_SCOPE}" == "full" ]] && find "${out}/arch/${ARCH}/boot/dts" -name '*.dtb' -print -quit 2>/dev/null | grep -q .; then
      find "${out}/arch/${ARCH}/boot/dts" -name '*.dtb' -print0 | tar --null -T - -czf "${RELEASE}/dtbs.tar.gz"
    fi
  fi

  if [[ "${USE_CCACHE}" == "true" ]] && command -v ccache >/dev/null 2>&1; then
    ccache -s > "${RELEASE}/ccache-stats.txt" || true
  fi
}

build_techpack() {
  local cc="$1" jobs="$2" out="$3"
  if [[ -z "${MODULES_SRC}" || -z "${MODULES_LIST}" || ! -f "${ROOT}/${MODULES_LIST}" ]]; then
    log "No techpack list for this source"
    return
  fi
  local src="${KERNEL_DIR}/${MODULES_SRC}"
  if [[ ! -d "${src}" ]]; then
    die "Techpack directory missing: ${src}"
  fi
  local module
  while IFS= read -r module; do
    [[ -z "${module}" || "${module}" == \#* ]] && continue
    if [[ ! -d "${src}/${module}" ]]; then
      log "::warning::Skipping missing techpack ${module}"
      continue
    fi
    log "Techpack ${module}"
    make -C "${KERNEL_DIR}" -j"${jobs}" O="${out}" ARCH="${ARCH}" LLVM=1 LLVM_IAS=1 CC="${cc}" \
      M="${src}/${module}" KERNEL_SRC="${KERNEL_DIR}" OUT_DIR="${out}" modules
  done < "${ROOT}/${MODULES_LIST}"
}

package_zip() {
  local ak="${ROOT}/ak3-work"
  rm -rf "${ak}"
  clone_ref "${ANYKERNEL_REPO}" "${ak}" "${ANYKERNEL_REF}"
  local susfs_tag="nosusfs" nm_tag="nm-${NOMOUNT}" manager_tag="${MANAGER}"
  [[ "${KSU_MODE}" == "lkm" && "${MANAGER}" != "none" ]] && manager_tag="${MANAGER}-lkm"
  [[ "${ENABLE_SUSFS}" == "true" ]] && susfs_tag="susfs"
  local version
  version="$(tr -d '\n' < "${RELEASE}/susfs-version.txt" 2>/dev/null || true)"
  local manager_label="${MANAGER_DISPLAY}"
  [[ "${KSU_MODE}" == "lkm" && "${MANAGER}" != "none" ]] && manager_label="${MANAGER_DISPLAY} LKM"
  local string="${DEVICE} ${SOURCE_DISPLAY} ${manager_label} ${susfs_tag} ${nm_tag}"
  [[ -n "${version}" ]] && string="${string} ${version}"
  sed \
    -e "s|__KERNEL_STRING__|${string}|" \
    -e "s|__DEVICE_NAME_1__|${DEVICE_NAME_1}|" \
    -e "s|__DEVICE_NAME_2__|${DEVICE_NAME_2}|" \
    "${ROOT}/ak3/anykernel.sh" > "${ak}/anykernel.sh"
  if [[ -z "${DEVICE_NAME_2}" ]]; then
    sed -i '/^device.name2=/d' "${ak}/anykernel.sh"
  fi
  local image
  image="$(find "${RELEASE}" -maxdepth 1 -type f \( -name 'Image' -o -name 'Image.gz' -o -name 'Image.gz-dtb' \) -print -quit)"
  cp -f "${image}" "${ak}/"
  rm -rf "${ak}/.git" "${ak}/README.md" "${ak}/"*.placeholder
  local run="${GITHUB_RUN_NUMBER:-local}"
  local name="${DEVICE}-${SOURCE_KEY}-${manager_tag}-${susfs_tag}-${nm_tag}-r${run}.zip"
  (
    cd "${ak}"
    zip -r9 "${RELEASE}/${name}" . -x '.git/*'
  )
  ( cd "${RELEASE}" && sha256sum "${name}" > "${name}.sha256" )
  if [[ -f "${RELEASE}/nomount.ko" ]]; then
    cp -f "${RELEASE}/nomount.ko" "${RELEASE}/${name%.zip}-nomount.ko"
  fi
  if [[ -f "${RELEASE}/kernelsu.ko" ]]; then
    cp -f "${RELEASE}/kernelsu.ko" "${RELEASE}/${name%.zip}-kernelsu.ko"
  fi
  cat > "${RELEASE}/build-info.txt" <<EOF
device: ${DEVICE} (${DEVICE_NAME_1} ${DEVICE_NAME_2})
source: ${SOURCE_DISPLAY} [${SOURCE_KEY}] ${ROM_LABEL}
fetch: ${FETCH}
kernel: ${KERNEL_REPO:-${MANIFEST_REPO}} @ ${KERNEL_REF:-${MANIFEST_REF}}
kernel_commit: $(cat "${RELEASE}/kernel-commit.txt" 2>/dev/null || echo unknown)
manager: ${MANAGER_DISPLAY} (${KSU_MODE}) ${MANAGER_REPO}@${MANAGER_REF}
susfs: ${ENABLE_SUSFS} ${SUSFS_BRANCH} ${SUSFS_REF:-HEAD} $(cat "${RELEASE}/susfs-version.txt" 2>/dev/null || true)
susfs_commit: $(cat "${RELEASE}/susfs-commit.txt" 2>/dev/null || echo n/a)
nomount: ${NOMOUNT} ${NOMOUNT_REF}
toolchain: ${TOOLCHAIN}
lto: ${LTO}
scope: ${BUILD_SCOPE}
zip: ${name}
EOF
  log "Packaged ${name}"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo "### ${name}"
      echo
      echo '```'
      cat "${RELEASE}/build-info.txt"
      echo '```'
    } >> "${GITHUB_STEP_SUMMARY}"
  fi
}

install_deps
fetch_tree
resolve_defconfig_if_auto
fetch_toolchain
apply_manager
apply_susfs
apply_nomount
make_kernel
package_zip
log "Done"
