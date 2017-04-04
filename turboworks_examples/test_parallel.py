"""
An example of running turboworks optimizations in parallel.
"""

import os
from fireworks import Workflow, Firework, LaunchPad
from turboworks.optimize import OptTask
from turboworks.optdb import OptDB
from turboworks.utils import random_guess
from turboworks_examples.calculate_task import BasicCalculateTask as CalculateTask


dims = [(1, 5), (1, 5), (1, 5)]

# a workflow creator function which takes z and returns a workflow based on z
def wf_creator(z):

    spec = {'A':z[0], 'B':z[1], 'C':z[2], '_tw_z':z}
    Z_dim = dims

    firework1 = Firework([CalculateTask(), OptTask(wf_creator ='turboworks_examples.test_parallel.wf_creator',
                                                   dimensions=Z_dim,
                                                   opt_label="parallel")], spec=spec)
    return Workflow([firework1])


# try a parallel implementation of turboworks
def load_parallel_wfs(n_processes):
    for i in range(n_processes):
        launchpad.add_wf(wf_creator(random_guess(dims)))


if __name__ == "__main__":

    TESTDB_NAME = 'turboworks'
    launchpad = LaunchPad(name=TESTDB_NAME)
    launchpad.reset(password=None, require_password=False)

    n_processes = 2
    n_runs = 5

    load_parallel_wfs(n_processes)

    for i in range(n_runs):
        sh_output = os.system('rlaunch -l my_launchpad.yaml multi ' + str(n_processes) + ' --nlaunches 1')
        print(sh_output)


    # tear down database
    # launchpad.connection.drop_database(TESTDB_NAME)




