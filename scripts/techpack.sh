#!/usr/bin/env bash
# Build one Qualcomm out-of-tree module while honoring its vendor wrapper Makefile.

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

  # Qualcomm wrappers may be inside the module or one level above it.
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
    # IMPORTANT: preserve symlink components such as qcacld-3.0/.qca6490.
    # realpath without -s follows that symlink and silently changes the WLAN
    # profile name inferred by the vendor Kbuild from M.
    module_rel="$(realpath -s --relative-to="${kernel_dir}" "${module_dir}")"

    if ! grep -Eq '^[[:space:]]*(modules([[:space:]]|:)|%[[:space:]]*:)' "${wrapper_makefile}"; then
      if grep -Eq '^[[:space:]]*all[[:space:]]*:' "${wrapper_makefile}"; then
        target="all"
      else
        printf '::error::Techpack wrapper has no modules/all target: %s\n' "${wrapper_makefile}" >&2
        return 1
      fi
    fi

    printf 'Techpack wrapper: %s (M=%s, target=%s)\n' "${wrapper_dir}" "${module_rel}" "${target}"
    make -C "${wrapper_dir}" -j"${jobs}" \
      KERNEL_SRC="${kernel_dir}" \
      OUT_DIR="${kernel_dir}" \
      O="${out}" \
      ARCH="${arch}" LLVM=1 LLVM_IAS=1 CC="${cc}" \
      M="${module_rel}" PWD="${module_dir}" \
      "${target}"
  else
    printf 'Techpack direct Kbuild: %s\n' "${module_dir}"
    make -C "${kernel_dir}" -j"${jobs}" O="${out}" ARCH="${arch}" \
      LLVM=1 LLVM_IAS=1 CC="${cc}" M="${module_dir}" \
      KERNEL_SRC="${kernel_dir}" OUT_DIR="${kernel_dir}" modules
  fi
}
