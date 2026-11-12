# AnyKernel3 install script. Device names and the banner string are filled in at package time.
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
'; }

block=boot;
is_slot_device=auto;
ramdisk_compression=auto;
patch_vbmeta_flag=auto;

. tools/ak3-core.sh;

dump_boot;
write_boot;
