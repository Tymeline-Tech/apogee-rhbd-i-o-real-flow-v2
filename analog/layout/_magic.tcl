crashbackups stop
gds read /scratch/jobs/b21d5fe53e484104ab06a90817c67c90/run/repo/analog/layout/TOP_IO.gds
load TOP_IO
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o /scratch/jobs/b21d5fe53e484104ab06a90817c67c90/run/repo/analog/layout/TOP_IO.ext.spice
quit -noprompt
