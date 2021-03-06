from _threading import Lock

import Jython_tasks
from Cb_constants import CbServer


class BucketStats(object):
    def __init__(self):
        # Used for plotting Bucket status table
        self.itemCount = 0
        self.diskUsed = 0
        self.memUsed = 0
        self.ram = 0
        self.manifest_uid = 0
        self.expected_item_count = 0
        self.mutex = Lock()
        # Used to manage Bucket stats task
        self.stats_task = {"count": 0,
                           "object": None,
                           "lock": Lock()}

    def increment_manifest_uid(self):
        """
        Increments the manifest UID of bucket object.
        :return: None
        """
        # Uses Lock to safely update the uid during threaded execution
        self.mutex.acquire()
        self.manifest_uid += 1
        self.mutex.release()

    def manage_task(self, operation, task_manager,
                    cluster=None, bucket=None,
                    monitor_stats=list(), sleep=1):
        task_pkg = Jython_tasks.task
        if operation == "start":
            self.stats_task["lock"].acquire()
            if self.stats_task["object"] is None:
                self.stats_task["object"] = task_pkg.PrintBucketStats(
                    cluster, bucket,
                    monitor_stats=monitor_stats,
                    sleep=sleep)
                task_manager.add_new_task(self.stats_task["object"])
            self.stats_task["count"] += 1
            self.stats_task["lock"].release()
        elif operation == "stop":
            self.stats_task["lock"].acquire()
            if self.stats_task["count"] == 1:
                self.stats_task["object"].end_task()
                task_manager.get_task_result(self.stats_task["object"])
                self.stats_task["object"] = None
            self.stats_task["count"] -= 1
            self.stats_task["lock"].release()


class Scope(object):
    def __init__(self, scope_spec=dict()):
        self.name = scope_spec.get("name")
        self.collections = dict()

        # Meta data for test case validation
        self.is_dropped = False
        self.recreated = 0

    def __str__(self):
        return self.name

    def get_dict_object(self):
        return {"name": self.name}

    @staticmethod
    def recreated(scope_obj, scope_spec):
        # Update meta fields
        scope_obj.is_dropped = False
        scope_obj.recreated += 1


class Collection(object):
    def __init__(self, collection_spec=dict()):
        self.name = collection_spec.get("name")
        self.num_items = collection_spec.get("num_items", 0)
        self.maxTTL = collection_spec.get("maxTTL", 0)

        # Meta data for test case validation
        self.is_dropped = False
        self.recreated = 0
        # Meta to preserve inserted doc index to support further CRUDs
        self.doc_index = (0, 0)
        self.sub_doc_index = (0, 0)

    def __str__(self):
        return self.name

    def get_dict_object(self):
        return {"name": self.name, "maxTTL": self.maxTTL}

    @staticmethod
    def flushed(collection_obj):
        collection_obj.num_items = 0
        collection_obj.doc_index = (0, 0)
        collection_obj.sub_doc_index = (0, 0)

    @staticmethod
    def recreated(collection_obj, collection_spec):
        collection_obj.num_items = collection_spec.get("num_items", 0)
        collection_obj.maxTTL = collection_spec.get("maxTTL", 0)

        # Update meta fields
        collection_obj.is_dropped = False
        collection_obj.recreated += 1
        collection_obj.doc_index = (0, 0)


