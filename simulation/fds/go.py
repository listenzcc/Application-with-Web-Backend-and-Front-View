# %%
import os
import pandas as pd
from pathlib import Path
from tqdm.auto import tqdm

# %%
DATA_DIR = Path('../../received/4/')
JOB_ID = '4'

# %%
os.chdir(DATA_DIR)

# %%
OUTPUT_DIR = Path('./output')
try:
    os.remove(OUTPUT_DIR)
except:
    pass
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# %%
devc = pd.read_csv(f'{JOB_ID}_devc.csv', header=1)
print(devc)

times = devc['Time']
times = times - times % 0.1
print(times)

# %%
conf = {
    'jobID': JOB_ID,
    'type': 2,
    'samplingFactor': 1,
    'domainSelection': 'n',
    'timeStarting': None,
    'timeEnding': None,
    'variablesToRead': 1,
    'indexForVariables': 2,  # Slice axis: 1=y，2=x，3=z
    'fileName': None
}


for t in tqdm(times, 'Computing times'):
    conf['timeStarting'] = f'{t:0.1f}'
    conf['timeEnding'] = f'{t + 0.1:0.1f}'
    conf['fileName'] = f'output/u-{t:0.1f}-{t+0.1:0.1f}.txt'

    with open('input.txt', 'w') as f:
        f.write('\n'.join([str(e) for e in conf.values()]))

    os.system('fds2ascii < input.txt')
