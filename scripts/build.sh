#!/usr/bin/env bash
# Build one flashable marble (or other device) kernel.
# Inputs are environment variables. See README.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

DEVICE="${DEVICE:-marble}"
KERNEL_NAME="${KERNEL_NAME:-}"
KERNEL_SOURCE="${KERNEL_SOURCE:-aosp}"
SOURCE_REF="${SOURCE_REF:-}"
CUSTOM_REPO="${CUSTOM_REPO:-}"
CUSTOM_REF="${CUSTOM_REF:-}"
CUSTOM_FETCH="${CUSTOM_FETCH:-git}"
CUSTOM_KERNEL_PATH="${CUSTOM_KERNEL_PATH:-}"
MANAGER="${MANAGER:-kernelsu}"
MANAGER_REF="${MANAGER_REF:-}"
ENABLE_SUSFS="${ENABLE_SUSFS:-true}"
SUSFS_REF="${SUSFS_REF:-}"
SUSFS_BRANCH="${SUSFS_BRANCH:-}"
ENABLE_NOMOUNT="${ENABLE_NOMOUNT:-${NOMOUNT:-false}}"
NOMOUNT_REF="${NOMOUNT_REF:-}"
TOOLCHAIN="${TOOLCHAIN:-auto}"
LTO="${LTO:-thin}"
BUILD_SCOPE="${BUILD_SCOPE:-image-only}"
USE_CCACHE="${USE_CCACHE:-true}"
ALL_SOURCES="${ALL_SOURCES:-false}"
TOOLCHAIN_URL="${TOOLCHAIN_URL:-}"
TOOLCHAIN_SHA256="${TOOLCHAIN_SHA256:-}"

SRC="${ROOT}/src"
RELEASE="${ROOT}/release"
mkdir -p "${SRC}"

log() { printf '%s\n' "$*"; }
die() { printf '::error::%s\n' "$*" >&2; exit 1; }

# shellcheck source=scripts/techpack.sh
source "${ROOT}/scripts/techpack.sh"

if [[ -n "${GITHUB_OUTPUT:-}" && "${MATRIX_ONLY:-}" == "1" ]]; then
  python3 "${ROOT}/scripts/plan.py" matrix \
    --device "${DEVICE}" \
    --kernel-source "${KERNEL_SOURCE}" \
    --source-ref "${SOURCE_REF}" \
    --custom-repo "${CUSTOM_REPO}" \
    --custom-ref "${CUSTOM_REF}" \
    --custom-fetch "${CUSTOM_FETCH}" \
    --manager "${MANAGER}" \
    --manager-ref "${MANAGER_REF}" \
    --toolchain "${TOOLCHAIN}" \
    --toolchain-url "${TOOLCHAIN_URL}" \
    --toolchain-sha256 "${TOOLCHAIN_SHA256}" \
    --all-sources "${ALL_SOURCES}" \
    --github-output "${GITHUB_OUTPUT}"
  exit 0
fi

# Never let files from a previous local build leak into this run's artifact.
rm -rf "${RELEASE}"
mkdir -p "${RELEASE}"

python3 "${ROOT}/scripts/plan.py" write-plan \
  --device "${DEVICE}" \
  --kernel-name "${KERNEL_NAME}" \
  --kernel-source "${KERNEL_SOURCE}" \
  --source-ref "${SOURCE_REF}" \
  --custom-repo "${CUSTOM_REPO}" \
  --custom-ref "${CUSTOM_REF}" \
  --custom-fetch "${CUSTOM_FETCH}" \
  --custom-kernel-path "${CUSTOM_KERNEL_PATH}" \
  --manager "${MANAGER}" \
  --manager-ref "${MANAGER_REF}" \
  --susfs "${ENABLE_SUSFS}" \
  --susfs-ref "${SUSFS_REF}" \
  --susfs-branch "${SUSFS_BRANCH}" \
  --nomount "${ENABLE_NOMOUNT}" \
  --nomount-ref "${NOMOUNT_REF}" \
  --toolchain "${TOOLCHAIN}" \
  --toolchain-url "${TOOLCHAIN_URL}" \
  --toolchain-sha256 "${TOOLCHAIN_SHA256}" \
  --lto "${LTO}" \
  --build-scope "${BUILD_SCOPE}" \
  --ccache "${USE_CCACHE}" \
  --out "${RELEASE}/plan.env"

