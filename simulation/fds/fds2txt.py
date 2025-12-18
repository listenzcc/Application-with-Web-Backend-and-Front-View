# %%
import time
import shutil
import tempfile
from tqdm import tqdm
import multiprocessing as mp
import os
import pandas as pd
from pathlib import Path
from tqdm.auto import tqdm

# %%
# Constants
WD = Path('../../received/4/')
JOB_ID = '4'

# cd to
os.chdir(WD)

# Make sure OUTPUT_DIR is clear
OUTPUT_DIR = Path('./output')
for e in OUTPUT_DIR.iterdir():
    e.unlink(missing_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# %%
# Get times
devc = pd.read_csv(f'{JOB_ID}_devc.csv', header=1)
print(devc)

times = devc['Time']
times = times - times % 0.1
print(times)

# %%


def process_time_point(t, job_id, output_dir='output'):
    """
    Process a single time point
    """
    conf = {
        'jobID': job_id,
        'type': 2,
        'samplingFactor': 1,
        'domainSelection': 'n',
        'timeStarting': f'{t:0.1f}',
        'timeEnding': f'{t + 0.1:0.1f}',
        'variablesToRead': 1,
        'indexForVariables': 2,  # Slice axis: 1=y，2=x，3=z
        'fileName': f'{output_dir}/u-{t:0.1f}-{t+0.1:0.1f}.txt'
    }

    # Create a temporary input file for this process
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write('\n'.join([str(e) for e in conf.values()]))
        temp_input_file = f.name

    try:
        # Run fds2ascii with the input file
        os.system(f'fds2ascii < {temp_input_file}')
    finally:
        # Clean up the temporary file
        os.unlink(temp_input_file)

    return t


def main():
    # Determine number of processes to use
    num_processes = min(mp.cpu_count(), len(times))

    tic = time.time()
    print(
        f"Processing {len(times)} time points using {num_processes} processes...")

    # Method 1: Using Process Pool (recommended for many tasks)
    with mp.Pool(processes=num_processes) as pool:
        # Prepare arguments for each time point
        args = [(t, JOB_ID, OUTPUT_DIR) for t in times]

        # Process time points in parallel with progress bar
        results = []
        for result in tqdm(
            pool.starmap(process_time_point, args),
            total=len(times),
            desc='Computing times'
        ):
            results.append((time.time()-tic, result))

    passed = time.time() - tic
    print(f"Processing complete ({passed:.4f} seconds)!")


# %%
if __name__ == '__main__':
    main()

# %%
