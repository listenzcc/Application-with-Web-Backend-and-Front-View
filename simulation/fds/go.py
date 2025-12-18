import os

# PROJECT_NAME = '4'

conf = {
    'jobID': '4',
    'type': 2,
    'samplingFactor': 1,
    'domainSelection': 'n',
    'timeStarting': None,
    'timeEnding': None,
    'variablesToRead': 1,
    'indexForVariables': 2,
    'fileName': None
}

try:
    os.mkdir('output')
except:
    pass

num = 100

for i in range(num):
    t = i*0.1
    conf['timeStarting'] = f'{t:0.1f}'
    conf['timeEnding'] = f'{t + 0.1:0.1f}'
    conf['fileName'] = f'output/u-{t:0.1f}-{t+0.1:0.1f}.txt'

    with open('input.txt', 'w') as f:
        f.write('\n'.join([str(e) for e in conf.values()]))

    os.system('fds2ascii < input.txt')


# j = 0


# for i in range(20, 1749, 33):
#     j = j + 1
#     with open('input.txt', 'w') as f:
#         f.write(PROJECT_NAME+"\n2\n1\nn\n30.0\n30.1\n1\n" +
#                 str(i)+"\nu"+str(j)+".txt\n")

#     os.system("fds2ascii<input.txt")
