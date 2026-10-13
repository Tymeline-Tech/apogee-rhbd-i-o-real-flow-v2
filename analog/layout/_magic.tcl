crashbackups stop
gds read /scratch/jobs/23309ef0c7de4b509e4fc3fc2f2aa08b/run/repo/analog/layout/por.gds
load por
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o /scratch/jobs/23309ef0c7de4b509e4fc3fc2f2aa08b/run/repo/analog/layout/por.ext.spice
quit -noprompt