redact_plan_artifact() {
  if [[ -f "${RELEASE}/plan.env" ]]; then
    python3 "${ROOT}/scripts/redact_plan.py" "${RELEASE}/plan.env" || \
      log "::warning::Could not redact toolchain URL from release/plan.env"
  fi
}
# Redact even when a later build step fails and Actions uploads artifacts with if: always().
trap redact_plan_artifact EXIT

# shellcheck disable=SC1091
set -a
source "${RELEASE}/plan.env"
set +a
MANAGER_EFFECTIVE_REPO="${MANAGER_REPO:-n/a}"
MANAGER_EFFECTIVE_REF="${MANAGER_REF:-n/a}"
if [[ "${MANAGER}" == "none" ]]; then
  MANAGER_EFFECTIVE_REPO="n/a"
  MANAGER_EFFECTIVE_REF="n/a"
fi
export MANAGER_EFFECTIVE_REPO MANAGER_EFFECTIVE_REF

if [[ "${LTO}" == "full" ]]; then
  mem_kb="$(awk '/^(MemTotal|SwapTotal):/ {sum += $2} END {print sum + 0}' /proc/meminfo 2>/dev/null || echo 0)"
  if (( mem_kb < 30 * 1024 * 1024 )); then
    log "::warning::LTO=full needs about 30 GB of RAM plus swap (this machine has $((mem_kb / 1024 / 1024)) GB). Using thin instead."
    LTO="thin"
  fi
fi

log "Plan: ${SOURCE_DISPLAY} (${SOURCE_KEY}) ${FETCH} + ${MANAGER_DISPLAY} susfs=${ENABLE_SUSFS} nomount=${ENABLE_NOMOUNT} name=${KERNEL_NAME:-default} toolchain=${TOOLCHAIN} lto=${LTO} scope=${BUILD_SCOPE}"
if [[ "${RESOLVE_ONLY:-}" == "1" ]]; then
  redact_plan_artifact
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
  [[ -n "${url}" && -n "${ref}" ]] || die "clone_ref needs both a URL and a revision"
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

safe_join() {
  # Resolve a path and ensure it remains beneath the supplied checkout root.
  python3 - "$1" "$2" <<'PYSAFEJOIN'
import os, sys
base = os.path.realpath(sys.argv[1])
path = os.path.realpath(os.path.join(base, sys.argv[2]))
try:
    inside = os.path.commonpath((base, path)) == base
except ValueError:
    inside = False
if not inside:
    print(f"::error::Path escapes checkout root: {sys.argv[2]}", file=sys.stderr)
    raise SystemExit(1)
print(path)
PYSAFEJOIN
}

record_project_commit() {
  local url="$1" ref="$2" path="$3" directory="$4" commit
  commit="$(git -C "${directory}" rev-parse HEAD)"
  printf '%s\t%s\t%s\t%s\n' "${path}" "${url}" "${ref}" "${commit}" >> "${RELEASE}/project-commits.tsv"
}

