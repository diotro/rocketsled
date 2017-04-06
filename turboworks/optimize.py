"""
The FireTask for running automatic optimization loops are contained in this module.
"""

import sys
import itertools
from bson.objectid import ObjectId
from fireworks.utilities.fw_utilities import explicit_serialize
from fireworks.core.firework import FireTaskBase
from fireworks import FWAction
from pymongo import MongoClient
from references import dtypes
from fireworks import LaunchPad

__author__ = "Alexander Dunn"
__version__ = "0.1"
__email__ = "ardunn@lbl.gov"

@explicit_serialize
class OptTask(FireTaskBase):
    """
    A FireTask for running optimization loops automatically.

    OptTask takes in and stores a vector 'x' which uniquely defines the input space and a scalar 'y' which is the
    scoring metric. OptTask produces a new x vector to minimize y using information from all x vectors (X) and y
    scalars (Y). Additionally, a z vector of extra features can be used by OptTask to better optimize, although new
    values of z will be discarded.

    Attributes:
        wf_creator (function): returns a workflow based on a unique vector, x.
        dimensions ([tuple]): each 2-tuple in the list defines the search space in (low, high) format.
            For categorical dimensions, includes all possible categories as a list.
            Example: dimensions = dim = [(1,100), (9.293, 18.2838), ("red", "blue", "green")].
        get_z (string): the fully-qualified name of a function which, given a x vector, returns another vector z which
            provides extra information to the machine learner. The features defined in z are not used to run the
            workflow creator.
            Examples: 
                get_z = 'my_module.my_fun'
                get_z = '/path/to/folder/containing/my_package.my_module.my_fun'
        predictor (string): names a function which given a list of inputs, a list of outputs, and a dimensions space,
            can return a new optimized input vector. Can specify either a skopt function or a custom function.
            Example: predictor = 'my_module.my_predictor'
        max (bool): Makes optimization tend toward maximum values instead of minimum ones.
        wf_creator_args (list): details the positional args to be passed to the wf_creator function alongsize the z
            vector
        wf_creator_kwargs (dict): details the kwargs to be passed to the wf_creator function alongside the z vector
        duplicate_check (bool): If True, checks for duplicate guesss in discrete, finite spaces. (NOT currently 100%
            working with concurrent workflows). Default is no duplicate check.
        host (string): The name of the MongoDB host where the optimization data will be stored. The default is
            'localhost'.
        port (int): The number of the MongoDB port where the optimization data will be stored. The default is 27017.
        name (string): The name of the MongoDB database where the optimization data will be stored.
        opt_label (string): Names the collection of that the particular optinization's data will be stored in. Multiple
            collections correspond to multiple independent optimization.
    """

    _fw_name = "OptTask"
    required_params = ['wf_creator', 'dimensions']
    optional_params = ['get_z', 'predictor', 'max', 'wf_creator_args', 'wf_creator_kwargs', 'duplicate_check',
                       'host', 'port', 'name','opt_label', 'lpad']


    def _store(self, spec, update = False, id = None):
        """
        Stores and updates turboworks database files.
        
        Args:
            spec (dict): a turboworks-generated spec (or subset of a spec) to be stored in the turboworks db.
            update (bool): whether to update the document (True) or insert a new one (False)
            id (ObjectId): the PyMongo BSON id object. if update == True, updates the document with this id.
            
        Returns:
            (ObjectId) the PyMongo BSON id object for the document inserted/updated.
        """

        if update == False:
            return self.collection.insert_one(spec)
        else:
            return self.collection.update({"_id":id },{'$set' : spec})

    def _deserialize_function(self, fun):
        """
        Takes a fireworks serialzed function handle and maps it to a function object.

        Args:
            fun (string): a 'module.function' or '/path/to/mod.func' style string specifying the function
         
        Returns:
            (function) The function object defined by fun
        """
        #todo: merge with PyTask's deserialze code, move to fw utils

        toks = fun.rsplit(".", 1)
        modname, funcname = toks

        if "/" in toks[0]:
            path, modname = toks[0].rsplit("/", 1)
            sys.path.append(path)

        mod = __import__(str(modname), globals(), locals(), fromlist=[str(funcname)])
        return getattr(mod, funcname)


    def _is_discrete(self, dims):
        """
        Checks if the search space is totally discrete.

        Args:
            dims ([tuple]): dimensions of the search space
            
        Returns:
            (bool) whether the search space is totally discrete.
        """

        for dim in dims:
            if type(dim[0]) not in dtypes.discrete or type(dim[1]) not in dtypes.discrete:
                return False
        return True

    def _calculate_discrete_space(self, dims):
        """
        Calculates all entries in a discrete space.

        Example:

            >>> dims = [(1,2), ["red","blue"]]
            >>> space = _calculate_discrete_space(dims)
            >>> space
            [(1, 'red'), (1, 'blue'), (2, 'red'), (2, 'blue')]

        Args:
            dims ([tuple]): dimensions of the search space.

        Returns:
            ([list]) all possible combinations inside the discrete space
        """

        total_dimspace = []

        for dim in dims:
            if type(dim[0]) in dtypes.ints:
                # Then the dimension is of the form (lower, upper)
                lower = dim[0]
                upper = dim[1]
                dimspace = list(range(lower, upper + 1))
            elif type(dim[0]) in dtypes.floats:
                raise ValueError("The dimension is a float. The dimension space is infinite.")
            else:  # The dimension is a discrete finite string list
                dimspace = dim
            total_dimspace.append(dimspace)

        return [[x] for x in total_dimspace[0]] if len(dims)==1 else list(itertools.product(*total_dimspace))

    def _dupe_check(self, x, X_dim):
        """
        Check for duplicates so that expensive workflow will not be needlessly rerun.

        Args:
            x (list): input to be duplicate checked
            X_dim ([tuples]): space in which to check for duplicate

        Returns:
            (list) updated input which is either the duplicate-checked input z or a randomly picked replacement
        """

        # todo: available_x should be stored per job, so it does not have to be created more than once.
        # TODO: I would agree that a performance improvement is needed, e.g. by only computing the full discrete space as well as available z only once (-AJ)
        available_x = self._calculate_discrete_space(X_dim) # all possible choices in the discrete space (expensive)

        for doc in self.collection.find():
            if tuple(doc['x']) in available_x:
                available_x.remove(tuple(doc['x']))

        if len(available_x) == 0:
            raise ValueError("The search space has been exhausted.")


        if x in available_x:
            return x
        else:
            import random
            return random.choice(available_x)

    @property
    def _Z_dims(self):
        """
        Creates some Z dimensions so that the optimizer can run without the user specifing the Z dimension range.
        Simply sets each dimension equal to the (lowest, highest) values of any z for that dimension in the database.
        If there is only one document in the database, it sets the dimension to slightly higher and lower values than
        the z dimension value. For categorical dimensions, it includes all dimensions in Z.

        Returns:
            ([tuple]) a list of dimensions
        """

        Z = [doc['z'] for doc in self.collection.find()]
        dims = [[z, z] for z in Z[0]]
        check = dims

        cat_values = []

        for z in Z:
            for i, dim in enumerate(dims):
                if type(z[i]) in dtypes.others:
                    # the dimension is categorical
                    if z[i] not in cat_values:
                        cat_values.append(z[i])
                        dims[i] = cat_values
                else:
                    if z[i] < dim[0]:
                        # this value is the new minimum
                        dims[i][0] = z[i]
                    elif z[i] > dim[1]:
                        # this value is the new maximum
                        dims[i][1] = z[i]
                    else:
                        pass

        if dims == check:  # there's only one document
            for i, dim in enumerate(dims):
                if type(dim[0]) in dtypes.numbers:
                    # invent some dimensions
                    # the prediction coming from these dimensions will not be used anyway, since it is z
                    if type(dim[0]) in dtypes.floats:
                        dim[0] = dim[0] - 0.05 * dim[0]
                        dim[1] = dim[1] + 0.05 * dim[1]
                    elif type(dim[0]) in dtypes.ints:
                        dim[0] = dim[0] - 1
                        dim[1] = dim[1] + 1

                    if dim[0] > dim[1]:
                        dim = [dim[1], dim[0]]

                    dims[i] = dim

        dims = [tuple(dim) for dim in dims]
        return dims

    def run_task(self, fw_spec):
        """
        FireTask implementation of running the optimization loop.

        Args:
            fw_spec (dict): the firetask spec. Must contain a '_tw_y' key with a float type field and must contain
                a '_tw_x' key containing a vector uniquely defining the search space.

        Returns:
            (FWAction)
        """
        x = fw_spec['_tw_x']
        y = fw_spec['_tw_y']

        # type safety for dimensions to avoid cryptic skopt errors
        X_dims = [tuple(dim) for dim in self['dimensions']]

        wf_creator = self._deserialize_function(self['wf_creator'])

        wf_creator_args = self['wf_creator_args'] if 'wf_creator_args' in self else []
        if not isinstance(wf_creator_args, list) or isinstance(wf_creator_args, tuple):
            raise TypeError("wf_creator_args should be a list/tuple of positional arguments")


        wf_creator_kwargs = self['wf_creator_kwargs'] if 'wf_creator_kwargs' in self else {}
        if not isinstance(wf_creator_kwargs, dict):
            raise TypeError("wf_creator_kwargs should be a dictonary of keyword arguments.")

        opt_label = self['opt_label'] if 'opt_label' in self else 'opt_default'

        # determine which Mongodb will store optimization data
        if any(k in self for k in ('host', 'port', 'name')):
            if all(k in self for k in ('host', 'port', 'name')):
                # the db is being defined with a host, port, and name.
                host, port, name = [self[k] for k in ('host', 'port', 'name')]
            else:
                # one of host, port, or name has not been specified
                raise AttributeError("Host, port, and name must all be specified!")
        elif 'lpad' in self:
            # the db is defined by a Firework's Launchpad object
            lpad = self['lpad']
            host, port, name = [lpad[k] for k in ('host', 'port', 'name')]
        elif '_add_launchpad_and_fw_id' in fw_spec:
            # the db is defined by fireworks placing an lpad object in the spec.
            if fw_spec['_add_launchpad_and_fw_id']:
                # host, port, name = [self.launchpad[k] for k in ('host', 'port', 'name')]
                # host, port, name = [self.launchpad[k] for k in ('host', 'port', 'name')]
                #todo: currently not working
                pass

        #todo: add my_launchpad.yaml option via Launchpad.auto_load()?
        else:
            raise AttributeError("The optimization database must be specified explicitly (with host, port, and name)"
                                 " with a Launchpad object (lpad), or by setting _add_launchpad_and_fw_id to True on"
                                 " the fw_spec.")


        mongo = MongoClient(host, port)
        db = getattr(mongo, name)
        self.collection = getattr(db, opt_label)

        # fetch z
        z = self._deserialize_function(self['get_z'])(x) if 'get_z' in self else []

        # store the data
        id = self._store({'z':z, 'y':y, 'x':x}).inserted_id

        # gather all docs from the collection
        X_tot = []   # the matrix to store all x and z data together
        Y = []
        # TODO: depending on how big the docs are in the collection apart from x,y,z, you might get better performance using find({}, {"x": 1, "y": 1, "z": 1})  (-AJ)
        # TODO: I would need to think whether the concurrency read is really done correctly (-AJ)
        for doc in self.collection.find():
            if all (k in doc for k in ('x','y','z')):  # concurrency read protection
                X_tot.append(doc['x'] + doc['z'])
                Y.append(doc['y'])

        # change Y vector if maximum is desired instead of minimum
        max_on = self['max'] if 'max' in self else False
        Y = [-1 * y if max_on else y for y in Y]

        # extend the dimensions to X features, so that X information can be used in optimization
        X_tot_dims = X_dims + self._Z_dims if z != [] else X_dims

        # run machine learner on Z and X features
        predictor = 'forest_minimize' if not 'predictor' in self else self['predictor']
        if predictor in ['gbrt_minimize', 'random_guess', 'forest_minimize', 'gp_minimize']:
            import skopt
            x_tot_new = getattr(skopt, predictor)(lambda x:0, X_tot_dims, x0=X_tot, y0=Y, n_calls=1,
                                                            n_random_starts=0).x_iters[-1]
        else:
            try:
                predictor_fun = self._deserialize_function(predictor)
                x_tot_new = predictor_fun(X_tot, Y, X_tot_dims)  #  TODO: later, you might want to add optional **args and **kwargs to this as well. For now I think it is fine as is. (-AJ)

            except Exception as E:
                raise ValueError("The custom predictor function {} did not call correctly! \n {}".format(predictor,E))

        # separate 'predicted' X features from the new Z vector
        x_new, z_new = x_tot_new[:len(x)], x_tot_new[len(x):]

        # duplicate checking. makes sure no repeat z vectors are inserted into the turboworks collection
        if 'duplicate_check' in self:
            if self['duplicate_check']:
                if self._is_discrete(X_dims):
                    x_new = self._dupe_check(x, X_dims)
                    # do not worry about mismatch with z_new, as z_new is not used for any calculations

        self._store({'z_new':z_new, 'x_new':x_new}, update=True, id=id)

        # return a new workflow
        return FWAction(additions=wf_creator(x_new, *wf_creator_args, **wf_creator_kwargs),
                        update_spec={'optimization_id':id})

