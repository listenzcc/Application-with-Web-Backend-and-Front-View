# Interact with fds2ascii

```powershell
$ fds2ascii.exe
 Enter Job ID string (CHID):
1
 What type of file to parse?
 PL3D file? Enter 1
 SLCF file? Enter 2
 BNDF file? Enter 3
1
 Enter Sampling Factor for Data?
 (1 for all data, 2 for every other point, etc.)
1
 Domain selection:
   y - domain size is limited
   n - domain size is not limited
   z - domain size is not limited and z levels are offset
   ya, na or za - slice files are selected based on type and location.
       The y, n, z prefix are defined as before.
n
    1   1_1_10p04.q, MESH    1, Time:   10.
    2   1_1_20p00.q, MESH    1, Time:   20.

Choose PLOT3D .q file by its index: (0 to end)
1
 Reading PLOT3D data file...
Enter output file name:
3d-1.txt
 Writing to file...      3d-1.txt
    1   1_1_10p04.q, MESH    1, Time:   10.
    2   1_1_20p00.q, MESH    1, Time:   20.

Choose PLOT3D .q file by its index: (0 to end)
2
 Reading PLOT3D data file...
Enter output file name:
3d-2.txt
 Writing to file...      3d-2.txt
    1   1_1_10p04.q, MESH    1, Time:   10.
    2   1_1_20p00.q, MESH    1, Time:   20.

Choose PLOT3D .q file by its index: (0 to end)
0
Stop - Program terminated.
```