class Bucket(object):
    name = "name"
    ramQuotaMB = "ramQuotaMB"
    bucketType = "bucketType"
    replicaNumber = "replicaNumber"
    replicaServers = "replicaServers"
    evictionPolicy = "evictionPolicy"
    priority = "priority"
    flushEnabled = "flushEnabled"
    conflictResolutionType = "conflictResolutionType"
    storageBackend = "storageBackend"
    maxTTL = "maxTTL"
    replicaIndex = "replicaIndex"
    threadsNumber = "threadsNumber"
    compressionMode = "compressionMode"
    uuid = "uuid"

    class Type(object):
        EPHEMERAL = "ephemeral"
        MEMBASE = "membase"
        MEMCACHED = "memcached"

    class ReplicaNum(object):
        ZERO = 0
        ONE = 1
        TWO = 2
        THREE = 3

    class EvictionPolicy(object):
        FULL_EVICTION = "fullEviction"
        NO_EVICTION = "noEviction"
        NRU_EVICTION = "nruEviction"
        VALUE_ONLY = "valueOnly"

    class ConflictResolution(object):
        SEQ_NO = "seqno"
        TIMESTAMP_BASED = "lww"

    class CompressionMode(object):
        ACTIVE = "active"
        PASSIVE = "passive"
        OFF = "off"

    class Priority(object):
        LOW = 3
        HIGH = 8

    class FlushBucket(object):
        DISABLED = 0
        ENABLED = 1

    class vBucket:
        def __init__(self):
            self.master = ''
            self.replica = []
            self.id = -1

    class StorageBackend(object):
        magma = "magma"
        couchstore = "couchstore"

    class DurabilityLevel(object):
        MAJORITY = "MAJORITY"
        MAJORITY_AND_PERSIST_TO_ACTIVE = "MAJORITY_AND_PERSIST_TO_ACTIVE"
        PERSIST_TO_MAJORITY = "PERSIST_TO_MAJORITY"

    def __init__(self, new_params=dict()):
        # Default values based on Couchbase document,
        # docs.couchbase.com/server/current/rest-api/rest-bucket-create.html

        self.name = new_params.get(Bucket.name, "default")
        self.bucketType = new_params.get(Bucket.bucketType,
                                         Bucket.Type.MEMBASE)
        self.replicaNumber = new_params.get(Bucket.replicaNumber,
                                            Bucket.ReplicaNum.ONE)
        self.replicaServers = new_params.get(Bucket.replicaServers, [])
        self.ramQuotaMB = new_params.get(Bucket.ramQuotaMB, 100)
        self.replicaIndex = new_params.get(Bucket.replicaIndex, 1)
        self.storageBackend = new_params.get(Bucket.storageBackend,
                                             Bucket.StorageBackend.couchstore)
        self.priority = new_params.get(Bucket.priority, Bucket.Priority.LOW)
        self.uuid = None
        self.conflictResolutionType = \
            new_params.get(Bucket.conflictResolutionType,
                           Bucket.ConflictResolution.SEQ_NO)
        self.maxTTL = new_params.get(Bucket.maxTTL, 0)
        self.flushEnabled = new_params.get(Bucket.flushEnabled,
                                           Bucket.FlushBucket.DISABLED)
        self.compressionMode = new_params.get(
            Bucket.compressionMode,
            Bucket.CompressionMode.PASSIVE)

        if self.bucketType == Bucket.Type.EPHEMERAL:
            self.evictionPolicy = new_params.get(
                Bucket.evictionPolicy,
                Bucket.EvictionPolicy.NO_EVICTION)
            if self.evictionPolicy not in [Bucket.EvictionPolicy.NRU_EVICTION,
                                           Bucket.EvictionPolicy.NO_EVICTION]:
                self.evictionPolicy = Bucket.EvictionPolicy.NO_EVICTION
        else:
            self.evictionPolicy = new_params.get(
                Bucket.evictionPolicy,
                Bucket.EvictionPolicy.VALUE_ONLY)

        self.nodes = None
        self.stats = BucketStats()
        self.servers = list()
        self.vbuckets = list()
        self.forward_map = list()
        self.scopes = dict()

        # Create default scope-collection association
        scope = Scope({"name": CbServer.default_scope})
        collection = Collection({"name": CbServer.default_collection})
        scope.collections[CbServer.default_collection] = collection
        self.scopes[CbServer.default_scope] = scope

    def __str__(self):
        return self.name

    @staticmethod
    def get_params():
        param_list = list()
        for param in vars(Bucket).keys():
            if not (param.startswith("_")
                    or callable(getattr(Bucket, param))):
                param_list.append(param)
        return param_list


class TravelSample(Bucket):
    def __init__(self):
        bucket_param = dict()
        bucket_param["name"] = "travel-sample"
        super(TravelSample, self).__init__(bucket_param)
        self.stats.expected_item_count = 31591


class BeerSample(Bucket):
    def __init__(self):
        bucket_param = dict()
        bucket_param["name"] = "beer-sample"
        super(BeerSample, self).__init__(bucket_param)
        self.stats.expected_item_count = 7303


class GamesimSample(Bucket):
    def __init__(self):
        bucket_param = dict()
        bucket_param["name"] = "gamesim-sample"
        super(GamesimSample, self).__init__(bucket_param)
        self.stats.expected_item_count = 586
