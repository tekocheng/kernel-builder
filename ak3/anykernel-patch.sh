### AnyKernel3 installer with a KernelSU / SUSFS menu (Bouquet style).
# The ZIP carries one stock Image plus binary diffs in bs_patches/. Volume keys
# choose which diff is applied, and every result is checked against a SHA-1
# from bs_patches/sha1.env, so a damaged or mismatched image is never flashed.
# Device names and the kernel string are filled in at package time.
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

# boot shell variables. Names must be UPPERCASE for current AnyKernel3.
BLOCK=boot;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

# import functions/variables and setup patching - see for reference (DO NOT REMOVE)
. tools/ak3-core.sh;

# Kernel-only install: unpack the boot image but leave its ramdisk untouched.
split_boot;

# SHA1_STOCK is written by the builder. bs_patches/managers.txt lists the menu entries.
[ -f $AKHOME/bs_patches/sha1.env ] || abort "! Missing bs_patches/sha1.env";
. $AKHOME/bs_patches/sha1.env;

KEYCODE_UP=42;
KEYCODE_DOWN=41;
KEY_TIMEOUT=20;

sha1() { $BIN/magiskboot sha1 "$1"; }

# ask_yes_no "<line>" ["<line>" ...]
# Vol+ returns 0 (yes). Vol- returns 1 (no). No key within KEY_TIMEOUT seconds
# also returns 1, so an install from an app without key input flashes the
# plain kernel instead of hanging.
ask_yes_no() {
  local rc1 rc2;

  ui_print " ";
  while [ $# != 0 ]; do
    ui_print "# $1";
    shift;
  done;
  ui_print "#";
  ui_print "# Vol+ = Yes, Vol- = No (no key in ${KEY_TIMEOUT}s = No).";
  while true; do
    # The first call reads the key press, the second one the key release.
    timeout $KEY_TIMEOUT $BIN/keycheck </dev/null; rc1=$?;
    case $rc1 in
      $KEYCODE_UP|$KEYCODE_DOWN) ;;
      *) ui_print "- No key pressed. Using No."; return 1;;
    esac;
    timeout $KEY_TIMEOUT $BIN/keycheck </dev/null; rc2=$?;
    [ "$rc1" = "$rc2" ] || continue;
    if [ "$rc2" = "$KEYCODE_UP" ]; then
      ui_print "- You chose Yes.";
      return 0;
    fi;
    ui_print "- You chose No.";
    return 1;
  done;
}

# apply_patch <image> <from sha1> <to sha1> <patch>
apply_patch() {
  local img=$1 from=$2 to=$3 patch=$4 now;

  now=$(sha1 $img);
  [ "$now" = "$to" ] && return 0;
  [ "$now" = "$from" ] || abort "! $(basename $img) does not match the expected stock image.";
  $BIN/hpatchz -f $img $patch $img.new >/dev/null 2>&1 || abort "! hpatchz failed on $(basename $patch).";
  mv -f $img.new $img;
  [ "$(sha1 $img)" = "$to" ] || abort "! Patched image checksum mismatch.";
}

# pick_manager: ask about each manager in bs_patches/managers.txt, in order.
# Line format: key;display name;sha1 of the manager image;sha1 of the SUSFS image or -
# The first Yes wins, then SUSFS is offered when a SUSFS patch exists for it.
# Sets use_patch and target_sha1. Returns 1 when every answer was No.
pick_manager() {
  local key display sha_m sha_s;

  [ -f $AKHOME/bs_patches/managers.txt ] || return 1;
  while IFS=';' read -r key display sha_m sha_s; do
    [ -n "$key" ] || continue;
    [ -f $AKHOME/bs_patches/$key.p ] || continue;
    if ask_yes_no \
        "Install the kernel with $display built in?" \
        "Vol- moves on. No to every choice installs the plain kernel."; then
      use_patch=$AKHOME/bs_patches/$key.p;
      target_sha1=$sha_m;
      if [ "$sha_s" != "-" ] && [ -f $AKHOME/bs_patches/$key-susfs.p ] && ask_yes_no \
          "Add SUSFS on top of $display?" \
          "Vol- keeps $display without SUSFS."; then
        use_patch=$AKHOME/bs_patches/$key-susfs.p;
        target_sha1=$sha_s;
      fi;
      return 0;
    fi;
  done < $AKHOME/bs_patches/managers.txt;
  return 1;
}

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

[ -s $AKHOME/Image ] || abort "! Missing Image.";
[ "$(sha1 $AKHOME/Image)" = "$SHA1_STOCK" ] || abort "! Kernel image is corrupted!";

use_patch=;
target_sha1=;
pick_manager || true;

if [ "$use_patch" ]; then
  ui_print " ";
  ui_print "- Patching kernel image...";
  apply_patch $AKHOME/Image $SHA1_STOCK $target_sha1 $use_patch;
fi;
rm -rf $AKHOME/bs_patches;

backup_current_boot;
flash_boot;
