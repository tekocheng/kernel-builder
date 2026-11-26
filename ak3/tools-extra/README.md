# Extra AnyKernel3 tools for the patch-menu installer

Prebuilt static Android binaries used only by `ak3/anykernel-patch.sh`
(`build_scope=image-menu`). They are copied into the ZIP's `tools/` directory.

| File | What it is | Used for |
|---|---|---|
| `hpatchz` | [HDiffPatch](https://github.com/sisong/HDiffPatch) patcher, aarch64, static | applies `bs_patches/*.p` to the stock `Image` |
| `keycheck` | volume-key reader, ARM, static | the Vol+ / Vol- menu |

Both were taken from the Bouquet Kernel v5.3 AnyKernel3 package
(Pzqqt/android_kernel_xiaomi_marble). Replace them with your own builds if you
prefer; keep the file names.

SHA-256:

    sha256sum ak3/tools-extra/*