github_url() {
  local repo="$1"
  if [[ "${repo}" == https://* || "${repo}" == ssh://* || "${repo}" == git://* || "${repo}" == git@* ]]; then
    printf '%s\n' "${repo}"
  else
    printf 'https://github.com/%s.git\n' "${repo}"
  fi
}

fetch_tree() {
  : > "${RELEASE}/project-commits.tsv"
  if [[ "${FETCH}" == "manifest" ]]; then
    local manifest_url manifest_xml
    manifest_url="$(github_url "${MANIFEST_REPO}")"
    log "Manifest ${manifest_url} @ ${MANIFEST_REF}"
    # Manifest projects removed upstream must not survive from an earlier local build.
    rm -rf "${SRC}/tree"
    mkdir -p "${SRC}/tree"
    clone_ref "${manifest_url}" "${SRC}/manifest" "${MANIFEST_REF}"
    git -C "${SRC}/manifest" rev-parse HEAD > "${RELEASE}/manifest-commit.txt"
    manifest_xml="$(safe_join "${SRC}/manifest" "${MANIFEST_FILE}")"
    python3 "${ROOT}/scripts/plan.py" manifest \
      --xml "${manifest_xml}" \
      --root "${SRC}/manifest" \
      --skip "${MANIFEST_SKIP}" \
      --kernel-path "${KERNEL_PATH}" \
      --kernel-ref "${SOURCE_REF_OVERRIDE}" \
      > "${RELEASE}/projects.tsv"
    while IFS=$'\t' read -r url rev path; do
      [[ -n "${url}" ]] || continue
      local project_dir
      project_dir="$(safe_join "${SRC}/tree" "${path}")"
      log "Clone ${url} @ ${rev} -> ${path}"
      clone_ref "${url}" "${project_dir}" "${rev}"
      record_project_commit "${url}" "${rev}" "${path}" "${project_dir}"
    done < "${RELEASE}/projects.tsv"
    KERNEL_DIR="$(safe_join "${SRC}/tree" "${KERNEL_PATH}")"
  else
    local kernel_url
    kernel_url="$(github_url "${KERNEL_REPO}")"
    log "Kernel ${kernel_url} @ ${KERNEL_REF}"
    clone_ref "${kernel_url}" "${SRC}/kernel" "${KERNEL_REF}"
    KERNEL_DIR="$(safe_join "${SRC}/kernel" "${KERNEL_PATH}")"
    record_project_commit "${kernel_url}" "${KERNEL_REF}" "${KERNEL_PATH}" "${SRC}/kernel"
    if [[ -s "${RELEASE}/extra.tsv" ]]; then
      while IFS=$'\t' read -r repo ref dest; do
        [[ -n "${repo}" ]] || continue
        local abs extra_url
        abs="$(safe_join "${SRC}" "${KERNEL_DIR}/${dest}")"
        extra_url="$(github_url "${repo}")"
        log "Extra ${extra_url} @ ${ref} -> ${abs}"
        clone_ref "${extra_url}" "${abs}" "${ref}"
        record_project_commit "${extra_url}" "${ref}" "${dest}" "${abs}"
      done < "${RELEASE}/extra.tsv"
    fi
  fi
  [[ -f "${KERNEL_DIR}/Makefile" ]] || die "Kernel Makefile not found at ${KERNEL_DIR}"
  git -C "${KERNEL_DIR}" rev-parse HEAD > "${RELEASE}/kernel-commit.txt"
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
  [[ -n "${TOOLCHAIN_URL}" ]] || die "No download URL for toolchain ${TOOLCHAIN}. See config/toolchains.json"
  local dir="${ROOT}/toolchains/${TOOLCHAIN}"
  local expected="${TOOLCHAIN_SHA256,,}" cached_sha="" cache_identity="" cached_identity=""
  cache_identity="$(printf '%s\n%s\n' "${TOOLCHAIN_URL}" "${expected}" | sha256sum | awk '{print $1}')"
  if [[ -f "${dir}/.archive.sha256" ]]; then
    cached_sha="$(tr -d '[:space:]' < "${dir}/.archive.sha256")"
  fi
  if [[ -f "${dir}/.identity" ]]; then
    cached_identity="$(tr -d '[:space:]' < "${dir}/.identity")"
  fi
  if [[ -x "${dir}/bin/clang" && "${cached_identity}" != "${cache_identity}" ]]; then
    log "Cached ${TOOLCHAIN} was created from a different URL/checksum identity; downloading again"
    rm -rf "${dir}"
  fi
  if [[ ! -x "${dir}/bin/clang" ]]; then
    local archive="${SRC}/toolchain.archive" tmp="${SRC}/toolchain-tmp" actual_sha
    local display_url
    display_url="$(python3 - "${TOOLCHAIN_URL}" <<'PYURL'
import sys, urllib.parse
parsed = urllib.parse.urlsplit(sys.argv[1])
host = parsed.hostname or ""
if parsed.port:
    host += f":{parsed.port}"
print(urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", "")))
PYURL
)"
    log "Toolchain ${TOOLCHAIN}: ${display_url}"
    curl -fL --retry 3 --retry-all-errors -o "${archive}" "${TOOLCHAIN_URL}"
    actual_sha="$(sha256sum "${archive}" | awk '{print $1}')"
    if [[ -n "${expected}" && "${actual_sha}" != "${expected}" ]]; then
      rm -f "${archive}"
      die "Toolchain SHA-256 mismatch: expected ${expected}, got ${actual_sha}"
    fi
    printf '%s\n' "${actual_sha}" > "${RELEASE}/toolchain-archive.sha256"
    rm -rf "${tmp}" "${dir}"
    mkdir -p "${tmp}" "$(dirname "${dir}")"
    python3 "${ROOT}/scripts/safe_extract.py" "${archive}" "${tmp}"
    rm -f "${archive}"
    local clang_bin
    clang_bin="$(find "${tmp}" -maxdepth 4 \( -type f -o -type l \) -path '*/bin/clang' -print -quit)"
    [[ -n "${clang_bin}" ]] || die "No bin/clang found in downloaded ${TOOLCHAIN} archive (${display_url})"
    mv "$(dirname "$(dirname "${clang_bin}")")" "${dir}"
    printf '%s\n' "${actual_sha}" > "${dir}/.archive.sha256"
    printf '%s\n' "${cache_identity}" > "${dir}/.identity"
    rm -rf "${tmp}"
  else
    if [[ -n "${cached_sha}" ]]; then
      printf '%s\n' "${cached_sha}" > "${RELEASE}/toolchain-archive.sha256"
    else
      log "::warning::Using cached ${TOOLCHAIN} without recorded archive checksum"
    fi
  fi
  TOOLCHAIN_BIN="${dir}/bin"
  export PATH="${TOOLCHAIN_BIN}:${PATH}"
  "${TOOLCHAIN_BIN}/clang" --version > "${RELEASE}/toolchain-version.txt"
  sed -n '1,2p' "${RELEASE}/toolchain-version.txt"
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
  MANAGER_EFFECTIVE_REPO="${repo}"
  MANAGER_EFFECTIVE_REF="${ref}"
  export MANAGER_EFFECTIVE_REPO MANAGER_EFFECTIVE_REF
  local url="https://raw.githubusercontent.com/${repo}/${ref}/${MANAGER_SETUP}"
  log "Manager setup ${repo} @ ${ref}"
  rm -rf "${KERNEL_DIR}/KernelSU" "${KERNEL_DIR}/KernelSU-Next" \
    "${KERNEL_DIR}/drivers/kernelsu" "${KERNEL_DIR}/common/drivers/kernelsu"
  curl -fsSL "${url}" -o "${SRC}/manager-setup.sh"
  sha256sum "${SRC}/manager-setup.sh" | awk '{print $1}' > "${RELEASE}/manager-setup.sha256"
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
  setup_manager_from "${MANAGER_REPO}" "${MANAGER_REF}"
  kconfig_path >/dev/null || die "Manager setup did not create a kernel Kconfig"
}

record_manager_commit() {
  local candidate
  : > "${RELEASE}/manager-commit.txt"
  if [[ "${MANAGER}" == "none" ]]; then
    printf 'n/a\n' > "${RELEASE}/manager-commit.txt"
    return 0
  fi
  for candidate in "${KERNEL_DIR}/KernelSU" "${KERNEL_DIR}/KernelSU-Next"; do
    if git -C "${candidate}" rev-parse HEAD >/dev/null 2>&1; then
      git -C "${candidate}" rev-parse HEAD > "${RELEASE}/manager-commit.txt"
      return 0
    fi
  done
  printf 'unknown\n' > "${RELEASE}/manager-commit.txt"
  if [[ "${MANAGER}" != "none" ]]; then
    log "::warning::Could not determine the installed manager commit"
  fi
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
  if [[ "${ENABLE_NOMOUNT}" != "true" ]]; then
    log "NoMount disabled"
    return
  fi
  local repo_base="${NOMOUNT_REPO%.git}"
  repo_base="${repo_base%/}"
  local raw
  if [[ "${repo_base}" == https://github.com/* ]]; then
    local slug="${repo_base#https://github.com/}"
    raw="https://raw.githubusercontent.com/${slug}/${NOMOUNT_REF}/kernel/setup.sh"
  else
    raw="${repo_base}/raw/${NOMOUNT_REF}/kernel/setup.sh"
  fi
  log "NoMount setup @ ${NOMOUNT_REF}"
  curl -fsSL "${raw}" -o "${SRC}/nomount-setup.sh"
  sha256sum "${SRC}/nomount-setup.sh" | awk '{print $1}' > "${RELEASE}/nomount-setup.sha256"
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
  if [[ -z "${JOBS_FORCE:-}" && -n "${TOOLCHAIN_MAX_JOBS}" && "${jobs}" -gt "${TOOLCHAIN_MAX_JOBS}" ]]; then
    log "Capping jobs from ${jobs} to ${TOOLCHAIN_MAX_JOBS} for ${TOOLCHAIN}"
    jobs="${TOOLCHAIN_MAX_JOBS}"
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
  if [[ -n "${KERNEL_NAME}" ]]; then
    local localver="${KERNEL_NAME}"
    [[ "${localver}" == -* ]] || localver="-${localver}"
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" --set-str LOCALVERSION "${localver}" ) || true
    log "Kernel localversion: ${localver} (${KBUILD_BUILD_USER}@${KBUILD_BUILD_HOST})"
  fi
  # uname suffix like -g<hash12>-ab<run id>. .scmversion replaces the git detection in
  # scripts/setlocalversion, so no "-dirty" is ever appended.
  ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e LOCALVERSION_AUTO ) || true
  local sha scm
  if sha="$(git -C "${KERNEL_DIR}" rev-parse --short=12 HEAD 2>/dev/null)"; then
    scm="-g${sha}-ab${GITHUB_RUN_ID:-0}"
    printf '%s' "${scm}" > "${KERNEL_DIR}/.scmversion"
    printf '%s' "${scm}" > "${out}/.scmversion"
    log "uname suffix: ${scm}"
  fi
  if [[ "${MANAGER}" != "none" ]]; then
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e KSU )
  fi
  if [[ "${ENABLE_SUSFS}" == "true" ]]; then
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e KSU_SUSFS )
  fi
  if [[ "${ENABLE_NOMOUNT}" == "true" ]]; then
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" -e NOMOUNT )
  else
    ( cd "${KERNEL_DIR}" && "${cfg[@]}" -d NOMOUNT ) || true
  fi
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
  if [[ "${MANAGER}" != "none" ]] && ! grep -Eq '^(CONFIG_KSU=y|CONFIG_KSU=m)$' "${out}/.config"; then
    die "CONFIG_KSU did not stay enabled"
  fi
  if [[ "${ENABLE_SUSFS}" == "true" ]] && ! grep -q '^CONFIG_KSU_SUSFS=y$' "${out}/.config"; then
    die "CONFIG_KSU_SUSFS did not stay enabled"
  fi
  if [[ "${ENABLE_NOMOUNT}" == "true" ]] && ! grep -q '^CONFIG_NOMOUNT=y$' "${out}/.config"; then
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

    local ko_roots=("${out}")
    if [[ -n "${MODULES_SRC}" && -d "${KERNEL_DIR}/${MODULES_SRC}" ]]; then
      ko_roots+=("${KERNEL_DIR}/${MODULES_SRC}")
    fi
    if find "${ko_roots[@]}" -name '*.ko' -print -quit | grep -q .; then
      find "${ko_roots[@]}" -name '*.ko' -print0 | tar --null -T - -czf "${RELEASE}/modules.tar.gz"
    fi
    if find "${out}/arch/${ARCH}/boot/dts" -name '*.dtb' -print -quit 2>/dev/null | grep -q .; then
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
  local module skipped="${RELEASE}/skipped-techpack.txt"
  : > "${skipped}"
  while IFS= read -r module; do
    [[ -z "${module}" || "${module}" == \#* ]] && continue
    if [[ ! -d "${src}/${module}" ]]; then
      log "::warning::Skipping missing techpack ${module}"
      printf '%s\n' "${module}" >> "${skipped}"
      continue
    fi
    log "Techpack ${module}"
    run_techpack_module "${KERNEL_DIR}" "${src}/${module}" "${jobs}" "${out}" "${ARCH}" "${cc}"
  done < "${ROOT}/${MODULES_LIST}"
  if [[ ! -s "${skipped}" ]]; then
    rm -f "${skipped}"
  else
    log "::warning::$(wc -l < "${skipped}" | tr -d ' ') configured techpack module(s) were not present; see skipped-techpack.txt"
  fi
}

write_build_metadata() {
  local zip_name="$1"
  python3 "${ROOT}/scripts/write_metadata.py" --release-dir "${RELEASE}" --zip-name "${zip_name}"
}

package_zip() {
  local ak="${ROOT}/ak3-work"
  rm -rf "${ak}"
  clone_ref "${ANYKERNEL_REPO}" "${ak}" "${ANYKERNEL_REF}"
  git -C "${ak}" rev-parse HEAD > "${RELEASE}/anykernel-commit.txt"
  local susfs_tag="nosusfs" nm_tag="nm-off"
  [[ "${ENABLE_NOMOUNT}" == "true" ]] && nm_tag="nm-on"
  [[ "${ENABLE_SUSFS}" == "true" ]] && susfs_tag="susfs"
  local version
  version="$(tr -d '\n' < "${RELEASE}/susfs-version.txt" 2>/dev/null || true)"
  local string="${DEVICE} ${SOURCE_DISPLAY}"
  [[ -n "${KERNEL_NAME}" ]] && string="${string} (${KERNEL_NAME#-})"
  string="${string} ${MANAGER_DISPLAY} ${susfs_tag} ${nm_tag}"
  [[ -n "${version}" ]] && string="${string} ${version}"
  export AK_KERNEL_STRING="${string}" AK_DEVICE_NAME_1="${DEVICE_NAME_1}" AK_DEVICE_NAME_2="${DEVICE_NAME_2}"
  python3 - "${ROOT}/ak3/anykernel.sh" "${ak}/anykernel.sh" <<'PYAK'
import os, pathlib, re, sys
source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
def shell_single_quoted_value(value: str) -> str:
    # The AnyKernel properties block is a shell single-quoted string.
    return value.replace("'", "'\\''")
values = {
    "__KERNEL_STRING__": shell_single_quoted_value(os.environ["AK_KERNEL_STRING"]),
    "__DEVICE_NAME_1__": shell_single_quoted_value(os.environ["AK_DEVICE_NAME_1"]),
    "__DEVICE_NAME_2__": shell_single_quoted_value(os.environ["AK_DEVICE_NAME_2"]),
}
pattern = re.compile("|".join(re.escape(key) for key in values))
source = pattern.sub(lambda match: values[match.group(0)], source)
remaining = ("__KERNEL_STRING__", "__DEVICE_NAME_1__", "__DEVICE_NAME_2__")
if any(token in source for token in remaining):
    raise SystemExit("Unexpanded AnyKernel template placeholder remains")
pathlib.Path(sys.argv[2]).write_text(source, encoding="utf-8")
PYAK
  if [[ -z "${DEVICE_NAME_2}" ]]; then
    sed -i '/^device.name2=/d' "${ak}/anykernel.sh"
  fi
  local image
  image=""
  for candidate in Image Image.gz Image.gz-dtb; do
    if [[ -s "${RELEASE}/${candidate}" ]]; then
      image="${RELEASE}/${candidate}"
      break
    fi
  done
  [[ -n "${image}" ]] || die "No packaged kernel image found in ${RELEASE}"
  cp -f "${image}" "${ak}/"
  rm -rf "${ak}/.git" "${ak}/README.md" "${ak}/"*.placeholder
  local run="${GITHUB_RUN_NUMBER:-local}"
  local name="${DEVICE}-${SOURCE_KEY}-${MANAGER}-${susfs_tag}-${nm_tag}-r${run}.zip"
  (
    cd "${ak}"
    zip -r9 "${RELEASE}/${name}" . -x '.git/*'
  )
  ( cd "${RELEASE}" && sha256sum "${name}" > "${name}.sha256" )
  write_build_metadata "${name}"
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
record_manager_commit
apply_nomount
make_kernel
package_zip
log "Done"
