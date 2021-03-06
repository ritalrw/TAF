from com.couchbase.client.java import *
from com.couchbase.client.java.json import *
from com.couchbase.client.java.query import *
from membase.api.rest_client import RestConnection, RestHelper
from TestInput import TestInputSingleton
import random
from BucketLib.BucketOperations import BucketHelper
from remote.remote_util import RemoteMachineShellConnection
from error_simulation.cb_error import CouchbaseError
from collections_helper.collections_spec_constants import MetaConstants, \
    MetaCrudParams
from bucket_utils.bucket_ready_functions import BucketUtils
from Cb_constants import CbServer
from bucket_collections.collections_base import CollectionBase


class volume(CollectionBase):
    # will add the __init__ functions after the test has been stabilised
    def setUp(self):
        self.input = TestInputSingleton.input
        self.input.test_params.update({"default_bucket":False})
        super(volume, self).setUp()
        self.rest = RestConnection(self.servers[0])
        self.available_servers = list()
        self.available_servers = self.cluster.servers[self.nodes_init:]
        self.iterations = self.input.param("iterations", 2)
        self.vbucket_check = self.input.param("vbucket_check", True)
        self.data_load_spec = self.input.param("data_load_spec", "volume_test_load")

    # Stopping and restarting the memcached process
    def stop_process(self):
        target_node = self.servers[2]
        remote = RemoteMachineShellConnection(target_node)
        error_sim = CouchbaseError(self.log, remote)
        error_to_simulate = "stop_memcached"
        # Induce the error condition
        error_sim.create(error_to_simulate)
        self.sleep(20, "Wait before reverting the error condition")
        # Revert the simulated error condition and close the ssh session
        error_sim.revert(error_to_simulate)
        remote.disconnect()

    def rebalance(self, nodes_in=0, nodes_out=0):
        servs_in = random.sample(self.available_servers, nodes_in)

        self.nodes_cluster = self.cluster.nodes_in_cluster[:]
        self.nodes_cluster.remove(self.cluster.master)
        servs_out = random.sample(self.nodes_cluster, nodes_out)

        if nodes_in == nodes_out:
            self.vbucket_check = False

        rebalance_task = self.task.async_rebalance(
            self.cluster.servers[:self.nodes_init], servs_in, servs_out, check_vbucket_shuffling=self.vbucket_check)

        self.available_servers = [servs for servs in self.available_servers if servs not in servs_in]
        self.available_servers += servs_out

        self.cluster.nodes_in_cluster.extend(servs_in)
        self.cluster.nodes_in_cluster = list(set(self.cluster.nodes_in_cluster) - set(servs_out))
        return rebalance_task

    def rebalance_validation(self, tasks_info, rebalance_task):
        if not rebalance_task.result:
            for task, _ in tasks_info.items():
                self.task.jython_task_manager.get_task_result(task)
            self.fail("Rebalance Failed")

    def data_load_collection(self):
        doc_loading_spec = \
            self.bucket_util.get_crud_template_from_package(self.data_load_spec)
        task = self.bucket_util.run_scenario_from_spec(self.task,
                                                self.cluster,
                                                self.bucket_util.buckets,
                                                doc_loading_spec,
                                                mutation_num=0,
                                                async_load=True)
        return task

    def wait_for_async_data_load_to_complete(self, task):
        self.task.jython_task_manager.get_task_result(task)
        if task.result is False:
            self.fail("Doc_loading failed")

    def data_validation_collection(self):
        self.bucket_util._wait_for_stats_all_buckets()
        self.bucket_util.validate_docs_per_collections_all_buckets()


    def test_volume_taf(self):
        self.loop = 0
        while self.loop<self.iterations:
            self.log.info("Finished steps 1-4 successfully in setup")
            self.log.info("Step 5: Rebalance in with Loading of docs")
            rebalance_task = self.rebalance(nodes_in = 1, nodes_out = 0)
            task = self.data_load_collection()
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()
            self.bucket_util.print_bucket_stats()
            #########################################################################################################################
            self.log.info("Step 6: Rebalance Out with Loading of docs")
            rebalance_task = self.rebalance(nodes_in = 0, nodes_out = 1)
            task = self.data_load_collection()
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()
            self.bucket_util.print_bucket_stats()
            #######################################################################################################################
            self.log.info("Step 7: Rebalance In_Out with Loading of docs")
            rebalance_task = self.rebalance(nodes_in = 2, nodes_out = 1)
            task = self.data_load_collection()
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()
            self.bucket_util.print_bucket_stats()
            ########################################################################################################################
            self.log.info("Step 8: Swap with Loading of docs")
            rebalance_task = self.rebalance(nodes_in=1, nodes_out=1)
            task = self.data_load_collection()
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()
            self.tasks = []
            self.bucket_util.print_bucket_stats()
            ########################################################################################################################
            self.log.info("Step 9: Updating the bucket replica to 2")
            bucket_helper = BucketHelper(self.cluster.master)
            for i in range(len(self.bucket_util.buckets)):
                bucket_helper.change_bucket_props(
                    self.bucket_util.buckets[i], replicaNumber=2)
            rebalance_task = self.rebalance(nodes_in =1, nodes_out= 0)
            task = self.data_load_collection()
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()
            self.bucket_util.print_bucket_stats()
            ########################################################################################################################
            if "ephemeral" in self.bucket_type:
                self.log.info("No Memcached kill for epehemral bucket")
            else:
                self.log.info("Step 10: Stopping and restarting memcached process")
                rebalance_task = self.task.async_rebalance(self.cluster.servers, [], [])
                task = self.data_load_collection()
                self.task.jython_task_manager.get_task_result(rebalance_task)
                self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
                self.stop_process()
                self.wait_for_async_data_load_to_complete(task)
                self.data_validation_collection()
                self.bucket_util.print_bucket_stats()
            ########################################################################################################################
            self.log.info("Step 11: Failover a node and RebalanceOut that node with loading in parallel")
            self.std_vbucket_dist = self.input.param("std_vbucket_dist", None)
            std = self.std_vbucket_dist or 1.0

            prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            self.sleep(10)

            disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
                self.cluster.nodes_in_cluster, self.bucket_util.buckets, path=None)

            self.rest = RestConnection(self.cluster.master)
            self.nodes = self.cluster_util.get_nodes(self.cluster.master)
            self.chosen = self.cluster_util.pick_nodes(self.cluster.master, howmany=1)

            # Mark Node for failover
            task = self.data_load_collection()
            self.success_failed_over = self.rest.fail_over(self.chosen[0].id, graceful=False)

            self.sleep(300)
            self.nodes = self.rest.node_statuses()
            self.rest.rebalance(otpNodes=[node.id for node in self.nodes], ejectedNodes=[self.chosen[0].id])
            # self.sleep(600)
            self.assertTrue(self.rest.monitorRebalance(stop_if_loop=True), msg="Rebalance failed")

            servs_out = [node for node in self.cluster.servers if node.ip == self.chosen[0].ip]
            self.cluster.nodes_in_cluster = list(set(self.cluster.nodes_in_cluster) - set(servs_out))
            self.available_servers += servs_out
            self.sleep(10)

            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()

            self.bucket_util.compare_failovers_logs(prev_failover_stats, self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            self.sleep(10)

            self.bucket_util.data_analysis_active_replica_all(
                disk_active_dataset, disk_replica_dataset,
                self.cluster.servers[:self.nodes_in + self.nodes_init],
                self.bucket_util.buckets, path=None)
            nodes = self.cluster_util.get_nodes_in_cluster(self.cluster.master)
            self.bucket_util.vb_distribution_analysis(
                servers=nodes, buckets=self.bucket_util.buckets,
                num_replicas=2,
                std=std, total_vbuckets=self.cluster_util.vbuckets)
            self.sleep(10)
            self.tasks = []
            rebalance_task = self.rebalance(nodes_in=1, nodes_out=0)
            # self.sleep(600)
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.bucket_util.print_bucket_stats()
            ########################################################################################################################
            self.log.info("Step 12: Failover a node and FullRecovery that node")

            self.std_vbucket_dist = self.input.param("std_vbucket_dist", None)
            std = self.std_vbucket_dist or 1.0

            prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            self.sleep(10)

            disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
                self.cluster.nodes_in_cluster, self.bucket_util.buckets, path=None)

            self.rest = RestConnection(self.cluster.master)
            self.nodes = self.cluster_util.get_nodes(self.cluster.master)
            self.chosen = self.cluster_util.pick_nodes(self.cluster.master, howmany=1)

            task = self.data_load_collection()
            # Mark Node for failover
            self.success_failed_over = self.rest.fail_over(self.chosen[0].id, graceful=False)

            self.sleep(300)

            # Mark Node for full recovery
            if self.success_failed_over:
                self.rest.set_recovery_type(otpNode=self.chosen[0].id, recoveryType="full")


            rebalance_task = self.task.async_rebalance(
                self.cluster.servers[:self.nodes_init], [], [])
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.sleep(10)

            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()

            self.bucket_util.compare_failovers_logs(prev_failover_stats, self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            self.sleep(10)

            self.bucket_util.data_analysis_active_replica_all(
                disk_active_dataset, disk_replica_dataset,
                self.cluster.servers[:self.nodes_in + self.nodes_init],
                self.bucket_util.buckets, path=None)
            nodes = self.cluster_util.get_nodes_in_cluster(self.cluster.master)
            self.bucket_util.vb_distribution_analysis(
                servers=nodes, buckets=self.bucket_util.buckets,
                num_replicas=2,
                std=std, total_vbuckets=self.cluster_util.vbuckets)
            self.sleep(10)
            self.tasks = []
            self.bucket_util.print_bucket_stats()
            ########################################################################################################################
            self.log.info("Step 13: Failover a node and DeltaRecovery that node with loading in parallel")

            self.std_vbucket_dist = self.input.param("std_vbucket_dist", None)
            std = self.std_vbucket_dist or 1.0

            prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            self.sleep(10)

            disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
                self.cluster.nodes_in_cluster, self.bucket_util.buckets, path=None)

            self.rest = RestConnection(self.cluster.master)
            self.nodes = self.cluster_util.get_nodes(self.cluster.master)
            self.chosen = self.cluster_util.pick_nodes(self.cluster.master, howmany=1)

            task = self.data_load_collection()
            # Mark Node for failover
            self.success_failed_over = self.rest.fail_over(self.chosen[0].id, graceful=False)

            self.sleep(300)
            if self.success_failed_over:
                self.rest.set_recovery_type(otpNode=self.chosen[0].id, recoveryType="delta")

            rebalance_task = self.task.async_rebalance(
                self.cluster.servers[:self.nodes_init], [], [])

            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.sleep(10)

            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()

            self.bucket_util.compare_failovers_logs(prev_failover_stats, self.cluster.nodes_in_cluster, self.bucket_util.buckets)
            self.sleep(10)

            self.bucket_util.data_analysis_active_replica_all(
                disk_active_dataset, disk_replica_dataset,
                self.cluster.servers[:self.nodes_in + self.nodes_init],
                self.bucket_util.buckets, path=None)
            nodes = self.cluster_util.get_nodes_in_cluster(self.cluster.master)
            self.bucket_util.vb_distribution_analysis(
                servers=nodes, buckets=self.bucket_util.buckets,
                num_replicas=2,
                std=std, total_vbuckets=self.cluster_util.vbuckets)
            self.bucket_util.print_bucket_stats()
        ########################################################################################################################
            self.log.info("Step 14: Updating the bucket replica to 1")
            bucket_helper = BucketHelper(self.cluster.master)
            for i in range(len(self.bucket_util.buckets)):
                bucket_helper.change_bucket_props(
                    self.bucket_util.buckets[i], replicaNumber=1)
            rebalance_task = self.task.async_rebalance(self.cluster.servers, [], [])
            task = self.data_load_collection()
            self.task.jython_task_manager.get_task_result(rebalance_task)
            self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            self.wait_for_async_data_load_to_complete(task)
            self.data_validation_collection()
            self.tasks = []
            self.bucket_util.print_bucket_stats()
        ########################################################################################################################
            self.log.info("Step 15: Flush the bucket and start the entire process again")
            self.loop += 1
            if self.loop < self.iterations:
                # Flush the bucket
                self.bucket_util.flush_all_buckets(self.cluster.master)
                self.sleep(10)
                if len(self.cluster.nodes_in_cluster) > self.nodes_init:
                    self.nodes_cluster = self.cluster.nodes_in_cluster[:]
                    self.nodes_cluster.remove(self.cluster.master)
                    servs_out = random.sample(self.nodes_cluster, int(len(self.cluster.nodes_in_cluster) - self.nodes_init))
                    rebalance_task = self.task.async_rebalance(
                        self.cluster.servers[:self.nodes_init], [], servs_out)
                    self.task.jython_task_manager.get_task_result(rebalance_task)
                    self.available_servers += servs_out
                    self.cluster.nodes_in_cluster = list(set(self.cluster.nodes_in_cluster) - set(servs_out))
                    self.assertTrue(rebalance_task.result, "rebalance failed, stuck or did not complete")
            else:
                self.log.info("Volume Test Run Complete")
        ############################################################################################################################
