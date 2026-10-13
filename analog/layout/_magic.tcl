crashbackups stop
gds read /scratch/jobs/685565f0939945139330ff0d411fce65/run/repo/analog/layout/LS_UP_LS_IN.gds
load LS_UP_LS_IN
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o /scratch/jobs/685565f0939945139330ff0d411fce65/run/repo/analog/layout/LS_UP_LS_IN.ext.spice
quit -noprompt
