from pymongo import MongoClient
from pprint import pprint
import numpy as np

"""
Utility functions for managing the turboworks database.

    __init__  : allows custom MongoDB params (ie, store the DB somewhere besides default)
    nuke      : deletes the entire collection
    count     : counts how many documents are in the collection
    query     : queries the DB based on typical pymongo syntax
    get_avg   : get the mean of a parameter
    get_param : get all values of the specified param/output
    get_optima: get the maximum/minimum value of a specified param/output
    back_up   : stores the entire collection in a backup collection
"""

class ManageDB():

    def __init__(self, hostname='localhost', portnum=27017, dbname='turboworks',
                 collection='turboworks'):
        """
        Allows configuration of the TurboWorks DB
        :param hostname: (str) host name of the MongoDB
        :param portnum: (str) port number of the DB
        :param dbname: (str) database name (creates it if nonexistent)
        :param collection: (str) collection name (creates it if nonexistent)
        """
        self.mongo = MongoClient(hostname, portnum)
        self.db = getattr(self.mongo,dbname)
        self.collection = getattr(self.db,collection)
        self.collection_string = collection

    def nuke(self):
        """
        deletes all data in the TurboWorks DB collection (TurboWorks_collection)
        :return num_deleted: (int) number of documents deleted from the database
        """
        docs_removed = self.collection.delete_many({})
        num_deleted = docs_removed.deleted_count
        try:
            print 'Documents removed:         ', num_deleted
        except:
            print('Documents removed:         ', num_deleted)
        print('Documents remaining:        0')
        return num_deleted

    def count(self):
        """
        counts documents in the TurboWorks DB collection (TurboWorks_collection)
        :return cursor.count(): (int) the total number of documents in the collection
        """
        cursor = self.collection.find()
        print('\nNumber of documents:       ', cursor.count())
        return cursor.count()

    def query(self, querydict=None, print_to_console = False):
        """
        queries documents via PyMongo's find()

        :param print_to_console: (boolean) determine whether all found matching docs should be
        printed to the console

        :param querydict: (dictionary) a dictionary query entry compatible with pymongo syntax

        :return docs: (list) a list of all documents matching the query
        """
        if querydict is None:
            querydict = {}
        cursor = self.collection.find(querydict)
        print('Documents matching:        ', cursor.count())
        print('Documents:')

        if print_to_console:
            for document in cursor:
                    pprint(document)

        docs = [document for document in cursor]
        return docs

    def get_avg(self, var):
        """
        :param var: (string) the variable to be averaged
            example: get_avg("some_output")
        :return average: (int/float) the average of all the var in database
        """
        total_list = []
        cursor = self.collection.find()
        for document in cursor:
            if var in document['input']:
                total_list.append(document['input'][var])
            elif var in document['output']:
                total_list.append(document['output'][var])
            else:
                raise KeyError("The key {} was not found anywhere "
                               "in the {} collection".format(var, self.collection_string))
        average = 0
        if type(total_list[0]) == np.int64 or type(total_list[0]) == int:
            average = int(sum(total_list) / len(total_list))
        elif type(total_list[0]) == np.float64 or type(total_list[0]) == float:
            average = float(sum(total_list) / len(total_list))
        return average

    def get_param(self, var):
        """
        :param var: (string) the variable to be collected

        :return total_list: (list) a list of all the var data in database
        """
        total_list = []
        cursor = self.collection.find()
        for document in cursor:
            if var in document['input']:
                total_list.append(document['input'][var])
            elif var in document['output']:
                total_list.append(document['output'][var])
            else:
                raise KeyError("The key {} was not found anywhere "
                               "in the {} collection".format(var, self.collection_string))
        return total_list

    def get_optima(self, var, min_or_max='min'):
        """
        :param output_var: a string representing the variable you want the optimum for
        :param min_or_max: 'min' finds minimum (default), 'max' finds maximum
        :return: maximum/minimum value
        """
        min = None
        max = None
        optima_params = {}
        cursor = self.collection.find()
        for document in cursor:
            if var in document['input']:
                if min_or_max == 'min':
                    if min != None:
                        if document['input'][var] < min:
                            min = document['input'][var]
                            optima_params = document['input']
                    elif min == None:
                        min = document['input'][var]
                        optima_params = document['input']
                elif min_or_max == 'max':
                    if max != None:
                        if document['input'][var] >= max:
                            max = document['input'][var]
                            optima_params = document['input']
                    elif max == None:
                        max = document['input'][var]
                        optima_params = document['input']
                else:
                    print("Invalid option for min_or_max \nUsing minimum")
                    self.get_optima(var)
            elif var in document['output']:
                if min_or_max == 'min':
                    if min != None:
                        if document['output'][var] < min:
                            min = document['output'][var]
                            optima_params = document['input']
                    elif min == None:
                        min = document['output'][var]
                        optima_params = document['input']
                elif min_or_max == 'max':
                    if max != None:
                        if document['output'][var] >= max:
                            max = document['output'][var]
                            optima_params = document['input']
                    elif max == None:
                        max = document['output'][var]
                        optima_params = document['input']
                else:
                    print("Invalid option for min_or_max \nUsing minimum")
                    self.get_optima(var)
            else:
                raise KeyError("The key {} was not found anywhere "
                               "in the {} collection".format(var, self.collection_string))
        if min_or_max == 'max':
            return (max, optima_params)
        elif min_or_max == 'min':
            return (min, optima_params)
        else:
            print("Invalid option for min_or_max \nUsing minimum")
            self.get_optima(var)

    def back_up(self, hostname='localhost', portnum=27017, dbname='turboworks',
                collection='backup'):
        """
        Transfers all data from the TurboWorks DB to another DB
        :param hostname: (str) host name of the MongoDB
        :param portnum: (str) port number of the DB
        :param dbname: (str) database name (creates it if nonexistent)
        :param collection: (str) collection name (creates it if nonexistent)
        """
        cursor = self.collection.find()
        backup_mongo = MongoClient(hostname, portnum)
        backup_db = getattr(backup_mongo, dbname)
        backup_collection = getattr(backup_db, collection)
        backup_collection_string = collection

        print("Beginning storage.")
        for document in cursor:
            backup_collection.insert_one(document)

        print("Ended storage in DB {}".format(backup_collection_string))