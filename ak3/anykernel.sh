### Minimal AnyKernel3 installer for Poco F5 / Redmi Note 12 Turbo.
# Device names and the kernel string are filled in at package time.
# Variable names below must be UPPERCASE. Current AnyKernel3 ignores lowercase
# names such as block= and is_slot_device=, and then cannot find the boot partition.
properties() { '
kernel.string=__KERNEL_STRING__
do.devicecheck=1
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=__DEVICE_NAME_1__
device.name2=__DEVICE_NAME_2__
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; } # end properties

# boot shell variables. AnyKernel3 detects the active slot and the boot partition.
BLOCK=boot;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

# import functions/variables and setup patching - see for reference (DO NOT REMOVE)
. tools/ak3-core.sh;

# Kernel-only install: unpack the boot image but leave its ramdisk untouched.
split_boot;

# Keep a copy of the current boot image before replacing it. Best effort: a
# recovery without writable storage prints a warning and the flash continues.
backup_current_boot() {
  local backup_dir="/sdcard/marble-kernel-backup"
  local stamp backup_img

  stamp="$(date +%Y%m%d-%H%M%S 2>/dev/null || date +%s)";
  backup_img="${backup_dir}/boot-marble${SLOT:-}-${stamp}.img";

  ui_print " ";
  ui_print "Backing up current boot image...";
  if [ -s "$BOOTIMG" ] && mkdir -p "$backup_dir" 2>/dev/null && cp -f "$BOOTIMG" "$backup_img" 2>/dev/null; then
    ui_print "Backup saved:";
    ui_print "$backup_img";
  else
    ui_print "Warning: boot backup was not saved (is /sdcard mounted?). Continuing.";
  fi;
}

backup_current_boot;
flash_boot;
