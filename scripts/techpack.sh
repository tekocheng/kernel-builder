#!/usr/bin/env bash
# Build one Qualcomm out-of-tree module while honoring its vendor wrapper Makefile.

# Upstream aosp-pablo/android_kernel_xiaomi_sm8450-modules (branch 17) declares
# max_hs_timer_supported twice in struct dsi_ctrl, which clang rejects with
# "duplicate member". Keep the first declaration and drop the repeat.
# Safe to run on every build: it changes nothing when there is no duplicate.
fix_duplicate_dsi_ctrl_member() {
  local header="$1/dsi/dsi_ctrl.h"
  [[ -f "${header}" ]] || return 0
  local tmp="${header}.fix"
  awk '
    /^struct dsi_ctrl [{]/ { in_struct = 1 }
    in_struct && /^[[:space:]]*bool max_hs_timer_supported;[[:space:]]*$/ { if (seen++) next }
    in_struct && /^[}];/ { in_struct = 0 }
    { print }
  ' "${header}" > "${tmp}"
  if cmp -s "${header}" "${tmp}"; then
    rm -f "${tmp}"
  else
    mv "${tmp}" "${header}"
    printf '::warning::Removed duplicate max_hs_timer_supported from %s\n' "${header}"
  fi
}

run_techpack_module() {
  local kernel_dir="$1"
  local module_dir="$2"
  local jobs="$3"
  local out="$4"
  local arch="$5"
  local cc="$6"

  local wrapper_dir=""
  local candidate
  local module_rel
  local wrapper_makefile
  local target="modules"

  fix_duplicate_dsi_ctrl_member "${module_dir}"

  # Most Qualcomm techpack modules ship a wrapper Makefile which supplies
  # required Kbuild variables (MMRM_ROOT, AUDIO_ROOT, CAMERA_KERNEL_ROOT,
  # CVP_ROOT, WLAN_ROOT, KBUILD_EXTRA_SYMBOLS, and others). Some nested
  # modules, such as qcacld-3.0/.qca6490, keep that wrapper one level up.
  for candidate in "${module_dir}" "$(dirname "${module_dir}")"; do
    if [[ -f "${candidate}/Makefile" ]] && \
       grep -Eq 'KERNEL_SRC|KBUILD_OPTIONS' "${candidate}/Makefile" && \
       grep -Fq '$(MAKE)' "${candidate}/Makefile"; then
      wrapper_dir="${candidate}"
      wrapper_makefile="${candidate}/Makefile"
      break
    fi
  done

  if [[ -n "${wrapper_dir}" ]]; then
    # Qualcomm wrappers expect M to be relative to KERNEL_SRC. Keep M pointed
    # at the actual module directory even when its wrapper is in the parent.
    # Preserve symlink components such as qcacld-3.0/.qca6490 so Qualcomm Kbuild
    # can infer the correct WLAN profile from M.
    module_rel="$(realpath -s --relative-to="${kernel_dir}" "${module_dir}")"

    # Most wrappers expose modules (often through a % rule). A few legacy
    # wrappers expose only all, which itself invokes the kernel modules target.
    if ! grep -Eq '^[[:space:]]*(modules([[:space:]]|:)|%[[:space:]]*:)' "${wrapper_makefile}"; then
      if grep -Eq '^[[:space:]]*all[[:space:]]*:' "${wrapper_makefile}"; then
        target="all"
      else
        printf '::error::Techpack wrapper has no modules/all target: %s\n' "${wrapper_makefile}" >&2
        return 1
      fi
    fi

    printf 'Techpack wrapper: %s (M=%s, target=%s)\n' "${wrapper_dir}" "${module_rel}" "${target}"

    # OUT_DIR is the Qualcomm wrapper's source-tree anchor, not Kbuild's
    # object directory. Their wrappers use OUT_DIR/../sm8450-modules to find
    # Module.symvers. O continues to point at the real Kbuild output directory.
    make -C "${wrapper_dir}" -j"${jobs}" \
      KERNEL_SRC="${kernel_dir}" \
      OUT_DIR="${kernel_dir}" \
      O="${out}" \
      ARCH="${arch}" LLVM=1 LLVM_IAS=1 CC="${cc}" \
      M="${module_rel}" PWD="${module_dir}" \
      "${target}"

    # With O= set, Kbuild writes the module's Module.symvers and .ko under
    # ${out}/${module_rel}, but wrappers of dependent modules look for
    # Module.symvers in the source tree (KBUILD_EXTRA_SYMBOLS). Mirror both there
    # so later modules link and the .ko files are collected from the source tree.
    local built_dir
    built_dir="$(realpath -m "${out}/${module_rel}")"
    if [[ -d "${built_dir}" && "${built_dir}" != "${module_dir}" ]]; then
      ( cd "${built_dir}" && find . \( -name Module.symvers -o -name '*.ko' \) \
          -exec cp -f --parents {} "${module_dir}/" \; )
    fi
  else
    # Keep support for generic external modules that only provide Kbuild rules
    # and no Qualcomm wrapper Makefile.
    printf 'Techpack direct Kbuild: %s\n' "${module_dir}"
    make -C "${kernel_dir}" -j"${jobs}" O="${out}" ARCH="${arch}" \
      LLVM=1 LLVM_IAS=1 CC="${cc}" M="${module_dir}" \
      KERNEL_SRC="${kernel_dir}" OUT_DIR="${kernel_dir}" modules
  fi
}
