# %%
import os
import time
import tempfile
import pandas as pd
import multiprocessing as mp

from pathlib import Path
from tqdm.auto import tqdm

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
        'indexForVariables': 1,  # Slice axis: 1=y，2=x，3=z
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


# %%
if __name__ == '__main__':
    # Prepare directory and constants
    JOB_ID = '4'

    OUTPUT_DIR = Path('./output')
    try:
        os.remove(OUTPUT_DIR)
    except:
        pass
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find the time points
    devc = pd.read_csv(f'{JOB_ID}_devc.csv', header=1)
    print(devc)
    times = devc['Time']
    times = times - times % 0.1
    print(times)

    # Processing
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


# # %% -------------------------
# JOB_ID = '4'

# # %%
# OUTPUT_DIR = Path('./output')
# try:
#     os.remove(OUTPUT_DIR)
# except:
#     pass
# OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# # %%
# devc = pd.read_csv(f'{JOB_ID}_devc.csv', header=1)
# print(devc)

# times = devc['Time']
# times = times - times % 0.1
# print(times)

# # %%
# conf = {
#     'jobID': JOB_ID,
#     'type': 2,
#     'samplingFactor': 1,
#     'domainSelection': 'n',
#     'timeStarting': None,
#     'timeEnding': None,
#     'variablesToRead': 1,
#     'indexForVariables': 3,  # Slice axis: 1=y，2=x，3=z
#     'fileName': None
# }


# for t in tqdm(times, 'Computing times'):
#     conf['timeStarting'] = f'{t:0.1f}'
#     conf['timeEnding'] = f'{t + 0.1:0.1f}'
#     conf['fileName'] = f'output/u-{t:0.1f}-{t+0.1:0.1f}.txt'

#     with open('input.txt', 'w') as f:
#         f.write('\n'.join([str(e) for e in conf.values()]))

#     os.system('fds2ascii < input.txt')
